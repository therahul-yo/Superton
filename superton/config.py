"""SuperTon configuration — paths, defaults, env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

from superton.logging import get_logger

log = get_logger("config")

VALID_BACKENDS = {"auto", "ollama", "huggingface"}
VALID_MEMORY_BACKENDS = {"hybrid", "semantic", "mempalace", "sqlite"}

# Single default model: MiniCPM5 (1B, 128K context) pulled via Ollama.
DEFAULT_BASE_MODEL = "openbmb/minicpm5"
DEFAULT_HF_MODEL = "openbmb/MiniCPM5-1B"
BASE_MODEL_DOWNLOAD_GB = 0.7


def detect_ram_gb() -> float | None:
    """Best-effort host RAM in GB. Returns None if we can't tell."""
    import platform
    import subprocess
    system = platform.system()
    try:
        if system == "Darwin":
            out = subprocess.check_output(
                ["sysctl", "-n", "hw.memsize"], text=True, timeout=2
            )
            return int(out.strip()) / (1024 ** 3)
        if system == "Linux":
            with open("/proc/meminfo", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return kb / (1024 ** 2)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return None


def _home() -> Path:
    override = os.environ.get("SUPERTON_HOME")
    if override:
        return Path(override).expanduser()
    return Path(user_data_dir("superton", appauthor=False))


def _read_settings(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    settings: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        settings[key.strip()] = value.strip().strip('"')
    return settings


def write_settings(home: Path, **updates: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    path = home / "config.toml"
    settings = _read_settings(path)
    settings.update({k: v for k, v in updates.items() if v})
    text = "\n".join(f'{key} = "{value}"' for key, value in sorted(settings.items()))
    path.write_text(text + "\n", encoding="utf-8")


@dataclass(frozen=True)
class Config:
    home: Path
    model: str = "superton"
    base_model: str = DEFAULT_BASE_MODEL
    model_backend: str = "auto"
    hf_model: str = DEFAULT_HF_MODEL
    embed_model: str = "nomic-embed-text"
    ollama_url: str = "http://127.0.0.1:11434"
    memory_backend: str = "hybrid"
    semantic_collection: str = "superton_drawers"
    offline: bool = True
    theme: str = "ember"
    first_repl_done: bool = False

    @classmethod
    def load(cls) -> Config:
        home = _home()
        settings = _read_settings(home / "config.toml")

        model_backend_raw = os.environ.get(
            "SUPERTON_MODEL_BACKEND",
            settings.get("model_backend", "auto"),
        ).lower()
        if model_backend_raw not in VALID_BACKENDS:
            log.warning("unknown model_backend=%r, falling back to 'auto'", model_backend_raw)
            model_backend_raw = "auto"

        memory_backend_raw = os.environ.get(
            "SUPERTON_MEMORY_BACKEND",
            settings.get("memory_backend", "hybrid"),
        ).lower()
        if memory_backend_raw not in VALID_MEMORY_BACKENDS:
            log.warning("unknown memory_backend=%r, falling back to 'hybrid'", memory_backend_raw)
            memory_backend_raw = "hybrid"

        theme = os.environ.get("SUPERTON_THEME", settings.get("theme", "ember"))
        # ui.THEMES is the source of truth, but importing ui here would create
        # a load-order cycle. Whitelist the four shipped themes inline.
        if theme not in {"ember", "crimson", "void", "ash"}:
            log.warning("unknown theme=%r, falling back to 'ember'", theme)
            theme = "ember"

        return cls(
            home=home,
            model=os.environ.get("SUPERTON_MODEL", settings.get("model", "superton")),
            base_model=os.environ.get(
                "SUPERTON_BASE_MODEL",
                settings.get("base_model", DEFAULT_BASE_MODEL),
            ),
            model_backend=model_backend_raw,
            hf_model=os.environ.get(
                "SUPERTON_HF_MODEL",
                settings.get("hf_model", DEFAULT_HF_MODEL),
            ),
            ollama_url=os.environ.get("OLLAMA_HOST", settings.get("ollama_url", "http://127.0.0.1:11434")),
            memory_backend=memory_backend_raw,
            semantic_collection=os.environ.get(
                "SUPERTON_SEMANTIC_COLLECTION",
                settings.get("semantic_collection", "superton_drawers"),
            ),
            theme=theme,
            first_repl_done=settings.get("first_repl_done", "").lower() in {"1", "true", "yes"},
        )

    @property
    def palace_dir(self) -> Path:
        return self.home / "palace"

    @property
    def semantic_dir(self) -> Path:
        return self.palace_dir / "semantic"

    @property
    def config_file(self) -> Path:
        return self.home / "config.toml"
