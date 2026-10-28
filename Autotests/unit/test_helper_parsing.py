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
import re
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
    assert helper.answered_user(helper.balance_parentheses("unlearn I | favorite_color\nsend Ok")) is True


# --- facts ----------------------------------------------------------------

def test_parse_fact_maps_self_words_to_the_speaker(helper):
    assert helper.parse_fact("I | favorite color | purple", "arturgontijo: my favorite color is purple") == (
        '("arturgontijo" "favorite_color" "purple")'
    )


def test_parse_fact_keeps_value_words_and_sanitizes_them(helper):
    assert helper.parse_fact("Paris | capital of | (France) $1", "") == (
        '("paris" "capital_of" "france 1")'
    )
    assert helper.parse_fact("I | favorite_color | Dark Blue", "") == '("user" "favorite_color" "dark blue")'
    assert helper.parse_fact("The capital of Brazil | population | more than one million", "") == (
        '("capital of brazil" "population" "more than one million")'
    )


def test_fact_text_keeps_non_ascii_letters_unescaped(helper):
    assert helper.parse_fact("Brazil | capital | Brasília", "") == '("brazil" "capital" "brasília")'
    assert helper.parse_fact("São Paulo | população | doze milhões", "") == (
        '("são paulo" "população" "doze milhões")'
    )
    assert helper.extracted_facts("FACT Brazil | capital | Brasília") == '("Brazil | capital | Brasília")'
    assert helper.fact_query_keys("ana: Onde fica Brasília?", 3) == '("ana" "onde" "brasília" "fica")'


def test_parse_fact_peels_attribute_off_a_compound_subject(helper):
    # The 9B model wrote FACT team b jersey | color | red, which DAS stored
    # under Concept "team b jersey" and a "team b" lookup then missed.
    assert helper.parse_fact("team b jersey | color | red", "") == '("team b" "jersey" "red")'
    assert helper.parse_fact("team b flag | color | red", "") == '("team b" "flag" "red")'
    assert helper.parse_fact("team b logo | color | red", "") == '("team b" "logo" "red")'
    assert helper.parse_fact("team a | jersey | blue", "") == '("team a" "jersey" "blue")'


def test_parse_fact_rejects_sentences_and_long_fields(helper):
    assert helper.parse_fact("The capital of Brazil has more than one million people actual", "") == "()"
    assert helper.parse_fact("I city big city population threshold is 500k people", "") == "()"
    assert helper.parse_fact("I | city | big city population threshold is 500k people", "") == "()"
    assert helper.parse_fact("the | capital | brasilia", "") == "()"
    assert helper.parse_fact("I | favorite color", "") == "()"
    assert helper.parse_fact("purple", "") == "()"


def test_parse_fact_key_takes_subject_and_relation(helper):
    assert helper.parse_fact_key("my | favorite color", "") == '("user" "favorite_color")'
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
             '("arturgontijo" "lives_in" "belo horizonte"))')
    assert helper.describe_facts(facts, "arturgontijo: what is my favorite color?") == (
        "your favorite color is blue; france's capital is paris; you live in belo horizonte."
    )
    assert helper.describe_facts('(("bob" is "tall"))', "bob: am I tall?") == "you are tall."
    assert helper.describe_facts('(("bob" is "tall"))', "ana: is bob tall?") == "bob is tall."
    assert helper.describe_facts(facts, "bob: what does arturgontijo like?").startswith(
        "arturgontijo's favorite color is blue;"
    )
    assert helper.describe_facts("()", "bob: hi") == "none"


