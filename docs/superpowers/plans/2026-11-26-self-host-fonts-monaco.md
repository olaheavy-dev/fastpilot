# Self-host the fonts and the Monaco editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Visitors' browsers load the fonts and the Monaco editor from fastpilot.olaheavy.dev only, never from Google Fonts or jsDelivr (#65).

**Architecture:** Font files live in `frontend/static/fonts/` and Streamlit's static serving hands them out at `/app/static/fonts/`; `@font-face` rules in `frontend/styles.py` replace the Google `@import`. A Dockerfile build stage downloads `monaco-editor` 0.36.1, checks its SHA-256 and copies `min/vs` beside `streamlit-monaco`'s built files; `frontend/monaco_patch.py` then rewrites the jsDelivr address in that bundle to a relative path, failing the build if it can't.

**Tech Stack:** Streamlit (static serving), `streamlit-monaco` 0.1.3, Docker multi-stage build, pytest.

**Spec:** `docs/superpowers/specs/2026-11-26-self-host-fonts-monaco-design.md`

**Execution:** native (founder, 26 Nov 2026: "Native, one review (Recommended)"), then one fresh-context review of the whole branch.

## Global Constraints

- Monaco stays **0.36.1**; tarball `https://registry.npmjs.org/monaco-editor/-/monaco-editor-0.36.1.tgz`, SHA-256 `0ffa1c42ef6939339031a1e9c72af6cc863773febe992b85a746dc24a6e07251`. Copy only `package/min/vs`.
- The address to replace is exactly `https://cdn.jsdelivr.net/npm/monaco-editor@0.36.1/min/vs`.
- Forbidden hosts anywhere under `frontend/` (except licence text): `fonts.googleapis.com`, `fonts.gstatic.com`, `cdn.jsdelivr.net`.
- Fonts: Source Sans 3 at 400, 500, 600, 700; JetBrains Mono at 400, 500; Latin subset, `.woff2`, `font-display: swap`; ship each font's OFL licence file. Licence: SIL Open Font License 1.1.
- No change to Caddy, the infra repository, the privacy note's wording, or `streamlit-monaco`'s version.
- Ruff `E/F/I/B`, line length 120; default test run stays hermetic (`uv run pytest`, no network).
- New packages: none in Python. The font files come from the `@fontsource/source-sans-3` and `@fontsource/jetbrains-mono` npm packages (OFL), a release at least 7 days old; record their versions in `frontend/static/fonts/README.md`. (Plan's call: the spec left the source open; fontsource gives ready Latin-subset `.woff2` files per weight.)
- Never push to `main`, never force-push; no agent attribution lines in commits or the pull request.

## Review Focus

1. **Monaco fails to load and Playground quietly shows the plain editor.** Every unit test still passes. Pinned by the browser check in Task 3, step 6 (the "Plain editor" caption must not appear).
2. **A future `streamlit-monaco` moves or reformats the address** (another chunk file, or a different version string). `patch_bundle` must fail, not succeed with zero replacements: Task 2, `test_patch_fails_when_address_missing`.
3. **The relative path resolves against the wrong base** (the chunk's folder instead of the component page), so the loader requests `/_next/static/chunks/monaco/vs/...`. Pinned by the network check in Task 3, step 6 (every `vs/` request returns 200 from our host).
4. **Running the patch twice** (a rebuild that reuses a layer, or a developer running it locally) must not double-rewrite or fail confusingly: Task 2, `test_patch_is_idempotent_failure_message`.
5. **A tampered or changed download** must stop the build: Task 3, step 3 (the stage checks SHA-256 before extracting; verified by a deliberate wrong hash once).

---

### Task 1: Self-hosted fonts

**Files:**
- Create: `frontend/static/fonts/` (six `.woff2` files, `OFL-SourceSans3.txt`, `OFL-JetBrainsMono.txt`, `README.md` with source package names and versions)
- Modify: `frontend/.streamlit/config.toml` (`[server]` adds `enableStaticServing = true`, with a one-line comment citing #65)
- Modify: `frontend/styles.py:28` (replace the `@import` with `@font-face` rules)
- Create: `tests/test_self_hosting.py`

**Interfaces:**
- Produces: `tests/test_self_hosting.py` with `FORBIDDEN_HOSTS: tuple[str, ...]`, reused by Task 2's tests.

- [ ] **Step 1: Write the failing tests** in `tests/test_self_hosting.py`:
  - `test_no_third_party_hosts_in_frontend`: walk `frontend/` (skip `__pycache__`, `*.woff2`, `OFL-*.txt`); assert no text file contains any of `FORBIDDEN_HOSTS`.
  - `test_static_serving_on`: `config.toml`'s `server.enableStaticServing is True`.
  - `test_font_faces_point_at_local_files`: for each `(family, weight)` in `[("Source Sans 3", 400), (…500), (…600), (…700), ("JetBrains Mono", 400), (…500)]`, the CSS in `styles.py` has an `@font-face` with that `font-family` and `font-weight`, a `src: url('/app/static/fonts/<file>.woff2')`, and `font-display: swap`; and `frontend/static/fonts/<file>.woff2` exists and starts with the bytes `wOF2`.
  - `test_font_licences_shipped`: both `OFL-*.txt` files exist and contain "SIL OPEN FONT LICENSE".

- [ ] **Step 2: Run them to see them fail**
  Run: `uv run pytest tests/test_self_hosting.py -v`
  Expected: 4 FAIL (Google host found; static serving missing; no `@font-face`; no files).

- [ ] **Step 3: Add the font files.** Download the two fontsource tarballs into the scratchpad, copy `files/source-sans-3-latin-{400,500,600,700}-normal.woff2` and `files/jetbrains-mono-latin-{400,500}-normal.woff2` and each package's `LICENSE` (as `OFL-SourceSans3.txt`, `OFL-JetBrainsMono.txt`) into `frontend/static/fonts/`. Write `README.md`: package, version, licence, date.

- [ ] **Step 4: Turn on static serving and write the `@font-face` rules** in `styles.py` in place of line 28. Keep the existing `font-family` lines unchanged.

- [ ] **Step 5: Run the tests to see them pass**
  Run: `uv run pytest tests/test_self_hosting.py tests/test_theme.py -v`
  Expected: all PASS.

- [ ] **Step 6: Commit**
  `git add frontend/static/fonts frontend/.streamlit/config.toml frontend/styles.py tests/test_self_hosting.py && git commit -m "Fonts: serve Source Sans 3 and JetBrains Mono from the app (#65)"`

### Task 2: The Monaco address rewrite

**Files:**
- Create: `frontend/monaco_patch.py`
- Modify: `tests/test_self_hosting.py`

**Interfaces:**
- Consumes: `FORBIDDEN_HOSTS` from Task 1.
- Produces:
  - `CDN_VS: str = "https://cdn.jsdelivr.net/npm/monaco-editor@0.36.1/min/vs"`
  - `LOCAL_VS: str = "./monaco/vs"` (relative to the component's `index.html`; Task 3's browser check confirms it)
  - `patch_bundle(build_dir: Path, local_vs: str = LOCAL_VS) -> int`: replaces `CDN_VS` in every `*.js` and `*.html` under `build_dir`; returns the number of files changed; raises `PatchError` (subclass of `RuntimeError`) if no file contained `CDN_VS`, or if any file still contains `cdn.jsdelivr.net` afterwards.
  - `package_build_dir() -> Path`: the installed `streamlit_monaco/frontend/build` folder (via `importlib.util.find_spec`).
  - `main() -> int`: patches `package_build_dir()`, prints `patched <n> file(s)`, returns 0; on `PatchError` prints the message to stderr and returns 1. `if __name__ == "__main__": raise SystemExit(main())`.

- [ ] **Step 1: Write the failing tests** (add to `tests/test_self_hosting.py`; `import monaco_patch`, since `frontend/` is on pytest's pythonpath):
  - `test_patch_rewrites_real_bundle(tmp_path)`: copy `package_build_dir()` to `tmp_path`; `patch_bundle(copy) == 1`; no file in the copy contains `cdn.jsdelivr.net`; the chunk now contains `"./monaco/vs"`.
  - `test_patch_fails_when_address_missing(tmp_path)`: a folder with one `.js` file without the address → `pytest.raises(PatchError, match="not found")`.
  - `test_patch_fails_on_leftover_cdn(tmp_path)`: one file with `CDN_VS` and another with `https://cdn.jsdelivr.net/npm/other@1/x.js` → `PatchError` matching `"still"`.
  - `test_patch_is_idempotent_failure_message(tmp_path)`: patch a copy once (returns 1), patch again → `PatchError` whose message says the bundle looks already patched (contains `LOCAL_VS`), so a rebuild failure is easy to read.
  - `test_installed_package_not_modified`: after the tests, the real `package_build_dir()` still contains `CDN_VS` (tests must work on copies only).

- [ ] **Step 2: Run them to see them fail**
  Run: `uv run pytest tests/test_self_hosting.py -k patch -v`
  Expected: FAIL with `ModuleNotFoundError: monaco_patch`.

- [ ] **Step 3: Implement `frontend/monaco_patch.py`** to the interface above. Read and write as UTF-8 text.

- [ ] **Step 4: Run the tests to see them pass**
  Run: `uv run pytest tests/test_self_hosting.py -v && uv run --frozen ruff check .`
  Expected: all PASS; ruff clean. (`test_no_third_party_hosts_in_frontend` must skip nothing new: `monaco_patch.py` names the CDN host, so build the constant from parts, for example `"cdn." + "jsdelivr.net"`, or exclude exactly that file by name with a comment. Plan's call: exclude the file by name, because the constant must be greppable.)

- [ ] **Step 5: Commit**
  `git add frontend/monaco_patch.py tests/test_self_hosting.py && git commit -m "Monaco: rewrite streamlit-monaco's CDN address to a local path (#65)"`

### Task 3: Build the image, check it in a browser, document

**Files:**
- Modify: `frontend/Dockerfile`
- Modify: `docs/production-decisions.md`, `wiki/dependency-updates.md`, the wiki page covering the frontend (find it in `wiki/index.md`), `wiki/log.md`, `docs/planning/status.md`

**Interfaces:**
- Consumes: `frontend/monaco_patch.py` (`python monaco_patch.py` exits 0 or 1) from Task 2.

- [ ] **Step 1: Add a `monaco` build stage** at the top of `frontend/Dockerfile`: `FROM python:3.12-slim AS monaco`; `ARG MONACO_VERSION=0.36.1` and `ARG MONACO_SHA256=0ffa1c42ef6939339031a1e9c72af6cc863773febe992b85a746dc24a6e07251`, with a comment that both change only together with `streamlit-monaco`; a `RUN python -c` (no curl in slim) that downloads the tarball, compares SHA-256 and exits non-zero on mismatch, then extracts only `package/min/vs` to `/monaco/vs`.

- [ ] **Step 2: In the final stage**, after `pip install`: `COPY --from=monaco /monaco/vs /usr/local/lib/python3.12/site-packages/streamlit_monaco/frontend/build/monaco/vs`; after `COPY . ./`: `RUN python monaco_patch.py`.

- [ ] **Step 3: Check that a wrong hash stops the build** (once, not committed)
  Run: `docker build --build-arg MONACO_SHA256=0000 -t fastpilot-frontend:hashcheck frontend`
  Expected: build FAILS in the `monaco` stage with a SHA-256 mismatch message. Then `docker image rm` anything left.

- [ ] **Step 4: Build the real image**
  Run: `docker build -t fastpilot-frontend:selfhost frontend`
  Expected: success; the log shows `patched 1 file(s)`. Then
  `docker run --rm --entrypoint sh fastpilot-frontend:selfhost -c 'grep -rl cdn.jsdelivr.net /usr/local/lib/python3.12/site-packages/streamlit_monaco || echo clean'`
  Expected: `clean`. (Plan's call: this, plus the patch step failing inside every image build, is the spec's "CI greps the image" check; CI's `publish-ghcr.yml` builds this Dockerfile on every pull request, so no workflow change is needed.)

- [ ] **Step 5: Run the image locally** with the local stack (see `wiki/` local-run page) or `docker run -p 8501:8501` with the backend URL set as the local compose file does.

- [ ] **Step 6: Browser check in both themes** (Chrome, system Light, then Dark): open Chat and Playground; in DevTools' Network panel, filter `-domain:localhost`: expected **no requests**. Every `vs/` request returns 200 from localhost under `/component/…/monaco/vs/`. Playground shows the Monaco editor with syntax colours and **not** the caption "Plain editor (the Monaco component is unavailable here)". Fonts: the Computed panel on body text shows `Source Sans 3` rendered, and on a source path `JetBrains Mono`. Take screenshots for the pull request. Stop the containers afterwards.

- [ ] **Step 7: Run the full check**
  Run: `uv run --frozen ruff check . && scripts/export_constraints.sh --check && uv run pytest`
  Expected: all pass, coverage gate green.

- [ ] **Step 8: Update the docs** (pre-flight: `grep -rn -i 'fonts.googleapis\|jsdelivr\|#65' docs wiki README.md frontend` and fix anything stale):
  - `docs/production-decisions.md`: a row "Fonts and Monaco from our own site (26 Nov 2026)": founder's choice "Self-host both (Recommended)" and, for Monaco's files, "Download at build, checked (Recommended)"; what changed.
  - `wiki/dependency-updates.md`: a `streamlit-monaco` or Monaco update must change `MONACO_VERSION` and `MONACO_SHA256` together; `monaco_patch.py` fails the build if the address moved.
  - The frontend wiki page and `wiki/log.md` (newest first); `docs/planning/status.md`: #65 to "in review" with the PR number.

- [ ] **Step 9: Commit**
  `git add frontend/Dockerfile docs wiki && git commit -m "Frontend image: Monaco from a checked download, no third-party hosts (#65)"`

### After the tasks

Fresh-context review of the whole branch (Opus), then open the pull request (body per the house rules, with "How it works" and "Concepts to learn"), then `@codex review`. Merging builds images but deploys nothing; deploy with the next planned deploy.
