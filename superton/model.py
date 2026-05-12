"""Miniton model layer — Ollama first, Hugging Face fallback."""

from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import httpx

from superton.config import Config


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

    def ping(self) -> bool:
        if self.cfg.model_backend == "huggingface":
            return self.hf_ready()
        try:
            r = self._client.get("/api/tags")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def backend(self) -> str | None:
        """Return the usable generation backend, if any."""
        if self.cfg.model_backend == "ollama":
            return "ollama" if self._ollama_ping() and self.has_model(self.cfg.model) else None
        if self.cfg.model_backend == "huggingface":
            return "huggingface" if self.hf_ready() else None
        if self._ollama_ping() and self.has_model(self.cfg.model):
            return "ollama"
        if self.hf_ready():
            return "huggingface"
        return None

    def _ollama_ping(self) -> bool:
        try:
            r = self._client.get("/api/tags")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def ollama_ready(self) -> bool:
        return self._ollama_ping()

    def hf_ready(self) -> bool:
        return bool(os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACEHUB_API_TOKEN"))

    def has_model(self, name: str) -> bool:
        try:
            r = self._client.get("/api/tags")
            r.raise_for_status()
            tags = r.json().get("models", [])
            return any(m.get("name", "").startswith(name) for m in tags)
        except httpx.HTTPError:
            return False

    def build(self, modelfile: Path) -> bool:
        result = subprocess.run(
            ["ollama", "create", self.cfg.model, "-f", str(modelfile)],
            check=False,
        )
        return result.returncode == 0

    def stop(self, model_name: str) -> bool:
        result = subprocess.run(["ollama", "stop", model_name], check=False)
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
                return True
            time.sleep(0.5)
        return False

    def generate(self, prompt: str, system: str | None = None) -> Iterator[str]:
        """Stream tokens from Miniton."""
        backend = self.backend()
        if backend == "huggingface":
            yield from self._generate_huggingface(prompt, system=system)
            return
        if backend != "ollama":
            raise ModelError("no model backend available: start Ollama or set HF_TOKEN")

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
