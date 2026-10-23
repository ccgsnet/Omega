import json
import os
import re
import subprocess
from collections import deque
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

try:
    from src.logger import get_logger
except ModuleNotFoundError:  # running this file directly as a script
    from logger import get_logger

logger = get_logger(__name__)

TS_RE = re.compile(r'^\("(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})"')
STATIC_LLM_COMMANDS = {
    "append-file",
    "believe",
    "beliefs",
    "das-forget",
    "das-recall",
    "das-store",
    "episodes",
    "learn",
    "metta",
    "pin",
    "query",
    "read-file",
    "remember",
    "search",
    "send",
    "shell",
    "unlearn",
    "version",
    "websearch",
    "write-file",
    "get-io-policy",
    "write-file-b64",
    "delete-file",
}
LLM_COMMANDS = set(STATIC_LLM_COMMANDS)
TWO_ARG_COMMANDS = {
    "write-file",
    "append-file",
    "write-file-b64"
}


def add_llm_command(command):
    LLM_COMMANDS.add(str(command))
    return True


def remove_llm_command(command):
    command = str(command)
    if command not in STATIC_LLM_COMMANDS:
        LLM_COMMANDS.discard(command)
    return True

def extract_timestamp(line):
    m = TS_RE.search(line)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
    except ValueError as e:
        logger.error(f"Line does not carry a parsable timestamp: {e}")
        return None

def around_time(needle_time_str, k):
    needle_time_str = needle_time_str.replace(r'\"', '').replace('"', '').strip()
    filename = "repos/Omega/memory/history.metta"
    target = datetime.strptime(needle_time_str, "%Y-%m-%d %H:%M:%S")
    best_lineno = None
    best_line = None
    best_diff = None
    buffer = []
    best_idx = None
    with open(filename, "r", encoding="utf-8", errors="replace") as f:
        for lineno, line in enumerate(f, 1):
            buffer.append((lineno, line))
            ts = extract_timestamp(line)
            if ts is None:
                continue
            diff = abs((ts - target).total_seconds())
            if best_diff is None or diff < best_diff:
                best_diff = diff
                best_lineno = lineno
                best_line = line
                best_idx = len(buffer) - 1
    if best_lineno is None:
        return
    start = max(0, best_idx - k)
    end = min(len(buffer), best_idx + k + 1)
    ret = ""
    for lineno, line in buffer[start:end]:
        ret += f"{lineno}:{line}"
    return ret

def quote_arg(x):
    if x.startswith('"') and x.endswith('"') and "\n" not in x:
        return x
    else:
        return json.dumps(x, ensure_ascii=False)

UNKNOWN_SKILL_REMINDER = (
    '(ALERT_FAILED UNKNOWN_SKILL_CALL '
    '"Answer with skill lines only. A user reply is the send skill followed by the reply. Do not send a status message.")'
)


def unknown_skill_only(response):
    """True when the parsed reply contains no real skill call."""
    text = response or ""
    if "UNKNOWN_SKILL_CALL" not in text:
        return False
    return not any(f"({cmd} " in text or f"({cmd})" in text for cmd in LLM_COMMANDS)


def unknown_skill_reminder():
    return UNKNOWN_SKILL_REMINDER


def skill_names(response):
    """Names of the top-level skill calls in a balance_parentheses result."""
    names, depth, in_str, escaped, start = [], 0, False, False, None
    for i, ch in enumerate(response or ""):
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
        elif ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
            if depth == 2:
                start = i + 1
        elif ch == ")":
            if depth == 2 and start is not None:
                names.append(response[start:i].split(maxsplit=1)[0] if response[start:i].strip() else "")
                start = None
            depth -= 1
        elif ch == " " and depth == 2 and start is not None:
            names.append(response[start:i])
            start = None
    return names


REPLY_SAFE_SKILLS = ("send", "pin", "learn", "unlearn", "remember")


def answered_user(response):
    """True when the reply sends content and runs no skill whose result is still unseen."""
    names = skill_names(response)
    return '(send "' in (response or "") and all(n in REPLY_SAFE_SKILLS for n in names)


