"""Base images are pinned by digest, and Dependabot moves the pins (#72).

Founder's choice, 26 Nov 2026: "Pin all three + Dependabot (Recommended)". A floating
``python:3.12-slim`` gave each build the newest Debian patches but made two builds of one commit
differ; a digest pin makes builds repeatable, and Dependabot's weekly ``docker`` updates bring the
patches as reviewable pull requests.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCKERFILES = [ROOT / "app" / "Dockerfile", ROOT / "frontend" / "Dockerfile", ROOT / "runner" / "Dockerfile"]
PINNED = re.compile(r"^FROM python:3\.12-slim@sha256:[0-9a-f]{64}( AS \w+)?$")


def test_every_base_image_pinned_by_digest():
    for dockerfile in DOCKERFILES:
        froms = [line.strip() for line in dockerfile.read_text().splitlines() if line.startswith("FROM ")]
        assert froms, dockerfile
        for line in froms:
            assert PINNED.match(line), f"{dockerfile.relative_to(ROOT)}: {line}"


def test_one_digest_for_all_images():
    digests = {
        m.group(0)
        for dockerfile in DOCKERFILES
        for m in re.finditer(r"sha256:[0-9a-f]{64}", dockerfile.read_text())
    }
    assert len(digests) == 1, digests


def test_dependabot_moves_the_pins():
    config = yaml.safe_load((ROOT / ".github" / "dependabot.yml").read_text())
    docker = [u for u in config["updates"] if u["package-ecosystem"] == "docker"]
    assert len(docker) == 1
    update = docker[0]
    assert sorted(update["directories"]) == ["/app", "/frontend", "/runner"]
    assert update["cooldown"]["default-days"] == 7
    # Stay on Python 3.12 (the version uv.lock and CI test); move only to newer 3.12 builds.
    ignored = {i["dependency-name"]: i["update-types"] for i in update["ignore"]}
    assert set(ignored["python"]) == {"version-update:semver-minor", "version-update:semver-major"}
    # One pull request moves all three pins together, so the images never differ.
    assert update["groups"]["base-images"]["patterns"] == ["python"]
