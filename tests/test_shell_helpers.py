"""Pure-function tests for shell helpers — no model required."""

from __future__ import annotations

import pytest

from superton.shell import (
    _contextualize_query,
    _format_history,
    _format_suggestions,
    _is_meta_question,
    _looks_memory_specific,
    _path_from_input,
    _query_tokens,
    _resolve_repl_path,
    _should_retrieve,
    _unescape_shell_path,
    _wants_source_expansion,
)


@pytest.mark.parametrize(
    "phrase",
    ["hi", "hello", "what are you", "who are you", "what can you do", "tell me about yourself"],
)
def test_meta_questions_recognized(phrase: str):
    assert _is_meta_question(phrase)


@pytest.mark.parametrize(
    "phrase",
    [
        "what is this file about please",  # too many trailing tokens
        "what are my resume projects",
        "tell me about quarterly numbers",
        "summarize the third paragraph",
    ],
)
def test_real_questions_not_meta(phrase: str):
    assert not _is_meta_question(phrase)


def test_meta_question_with_trailing_filler():
    assert _is_meta_question("what are you exactly")


def test_meta_question_with_typos():
    assert _is_meta_question("wat r u")


def test_should_retrieve_skips_greetings():
    assert _should_retrieve("hello") is False
    assert _should_retrieve("what is the deployment plan") is True


def test_query_tokens_filters_stopwords():
    tokens = _query_tokens("what are my projects from resume")
    assert "projects" in tokens
    assert "resume" in tokens
    assert "what" not in tokens
    assert "my" not in tokens


def test_query_tokens_drops_short_tokens():
    assert "a" not in _query_tokens("a quick brown fox")
    assert "brown" in _query_tokens("a quick brown fox")


def test_looks_memory_specific_detects_resume():
    assert _looks_memory_specific("alice resume projects")
    assert _looks_memory_specific("from my pdf")


def test_looks_memory_specific_negative_case():
    assert not _looks_memory_specific("how do I write a python loop")


def test_wants_source_expansion_for_list_queries():
    assert _wants_source_expansion("list all projects")
    assert _wants_source_expansion("full resume contents")
    assert not _wants_source_expansion("when was python released")


def test_format_history_renders_role_tags():
    out = _format_history([("user", "hi"), ("assistant", "hello")])
    assert "user: hi" in out
    assert "assistant: hello" in out


def test_format_history_empty():
    assert _format_history([]) == ""


def test_contextualize_short_followup_prepends_prior():
    history = [("user", "show me my resume"), ("assistant", "...")]
    out = _contextualize_query("what about projects", history)
    assert "resume" in out
    assert "projects" in out


def test_contextualize_long_query_passthrough():
    history = [("user", "show me my resume"), ("assistant", "...")]
    long_query = "tell me everything about quarterly performance reports"
    assert _contextualize_query(long_query, history) == long_query


def test_contextualize_no_history():
    assert _contextualize_query("hi", None) == "hi"


def test_format_suggestions_dedupes_by_source():
    class _Drawer:
        def __init__(self, source: str):
            self.source = source

    class _Hit:
        def __init__(self, source: str):
            self.drawer = _Drawer(source)

    hits = [_Hit("/a.pdf"), _Hit("/a.pdf"), _Hit("/b.pdf")]
    out = _format_suggestions(hits)
    assert out.count("a.pdf") == 1
    assert "b.pdf" in out


def test_format_suggestions_empty():
    assert _format_suggestions([]) == ""


# --- shell-style path unescape (drag-and-drop on macOS Terminal) ----------


def test_unescape_shell_path_drops_backslash_spaces():
    raw = r"/Users/alice/Downloads/Lord\ of\ Mysteries\ -\ Book\ 1.epub"
    assert _unescape_shell_path(raw) == "/Users/alice/Downloads/Lord of Mysteries - Book 1.epub"


def test_unescape_shell_path_handles_parens_and_amp():
    raw = r"/tmp/foo\&bar/baz\(1\).pdf"
    assert _unescape_shell_path(raw) == "/tmp/foo&bar/baz(1).pdf"


