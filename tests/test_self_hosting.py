"""Visitors' browsers load fonts and the Monaco editor from our own site only (#65).

Google Fonts and jsDelivr each received every visitor's IP address and referrer, and the privacy
note names neither. Founder's choice, 25 Nov 2026: "Self-host both (Recommended)".
"""

from __future__ import annotations

import re
import shutil
import tomllib
from pathlib import Path

import monaco_patch  # frontend/ is on pytest's pythonpath (pyproject.toml)
import pytest
from monaco_patch import CDN_VS, LOCAL_VS, PatchError, package_build_dir, patch_bundle

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


_SKIP_DIRS = {"__pycache__", "node_modules"}


def _frontend_text_files(root: Path = FRONTEND):
    for path in sorted(root.rglob("*")):
        parts = path.relative_to(root).parts[:-1]
        if not path.is_file() or any(p in _SKIP_DIRS or (p.startswith(".") and p != ".streamlit") for p in parts):
            continue
        if path.suffix in {".woff2", ".pyc"} or path.name.startswith("OFL-") or path.name in _ALLOWED:
            continue
        yield path


def test_scan_skips_installed_and_hidden_folders(tmp_path):
    """A local `node_modules` or `.venv` inside frontend/ is not our code; scanning it would be
    slow and could fail on third-party files."""
    for folder in ("node_modules", ".venv"):
        (tmp_path / folder).mkdir()
        (tmp_path / folder / "x.js").write_text("https://cdn.jsdelivr.net/npm/x")
    (tmp_path / "ours.py").write_text("x = 1")
    assert [p.name for p in _frontend_text_files(tmp_path)] == ["ours.py"]


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


# --- Monaco: streamlit-monaco's bundle names jsDelivr; the image build rewrites it -------------

def _add_monaco_files(build: Path) -> None:
    """Stand-ins for the files the image copies to build/monaco/vs (frontend/Dockerfile)."""
    vs = build / "monaco" / "vs"
    (vs / "editor").mkdir(parents=True)
    (vs / "loader.js").write_text("// loader")
    (vs / "editor" / "editor.main.js").write_text("// editor")


def _copy_build(tmp_path: Path) -> Path:
    dest = tmp_path / "build"
    shutil.copytree(package_build_dir(), dest)
    _add_monaco_files(dest)
    return dest


def _files_containing(folder: Path, text: str) -> list[Path]:
    return [p for p in folder.rglob("*") if p.is_file() and text in p.read_text(encoding="utf-8", errors="ignore")]


def test_patch_rewrites_real_bundle(tmp_path):
    build = _copy_build(tmp_path)
    assert patch_bundle(build) == 1
    assert _files_containing(build, "cdn.jsdelivr.net") == []
    assert len(_files_containing(build, f'"{LOCAL_VS}"')) == 1


def test_patch_fails_when_monaco_files_missing(tmp_path):
    """A wrong COPY path (say, a new Python version in the base image) must stop the build: the
    browser would get 404s and an empty editor, not the plain text box."""
    build = tmp_path / "build"
    shutil.copytree(package_build_dir(), build)
    with pytest.raises(PatchError, match="Monaco files missing"):
        patch_bundle(build)
    assert _files_containing(build, CDN_VS) != []  # nothing rewritten


def test_patch_fails_when_address_missing(tmp_path):
    _add_monaco_files(tmp_path)
    (tmp_path / "chunk.js").write_text('const vs = "somewhere/else";')
    with pytest.raises(PatchError, match="not found"):
        patch_bundle(tmp_path)


def test_patch_fails_on_leftover_cdn(tmp_path):
    _add_monaco_files(tmp_path)
    (tmp_path / "a.js").write_text(f'paths:{{vs:"{CDN_VS}"}}')
    (tmp_path / "b.js").write_text('load("https://cdn.jsdelivr.net/npm/other@1/x.js")')
    with pytest.raises(PatchError, match="still"):
        patch_bundle(tmp_path)


def test_patch_is_idempotent_failure_message(tmp_path):
    build = _copy_build(tmp_path)
    assert patch_bundle(build) == 1
    with pytest.raises(PatchError, match="already patched"):
        patch_bundle(build)


def test_main_reports_failure_with_exit_code(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(monaco_patch, "package_build_dir", lambda: tmp_path)
    assert monaco_patch.main() == 1
    assert "Monaco files missing" in capsys.readouterr().err


def test_installed_package_not_modified():
    assert _files_containing(package_build_dir(), CDN_VS) != []


# --- The frontend image copies only what it runs (#70) -----------------------------------------


def _segments_match(pattern: list[str], path: list[str]) -> bool:
    import fnmatch

    if not pattern:
        return not path
    if pattern[0] == "**":
        return any(_segments_match(pattern[1:], path[n:]) for n in range(len(path) + 1))
    return bool(path) and fnmatch.fnmatchcase(path[0], pattern[0]) and _segments_match(pattern[1:], path[1:])


def _ignored(path: str, patterns: list[str]) -> bool:
    """Docker's rule for our patterns: `*` stays inside one path segment, `**` spans any number,
    a pattern that matches a folder ignores everything under it, the last matching line wins,
    and `!` re-includes."""
    parts = path.split("/")
    result = False
    for raw in patterns:
        negate, pattern = raw.startswith("!"), raw.lstrip("!")
        segs = pattern.split("/")
        if any(_segments_match(segs, parts[:n]) for n in range(1, len(parts) + 1)):
            result = not negate
    return result


def test_frontend_dockerignore_keeps_notes_out_and_app_in():
    patterns = [
        line.strip()
        for line in (FRONTEND / ".dockerignore").read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    for path in ("__pycache__/app.cpython-312.pyc", "static/__pycache__/x.pyc", ".DS_Store",
                 "static/fonts/.DS_Store", "WATCHTOWER_PROOF.md", "railway.toml"):
        assert _ignored(path, patterns), f"{path} should stay out of the image"
    # Everything the image runs, checked as real files, so a broad pattern (`*`, `**/*.py`,
    # `static/**`) can't slip through.
    needed = [
        p.relative_to(FRONTEND).as_posix()
        for p in sorted(FRONTEND.rglob("*"))
        if p.is_file()
        and "__pycache__" not in p.parts
        and (p.suffix in {".py", ".txt", ".toml", ".woff2"})
        and p.name != "railway.toml"
    ]
    assert "app.py" in needed and ".streamlit/config.toml" in needed and "monaco_patch.py" in needed
    kept_out = [p for p in needed if _ignored(p, patterns)]
    assert kept_out == []


def test_dockerignore_check_catches_broad_patterns():
    """The checker itself: a catch-all or a font wildcard must count as ignoring app files."""
    assert _ignored("app.py", ["*"])
    assert _ignored("static/fonts/x.woff2", ["static"])
    assert _ignored("static/fonts/x.woff2", ["**/*.woff2"])
    assert not _ignored("static/fonts/README.md", ["*.md"])  # top level only, as in Docker
    assert not _ignored("app.py", ["*", "!*.py"])
