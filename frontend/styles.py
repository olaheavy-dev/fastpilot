"""Injected CSS + pure HTML helpers for the FastPilot UI.

The CSS layer carries the ratified design tokens (round-2 review) as CSS variables
with a ``prefers-color-scheme: dark`` override, so our custom elements (chips, status
badges, citation markers, sources, terminal) flip with the OS the same way Streamlit's
native widgets do via the ``[theme.light]`` / ``[theme.dark]`` config. One rule drives
both, so they can never disagree; there is no in-app theme switch (24 Nov 2026).

The ``*_html`` helpers are pure (no Streamlit import) and emit class-based markup, so
they're theme-independent and unit-testable.
"""

from __future__ import annotations

import difflib
import html
import re

QUERY_TYPE_LABEL = {
    "FACTUAL": "FACTUAL",
    "HOW_TO": "HOW-TO",
    "TROUBLESHOOTING": "TROUBLESHOOTING",
    "CODE_GENERATION": "CODE",
}

_CSS = """
<style>
/* Fonts from our own site, not Google Fonts (#65): frontend/static/fonts/, served at /app/static/.
   The addresses assume the app runs at the site's root; under server.baseUrlPath they must change. */
@font-face { font-family: 'Source Sans 3'; font-style: normal; font-weight: 400; font-display: swap;
  src: url('/app/static/fonts/source-sans-3-latin-400-normal.woff2') format('woff2'); }
@font-face { font-family: 'Source Sans 3'; font-style: normal; font-weight: 500; font-display: swap;
  src: url('/app/static/fonts/source-sans-3-latin-500-normal.woff2') format('woff2'); }
@font-face { font-family: 'Source Sans 3'; font-style: normal; font-weight: 600; font-display: swap;
  src: url('/app/static/fonts/source-sans-3-latin-600-normal.woff2') format('woff2'); }
@font-face { font-family: 'Source Sans 3'; font-style: normal; font-weight: 700; font-display: swap;
  src: url('/app/static/fonts/source-sans-3-latin-700-normal.woff2') format('woff2'); }
@font-face { font-family: 'JetBrains Mono'; font-style: normal; font-weight: 400; font-display: swap;
  src: url('/app/static/fonts/jetbrains-mono-latin-400-normal.woff2') format('woff2'); }
@font-face { font-family: 'JetBrains Mono'; font-style: normal; font-weight: 500; font-display: swap;
  src: url('/app/static/fonts/jetbrains-mono-latin-500-normal.woff2') format('woff2'); }

:root {
  --fp-text: #1C1917; --fp-app-bg: #FAFAF9; --fp-surface: #FFFFFF; --fp-surface-2: #F5F5F4;
  --fp-border: #E7E5E4; --fp-muted: #736C67; --fp-muted-code: #6B6862; --fp-toggle-off: #878079;
  --fp-accent: #0D9488; --fp-accent-btn: #0F766E; --fp-accent-text: #0F766E;
  --fp-accent-soft: #CCFBF1; --fp-accent-soft-bd: #99F6E4;
  --fp-danger: #DC2626; --fp-danger-text: #B91C1C; --fp-danger-soft: #FEE2E2;
  --fp-success: #16A34A; --fp-success-text: #15803D;
}
@media (prefers-color-scheme: dark) {
  :root {
    --fp-text: #E7E9EE; --fp-app-bg: #0C1222; --fp-surface: #151D30; --fp-surface-2: #0A0F1C;
    --fp-border: #28324A; --fp-muted: #8B94A7; --fp-muted-code: #8B94A7; --fp-toggle-off: #6B7489;
    --fp-accent: #2DD4BF; --fp-accent-btn: #2DD4BF; --fp-accent-text: #5EEAD4;
    --fp-accent-soft: #134E4A; --fp-accent-soft-bd: #115E59;
    --fp-danger: #F87171; --fp-danger-text: #FCA5A5; --fp-danger-soft: #3B1A1E;
    --fp-success: #4ADE80; --fp-success-text: #86EFAC;
  }
}

html, body, [class*="css"] { font-family: 'Source Sans 3', system-ui, sans-serif; }
#MainMenu, footer { visibility: hidden; }

/* Welcome hero */
.fp-hero { text-align: center; margin: 2.2rem 0 0.4rem; }
.fp-wordmark {
  font-size: 1.4rem; font-weight: 700; letter-spacing: -0.01em; color: var(--fp-text); margin-bottom: 1rem;
}
.fp-hero h1 { font-size: 2.1rem; font-weight: 650; letter-spacing: -0.02em; margin: 0; color: var(--fp-text); }
.fp-hero p { font-size: 1.02rem; color: var(--fp-muted); max-width: 38rem; margin: 0.5rem auto 0; line-height: 1.55; }

/* Suggestion chips / buttons */
.stButton > button {
  border-radius: 12px; border: 1px solid var(--fp-border); font-weight: 600;
  min-height: 48px; transition: border-color .15s ease, color .15s ease;
}
.stButton > button:hover { border-color: var(--fp-accent); color: var(--fp-accent-text); }

/* Status badges */
.fp-badges { margin: 0 0 .35rem; display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }
.fp-badge {
  display: inline-flex; align-items: center; gap: 4px; padding: 2px 9px; border-radius: 999px;
  font-size: 11px; font-weight: 600; border: 1px solid var(--fp-border); color: var(--fp-muted);
  font-family: 'JetBrains Mono', monospace; letter-spacing: .03em;
}
.fp-badge--cache {
  background: var(--fp-accent-soft); color: var(--fp-accent-text); border-color: var(--fp-accent-soft-bd);
}
.fp-badge--rewrite { background: var(--fp-surface-2); }
.fp-badge--guarded { background: transparent; color: var(--fp-accent-text); border-color: var(--fp-accent); }

/* Conditional-rewrite caption — shows the standalone query a follow-up was rewritten to */
.fp-rewrite-note { font-size: 12px; color: var(--fp-muted); margin: -1px 0 7px; line-height: 1.45; }
.fp-rewrite-note em { font-style: normal; color: var(--fp-text); }

/* Low retrieval-confidence caution — best reranked chunk scored below the floor */
.fp-lowconf {
  font-size: 12.5px; color: var(--fp-danger-text); background: var(--fp-danger-soft);
  border: 1px solid var(--fp-danger); border-radius: 8px; padding: 6px 11px; margin: 2px 0 8px; line-height: 1.45;
}

/* Inline citation markers */
sup.fp-cite { color: var(--fp-accent-text); font-weight: 700; font-size: .72em; padding: 0 1px; }

/* Sources */
.fp-src-path { font-family: 'JetBrains Mono', monospace; font-size: 12.5px; color: var(--fp-text); }
.fp-src-type {
  display: inline-block; padding: 1px 7px; border-radius: 6px; border: 1px solid var(--fp-border);
  font-size: 10px; font-weight: 600; color: var(--fp-muted); text-transform: uppercase; letter-spacing: .04em;
}
.fp-src-snippet { color: var(--fp-muted); font-size: 12.5px; line-height: 1.45; }

/* Terminal (agent/playground, Phase 3) */
.fp-term {
  background: var(--fp-surface-2); border: 1px solid var(--fp-border); border-radius: 10px;
  padding: 10px 13px; font-family: 'JetBrains Mono', monospace; font-size: 12.5px;
  color: var(--fp-text); overflow-x: auto; white-space: pre-wrap;
}
.fp-term .err { color: var(--fp-danger-text); }
.fp-term .foot { margin-top: 6px; font-weight: 600; }
.fp-term .foot.ok { color: var(--fp-success-text); }
.fp-term .foot.bad { color: var(--fp-danger-text); }

/* Agent step timeline */
.fp-steps { display: flex; flex-direction: column; gap: 4px; margin: 2px 0 10px; }
.fp-step { display: flex; align-items: center; gap: 9px; font-size: 13.5px; color: var(--fp-text); }
.fp-step .g { width: 16px; text-align: center; font-weight: 700; }
.fp-step .d { color: var(--fp-muted); font-size: 12.5px; }
.fp-step.done .g { color: var(--fp-success-text); }
.fp-step.error .g { color: var(--fp-danger-text); }
.fp-step.error .d { color: var(--fp-danger-text); }
.fp-step.pending { color: var(--fp-muted); }
.fp-step.pending .g { color: var(--fp-muted); }
.fp-step.running .g { color: var(--fp-accent-text); animation: fp-pulse 1s ease-in-out infinite; }
@keyframes fp-pulse { 0%,100% { opacity: 1; } 50% { opacity: .4; } }
@media (prefers-reduced-motion: reduce) { .fp-step.running .g { animation: none; } }

/* Fix-with-AI diff preview */
.fp-diff { font-family: 'JetBrains Mono', monospace; font-size: 12px; }
.fp-diff .add { color: var(--fp-success-text); }
.fp-diff .del { color: var(--fp-danger-text); }

/* Disclaimer + mode note */
.fp-disclaimer { text-align: center; font-size: 12px; color: var(--fp-muted); margin-top: .4rem; }
.fp-mode-note { font-size: 11.5px; color: var(--fp-muted); margin: -4px 2px 6px; }

/* Long-content guards: a chat message never forces a horizontal page scroll —
   code blocks scroll inside themselves, long words/inline-code wrap. */
[data-testid="stChatMessage"] { overflow-wrap: anywhere; }
[data-testid="stChatMessage"] pre { overflow-x: auto; max-width: 100%; }
[data-testid="stChatMessage"] :not(pre) > code { overflow-wrap: anywhere; word-break: break-word; }

/* Toggle "off" track: Streamlit's default is a faint tint (20% at rest, 15% on hover) that
   nearly disappears on the sidebar (#46). --fp-toggle-off clears 3:1 (WCAG 1.4.11) against
   both the sidebar and the knob: light 3.89:1 / 3.89:1, dark 3.59:1 / 3.86:1. "On" stays the
   theme's teal. One colour for rest and hover (Streamlit's hover tint is dropped, by choice).
   Disabled toggles keep Streamlit's own look. */
[data-testid="stCheckbox"] label:has(input[role="switch"]:not(:checked):not(:disabled)) > span + div {
  background-color: var(--fp-toggle-off);
}

/* Mobile */
@media (max-width: 640px) {
  .block-container { padding: 1rem .75rem 5rem; }
  .fp-hero h1 { font-size: 1.7rem; }
  [data-testid="stColumn"] { min-width: 100% !important; }
}
</style>
"""


