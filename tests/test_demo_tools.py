"""The demo-video tools (tools/demo/, #20). Hermetic: no model, no browser, no network."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path

import pytest

from tools.demo.manifest import build_manifest
from tools.demo.narrate import Scene, scenes, text_hash
from tools.demo.walkthrough import (
    ACTIONS,
    ANSWER_DONE,
    FOLLOWUP_DONE,
    Marker,
    check_actions,
    hold_for,
    load_durations,
    run_scene,
    take_stem,
)

SCRIPT = """# FastPilot demo narration

Intro text that is not a scene.

## 01-open (footage)
FastPilot answers FastAPI questions from the official docs.

## 04-retrieval (explainer)
It searches two ways, then reranks. <!-- source: wiki/component-architecture.md -->

Then it answers with citations.
"""


FULL = """## 01-open (footage)
Open.

## 04-retrieval (explainer)
How it searches.

## 05-agent (footage)
Agent.
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


def test_scenes_refuse_an_empty_scene(tmp_path):
    with pytest.raises(ValueError, match="01-open"):
        scenes(_write(tmp_path, "## 01-open (footage)\n## 02-ask (footage)\nLine two.\n"))


def test_scenes_refuse_duplicates(tmp_path):
    with pytest.raises(ValueError, match="01-open"):
        scenes(_write(tmp_path, "## 01-open (footage)\nA.\n\n## 01-open (footage)\nB.\n"))


def test_scenes_refuse_an_unclosed_comment(tmp_path):
    with pytest.raises(ValueError, match="01-open"):
        scenes(_write(tmp_path, "## 01-open (footage)\nSaid. <!-- source: never closed\n"))


def test_scene_caption_override(tmp_path):
    text = "## 08-close (footage)\nAt fastpilot dot dev. <!-- caption: At fastpilot.dev. -->\n"
    scene = scenes(_write(tmp_path, text))["08-close"]
    assert scene.text == "At fastpilot dot dev." and scene.caption == "At fastpilot.dev."


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


def _durations(tmp_path: Path, script: Path, values: dict, stale: tuple[str, ...] = ()) -> Path:
    """durations.json as narrate.py writes it: seconds plus a hash of the text that was read."""
    texts = scenes(script)
    data = {
        name: {"seconds": sec, "text_sha": text_hash("old words" if name in stale else texts[name].text)}
        for name, sec in values.items()
    }
    path = tmp_path / "durations.json"
    path.write_text(json.dumps(data))
    return path


def test_refuses_without_durations(tmp_path):
    script = _write(tmp_path)
    with pytest.raises(SystemExit, match="durations.json"):
        load_durations(tmp_path / "durations.json", script)


def test_refuses_stale_durations(tmp_path):
    """A line edited after the narration was rendered is named; file times don't matter."""
    script = _write(tmp_path)
    path = _durations(tmp_path, script, {"01-open": 3.0, "04-retrieval": 9.8}, stale=("04-retrieval",))
    with pytest.raises(SystemExit, match="04-retrieval"):
        load_durations(path, script)


def test_durations_ignore_file_times(tmp_path):
    script = _write(tmp_path)
    path = _durations(tmp_path, script, {"01-open": 3.0, "04-retrieval": 9.8})
    t = script.stat().st_mtime - 60
    os.utime(path, (t, t))  # e.g. a git checkout touched script.md
    assert load_durations(path, script) == {"01-open": 3.0, "04-retrieval": 9.8}


def test_refuses_durations_missing_a_scene(tmp_path):
    script = _write(tmp_path)
    path = _durations(tmp_path, script, {"01-open": 3.0})
    with pytest.raises(SystemExit, match="04-retrieval"):
        load_durations(path, script)


def test_hold_counts_the_wait_into_the_line():
    """The voice starts with the scene: hold only for what is left of the line once it's done."""
    clock = FakeClock()
    hold_for(FakePage(clock, delay=2.0), "text=exit 0", 3.0, started=0.0, clock=clock)
    assert clock.now == pytest.approx(3.0)