def test_clean_reply_removes_format_noise_seen_in_chat(helper):
    # Cases taken from IRC sessions with a 9B model.
    assert helper.clean_reply('quote_The rule is recorded: cities with more than 500k people are big city."') == (
        "The rule is recorded: cities with more than 500k people are big city."
    )
    assert helper.clean_reply(
        '"Yes—understood. I\'ve recorded this rule." (learn arturgontijo | classification rule | mid-size)'
    ) == "Yes—understood. I've recorded this rule."
    assert helper.clean_reply(
        "How can we classify Divinópolis city?\n\nDivinópolis, with around 250k people, is a mid-size city.",
        "arturgontijo: How can we classify Divinópolis city?",
    ) == "Divinópolis, with around 250k people, is a mid-size city."
    assert helper.clean_reply(
        "What can we say about the people who live in Divinópolis?\nPeople who live in Divinópolis are poor.",
        "arturgontijo: What can we say about people that live there?",
    ) == "People who live in Divinópolis are poor."
    assert helper.clean_reply("Divinópolis_apostrophe_ people are poor_newline_Said by you.") == (
        "Divinópolis' people are poor\nSaid by you."
    )
    assert helper.clean_reply("_quote__apostrophe_Noted: Team B is not playing the 2026 championship._apostrophe__quote_") == (
        "Noted: Team B is not playing the 2026 championship."
    )
    assert helper.clean_reply("'_Noted. Here's what I know about Team A:_") == (
        "Noted. Here's what I know about Team A:"
    )
    assert helper.clean_reply(
        "`'_Team B has a red logo and is from Divinópolis.'` Team B has a red logo and is from Divinópolis."
    ) == "Team B has a red logo and is from Divinópolis."
    assert helper.clean_reply("'_Noted: Team B. Team B is not in the 2026 championship.") == (
        "Noted: Team B. Team B is not in the 2026 championship."
    )


def test_clean_reply_keeps_ordinary_replies(helper):
    assert helper.clean_reply("Do you mean the staging server?\nIt runs Ubuntu.", "bob: which server?") == (
        "Do you mean the staging server?\nIt runs Ubuntu."
    )
    assert helper.clean_reply('He said "hi" and "bye".') == 'He said "hi" and "bye".'
    assert helper.clean_reply("Run (shell ls) to list files.") == "Run (shell ls) to list files."
    assert helper.clean_reply("Is this a question?", "bob: Is this a question?") == "Is this a question?"
    assert helper.clean_reply('""') == ""
    assert helper.clean_reply("  ") == ""


def test_describe_facts_names_the_source_of_each_fact(helper):
    facts = ('(("divinópolis" people "poor" "arturgontijo" "2026-10-23 13:38:48") '
             '("divinópolis" "population_is" "around 250k" "ana" "2026-10-23 13:35:07"))')
    assert helper.describe_facts(facts, "arturgontijo: who told you that?") == (
        "divinópolis's people is poor (said by you on 2026-10-23 13:38:48); "
        "divinópolis's population is around 250k (said by ana on 2026-10-23 13:35:07)."
    )
    assert helper.describe_facts('(("bob" is "tall" "bob" ""))', "ana: is bob tall?") == "bob is tall (said by bob)."


def test_fact_query_keys_start_with_the_speaker_and_skip_stopwords(helper):
    message = "bob: hi | arturgontijo: What_apostrophe_s my favorite color of all?"
    assert helper.fact_query_keys(message, 3) == '("arturgontijo" "favorite" "color" "all")'
    assert helper.fact_query_keys("no speaker here at all", 2) == '("speaker" "here")'


def test_parse_fact_rejects_placeholder_fields(helper):
    assert helper.parse_fact("NONE | likes | purple", "bob: who likes purple?") == "()"
    assert helper.parse_fact("I | likes | unknown", "bob: hi") == "()"
    assert helper.extracted_lookups("LOOKUP none\nLOOKUP purple", "bob: q?") == '("purple")'


def test_fact_term_is_the_binary_pln_evaluation(helper):
    assert helper.fact_term("brazil", "capital", "brasília") == (
        '(Evaluation (Predicate "capital") (List (Concept "brazil") (Concept "brasília")))'
    )
    assert helper.speaker_literal("ana: hi") == '"ana"'
    assert helper.speaker_literal("no sender") == '"user"'


