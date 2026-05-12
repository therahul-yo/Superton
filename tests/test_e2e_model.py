"""Optional model-generation smoke test.

Run with ``SUPERTON_E2E=1`` after ``superton init --yes``.
"""

from __future__ import annotations

import os

import pytest

from superton.config import Config
from superton.model import Model


@pytest.mark.skipif(os.environ.get("SUPERTON_E2E") != "1", reason="requires local/remote model")
def test_model_generation_e2e():
    model = Model(Config.load())
    try:
        text = "".join(model.generate("Say only: ok"))
        assert text.strip()
    finally:
        model.close()
