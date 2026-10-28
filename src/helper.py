import json
import os
import re
import subprocess
import unicodedata
import urllib.request
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


REPLY_SAFE_SKILLS = ("send", "pin", "unlearn", "remember")


def answered_user(response):
    """True when the reply sends content and runs no skill whose result is still unseen."""
    names = skill_names(response)
    return '(send "' in (response or "") and all(n in REPLY_SAFE_SKILLS for n in names)


def is_send_call(command):
    """True when one skill call, as printed by repr, is a send."""
    return skill_names(f"({command})") == ["send"]


REPLY_MARKERS = (("_quote_", '"'), ("_newline_", "\n"), ("_apostrophe_", "'"))
REPLY_QUOTES = (('"', '"'), ("\u201c", "\u201d"), ("\u00ab", "\u00bb"))
ECHO_MIN_OVERLAP = 0.5


def _echoes(line, text):
    """True when the question in line mostly repeats the words of text."""
    if not line.rstrip().endswith("?"):
        return False
    words = set(re.findall(r"\w+", line.lower()))
    said = set(re.findall(r"\w+", text.lower()))
    return bool(words) and len(words & said) / len(words) >= ECHO_MIN_OVERLAP


def clean_reply(reply, message=""):
    """The text of a send as the user should read it.

    Small models leak their format into replies: the escape markers of the
    prompt, quotes around the whole answer, a skill call appended to the
    text, and the user's question repeated before the answer. Each is
    removed; an empty result means there is nothing to send.
    """
    text = str(reply or "")
    for marker, char in REPLY_MARKERS:
        text = text.replace(marker, char)
    # A marker copied without its underscore at either end of the text.
    text = re.sub(r"^\s*quote_|quote_\s*$", '"', text)
    # One or more skill calls written after the answer, such as (learn a | b | c);
    # learn is no longer a skill but models still write it.
    commands = "|".join(re.escape(cmd) for cmd in sorted(LLM_COMMANDS | {"learn"}))
    text = re.sub(rf"(?:\s*\((?:{commands})\b[^()]*\))+\s*$", "", text)
    text = text.strip()
    for opening, closing in REPLY_QUOTES:
        if len(text) > 1 and text.startswith(opening) and text.endswith(closing) and text.count(opening) == 1 + (opening == closing):
            text = text[1:-1].strip()
    lines = text.split("\n")
    if len(lines) > 1 and _echoes(lines[0], _latest_text(message)):
        lines = lines[1:]
    text = re.sub(r"\n\s*\n+", "\n\n", "\n".join(lines)).strip()
    return text


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
# A field that is only a placeholder means the model had no subject or value.
FACT_PLACEHOLDERS = {"none", "unknown", "null", "n/a", "nobody", "nothing"}
# Words that name a property rather than a stored value. Extraction often writes
# "logo" for "its logo blue"; the value beside it in the message is what DAS holds.
FACT_ATTRIBUTES = {
    "logo", "color", "colour", "colors", "colours", "city", "origin", "name",
    "year", "type", "kind", "size", "age", "job", "role", "eyes", "eye",
    "hair", "jersey", "flag", "title", "position",
}
# A generic kind of thing, not a stored name. "LOOKUP Team A" must not also
# spend a query slot on "team", which then leaves room for an unrelated index hit.
FACT_KINDS = {
    "team", "teams", "city", "cities", "person", "people", "player", "players",
    "server", "servers", "club", "clubs", "company", "group", "family",
    "country", "countries", "agent", "user",
}
# A relation that only says "this is a note" carries a sentence, not a fact.
RELATION_PLACEHOLDERS = {"note", "notes", "noted", "fact", "facts", "info", "information", "memo", "remember", "said", "says"}
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
    if any(len(words) == 1 and words[0] in FACT_PLACEHOLDERS for words in fields):
        return None
    subject = fields[0]
    while len(subject) > 1 and subject[0] in FACT_ARTICLES:
        subject = subject[1:]
    if subject == [] or (len(subject) == 1 and subject[0] in FACT_ARTICLES):
        return None
    if len(subject) == 1 and subject[0] in FACT_SELF_WORDS:
        subject = [message_speaker(message) or "user"]
    relations = [_relation_words(words) for words in fields[1:2]]
    return [" ".join(subject)] + ["_".join(words) for words in relations] + [" ".join(words) for words in fields[2:]]