def test_unescape_shell_path_idempotent_for_clean_paths():
    raw = "/tmp/already-clean/file.txt"
    assert _unescape_shell_path(raw) == raw


def test_unescape_shell_path_preserves_trailing_backslash():
    # Lone trailing backslash has no character to consume → keep it.
    assert _unescape_shell_path("/tmp/odd\\") == "/tmp/odd\\"


def test_resolve_repl_path_unescapes_and_strips_quotes(tmp_path):
    target = tmp_path / "Lord of Mysteries - Book 1.epub"
    target.write_text("epub")
    # Mimic what drag-and-drop would produce:
    raw = (
        str(tmp_path)
        + r"/Lord\ of\ Mysteries\ -\ Book\ 1.epub"
    )
    path = _resolve_repl_path(raw)
    assert path == target
    assert path.exists()


def test_resolve_repl_path_strips_wrapping_single_quotes(tmp_path):
    target = tmp_path / "hello world.txt"
    target.write_text("x")
    path = _resolve_repl_path(f"'{target}'")
    assert path == target


def test_path_from_input_detects_dropped_escaped_path(tmp_path):
    # Bare input (no /add prefix) should still auto-detect a file that
    # exists once you unescape the shell quoting.
    target = tmp_path / "Screenshot 2026-05-18 at 9.09.46 PM.png"
    target.write_bytes(b"png")
    raw = str(target).replace(" ", "\\ ")
    assert _path_from_input(raw) == target


def test_path_from_input_returns_none_for_question_text():
    assert _path_from_input("what is the capital of france") is None


def test_path_from_input_returns_none_for_nonexistent_path():
    assert _path_from_input("/definitely/not/a/real/path/anywhere.xyz") is None


# --- slash-command typo suggestions + path completion ---------------------------


def test_suggest_command_fixes_close_typo():
    from superton.shell import _suggest_command

    assert _suggest_command("/serach auth") == "/search"
    assert _suggest_command("/them") == "/theme"
    assert _suggest_command("/impotr claude-code") == "/import"


def test_suggest_command_returns_none_for_garbage():
    from superton.shell import _suggest_command

    assert _suggest_command("/zzzqqq") is None


def test_known_commands_cover_command_help():
    from superton.shell import COMMAND_HELP, KNOWN_COMMANDS

    assert set(COMMAND_HELP) <= KNOWN_COMMANDS


def test_command_groups_only_reference_known_commands():
    from superton.shell import COMMAND_GROUPS, KNOWN_COMMANDS

    heads = {
        cmd.split()[0]
        for _, commands in COMMAND_GROUPS
        for cmd, _ in commands
    }
    assert heads <= KNOWN_COMMANDS


def test_path_completion_lists_directory(tmp_path):
    from superton.shell import _path_completion_candidates

    (tmp_path / "docs").mkdir()
    (tmp_path / "readme.md").write_text("x")
    completions = dict(_path_completion_candidates(f"{tmp_path}/"))
    assert "docs/" in completions
    assert "readme.md" in completions


def test_path_completion_filters_by_prefix(tmp_path):
    from superton.shell import _path_completion_candidates

    (tmp_path / "notes.md").write_text("x")
    (tmp_path / "other.md").write_text("x")
    names = [text for text, _ in _path_completion_candidates(f"{tmp_path}/no")]
    assert names == ["notes.md"]


def test_path_completion_hides_dotfiles_unless_asked(tmp_path):
    from superton.shell import _path_completion_candidates

    (tmp_path / ".secret").write_text("x")
    (tmp_path / "visible.md").write_text("x")
    plain = [text for text, _ in _path_completion_candidates(f"{tmp_path}/")]
    assert ".secret" not in plain
    dotted = [text for text, _ in _path_completion_candidates(f"{tmp_path}/.se")]
    assert ".secret" in dotted


def test_path_completion_bad_directory_is_empty():
    from superton.shell import _path_completion_candidates

    assert _path_completion_candidates("/definitely/not/here/") == []