def inject_css(st) -> None:  # noqa: ANN001 - st passed in to keep this module import-light
    """Inject the stylesheet. Theme follows the visitor's system (``prefers-color-scheme``),
    the same rule Streamlit uses for its own widgets, so the two always agree."""
    st.markdown(_CSS, unsafe_allow_html=True)


# --- Pure helpers ---------------------------------------------------------
_CITE_RE = re.compile(r"(?<![\w\]])\[(\d+(?:\s*,\s*\d+)*)\]")
# Fenced ```…``` blocks and inline `…` code. Citations inside these must be left alone:
# the <sup> HTML renders as *literal text* in a code context, and lengthening a
# non-wrapping code line is what forces the chat message into a horizontal scroll.
_CODE_RE = re.compile(r"(```.*?```|`[^`]*`)", re.DOTALL)


def _wrap_cites(prose: str) -> str:
    return _CITE_RE.sub(lambda m: f'<sup class="fp-cite">[{m.group(1)}]</sup>', prose)


def render_answer(text: str) -> str:
    """Wrap inline ``[n]`` citation markers in a styled superscript — in PROSE only.

    Fenced and inline code pass through untouched (see ``_CODE_RE``). ``re.split`` with a
    capturing group yields alternating prose / code segments (code lands at odd indices),
    so we wrap citations only in the even (prose) ones. The negative lookbehind still
    guards prose-level indexing like ``items[0]``. Returns HTML for ``unsafe_allow_html``.
    """
    return "".join(seg if i % 2 else _wrap_cites(seg) for i, seg in enumerate(_CODE_RE.split(text)))


