"""Typed errors and recovery-hint rendering for SuperTon.

The goal: every failure the user sees ends with a one-line "try this next"
hint. This module centralizes both the exception types we raise and the
mapping from error → hint, so the same suggestion appears whether the
failure surfaces in the CLI, the shell, or the MCP server.
"""

from __future__ import annotations

from dataclasses import dataclass

from superton.model import HuggingFaceError, ModelError, OllamaError


class SupertonError(Exception):
    """Base class for SuperTon-specific user-facing errors."""


class ConfigError(SupertonError):
    """Bad value or missing prerequisite in the persisted config."""


class IngestError(SupertonError):
    """Could not parse or store an ingested file."""


class MemoryError(SupertonError):  # noqa: A001 — domain-meaningful name
    """Drawer store could not satisfy a read/write request."""


class ImportError_(SupertonError):
    """Failed to read an external transcript (Claude, ChatGPT, etc.)."""


@dataclass(frozen=True)
class _Hint:
    summary: str
    hint: str


def hint_for(exc: BaseException) -> _Hint:
    """Map a known exception to (summary, recovery-hint)."""
    if isinstance(exc, OllamaError):
        return _Hint(
            summary="cannot reach Ollama",
            hint="start it with [bold]ollama serve[/bold] or run [bold]superton init[/bold]",
        )
    if isinstance(exc, HuggingFaceError):
        return _Hint(
            summary="Hugging Face request failed",
            hint="check [bold]HF_TOKEN[/bold] and your network, or switch to Ollama",
        )
    if isinstance(exc, ModelError):
        return _Hint(
            summary="no model backend available",
            hint="run [bold]superton init[/bold] or set [bold]SUPERTON_MODEL_BACKEND[/bold]",
        )
    if isinstance(exc, IngestError):
        return _Hint(summary=str(exc) or "could not ingest file", hint="see [bold]superton doctor[/bold]")
    if isinstance(exc, ConfigError):
        return _Hint(
            summary=str(exc) or "bad configuration",
            hint="edit [bold]~/.superton/config.toml[/bold] or unset the bad env var",
        )
    if isinstance(exc, MemoryError):
        return _Hint(
            summary=str(exc) or "palace error",
            hint="run [bold]superton reindex[/bold] to rebuild the index",
        )
    if isinstance(exc, FileNotFoundError):
        return _Hint(summary=f"not found: {exc.filename or exc}", hint="check the path and try again")
    if isinstance(exc, PermissionError):
        return _Hint(summary=f"permission denied: {exc}", hint="check file ownership and permissions")
    return _Hint(summary=str(exc) or exc.__class__.__name__, hint="re-run with [bold]SUPERTON_LOG=debug[/bold] for details")


def render(exc: BaseException) -> None:
    """Print a uniform two-line error + hint via the active theme."""
    from superton import ui  # local import to dodge circular deps at module load

    h = hint_for(exc)
    ui.err(h.summary)
    ui.hint(h.hint)