def test_hold_waits_for_done_even_past_the_line():
    clock = FakeClock()
    hold_for(FakePage(clock, delay=5.0), "text=exit 0", 3.0, started=0.0, clock=clock)
    assert clock.now == pytest.approx(5.0)


def test_explainer_scenes_only_marked(tmp_path):
    clock = FakeClock()
    page = FakePage(clock)
    log = tmp_path / "w.log"
    marker = Marker(log, clock=clock)
    run_scene(page, "04-retrieval", Scene("x", "explainer"), 9.8, marker, actions={}, clock=clock)
    assert page.calls == []
    assert log.read_text() == "0.00 scene 04-retrieval\n"
    assert clock.now == pytest.approx(0.5)


def test_footage_scene_marks_done_then_holds(tmp_path):
    clock = FakeClock()
    page = FakePage(clock, delay=1.0)
    log = tmp_path / "w.log"
    marker = Marker(log, clock=clock)
    actions = {"01-open": lambda p: "text=Ready"}
    run_scene(page, "01-open", Scene("x", "footage"), 3.0, marker, actions=actions, clock=clock)
    assert page.calls == ["text=Ready"]
    assert log.read_text() == "0.00 scene 01-open\n1.00 done 01-open\n"
    assert clock.now == pytest.approx(3.0)


def test_marker_writes_the_url_first(tmp_path):
    Marker(tmp_path / "w.log", clock=FakeClock(), url="http://localhost:8501")
    assert (tmp_path / "w.log").read_text() == "# url http://localhost:8501\n"


def test_each_take_gets_its_own_files():
    assert take_stem(dt.datetime(2026, 11, 27, 19, 5, 33)) == "walkthrough-2026-11-27-190533"


def test_actions_match_footage_scenes(tmp_path):
    script = scenes(_write(tmp_path, FULL))
    check_actions(script, {"01-open": None, "05-agent": None})  # fine
    with pytest.raises(SystemExit, match="05-agent"):
        check_actions(script, {"01-open": None})
    with pytest.raises(SystemExit, match="03-sources"):
        check_actions(script, {"01-open": None, "05-agent": None, "03-sources": None})


def test_answer_counts_as_done_only_when_sources_appear():
    """Citations render while the answer streams; the Sources expander only after it ends."""
    pattern = re.compile(ANSWER_DONE.removeprefix("text=/").removesuffix("/"))
    assert pattern.search("Sources (8)") and not pattern.search("[1]")


# --- manifest.py: what the Remotion edit (part B) reads ---------------------------------------

LENGTHS = {"01-open": 3.1, "04-retrieval": 9.8, "05-agent": 7.2}


