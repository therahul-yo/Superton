"""Pure chat orchestration logic for the shell.

This module owns the *decision* part of "user asked a question": meta-question
detection, retrieval, expansion, refusal, system-prompt construction. It does
NOT touch the console — it streams text through generators and returns a
typed result that the caller renders however it wants.

The shell wraps this in `ui.stream_answer()`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from superton.logging import get_logger
from superton.memory import Memory, SearchHit
from superton.model import ModelError

log = get_logger("chat")

# These mirror the constants that lived in shell.py — re-exported so callers
# don't import private shell internals.
ANSWER_CONTEXT_DRAWERS = 10
ANSWER_DRAWER_CHARS = 1200
CONVERSATION_WINDOW = 6


GREETINGS = {"hi", "hey", "hello", "yo", "sup", "hwy", "hye", "heey", "helo"}

_TYPO_MAP = {
    "waht": "what", "wut": "what", "wat": "what", "wha": "what",
    "r": "are", "ur": "your", "u": "you", "ure": "your",
    "teh": "the", "hwo": "how", "fo": "for",
}

# Questions about the assistant itself.
META_PHRASES = (
    "what are you", "what r u", "what are u",
    "who are you", "who r u", "who are u",
    "what can you do", "what do you do",
    "what is your use", "what is ur use", "whats your use", "whats ur use",
    "tell me about yourself", "introduce yourself",
    "what is this", "whats this", "wats this",
    "how do you work", "how does this work",
    "what r u for", "what are u for",
)

STOPWORDS = {
    "a", "about", "an", "and", "are", "from", "give", "gimme", "how", "i",
    "in", "is", "it", "me", "my", "of", "on", "the", "this", "to", "u",
    "use", "what", "you",
}


# --- query analysis -----------------------------------------------------------


def query_tokens(query: str) -> set[str]:
    cleaned = "".join(ch.lower() if ch.isalnum() else " " for ch in query)
    return {token for token in cleaned.split() if len(token) > 1 and token not in STOPWORDS}


def looks_memory_specific(query: str) -> bool:
    """True when the query names a personal document the user expects to exist."""
    normalized = query.lower()
    personal_markers = (
        "resume", "resue", "cv", "pdf", "document", "file",
        "from my", "from his", "fromhis",
    )
    return any(marker in normalized for marker in personal_markers)


def wants_source_expansion(query: str) -> bool:
    normalized = query.lower()
    exhaustive_markers = (
        "all", "every", "list", "projects", "project", "experience",
        "resume", "resue", "cv", "document", "pdf", "full",
    )
    return any(marker in normalized for marker in exhaustive_markers)


def is_meta_question(query: str) -> bool:
    normalized = query.lower().strip(" !?.")
    if normalized in GREETINGS:
        return True
    fixed = " ".join(_TYPO_MAP.get(w, w) for w in normalized.split())
    for phrase in META_PHRASES:
        if fixed == phrase:
            return True
        phrase_len = len(phrase.split())
        if fixed.startswith(phrase + " ") and len(fixed.split()) <= phrase_len + 1:
            return True
    return False


def should_retrieve(query: str) -> bool:
    return not is_meta_question(query)


def relevant_hits(question: str, hits: list[SearchHit]) -> list[SearchHit]:
    """Re-rank hits so keyword-overlap moves up without filtering anything out."""
    if not hits:
        return []
    tokens = query_tokens(question)
    if not tokens:
        return list(hits)
    scored: list[tuple[float, int, SearchHit]] = []
    for idx, hit in enumerate(hits):
        haystack = f"{Path(hit.drawer.source).name} {hit.drawer.text[:2500]}".lower()
        matches = sum(1 for token in tokens if token in haystack)
        base = float(getattr(hit, "score", 0.0) or 0.0)
        boost = 0.15 * matches
        scored.append((base + boost, -idx, hit))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [h for _, _, h in scored]


def any_token_match(question: str, hits: list[SearchHit]) -> bool:
    tokens = query_tokens(question)
    if not tokens:
        return False
    for hit in hits:
        haystack = f"{Path(hit.drawer.source).name} {hit.drawer.text[:2500]}".lower()
        if any(token in haystack for token in tokens):
            return True
    return False


def expand_hits_for_answer(
    mem: Memory,
    question: str,
    hits: list[SearchHit],
    *,
    max_drawers: int = ANSWER_CONTEXT_DRAWERS,
) -> list[SearchHit]:
    """For document/list queries, pull sibling chunks from matched sources."""
    ranked = list(hits)
    if not ranked or not wants_source_expansion(question):
        return ranked[:max_drawers]

    expanded: list[SearchHit] = []
    seen_ids: set[str] = set()

    def add_hit(hit: SearchHit) -> None:
        drawer_id = getattr(hit.drawer, "id", "")
        if drawer_id and drawer_id not in seen_ids:
            seen_ids.add(drawer_id)
            expanded.append(hit)

    for hit in ranked:
        add_hit(hit)

    source_order: list[str] = []
    seen_sources: set[str] = set()
    for hit in ranked:
        source = hit.drawer.source
        if source not in seen_sources:
            seen_sources.add(source)
            source_order.append(source)

    for source in source_order:
        source_drawers = mem.drawers_for_source(source, limit=max_drawers)
        for drawer in source_drawers:
            if len(expanded) >= max_drawers:
                break
            add_hit(SearchHit(drawer=drawer, score=0.70))
        if len(expanded) >= max_drawers:
            break
    return expanded[:max_drawers]


def format_history(history: list[tuple[str, str]]) -> str:
    """Render recent turns for the prompt — compact, role-tagged.

    Currently unused by the prompt builder (we pass structured `chat_history`
    instead) but kept as a public helper for transcript rendering.
    """
    if not history:
        return ""
    lines: list[str] = []
    for role, text in history[-CONVERSATION_WINDOW:]:
        lines.append(f"{role}: {text.strip()}")
    return "\n".join(lines)


def contextualize_query(question: str, history: list[tuple[str, str]] | None) -> str:
    """Prepend the most recent user turn for short follow-ups."""
    if not history:
        return question
    if len(question.split()) >= 5:
        return question
    last_user = None
    for role, text in reversed(history):
        if role == "user":
            last_user = text
            break
    if not last_user:
        return question
    return f"{last_user} {question}"


def format_suggestions(raw_hits: list[SearchHit], limit: int = 2) -> str:
    if not raw_hits:
        return ""
    seen: set[str] = set()
    lines: list[str] = []
    for hit in raw_hits:
        src = Path(hit.drawer.source).name
        if src in seen:
            continue
        seen.add(src)
        lines.append(f"  • {src}")
        if len(lines) >= limit:
            break
    return "\n".join(lines)


# --- prompt construction ------------------------------------------------------


def build_system_prompt(*, has_drawers: bool) -> str:
    if has_drawers:
        # Framed as plain document QA on purpose: small models carry strong
        # privacy-refusal training, and words like "memory" or "personal
        # data access" trigger canned "I don't have access" replies even
        # with the context right there in the prompt.
        return (
            "You are Superton, a document QA assistant. The user gives you "
            "excerpts from their own files, then a question. Answer the "
            "question directly using the excerpts. Quote specific names, "
            "numbers, and facts. Cite excerpt ids inline like [abcd1234]. "
            "If asked for all/list items, scan every excerpt and list every "
            "distinct item you find. "
            "Never mention access, permissions, or what you can or cannot "
            "see. Never ask for a file, link, or path. "
            "If the excerpts lack the answer, say only: not yet in the "
            "palace. Keep answers under 8 lines unless asked for detail."
        )
    return (
        "You are Superton — a small local AI assistant built into the "
        "SuperTon CLI. You run entirely on the user's machine via Ollama "
        "and answer questions grounded in their personal palace of memories "
        "(notes, documents, past AI-tool conversations). No memory drawers "
        "were retrieved for this message, so answer briefly and "
        "conversationally as a normal assistant. If asked who you are or "
        "what you do, give a short one-paragraph self-introduction. Keep "
        "answers under 6 lines."
    )


def _build_context_block(hits: list[SearchHit]) -> str:
    return "\n\n---\n\n".join(
        f"[drawer:{h.drawer.id[:8]} source:{Path(h.drawer.source).name}]\n"
        f"{h.drawer.text[:ANSWER_DRAWER_CHARS]}"
        for h in hits[:ANSWER_CONTEXT_DRAWERS]
    )


# --- orchestration ------------------------------------------------------------


class _ModelLike(Protocol):
    def generate(
        self,
        prompt: str,
        system: str | None = ...,
        history: list[dict[str, str]] | None = ...,
    ) -> Iterator[str]: ...

    def backend(self) -> str | None: ...

    def start_ollama(self, *, timeout: float = ...) -> bool: ...


@dataclass
class ChatTurn:
    """One round of the conversation, including its grounding."""

    question: str
    answer: str = ""
    hits: list[SearchHit] = field(default_factory=list)
    refused: bool = False
    error: str | None = None


@dataclass
class PlannedAnswer:
    """The retrieval/refusal decision before the model is called."""

    hits: list[SearchHit]
    raw_hits: list[SearchHit]
    system: str
    prompt: str
    chat_history: list[dict[str, str]]
    refusal: str | None = None  # populated when we should NOT call the model


def plan_answer(
    mem: Memory,
    question: str,
    history: list[tuple[str, str]] | None = None,
) -> PlannedAnswer:
    """Run retrieval, refusal checks, and prompt assembly without calling the model.

    Returns a `PlannedAnswer` the caller passes straight to
    `ui.stream_answer`. Splitting plan/execute lets the shell render
    citations before the model finishes streaming.
    """
    search_query = contextualize_query(question, history)
    raw_hits = mem.search(search_query, limit=8) if should_retrieve(question) else []
    hits = expand_hits_for_answer(mem, question, relevant_hits(question, raw_hits))

    # Refuse memory-specific queries when no hit shares any meaningful token.
    if looks_memory_specific(question) and not any_token_match(question, hits):
        base = "I do not have matching memory for that."
        suggestions = format_suggestions(raw_hits)
        if suggestions:
            refusal = (
                f"{base}\n\n"
                "Did you mean one of these?\n"
                f"{suggestions}\n\n"
                "Ask about one of those, or add the source with `/add <path>`."
            )
        else:
            refusal = (
                f"{base} Add the resume or document first with "
                "`/add <path>` or paste the file path directly."
            )
        return PlannedAnswer(
            hits=[],
            raw_hits=raw_hits,
            system=build_system_prompt(has_drawers=False),
            prompt=question,
            chat_history=[],
            refusal=refusal,
        )

    context = _build_context_block(hits)
    system = build_system_prompt(has_drawers=bool(hits))

    if is_meta_question(question) or hits:
        # Clean slate for meta questions AND drawer-grounded answers. The
        # small model parrots its previous reply verbatim when it sees its
        # own answers in history; with drawers retrieved, the excerpts are
        # the only context that matters. History still feeds
        # contextualize_query above, so follow-ups retrieve correctly.
        chat_history: list[dict[str, str]] = []
    else:
        chat_history = [
            {"role": "user" if role == "user" else "assistant", "content": text}
            for role, text in (history or [])[-CONVERSATION_WINDOW * 2:]
        ]

    if hits:
        # Bare keyword queries ("rahul college", "commits") make small
        # models miss the relevant excerpt; phrasing them as a question
        # reliably focuses the answer.
        asked = question
        if "?" not in question and len(query_tokens(question)) <= 3:
            asked = f"What do the excerpts say about: {question}? Give the specific facts."
        prompt = "\n\n".join([
            f"FILE EXCERPTS:\n\n{context}",
            f"QUESTION: {asked}",
            "Answer from the excerpts above, concisely — not a dump of the context.",
        ])
    else:
        prompt = question

    return PlannedAnswer(
        hits=hits,
        raw_hits=raw_hits,
        system=system,
        prompt=prompt,
        chat_history=chat_history,
    )


def stream_answer(model: _ModelLike, plan: PlannedAnswer) -> Iterator[str]:
    """Yield tokens for `plan`. Raises ModelError if no backend is reachable.

    Caller-side fallback for `ModelError` is responsible for showing a
    helpful refusal that still cites the retrieved drawers.
    """
    if plan.refusal is not None:
        yield plan.refusal
        return

    backend = getattr(model, "backend", lambda: None)()
    if backend is None:
        starter = getattr(model, "start_ollama", None)
        if callable(starter):
            starter(timeout=5.0)

    yield from model.generate(plan.prompt, system=plan.system, history=plan.chat_history)


def fallback_answer(plan: PlannedAnswer) -> str:
    """Produce a non-model answer when the backend is unavailable."""
    if plan.hits:
        top = plan.hits[0]
        return (
            "I found related memory, but the model backend is unavailable. "
            f"Top match: [{top.drawer.id[:8]}] {Path(top.drawer.source).name}"
        )
    return "Superton is not available. Run `superton init` to start/build the local model."


def answer(
    mem: Memory,
    model: _ModelLike,
    question: str,
    history: list[tuple[str, str]] | None = None,
    on_token: Callable[[str], None] | None = None,
) -> ChatTurn:
    """End-to-end: plan, stream, collect.

    `on_token` is invoked for each streamed token so callers can update a
    live widget. Returns a `ChatTurn` carrying the full answer, the cited
    hits, and a flag indicating whether the model was refused/errored.
    """
    plan = plan_answer(mem, question, history=history)
    if plan.refusal is not None:
        log.info("refusing memory-specific question with no token overlap")
        return ChatTurn(question=question, answer=plan.refusal, hits=[], refused=True)

    buf: list[str] = []
    try:
        for tok in stream_answer(model, plan):
            buf.append(tok)
            if on_token is not None:
                on_token(tok)
    except ModelError as e:
        log.warning("model backend unavailable during answer: %s", e)
        text = fallback_answer(plan)
        return ChatTurn(
            question=question,
            answer=text,
            hits=plan.hits,
            error=str(e),
        )

    text = "".join(buf).strip()
    if not text:
        text = "I found related memory, but Superton returned an empty answer."
    return ChatTurn(question=question, answer=text, hits=plan.hits)
