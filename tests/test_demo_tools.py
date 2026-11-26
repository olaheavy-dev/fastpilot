"""The demo-video tools (tools/demo/, #20). Hermetic: no model, no browser, no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.demo.narrate import Scene, scenes

SCRIPT = """# FastPilot demo narration

Intro text that is not a scene.

## 01-open (footage)
FastPilot answers FastAPI questions from the official docs.

## 04-retrieval (explainer)
It searches two ways, then reranks. <!-- source: wiki/component-architecture.md -->

Then it answers with citations.
"""


def _write(tmp_path: Path, text: str = SCRIPT) -> Path:
    path = tmp_path / "script.md"
    path.write_text(text)
    return path


def test_scenes_parse_headings_in_order(tmp_path):
    found = scenes(_write(tmp_path))
    assert list(found) == ["01-open", "04-retrieval"]
    assert found["01-open"] == Scene(text="FastPilot answers FastAPI questions from the official docs.", kind="footage")
    assert found["04-retrieval"].kind == "explainer"


def test_scenes_strip_source_comments(tmp_path):
    text = scenes(_write(tmp_path))["04-retrieval"].text
    assert "source:" not in text and "<!--" not in text
    assert text == "It searches two ways, then reranks.\n\nThen it answers with citations."


def test_scene_kind_required(tmp_path):
    with pytest.raises(ValueError, match="02-ask"):
        scenes(_write(tmp_path, "## 02-ask\nA line.\n"))
