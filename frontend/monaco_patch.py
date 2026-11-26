"""Point streamlit-monaco's editor at our own copy of Monaco instead of jsDelivr (#65).

streamlit-monaco 0.1.3 has the jsDelivr address of monaco-editor 0.36.1 compiled into its built
web page, so every Playground visitor's browser contacted jsDelivr. The frontend image copies the
checked Monaco files next to that page (``build/monaco/vs``, see ``frontend/Dockerfile``) and runs
this script to replace the address with a relative path. It fails loudly when the address is
missing, so a new streamlit-monaco version cannot quietly bring the CDN back.

Run in the image build: ``python monaco_patch.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

CDN_VS = "https://cdn.jsdelivr.net/npm/monaco-editor@0.36.1/min/vs"
# Relative to the component's index.html, which Streamlit serves under /component/<name>/.
LOCAL_VS = "./monaco/vs"
_CDN_HOST = "cdn.jsdelivr.net"


class PatchError(RuntimeError):
    """The bundle did not look as expected; the image build must stop."""


def _bundle_files(build_dir: Path) -> list[Path]:
    return sorted(p for p in build_dir.rglob("*") if p.is_file() and p.suffix in {".js", ".html"})


def patch_bundle(build_dir: Path, local_vs: str = LOCAL_VS) -> int:
    """Replace ``CDN_VS`` with ``local_vs`` in the bundle; return the number of files changed."""
    changed = 0
    already = False
    for path in _bundle_files(build_dir):
        text = path.read_text(encoding="utf-8")
        if CDN_VS in text:
            path.write_text(text.replace(CDN_VS, local_vs), encoding="utf-8")
            changed += 1
        elif f'"{local_vs}"' in text:
            already = True
    if changed == 0:
        if already:
            raise PatchError(f"{CDN_VS} not found: the bundle in {build_dir} looks already patched ({local_vs})")
        raise PatchError(f"{CDN_VS} not found in {build_dir}: has streamlit-monaco changed? Re-check #65.")
    leftovers = [str(p) for p in _bundle_files(build_dir) if _CDN_HOST in p.read_text(encoding="utf-8")]
    if leftovers:
        raise PatchError(f"{_CDN_HOST} still named in: {', '.join(leftovers)}")
    return changed


def package_build_dir() -> Path:
    """The installed streamlit_monaco/frontend/build folder."""
    spec = importlib.util.find_spec("streamlit_monaco")
    if spec is None or spec.origin is None:
        raise PatchError("streamlit_monaco is not installed")
    return Path(spec.origin).parent / "frontend" / "build"


def main() -> int:
    try:
        changed = patch_bundle(package_build_dir())
    except PatchError as exc:
        print(f"monaco_patch: {exc}", file=sys.stderr)
        return 1
    print(f"patched {changed} file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
