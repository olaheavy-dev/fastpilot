"""Join the walkthrough's scene marks and the narration into manifest.json for the Remotion edit (#20).

Part B of the showcase-video plan (personal-website `tools/explainers/`) reads this file: where each
footage scene starts and ends in the recording, which audio file narrates it, how long that line
is, and its text for captions. Explainer scenes have no footage window; Remotion draws them.

    python -m tools.demo.manifest --log out/video/walkthrough-2026-11-27-190533.log \\
        --video out/video/walkthrough-2026-11-27-190533.webm

Writes `out/manifest.json`. It stops with the scene named if the log and the script disagree.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from tools.demo.narrate import scenes
from tools.demo.walkthrough import load_durations

HERE = Path(__file__).resolve().parent
END = "end"
_MARK = re.compile(r"^(\d+(?:\.\d+)?) (scene|done) (\S+)$")
_URL = re.compile(r"^# url (\S+)$")
_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
LIVE_URL = "https://fastpilot.olaheavy.dev"


def _read_log(log: Path) -> tuple[list[tuple[str, float]], dict[str, float], str | None]:
    """Scene marks in order, done times by scene, and the URL the take recorded (if logged)."""
    marks: list[tuple[str, float]] = []
    done: dict[str, float] = {}
    url = None
    for line in log.read_text().splitlines():
        line = line.strip()
        if match := _URL.match(line):
            url = match.group(1)
        elif match := _MARK.match(line):
            seconds, event, name = float(match.group(1)), match.group(2), match.group(3)
            if event == "scene":
                marks.append((name, seconds))
            else:
                done[name] = seconds
    return marks, done, url


def build_manifest(
    log: Path, video: Path, script: Path, durations: dict[str, float], url: str = LIVE_URL
) -> dict[str, Any]:
    """The manifest as a dict (see the module docstring). Raises ValueError naming any mismatch.

    Each footage scene gets `done`: when the page showed it finished (a streamed answer, an agent
    run), so part B can speed up a long wait after the line ends. The URL comes from the log when
    the walkthrough wrote it (a local build is then named), else from `url`.
    """
    script_scenes = scenes(script)
    marks, done, logged_url = _read_log(log)
    names = [name for name, _ in marks]
    unknown = [n for n in names if n != END and n not in script_scenes]
    if unknown:
        raise ValueError(f"marks in {log.name} not in the script: {', '.join(unknown)}")
    missing = [n for n in script_scenes if n not in names]
    if missing:
        raise ValueError(f"scenes with no mark in {log.name}: {', '.join(missing)}")
    if not names or names[-1] != END:
        raise ValueError(f"{log.name} has no final `scene {END}` mark: was the recording cut short?")
    no_length = [n for n in script_scenes if n not in durations]
    if no_length:
        raise ValueError(f"no narration length for: {', '.join(no_length)} (render the narration)")

    times = dict(marks)
    following = {name: marks[i + 1][1] for i, (name, _) in enumerate(marks[:-1])}
    out = []
    for name, scene in script_scenes.items():
        footage = scene.kind == "footage"
        out.append(
            {
                "name": name,
                "kind": scene.kind,
                "start": times[name] if footage else None,
                "end": following[name] if footage else None,
                "done": done.get(name) if footage else None,
                "audio": f"{name}.wav",
                "seconds": durations[name],
                "text": scene.text,
                "caption": scene.caption or scene.text,
            }
        )
    date = _DATE.search(video.name)
    return {
        "version": 1,
        "narration": "ai-generated",
        "recorded": date.group(1) if date else "",
        "url": logged_url or url,
        "video": video.name,
        "scenes": out,
    }


def main() -> None:  # pragma: no cover - a thin command-line wrapper
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--video", type=Path, required=True)
    parser.add_argument("--script", type=Path, default=HERE / "script.md")
    parser.add_argument("--durations", type=Path, default=HERE / "out" / "audio" / "durations.json")
    parser.add_argument("--url", default=LIVE_URL)
    parser.add_argument("--out", type=Path, default=HERE / "out" / "manifest.json")
    args = parser.parse_args()
    durations = load_durations(args.durations, args.script)  # refuses stale narration too
    manifest = build_manifest(args.log, args.video, args.script, durations, args.url)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {args.out} ({len(manifest['scenes'])} scenes)")


if __name__ == "__main__":
    main()
