"""Measure SuperTon's runtime characteristics for the README.

Run on the target hardware (or in a clean uv tool venv):

    uv run python scripts/bench.py

Reports — quote these in the README's Performance section:

    superton_version_ms  — full `superton --version` invocation (Python
                           interpreter boot + Typer app init + version print)
    import_ms            — `from superton import …` (in-process)
    memory_init_ms       — Memory() open on a fresh palace
    ingest_drawers_per_s — sustained add() throughput on synthetic 1 KB drawers
    retrieval_p50_ms     — median Memory.search() latency over 200 queries
    retrieval_p95_ms     — 95th-percentile Memory.search() latency
    storage_bytes_drawer — SQLite + FTS bytes per ingested drawer

Numbers are machine-specific. Re-run on the target box before quoting;
treat sub-percent variation as noise.

What this script does NOT measure (do it manually):

    - First-token latency from a real model (needs Ollama + Superton)
    - R@5 retrieval recall (needs a labelled Q→drawer corpus)
    - End-to-end install→first-answer time (needs a fresh machine)

Run those with a stopwatch and quote them separately.
"""

from __future__ import annotations

import argparse
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

# Add the repo root to sys.path so `python scripts/bench.py` works
# without `pip install -e .` first. Keeps the script trivially
# runnable from a fresh clone.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Synthetic content generator — drawers look like real notes (varied
# lengths, common-word distribution, occasional code-fence) so the FTS
# tokenizer hits a realistic branch mix.
_LOREM = (
    "the quick brown fox jumps over the lazy dog "
    "lorem ipsum dolor sit amet consectetur adipiscing elit "
    "sed do eiusmod tempor incididunt ut labore et dolore magna aliqua "
    "ut enim ad minim veniam quis nostrud exercitation ullamco laboris "
    "memory palace drawer retrieval query embedding hint citation source "
)


def _make_drawer(rng: random.Random, idx: int) -> tuple[str, str]:
    """Return (text, source) for a synthetic drawer."""
    words = _LOREM.split()
    rng.shuffle(words)
    body_len = rng.randint(40, 180)
    body = " ".join(words[: min(body_len, len(words))])
    if rng.random() < 0.15:
        body += f"\n\n```python\ndef fn_{idx}(): return {idx}\n```\n"
    return body, f"/synth/drawer_{idx:05d}.md"