def test_extracted_lookups_map_self_to_the_speaker_and_cap_the_count(helper):
    reply = "LOOKUP I\nLOOKUP Brazil\nLOOKUP Brasilia (the capital)\nLOOKUP purple\nFACT I | dog | Rex"
    assert helper.extracted_lookups(reply, "arturgontijo: q?", 3) == '("brazil" "brasilia" "purple")'
    assert helper.extracted_lookups("NONE", "arturgontijo: q?") == "()"
    assert helper.extracted_facts(reply) == '("I | dog | Rex")'


def test_extracted_lookups_also_give_the_names_inside_a_longer_name(helper):
    # "Divinópolis people" is stored under "divinópolis"; "staging server" has no name to split off.
    assert helper.extracted_lookups("LOOKUP Divinópolis people", "bob: q?") == '("divinópolis people" "divinópolis")'
    assert helper.extracted_lookups("LOOKUP The Acme team\nLOOKUP staging server", "bob: q?", 3) == (
        '("acme team" "acme" "staging server")'
    )


def test_any_values_are_looked_up_like_names_and_all_values_make_a_conjunction(helper):
    # OR: each value is a recall key; AND: the values of the first ALL line, at most three.
    assert helper.extracted_lookups("ANY Ubuntu | Debian", "bob: Which servers run Ubuntu or Debian?") == '("ubuntu" "debian")'
    assert helper.extracted_lookups("LOOKUP Ana\nANY tea | coffee", "bob: q?") == '("ana" "tea" "coffee")'
    assert helper.extracted_conjunction("LOOKUP team\nALL blue | 2009") == '("blue" "2009")'
    assert helper.extracted_conjunction("ALL Lisbon | Acme | tea | red") == '("lisbon" "acme" "tea")'
    assert helper.extracted_conjunction("ALL blue") == "()"
    assert helper.extracted_conjunction("ALL none | blue\nALL red | 2022") == '("red" "2022")'
    assert helper.extracted_conjunction("LOOKUP Ana") == "()"
    # The kind of thing asked for is not a condition, singular or plural.
    message = "arturgontijo: Which team has its logo blue and have won the 2009 championship?"
    assert helper.extracted_conjunction("ALL team | blue | 2009 championship", message) == '("blue" "2009 championship")'
    assert helper.extracted_lookups("ANY teams | red | blue", "bob: Which team has red or blue jerseys?") == '("red" "blue")'
    assert "ALL value | value" in helper.FACT_EXTRACTION_PROMPT and "ANY value | value" in helper.FACT_EXTRACTION_PROMPT
    # The model often names the attribute ("logo") instead of the stored value ("blue").
    message = "bob: Which team has its logo blue and is from Brasília?"
    assert helper.extracted_conjunction("ALL logo | Brasília", message) == '("blue" "brasília")'
    assert helper.extracted_lookups("ALL logo | Brasília", message) == '("blue" "brasília")'
    assert helper.extracted_conjunction("ALL red | Brasília",
                                        "bob: Which team has its logo red and is from Brasília?") == '("red" "brasília")'
    assert helper.extracted_conjunction("ALL eyes | Oslo", "bob: Which player has green eyes and is from Oslo?") == (
        '("green" "oslo")')
    assert helper.extracted_lookups("LOOKUP Ana\nALL Acme | Lisbon", "bob: q?", 2) == '("ana" "acme")'


