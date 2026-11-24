"""Theme rules: one theme system (the visitor's system setting), both themes complete and readable.

Background (24 Nov 2026 review): an in-app toggle forced our CSS tokens but could not switch
Streamlit's own widgets, so a toggle that disagreed with the system left code blocks, radios,
captions and icons in the other theme. Founder's choice: "Follow the system only (Recommended)".
These tests keep that from coming back and measure contrast instead of eyeballing it.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CONFIG = tomllib.loads((ROOT / "frontend" / ".streamlit" / "config.toml").read_text())

import styles  # noqa: E402  (frontend/ is on pytest's pythonpath, pyproject.toml)


def _luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    channels = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _blocks() -> tuple[dict[str, str], dict[str, str]]:
    """Return (bare :root tokens, dark-scheme overrides) from the stylesheet."""
    css = styles._CSS
    root = re.search(r"^:root\s*\{(.*?)\}", css, re.S | re.M)
    dark = re.search(r"@media \(prefers-color-scheme: dark\)\s*\{\s*:root\s*\{(.*?)\}", css, re.S)
    assert root and dark, "expected a bare :root block and a prefers-color-scheme: dark override"

    def parse(body: str) -> dict[str, str]:
        return {k: v.strip() for k, v in re.findall(r"(--fp-[\w-]+)\s*:\s*([^;]+)", body)}

    return parse(root.group(1)), parse(dark.group(1))


def test_inject_css_takes_no_theme_and_forces_nothing():
    calls: list[str] = []

    class FakeSt:
        @staticmethod
        def markdown(body, unsafe_allow_html=False):  # noqa: ANN001, ANN205
            calls.append(body)

    styles.inject_css(FakeSt)
    assert len(calls) == 1, "one stylesheet; no second, forced-theme block"
    css = calls[0]
    for native in ('[data-testid="stBottom"]', '[data-testid="stHeader"]', '[data-testid="stChatInput"] div'):
        assert native not in css, f"Streamlit's own surfaces are themed by config.toml, not by {native} overrides"


def test_every_dark_token_has_a_light_definition_on_bare_root():
    light, dark = _blocks()
    missing = sorted(set(dark) - set(light))
    assert not missing, f"tokens defined only for dark mode (invisible in light): {missing}"
    assert "--fp-app-bg" in light


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_config_themes_set_code_and_border_colours(theme):
    section = CONFIG["theme"][theme]
    for key in ("primaryColor", "backgroundColor", "secondaryBackgroundColor", "textColor",
                "codeTextColor", "codeBackgroundColor", "borderColor", "linkColor"):
        assert key in section, f"[theme.{theme}] must set {key}, or Streamlit falls back to its defaults"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_text_contrast_in_both_themes(theme):
    cfg = CONFIG["theme"][theme]
    light, dark = _blocks()
    tokens = light if theme == "light" else {**light, **dark}
    bg = tokens["--fp-app-bg"]
    assert bg.lower() == cfg["backgroundColor"].lower(), "CSS app background must match config.toml"
    checks = {
        "body text": (cfg["textColor"], cfg["backgroundColor"]),
        "muted text": (tokens["--fp-muted"], bg),
        "inline/block code": (cfg["codeTextColor"], cfg["codeBackgroundColor"]),
        "links": (cfg["linkColor"], cfg["backgroundColor"]),
        "accent text": (tokens["--fp-accent-text"], bg),
    }
    # Every (text token, surface token) pair the stylesheet actually draws, not only the page.
    pairs = [
        ("--fp-muted", "--fp-surface"),  # sidebar notes, sources inside expanders
        ("--fp-muted", "--fp-surface-2"),  # the "rewritten" badge
        ("--fp-accent-text", "--fp-accent-soft"),  # the "cache hit" badge
        ("--fp-danger-text", "--fp-danger-soft"),  # the low-confidence caution
        ("--fp-text", "--fp-surface-2"),  # terminal output
        ("--fp-success-text", "--fp-surface-2"),  # terminal "exit 0" footer
        ("--fp-danger-text", "--fp-surface-2"),  # terminal stderr
        ("--fp-success-text", "--fp-app-bg"),  # agent step ticks
        ("--fp-danger-text", "--fp-app-bg"),  # agent step errors, diff deletions
    ]
    for fg_token, bg_token in pairs:
        checks[f"{fg_token} on {bg_token}"] = (tokens[fg_token], tokens[bg_token])
    for name, (fg, back) in checks.items():
        ratio = _contrast(fg, back)
        assert ratio >= 4.5, f"{theme} {name}: {fg} on {back} is {ratio:.2f}:1, needs 4.5:1"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_code_blocks_stand_out_from_the_page(theme):
    cfg = CONFIG["theme"][theme]
    ratio = _contrast(cfg["codeBackgroundColor"], cfg["backgroundColor"])
    assert ratio >= 1.08, f"{theme}: code background is indistinguishable from the page ({ratio:.2f}:1)"


def test_no_text_is_faded_with_opacity():
    """Opacity on text drops it below 4.5:1 (the disclaimer was 3.44:1, pending steps 1.93:1).
    Only the running-step pulse animation may change opacity."""
    css = re.sub(r"@keyframes fp-pulse \{.*?\}\s*\}", "", styles._CSS, flags=re.S)
    faded = [line.strip() for line in css.splitlines() if "opacity" in line]
    assert not faded, f"rules that fade with opacity: {faded}"


@pytest.mark.parametrize(
    ("streamlit_theme", "expected"),
    [("dark", "vs-dark"), ("light", "streamlit"), (None, "streamlit")],
)
def test_playground_editor_uses_a_dark_syntax_theme_in_dark_mode(monkeypatch, streamlit_theme, expected):
    """streamlit-monaco's "streamlit" theme always uses Monaco's light syntax colours (base "vs"),
    so dark mode showed dark-blue keywords on a dark page. Dark mode asks for "vs-dark" instead."""
    import playground_view

    class Theme:
        type = streamlit_theme

    class Ctx:
        theme = Theme()

    monkeypatch.setattr(playground_view.st, "context", Ctx())
    assert playground_view._monaco_theme() == expected
