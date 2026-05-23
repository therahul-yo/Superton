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


def test_note_captures_drawer(env: Path):
    result = CliRunner().invoke(app, ["note", "remember the token bucket decision", "--tag", "api"])
    assert result.exit_code == 0
    assert "captured note" in result.stdout

    recent = CliRunner().invoke(app, ["recent"])
    assert recent.exit_code == 0
    assert "note:" in recent.stdout


def test_sources_health_reports_virtual_note(env: Path):
    result = CliRunner().invoke(app, ["note", "health check note"])
    assert result.exit_code == 0

    health = CliRunner().invoke(app, ["sources", "--health"])
    assert health.exit_code == 0
    assert "virtual" in health.stdout


def test_today_lists_recent_note(env: Path):
    captured = CliRunner().invoke(app, ["note", "today's note"])
    assert captured.exit_code == 0

    result = CliRunner().invoke(app, ["today"])
    assert result.exit_code == 0
    # `today` is a thin wrapper around the same renderer as `recent` with
    # days=1 — verify both the header reflects that window and the just-
    # captured note appears in the output.
    assert "last 1 day(s)" in result.stdout
    assert "note:" in result.stdout


def test_today_empty_palace_renders_placeholder(env: Path):
    result = CliRunner().invoke(app, ["today"])
    assert result.exit_code == 0
    assert "no recent sources" in result.stdout


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


def test_uninstall_default_runs_tool_uninstall(env: Path, monkeypatch):
    """With no --keep-tool, `uninstall` must invoke the installer's
    uninstall command via subprocess (replacing the earlier os.execvp
    pattern) and then sweep any orphan tool dirs the installer left
    behind. The CliRunner can't actually unlink the test runner's own
    bin so we patch subprocess.run + the orphan-sweep paths to a
    sandbox directory and assert both fire."""
    monkeypatch.setattr("superton.cli.shutil.which", lambda name: "/usr/bin/" + name)
    # Force the install-method detection to "uv" so we test the most
    # common path. Without this the path of the test interpreter would
    # decide it (usually "pip"), and the orphan-sweep list would be
    # empty.
    monkeypatch.setattr("superton.cli._detect_install_method", lambda: "uv")

    orphan_tool_dir = env / "fake_tool_dir"
    orphan_tool_dir.mkdir(parents=True)
    orphan_bin = env / "fake_bin"
    orphan_bin.write_text("#!/bin/sh\n")
    monkeypatch.setattr(
        "superton.cli._tool_orphan_paths",
        lambda method: [orphan_tool_dir, orphan_bin],
    )

    captured: list[list[str]] = []

    class _Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def _fake_run(cmd, *args, **kwargs):
        captured.append(list(cmd))
        return _Result()

    monkeypatch.setattr("superton.cli.subprocess.run", _fake_run)
    result = CliRunner().invoke(app, ["uninstall", "--yes", "--keep-data", "--keep-models"])

    assert result.exit_code == 0
    assert captured, "uninstall should have invoked the installer's uninstall command"
    assert "superton" in " ".join(captured[0])
    # The defensive sweep must clean up the orphans the installer left
    # behind even though the subprocess call returned 0.
    assert not orphan_tool_dir.exists()
    assert not orphan_bin.exists()


def test_tool_orphan_paths_uv_includes_install_root(env: Path):
    """The uv-specific orphan sweep targets the documented install dir
    (`~/.local/share/uv/tools/superton`) plus the bin shim — i.e. the
    two paths users see when `find ~ -iname '*superton*'` reports a
    leftover after `superton uninstall` claimed to finish."""
    from superton.cli import _tool_orphan_paths

    paths = [str(p) for p in _tool_orphan_paths("uv")]
    assert any(p.endswith(".local/share/uv/tools/superton") for p in paths)
    assert any(p.endswith(".local/bin/superton") for p in paths)


def test_tool_orphan_paths_returns_empty_for_pip(env: Path):
    """The pip / unknown path has no canonical install-dir to sweep —
    pip installs go into site-packages which we won't touch."""
    from superton.cli import _tool_orphan_paths

    assert _tool_orphan_paths("pip") == []


def test_detect_install_method_returns_string(env: Path):
    from superton.cli import _detect_install_method

    method = _detect_install_method()
    assert method in {"uv", "pipx", "pip"}


def test_detect_install_method_uv_via_sys_prefix(monkeypatch):
    """A uv tool install puts `sys.prefix` under `~/.local/share/uv/tools/<name>`
    even though `Path(sys.executable).resolve()` follows the bin/python
    symlink out of the tool dir. Detection must read `sys.prefix`, not
    the resolved executable — this regression cascaded into an empty
    orphan-path list and left `~/.local/bin/superton` behind after
    `superton uninstall` claimed success."""
    from superton.cli import _detect_install_method

    monkeypatch.setattr(
        "superton.cli.sys.prefix",
        "/Users/test/.local/share/uv/tools/superton",
    )
    # The cascade only happens when the executable also gets symlink-
    # resolved away from the tool dir; mimic that here so the test
    # would fail under the old detection.
    monkeypatch.setattr(
        "superton.cli.sys.executable",
        "/opt/homebrew/Cellar/python@3.12/3.12.7/Frameworks/Python.framework/Versions/3.12/bin/python3.12",
    )
    assert _detect_install_method() == "uv"


def test_detect_install_method_pipx_via_sys_prefix(monkeypatch):
    from superton.cli import _detect_install_method

    monkeypatch.setattr(
        "superton.cli.sys.prefix",
        "/Users/test/.local/share/pipx/venvs/superton",
    )
    monkeypatch.setattr(
        "superton.cli.sys.executable",
        "/usr/bin/python3",
    )
    assert _detect_install_method() == "pipx"


def test_detect_install_method_falls_back_to_pip(monkeypatch):
    from superton.cli import _detect_install_method

    monkeypatch.setattr("superton.cli.sys.prefix", "/usr/local")
    monkeypatch.setattr("superton.cli.sys.executable", "/usr/local/bin/python3")
    assert _detect_install_method() == "pip"


def test_detect_install_method_uses_executable_when_prefix_unhelpful(monkeypatch):
    """Belt-and-braces: if some shell flavour leaves `sys.prefix` looking
    generic but the executable still lives in a tool dir, we should
    still pick the right method."""
    from superton.cli import _detect_install_method

    monkeypatch.setattr("superton.cli.sys.prefix", "/usr/local")
    monkeypatch.setattr(
        "superton.cli.sys.executable",
        "/Users/test/.local/share/uv/tools/superton/bin/python",
    )
    assert _detect_install_method() == "uv"


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
