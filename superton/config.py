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
    model: str = "mini-ton"
    base_model: str = "qwen2.5:0.5b"
    embed_model: str = "nomic-embed-text"
    ollama_url: str = "http://127.0.0.1:11434"
    offline: bool = True

    @classmethod
    def load(cls) -> Config:
        return cls(
            home=_home(),
            model=os.environ.get("SUPERTON_MODEL", "mini-ton"),
            ollama_url=os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
        )

    @property
    def palace_dir(self) -> Path:
        return self.home / "palace"

    @property
    def config_file(self) -> Path:
        return self.home / "config.toml"
