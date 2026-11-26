"""The demo-video tools (tools/demo/, #20). Hermetic: no model, no browser, no network."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tools.demo.narrate import Scene, scenes
from tools.demo.walkthrough import Marker, hold_for, load_durations, run_scene

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


# --- walkthrough.py: recorded to the narration ------------------------------------------------


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class FakeLocator:
    def __init__(self, clock: FakeClock, delay: float) -> None:
        self.clock, self.delay = clock, delay
        self.first = self

    def wait_for(self, **_: object) -> None:
        self.clock.now += self.delay


class FakePage:
    def __init__(self, clock: FakeClock, delay: float = 0.0) -> None:
        self.clock, self.delay, self.calls = clock, delay, []

    def locator(self, selector: str) -> FakeLocator:
        self.calls.append(selector)
        return FakeLocator(self.clock, self.delay)


def _durations(tmp_path: Path, script: Path, values: dict, older: bool = False) -> Path:
    path = tmp_path / "durations.json"
    path.write_text(json.dumps(values))
    if older:
        t = script.stat().st_mtime - 60
        os.utime(path, (t, t))
    return path


def test_refuses_without_durations(tmp_path):
    script = _write(tmp_path)
    with pytest.raises(SystemExit, match="durations.json"):
        load_durations(tmp_path / "durations.json", script)


def test_refuses_stale_durations(tmp_path):
    script = _write(tmp_path)
    path = _durations(tmp_path, script, {"01-open": 3.0, "04-retrieval": 9.8}, older=True)
    with pytest.raises(SystemExit, match="older than"):
        load_durations(path, script)


def test_refuses_durations_missing_a_scene(tmp_path):
    script = _write(tmp_path)
    path = _durations(tmp_path, script, {"01-open": 3.0})
    with pytest.raises(SystemExit, match="04-retrieval"):
        load_durations(path, script)


def test_hold_waits_for_done_then_line():
    clock = FakeClock()
    hold_for(FakePage(clock, delay=2.0), "text=exit 0", 3.0, clock=clock)
    assert clock.now >= 5.0


def test_explainer_scenes_only_marked(tmp_path):
    clock = FakeClock()
    page = FakePage(clock)
    log = tmp_path / "w.log"
    marker = Marker(log, clock=clock)
    run_scene(page, "04-retrieval", Scene("x", "explainer"), 9.8, marker, actions={}, clock=clock)
    assert page.calls == []
    assert log.read_text() == "0.00 scene 04-retrieval\n"
    assert clock.now == pytest.approx(0.5)


def test_footage_scene_runs_its_action_then_holds(tmp_path):
    clock = FakeClock()
    page = FakePage(clock, delay=1.0)
    marker = Marker(tmp_path / "w.log", clock=clock)
    actions = {"01-open": lambda p: "text=Ready"}
    run_scene(page, "01-open", Scene("x", "footage"), 3.0, marker, actions=actions, clock=clock)
    assert page.calls == ["text=Ready"]
    assert clock.now == pytest.approx(4.0)
