"""The backend sends no third-party telemetry (#64): Haystack (PostHog), Opik's crash
reports (Sentry) and Hugging Face Hub. Checked in fresh, non-pytest processes, because
the libraries decide at import time and Opik skips Sentry under pytest."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_VARS = (
    "HAYSTACK_TELEMETRY_ENABLED",
    "OPIK_SENTRY_ENABLE",
    "HF_HUB_DISABLE_TELEMETRY",
    "OPIK_CONNECTION_MONITOR_PING_INTERVAL",
)


def _run(code: str, **extra_env: str) -> str:
    env = {k: v for k, v in os.environ.items() if k not in _VARS and not k.startswith("PYTEST")}
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, "-c", code], env=env, cwd=_ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()


_CHECK = (
    "import app, app.observability, haystack.telemetry._telemetry as t, sentry_sdk, "
    "huggingface_hub.constants as hf; "
    "print(t.telemetry is None, sentry_sdk.get_client().is_active(), hf.HF_HUB_DISABLE_TELEMETRY)"
)


def test_all_telemetry_is_off_once_app_is_imported():
    assert _run(_CHECK) == "True False True"


@pytest.mark.parametrize("value", ["true", "1"])
def test_an_env_file_cannot_switch_telemetry_back_on(value):
    """Forced, not defaulted (founder: "Force off (Recommended)")."""
    on = {"HAYSTACK_TELEMETRY_ENABLED": value, "OPIK_SENTRY_ENABLE": value, "HF_HUB_DISABLE_TELEMETRY": "0"}
    assert _run(_CHECK, **on) == "True False True"


# --- Opik's connection monitor (#62) ---------------------------------------------------------
# Each Opik client pings `is-alive/ping` every `connection_monitor_ping_interval` seconds (SDK
# default 10), traffic or not, and the backend has two clients (ours and @track's), so production
# pinged about every 6 seconds: 15,853 requests in 26 hours. 300 s keeps the outage detection
# (failed traces are resent after Opik comes back) at about 580 pings a day.
_PING = "import app, opik.config as c; print(c.OpikConfig().connection_monitor_ping_interval)"


def test_opik_pings_every_five_minutes_by_default():
    assert _run(_PING) == "300.0"


def test_an_env_file_can_still_set_the_opik_ping_interval():
    """Defaulted, not forced: a different interval is an operations choice, not a privacy rule."""
    assert _run(_PING, OPIK_CONNECTION_MONITOR_PING_INTERVAL="60") == "60.0"
