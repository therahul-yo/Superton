"""Structured logging for SuperTon.

A single `get_logger(name)` accessor used across the package. The first call
to `configure()` decides the handler and level; later calls are no-ops, so
imports can freely call `get_logger()` without races.

Configuration:
    SUPERTON_LOG       one of: debug, info, warn, error, off  (default: warn)
    SUPERTON_LOG_JSON  truthy => emit one JSON line per record (default: off)
    SUPERTON_LOG_FILE  if set, also write records to this file

The default level is `warn` so users see no noise. Setting `SUPERTON_LOG=info`
unlocks operational breadcrumbs (ingest started, model backend chosen,
mempalace fell back to sqlite, etc.). `debug` adds per-row detail.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from logging import Logger
from pathlib import Path

_CONFIGURED = False
_PACKAGE_LOGGER = "superton"

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "warning": logging.WARNING,
    "error": logging.ERROR,
    "off": logging.CRITICAL + 10,
}


class _JsonFormatter(logging.Formatter):
    """One JSON object per record. Stable schema for log shippers."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key in ("source", "drawer_id", "url", "backend", "count"):
            value = record.__dict__.get(key)
            if value is not None:
                payload[key] = value
        return json.dumps(payload, default=str)


def _level_from_env() -> int:
    raw = (os.environ.get("SUPERTON_LOG") or "warn").strip().lower()
    return _LEVELS.get(raw, logging.WARNING)


def configure(*, force: bool = False) -> None:
    """Install handlers on the package logger. Idempotent unless `force=True`."""
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    root = logging.getLogger(_PACKAGE_LOGGER)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    root.setLevel(_level_from_env())
    root.propagate = False

    json_mode = (os.environ.get("SUPERTON_LOG_JSON") or "").strip().lower() in {"1", "true", "yes", "json"}
    formatter: logging.Formatter
    if json_mode:
        formatter = _JsonFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s %(levelname)-5s %(name)s · %(message)s",
            datefmt="%H:%M:%S",
        )

    stream = logging.StreamHandler(sys.stderr)
    stream.setFormatter(formatter)
    root.addHandler(stream)

    log_file = os.environ.get("SUPERTON_LOG_FILE")
    if log_file:
        try:
            path = Path(log_file).expanduser()
            path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(path, encoding="utf-8")
            file_handler.setFormatter(_JsonFormatter())
            root.addHandler(file_handler)
        except OSError:
            root.warning("could not open SUPERTON_LOG_FILE=%s", log_file)

    _CONFIGURED = True


def get_logger(name: str) -> Logger:
    """Return a child of the `superton` logger.

    Call sites can use either `get_logger(__name__)` or a short tag like
    `get_logger("memory")`. Both produce children under the package logger
    so a single `SUPERTON_LOG` setting controls all of them.
    """
    if not _CONFIGURED:
        configure()
    if name.startswith(_PACKAGE_LOGGER):
        return logging.getLogger(name)
    return logging.getLogger(f"{_PACKAGE_LOGGER}.{name}")