def test_new_subjects_are_those_recalled_from_the_value_side(helper):
    facts = ('(("Team A" "founded_in" "Brasília" "" "" 1.0) ("bob" "likes" "tea" "bob" "2026-10-27 10:00:00" 1.0)'
             ' ("team b" "founded_in" "Divinópolis" "" "" 1.0) ("Team A" "logo_color" "blue" "" "" 1.0)'
             ' ("iPad" "owner" "ana" "" "" 1.0) ("Club C" "city" "Brasília" "" "" 1.0))')
    assert helper.new_subjects(facts, '("brasília" "team b")', "bob") == '("Team A" "team a" "iPad" "ipad" "Club C" "club c")'
    assert helper.new_subjects(facts, '("brasília" "team b")', "bob", 1) == '("Team A" "team a")'
    assert helper.new_subjects(facts, '("Team A" "ipad" "club c" "team b")', "bob") == "()"
    assert helper.new_subjects("()", '("x")', "bob") == "()"
    # Omega stored the fact as "team a"; other agents wrote "Team A". The
    # lowercase key is not enough if that first round missed the capitals.
    learned = '(("team a" "is_playing" "2026 championship" "bob" "2026-10-28 10:00:00" 1.0))'
    about_a = "bob: What do you know about Team A?"
    assert helper.new_subjects(learned, '("team a")', "bob", 3, about_a) == '("Team A")'
    assert helper.new_subjects(
        '(("team a" "is_playing" "2026 championship" "bob" "" 1.0) ("Team A" "jersey_color" "blue" "" "" 1.0))',
        '("team a")', "bob", 3, about_a) == "()"


def test_conjunction_queries_pair_each_value_with_the_first_in_every_spelling(helper):
    message = "arturgontijo: Which team has its logo blue and won the 2009 championship?"
    assert helper.conjunction_queries('("blue" "2009")', message) == (
        '(((, (Evaluation (Predicate $r1) (List (Concept $s) (Concept "blue")))'
        ' (Evaluation (Predicate $r2) (List (Concept $s) (Concept "2009"))))'
        ' (($s $r1 "blue" "" "" 1.0) ($s $r2 "2009" "" "" 1.0))))'
    )
    # A value spelled with capitals in the message is tried that way too; a third value pairs with the first.
    queries = helper.conjunction_queries('("lisbon" "acme" "tea")', "bob: Who lives in Lisbon, works at Acme and likes tea?")
    patterns = queries.split("((, ")[1:]
    assert len(patterns) == 6
    assert '(Concept "Lisbon")' in queries and '(Concept "Acme")' in queries
    assert all(p.count("(Evaluation") == 2 for p in patterns)
    # A value of several words is also tried word by word, as it is most likely stored as one of them.
    queries = helper.conjunction_queries('("blue" "2009 championship")', message)
    assert [m.group(1) for m in re.finditer(r'\$r2\) \(List \(Concept \$s\) \(Concept "([^"]*)"', queries)] == [
        "2009 championship", "2009", "championship"]
    assert helper.conjunction_queries('("blue")', message) == "()"


def test_conjunction_facts_keep_only_subjects_related_to_every_value(helper):
    facts = ('(("Team A" "logo_color" "blue" "" "" 1.0) ("Team A" "won_national_championship" "2009" "" "" 1.0)'
             ' ("Team B" "jersey_color" "blue" "" "" 1.0) ("Team B" "founded_year" "1982" "" "" 1.0))')
    team_a = '(("Team A" "logo_color" "blue" "" "" 1.0) ("Team A" "won_national_championship" "2009" "" "" 1.0))'
    assert helper.conjunction_facts(facts, '("blue" "2009")') == team_a
    # The message spelling and a word of a longer value count as the same value.
    assert helper.conjunction_facts('(("ana" "lives_in" "Lisbon" "" "" 1.0) ("ana" "works_at" "acme" "" "" 1.0))',
                                    '("lisbon" "acme")') == (
        '(("ana" "lives_in" "Lisbon" "" "" 1.0) ("ana" "works_at" "acme" "" "" 1.0))')
    assert helper.conjunction_facts(facts, '("blue" "2009 championship")', "bob: who won the 2009 championship?") == team_a
    assert helper.conjunction_facts(facts, '("blue" "1982")') == (
        '(("Team B" "jersey_color" "blue" "" "" 1.0) ("Team B" "founded_year" "1982" "" "" 1.0))'
    )
    assert helper.conjunction_facts(facts, '("blue" "2022")') == "()"
    assert helper.conjunction_facts("()", '("blue" "2009")') == "()"
    # Tuples without a strength (older callers) are read as believed true.
    assert helper.conjunction_facts('(("x" "a" "blue" "" "") ("x" "b" "2009" "" ""))', '("blue" "2009")') == (
        '(("x" "a" "blue" "" "" 1.0) ("x" "b" "2009" "" "" 1.0))'
    )


