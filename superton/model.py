"""Mini-Ton model layer — talks to Ollama."""

from __future__ import annotations

import json
from typing import Iterator

import httpx

from superton.config import Config


class OllamaError(RuntimeError):
    pass


class Model:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._client = httpx.Client(base_url=cfg.ollama_url, timeout=120.0)

    def ping(self) -> bool:
        try:
            r = self._client.get("/api/tags")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def has_model(self, name: str) -> bool:
        try:
            r = self._client.get("/api/tags")
            r.raise_for_status()
            tags = r.json().get("models", [])
            return any(m.get("name", "").startswith(name) for m in tags)
        except httpx.HTTPError:
            return False

    def generate(self, prompt: str, system: str | None = None) -> Iterator[str]:
        """Stream tokens from mini-ton."""
        payload = {
            "model": self.cfg.model,
            "prompt": prompt,
            "stream": True,
        }
        if system:
            payload["system"] = system
        try:
            with self._client.stream("POST", "/api/generate", json=payload) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if "response" in chunk:
                        yield chunk["response"]
                    if chunk.get("done"):
                        break
        except httpx.HTTPError as e:
            raise OllamaError(f"failed to reach ollama at {self.cfg.ollama_url}: {e}") from e

    def embed(self, text: str) -> list[float]:
        r = self._client.post(
            "/api/embeddings",
            json={"model": self.cfg.embed_model, "prompt": text},
        )
        r.raise_for_status()
        return r.json()["embedding"]

    def close(self) -> None:
        self._client.close()
