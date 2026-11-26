# Showcase video, part A: FastPilot capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce, repeatably, the raw material for the FastPilot demo: a narration in a cloned voice, a Playwright recording of the live site held to that narration, and one manifest that the Remotion project (part B) reads.

**Architecture:** `tools/demo/` in FastPilot, outside the app and its images, with its own Python 3.11 environment (as in Foresight). `narrate.py` (copied from Foresight) renders one WAV per scene and `durations.json`; `walkthrough.py` (Python Playwright, already a FastPilot dev dependency) records the live site, holding each footage scene for its line and logging scene marks; `manifest.py` joins marks and durations into `manifest.json`. Explainer scenes are narrated here but drawn in part B.

**Tech Stack:** Python, Playwright for Python, Chatterbox TTS 0.1.7 (MIT, local), FFmpeg (GIF only, Task 4).

**Spec:** `docs/superpowers/specs/2026-11-26-showcase-video-design.md`

## Global Constraints

- Nothing in `tools/demo/` is imported by `app/`, `frontend/` or `runner/`, or copied into an image. Its packages go in `tools/demo/requirements.txt`, never `pyproject.toml`.
- Never commit a voice recording or rendered audio: `tools/demo/voice/` and `tools/demo/out/` are git-ignored.
- Every frame of the final video says the narration is AI-generated (part B draws it; the manifest carries `"narration": "ai-generated"`).
- The walkthrough records `https://fastpilot.olaheavy.dev` by default; `--url` points it at a local build if Agent and Playground are off on the live site (founder's decision of 26 Nov evening).
- Each live take makes real Gemini and Voyage calls (a few cents) and Opik traces; the questions the walkthrough asks start with "Demo:" so the traces are recognisable.
- Every number the narration states has a source in the repo (claims policy); the script cites it in a trailing HTML comment, which `narrate.py` strips.
- British English; plain writing.

## Review Focus

1. **A scene in `script.md` with no matching mark in the recording** (or the reverse): the manifest must fail, not silently drop the scene. Pinned in Task 3 (`test_manifest_rejects_missing_scene`).
2. **The live answer streams slower than the line is long:** the walkthrough must wait for the answer to finish before holding, not cut it off. Pinned in Task 2 (`hold_for` waits on a completion selector first; `test_hold_waits_for_done_then_line`).
3. **`durations.json` older than `script.md`:** recording to stale timings. Pinned in Task 2 (`test_refuses_stale_durations`).
4. **An explainer scene given a footage window:** part B would cut footage where it should draw a scene. Explainers are marked in the log (the mark ends the previous footage window) but get `start`/`end` null. Pinned in Task 3 (`test_explainer_scenes_have_no_footage`).
5. **The HTML source comment read aloud:** Pinned in Task 1 (`test_scenes_strip_source_comments`).

---

### Task 1: Narration tools and script

**Files:**
- Create: `tools/demo/requirements.txt` (`chatterbox-tts==0.1.7`, `setuptools<81`, `playwright` pinned to FastPilot's lock version), `tools/demo/__init__.py`, `tools/demo/narrate.py`, `tools/demo/script.md`
- Modify: `.gitignore` (`tools/demo/voice/`, `tools/demo/out/`, `tools/demo/.venv/`)
- Test: `tests/test_demo_tools.py`

**Interfaces:**
- Produces: `scenes(script: Path) -> dict[str, Scene]` with `Scene = NamedTuple(text: str, kind: Literal["footage", "explainer"])`; `durations.json` = `{scene_name: seconds}`.

- [ ] **Step 1: Write the failing tests:** `test_scenes_parse_headings_in_order` (`## 01-open (footage)` → key `01-open`, kind `footage`, order kept); `test_scenes_strip_source_comments` (`<!-- source: … -->` absent from `text`); `test_scene_kind_required` (a heading without `(footage)` or `(explainer)` raises `ValueError`).
- [ ] **Step 2: Run:** `uv run pytest tests/test_demo_tools.py -v`. Expected: FAIL, no module `tools.demo.narrate`.
- [ ] **Step 3: Implement.** Copy Foresight's `tools/demo/narrate.py` (MIT; same author), change `scenes()` to return `Scene` with the kind from the heading's parentheses and strip HTML comments; keep `EXAGGERATION, CFG_WEIGHT = 0.4, 0.3`. Torch imports stay inside functions, so the tests run in the app's environment.
- [ ] **Step 4: Write `script.md`:** scenes `01-open (footage)` landing page; `02-ask (footage)` Chat question "Demo: how do I add JWT auth to a FastAPI app?" streaming; `03-sources (footage)` citations and sources; `04-retrieval (explainer)` hybrid search, rerank, grounded answer; `05-agent (footage)` Agent builds and runs an endpoint; `06-playground (footage)` edit and run; `07-runner (explainer)` how a visitor's code is contained; `08-close (footage)`. One line per beat; sources as comments (`docs/evaluation-strategy.md` for any score).
- [ ] **Step 5: Run the tests:** PASS. **Commit:** `Demo tools: narration script and narrate.py (#20)`.

### Task 2: The walkthrough recorder

**Files:**
- Create: `tools/demo/walkthrough.py`
- Test: `tests/test_demo_tools.py`

**Interfaces:**
- Consumes: `scenes()` and `durations.json` (Task 1).
- Produces: a raw `out/video/walkthrough-<date>.webm` and `out/video/walkthrough-<date>.log`, one line per event: `<seconds since start, 2 dp> scene <name>`; CLI `python -m tools.demo.walkthrough --url URL [--durations PATH] [--headed]`.

- [ ] **Step 1: Write the failing tests:** `test_refuses_without_durations` and `test_refuses_stale_durations` (`durations.json` mtime older than `script.md` → `SystemExit` naming the file); `test_hold_waits_for_done_then_line` (with a fake page whose done-selector resolves after 2 s and a 3 s line, `hold_for` returns after ≥ 5 s on a fake clock); `test_explainer_scenes_only_marked` (an explainer scene writes its mark and holds 0.5 s, no page action).
- [ ] **Step 2: Run:** FAIL, no module.
- [ ] **Step 3: Implement** `load_durations(path: Path, script: Path) -> dict[str, float]`, `hold_for(page, done_selector: str | None, seconds: float, clock=time) -> None`, and `main()`. Chromium 1600×1000, `record_video_dir`, light theme (`color_scheme="light"`). Per footage scene, one function in a dict keyed by scene name that performs the page actions; selectors from the Streamlit app (`frontend/app.py`, the visual tests in `tests/test_visual.py` show working ones).
- [ ] **Step 4: Run the tests:** PASS.
- [ ] **Step 5: Live check (manual, costs cents):** render narration (`docs/demo-video.md`, Task 4), then `python -m tools.demo.walkthrough --headed`. Expected: every scene mark in the log, the answer finishes before each hold, Playground shows Monaco. **Commit:** `Demo tools: walkthrough recorder held to the narration (#20)`.

### Task 3: The manifest for part B

**Files:**
- Create: `tools/demo/manifest.py`
- Test: `tests/test_demo_tools.py`

**Interfaces:**
- Consumes: the log (Task 2), `scenes()` and durations (Task 1).
- Produces: `build_manifest(log: Path, video: Path, script: Path, durations: dict[str, float]) -> dict` and `out/manifest.json`:
  ```json
  {"version": 1, "narration": "ai-generated", "recorded": "2026-11-27", "url": "https://fastpilot.olaheavy.dev",
   "video": "walkthrough-2026-11-27.webm",
   "scenes": [{"name": "01-open", "kind": "footage", "start": 0.0, "end": 6.4, "done": 2.1, "audio": "01-open.wav", "seconds": 6.1, "text": "…", "caption": "…"},
              {"name": "04-retrieval", "kind": "explainer", "start": null, "end": null, "done": null, "audio": "04-retrieval.wav", "seconds": 9.8, "text": "…", "caption": "…"}]}
  ```
  Order is the script's. `start`/`end` are footage times from the log; `end` is the next mark's time. The walkthrough writes a final `scene end` mark after the last scene, so the last footage scene has an end. After review (26 Nov 2026): the log also carries `# url …` and `<t> done <name>` lines; `done` and `caption` are in each scene; narration freshness is checked per scene by a hash of its words, not by file times.

- [ ] **Step 1: Write the failing tests:** `test_manifest_orders_by_script`; `test_manifest_rejects_missing_scene` (a scene with no mark → `ValueError` naming it); `test_manifest_rejects_unknown_mark` (a mark not in the script → `ValueError` naming it); `test_manifest_needs_an_end_mark`; `test_explainer_scenes_have_no_footage` (an explainer is marked but gets `start` and `end` null); `test_manifest_marks_ai_narration` (`"narration" == "ai-generated"`).
- [ ] **Step 2: Run:** FAIL. **Step 3: Implement** `build_manifest` and `python -m tools.demo.manifest --log … --video …`. **Step 4: Run:** PASS. **Commit:** `Demo tools: manifest for the Remotion edit (#20)`.

### Task 4: Docs, README GIF step, full check

**Files:**
- Create: `docs/demo-video.md` (setup, record your voice, render narration, record, build manifest, hand to part B, then the GIF; adapted from Foresight's page, with its voice-safety rules)
- Modify: `wiki/log.md`, `wiki/index.md` if a page is added, `docs/planning/status.md` (row 8: part A built)

- [ ] **Step 1:** Write `docs/demo-video.md`; include the GIF command for after part B: `ffmpeg -ss <start> -t 8 -i docs/assets/demo/fastpilot-demo.mp4 -vf "fps=12,scale=960:-1:flags=lanczos" docs/assets/demo/fastpilot-demo.gif`, kept under 5 MB.
- [ ] **Step 2: Full check:** `uv run --frozen ruff check . && scripts/export_constraints.sh --check && uv run pytest`. Expected: all pass, coverage gate green (tools are outside `--cov=app --cov=runner`).
- [ ] **Step 3: Commit:** `Demo video docs and handover (#20)`.
