"""Tests for the extracted `superton.chat` orchestration module."""

from __future__ import annotations

from pathlib import Path

import pytest

from superton import chat
from superton.config import Config
from superton.memory import Memory


@pytest.fixture
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    monkeypatch.setenv("SUPERTON_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERTON_MEMORY_BACKEND", "sqlite")
    return Config.load()


# --- pure helpers ----------------------------------------------------------


def test_query_tokens_strips_stopwords():
    tokens = chat.query_tokens("what are my projects from resume")
    assert "projects" in tokens
    assert "resume" in tokens
    assert "what" not in tokens


def test_is_meta_question_greeting():
    assert chat.is_meta_question("hi")
    assert chat.is_meta_question("hello")


def test_is_meta_question_phrase():
    assert chat.is_meta_question("what are you")


def test_is_meta_question_not_real_query():
    assert not chat.is_meta_question("what is my resume project")


def test_looks_memory_specific():
    assert chat.looks_memory_specific("from my pdf")
    assert not chat.looks_memory_specific("how do I write a loop")


def test_wants_source_expansion():
    assert chat.wants_source_expansion("list all projects")
    assert not chat.wants_source_expansion("when was python released")


def test_contextualize_short_followup_prepends_prior():
    history = [("user", "show me my resume"), ("assistant", "...")]
    out = chat.contextualize_query("what about projects", history)
    assert "resume" in out and "projects" in out


def test_contextualize_long_query_passthrough():
    history = [("user", "x"), ("assistant", "y")]
    long_q = "summarize the project plan and the related risks"
    assert chat.contextualize_query(long_q, history) == long_q


def test_format_history_compact():
    out = chat.format_history([("user", "hi"), ("assistant", "hello")])
    assert "user: hi" in out
    assert "assistant: hello" in out


def test_format_suggestions_dedupes():
    class _Drawer:
        def __init__(self, source):
            self.source = source

    class _Hit:
        def __init__(self, source):
            self.drawer = _Drawer(source)

    out = chat.format_suggestions([_Hit("/a.pdf"), _Hit("/a.pdf"), _Hit("/b.pdf")])
    assert out.count("a.pdf") == 1
    assert "b.pdf" in out


# --- planning / refusal ---------------------------------------------------


def test_plan_answer_returns_refusal_for_memory_specific_no_match(cfg: Config):
    mem = Memory(cfg)
    mem.add(text="unrelated rate limiting note", source="rate.md")
    plan = chat.plan_answer(mem, "what is alice's resume?")
    assert plan.refusal is not None
    assert "matching memory" in plan.refusal
    mem.close()


def test_plan_answer_skips_retrieval_for_meta(cfg: Config):
    mem = Memory(cfg)
    mem.add(text="real content", source="x.md")
    plan = chat.plan_answer(mem, "hi")
    assert plan.refusal is None
    # Meta questions get empty chat_history (clean slate for small models).
    assert plan.chat_history == []


def test_plan_answer_includes_drawers_in_prompt_when_hits(cfg: Config):
    mem = Memory(cfg)
    mem.add(text="rate limiting via token bucket", source="notes.md")
    plan = chat.plan_answer(mem, "rate limiting")
    assert plan.hits
    assert "token bucket" in plan.prompt


def test_plan_answer_passes_history(cfg: Config):
    mem = Memory(cfg)
    mem.add(text="recipe for pancakes", source="cook.md")
    history = [("user", "pancakes recipe"), ("assistant", "see above")]
    plan = chat.plan_answer(mem, "and the cooking time", history=history)
    # Non-meta + history → chat_history present.
    assert plan.chat_history
    mem.close()


# --- stream / fallback ----------------------------------------------------


def test_stream_answer_yields_refusal_when_present():
    plan = chat.PlannedAnswer(
        hits=[], raw_hits=[], system="", prompt="", chat_history=[],
        refusal="no memory for that",
    )

    class _Model:
        def backend(self) -> str | None:
            return None

        def generate(self, *args, **kwargs):
            raise AssertionError("should not be called")

    tokens = list(chat.stream_answer(_Model(), plan))
    assert tokens == ["no memory for that"]


def test_fallback_answer_uses_top_hit_when_available(cfg: Config):
    mem = Memory(cfg)
    mem.add(text="rate limiting", source="/x/notes.md")
    plan = chat.plan_answer(mem, "rate limiting")
    text = chat.fallback_answer(plan)
    assert "Top match" in text
    assert "notes.md" in text
    mem.close()


def test_fallback_answer_when_no_hits():
    plan = chat.PlannedAnswer(hits=[], raw_hits=[], system="", prompt="", chat_history=[])
    text = chat.fallback_answer(plan)
    assert "superton init" in text.lower() or "superton init" in text


def test_answer_end_to_end_with_fake_model(cfg: Config):
    mem = Memory(cfg)
    mem.add(text="capital of france is paris", source="geo.md")

    class _Model:
        def backend(self) -> str | None:
            return "ollama"

        def generate(self, prompt, system=None, history=None):
            yield "It's "
            yield "Paris."

    turn = chat.answer(mem, _Model(), "what is the capital of france")
    assert turn.answer == "It's Paris."
    assert not turn.refused
    assert turn.error is None
    mem.close()


def test_answer_records_refusal(cfg: Config):
    mem = Memory(cfg)

    class _Model:
        def backend(self) -> str | None:
            return "ollama"

        def generate(self, *a, **kw):
            raise AssertionError("should not be reached")

    turn = chat.answer(mem, _Model(), "what is in my resume pdf")
    assert turn.refused is True
    assert "matching memory" in turn.answer
    mem.close()


def test_answer_records_error_on_model_failure(cfg: Config):
    mem = Memory(cfg)
    mem.add(text="rate limiting via token bucket", source="notes.md")

    from superton.model import ModelError

    class _BrokenModel:
        def backend(self) -> str | None:
            return "ollama"

        def generate(self, *a, **kw):
            raise ModelError("no backend")

    turn = chat.answer(mem, _BrokenModel(), "rate limiting")
    assert turn.error is not None
    assert "Top match" in turn.answer
    mem.close()


def test_answer_invokes_on_token_callback(cfg: Config):
    mem = Memory(cfg)

    class _Model:
        def backend(self) -> str | None:
            return "ollama"

        def generate(self, *a, **kw):
            yield "ok"

    received: list[str] = []
    chat.answer(mem, _Model(), "hi", on_token=received.append)
    assert received == ["ok"]
    mem.close()