def badges_html(
    *, rewritten: bool = False, cache_hit: bool = False, query_type: str | None = None, guarded: bool = False
) -> str:
    """Build the status-badge row HTML (✎ rewritten · ⚡ cache hit · query type / GUARDED)."""
    parts: list[str] = []
    if rewritten:
        parts.append('<span class="fp-badge fp-badge--rewrite">✎ rewritten</span>')
    if cache_hit:
        parts.append('<span class="fp-badge fp-badge--cache">⚡ cache hit</span>')
    if guarded:
        # A guarded refusal replaces the query-type badge with an outline GUARDED pill.
        parts.append('<span class="fp-badge fp-badge--guarded">GUARDED</span>')
    elif query_type:
        label = QUERY_TYPE_LABEL.get(query_type, query_type)
        parts.append(f'<span class="fp-badge">{html.escape(label)}</span>')
    if not parts:
        return ""
    return '<div class="fp-badges">' + "".join(parts) + "</div>"


def rewrite_note_html(standalone: str | None) -> str:
    """Caption revealing the standalone query a follow-up was rewritten to (empty if none),
    e.g. ↻ searched as: *Can a query parameter with a default value be an integer?*"""
    if not standalone:
        return ""
    return f'<div class="fp-rewrite-note">↻ searched as: <em>{html.escape(standalone)}</em></div>'


