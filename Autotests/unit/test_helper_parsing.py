"""In-process unit tests for the parsing helpers in src/helper.py.

quote_arg / split_command_blocks / balance_parentheses turn the model's
loosely-structured reply into the s-expression the agent actually runs, so a
regression here silently corrupts every skill call. The module ships one inline
test_balance_parenthesis(), but it never exercises backslashes, embedded quotes
or quote_arg directly — the exact paths behind the escaping (#262) and command
parsing (#209) bugs. These cover them.

No container, no network, no token — same pattern as
test_fileio_verified_writes.py: the module is loaded by file path.
"""
import datetime
import importlib.util
import os
import sys

import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_HELPER_PATH = os.path.join(_REPO_ROOT, "src", "helper.py")

# helper.py does `from src.logger import get_logger` (repo-root package) at import time.
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _load_helper():
    spec = importlib.util.spec_from_file_location("helper_under_test", _HELPER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def helper():
    return _load_helper()


# --- quote_arg ------------------------------------------------------------

def test_quote_arg_wraps_plain_token(helper):
    assert helper.quote_arg("hello") == '"hello"'


def test_quote_arg_passes_through_already_quoted_single_line(helper):
    assert helper.quote_arg('"hello"') == '"hello"'


def test_quote_arg_requotes_when_quoted_value_contains_newline(helper):
    # the pass-through guard excludes newlines, so this goes through json.dumps
    assert helper.quote_arg('"a\nb"') == '"\\"a\\nb\\""'


def test_quote_arg_escapes_backslash(helper):
    assert helper.quote_arg("a\\b") == '"a\\\\b"'


def test_quote_arg_escapes_trailing_backslash_windows_path(helper):
    # #262: a trailing backslash must not escape the closing quote
    assert helper.quote_arg("C:\\path\\to\\") == '"C:\\\\path\\\\to\\\\"'


def test_quote_arg_escapes_embedded_double_quote(helper):
    assert helper.quote_arg('say "hi"') == '"say \\"hi\\""'


def test_quote_arg_escapes_real_newline(helper):
    assert helper.quote_arg("a\nb") == '"a\\nb"'


def test_quote_arg_keeps_non_ascii_unescaped(helper):
    # ensure_ascii=False keeps UTF-8 readable instead of \uXXXX
    assert helper.quote_arg("café €") == '"café €"'


# --- starts_command_line --------------------------------------------------

def test_starts_command_line_recognizes_known_commands(helper):
    assert helper.starts_command_line("send hi") is True
    assert helper.starts_command_line("(send hi)") is True
    assert helper.starts_command_line("  shell ls") is True
    assert helper.starts_command_line("write-file a b") is True


def test_starts_command_line_rejects_prose_and_blanks(helper):
    assert helper.starts_command_line("hello there") is False
    assert helper.starts_command_line("") is False
    assert helper.starts_command_line("(") is False


# --- split_command_blocks -------------------------------------------------

def test_split_attaches_continuation_lines_to_the_current_command(helper):
    assert helper.split_command_blocks("send hello\nmore text\npin done") == [
        "send hello\nmore text",
        "pin done",
    ]


def test_split_single_command_is_one_block(helper):
    assert helper.split_command_blocks("shell ls -la") == ["shell ls -la"]


def test_split_drops_blank_lines_between_commands(helper):
    assert helper.split_command_blocks("send a\n\n\npin b") == ["send a", "pin b"]


# --- balance_parentheses (escaping paths the inline test misses) ----------

def test_balance_escapes_backslashes_in_send_content(helper):
    assert helper.balance_parentheses("send C:\\path\\to") == '((send "C:\\\\path\\\\to"))'


def test_balance_escapes_backslashes_in_write_file_content(helper):
    assert helper.balance_parentheses("write-file a.txt C:\\x\\y") == (
        '((write-file "a.txt" "C:\\\\x\\\\y"))'
    )


def test_balance_escapes_embedded_quotes_in_content(helper):
    assert helper.balance_parentheses('send say "hi" ok') == '((send "say \\"hi\\" ok"))'


def test_balance_escapes_backslash_in_shell_command(helper):
    assert helper.balance_parentheses("shell echo a\\b") == '((shell "echo a\\\\b"))'


def test_balance_passes_belief_skills_as_one_sexpression_string(helper):
    parsed = helper.balance_parentheses(
        "believe ((--> sam animal) (stv 1.0 0.9))\nbeliefs (--> sam $1)"
    )
    assert parsed == (
        '((believe "((--> sam animal) (stv 1.0 0.9))") (beliefs "(--> sam $1)"))'
    )


def test_skill_names_ignores_parentheses_inside_arguments(helper):
    parsed = helper.balance_parentheses('beliefs (--> a $1)\nsend say "(remember x)" ok\nversion')
    assert helper.skill_names(parsed) == ["beliefs", "send", "version"]


def test_answered_user_only_for_send_without_pending_results(helper):
    assert helper.answered_user(helper.balance_parentheses("send a is b")) is True
    assert helper.answered_user(helper.balance_parentheses("pin noted\nsend a is b")) is True
    assert helper.answered_user(helper.balance_parentheses("beliefs (--> a $1)\nsend done")) is False
    assert helper.answered_user(helper.balance_parentheses("send")) is False
    assert helper.answered_user(helper.balance_parentheses("beliefs (--> a $1)")) is False
    assert helper.answered_user(helper.balance_parentheses("learn I favorite_color purple\nsend Ok")) is True


# --- facts ----------------------------------------------------------------

def test_parse_fact_maps_self_words_to_the_speaker(helper):
    assert helper.parse_fact("I | favorite color | purple", "arturgontijo: my favorite color is purple") == (
        '("arturgontijo" favorite_color "purple")'
    )


def test_parse_fact_keeps_value_words_and_sanitizes_them(helper):
    assert helper.parse_fact("Paris | capital of | (France) $1", "") == (
        '("paris" capital_of "france 1")'
    )
    assert helper.parse_fact("I | favorite_color | Dark Blue", "") == '("user" favorite_color "dark blue")'
    assert helper.parse_fact("The capital of Brazil | population | more than one million", "") == (
        '("capital of brazil" population "more than one million")'
    )


def test_fact_text_keeps_non_ascii_letters_unescaped(helper):
    assert helper.parse_fact("Brazil | capital | Brasília", "") == '("brazil" capital "brasília")'
    assert helper.parse_fact("São Paulo | população | doze milhões", "") == (
        '("são paulo" população "doze milhões")'
    )
    assert helper.extracted_facts("FACT Brazil | capital | Brasília") == '("Brazil | capital | Brasília")'
    assert helper.fact_query_keys("ana: Onde fica Brasília?", 3) == '("ana" "onde" "brasília" "fica")'


def test_parse_fact_rejects_sentences_and_long_fields(helper):
    assert helper.parse_fact("The capital of Brazil has more than one million people actual", "") == "()"
    assert helper.parse_fact("I city big city population threshold is 500k people", "") == "()"
    assert helper.parse_fact("I | city | big city population threshold is 500k people", "") == "()"
    assert helper.parse_fact("the | capital | brasilia", "") == "()"
    assert helper.parse_fact("I | favorite color", "") == "()"
    assert helper.parse_fact("purple", "") == "()"


def test_parse_fact_key_takes_subject_and_relation(helper):
    assert helper.parse_fact_key("my | favorite color", "") == '("user" favorite_color)'
    assert helper.parse_fact_key("my favorite_color", "") == "()"


def test_fact_extraction_prompt_uses_only_the_latest_message_text(helper):
    prompt = helper.fact_extraction_prompt("bob: hi | arturgontijo: My favorite color is blue.")
    assert prompt.endswith("MESSAGE: My favorite color is blue.")
    assert "FACT subject | relation | value" in prompt


def test_extracted_facts_reads_fact_lines_and_fused_lines(helper):
    assert helper.extracted_facts("FACT I | favorite color | blue\nFACT I | favorite food | pasta") == (
        '("I | favorite color | blue" "I | favorite food | pasta")'
    )
    assert helper.extracted_facts('**FACT I | favorite color | "blue"**, FACT I | favorite food | pasta.') == (
        '("I | favorite color | blue" "I | favorite food | pasta")'
    )
    assert helper.extracted_facts("My favorite color is blue. -> FACT I | favorite color | blue (about the speaker)") == (
        '("I | favorite color | blue")'
    )
    assert helper.extracted_facts("NONE (a general rule, not about one thing)") == "()"


def test_describe_facts_addresses_the_sender_as_you(helper):
    facts = ('(("arturgontijo" favorite_color "blue") ("france" capital "paris") '
             '("arturgontijo" lives_in "belo horizonte"))')
    assert helper.describe_facts(facts, "arturgontijo: what is my favorite color?") == (
        "your favorite color is blue; france's capital is paris; you live in belo horizonte."
    )
    assert helper.describe_facts('(("bob" is "tall"))', "bob: am I tall?") == "you are tall."
    assert helper.describe_facts('(("bob" is "tall"))', "ana: is bob tall?") == "bob is tall."
    assert helper.describe_facts(facts, "bob: what does arturgontijo like?").startswith(
        "arturgontijo's favorite color is blue;"
    )
    assert helper.describe_facts("()", "bob: hi") == "none"


def test_fact_query_keys_start_with_the_speaker_and_skip_stopwords(helper):
    message = "bob: hi | arturgontijo: What_apostrophe_s my favorite color of all?"
    assert helper.fact_query_keys(message, 3) == '("arturgontijo" "favorite" "color" "all")'
    assert helper.fact_query_keys("no speaker here at all", 2) == '("speaker" "here")'


def test_is_send_call_matches_only_a_top_level_send(helper):
    assert helper.is_send_call('(send "No new user input.")')
    assert not helper.is_send_call('(pin "send this later")')
    assert not helper.is_send_call('(das-recall (send x))')
    assert not helper.is_send_call('(sendx "a")')


def test_fact_query_keys_look_up_names_before_other_words(helper):
    assert helper.fact_query_keys("arturgontijo: How many people live in Divinópolis?", 3) == (
        '("arturgontijo" "divinópolis" "people" "live")'
    )


def test_unknown_skill_only_matches_prose(helper):
    parsed = helper.balance_parentheses("My favorite color is blue")
    assert helper.unknown_skill_only(parsed) is True
    assert "send skill followed by the reply" in helper.unknown_skill_reminder()


def test_unknown_skill_only_keeps_a_real_send(helper):
    parsed = helper.balance_parentheses("send Paris is the capital")
    assert helper.unknown_skill_only(parsed) is False


# --- normalize_string -----------------------------------------------------

def test_normalize_string_decodes_bytes(helper):
    assert helper.normalize_string(b"abc") == "abc"


def test_normalize_string_passes_through_str(helper):
    assert helper.normalize_string("abc") == "abc"


def test_normalize_string_drops_invalid_utf8_instead_of_raising(helper):
    assert helper.normalize_string(b"a\xffb") == "ab"


def test_normalize_string_stringifies_non_text(helper):
    assert helper.normalize_string(123) == "123"


# --- extract_timestamp ----------------------------------------------------

def test_extract_timestamp_parses_leading_history_stamp(helper):
    assert helper.extract_timestamp('("2026-07-30 12:00:00" foo)') == datetime.datetime(
        2026, 7, 30, 12, 0, 0
    )


def test_extract_timestamp_returns_none_when_absent(helper):
    assert helper.extract_timestamp("no timestamp here") is None
