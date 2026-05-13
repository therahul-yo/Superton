"""Shared implementation of the SuperTon doctor health-check report.

Both the CLI `superton doctor` command and the interactive shell's
`/doctor` slash command call `render_doctor_report(cfg)` so they always
show the same information.
"""

from __future__ import annotations

import shutil

from superton import ui
from superton.config import Config
from superton.memory import Memory
from superton.model import Model


def render_doctor_report(cfg: Config) -> None:
    """Render the doctor health table using the active UI theme."""
    mem = Memory(cfg)
    s = mem.stats()
    mem.close()

    ui.section("doctor")
    table = ui.make_table("check", "status", "detail")

    def row(name: str, ok: bool, detail: str) -> None:
        status = (
            f"[{ui.theme().success}]ok[/]"
            if ok
            else f"[{ui.theme().warning}]warn[/]"
        )
        table.add_row(name, status, detail)

    row("home", cfg.home.exists(), str(cfg.home))
    row("palace", cfg.palace_dir.exists(), str(cfg.palace_dir))
    row("drawers", True, str(s["drawers"]))
    row("memory backend", True, cfg.memory_backend)
    row("model backend", True, cfg.model_backend)
    row("model profile", True, f"{cfg.model_profile} · {cfg.base_model}")
    row("theme", True, f"{cfg.theme} · {ui.theme().label}")

    try:
        import mempalace

        row("mempalace", True, getattr(mempalace, "__version__", "installed"))
    except Exception as e:
        row("mempalace", False, str(e))

    ollama_bin = shutil.which("ollama")
    row("ollama binary", ollama_bin is not None, ollama_bin or "missing")

    model = Model(cfg)
    ollama_ok = model.ollama_ready()
    row("ollama daemon", ollama_ok, cfg.ollama_url)
    if ollama_ok:
        row("Miniton model", model.has_model(cfg.model), cfg.model)
        row("base model", model.has_model(cfg.base_model), cfg.base_model)
        row("embed model", model.has_model(cfg.embed_model), cfg.embed_model)
    row(
        "hugging face",
        model.hf_ready(),
        cfg.hf_model if model.hf_ready() else "HF_TOKEN missing",
    )
    model.close()

    if s.get("semantic_error"):
        row("semantic index", False, str(s["semantic_error"]))
    else:
        row(
            "semantic index",
            bool(s["semantic_enabled"]),
            cfg.semantic_collection,
        )

    ui.print_table(table)
