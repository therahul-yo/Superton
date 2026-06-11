"""Superton model layer — Ollama first, Hugging Face fallback."""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import httpx

from superton.config import Config
from superton.logging import get_logger

log = get_logger("model")


class ModelError(RuntimeError):
    pass


class OllamaError(ModelError):
    pass


class HuggingFaceError(ModelError):
    pass


class Model:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._client = httpx.Client(base_url=cfg.ollama_url, timeout=120.0)
        self._hf_client = httpx.Client(timeout=120.0)
        self._tags_cache: tuple[float, list[dict]] | None = None
        self._backend_cache: tuple[float, str | None] | None = None
        self._ready_ttl = 4.0

    def invalidate_cache(self) -> None:
        self._tags_cache = None
        self._backend_cache = None

    def ping(self) -> bool:
        if self.cfg.model_backend == "huggingface":
            return self.hf_ready()
        return self._tags() is not None

    def backend(self) -> str | None:
        """Return the usable generation backend, if any."""
        now = time.time()
        if self._backend_cache is not None and now - self._backend_cache[0] < self._ready_ttl:
            return self._backend_cache[1]
        if self.cfg.model_backend == "ollama":
            backend = "ollama" if self._ollama_ping() and self.has_model(self.cfg.model) else None
        elif self.cfg.model_backend == "huggingface":
            backend = "huggingface" if self.hf_ready() else None
        elif self._ollama_ping() and self.has_model(self.cfg.model):
            backend = "ollama"
        elif self.hf_ready():
            backend = "huggingface"
        else:
            backend = None
        self._backend_cache = (now, backend)
        return backend

    def _tags(self) -> list[dict] | None:
        now = time.time()
        if self._tags_cache is not None and now - self._tags_cache[0] < self._ready_ttl:
            return self._tags_cache[1]
        try:
            r = self._client.get("/api/tags")
            r.raise_for_status()
            tags = r.json().get("models", [])
        except httpx.HTTPError:
            self._tags_cache = None
            return None
        self._tags_cache = (now, tags)
        return tags

    def _ollama_ping(self) -> bool:
        return self._tags() is not None

    def ollama_ready(self) -> bool:
        return self._ollama_ping()

    def hf_ready(self) -> bool:
        return bool(os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN"))

    def has_model(self, name: str) -> bool:
        tags = self._tags()
        if tags is None:
            return False
        return any(m.get("name", "").startswith(name) for m in tags)

    def build(self, modelfile: Path) -> bool:
        result = subprocess.run(
            ["ollama", "create", self.cfg.model, "-f", str(modelfile)],
            check=False,
        )
        self.invalidate_cache()
        return result.returncode == 0

    def stop(self, model_name: str) -> bool:
        result = subprocess.run(["ollama", "stop", model_name], check=False)
        self.invalidate_cache()
        return result.returncode == 0

    def start_ollama(self, *, timeout: float = 15.0) -> bool:
        """Best-effort local Ollama startup for first-run setup."""
        if self._ollama_ping():
            return True
        try:
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except FileNotFoundError:
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._ollama_ping():
                self.invalidate_cache()
                return True
            time.sleep(0.5)
        return False

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> Iterator[str]:
        """Stream tokens from Superton via /api/chat (structured messages)."""
        backend = self.backend()
        log.debug("generate via backend=%s prompt_chars=%d", backend, len(prompt))
        if backend == "huggingface":
            yield from self._generate_huggingface(prompt, system=system)
            return
        if backend != "ollama":
            raise ModelError("no model backend available: start Ollama or set HF_TOKEN")

        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        for msg in history or []:
            messages.append(msg)
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self.cfg.model,
            "messages": messages,
            "stream": True,
            # MiniCPM5 reasoning control belongs on the Ollama chat request. It is
            # not a valid Modelfile PARAMETER on current Ollama builds.
            "think": False,
            "options": {"num_predict": 512},
        }
        try:
            with self._client.stream("POST", "/api/chat", json=payload) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    delta = chunk.get("message", {}).get("content", "")
                    if delta:
                        yield delta
                    if chunk.get("done"):
                        break
        except httpx.HTTPError as e:
            log.error("ollama stream failed at %s: %s", self.cfg.ollama_url, e)
            raise OllamaError(f"failed to reach ollama at {self.cfg.ollama_url}: {e}") from e

    def _generate_huggingface(self, prompt: str, system: str | None = None) -> Iterator[str]:
        token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN")
        if not token:
            raise HuggingFaceError("HF_TOKEN is required for Hugging Face fallback")
        headers = {"Authorization": f"Bearer {token}"}
        full_prompt = prompt if system is None else f"{system}\n\n{prompt}"
        payload = {
            "inputs": full_prompt,
            "parameters": {
                "max_new_tokens": 512,
                "temperature": 0.3,
                "return_full_text": False,
            },
        }
        url = f"https://api-inference.huggingface.co/models/{self.cfg.hf_model}"
        try:
            r = self._hf_client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
        except httpx.HTTPError as e:
            log.error("hugging face request failed for %s: %s", self.cfg.hf_model, e)
            raise HuggingFaceError(f"failed to reach Hugging Face model {self.cfg.hf_model}: {e}") from e
        if isinstance(data, list) and data:
            text = data[0].get("generated_text", "")
        elif isinstance(data, dict):
            text = data.get("generated_text") or data.get("error", "")
        else:
            text = str(data)
        yield text

    def embed(self, text: str) -> list[float]:
        r = self._client.post(
            "/api/embeddings",
            json={"model": self.cfg.embed_model, "prompt": text},
        )
        r.raise_for_status()
        return r.json()["embedding"]

    def close(self) -> None:
        self._client.close()
        self._hf_client.close()
