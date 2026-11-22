"""Runtime feature flags shared by Streamlit views."""

from __future__ import annotations

import os

_FALSE_VALUES = {"0", "false", "no", "off"}


def _flag(name: str) -> bool:
    return os.environ.get(name, "true").strip().lower() not in _FALSE_VALUES


def playground_enabled() -> bool:
    return _flag("PLAYGROUND_ENABLED")


def agent_enabled() -> bool:
    return _flag("AGENT_ENABLED")
