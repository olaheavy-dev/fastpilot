"""Record FastPilot's demo walkthrough, held to the narration (#20; docs/demo-video.md).

Drives the live site (or `--url` for a local build) in Chromium and records video. Each footage
scene runs its page actions, waits until the page shows the scene is done (an answer finished
streaming, a run printed its exit line), then holds for the scene's narration line from
`out/audio/durations.json`. So the voice and the screen stay in step, beat by beat. Explainer
scenes are drawn in Remotion (part B), so here they get only a mark in the log.

    python -m tools.demo.walkthrough                       # the live site
    python -m tools.demo.walkthrough --url http://localhost:8501 --headed

Writes `out/video/walkthrough-<date>.webm` and `.log` (one line per scene: seconds since the
recording started, then `scene <name>`). Every live take makes real Gemini and Voyage calls (a few
cents) and Opik traces; the question starts with "Demo:" so the traces are easy to spot.
Run it in the demo environment (tools/demo/requirements.txt).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable

from tools.demo.narrate import Scene, scenes

HERE = Path(__file__).resolve().parent
LIVE_URL = "https://fastpilot.olaheavy.dev"
QUESTION = "Demo: how do I add JWT authentication to a FastAPI app?"
AGENT_TASK = "Demo: a GET /greet/{name} endpoint that returns a greeting, with a test that calls it"
DONE_TIMEOUT_MS = 120_000  # a streamed answer or an agent run can take a while
EXPLAINER_GAP_S = 0.5  # a short still on the page where Remotion inserts the explainer

Action = Callable[[Any], "str | None"]  # runs a scene's page actions, returns its done-selector


def load_durations(path: Path, script: Path) -> dict[str, float]:
    """Each scene's line length. Refuses to record to missing or out-of-date timings."""
    if not path.exists():
        raise SystemExit(f"{path} not found: render the narration first (narrate.py), then record")
    if path.stat().st_mtime < script.stat().st_mtime:
        raise SystemExit(f"{path} is older than {script}: render the narration again, then record")
    lengths = json.loads(path.read_text())
    missing = [name for name in scenes(script) if name not in lengths]
    if missing:
        raise SystemExit(f"{path} has no length for: {', '.join(missing)}")
    return {name: float(seconds) for name, seconds in lengths.items()}


def hold_for(page: Any, done_selector: str | None, seconds: float, clock: Any = time) -> None:
    """Wait until the page shows the scene is done, then hold for the narration line."""
    if done_selector:
        page.locator(done_selector).first.wait_for(state="visible", timeout=DONE_TIMEOUT_MS)
    clock.sleep(seconds)


class Marker:
    """Writes `<seconds> scene <name>` lines, timed from when recording started."""

    def __init__(self, log: Path, clock: Any = time) -> None:
        self.log, self.clock, self.start = log, clock, clock.monotonic()
        log.write_text("")

    def mark(self, name: str) -> None:
        with self.log.open("a") as f:
            f.write(f"{self.clock.monotonic() - self.start:.2f} scene {name}\n")


def run_scene(
    page: Any, name: str, scene: Scene, seconds: float, marker: Marker, actions: dict[str, Action], clock: Any = time
) -> None:
    marker.mark(name)
    if scene.kind == "explainer":
        clock.sleep(EXPLAINER_GAP_S)
        return
    hold_for(page, actions[name](page), seconds, clock=clock)


# --- Page actions, one per footage scene (selectors as in tests/test_visual.py) ----------------


def _pick_mode(page: Any, label: str) -> None:
    option = page.locator("label").filter(has_text=label).first
    option.wait_for(state="visible", timeout=10_000)
    option.click()


def _open(page: Any) -> str:
    return "text=Learn FastAPI by building."


def _ask(page: Any) -> str:
    # Switch the semantic cache off for the take: a cached answer appears at once, and the
    # narration says it streams in as it is written. Costs one more model call (a few cents).
    toggle = page.locator("label").filter(has_text="Semantic Cache")  # a Streamlit toggle (stCheckbox)
    if toggle.locator("input").first.is_checked():
        toggle.first.click()
        page.wait_for_timeout(500)
    box = page.get_by_placeholder(re.compile("Ask about FastAPI"))
    box.fill(QUESTION)
    box.press("Enter")
    return "sup.fp-cite"  # citations render when the answer is complete


def _sources(page: Any) -> str:
    toggle = page.get_by_text(re.compile(r"^Sources \(\d+\)$")).last  # the expander under the answer
    toggle.scroll_into_view_if_needed()
    toggle.click()
    return ".fp-src-path"


def _agent(page: Any) -> str:
    _pick_mode(page, "Agent")
    box = page.get_by_placeholder(re.compile("Describe an endpoint"))
    box.fill(AGENT_TASK)
    box.press("Enter")
    return 'button:has-text("Send to Playground")'  # appears only once the run has finished


def _playground(page: Any) -> str:
    page.get_by_role("button", name="Send to Playground").click()
    # Wait until Monaco shows the Agent's code; clicking Run earlier raced the editor (live check,
    # 26 Nov 2026) and the run's exit line never came.
    editor = page.frame_locator('iframe[title*="monaco"]').locator(".view-line").first
    editor.wait_for(state="visible", timeout=30_000)
    page.wait_for_timeout(700)
    page.get_by_role("button", name="▶ Run").click()
    return "text=/exit 0 · \\d+ ms/"


def _close(page: Any) -> None:
    page.mouse.wheel(0, -5000)
    return None


ACTIONS: dict[str, Action] = {
    "01-open": _open,
    "02-ask": _ask,
    "03-sources": _sources,
    "05-agent": _agent,
    "06-playground": _playground,
    "08-close": _close,
}


def main() -> None:  # pragma: no cover - drives a real browser
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=LIVE_URL)
    parser.add_argument("--script", type=Path, default=HERE / "script.md")
    parser.add_argument("--durations", type=Path, default=HERE / "out" / "audio" / "durations.json")
    parser.add_argument("--out", type=Path, default=HERE / "out" / "video")
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    script = scenes(args.script)
    lengths = load_durations(args.durations, args.script)
    unknown = [n for n, s in script.items() if s.kind == "footage" and n not in ACTIONS]
    if unknown:
        sys.exit(f"no page actions for footage scenes: {', '.join(unknown)}")

    from playwright.sync_api import sync_playwright

    args.out.mkdir(parents=True, exist_ok=True)
    stem = f"walkthrough-{dt.date.today().isoformat()}"
    raw = args.out / "raw"
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not args.headed)
        size = {"width": 1600, "height": 1000}
        context = browser.new_context(viewport=size, record_video_dir=raw, record_video_size=size, color_scheme="light")
        page = context.new_page()
        marker = Marker(args.out / f"{stem}.log")
        page.goto(args.url)
        for name, scene in script.items():
            try:
                run_scene(page, name, scene, lengths[name], marker, ACTIONS)
            except Exception:
                shot = args.out / f"{stem}-failed-{name}.png"
                page.screenshot(path=str(shot), full_page=True)
                print(f"scene {name} failed; screenshot: {shot}", file=sys.stderr)
                raise
        marker.mark("end")  # closes the last footage scene's window (manifest.py needs it)
        video = page.video
        context.close()
        browser.close()
        shutil.move(video.path(), args.out / f"{stem}.webm")
    shutil.rmtree(raw, ignore_errors=True)
    print(f"wrote {args.out / stem}.webm and .log")


if __name__ == "__main__":
    main()