def _make_queries(rng: random.Random, drawers: list[tuple[str, str]], n: int) -> list[str]:
    """Build retrieval queries by sampling 1-3 words from real drawer text."""
    queries: list[str] = []
    for _ in range(n):
        text, _ = rng.choice(drawers)
        tokens = [t for t in text.split() if len(t) > 3]
        if not tokens:
            queries.append("memory")
            continue
        k = rng.randint(1, min(3, len(tokens)))
        queries.append(" ".join(rng.sample(tokens, k)))
    return queries


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    idx = int(len(values) * pct)
    idx = min(idx, len(values) - 1)
    return values[idx]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--drawers", type=int, default=2000,
                        help="how many drawers to ingest (default: 2000)")
    parser.add_argument("--queries", type=int, default=200,
                        help="how many retrieval queries to time (default: 200)")
    parser.add_argument("--seed", type=int, default=42,
                        help="random seed for synthetic content (default: 42)")
    parser.add_argument("--keep-tmp", action="store_true",
                        help="leave the temporary palace on disk for inspection")
    args = parser.parse_args()

    rng = random.Random(args.seed)

    # Point SuperTon at a throwaway palace so we never touch the user's
    # real data. `SUPERTON_HOME` is the documented override; setting it
    # before the first import makes Config.load() pick up the tmp dir.
    import os  # noqa: PLC0415
    import subprocess  # noqa: PLC0415
    tmp = Path(tempfile.mkdtemp(prefix="superton-bench-"))
    os.environ["SUPERTON_HOME"] = str(tmp)
    os.environ.setdefault("SUPERTON_MEMORY_BACKEND", "sqlite")  # no semantic side effects

    # --- end-to-end CLI launch ---------------------------------------------
    # `superton --version` is the cheapest invocation — boots Python,
    # imports the package, runs Typer, prints. Best proxy for "time from
    # user hitting Enter to a prompt being ready". Average over 3 runs
    # so we don't quote noise from a cold disk cache.
    version_samples_ms: list[float] = []
    for _ in range(3):
        t0 = time.perf_counter()
        subprocess.run(
            [sys.executable, "-m", "superton.cli", "--version"],
            check=False,
            capture_output=True,
            env={**os.environ},
        )
        version_samples_ms.append((time.perf_counter() - t0) * 1000.0)
    superton_version_ms = statistics.median(version_samples_ms)

    # --- in-process import + Memory init -----------------------------------
    t0 = time.perf_counter()
    from superton.config import Config  # noqa: PLC0415  (timed import)
    from superton.memory import Memory  # noqa: PLC0415  (timed import)
    import_ms = (time.perf_counter() - t0) * 1000.0

    cfg = Config.load()

    t0 = time.perf_counter()
    mem = Memory(cfg)
    memory_init_ms = (time.perf_counter() - t0) * 1000.0

    # --- ingest throughput --------------------------------------------------
    drawers = [_make_drawer(rng, i) for i in range(args.drawers)]
    t0 = time.perf_counter()
    for text, source in drawers:
        mem.add(text=text, source=source)
    ingest_elapsed = time.perf_counter() - t0
    ingest_per_s = args.drawers / ingest_elapsed if ingest_elapsed else 0.0

    # --- retrieval latency --------------------------------------------------
    queries = _make_queries(rng, drawers, args.queries)
    samples_ms: list[float] = []
    for q in queries:
        t0 = time.perf_counter()
        mem.search(q, limit=5)
        samples_ms.append((time.perf_counter() - t0) * 1000.0)

    p50 = statistics.median(samples_ms)
    p95 = _percentile(samples_ms, 0.95)
    p99 = _percentile(samples_ms, 0.99)
    mean = statistics.mean(samples_ms)

    # --- storage per drawer -------------------------------------------------
    mem.close()
    sqlite_path = cfg.palace_dir / "drawers.sqlite"
    sqlite_bytes = sqlite_path.stat().st_size if sqlite_path.exists() else 0
    per_drawer_bytes = sqlite_bytes / args.drawers if args.drawers else 0.0

    # --- report -------------------------------------------------------------
    print()
    print("=" * 60)
    print("  SuperTon bench")
    print("=" * 60)
    print(f"  drawers ingested      {args.drawers}")
    print(f"  queries timed         {args.queries}")
    print(f"  seed                  {args.seed}")
    print()
    print(f"  superton_version_ms   {superton_version_ms:8.1f}   (median of 3 `python -m superton.cli --version` runs)")
    print(f"  import_ms             {import_ms:8.1f}   (in-process)")
    print(f"  memory_init_ms        {memory_init_ms:8.1f}")
    print(f"  ingest_drawers_per_s  {ingest_per_s:8.1f}")
    print(f"  retrieval_mean_ms     {mean:8.2f}")
    print(f"  retrieval_p50_ms      {p50:8.2f}")
    print(f"  retrieval_p95_ms      {p95:8.2f}")
    print(f"  retrieval_p99_ms      {p99:8.2f}")
    print(f"  storage_bytes_drawer  {per_drawer_bytes:8.0f}")
    print(f"  storage_total_bytes   {sqlite_bytes:8d}")
    print()
    print("  Quote these in README.md → ## Performance. Re-run on the")
    print("  target hardware before changing the numbers.")
    print("=" * 60)
    print()

    if not args.keep_tmp:
        import shutil  # noqa: PLC0415
        shutil.rmtree(tmp, ignore_errors=True)
    else:
        print(f"  kept palace at: {tmp}")
        print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
