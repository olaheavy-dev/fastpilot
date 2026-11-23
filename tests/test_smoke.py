"""Seed smoke test — keeps CI green from day 1 (plan §10.4).

Proves the foundation imports and the app serves /health, with no network, no
credentials, and no dependence on the developer's real .env (hermetic: Settings
is constructed with env files disabled and asserted fields cleared from the
environment). Phase 1 replaces/extends this with the real contract + SSE suite.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SUBMISSION_DIR = _REPO_ROOT


def test_config_defaults_are_plan_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Assert the *code defaults* (plan D1), not the ambient environment."""
    from app.config import Settings

    for var in ("APP_NAME", "QDRANT_COLLECTION", "VOYAGE_DIMENSION"):
        monkeypatch.delenv(var, raising=False)

    settings = Settings(_env_file=None)  # hermetic: ignore repo/.env entirely
    assert settings.app_name == "FastPilot"
    assert settings.qdrant_collection == "rag_accelerator_capstone_final"
    assert settings.voyage_dimension == 2048


def test_app_factory_and_routes() -> None:
    from app.main import app, create_app

    paths = {route.path for route in app.routes}
    assert {"/", "/health", "/metrics"} <= paths
    # The factory builds independent instances — the Phase 1 testability seam.
    assert create_app() is not app


_IMAGE_REQUIREMENTS = ("app/requirements.txt", "frontend/requirements.txt", "runner/requirements.txt")


def _names(lines: list[str]) -> set[str]:
    out = set()
    for line in lines:
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            out.add(re.sub(r"[-_.]+", "-", re.split(r"[\[<>=!~; ]", line, maxsplit=1)[0].strip().lower()))
    return out


def test_container_requirements_subset_of_pyproject() -> None:
    """Drift tripwire: every package an image installs must be a project dependency, so dev and CI
    (which install from uv.lock) run it too."""
    pyproject = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text())
    project_names = _names(pyproject["project"]["dependencies"])
    for rel in _IMAGE_REQUIREMENTS:
        missing = _names((_REPO_ROOT / rel).read_text().splitlines()) - project_names
        assert not missing, (
            f"{rel} deps missing from root pyproject: {sorted(missing)} — "
            "add them to pyproject (and `uv lock`) or remove them from the image list."
        )


def test_every_image_requirement_is_pinned_by_constraints() -> None:
    """pip's -c only pins packages the constraints file names: anything an image installs that is
    missing there would install at its newest version, untested (issue #25)."""
    pinned = {
        re.sub(r"[-_.]+", "-", line.split("==", 1)[0].strip().lower())
        for line in (_REPO_ROOT / "app" / "constraints.txt").read_text().splitlines()
        if "==" in line and not line.lstrip().startswith("#")
    }
    for rel in _IMAGE_REQUIREMENTS:
        unpinned = _names((_REPO_ROOT / rel).read_text().splitlines()) - pinned
        assert not unpinned, (
            f"{rel}: not pinned in app/constraints.txt: {sorted(unpinned)} — "
            "run `uv lock` and scripts/export_constraints.sh"
        )
