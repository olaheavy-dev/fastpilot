"""Render the demo's narration (tools/demo/script.md), one WAV per scene, in a cloned voice.

Adapted from Foresight's tools/demo/narrate.py (same author) for FastPilot's showcase video (#20):
each scene heading carries its kind, `(footage)` or `(explainer)`, and `<!-- source: … -->`
comments (where a number comes from) are never read aloud.

Uses Chatterbox (Resemble AI, MIT licence) locally: on Apple Silicon it runs on the GPU (MPS), and
neither the reference recording nor the text leaves the machine. Every output carries Resemble's
inaudible Perth watermark, so it can be identified as generated. See docs/demo-video.md.

    python -m tools.demo.narrate --voice tools/demo/voice/reference.wav    # every scene
    python -m tools.demo.narrate --voice ... --only 02-ask 05-agent         # some scenes again

It also writes out/audio/durations.json: each scene's length and a hash of its words. The
walkthrough and the manifest read it, and refuse a scene whose words changed since it was rendered:
render the narration before recording. See docs/demo-video.md.

Run it in the demo environment (tools/demo/requirements.txt), not the app's.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal, NamedTuple

HERE = Path(__file__).resolve().parent
# The settings chosen on 25 Oct 2026 ("calmer"): less expressive and steadier than the defaults.
EXAGGERATION, CFG_WEIGHT = 0.4, 0.3
PAUSE_SECONDS = 0.45  # between paragraphs within a scene


class Scene(NamedTuple):
    text: str  # what is read aloud
    kind: Literal["footage", "explainer"]
    caption: str | None = None  # what is shown, when it differs (e.g. a web address)


_HEADING = re.compile(r"^## (\S+)([^\n]*)$", re.M)
_KIND = re.compile(r"\((footage|explainer)\)")
_CAPTION = re.compile(r"<!--\s*caption:\s*(.*?)\s*-->", re.S)
_COMMENT = re.compile(r"[ \t]*<!--.*?-->", re.S)


def text_hash(text: str) -> str:
    """Identifies the words a WAV was rendered from, so stale narration can be named."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def scenes(script: Path) -> dict[str, Scene]:
    """`## <name> (footage|explainer)` headings to their narration, in script order.

    Refuses a heading without a kind, an empty scene, a repeated name and an unclosed comment, so
    no scene vanishes and no comment is read aloud.
    """
    source = script.read_text()
    headings = list(_HEADING.finditer(source))
    found: dict[str, Scene] = {}
    for i, match in enumerate(headings):
        name, rest = match.group(1), match.group(2)
        body = source[match.end() : headings[i + 1].start() if i + 1 < len(headings) else len(source)]
        kind = _KIND.search(rest)
        if not kind:
            raise ValueError(f"scene {name}: the heading needs (footage) or (explainer)")
        if name in found:
            raise ValueError(f"scene {name} appears twice")
        caption = _CAPTION.search(body)
        text = _COMMENT.sub("", body).strip()
        if "<!--" in text or "-->" in text:
            raise ValueError(f"scene {name}: a comment is not closed, so it would be read aloud")
        if not text:
            raise ValueError(f"scene {name} has no narration")
        found[name] = Scene(text=text, kind=kind.group(1), caption=caption.group(1) if caption else None)
    return found


def load_model() -> Any:
    import torch
    from chatterbox.tts import ChatterboxTTS

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    # The checkpoints were saved on CUDA: map them onto whatever this machine has.
    original = torch.load
    torch.load = lambda *a, **k: original(*a, **{**k, "map_location": torch.device(device)})
    try:
        return ChatterboxTTS.from_pretrained(device=device)
    finally:
        torch.load = original


def render(model: Any, text: str, voice: Path, out: Path, exaggeration: float, cfg: float) -> float:
    import torch
    import torchaudio

    pause = torch.zeros(1, int(model.sr * PAUSE_SECONDS))
    parts: list[Any] = []
    for paragraph in [p.strip() for p in text.split("\n\n") if p.strip()]:
        wav = model.generate(
            paragraph, audio_prompt_path=str(voice), exaggeration=exaggeration, cfg_weight=cfg
        )
        parts += [pause, wav.cpu()] if parts else [wav.cpu()]
    audio = torch.cat(parts, dim=1)
    torchaudio.save(str(out), audio, model.sr)
    return float(audio.shape[1] / model.sr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--voice", type=Path, required=True, help="reference recording, 10–20 s")
    parser.add_argument("--script", type=Path, default=HERE / "script.md")
    parser.add_argument("--out", type=Path, default=HERE / "out" / "audio")
    parser.add_argument("--only", nargs="*", help="scene names to render again (default: all)")
    parser.add_argument("--exaggeration", type=float, default=EXAGGERATION)
    parser.add_argument("--cfg", type=float, default=CFG_WEIGHT)
    args = parser.parse_args()

    todo = scenes(args.script)
    if args.only:
        unknown = set(args.only) - set(todo)
        if unknown:
            parser.error(f"no such scene: {', '.join(sorted(unknown))}")
        todo = {name: todo[name] for name in args.only}
    args.out.mkdir(parents=True, exist_ok=True)
    # Each scene's length, read by the walkthrough so it holds every scene for its line (the video
    # is recorded to the narration, not the other way round).
    lengths_file = args.out / "durations.json"
    lengths = json.loads(lengths_file.read_text()) if lengths_file.exists() else {}
    model = load_model()
    for name, scene in todo.items():
        seconds = render(model, scene.text, args.voice, args.out / f"{name}.wav", args.exaggeration,
                         args.cfg)  # fmt: skip
        lengths[name] = {"seconds": round(seconds, 2), "text_sha": text_hash(scene.text)}
        lengths_file.write_text(json.dumps(lengths, indent=2, sort_keys=True) + "\n")
        print(f"{name}: {seconds:.1f}s", flush=True)


if __name__ == "__main__":
    main()
