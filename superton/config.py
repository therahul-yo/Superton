"""SuperTon configuration — paths, defaults, env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TypedDict

from platformdirs import user_data_dir

from superton.logging import get_logger


class ModelProfile(TypedDict):
    base_model: str
    hf_model: str
    label: str
    download_gb: float
    min_ram_gb: int

log = get_logger("config")

VALID_BACKENDS = {"auto", "ollama", "huggingface"}
VALID_MEMORY_BACKENDS = {"hybrid", "semantic", "mempalace", "sqlite"}

# Profiles use particle-physics names to rhyme with the SuperTon / Miniton
# vocabulary. All three pull Qwen 3.5 weights via Ollama:
#   photon  → qwen3.5:0.8b   smallest, fastest, runs on any laptop
#   proton  → qwen3.5:4b     balanced default for everyday use
#   neutron → qwen3.5:9b     best local quality, wants real RAM
MODEL_PROFILES: dict[str, ModelProfile] = {
    "photon": {
        "base_model": "qwen3.5:0.8b",
        "hf_model": "Qwen/Qwen3.5-0.8B",
        "label": "photon · 0.8B · lowest memory · runs anywhere",
        "download_gb": 1.0,
        "min_ram_gb": 4,
    },
    "proton": {
        "base_model": "qwen3.5:4b",
        "hf_model": "Qwen/Qwen3.5-4B",
        "label": "proton · 4B · balanced · default for new installs",
        "download_gb": 3.4,
        "min_ram_gb": 8,
    },
    "neutron": {
        "base_model": "qwen3.5:9b",
        "hf_model": "Qwen/Qwen3.5-9B",
        "label": "neutron · 9B · best local quality · needs 14+ GB RAM",
        "download_gb": 6.6,
        "min_ram_gb": 14,
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
    model_profile: str = "proton"
    model: str = "miniton"
    base_model: str = "qwen3.5:4b"
    model_backend: str = "auto"
    hf_model: str = "Qwen/Qwen3.5-4B"
    embed_model: str = "nomic-embed-text"
    ollama_url: str = "http://127.0.0.1:11434"
    memory_backend: str = "hybrid"
    semantic_collection: str = "superton_drawers"
    offline: bool = True
    theme: str = "nebula"
    first_repl_done: bool = False

    @classmethod
    def load(cls) -> Config:
        home = _home()
        settings = _read_settings(home / "config.toml")
        profile = os.environ.get("SUPERTON_MODEL_PROFILE", settings.get("model_profile", "proton"))
        # Migrate users coming from the pre-Qwen3.5 profile names.
        _LEGACY_PROFILE_MAP = {"fast": "photon", "better": "proton", "strong": "neutron"}
        if profile in _LEGACY_PROFILE_MAP:
            log.warning(
                "legacy profile %r → %r (Qwen 3.5 release renamed the tiers)",
                profile, _LEGACY_PROFILE_MAP[profile],
            )
            profile = _LEGACY_PROFILE_MAP[profile]
        if profile not in MODEL_PROFILES:
            log.warning("unknown model_profile=%r, falling back to 'proton'", profile)
            profile = "proton"
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
