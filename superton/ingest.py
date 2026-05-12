"""Document parsers and chunking."""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

CHUNK_SIZE = 1200
CHUNK_OVERLAP = 200


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> Iterator[str]:
    text = text.strip()
    if not text:
        return
    if len(text) <= size:
        yield text
        return
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        # try to break at a paragraph or sentence boundary
        if end < len(text):
            for sep in ("\n\n", "\n", ". ", " "):
                cut = text.rfind(sep, start + size // 2, end)
                if cut != -1:
                    end = cut + len(sep)
                    break
        chunk = text[start:end].strip()
        if chunk:
            yield chunk
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)


def read_file(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown", ".rst", ".log", ".py", ".js", ".ts",
                  ".tsx", ".jsx", ".go", ".rs", ".java", ".c", ".cpp", ".h", ".sh",
                  ".yaml", ".yml", ".toml", ".json", ".html", ".css", ".sql"}:
        return path.read_text(encoding="utf-8", errors="replace")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise RuntimeError("pypdf not installed — run: pip install pypdf") from e
        reader = PdfReader(str(path))
        return "\n\n".join(p.extract_text() or "" for p in reader.pages)
    if suffix == ".docx":
        try:
            import docx
        except ImportError as e:
            raise RuntimeError("python-docx not installed") from e
        d = docx.Document(str(path))
        return "\n\n".join(p.text for p in d.paragraphs)
    raise ValueError(f"unsupported file type: {suffix}")


def walk(path: Path) -> Iterator[Path]:
    if path.is_file():
        yield path
        return
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
                 ".pytest_cache", "dist", "build", ".next"}
    for p in path.rglob("*"):
        if p.is_file() and not any(part in skip_dirs for part in p.parts):
            yield p