def is_send_call(command):
    """True when one skill call, as printed by repr, is a send."""
    return skill_names(f"({command})") == ["send"]


FACT_SELF_WORDS = {"i", "me", "my", "mine", "myself", "user"}
FACT_STOPWORDS = {
    "a", "an", "and", "are", "about", "can", "did", "do", "does", "for", "from", "have", "has",
    "how", "is", "it", "its", "know", "many", "much", "me", "my", "of", "on", "or", "please", "tell", "that",
    "the", "this", "to", "was", "were", "what", "when", "where", "which", "who", "why", "with",
    "you", "your",
}
SAFE_STRING_MARKERS = ("_quote_", "_newline_", "_apostrophe_")


def _plain_text(text):
    text = str(text or "")
    for marker in SAFE_STRING_MARKERS:
        text = text.replace(marker, " ")
    return text


def fact_token(word):
    """Lowercase MeTTa symbol for one fact part: no spaces, parentheses, quotes or variables."""
    token = re.sub(r"[^\w./@+-]+", "_", str(word).strip().lower())
    return re.sub(r"_+", "_", token).strip("_")


def metta_string(text):
    """MeTTa string literal. sread has no \\u escapes, so non-ASCII text stays as is."""
    return json.dumps(text, ensure_ascii=False)


def message_speaker(message):
    """Nick of the sender of the latest 'nick: text' message, or empty."""
    last = _plain_text(message).split(" | ")[-1]
    nick, sep, _ = last.partition(":")
    nick = nick.strip()
    return fact_token(nick) if sep and nick and " " not in nick else ""


FACT_ARTICLES = {"a", "an", "the"}
# Longest subject, relation and value accepted, in words. A longer field means
# a sentence was passed instead of one fact about one named thing.
FACT_MAX_WORDS = (4, 3, 6)


def _fact_words(field):
    return [token for token in (fact_token(word) for word in field.split()) if token]


def _fact_fields(text, count, message):
    """The '|'-separated fields of a fact, or None when they do not form one short fact."""
    fields = [_fact_words(field) for field in _plain_text(text).split("|")]
    if len(fields) != count or not all(fields):
        return None
    if any(len(words) > limit for words, limit in zip(fields, FACT_MAX_WORDS)):
        return None
    subject = fields[0]
    while len(subject) > 1 and subject[0] in FACT_ARTICLES:
        subject = subject[1:]
    if subject == [] or (len(subject) == 1 and subject[0] in FACT_ARTICLES):
        return None
    if len(subject) == 1 and subject[0] in FACT_SELF_WORDS:
        subject = [message_speaker(message) or "user"]
    return [" ".join(subject), "_".join(fields[1])] + [" ".join(words) for words in fields[2:]]


def _strings(*tokens):
    return f"({' '.join(metta_string(token) for token in tokens)})"


def parse_fact(text, message=""):
    """'subject | relation | value' as '("subject" relation "value")', or '()' when it is not one short fact.

    The relation is a symbol and the value a string, as a column name and its
    literal value are in DAS Sql2AtomsMapper predicates.
    """
    fields = _fact_fields(text, 3, message)
    if fields is None:
        return "()"
    subject, relation, value = fields
    return f"({metta_string(subject)} {relation} {metta_string(value)})"


def parse_fact_key(text, message=""):
    """'subject | relation' as '("subject" relation)', or '()' when malformed."""
    fields = _fact_fields(text, 2, message)
    if fields is None:
        return "()"
    subject, relation = fields
    return f"({metta_string(subject)} {relation})"