def test_denials_are_extracted_and_a_denied_fact_is_described_as_not_so(helper):
    reply = "FACT Team A | is playing | 2026 championship\nNOT Team B | is playing | 2026 championship\nNOT none | x | y"
    assert helper.extracted_facts(reply) == '("Team A | is playing | 2026 championship")'
    assert helper.extracted_denials(reply) == '("Team B | is playing | 2026 championship" "none | x | y")'
    assert helper.extracted_denials("NONE") == "()"
    # The model often writes FACT for a denial; the message is what makes it NOT.
    denied = "arturgontijo: Team B is not playing the 2026 championship."
    assert helper.extracted_facts("FACT Team B | plays | 2026 championship", denied) == "()"
    assert helper.extracted_denials("FACT Team B | plays | 2026 championship", denied) == (
        '("Team B | plays | 2026 championship")')
    moved = "bob: I no longer live in Lisbon, I moved to Porto."
    both = "FACT I | lives in | Lisbon\nFACT I | lives in | Porto"
    assert helper.extracted_facts(both, moved) == '("I | lives in | Porto")'
    assert helper.extracted_denials(both, moved) == '("I | lives in | Lisbon")'
    playing = "arturgontijo: Team A is playing the 2026 championship."
    assert helper.extracted_facts("FACT Team A | plays in | 2026 championship", playing) == (
        '("Team A | plays in | 2026 championship")')
    assert helper.extracted_denials("FACT Team A | plays in | 2026 championship", playing) == "()"
    assert "NOT subject | relation | value" in helper.FACT_EXTRACTION_PROMPT
    facts = ('(("team b" "is_playing" "2026 championship" "bob" "2026-10-27 23:00:00" 0.0) '
             '("bob" "likes" "tea" "bob" "2026-10-27 22:00:00" 0.0) '
             '("bob" "favorite_color" "blue" "bob" "2026-10-27 21:00:00" 0.0) '
             '("bob" "has" "dog" "bob" "2026-10-27 20:00:00" 0.0) '
             '("bob" "lives_in" "porto" "bob" "2026-10-27 19:00:00" 0.0) '
             '("bob" "lives_in" "lisbon" "bob" "2026-10-27 18:00:00" 1.0))')
    assert helper.describe_facts(facts, "bob: where do I live?") == (
        "team b is not playing 2026 championship (said by you on 2026-10-27 23:00:00); "
        "you do not like tea (said by you on 2026-10-27 22:00:00); "
        "your favorite color is not blue (said by you on 2026-10-27 21:00:00); "
        "you do not have dog (said by you on 2026-10-27 20:00:00); "
        "you do not live in porto (said by you on 2026-10-27 19:00:00); "
        "you live in lisbon (said by you on 2026-10-27 18:00:00)."
    )
    assert helper.describe_facts('(("Team B" "jersey_color" "red" "" "" 0.0))', "ana: hi") == (
        "Team B's jersey color is not red."
    )


