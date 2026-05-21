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

MODEL_PROFILES = {
    "fast": {
        "base_model": "qwen2.5:1.5b-instruct",
        "hf_model": "Qwen/Qwen2.5-1.5B-Instruct",
        "label": "fast · 1.5B · lowest memory",
        "download_gb": 1.0,
        "min_ram_gb": 4,
    },
    "better": {
        "base_model": "qwen2.5:3b-instruct",
        "hf_model": "Qwen/Qwen2.5-3B-Instruct",
        "label": "better · 3B · stronger answers",
        "download_gb": 2.0,
        "min_ram_gb": 8,
    },
    "strong": {
        "base_model": "qwen2.5:7b-instruct",
        "hf_model": "Qwen/Qwen2.5-7B-Instruct",
        "label": "strong · 7B · best local quality",
        "download_gb": 4.7,
        "min_ram_gb": 16,
    },
}


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
    model_profile: str = "fast"
    model: str = "miniton"
    base_model: str = "qwen2.5:1.5b-instruct"
    model_backend: str = "auto"
    hf_model: str = "Qwen/Qwen2.5-1.5B-Instruct"
    embed_model: str = "nomic-embed-text"
    ollama_url: str = "http://127.0.0.1:11434"
    memory_backend: str = "hybrid"
    semantic_collection: str = "superton_drawers"
    offline: bool = True
    theme: str = "nebula"

    @classmethod
    def load(cls) -> Config:
        home = _home()
        settings = _read_settings(home / "config.toml")
        profile = os.environ.get("SUPERTON_MODEL_PROFILE", settings.get("model_profile", "fast"))
        if profile not in MODEL_PROFILES:
            log.warning("unknown model_profile=%r, falling back to 'fast'", profile)
            profile = "fast"
        profile_defaults = MODEL_PROFILES[profile]

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

        theme = os.environ.get("SUPERTON_THEME", settings.get("theme", "nebula"))
        # ui.THEMES is the source of truth, but importing ui here would create
        # a load-order cycle. Whitelist the four shipped themes inline.
        if theme not in {"nebula", "mono", "solar", "frost"}:
            log.warning("unknown theme=%r, falling back to 'nebula'", theme)
            theme = "nebula"

        return cls(
            home=home,
            model_profile=profile,
            model=os.environ.get("SUPERTON_MODEL", settings.get("model", "miniton")),
            base_model=os.environ.get(
                "SUPERTON_BASE_MODEL",
                settings.get("base_model", profile_defaults["base_model"]),
            ),
            model_backend=model_backend_raw,
            hf_model=os.environ.get(
                "SUPERTON_HF_MODEL",
                settings.get("hf_model", profile_defaults["hf_model"]),
            ),
            ollama_url=os.environ.get("OLLAMA_HOST", settings.get("ollama_url", "http://127.0.0.1:11434")),
            memory_backend=memory_backend_raw,
            semantic_collection=os.environ.get(
                "SUPERTON_SEMANTIC_COLLECTION",
                settings.get("semantic_collection", "superton_drawers"),
            ),
            theme=theme,
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