FACT_EXTRACTION_PROMPT = (
    "Extract the lasting facts the speaker states as true about one named person or thing in the message below.\n"
    "Write one line per fact: FACT subject | relation | value\n"
    "subject: the person or thing, at most 4 words, I for the speaker. "
    "relation: at most 3 words. value: at most 6 words.\n"
    "Examples:\n"
    "My favorite color is blue. -> FACT I | favorite color | blue\n"
    "Brasilia is the capital of Brazil. -> FACT Brazil | capital | Brasilia\n"
    "I live in Belo Horizonte and my dog is Rex. -> FACT I | lives in | Belo Horizonte\nFACT I | dog | Rex\n"
    "Cities with more than 500k people are big cities. -> NONE (a general rule, not about one thing)\n"
    "What is my favorite color? -> NONE (a question)\n"
    "Questions, requests, commands and general rules are not facts. If there is no fact, write NONE.\n"
    "MESSAGE: "
)


def _latest_text(message):
    last = _plain_text(message).split(" | ")[-1]
    return last.partition(":")[2].strip() if message_speaker(message) else last.strip()


def fact_extraction_prompt(message):
    return FACT_EXTRACTION_PROMPT + _latest_text(message)


def extracted_facts(reply):
    """'subject | relation | value' strings from FACT entries of an extraction reply."""
    text = re.sub(r"[\"\\`*]", "", str(reply or ""))
    facts = []
    for line in text.splitlines():
        for part in re.split(r"\bFACT\s+", line)[1:]:
            fact = re.sub(r"\(.*?\)", "", part.split("->")[0]).strip(" ,;.")
            if fact:
                facts.append(fact)
    return _strings(*facts)


FACT_VERB_RELATIONS = ("is", "are", "has", "have", "likes", "loves", "hates", "owns", "lives", "works")
SECOND_PERSON_VERBS = {"is": "are", "has": "have"}


def _second_person(verb):
    return SECOND_PERSON_VERBS.get(verb, verb[:-1] if verb.endswith("s") and verb != "is" else verb)


def _fact_sentence(subject, relation, value, speaker):
    relation, value = relation.replace("_", " "), value.replace("_", " ")
    verb, _, rest = relation.partition(" ")
    if verb in FACT_VERB_RELATIONS:
        if subject == speaker:
            return " ".join(part for part in ("you", _second_person(verb), rest, value) if part)
        return f"{subject} {relation} {value}"
    owner = "your" if subject == speaker else f"{subject}'s"
    return f"{owner} {relation} is {value}"


def describe_facts(facts, message=""):
    """Recalled ("subject" relation "value") triples as sentences addressed to the message sender."""
    speaker = message_speaker(message)
    triples = re.findall(r'\(\s*"([^"]*)"\s+([^\s()"]+)\s+"([^"]*)"\s*\)', str(facts or ""))
    if not triples:
        return "none"
    return "; ".join(_fact_sentence(subject, relation, value, speaker)
                     for subject, relation, value in triples) + "."


def fact_query_keys(message, limit=3):
    """Concept names to look up for a message: the speaker, then up to limit content words, names first."""
    speaker = message_speaker(message)
    words = re.findall(r"[^\W_][\w./@+-]*", _latest_text(message))
    candidates = []
    for word in sorted(words, key=lambda word: not word[0].isupper()):
        key = fact_token(word)
        if len(key) >= 3 and key not in FACT_STOPWORDS and key != speaker and key not in candidates:
            candidates.append(key)
    return _strings(*([speaker] if speaker else []), *candidates[:int(limit)])

def starts_command_line(line):
    s = line.lstrip()
    if not s:
        return False
    # allow "(send ...)" as command start too
    if s.startswith("("):
        s = s[1:].lstrip()
    if not s:
        return False
    first = s.split(maxsplit=1)[0].rstrip(")")
    return first in LLM_COMMANDS

def split_command_blocks(s):
    blocks = []
    cur = []
    for raw in s.splitlines():
        if not raw.strip():
            if cur:
                cur.append(raw)
            continue
        if starts_command_line(raw) and cur:
            blocks.append("\n".join(cur).strip())
            cur = [raw]
        else:
            cur.append(raw)
    if cur:
        blocks.append("\n".join(cur).strip())
    return blocks