def test_merge_facts_prefers_the_sourced_copy_of_a_fact(helper):
    facts = ('(("Team B" "jersey_color" "red" "" "" 1.0) ("team b" "supporters" "90000" "ana" "2026-10-27 10:00:00" 1.0)'
             ' ("team b" "supporters" "90000" "" "" 1.0) ("Team B" "jersey_color" "red" "" "" 1.0)'
             ' ("team b" "is_playing" "2026 championship" "" "" 1.0)'
             ' ("team b" "is_playing" "2026 championship" "bob" "2026-10-27 11:00:00" 0.0))')
    assert helper.merge_facts(facts) == (
        '(("Team B" "jersey_color" "red" "" "" 1.0) ("team b" "supporters" "90000" "ana" "2026-10-27 10:00:00" 1.0)'
        ' ("team b" "is_playing" "2026 championship" "bob" "2026-10-27 11:00:00" 0.0))'
    )
    assert helper.merge_facts("()") == "()"


def test_drop_denied_removes_facts_the_speaker_denied(helper):
    facts = ('(("team b" "jersey_color" "red" "" "" 1.0) ("team b" "is_playing" "2026 championship" "" "" 1.0)'
             ' ("team a" "is_playing" "2026 championship" "" "" 1.0))')
    assert helper.fact_subjects(facts) == '("team b" "team a")'
    beliefs = '(("team b" "is_playing" "2026 championship" 0.0) ("team a" "is_playing" "2026 championship" 1.0))'
    assert helper.drop_denied(facts, beliefs) == (
        '(("team b" "jersey_color" "red" "" "" 1.0) ("team a" "is_playing" "2026 championship" "" "" 1.0))'
    )
    assert helper.drop_denied(facts, "()") == facts


def test_is_token_limit_reply_recognises_the_provider_message(helper):
    assert helper.is_token_limit_reply(
        '(send "The agent didn\'t return an answer: reasoning exceeded the token limit (4000 tokens).")')
    assert not helper.is_token_limit_reply("FACT I | likes | tea")
    assert not helper.is_token_limit_reply("NONE")


def test_needs_fact_extraction_skips_commands_and_short_acknowledgements(helper):
    assert helper.needs_fact_extraction("arturgontijo: My favorite color is blue")
    assert helper.needs_fact_extraction("arturgontijo: Brasília?")
    assert not helper.needs_fact_extraction("arturgontijo: ok thanks")
    assert not helper.needs_fact_extraction("arturgontijo: auth choose-a-secret")
    assert not helper.needs_fact_extraction("arturgontijo: metta (+ 1 2)")
    assert not helper.needs_fact_extraction("")


def test_fact_index_round_trip(helper):
    doc = helper.fact_index_text("brazil", "capital", "brasília")
    assert doc == "FACT brazil | capital | brasília"
    results = f'[["2026-10-23 08:00:00", "{doc}"], ["2026-10-22 09:00:00", "a note"], ' \
              '["2026-10-22 09:00:00", "FACT Divinópolis | population | 250k"]]'
    assert helper.indexed_fact_subjects(results, 3) == '("brazil" "divinópolis")'
    assert helper.indexed_fact_subjects("[]") == "()"