def low_confidence_note_html() -> str:
    """Caution shown when the best reranked chunk scored below the confidence floor — the
    retrieval-confidence guard's user-facing warning that the answer may be off-corpus."""
    return (
        '<div class="fp-lowconf">⚠ Low retrieval confidence — this may be outside the FastAPI '
        "docs, so double-check the answer.</div>"
    )


def source_label(metadata: dict) -> str:
    """Frontend mirror of the backend label (the backend already puts the resolved
    label in ``metadata.file_path``, but fall through for safety)."""
    for key in ("file_path", "file", "title", "source_id", "name"):
        value = metadata.get(key)
        if value:
            return str(value)
    return str(metadata.get("source") or metadata.get("category") or "unknown")


_STEP_GLYPH = {"done": "✓", "error": "✗", "running": "●", "pending": "○"}
_STEP_LABEL = {"plan": "Plan", "retrieve": "Retrieve", "write": "Write code", "fix": "Fix & rerun", "run": "Run"}


def timeline_html(steps: list[dict]) -> str:
    """Render the agent step list. Each step: {name, status, detail}."""
    rows = []
    for s in steps:
        status = s.get("status", "running")
        glyph = _STEP_GLYPH.get(status, "●")
        label = _STEP_LABEL.get(s.get("name", ""), s.get("name", ""))
        detail = html.escape(str(s.get("detail", "")))
        rows.append(
            f'<div class="fp-step {status}"><span class="g">{glyph}</span>'
            f'<span>{label}</span><span class="d">{detail}</span></div>'
        )
    return '<div class="fp-steps">' + "".join(rows) + "</div>"


def terminal_html(stdout: str, stderr: str, exit_code: int, duration_ms: int, timed_out: bool = False) -> str:
    """Render a terminal output block (dimmed stdout + danger-tinted stderr + exit footer)."""
    body = f'<span class="out">{html.escape(stdout)}</span>' if stdout else ""
    if stderr:
        body += ("\n" if body else "") + f'<span class="err">{html.escape(stderr)}</span>'
    ok = exit_code == 0 and not timed_out
    foot = f"exit {exit_code} · {duration_ms} ms" if not timed_out else "killed · time limit"
    cls = "ok" if ok else "bad"
    return f'<div class="fp-term">{body}<div class="foot {cls}">{foot}</div></div>'


def diff_html(old: str, new: str, max_rows: int = 40) -> str:
    """Compact ±line pseudo-diff for the Fix-with-AI preview (no dependency — difflib)."""
    rows: list[str] = []
    for line in difflib.unified_diff((old or "").splitlines(), (new or "").splitlines(), lineterm="", n=1):
        if line[:3] in ("---", "+++") or line.startswith("@@"):
            continue
        cls = "add" if line.startswith("+") else "del" if line.startswith("-") else ""
        rows.append(f'<div class="{cls}">{html.escape(line) or "&nbsp;"}</div>')
        if len(rows) >= max_rows:
            rows.append('<div class="del">… (diff truncated)</div>')
            break
    return '<div class="fp-diff">' + "".join(rows) + "</div>" if rows else ""