def _relation_words(words):
    """'is similar to' and 'similar to' name the same relation; 'is a' keeps its verb."""
    if len(words) > 2 and words[0] in ("is", "are"):
        return words[1:]
    return words


def _strings(*tokens):
    return f"({' '.join(metta_string(token) for token in tokens)})"


def parse_fact(text, message=""):
    """'subject | relation | value' as '("subject" "relation" "value")', or '()' when it is not one short fact.

    All three are strings: the relation is a snake_case name such as "similar_to".
    """
    fields = _fact_fields(text, 3, message)
    if fields is None or fields[1] in RELATION_PLACEHOLDERS:
        return "()"
    return _strings(*fields)


def fact_term(subject, relation, value):
    """The PLN atom for a fact, as text for sread.

    (Evaluation (Predicate "relation") (List (Concept "subject") (Concept "value"))) is the
    binary form the lib_pln rules match, so a stored fact is a premise for |~. The
    predicate name is a string: DAS tells (Predicate similar_to) from
    (Predicate "similar_to"), and other agents writing to the same DAS use the
    string form, so a grounded query from either side finds the other's facts.
    """
    return (f"(Evaluation (Predicate {metta_string(fact_token(relation))}) "
            f"(List (Concept {metta_string(str(subject))}) (Concept {metta_string(str(value))})))")


def name_variants(key, message=""):
    """Spellings of a recall key to try against facts written by other agents.

    Omega lowercases concept names; other writers keep the user's spelling. The
    key as written in the message and in Title Case cover the common cases. A
    short key that is a word of a longer name ("team" in "Team A") also tries
    that longer name, which is where the facts are stored.
    """
    key = normalize_string(key).strip()
    variants = []

    def add(spelling):
        if spelling and spelling not in variants:
            variants.append(spelling)

    add(key)
    text = _latest_text(message)
    if key:
        for match in re.finditer(rf"(?i)(?<!\w){re.escape(key)}(?!\w)", text):
            add(match.group(0))
            # "team" in "Team A" also tries "Team A", where the facts are stored.
            longer = re.match(r"(?:\s+[A-Z0-9][\w./@+-]*)+", text[match.end():])
            if longer:
                add(match.group(0) + longer.group(0))
    add(key.title())
    return _strings(*variants)


def join_values(*values):
    """A three-place record's values as one MeTTa string: (List subject "1986" "26") reads as "1986 26"."""
    return metta_string(" ".join(normalize_string(v) for v in values))


def das_ping(endpoint, timeout=3):
    """True when the DAS Command Router at host:port answers GET /ping, or when no router is configured.

    Anything that is not host:port counts as no router: &das is then an in-process space.
    """
    endpoint = normalize_string(endpoint).strip()
    if not re.fullmatch(r"[\w.\-]+:\d+", endpoint):
        return True
    try:
        with urllib.request.urlopen(f"http://{endpoint}/ping", timeout=timeout) as resp:
            return "PONG" in resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        logger.warning(f"DAS router {endpoint} does not answer /ping: {e}")
        return False


def speaker_literal(message):
    """The sender's nick as a MeTTa string, "user" when the message names no sender."""
    return metta_string(message_speaker(message) or "user")


def parse_fact_key(text, message=""):
    """'subject | relation' as '("subject" "relation")', or '()' when malformed."""
    fields = _fact_fields(text, 2, message)
    if fields is None:
        return "()"
    return _strings(*fields)