def test_recall_keys_prefer_lookups_then_index_then_words(helper):
    message = "arturgontijo: How big is the Brazilian capital?"
    assert helper.recall_keys(message, '("brazil" "brasilia")', '("brasília")', 3) == (
        '("brazil" "brasilia" "brasília")'
    )
    assert helper.recall_keys(message, '("arturgontijo" "brazil")', "()", 3) == '("brazil")'
    # Without LOOKUP lines only capitalised words are worth a query.
    assert helper.recall_keys(message, "()", "()", 3) == '("brazilian")'
    assert helper.recall_keys("bob: How can we classify Divinópolis city?", "()", "()", 3) == '("divinópolis")'
    assert helper.recall_keys("bob: Remind me what laptop I ordered. Ana knows.", "()", "()", 3) == '("ana")'
    assert helper.recall_keys("no sender here", '("x" "y")', "()", 1) == '("x")'
    # An indexed fact about someone else must not replace the name the question asked.
    about_a = "arturgontijo: What do you know about Team A?"
    assert helper.recall_keys(about_a, '("team a")', '("team b")', 3) == '("team a")'
    assert helper.extracted_lookups("LOOKUP Team A", about_a) == '("team a")'
    # A follow-up that names nothing keeps the previous keys, not the last learned fact.
    assert helper.recall_keys("arturgontijo: Try again", "()", '("team b")', 3, '("team a")') == '("team a")'
    # A new question that names nothing still uses the index (fuzzy recall).
    assert helper.recall_keys("bob: who is poor?", "()", '("divinópolis")', 3, '("team a")') == '("divinópolis")'
    # A statement has a FACT and no LOOKUP; its subject is the key, not the previous turn's.
    stated = "arturgontijo: Team A is playing the 2026 championship."
    assert helper.extracted_lookups("FACT Team A | is playing | 2026 championship", stated) == '("team a")'
    assert helper.extracted_lookups("NOT Team B | plays in | 2026 championship",
                                    "arturgontijo: Team B is not playing the 2026 championship.") == '("team b")'
    assert helper.recall_keys(stated, '("team a")', '("team b")', 3, '("team b")') == '("team a")'


def test_parse_fact_drops_the_copula_of_a_longer_relation(helper):
    assert helper.parse_fact("human | is similar to | monkey", "bob: hi") == '("human" "similar_to" "monkey")'
    assert helper.parse_fact("human | similar to | chimp", "bob: hi") == '("human" "similar_to" "chimp")'
    assert helper.parse_fact("banana | is a | fruit", "bob: hi") == '("banana" "is_a" "fruit")'
    assert helper.parse_fact("bob | is | tall", "bob: hi") == '("bob" "is" "tall")'


def test_describe_facts_lists_the_newest_fact_first(helper):
    facts = ('(("human" similar_to "monkey" "bob" "2026-10-27 11:23:00") '
             '("human" "similar_to" "chimp" "bob" "2026-10-27 11:33:00"))')
    assert helper.describe_facts(facts, "ana: hi") == (
        "human's similar to is chimp (said by bob on 2026-10-27 11:33:00); "
        "human's similar to is monkey (said by bob on 2026-10-27 11:23:00)."
    )


def test_name_variants_add_the_message_spelling_and_title_case(helper):
    assert helper.name_variants("team b", "ana: What do you know about Team B?") == '("team b" "Team B")'
    assert helper.name_variants("team", "ana: What do you know about Team A?") == '("team" "Team" "Team A")'
    assert helper.name_variants("ipad", "ana: Who owns the iPad?") == '("ipad" "iPad" "Ipad")'
    assert helper.name_variants("divinópolis", "") == '("divinópolis" "Divinópolis")'
    assert helper.join_values("2022", "17") == '"2022 17"'


def test_parse_fact_rejects_note_like_relations(helper):
    assert helper.parse_fact("I | note | Brasília was founded in 1960", "bob: hi") == "()"
    # unlearn must still be able to remove such a fact stored by older code
    assert helper.parse_fact_key("I | note", "bob: hi") == '("bob" "note")'
    assert helper.parse_fact("Brasília | founded in | 1960", "bob: hi") == '("brasília" "founded_in" "1960")'


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


def test_balance_recovers_send_glued_with_underscore(helper):
    parsed = helper.balance_parentheses(
        "send_What I know about Team A:\n\n- Color: blue\n- Revenue: 210 000 000"
    )
    assert parsed == (
        '((send "What I know about Team A:\\n\\n- Color: blue\\n- Revenue: 210 000 000"))'
    )
    assert helper.unknown_skill_only(parsed) is False
    assert helper.answered_user(parsed) is True


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
    assert helper.extract_timestamp('("2026-07-30 12:00:00" "foo")') == datetime.datetime(
        2026, 7, 30, 12, 0, 0
    )


def test_extract_timestamp_returns_none_when_absent(helper):
    assert helper.extract_timestamp("no timestamp here") is None
