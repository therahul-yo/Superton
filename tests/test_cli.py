"""CLI integration tests via Typer's CliRunner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from superton.cli import app


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("SUPERTON_HOME", str(tmp_path))
    monkeypatch.setenv("SUPERTON_MEMORY_BACKEND", "sqlite")
    return tmp_path


def test_version_flag(env: Path):
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "superton" in result.stdout.lower()


def test_init_no_model_creates_palace(env: Path):
    result = CliRunner().invoke(app, ["init", "--no-model", "-y"])
    assert result.exit_code == 0
    assert (env / "palace").exists()


def test_add_file_ingests_drawers(env: Path, tmp_path: Path):
    note = tmp_path / "note.txt"
    note.write_text("rate limiting via token bucket", encoding="utf-8")
    result = CliRunner().invoke(app, ["add", str(note)])
    assert result.exit_code == 0
    assert "ingested" in result.stdout


def test_add_missing_path_errors(env: Path):
    result = CliRunner().invoke(app, ["add", "/nonexistent/path/here"])
    assert result.exit_code == 1


def test_list_empty_palace(env: Path):
    result = CliRunner().invoke(app, ["list"])
    assert result.exit_code == 0


def test_stats_empty_palace(env: Path):
    result = CliRunner().invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "drawers" in result.stdout


def test_search_no_matches(env: Path):
    result = CliRunner().invoke(app, ["search", "nonsense_token_zzz"])
    assert result.exit_code == 0


def test_forget_missing_drawer_warns(env: Path):
    result = CliRunner().invoke(app, ["forget", "deadbeef"])
    assert result.exit_code == 0
    assert "no drawer matched" in result.stdout


def test_forget_source_no_match(env: Path):
    result = CliRunner().invoke(app, ["forget-source", "missing.txt"])
    assert result.exit_code == 0


def test_theme_unknown_rejected(env: Path):
    result = CliRunner().invoke(app, ["theme", "neopunk"])
    assert result.exit_code == 1


def test_theme_list_shows_active(env: Path):
    result = CliRunner().invoke(app, ["theme"])
    assert result.exit_code == 0
    assert "nebula" in result.stdout


def test_model_profile_unknown_rejected(env: Path):
    result = CliRunner().invoke(app, ["model", "huge"])
    assert result.exit_code == 1


def test_doctor_runs(env: Path):
    result = CliRunner().invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "doctor" in result.stdout or "home" in result.stdout


def test_doctor_json_runs(env: Path):
    result = CliRunner().invoke(app, ["doctor", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["home"] == str(env)
    assert data["install_method"] in {"uv", "pipx", "pip"}
    assert any(check["name"] == "palace" for check in data["checks"])


def test_demo_seeds_stable_drawers(env: Path):
    result = CliRunner().invoke(app, ["demo"])
    assert result.exit_code == 0
    assert "seeded 3" in result.stdout

    second = CliRunner().invoke(app, ["demo"])
    assert second.exit_code == 0
    assert "already present" in second.stdout


def test_init_no_model_ready_card_guides_empty_palace(env: Path):
    result = CliRunner().invoke(app, ["init", "--no-model", "-y"])
    assert result.exit_code == 0
    assert "superton add ~/notes" in result.stdout
    assert "your palace is empty" in result.stdout


def test_ask_empty_palace_suggests_demo(env: Path, monkeypatch):
    class DownModel:
        def __init__(self, cfg):
            pass

        def backend(self):
            return None

        def start_ollama(self, *, timeout: float = 5.0):
            return False

        def close(self):
            pass

    monkeypatch.setattr("superton.cli.Model", DownModel)
    result = CliRunner().invoke(app, ["ask", "hello"])
    assert result.exit_code == 0
    assert "your palace is empty" in result.stdout
    assert "superton demo" in result.stdout


def test_uninstall_removes_data_when_confirmed(env: Path, monkeypatch):
    monkeypatch.setattr("superton.cli.shutil.which", lambda name: None)
    (env / "palace").mkdir(parents=True)
    (env / "config.toml").write_text('theme = "mono"\n', encoding="utf-8")

    # --keep-tool prevents the test runner from being execvp'd into oblivion.
    result = CliRunner().invoke(app, ["uninstall", "--yes", "--keep-models", "--keep-tool"])

    assert result.exit_code == 0
    assert not env.exists()


def test_uninstall_default_swaps_into_tool_uninstall(env: Path, monkeypatch):
    """With no --keep-tool, uninstall must call os.execvp so the binary
    can be safely unlinked. The CliRunner can't actually execvp, but we
    can patch it to verify the call site exists and aims at the right cmd."""
    monkeypatch.setattr("superton.cli.shutil.which", lambda name: "/usr/bin/" + name)

    captured: list[tuple[str, list[str]]] = []

    def _fake_execvp(file: str, args: list[str]) -> None:
        captured.append((file, args))
        # execvp normally never returns; raise SystemExit to mimic the
        # process being replaced so the surrounding code stops cleanly.
        raise SystemExit(0)

    monkeypatch.setattr("superton.cli.os.execvp", _fake_execvp)
    result = CliRunner().invoke(app, ["uninstall", "--yes", "--keep-data", "--keep-models"])

    assert captured, "uninstall should have called os.execvp for the binary"
    assert captured[0][1][0] in {"uv", "pipx", result.stdout and "python" or "python"} or (
        "pip" in " ".join(captured[0][1])
    )


def test_detect_install_method_returns_string(env: Path):
    from superton.cli import _detect_install_method

    method = _detect_install_method()
    assert method in {"uv", "pipx", "pip"}


def test_tool_uninstall_command_contains_superton(env: Path):
    from superton.cli import _tool_uninstall_command

    cmd = _tool_uninstall_command()
    assert "superton" in " ".join(cmd)


def test_uninstall_model_names_include_dependencies_by_default(env: Path):
    from superton.cli import _uninstall_model_names
    from superton.config import Config

    cfg = Config.load()
    assert _uninstall_model_names(cfg, models=True, all_models=True) == [
        "miniton",
        "qwen3.5:4b",
        "nomic-embed-text",
    ]
    assert _uninstall_model_names(cfg, models=True, all_models=False) == ["miniton"]


def test_init_shows_preflight_card(env: Path):
    result = CliRunner().invoke(app, ["init", "--no-model", "-y"])
    assert result.exit_code == 0
    assert "about to do" in result.stdout
    # Stage progress indicator visible.
    assert "[1/" in result.stdout
    # Final ready card visible.
    assert "ready" in result.stdout


def test_init_rejects_unknown_theme_fast(env: Path):
    # Bad theme should exit non-zero before doing any work (no palace dir
    # created beyond what the cfg accessor already does).
    result = CliRunner().invoke(app, ["init", "--no-model", "-y", "--theme", "neopunk"])
    assert result.exit_code == 1


def test_init_rejects_unknown_profile_fast(env: Path):
    result = CliRunner().invoke(app, ["init", "--no-model", "-y", "--model", "huge"])
    assert result.exit_code == 1


def test_detect_preflight_marks_existing_palace(env: Path, tmp_path: Path):
    from superton.cli import _detect_preflight
    from superton.config import Config
    from superton.memory import Memory

    # A real palace is the sqlite db, not just the directory — create one
    # via Memory() so the helper sees the same shape it would in production.
    cfg = Config.load()
    Memory(cfg).close()
    rows = _detect_preflight(cfg)
    assert any(name == "palace" and status == "✓" for status, name, _ in rows)


def test_detect_preflight_makes_no_network_calls(env: Path, monkeypatch):
    """Preflight must stay hermetic: no httpx clients, no subprocesses
    beyond `shutil.which`. On CI runners where `ollama` is on PATH but
    the daemon isn't running, pinging it would hang the card.
    """
    import httpx

    from superton.cli import _detect_preflight
    from superton.config import Config

    def _no_client(*args, **kwargs):
        raise AssertionError("preflight made an httpx call — should be filesystem-only")

    monkeypatch.setattr(httpx, "Client", _no_client)
    cfg = Config.load()
    _detect_preflight(cfg)  # must not raise


def test_detect_preflight_reports_ollama_state(env: Path):
    from superton.cli import _detect_preflight
    from superton.config import Config

    cfg = Config.load()
    rows = _detect_preflight(cfg)
    assert any(name == "ollama" for _, name, _ in rows)