def balance_parentheses(s):
    s = s.replace("_quote_", '"').replace("_newline_", "\n")
    sexprs = []
    for line in split_command_blocks(s):
        line = line.strip()
        if not line:
            continue
        if line.startswith("(-"):
            line = "(pin " + line[2:]
        elif line.startswith("-"):
            line = "pin " + line[1:]
        # remove one outer (...) if present
        if line.startswith("(") and line.endswith(")"):
            line = line[1:-1].strip()
        elif line.startswith("("):
            line = line[1:].strip()
        parts = line.split(maxsplit=1)
        if not parts:
            continue
        cmd = parts[0]
        rest = parts[1].strip() if len(parts) > 1 else ""
        if cmd not in LLM_COMMANDS:
            # Do not let model commentary become a MeTTa expression.  The
            # loop turns this into ALERT_FAILED feedback for the next turn.
            sexprs.append(f"(Error UNKNOWN_SKILL_CALL {quote_arg(line)})")
            continue
        if cmd in TWO_ARG_COMMANDS:
            if not rest:
                sexprs.append(f"({cmd})")
                continue
            # filename is first token unless already quoted
            if rest.startswith('"'):
                end = 1
                escaped = False
                while end < len(rest):
                    ch = rest[end]
                    if ch == '"' and not escaped:
                        break
                    escaped = (ch == '\\' and not escaped)
                    if ch != '\\':
                        escaped = False
                    end += 1
                if end < len(rest) and rest[end] == '"':
                    filename = rest[:end+1]
                    content = rest[end+1:].strip()
                else:
                    filename = quote_arg(rest[1:])
                    content = ""
            else:
                split_rest = rest.split(maxsplit=1)
                filename = quote_arg(split_rest[0])
                content = split_rest[1].strip() if len(split_rest) > 1 else ""
            if content:
                sexprs.append(f"({cmd} {filename} {quote_arg(content)})")
            else:
                sexprs.append(f"({cmd} {filename})")
            continue
        if rest:
            sexprs.append(f"({cmd} {quote_arg(rest)})")
        else:
            sexprs.append(f"({cmd})")
    ret = " ".join(sexprs)
    return "(" + ret + ")"

def normalize_string(x):
    try:
        if isinstance(x, bytes):
            return x.decode("utf-8", errors="ignore")
        return str(x).encode("utf-8", errors="ignore").decode("utf-8", errors="ignore")
    except Exception as e:
        logger.debug(f"Could not normalize value, using its plain string form: {e}")
        return str(x)

def joinPath(parts):
    return os.path.join(*parts)

def projectRootDirectory():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _format_omega_version(version: str) -> str | None:
    version = version.strip()
    if not version:
        return None
    if version.startswith("Omega version="):
        return version
    if version.startswith("Omega "):
        version = version[len("Omega "):]
    return f"Omega version={version}"