def _log(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "walkthrough-2026-11-27.log"
    path.write_text(text)
    return path


def _video(tmp_path: Path) -> Path:
    path = tmp_path / "walkthrough-2026-11-27.webm"
    path.write_bytes(b"")
    return path


def test_manifest_orders_by_script(tmp_path):
    log = _log(tmp_path, "0.30 scene 01-open\n4.00 scene 04-retrieval\n4.50 scene 05-agent\n20.00 scene end\n")
    m = build_manifest(log, _video(tmp_path), _write(tmp_path, FULL), LENGTHS)
    assert [s["name"] for s in m["scenes"]] == ["01-open", "04-retrieval", "05-agent"]
    first, explainer, agent = m["scenes"]
    assert (first["start"], first["end"]) == (0.30, 4.00)
    assert (explainer["start"], explainer["end"]) == (None, None)
    assert (agent["start"], agent["end"]) == (4.50, 20.00)
    assert first["audio"] == "01-open.wav" and first["seconds"] == 3.1 and first["text"] == "Open."
    assert m["video"] == "walkthrough-2026-11-27.webm" and m["recorded"] == "2026-11-27"


def test_manifest_rejects_missing_scene(tmp_path):
    log = _log(tmp_path, "0.30 scene 01-open\n4.00 scene 04-retrieval\n9.00 scene end\n")
    with pytest.raises(ValueError, match="05-agent"):
        build_manifest(log, _video(tmp_path), _write(tmp_path, FULL), LENGTHS)


def test_explainer_scenes_have_no_footage(tmp_path):
    """Explainers are marked (the mark ends the footage before them) but get no footage window."""
    log = _log(tmp_path, "0.30 scene 01-open\n4.00 scene 04-retrieval\n4.50 scene 05-agent\n20.00 scene end\n")
    explainer = build_manifest(log, _video(tmp_path), _write(tmp_path, FULL), LENGTHS)["scenes"][1]
    assert explainer["kind"] == "explainer" and explainer["start"] is None and explainer["end"] is None


def test_manifest_rejects_unknown_mark(tmp_path):
    marks = "0.30 scene 01-open\n2.00 scene 99-extra\n4.00 scene 04-retrieval\n4.50 scene 05-agent\n20.00 scene end\n"
    log = _log(tmp_path, marks)
    with pytest.raises(ValueError, match="99-extra"):
        build_manifest(log, _video(tmp_path), _write(tmp_path, FULL), LENGTHS)


def test_manifest_needs_an_end_mark(tmp_path):
    log = _log(tmp_path, "0.30 scene 01-open\n4.00 scene 04-retrieval\n4.50 scene 05-agent\n")
    with pytest.raises(ValueError, match="end"):
        build_manifest(log, _video(tmp_path), _write(tmp_path, FULL), LENGTHS)


def test_marker_end_closes_the_last_scene(tmp_path):
    clock = FakeClock()
    marker = Marker(tmp_path / "w.log", clock=clock)
    clock.sleep(2.5)
    marker.mark("end")
    assert (tmp_path / "w.log").read_text() == "2.50 scene end\n"


def test_manifest_marks_ai_narration(tmp_path):
    log = _log(tmp_path, "0.30 scene 01-open\n4.00 scene 04-retrieval\n4.50 scene 05-agent\n20.00 scene end\n")
    m = build_manifest(log, _video(tmp_path), _write(tmp_path, FULL), LENGTHS)
    assert m["version"] == 1 and m["narration"] == "ai-generated"


def test_manifest_carries_done_url_and_caption(tmp_path):
    marks = ("# url http://localhost:8501\n0.30 scene 01-open\n2.10 done 01-open\n4.00 scene 04-retrieval\n"
             "4.50 scene 05-agent\n19.00 done 05-agent\n20.00 scene end\n")
    full = FULL.replace("Agent.", "Agent. <!-- caption: The agent. -->")
    m = build_manifest(_log(tmp_path, marks), _video(tmp_path), _write(tmp_path, full), LENGTHS)
    first, explainer, agent = m["scenes"]
    assert m["url"] == "http://localhost:8501"
    assert first["done"] == 2.10 and explainer["done"] is None and agent["done"] == 19.00
    assert first["caption"] == "Open." and agent["caption"] == "The agent."


def test_manifest_names_a_scene_missing_from_durations(tmp_path):
    log = _log(tmp_path, "0.30 scene 01-open\n4.00 scene 04-retrieval\n4.50 scene 05-agent\n20.00 scene end\n")
    with pytest.raises(ValueError, match="05-agent"):
        build_manifest(log, _video(tmp_path), _write(tmp_path, FULL), {"01-open": 3.1, "04-retrieval": 9.8})


def test_followup_waits_for_the_searched_as_note():
    """The rewritten question ("searched as") shows above the sources once the answer is complete."""
    assert FOLLOWUP_DONE == ".fp-rewrite-note"


def test_the_approved_script_and_the_recorder_agree():
    check_actions(scenes(Path(__file__).resolve().parents[1] / "tools" / "demo" / "script.md"), ACTIONS)
