# Change / Session Log

Newest first. Append one entry per working session or notable change (see [[CLAUDE.md]]
rule 4). Keep entries short: what changed, why, and which wiki pages were touched.

---

## 2026-11-23 — Images and CI pinned to uv.lock (issue #25)

While measuring memory for infra Phase 22a, every Chat question in a freshly built backend image failed with Gemini `400 INVALID_ARGUMENT ... Use api version v1beta`. The images install `app/requirements.txt` and `frontend/requirements.txt`, which only set minimum versions, so a build picked up untested major versions (haystack-ai 3.5.0 vs 2.30.2 tested, google-genai-haystack 7.2.2 vs 4.4.1, qdrant-haystack 13.2.0 vs 10.3.0, voyage-embedders-haystack 3.0.0 vs 1.10.0, Streamlit 1.67.0 vs 1.58.0). CI did the same, so the tests never saw what the images ran.
- **Added:** `scripts/export_constraints.sh` writes `app/constraints.txt` and `frontend/constraints.txt` from `uv.lock` (`--check` mode for CI). All three Dockerfiles install with `-c constraints.txt`; each image keeps its own package list.
- **CI:** installs uv 0.13.7 and runs `uv sync --frozen --all-extras`, then `uv run ruff`, the constraints check and `uv run pytest`: the same versions as local work and the images. The `redis<8.2` stopgap is gone (the lock pins redis 8.0.0 and fakeredis 2.36.2).
- **Updating a dependency now:** the five steps in [[coding-conventions]] (pyproject, the image's requirements.txt, `uv lock`, the export script, commit). A new test checks every image requirement is pinned; CI fails on a stale lock (`uv sync --locked`) and never re-locks (`uv run --frozen`). CI no longer caches pip (it installs only uv now).

## 2026-11-23 — Container images move to olaheavy-dev

`publish-ghcr.yml` had failed on `main` since the repository moved to `olaheavy-dev` ("denied: permission_denied: The requested installation does not exist" when pushing to `ghcr.io/sunkanmi-olawuwo/...`), so the #24 merge (`7ce6936`) published no images. Images now go to `ghcr.io/olaheavy-dev/fastpilot-{backend,frontend,runner}`, to be public (founder's choice, recorded in `docs/production-decisions.md`): GitHub creates them private, so the founder sets each to public once after the first publish (`DEPLOY.md`). `DEPLOY.md` updated (staging wording removed: `fastpilot-staging` was retired on 23 Nov, see the infra log). Issue #16 keeps the README badge part.


## 2026-11-23 — Rate limits per visitor address (issue #12)

The Playground limit counted per `session_id`, which the browser chooses, so a client could skip it.
The browser never talks to the backend (Streamlit's server does), so the backend could not just read
the client IP either.
- **Added:** `app/augmentations/client_identity.py` (rate-limit key = forwarded address only when
  `FRONTEND_PROXY_KEY` matches, else the connection's address; IPv6 grouped by /64),
  `frontend/visitor.py` (reads `CF-Connecting-IP`, or `VISITOR_IP_HEADER`), and an `api_client` hook
  that sends `X-FastPilot-Client-IP` + `X-FastPilot-Proxy-Key` on every backend call.
- **Changed:** `rate_limit.py` holds several windows per feature and falls back to memory on a Redis
  error (it used to let everything through). New limits: Chat 15/day (new), Agent 2/min + 5/day (new;
  it had none), Playground 3/min + 30/day. Over a limit: friendly message; Chat/Agent streams end with
  `done{rate_limited: true}`.
- **Decisions** (founder's choices, all the recommended option) recorded in
  `docs/production-decisions.md` (D11 update).
- **Pages updated:** [[component-architecture]], [[endpoint-summary]], [[feature-coverage]],
  [[onboarding]]; also `DEPLOY.md`, `README.md`, `.env.example`, `docs/augmentation-decisions.md`.
- **Contradiction noted:** pages said Agent/Playground wait on issue #12; they now wait only on the VPS
  move. The original "3 runs/min/session" text stays in the decision essays as history.

- **CI fix:** `redis` 8.2.0 (released 23 Nov) breaks `fakeredis` 2.40.0, failing every fakeredis
  test; CI now installs `redis<8.2` until fakeredis catches up. The concurrent soak script switches
  the quotas off for its run (it measures the pipeline, and all its simulated users share one address).

**Next steps (replaces step 1 of the 22 Nov hand-over):** the infra phase must set the same
`FRONTEND_PROXY_KEY` on backend and frontend, keep the backend private, and expose the frontend only
through Cloudflare (no open port), as listed in `DEPLOY.md`. Steps 2–4 of the 22 Nov hand-over stand.

## 2026-11-22 — Session hand-over (open items, next steps, founder to-dos)

**Merged today:** #17 sandbox hardening (allowlist, privilege drop, `AGENT_ENABLED`), #19 runner
sidecar (visitor code runs in a no-network, no-keys container). Decisions: `docs/production-decisions.md`;
build rulings: the runner design doc.

**Current state**
- Nothing is public. Railway is gone; FastPilot staging on the VPS is **stopped** (`docker compose start`
  in `/home/apps/fastpilot` brings it back, but it still points at the lapsed Qdrant/Redis Cloud).
- Qdrant Cloud and Redis Cloud free databases have lapsed. Gemini, Voyage and Opik keys work (not rotated,
  founder's choice).
- The infra uptime check (`staging-uptime.yml`) was already disabled.

**Next steps, in order**
1. Fix #12: key the Playground/Agent rate limit on the client IP from a trusted proxy header. Required before
   any public code execution.
2. After infra PR #85 (Vestagraph Phase 21d-1) merges: a new infra phase moves FastPilot to
   `fastpilot.olaheavy.dev` in Cloudflare edge mode: self-hosted Qdrant + Redis Stack (treated as rebuildable),
   the runner service, reindex the corpus, retire `fastpilot-staging`, re-point the uptime check. The infra
   FastPilot template must set `EXECUTOR_MODE=runner` and `ALLOW_LOCAL_EXECUTOR=false`.
3. Showcase: personal-website#161 (case-study page with GSAP, can start now), then #20 (demo + explainer
   video with Remotion, after the VPS move).
4. Smaller follow-ups: #13 routers, #14 course leftovers, #15 `make check`, #16 old repo owner in badges/GHCR,
   #18 stale test counts, #21 compose `../.env` path.

**Founder to-dos**
- Review and merge personal-website#162 (one register line) once Codex has reviewed it.
- Decide when to start #12 and the infra phase; GSAP and Remotion PRs are founder-merge (new packages).

## 2026-11-22 — Runner sidecar built

The sandbox scan is a filter, not a boundary, so generated code now runs in a separate container.
- **Added:** `runner/` (FastAPI on a Unix socket; two uid slots 61001/61002; kills leftovers and
  cleans `/tmp` and `/dev/shm` after every run; a failed clean-up holds the slot and restarts the
  runner; restarts after 200 runs or 6 h), `runner/Dockerfile`, `app/augmentations/runner_client.py`
  (fails closed), settings `EXECUTOR_MODE` / `RUNNER_SOCKET` / `ALLOW_LOCAL_EXECUTOR`, a startup gate
  that turns Agent and Playground off when code would run in the backend, `executor` and
  `components.code_runner` in `/health`, a hardened `runner` service in `docker-compose.yml`, a GHCR
  image `fastpilot-runner`, and `httpx` in `app/requirements.txt`.
- **Changed:** `code_executor.py` takes `sandbox_uid`/`sandbox_gid`, cleans up as the run uid and hands
  the folder over with chown/chmod (root in the runner has no `DAC_OVERRIDE`). Its docstring now names
  the runner as the boundary.
- **Tests:** `tests/test_runner.py` and `tests/test_runner_client.py` (hermetic);
  `tests/test_runner_integration.py` (`-m integration`, needs Docker). CI coverage gate now covers
  `app/` and `runner/`.
- **Honest limits:** escaped code can still use the runner's CPU and memory, within limits. Agent and
  Playground should not go public until the VPS move (after infra PR #85) and issue #12 are done. The
  demo is not live.
- **Design doc fixed:** the runner's `/health` returns `slots_free`, not `uid` (noted in the doc).
- **Contradiction noted:** older text said the runner was "planned" and "deferred"; updated in
  [[component-architecture]], [[feature-coverage]], [[onboarding]], [[overview]], [[endpoint-summary]],
  [[testing-strategy]], `README.md`, `DEPLOY.md` (Railway marked historical),
  `docs/production-decisions.md` (D6 update) and `docs/augmentation-decisions.md`.
- **Final review fixes:** the runner's slot wait now ends after `RUNNER_QUEUE_WAIT_S` (8 s) with
  `[runner] busy`, so a job the backend gave up on never runs later; `RunnerClient` caps calls in flight
  at `RUNNER_MAX_IN_FLIGHT` (3) and answers `[sandbox] code runner busy` at once over that; client
  timeout is wall + 15 s (was + 10); each slot gets `max_procs=48` (under `pids_limit: 128`); the
  integration test polls until the run folder belongs to a slot uid; doc fixes (three services, softer
  Railway wording, README tech line, "process memory", 256 MB is per process). Touched
  [[component-architecture]], the design spec and plan, `DEPLOY.md`, `README.md`,
  `docs/production-decisions.md`.

---

- **Codex review fix (PR #19):** compose no longer sets `AGENT_ENABLED` / `PLAYGROUND_ENABLED` in `environment:` (it overrode a kill switch set in the shared env_file). New `tests/test_compose_config.py` guards this and the runner's no-env-file / no-network settings.

## 2026-11-22 — Sandbox allowlist + privilege drop; relaunch decisions

A project review found the Railway demo offline (404), the free Qdrant Cloud cluster refusing
connections and the Redis Cloud database gone (DNS no longer resolves). It also found shell escapes
in the sandbox scan: `posix.system`, `os.spawn*`, `os.posix_spawnp`, `__builtins__.eval`, an aliased
`eval`, `typing.sys` and `asyncio.subprocess` all passed the old denylist and ran.
- **Changed:** `app/augmentations/code_executor.py` now uses an import **allowlist** plus a denylist of
  reflection routes, dangerous attribute names and code inside strings; the child drops to `nobody`
  when the server is root. Verified in a Linux root container: the captured agent programs still
  pass, and with the scan disabled the child gets `PermissionError` reading the server's environ.
- **Tests:** a regression test per escape in `tests/test_executor.py`; tests that relied on `sys`,
  `urllib` and `pathlib` (now blocked on purpose) were rewritten.
- **Second review (fresh context) sent it back:** confirmed escapes via the event loop's
  `subprocess_shell`, run-time strings evaluated as annotations, `FileResponse`, `logging.config` and
  raw sockets, plus a pinned server thread after a timeout and false refusals (`re.compile`,
  `super().__init__`). Fixed: those routes, a bounded second wait, `RLIMIT_NPROC`, privilege drop via
  `Popen(user=, group=)` (thread-safe), the false refusals, and a new **`AGENT_ENABLED`** kill switch.
  The unfixable one is pinned by a strict `xfail` test. Docs now say the scan is a filter, not a boundary.
- **Staging stopped:** `fastpilot-staging.olaheavy.dev` ran the old sandbox as root with live keys;
  both containers were stopped on the VPS (founder's choice). The infra uptime check will fail until
  production replaces it.
- **Decisions** (VPS, self-hosted Qdrant + Redis treated as rebuildable, runner sidecar, replace staging
  with production after infra PR #85, keep keys, two PRs) are recorded in `docs/production-decisions.md`.
- **Pages updated:** [[component-architecture]] (diagram + honest-boundary note), [[feature-coverage]],
  [[onboarding]], [[endpoint-summary]], [[testing-strategy]].
- **Removed:** `video-transcript-orignal.md` (misspelt duplicate of `video-transcript.md`).

## 2026-07-01 — Watchtower auto-update proof marker

Added non-runtime proof marker files to the backend and frontend Docker build contexts so a merge to
`main` changes both GHCR image digests. This is used to prove the parallel deployment path: Railway
production still deploys from `main`, GHCR publishes `:main`, and SoloForge staging updates through
Watchtower.

## 2026-06-28 — Demo polish: source titles/URLs, exec_result `ok`, reliable agent task

End-to-end demo-path verification surfaced three rough edges; all fixed and re-verified live.
- **Human-friendly sources.** `app/formatting.py` gains `source_title` + `source_url`, deriving
  `Advanced › Security › OAuth2 Scopes` and `https://fastapi.tiangolo.com/advanced/security/oauth2-scopes/`
  from the raw `official_docs::…/index.md` / `github_issue::N` labels (acronym-aware: OAuth2/API/JWT).
  `_format_contexts` ([app/main.py]) now emits `title` + `url` alongside `file_path`; the Chat and
  Agent sources panels ([frontend/app.py], [frontend/agent_view.py]) render the title as a link.
  All generated URLs verified `200`.
- **`exec_result.ok`.** The agent SSE `exec_result` event now includes `ok` (mirrors
  `ExecuteResult.ok`) so the UI doesn't re-derive success from `exit_code`
  ([app/augmentations/agent_orchestrator.py]).
- **Rewrite query shown above sources.** The "↻ searched as: <standalone>" caption moved from the
  top of the answer to **just above the sources list** ([frontend/app.py]), so the user sees the
  rewritten query right next to what it retrieved against. The standalone text is now captured from
  the `rewrite` SSE event and persisted to message metadata (`standalone_query`), so it survives a
  history re-render even when the `done` event omits it. (The "✎ rewritten" badge stays at the top.)
- **Reliable demo task.** Empirically tested candidate Agent tasks against the real backend; the
  *"POST /items … returns the created item with HTTP 201, self-test asserts 201"* task fails the
  first attempt **6/7** runs (genuine AssertionError) and recovers **7/7** — so the fail→fix→exit-0
  beat actually shows on camera. Swapped it into `video-transcript.md` + `DEPLOY.md` (the old 422
  task succeeded first-try ~half the time; the password-confirm/EmailStr alternatives failed to
  recover and would show an honest failure). See [[endpoint-summary]] for the updated schemas.

## 2026-06-27 — Semantic cache fix: pin RESP2 so KNN lookups parse (was 0% hit rate)

End-to-end check against the real services found the semantic cache **never returned a hit** — it
connected, reported healthy, and *wrote* entries (`num_docs` climbed), but every `/query` came back
`cache_hit: false`. Root cause: Redis Cloud is now **Redis 8.4 (RESP3 by default)**, and **redis-py
8.0**'s `FT.SEARCH` result parser misreads the RESP3 response map when `decode_responses=False`
(its keys arrive as `bytes`), silently reporting **0 results** for every KNN query. The cache uses
`decode_responses=False` to read raw embedding bytes, so its lookup was permanently empty —
a silent 0% hit rate that `ping`/`is_healthy()`/`/health` all reported green (same green-degradation
class the DIM-mismatch guard already defends against).
- `app/redis_client.py`: `make_redis_client` now pins `protocol=2` (RESP2). Verified: the *only*
  variable — same index/data/query — `decode_responses=False` gives KNN `total 0` on RESP3 vs
  `total 1` on RESP2.
- Re-verified live after the fix: identical query → HIT `distance 0.0` in **722ms** (vs 7.7s miss),
  a **reworded** query → HIT `distance 0.056` (< 0.16 threshold, proves *semantic* match), unrelated
  query → correct MISS. `/metrics` hit-rate moved 0% → 50% across the 4-query probe.
- See [[component-architecture]] → *Resilience* and [[overview]] (Memory + cache row).

## 2026-06-21 — Sandbox suppresses Starlette's httpx-deprecation warning

Starlette 1.3+ emits a `StarletteDeprecationWarning` at `TestClient` import (it prefers an
`httpx2` package). Cosmetic, but it landed in every sandbox run's stderr — which the Agent and
Playground surface to learners.
- `app/augmentations/code_executor.py`: added a `-W` message filter to the sandbox argv. It must
  be `-W`, not `PYTHONWARNINGS`: the executor runs `python -I` (isolated mode), which ignores
  `PYTHON*` env vars, and a category filter can't import the starlette class at interpreter
  startup — so the filter matches on the message text.
- Regression test in `tests/test_executor.py` asserts the sandbox stderr stays clean.

## 2026-06-21 — Agent asserts on Pydantic v2 error `type`, not v1 `msg`

Prod symptom: the Agent's generated self-tests asserted on Pydantic **v1** error wording
(`"ensure this value is greater than 0"`), which never matches the **v2** sandbox
(`"Input should be greater than 0"`). The program failed its own `assert`, the ≤2-attempt
fix loop ([[component-architecture]]) couldn't recover, and the run surfaced as a failure.
- `app/prompts/templates.py`: `AGENT_CODE_PROMPT` now tells the agent the sandbox is Pydantic v2
  and to assert on the stable `err["type"]` (`greater_than`, `string_too_short`, `value_error`)
  rather than the reworded `err["msg"]`. `AGENT_FIX_PROMPT` gains a v1→v2 hint so the fix loop
  can repair a msg-substring assert if one slips through.

## 2026-06-21 — Frontend accepts `BACKEND_URL` as an `API_BASE_URL` alias

While deploying to Railway, the frontend couldn't reach the backend: the env var was set as
`BACKEND_URL`, but `frontend/api_client.py` only read `API_BASE_URL` (falling back to
`http://localhost:8000` — the frontend container itself).
- `frontend/api_client.py` now resolves the base URL as
  `API_BASE_URL` → `BACKEND_URL` → `http://localhost:8000`, using `or` so empty values fall
  through (matches the secrets-default-to-empty / degrade-don't-crash convention).
- `DEPLOY.md` notes the alias under the frontend env vars.

## 2026-06-20 — Wiki embeds design conclusions (links out, no file moves)

Decided to keep `docs/` (deep design essays, code-coupled) and `wiki/` (the living map) as two
cross-linked systems rather than merging them. To make the wiki self-sufficient for the *takeaways*:
- [[component-architecture]] now carries the **evidence conclusions** inline — T1b won 30/36 pairwise
  (+21 from rerank, T3 skipped ~34 s), chunking removed 27.9% truncation, and the agent's
  ≤2-fix loop lifts success ~50% → 100% — each with a **link out to the full essay**. Added an
  add/skip-decision pointer to the production-decisions essay.
- [[overview]] links the scoping essay (problem + corpus); [[feature-coverage]] links the chunking,
  retrieval, and evaluation essays. All link-outs are **absolute GitHub URLs** so they resolve in the
  published GitHub Wiki (relative `../docs/` paths don't).
- Also de-course-ified residual wiki references for consistency (`Week-6` → augmentation layer,
  `class CRAG` → CRAG, the `AC1.5` convention example → `D#` decision IDs).

## 2026-06-20 — De-course-ified the design docs

Removed coursework framing from the `docs/` design essays so they read as professional engineering
docs, **without touching any technical substance**:
- **Titles:** dropped `(Week 5)`, `(Week 6) — BONUS`, `(BONUS — Optional Depth)`.
- **Bodies:** neutralized course-week labels (Week 1–6), dropped acceptance-criteria IDs (`AC#`) while
  keeping their thresholds in plain words, removed rubric/grading/self-assessment/submission framing,
  and rephrased "the class …" → "the reference …". `iteration-log.md` section headings reframed from
  weeks to phases (Foundations / Production backend / Agent augmentation / Live evaluation / Security
  & load hardening).
- **Preserved verbatim:** all metrics, dates, file paths, model names, and the internal decision IDs
  (`D#`, `T1a/T1b/T2/T3`). Verified: zero real numeric tokens lost (only `AC#`/self-score bookkeeping
  removed), all 29 dates intact, no broken heading anchors. See [[feature-coverage]] for results.

## 2026-06-20 — Removed submission.md (course artifact)

- Deleted `submission.md` (the capstone write-up: student name + rubric self-assessment) — it read
  as coursework, not product. Its substantive content already lives elsewhere: results + honest
  findings in `README.md`, the full limitations list in [[feature-coverage]].
- Repointed the three README links (`Full write-up` → **Docs & architecture** wiki; self-assessment
  line → `wiki/feature-coverage.md`; Documentation-table row → the Developer wiki) and dropped the
  `submission.md` bullet from [[index]]. No dangling references remain.

## 2026-06-20 — Sidebar expanded by default + better screenshots

- **Frontend:** `initial_sidebar_state` flipped `collapsed → expanded` (`frontend/app.py`) so the
  Chat/Agent/Playground mode switcher + controls are visible on load.
- **Screenshots regenerated** via the `visual` suite and promoted to `docs/screenshots/` (used by
  `README.md`): the agent shot now shows the **populated, syntax-highlighted attempt-2 code** and the
  Playground shows the **fully-painted Monaco editor** (previously blank / "Loading…"), all with the
  expanded sidebar.
- **`tests/test_visual.py`:** waits added so captures fire after the agent's static re-render
  (Send-to-Playground button + code visible) and after Monaco paints (`_wait_monaco`); `_switch_mode`
  tolerates the now-expanded sidebar; mobile overflow tests `_collapse_sidebar` first (the expanded
  sidebar overlays the chips at 390px). 12 visual + 208 hermetic tests green.

## 2026-06-20 — GitHub Wiki published + CI auto-publish

- Published `wiki/` to the **GitHub Wiki** via `scripts/publish_wiki.py` (in-repo `wiki/`
  stays canonical; the GitHub Wiki is a generated mirror with a `_Sidebar` and `index → Home`).
- Added a **`publish-wiki` CI job** (`.github/workflows/ci.yml`): on push to `main`, after
  tests pass, it re-runs the publish script so the wiki never drifts from `wiki/`. Uses
  `contents: write` + `GITHUB_TOKEN`; idempotent (no-ops when unchanged). This very entry is
  the first edit auto-published by that job.

## 2026-06-20 — Wiki established + repo packaged as standalone product

**Context.** FastPilot was extracted from the capstone monorepo into its own standalone repo
(`final-submission/` → repo root, full Phase 0–5 history preserved via `git filter-repo`),
then published at `github.com/sunkanmi-olawuwo/fastpilot` (public, CI green).

**This session — created the developer wiki** under `wiki/`:
- Wrote [[overview]], [[component-architecture]], [[endpoint-summary]], [[coding-conventions]],
  [[testing-strategy]], [[feature-coverage]], and the [[onboarding]] article — all derived
  from the current source (`app/`, `tests/`, `pyproject.toml`), with inline Mermaid diagrams
  for the architecture, RAG pipeline, agent loop, sandbox layers, and request sequence.
- Captured `raw/openapi.json` — the live OpenAPI 3.1 contract (10 routes) — as the immutable
  API reference. See [[raw/README]].
- Created `wiki/plans/` (empty by design — see [[plans/README]]) and `wiki/assets/`.
- Added the wiki-maintenance rules to the repo's `CLAUDE.md`.

**Decisions.**
- Wiki lives in the **fastpilot** repo (not the monorepo).
- Historical course plans and any "plan-diverge" tooling were intentionally **left out** of
  scope; `wiki/plans/` starts fresh for future work.
- `docs/` (design essays) and `wiki/` (living dev map) are kept distinct — wiki links to docs
  rather than duplicating them.

**State.** Code/docs/evals/tests/CI green. Outstanding (owner-only): Railway deploy + demo
video — tracked in [[feature-coverage]].
