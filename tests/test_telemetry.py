"""The backend sends no third-party usage telemetry (#64)."""

from __future__ import annotations

import os
import subprocess
import sys


def _run(code: str) -> str:
    env = {k: v for k, v in os.environ.items() if k not in ("HAYSTACK_TELEMETRY_ENABLED", "HF_HUB_DISABLE_TELEMETRY")}
    return subprocess.run(
        [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
    ).stdout.strip()


def test_haystack_telemetry_is_off_once_app_is_imported():
    """In a fresh process with no telemetry variables set, importing the app first turns
    Haystack's PostHog telemetry off before Haystack loads."""
    out = _run("import app, haystack.telemetry._telemetry as t; print(t.telemetry is None)")
    assert out == "True"


def test_hugging_face_telemetry_is_off_once_app_is_imported():
    out = _run("import app, os; print(os.environ['HF_HUB_DISABLE_TELEMETRY'])")
    assert out == "1"
