"""SuperTon configuration — paths, defaults, env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir

MODEL_PROFILES = {
    "fast": {
        "base_model": "qwen2.5:1.5b-instruct",
        "hf_model": "Qwen/Qwen2.5-1.5B-Instruct",
        "label": "fast · 1.5B · lowest memory",
    },
    "better": {
        "base_model": "qwen2.5:3b-instruct",
        "hf_model": "Qwen/Qwen2.5-3B-Instruct",
        "label": "better · 3B · stronger answers",
    },
    "strong": {
        "base_model": "qwen2.5:7b-instruct",
        "hf_model": "Qwen/Qwen2.5-7B-Instruct",
        "label": "strong · 7B · best local quality",
    },
}


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
    theme: str = "claude"

    @classmethod
    def load(cls) -> Config:
        home = _home()
        settings = _read_settings(home / "config.toml")
        profile = os.environ.get("SUPERTON_MODEL_PROFILE", settings.get("model_profile", "fast"))
        if profile not in MODEL_PROFILES:
            profile = "fast"
        profile_defaults = MODEL_PROFILES[profile]
        return cls(
            home=home,
            model_profile=profile,
            model=os.environ.get("SUPERTON_MODEL", settings.get("model", "miniton")),
            base_model=os.environ.get(
                "SUPERTON_BASE_MODEL",
                settings.get("base_model", profile_defaults["base_model"]),
            ),
            model_backend=os.environ.get(
                "SUPERTON_MODEL_BACKEND",
                settings.get("model_backend", "auto"),
            ).lower(),
            hf_model=os.environ.get(
                "SUPERTON_HF_MODEL",
                settings.get("hf_model", profile_defaults["hf_model"]),
            ),
            ollama_url=os.environ.get("OLLAMA_HOST", settings.get("ollama_url", "http://127.0.0.1:11434")),
            memory_backend=os.environ.get(
                "SUPERTON_MEMORY_BACKEND",
                settings.get("memory_backend", "hybrid"),
            ).lower(),
            semantic_collection=os.environ.get(
                "SUPERTON_SEMANTIC_COLLECTION",
                settings.get("semantic_collection", "superton_drawers"),
            ),
            theme=os.environ.get(
                "SUPERTON_THEME",
                settings.get("theme", "claude"),
            ),
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
