"""Pure-function tests for shell helpers — no model required."""

from __future__ import annotations

import pytest

from superton.shell import (
    _contextualize_query,
    _format_history,
    _format_suggestions,
    _is_meta_question,
    _looks_memory_specific,
    _query_tokens,
    _should_retrieve,
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
