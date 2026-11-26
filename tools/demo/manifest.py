"""Join the walkthrough's scene marks and the narration into manifest.json for the Remotion edit (#20).

Part B of the showcase-video plan (personal-website `tools/explainers/`) reads this file: where each
footage scene starts and ends in the recording, which audio file narrates it, how long that line
is, and its text for captions. Explainer scenes have no footage window; Remotion draws them.

    python -m tools.demo.manifest --log out/video/walkthrough-2026-11-27.log \\
        --video out/video/walkthrough-2026-11-27.webm

Writes `out/manifest.json`. It stops with the scene named if the log and the script disagree.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from tools.demo.narrate import scenes

HERE = Path(__file__).resolve().parent
END = "end"
_MARK = re.compile(r"^(\d+(?:\.\d+)?) scene (\S+)$")
_DATE = re.compile(r"(\d{4}-\d{2}-\d{2})")
LIVE_URL = "https://fastpilot.olaheavy.dev"


def _marks(log: Path) -> list[tuple[str, float]]:
    found = []
    for line in log.read_text().splitlines():
        match = _MARK.match(line.strip())
        if match:
            found.append((match.group(2), float(match.group(1))))
    return found


def build_manifest(
    log: Path, video: Path, script: Path, durations: dict[str, float], url: str = LIVE_URL
) -> dict[str, Any]:
    """The manifest as a dict (see the module docstring). Raises ValueError naming any mismatch."""
    script_scenes = scenes(script)
    marks = _marks(log)
    names = [name for name, _ in marks]
    unknown = [n for n in names if n != END and n not in script_scenes]
    if unknown:
        raise ValueError(f"marks in {log.name} not in the script: {', '.join(unknown)}")
    missing = [n for n in script_scenes if n not in names]
    if missing:
        raise ValueError(f"scenes with no mark in {log.name}: {', '.join(missing)}")
    if not names or names[-1] != END:
        raise ValueError(f"{log.name} has no final `scene {END}` mark: was the recording cut short?")

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
                "audio": f"{name}.wav",
                "seconds": durations[name],
                "text": scene.text,
            }
        )
    date = _DATE.search(video.name)
    return {
        "version": 1,
        "narration": "ai-generated",
        "recorded": date.group(1) if date else "",
        "url": url,
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
    durations = json.loads(args.durations.read_text())
    manifest = build_manifest(args.log, args.video, args.script, durations, args.url)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {args.out} ({len(manifest['scenes'])} scenes)")


if __name__ == "__main__":
    main()