FACT_EXTRACTION_PROMPT = (
    "Read the message below.\n"
    "For each lasting fact the speaker states as true about one subject, write one line: "
    "FACT subject | relation | value\n"
    "subject: a named person or thing, or a kind of thing such as banana or human; at most 4 words, I for the speaker. "
    "relation: at most 3 words. value: at most 6 words.\n"
    "For each lasting fact the speaker denies about one subject, or says is no longer so, write one line: "
    "NOT subject | relation | value\n"
    "For each named person or thing the speaker asks about, write one line: LOOKUP name\n"
    "name: the person or thing, at most 4 words, I for the speaker.\n"
    "For a question about something that must meet several conditions at once, write one line: "
    "ALL value | value\n"
    "For a question about something that meets any one of several conditions, write one line: "
    "ANY value | value\n"
    "value: one word or number from the message that the thing must be related to, such as a color, "
    "a place, a year or a name (blue, Lisbon, 2009); never the attribute it describes (logo, color, city, eyes) "
    "and never the kind of thing asked for (team, city, person); at most 3 values. "
    "'its logo blue' gives blue, not logo; 'green eyes' gives green, not eyes.\n"
    "Examples:\n"
    "My favorite color is blue. -> FACT I | favorite color | blue\n"
    "My sister Ana works at Acme as a designer. -> FACT Ana | works at | Acme\nFACT Ana | job | designer\n"
    "The staging server runs Ubuntu 22.04 and our standup is at 9:30. -> FACT staging server | runs | Ubuntu 22.04\nFACT standup | time | 9:30\n"
    "I moved to Lisbon last year. -> FACT I | lives in | Lisbon\n"
    "People from Oslo are tall and the Acme team is remote. -> FACT Oslo | people | tall\nFACT Acme team | work mode | remote\n"
    "Bananas are a fruit and dolphins are mammals. -> FACT banana | is a | fruit\nFACT dolphin | is a | mammal\n"
    "Ana does not work at Acme. -> NOT Ana | works at | Acme\n"
    "I no longer live in Lisbon, I moved to Porto. -> NOT I | lives in | Lisbon\nFACT I | lives in | Porto\n"
    "What is my favorite color? -> LOOKUP I\n"
    "When is the standup and who runs it? -> LOOKUP standup\n"
    "Tell me about Ana's job. -> LOOKUP Ana\n"
    "Who uses Ubuntu? -> LOOKUP Ubuntu\n"
    "Who said people from Oslo are tall? -> LOOKUP Oslo\n"
    "Who lives in Lisbon and works at Acme? -> ALL Lisbon | Acme\n"
    "Which city is on the coast and hosted the 1992 games? -> ALL coast | 1992\n"
    "Which player has green eyes and is from Oslo? -> ALL green | Oslo\n"
    "Which team has its logo blue and is from Oslo? -> ALL blue | Oslo\n"
    "Which servers run Ubuntu or Debian? -> ANY Ubuntu | Debian\n"
    "Does Ana work at Acme and live in Lisbon? -> LOOKUP Ana\nALL Acme | Lisbon\n"
    "Servers with more than 64 GB are large. -> NONE (a rule with a condition, not a fact about one subject)\n"
    "Please list the files. -> NONE (a request)\n"
    "A statement about the people, members or parts of a named thing is a fact about that thing. "
    "Every question that names a person or thing gets a LOOKUP line, whatever the topic. "
    "A question that joins conditions with and gets an ALL line, with or an ANY line, besides any LOOKUP. "
    "A NOT line names the fact being denied in its positive form, never a relation containing not. "
    "Requests, commands and rules with a condition give nothing. If there is no FACT, NOT, LOOKUP, ALL or ANY, write NONE.\n"
    "MESSAGE: "
)


def _latest_text(message):
    last = _plain_text(message).split(" | ")[-1]
    return last.partition(":")[2].strip() if message_speaker(message) else last.strip()


def fact_extraction_prompt(message):
    return FACT_EXTRACTION_PROMPT + _latest_text(message)


# Messages that cannot state or ask about a fact skip the extraction model call:
# the authentication command, direct skill calls, and short acknowledgements.
FACT_SKIP_MIN_WORDS = 3


def needs_fact_extraction(message):
    """True when the latest message may state or ask about a fact."""
    text = _latest_text(message)
    words = text.split()
    if not words:
        return False
    first = words[0].lower()
    if first == "auth" or first in LLM_COMMANDS:
        return False
    return len(words) >= FACT_SKIP_MIN_WORDS or text.endswith("?")


def _extraction_entries(reply, tag):
    """The text after each 'TAG ' in an extraction reply, without quotes, comments and arrows."""
    text = re.sub(r"[\"\\`*]", "", str(reply or ""))
    entries = []
    for line in text.splitlines():
        for part in re.split(rf"\b{tag}\s+", line)[1:]:
            entry = re.sub(r"\(.*?\)", "", part.split("->")[0]).strip(" ,;.")
            if entry:
                entries.append(entry)
    return entries