def omega_version(repo_root: str | os.PathLike | None = None) -> str:
    """Return the checkout version, falling back to the baked version file."""
    root = Path(repo_root) if repo_root is not None else Path(projectRootDirectory())

    try:
        # Prevent `git -C` from walking up to a parent repository such as /PeTTa.
        if not (root / ".git").exists():
            raise FileNotFoundError
        result = subprocess.run(
            ["git", "-C", str(root), "describe", "--tags", "--dirty", "--always"],
            check=False,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            version = _format_omega_version(result.stdout)
            if version is not None:
                return version
    except (OSError, subprocess.TimeoutExpired):
        pass

    try:
        version = _format_omega_version(
            (root / "version").read_text(encoding="utf-8")
        )
        if version is not None:
            return version
    except OSError:
        pass

    return "Omega unknown"


def test_omega_version():
    with TemporaryDirectory() as directory:
        root = Path(directory)
        assert omega_version(root) == "Omega unknown"

        (root / "version").write_text("v1.2.3-4-g1234567\n", encoding="utf-8")
        assert omega_version(root) == "Omega version=v1.2.3-4-g1234567"

        (root / "version").write_text("Omega v1.2.3\n", encoding="utf-8")
        assert omega_version(root) == "Omega version=v1.2.3"


def test_balance_parenthesis():
    assert balance_parentheses('(write-file test.txt hello world)') == '((write-file "test.txt" "hello world"))'
    assert balance_parentheses('(append-file test.txt hello world)') == '((append-file "test.txt" "hello world"))'
    assert balance_parentheses('(write-file-b64 test.txt aGVsbG8=)') == '((write-file-b64 "test.txt" "aGVsbG8="))'
    assert balance_parentheses('write-file-b64 test.txt aGVsbG8=') == '((write-file-b64 "test.txt" "aGVsbG8="))'
    assert balance_parentheses('(write-file "test.txt" hello world)') == '((write-file "test.txt" "hello world"))'
    assert balance_parentheses('(write-file "test.txt" "hello world")') == '((write-file "test.txt" "hello world"))'
    assert balance_parentheses('(write-file test.txt "hello world")') == '((write-file "test.txt" "hello world"))'
    assert balance_parentheses('(send test.xt hello world)') == '((send "test.xt hello world"))'
    assert balance_parentheses('write-file test.txt hello world') == '((write-file "test.txt" "hello world"))'
    assert balance_parentheses('append-file test.txt hello world') == '((append-file "test.txt" "hello world"))'
    assert balance_parentheses('write-file "test.txt" hello world') == '((write-file "test.txt" "hello world"))'
    assert balance_parentheses('write-file "test.txt" "hello world"') == '((write-file "test.txt" "hello world"))'
    assert balance_parentheses('write-file test.txt "hello world"') == '((write-file "test.txt" "hello world"))'
    assert balance_parentheses('send test.xt hello world') == '((send "test.xt hello world"))'
    assert balance_parentheses('send Here are the planets:\n1. Mercury\n2. Venus') == '((send "Here are the planets:\\n1. Mercury\\n2. Venus"))'
    assert balance_parentheses('send Here are the options:\n- MacBook Air\n- ThinkPad X1\npin done') == '((send "Here are the options:\\n- MacBook Air\\n- ThinkPad X1") (pin "done"))'
    assert balance_parentheses('(shell "pwd")\n(version)') == '((shell "pwd") (version))'
    assert balance_parentheses('send "Plain text version:"\n**Mars** - red planet\nNote: Pluto is a dwarf planet') == '((send "\\\"Plain text version:\\\"\\n**Mars** - red planet\\nNote: Pluto is a dwarf planet"))'
    assert balance_parentheses('(send Here are the planets:\n1. Mercury\n2. Venus)') == '((send "Here are the planets:\\n1. Mercury\\n2. Venus"))'
    assert balance_parentheses('send "hello" world') == '((send "\\"hello\\" world"))'
    assert balance_parentheses('send "Hello"\nHow are you?') == '((send "\\"Hello\\"\\nHow are you?"))'
    # bare "()" lines yield no tokens after _strip_outer_parens and must be skipped, not crash
    assert balance_parentheses('()') == '()'
    assert balance_parentheses('') == '()'
    assert balance_parentheses('   ') == '()'
    assert balance_parentheses('()\nsend hello') == '((send "hello"))'
    assert balance_parentheses('write-file "test.txt" hello\nworld') == '((write-file "test.txt" "hello\\nworld"))'
    assert balance_parentheses('- Found a bug') == '((pin "Found a bug"))'
    assert balance_parentheses('(- Found a bug)') == '((pin "Found a bug"))'
    assert balance_parentheses('- Found\na\nbug') == '((pin "Found\\na\\nbug"))'
    assert balance_parentheses('(- Found a bug') == '((pin "Found a bug"))'
    assert balance_parentheses('(No "action needed")') == \
        '((Error UNKNOWN_SKILL_CALL "No \\"action needed\\""))'
    add_llm_command("workflow-load-instructions")
    assert balance_parentheses('workflow-load-instructions test-workflow') == \
        '((workflow-load-instructions "test-workflow"))'
    remove_llm_command("workflow-load-instructions")
    assert balance_parentheses('workflow-load-instructions test-workflow') == \
        '((Error UNKNOWN_SKILL_CALL "workflow-load-instructions test-workflow"))'

if __name__ == "__main__":
    test_omega_version()
    test_balance_parenthesis()
