"""SuperTon configuration — paths, defaults, env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from platformdirs import user_data_dir


def _home() -> Path:
    override = os.environ.get("SUPERTON_HOME")
    if override:
        return Path(override).expanduser()
    return Path(user_data_dir("superton", appauthor=False))


@dataclass(frozen=True)
class Config:
    home: Path
    model: str = "miniton"
    base_model: str = "qwen2.5:1.5b-instruct"
    model_backend: str = "auto"
    hf_model: str = "Qwen/Qwen2.5-1.5B-Instruct"
    embed_model: str = "nomic-embed-text"
    ollama_url: str = "http://127.0.0.1:11434"
    memory_backend: str = "hybrid"
    semantic_collection: str = "superton_drawers"
    offline: bool = True

    @classmethod
    def load(cls) -> Config:
        return cls(
            home=_home(),
            model=os.environ.get("SUPERTON_MODEL", "miniton"),
            base_model=os.environ.get("SUPERTON_BASE_MODEL", "qwen2.5:1.5b-instruct"),
            model_backend=os.environ.get("SUPERTON_MODEL_BACKEND", "auto").lower(),
            hf_model=os.environ.get("SUPERTON_HF_MODEL", "Qwen/Qwen2.5-1.5B-Instruct"),
            ollama_url=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
            memory_backend=os.environ.get("SUPERTON_MEMORY_BACKEND", "hybrid").lower(),
            semantic_collection=os.environ.get(
                "SUPERTON_SEMANTIC_COLLECTION", "superton_drawers"
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