def extracted_facts(reply):
    """'subject | relation | value' strings from FACT entries of an extraction reply."""
    return _strings(*_extraction_entries(reply, "FACT"))


def extracted_denials(reply):
    """'subject | relation | value' strings from NOT entries: facts the speaker denies."""
    return _strings(*_extraction_entries(reply, "NOT"))


# The provider answers this when a reasoning model spends the whole output budget thinking.
TOKEN_LIMIT_MARKER = "reasoning exceeded the token limit"


def is_token_limit_reply(reply):
    """True when an extraction reply is the provider's token-limit message rather than an answer."""
    return TOKEN_LIMIT_MARKER in normalize_string(reply)


def extracted_lookups(reply, message="", limit=3):
    """Concept names from LOOKUP entries of an extraction reply, the speaker for I/me/my.

    A name of several words such as "Oslo people" also gives each capitalised word
    on its own, as the fact is most likely stored under "oslo". The subject of a
    FACT or NOT line is looked up too: a statement names the thing in the fact
    and often has no LOOKUP, so "Team A is playing…" still recalls Team A rather
    than the previous keys. The values of an ANY entry (a question joining
    conditions with or) are looked up the same way: recall reads a name on both
    sides of a fact, so the union of their facts is the OR of the conditions.
    The values of an ALL entry are looked up too, after the names: the
    conjunction over them answers the question when the model named the right
    values, and when it did not ("logo" for "blue"), the facts of each value
    still name the candidates, whose other facts recall then reads.
    """
    speaker = message_speaker(message)
    names = []

    def add(name):
        if name and name != speaker and name not in names:
            names.append(name)

    for entry in _extraction_entries(reply, "LOOKUP"):
        fields = _fact_fields(entry, 1, message)
        if not fields:
            continue
        add(fields[0])
        words = entry.split()
        if len(words) > 1:
            for word in words:
                token = fact_token(word)
                if (word[0].isupper() and len(token) >= 3 and token not in FACT_STOPWORDS
                        and token not in FACT_KINDS):
                    add(token)
    for tag in ("FACT", "NOT"):
        for entry in _extraction_entries(reply, tag):
            fields = _fact_fields(entry, 3, message)
            if fields:
                add(fields[0])
    for tag in ("ANY", "ALL"):
        for value in _entry_values(reply, tag, message):
            add(value)
    return _strings(*names[:int(limit)])


# Most values a thing must be related to at once; each one past the first is a DAS query.
CONJUNCTION_MAX_VALUES = 3


def _asked_kind(message):
    """The kind of thing a question asks for, as in 'which team' or 'what cities': {team} or {city, cities}."""
    match = re.search(r"\b(?:which|what)\s+(\w+)", _latest_text(message), re.IGNORECASE)
    if not match:
        return set()
    kind = fact_token(match.group(1))
    return {kind, kind[:-1] if kind.endswith("s") else kind + "s"}


def _value_for_attribute(attr, message, kind, used):
    """The stored value an attribute names in the message: 'logo' in 'its logo blue' is blue."""
    skip = FACT_STOPWORDS | FACT_ATTRIBUTES | FACT_PLACEHOLDERS | FACT_SELF_WORDS | kind | set(used)
    words = re.findall(r"\w+", _latest_text(message))
    tokens = [fact_token(word) for word in words]
    for i, token in enumerate(tokens):
        if token != attr:
            continue
        for j in (i + 1, i - 1, i + 2, i - 2):
            if 0 <= j < len(tokens) and tokens[j] not in skip and (len(tokens[j]) >= 3 or tokens[j].isdigit()):
                return tokens[j]
    return None


def _entry_values(reply, tag, message=""):
    """The '|'-separated values of the first TAG entry with at least two of them, lowercase.

    The kind of thing asked for is not a value: "which team" gives no team.
    An attribute the model named instead of the stored value ("logo" for
    "its logo blue") is replaced by the neighboring word in the message.
    """
    kind = _asked_kind(message)
    for entry in _extraction_entries(reply, tag):
        values = []
        for field in _plain_text(entry).split("|"):
            value = " ".join(_fact_words(field))
            if value in FACT_ATTRIBUTES:
                value = _value_for_attribute(value, message, kind, values)
            if value and value not in FACT_PLACEHOLDERS and value not in kind and value not in values:
                values.append(value)
        if len(values) >= 2:
            return values[:CONJUNCTION_MAX_VALUES]
    return []


