"""Model-written text that is safe to show a person.

The mock LLM provider used to label its placeholder output "[mock]" so
developers could tell it apart. Anything written while the app ran without an
API key -- including rows already sitting in a database -- still carries that
label, so every model-written string sent to a user goes through here.
"""

from __future__ import annotations

MOCK_MARKER = "[mock]"


def is_placeholder(text: str | None) -> bool:
    return bool(text) and text.lstrip().lower().startswith(MOCK_MARKER)


def public_text(text: str | None, fallback: str | None = None) -> str | None:
    """`text`, unless it is placeholder output, in which case `fallback`."""
    if text is None:
        return fallback
    return fallback if is_placeholder(text) else text
