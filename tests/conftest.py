"""Shared fixtures. Every test runs against mock providers -- no network, no keys."""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ.setdefault("GOODDEED_USE_MOCKS", "1")

# Keep the suite hermetic: if the developer running it has a real .env with
# live keys, it must not leak into tests that assert on provider selection.
import gooddeed_agent.config as _config  # noqa: E402

_config._dotenv_loaded = True

from gooddeed_agent.providers import MockLLMProvider, MockPlacesProvider  # noqa: E402

# A 1x1 PNG -- smallest thing that survives magic-byte sniffing.
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


@pytest.fixture
def llm() -> MockLLMProvider:
    return MockLLMProvider()


@pytest.fixture
def places() -> MockPlacesProvider:
    return MockPlacesProvider()


@pytest.fixture
def photo_bytes() -> bytes:
    return TINY_PNG


@pytest.fixture
def photo_file(tmp_path: Path) -> Path:
    path = tmp_path / "deed.png"
    path.write_bytes(TINY_PNG)
    return path
