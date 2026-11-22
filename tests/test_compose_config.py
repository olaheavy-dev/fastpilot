"""Static checks on docker-compose.yml that protect security settings (no Docker needed)."""

from __future__ import annotations

from pathlib import Path

import yaml

_COMPOSE = yaml.safe_load((Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text())
_SERVICES = _COMPOSE["services"]
_KILL_SWITCHES = ("AGENT_ENABLED", "PLAYGROUND_ENABLED")


def test_kill_switches_are_not_overridden_in_compose_environment():
    """Codex review (PR #19): an `environment:` default would silently override a kill switch set
    in the shared env_file, because Compose gives `environment` precedence."""
    for name in ("backend", "frontend"):
        env = _SERVICES[name].get("environment") or {}
        for flag in _KILL_SWITCHES:
            assert flag not in env, f"{name} sets {flag} in environment; leave it to env_file"


def test_backend_and_frontend_read_the_same_env_file():
    paths = {name: [e["path"] for e in _SERVICES[name]["env_file"]] for name in ("backend", "frontend")}
    assert paths["backend"] == paths["frontend"]


def test_runner_has_no_env_file_and_no_network():
    runner = _SERVICES["runner"]
    assert "env_file" not in runner
    assert runner["network_mode"] == "none"
    assert runner["read_only"] is True