def extracted_conjunction(reply, message=""):
    """The values of an ALL entry (a question joining conditions with and) as ("v1" "v2"), or ()."""
    values = _entry_values(reply, "ALL", message)
    return _strings(*values) if values else "()"


def _value_spellings(value, message):
    """The forms a condition value may be stored under: lowercase, as spelled in the message,
    and for several words each word on its own, as "2009 championship" is most likely stored as "2009"."""
    spellings = []

    def add(spelling):
        if spelling and spelling not in spellings:
            spellings.append(spelling)
        match = re.search(re.escape(spelling), _latest_text(message), re.IGNORECASE) if spelling else None
        if match:
            add_plain(match.group(0))

    def add_plain(spelling):
        if spelling and spelling not in spellings:
            spellings.append(spelling)

    add(value)
    words = value.split()
    if len(words) > 1:
        for word in words:
            if word not in FACT_STOPWORDS and (len(word) >= 3 or word.isdigit()):
                add(word)
    return spellings


def _value_matches(stored, value, message):
    """True when a stored value is one of the forms of a condition value."""
    return stored.lower() in {spelling.lower() for spelling in _value_spellings(value, message)}


def conjunction_queries(values, message=""):
    """DAS queries for a subject related to every value, as ((pattern template) ...).

    A pattern is one conjunction of two bare Evaluation clauses sharing the
    subject, whatever their relations are, so it reads learned facts and facts
    written by other agents alike. The router takes two clauses per conjunction,
    so each value past the first is paired with the first and conjunction_facts
    keeps the subjects seen with all of them. The template gives the two facts
    in the recall tuple form. Each value is tried lowercase and as spelled in
    the message.
    """
    values = re.findall(r'"([^"]*)"', str(values or ""))
    if len(values) < 2:
        return "()"
    pairs = []
    for other in values[1:]:
        for first in _value_spellings(values[0], message):
            for second in _value_spellings(other, message):
                clauses = [("$r1", first), ("$r2", second)]
                pattern = "(, " + " ".join(f"(Evaluation (Predicate {r}) (List (Concept $s) (Concept {metta_string(v)})))"
                                           for r, v in clauses) + ")"
                template = "(" + " ".join(f'($s {r} {metta_string(v)} "" "" 1.0)' for r, v in clauses) + ")"
                pairs.append(f"({pattern} {template})")
    return f"({' '.join(pairs)})"


def conjunction_facts(facts, values, message=""):
    """The recalled facts whose subject is related to every value, in any of the value's forms."""
    wanted = re.findall(r'"([^"]*)"', str(values or ""))
    by_subject = {}
    for fact in _fact_tuples(facts):
        by_subject.setdefault(fact[0], []).append(fact)
    kept = [fact for subject_facts in by_subject.values()
            if all(any(_value_matches(fact[2], value, message) for fact in subject_facts) for value in wanted)
            for fact in subject_facts]
    return _fact_list_text(kept)


def fact_index_text(subject, relation, value):
    """The document a learned fact is stored under in the embedding index."""
    return f"FACT {subject} | {relation} | {value}"


def indexed_fact_subjects(results, limit=3):
    """Subjects of FACT documents in a Chroma query result, most similar first."""
    subjects = []
    for match in re.finditer(r"FACT\s+([^|]+?)\s*\|", _plain_text(results)):
        subject = " ".join(_fact_words(match.group(1)))
        if subject and subject not in subjects:
            subjects.append(subject)
    return _strings(*subjects[:int(limit)])


def _folded_name(name):
    """Lowercase name without combining marks, so brasilia and brasília compare equal."""
    return "".join(c for c in unicodedata.normalize("NFD", str(name).lower())
                   if unicodedata.category(c) != "Mn")


