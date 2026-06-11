"""Shared implementation of the SuperTon doctor health-check report.

Both the CLI `superton doctor` command and the interactive shell's
`/doctor` slash command call `render_doctor_report(cfg)` so they always
show the same information.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import sys
from pathlib import Path
from typing import Any

from superton import __version__, ui
from superton.config import Config
from superton.memory import Memory
from superton.model import Model


def _mask_token(token: str) -> str:
    """Show only the first 4 and last 4 characters of a secret-like string."""
    if not token:
        return ""
    if len(token) <= 8:
        return "•" * len(token)
    return f"{token[:4]}…{token[-4:]}"


def _detect_install_method() -> str:
    exe = str(Path(sys.executable).resolve())
    if "/uv/tools/" in exe or "uv\\tools\\" in exe:
        return "uv"
    if "/pipx/" in exe or "pipx\\" in exe:
        return "pipx"
    return "pip"


def collect_doctor_report(cfg: Config) -> dict[str, Any]:
    """Collect machine-readable diagnostics without exposing secrets."""
    mem = Memory(cfg)
    s = mem.stats()
    mem.close()

    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    add("home", cfg.home.exists(), str(cfg.home))
    add("palace", cfg.palace_dir.exists(), str(cfg.palace_dir))
    add("drawers", True, str(s["drawers"]))
    add("memory backend", True, cfg.memory_backend)
    add("model backend", True, cfg.model_backend)
    add("model", True, f"{cfg.model} · {cfg.base_model}")
    add("theme", True, f"{cfg.theme} · {ui.theme().label}")

    try:
        import mempalace

        add("mempalace", True, getattr(mempalace, "__version__", "installed"))
    except Exception as e:
        add("mempalace", False, str(e))

    try:
        import trafilatura
        add("trafilatura", True, getattr(trafilatura, "__version__", "installed"))
    except ImportError:
        add("trafilatura", False, "missing — run: pip install trafilatura")

    try:
        import playwright
        add("playwright", True, getattr(playwright, "__version__", "installed"))
    except ImportError:
        add("playwright", False, "optional — run: pip install 'superton[web]'")

    ollama_bin = shutil.which("ollama")
    add("ollama binary", ollama_bin is not None, ollama_bin or "missing")

    model = Model(cfg)
    ollama_ok = model.ollama_ready()
    add("ollama daemon", ollama_ok, cfg.ollama_url)
    if ollama_ok:
        add("Superton model", model.has_model(cfg.model), cfg.model)
        add("base model", model.has_model(cfg.base_model), cfg.base_model)
        add("embed model", model.has_model(cfg.embed_model), cfg.embed_model)
    hf_token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN") or ""
    if model.hf_ready():
        hf_detail = f"{cfg.hf_model}  (token: {_mask_token(hf_token)})"
    else:
        hf_detail = "HF_TOKEN missing"
    add("hugging face", model.hf_ready(), hf_detail)
    model.close()

    if s.get("semantic_error"):
        add("semantic index", False, str(s["semantic_error"]))
    else:
        add(
            "semantic index",
            bool(s["semantic_enabled"]),
            cfg.semantic_collection,
        )

    return {
        "version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "executable": sys.executable,
        "install_method": _detect_install_method(),
        "config_file": str(cfg.config_file),
        "home": str(cfg.home),
        "palace": str(cfg.palace_dir),
        "model_backend": cfg.model_backend,
        "memory_backend": cfg.memory_backend,
        "theme": cfg.theme,
        "stats": s,
        "checks": checks,
    }


def render_doctor_report(cfg: Config, *, json_output: bool = False) -> None:
    """Render the doctor health table using the active UI theme."""
    report = collect_doctor_report(cfg)
    if json_output:
        print(json.dumps(report, indent=2, sort_keys=True))
        return

    ui.section("doctor")
    table = ui.make_table("check", "status", "detail")

    def row(name: str, ok: bool, detail: str) -> None:
        status = (
            f"[{ui.theme().success}]ok[/]"
            if ok
            else f"[{ui.theme().warning}]warn[/]"
        )
        table.add_row(name, status, detail)

    row("install method", True, report["install_method"])
    row("executable", True, report["executable"])
    row("python", True, str(report["python"]))
    for check in report["checks"]:
        row(str(check["name"]), bool(check["ok"]), str(check["detail"]))
    ui.print_table(table)
