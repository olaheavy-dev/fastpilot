"""Visitors' browsers load fonts and the Monaco editor from our own site only (#65).

Google Fonts and jsDelivr each received every visitor's IP address and referrer, and the privacy
note names neither. Founder's choice, 25 Nov 2026: "Self-host both (Recommended)".
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
FONTS = FRONTEND / "static" / "fonts"

FORBIDDEN_HOSTS: tuple[str, ...] = ("fonts.googleapis.com", "fonts.gstatic.com", "cdn.jsdelivr.net")

# (family, weight, file in frontend/static/fonts/)
FONT_FACES = [
    ("Source Sans 3", 400, "source-sans-3-latin-400-normal.woff2"),
    ("Source Sans 3", 500, "source-sans-3-latin-500-normal.woff2"),
    ("Source Sans 3", 600, "source-sans-3-latin-600-normal.woff2"),
    ("Source Sans 3", 700, "source-sans-3-latin-700-normal.woff2"),
    ("JetBrains Mono", 400, "jetbrains-mono-latin-400-normal.woff2"),
    ("JetBrains Mono", 500, "jetbrains-mono-latin-500-normal.woff2"),
]

# Files allowed to name a forbidden host: font licences, and the patch script, whose constant
# must stay greppable so the address it replaces is obvious.
_ALLOWED = {"monaco_patch.py"}


def _frontend_text_files():
    for path in FRONTEND.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        if path.suffix in {".woff2", ".pyc"} or path.name.startswith("OFL-") or path.name in _ALLOWED:
            continue
        yield path


def test_no_third_party_hosts_in_frontend():
    offenders = []
    for path in _frontend_text_files():
        text = path.read_text(encoding="utf-8", errors="ignore")
        offenders += [f"{path.relative_to(ROOT)}: {host}" for host in FORBIDDEN_HOSTS if host in text]
    assert offenders == []


def test_static_serving_on():
    config = tomllib.loads((FRONTEND / ".streamlit" / "config.toml").read_text())
    assert config["server"]["enableStaticServing"] is True


def _font_face_blocks() -> list[str]:
    import styles  # frontend/ is on pytest's pythonpath (pyproject.toml)

    css = Path(styles.__file__).read_text()
    return re.findall(r"@font-face\s*\{[^}]*\}", css)


def test_font_faces_point_at_local_files():
    blocks = _font_face_blocks()
    for family, weight, filename in FONT_FACES:
        matching = [
            b
            for b in blocks
            if f"font-family: '{family}'" in b and re.search(rf"font-weight:\s*{weight}\b", b)
        ]
        assert len(matching) == 1, f"one @font-face for {family} {weight}"
        block = matching[0]
        assert f"url('/app/static/fonts/{filename}') format('woff2')" in block
        assert "font-display: swap" in block
        font = FONTS / filename
        assert font.is_file(), font
        assert font.read_bytes()[:4] == b"wOF2", f"{filename} is not a woff2 file"


def test_font_licences_shipped():
    for name in ("OFL-SourceSans3.txt", "OFL-JetBrainsMono.txt"):
        text = (FONTS / name).read_text(encoding="utf-8")
        assert "SIL OPEN FONT LICENSE" in text.upper()