def recall_keys(message, lookups, indexed, limit=3, previous="()"):
    """Concept names besides the speaker to query for a message.

    LOOKUP names come first. An indexed FACT subject is added only as a spelling
    of a LOOKUP (brasília for brasilia), never an unrelated name: the nearest
    document after learning about Team B is Team B, which must not replace a
    question about Team A. Capitalised message words fill in when extraction
    named nothing. A follow-up that names nothing ('Try again') keeps the
    previous keys instead of that nearest document.
    """
    speaker = message_speaker(message)
    lookups = re.findall(r'"([^"]*)"', str(lookups or ""))
    indexed = re.findall(r'"([^"]*)"', str(indexed or ""))
    previous = re.findall(r'"([^"]*)"', str(previous or ""))
    fallback = [] if lookups else [name for name in re.findall(r'"([^"]*)"', fact_query_keys(message, limit, names_only=True))
                                   if name and name != speaker]
    folded = {_folded_name(name) for name in lookups}
    extra_index = [name for name in indexed if _folded_name(name) in folded]
    if lookups:
        pool = lookups + extra_index
    elif fallback:
        pool = fallback + indexed
    elif previous and not _latest_text(message).endswith("?"):
        pool = previous
    else:
        pool = indexed
    names = []
    for name in pool:
        if name and name != speaker and name not in names and len(names) < int(limit):
            names.append(name)
    return _strings(*names)


FACT_VERB_RELATIONS = ("is", "are", "has", "have", "likes", "loves", "hates", "owns", "lives", "works")
SECOND_PERSON_VERBS = {"is": "are", "has": "have"}


def _second_person(verb):
    return SECOND_PERSON_VERBS.get(verb, verb[:-1] if verb.endswith("s") and verb != "is" else verb)


def _negated(verb):
    """'is' -> 'is not', 'has' -> 'does not have', 'likes' -> 'does not like', 'like' -> 'do not like'."""
    if verb in ("is", "are"):
        return f"{verb} not"
    if verb == "has":
        return "does not have"
    if verb.endswith("s"):
        return f"does not {_second_person(verb)}"
    return f"do not {verb}"


def _fact_sentence(subject, relation, value, speaker, denied=False):
    relation, value = relation.replace("_", " "), value.replace("_", " ")
    words = relation.split()
    # "population is" reads as "population is is" once the sentence adds its own verb.
    if len(words) > 1 and words[-1] in ("is", "are"):
        relation = " ".join(words[:-1])
    verb, _, rest = relation.partition(" ")
    if verb in FACT_VERB_RELATIONS:
        if subject == speaker:
            verb = _second_person(verb)
            return " ".join(part for part in ("you", _negated(verb) if denied else verb, rest, value) if part)
        return " ".join(part for part in (subject, _negated(verb) if denied else verb, rest, value) if part)
    owner = "your" if subject == speaker else f"{subject}'s"
    return f"{owner} {relation} {'is not' if denied else 'is'} {value}"


def _fact_source(who, when, speaker):
    if not who:
        return ""
    teller = "you" if who == speaker else who
    return f" (said by {teller} on {when})" if when else f" (said by {teller})"


def _fact_tuples(facts):
    """Recall tuples in a MeTTa list as (subject, relation, value, who, when, strength).

    A tuple is ("subject" "relation" "value"), with its source
    ("subject" "relation" "value" "who" "when"), or with its truth as well
    ("subject" "relation" "value" "who" "when" 1.0); who and when are empty and
    the strength 1.0 when absent. A strength under 0.5 is a denied fact. The
    relation is accepted quoted or as a bare symbol, which older stored facts used.
    """
    found = re.findall(r'\(\s*"([^"]*)"\s+(?:"([^"]*)"|([^\s()"]+))\s+"([^"]*)"'
                       r'(?:\s+"([^"]*)"\s+"([^"]*)"(?:\s+([0-9.eE+-]+))?)?\s*\)',
                       str(facts or ""))
    return [(s, quoted or bare, v, who, when, _strength(strength)) for s, quoted, bare, v, who, when, strength in found]


def _strength(text):
    try:
        return float(text)
    except (TypeError, ValueError):
        return 1.0


def _denied(fact):
    return fact[5] < 0.5


def _fact_tuple_text(fact):
    """A recall tuple as MeTTa text, the strength unquoted."""
    subject, relation, value, who, when, strength = fact
    return f"({' '.join(metta_string(t) for t in (subject, relation, value, who, when))} {float(strength)!r})"


def _fact_list_text(facts):
    return "(" + " ".join(_fact_tuple_text(fact) for fact in facts) + ")"


def merge_facts(facts):
    """Recalled tuples without the sourceless copy of a fact that also came with its source.

    A learned fact answers both the Belief/Stated query, with who, when and
    truth, and the bare Evaluation query, with none; the bare copy would read a
    denied fact as true. Order is kept, duplicates dropped.
    """
    tuples = _fact_tuples(facts)
    sourced = {fact[:3] for fact in tuples if fact[3]}
    kept = []
    for fact in tuples:
        if (fact[3] or fact[:3] not in sourced) and fact not in kept:
            kept.append(fact)
    return _fact_list_text(kept)


def fact_subjects(facts):
    """The distinct subjects of recall tuples, as ("Team A" "team b")."""
    subjects = []
    for fact in _fact_tuples(facts):
        if fact[0] not in subjects:
            subjects.append(fact[0])
    return _strings(*subjects)


def new_subjects(facts, keys, speaker="", limit=3):
    """Subjects of recall tuples that were not looked up themselves, spelled as stored.

    A fact found from its value side, "Team A founded_in Brasília" for the key
    "brasília", names a thing the message did not: its other facts (Team A's
    logo color) are what answers "which team from Brasília has a blue logo", so
    recall reads them next. Subjects equal to a key or to the speaker are already
    read in full. At most limit subjects, in the order found; a subject another
    agent stored with capitals ("Team A") is given lowercase as well, which is
    how the facts learned here about it are stored.
    """
    known = {str(k).lower() for k in re.findall(r'"([^"]*)"', str(keys or ""))}
    known.add(str(speaker or "").lower())
    subjects = []
    for fact in _fact_tuples(facts):
        subject = fact[0]
        if subject and subject.lower() not in known and subject.lower() not in (s.lower() for s in subjects):
            subjects.append(subject)
    names = []
    for subject in subjects[:int(limit)]:
        for name in (subject, subject.lower()):
            if name not in names:
                names.append(name)
    return _strings(*names)


def drop_denied(facts, beliefs):
    """Recall tuples without those whose fact is believed false.

    beliefs are ("subject" "relation" "value" strength) tuples read from the
    Belief links of the facts' subjects.
    """
    denied = {(s, r, v) for s, r, v, strength in re.findall(r'\(\s*"([^"]*)"\s+"([^"]*)"\s+"([^"]*)"\s+([0-9.eE+-]+)\s*\)',
                                                              str(beliefs or ""))
              if _strength(strength) < 0.5}
    return _fact_list_text([fact for fact in _fact_tuples(facts) if fact[:3] not in denied])


def describe_facts(facts, message=""):
    """Recalled facts as sentences addressed to the message sender.

    A fact is ("subject" relation "value") or, with its provenance,
    ("subject" relation "value" "who" "when") and its truth; the source is kept
    so the agent can say who told it what, and when, and a denied fact reads
    "is not". The newest facts come first, so when a relation holds several
    values the latest statement is read first.
    """
    speaker = message_speaker(message)
    found = _fact_tuples(facts)
    if not found:
        return "none"
    found.sort(key=lambda fact: fact[4], reverse=True)
    return "; ".join(_fact_sentence(subject, relation, value, speaker, denied=_denied(fact)) + _fact_source(who, when, speaker)
                     for fact in found for subject, relation, value, who, when, _ in [fact]) + "."


def fact_query_keys(message, limit=3, names_only=False):
    """Concept names to look up for a message: the speaker, then up to limit content words, names first.

    names_only keeps capitalised words alone, for the fallback when the extraction named
    nothing: each key costs two DAS queries, so common words are not worth asking for.
    """
    speaker = message_speaker(message)
    text = _latest_text(message)
    words = re.findall(r"[^\W_][\w./@+-]*", text)
    # The first word of a message is capitalised whatever it is, so alone it is not a name.
    first = words[0] if words else ""
    candidates = []
    for word in sorted(words, key=lambda word: not word[0].isupper()):
        key = fact_token(word)
        if names_only and (not word[0].isupper() or (word == first and words.count(word) == 1)):
            continue
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

def getenv(key, default=""):
    return os.environ.get(str(key), default)

def is_set(x):
    """True when x is non-empty text. A MeTTa bool reaches Python as text, so no flag argument."""
    return x is not None and bool(str(x).strip())

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
