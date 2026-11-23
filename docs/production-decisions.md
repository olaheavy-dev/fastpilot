# Production Decisions

> One entry per production service: **added or skipped**, with rationale and evidence.

Every production service below is an explicit **add** or **skip** with a reason and evidence — not
a template default. Components live in `app/services/` and `app/augmentations/`.

### SSE streaming — **added**
**Why:** answers run 1.7k–10k chars; streaming token-by-token makes the wait legible instead of a
30-second blank. **How:** `text/event-stream` with the standard SSE event protocol
(`session / rewrite / cache_status / classification / context / token / done / error`), consumed in
Streamlit via `requests.post(..., stream=True)` + `iter_lines()`. **Hardening:** a mid-stream
disconnect cancels the producer task; once tokens have emitted we surface the error rather than retry
(no garbled double-answer). **Evidence:** SSE event-order + post-emit-failure tests in
`tests/test_pipeline.py` / `test_api.py`.

### Semantic cache — **added, threshold calibrated**
**Why:** repeated/paraphrased questions are common for a learning tool; a cache answers them instantly
at ~$0. **How:** Redis HNSW/KNN over voyage-4-lite query embeddings (`FT.CREATE`/`FT.SEARCH`); a miss
embeds the query **once** and reuses that vector for retrieval + cache-set (verified byte-identical,
cosine 1.000000) — saving the 2 redundant re-embeds per miss (retrieval + cache-set). **Calibration:** the paraphrase/near-miss
distance bands *overlap* (a true paraphrase at 0.31 sits beyond the closest near-miss at 0.23), so the
strict "100% paraphrase / 0 near-miss" target is unachievable with this embedder. We chose **safety**
(zero wrong-answer serving) and set the threshold to **0.16** (4/6 paraphrases hit, 0/6 near-misses,
0.068 margin) — 4× the hit-rate of the original 0.06 with no wrong-answer risk. **Evidence:**
`evaluations/eval_results/cache_threshold.json`; a live paraphrase hit observed during the soak.

### Conversation memory + conditional rewrite — **added**
**Why:** follow-ups ("can it be an integer?") are meaningless without history. **How:** Redis-backed
windowed memory per `session_id` (TTL 24h); a follow-up turn is rewritten to a standalone query before
retrieval, a first turn is not (no phantom rewrite). **Honest detail:** refusals don't pollute memory —
a refused first turn stays a true first turn. **Evidence:** the dogfood log shows live rewrites
resolving referents ("can it be an integer?" → "Can a query parameter with a default value be an
integer?").

### Query router — **added**
**Why:** a FACTUAL question and a CODE_GENERATION request deserve different prompts/temperature. **How:**
a lightweight classifier tags each query (FACTUAL / HOW_TO / TROUBLESHOOTING / CODE_GENERATION) and
selects the matching versioned prompt; defaults safely to FACTUAL on a parse failure. **Evidence:**
router parse-edge tests; classification spans visible in Opik.

### Redis graceful degradation — **design choice**
**Why:** a downed Redis must not 5xx a learning session. **How:** missing creds or a *runtime* Redis
failure demote the cache and conversation memory to in-memory/no-op symmetrically — `/health` reports
`degraded` honestly rather than crashing. **Evidence:** degradation tests assert no 5xx;
runtime-demote tests in `tests/test_services.py`.

### Security guards — **added**
**Why:** a public RAG endpoint invites prompt injection. **How:** the `InputGuard` (prompt-injection
regex, tightened to avoid false refusals on real FastAPI questions like "I always forget…") on both
`/query` and `/query/stream`, polite structured refusals (200, not 500); `OutputValidator` PII pass on
agent output. **Evidence:** 10-injection / 5-benign suite; a soak injection refused as `200 + refused`,
never a 5xx.

### Sandboxed code executor (D6) — **added** (the augmentation)
**Why:** the gap was that `CODE_GENERATION` answers were *unverified* — users still had to run the code.
**How:** AST denylist (denied imports/calls/builtins **plus** dunder-attribute and reflection-builtin
blocking, so `().__class__…__subclasses__()`, `getattr`, and `open` are rejected at scan) → `python -I`
subprocess isolation (scrubbed env, temp-dir cwd, own process group) → `RLIMIT` CPU/AS/FSIZE →
wall-timeout `killpg` → socket-guard prelude. Generated code self-verifies in-process with `TestClient`
(D7) so "running" never binds a port. **Honest limit:** a pure in-process Python sandbox is
defense-in-depth, **not a hard boundary** — the common reflection escapes are closed and the blast
radius is capped (no secrets in env, no network), but only OS isolation guarantees it; the documented
production-grade path is a Docker backend (`--network none --memory 256m`), deferred only because
Railway has no docker-in-docker. **Evidence:** safety suite (loop killed, network
blocked, denylist + reflection escapes + `open` all rejected pre-exec, temp-dir isolation); full
write-up in [`augmentation-decisions.md`](augmentation-decisions.md).
**Update 2026-11-22:** a review found shell escapes the denylist missed (`posix.system`, `os.spawn*`,
`os.posix_spawnp`, `__builtins__.eval`, an aliased `eval`, `typing.sys`, `asyncio.subprocess`). The scan
is now an import **allowlist** plus a reflection / dangerous-attribute / code-in-string denylist, and the
child drops to `nobody` when the server is root. A second, fresh-context review then confirmed more
escapes, including one no static scan can close (a string built at run time and used as a type
annotation, which FastAPI evaluates as code), and that the drop protects the keys only when the
server is root. **Conclusion: the scan is a filter, not a boundary.** The boundary will be a runner
sidecar container; until then `AGENT_ENABLED` and `PLAYGROUND_ENABLED` stay off on public hosts.
Regression tests for each finding are in `tests/test_executor.py`.
**Update 2026-11-22 (runner sidecar built):** the boundary now exists. Code runs in a separate `runner`
container (no network, no keys, read-only filesystem, `cap_drop: ALL` plus four needed capabilities,
`no-new-privileges`, 768 MB memory, 128 processes). The backend reaches it over a Unix socket and fails
closed when it is down. Each of two slots has its own uid (61001, 61002), so one visitor cannot read
another's files or process memory; after every run leftover processes are killed and the slot's files are
deleted, and a failed clean-up holds the slot back and restarts the runner. A startup gate turns Agent
and Playground off if code would run inside the backend and that is not explicitly allowed
(`ALLOW_LOCAL_EXECUTOR`). Proof tests (`tests/test_runner_integration.py`, `-m integration`, need
Docker) check no network, no keys, a read-only filesystem and the slot isolation. **What it does not
guarantee:** escaped code can still use the runner's CPU and memory, within its limits, and the scan in
front of it is still only a filter. The built design is in
`docs/superpowers/specs/2026-11-22-runner-sidecar-design.md`. Agent and Playground should not go public
until the VPS move (after infra PR #85) is done. Issue #12 (the rate limit) is fixed; see the D11 update
below. The demo is not live.

### Playground (D11) — **added, with a threat model**
**Why:** turns the agent's sandbox into a user-facing "now *you* tweak it" surface — the strongest demo
beat. **Threat model for user-submitted code:** identical AST-scan + sandbox path as the agent, plus
caps (10 KB, 15 s wall, 3 runs/min/session), no secrets in the subprocess env, and a `PLAYGROUND_ENABLED`
kill switch that 404s the endpoint without a redeploy. The only added dependency (`streamlit-monaco`),
contained to one view with a `st.text_area` fallback. **Evidence:** oversize / rate-limit / denylist /
disabled-404 guard tests.

**Update 2026-11-23 (issue #12, rate limits per visitor address).** The limit used to count per
`session_id`, a value the browser sends, so a client could send a new id each time and skip it. The
browser never talks to the backend (Streamlit's server does), so the frontend now forwards the visitor's
address and the backend counts per address. Founder's choices, 23 Nov 2026, each the recommended option:
- **Trust:** "Shared secret (Recommended)". The backend believes the forwarded address only with a
  matching `FRONTEND_PROXY_KEY`; otherwise it uses the connection's own address. Safe even if the backend
  port opens by mistake.
- **Agent limit:** "Own limit, 2 a minute (Recommended)". The Agent had no limit; an Agent run is far
  heavier than a Playground run.
- **Redis down:** "Fall back to memory (Recommended)". The limiter used to allow everything on a Redis
  error; now it counts in-process, so an outage cannot switch the limit off.
- **IPv6:** "Group by /64 block (Recommended)". One connection usually gets a whole /64.
- **Daily caps:** asked "how many questions per day is an ip address allow - 10 or 15 is fine?", then
  chose "15 a day (Recommended)" for Chat and "Yes: Agent 5, Playground 30 (Recommended)".

What is stored: each counter's Redis key holds a keyed hash (HMAC-SHA256 with `FRONTEND_PROXY_KEY`) of
the address, not the address, and expires a few seconds after its window ends (a day counter by just
after midnight UTC). Blocked calls are taken back off, so they use up no quota. The check runs in a
worker thread with Redis timeouts (3 s connect, 5 s read), so a slow Redis cannot stall other requests.
Known limits: visitors behind a shared address (for example, many mobile users behind one carrier IPv4
address) share one budget; a host given a large IPv6 block (/48) gets many /64 budgets.

Limits now: Chat 15 a day; Agent 2 a minute and 5 a day; Playground 3 a minute and 30 a day (`/execute`
and `/fix` together). Days reset at midnight UTC. Any limit set to 0 is off. Code:
`app/augmentations/rate_limit.py`, `app/augmentations/client_identity.py`, `frontend/visitor.py`. The
"3 runs/min/session" above is the original design, kept for history.

### T3 two-stage LLM routing — **skipped** (honest cost/benefit)
**Why skipped:** T3 was competitive on retrieval but ran **~34 s/query** (vs T1b's ~11 s) from the extra
LLM routing hop — unacceptable for an interactive learning tool, and the evaluation showed T1b already
wins *answer quality* (T3's edge is exact-file retrieval, which the LLM judges can't even see). Production
runs **T1b**. See [`retrieval-strategy.md`](retrieval-strategy.md).

### Retrieval-confidence guard — **added** (the right-sized slice of CRAG)
**Why:** the one real retrieval failure mode left is *off-corpus* queries — ask something the FastAPI corpus
doesn't cover and retrieval returns weak chunks, risking a plausible-but-ungrounded answer. **How:** the
reranker already scores every chunk 0–1, so the guard is **deterministic and latency-free** — no extra LLM
call. If the best reranked chunk falls below `retrieval_confidence_min` (0.3; in-domain top scores run
~0.5–0.85), the response carries `low_confidence=true` and the UI shows a caution ("may be outside the FastAPI
docs — double-check"). **Evidence:** `_confidence_meta` unit-tested (low scores flag, in-domain don't); the
frontend caution is hermetically tested.

### CRAG corrective retrieval — **considered, declined**
**What it is:** grade retrieved docs with an evaluator and, on poor retrieval, take corrective action
(re-retrieval, query refinement, or **web search**). **Why declined here:** (1) retrieval isn't the weak link —
production `answer_coverage` is **0.941** and faithfulness **0.992**, so there's little bad retrieval to
rescue; (2) the corpus is **closed and curated** (514 FastAPI docs) — CRAG's signature web-search fallback
would **break the value prop** (grounded in the official docs, every claim `[n]`-cited) by injecting
un-citable web content; (3) it adds a **per-query LLM grader call** to a latency-sensitive path we already
trimmed (see T3). The genuinely useful slice — *knowing when retrieval is weak* — is captured by the
deterministic **retrieval-confidence guard** above, at zero latency and with no grounding risk. Full CRAG
(or a query-shape T1b/T3 router for the exact-file gap) is noted as future work in
[`retrieval-strategy.md`](retrieval-strategy.md).

## Observability — Opik (D8)

**Added.** A thin shim (`app/observability.py`) makes Opik fully optional: every helper
decides at *call* time whether to trace, so with the key unset or Opik down, every other
requirement still passes. It's wired four ways, each with dashboard evidence below (project
`fastpilot`, workspace `sunkanmi-daniel`; screenshots in [`opik/`](opik/)).

**1. Distributed tracing** — `@track` spans on the hot path (`rewrite_if_needed`,
`cache-lookup`, `classify`, `retrieve`, `generate`) nest under a parent `rag-query` /
`rag-query-stream` trace; `set_thread_id` groups a conversation's traces into one thread.
The Phase-4 evals alone produced **48 traces / 210 spans at a 0% error rate** (p50 7.5s).

![Project overview — 48 traces, 0 errors, latency + per-span volume](opik/01-dashboard-overview.png)
![Traces — rag-query + agent traces, 0% error rate](opik/02-traces-list.png)
![Spans — generate / retrieve / classify / cache-lookup / rewrite_if_needed with structured I/O](opik/03-spans-list.png)
![Span waterfall — one rag-query trace, nested spans](opik/04-span-waterfall.png)
![Threads — set_thread_id conversation grouping (the 6-message path-param follow-up chain)](opik/05-threads.png)

**2. Prompt versioning + hot-swap** — `register_prompts()` (now called explicitly in the app
lifespan) pushes each generation template to Opik's prompt library at startup (auto-versions on
change); `fetch_prompt()` pulls the latest at runtime (60s cache), so an edit in the Opik UI is
picked up on the next request with no redeploy. The flag is read through the module at call time,
so startup config is seen (a value-import would freeze it False).

Verified server-side via the Opik prompt API — all 4 templates registered and versioned
(commit hashes in [`opik/prompt-versions.json`](opik/prompt-versions.json)):
`rag-factual` `dd7b0a4e` · `rag-how-to` `747b4afd` · `rag-troubleshooting` `dd5a023e` ·
`rag-code-generation` `0fe056e6`. **Note:** Comet Cloud's *Prompt library UI* did not render
these SDK-registered prompts (a pre-existing prompt didn't show either — a platform rendering
quirk, not a registration failure); the API list endpoint returns all of them, and the runtime
`fetch_prompt → get_prompt` hot-swap path is confirmed live. The JSON above is the authoritative
evidence; `06-prompt-library.png` is optional if the UI later renders. The **Prompts tab on a
live trace** is the stronger proof that versioning is wired end-to-end — it shows the exact
prompt version attached to a `rag-query-stream` generation (verified: the trace context survives
the `asyncio.to_thread` hop where `build_prompt` runs, so the link lands on the right trace).

![Linked prompt on a live rag-query-stream trace (Prompts tab)](opik/06b-linked-prompt-trace.png)
![Prompt library — registered prompts + version history](opik/06-prompt-library.png)

**3. Feedback linking** — thumbs up/down → `/feedback` → `log_feedback_score` attaches a
`user_feedback` score to the answer's trace (joined by `trace_id`), closing the loop from a
user reaction back to the exact generation.

![Feedback score linked to its trace](opik/07-feedback-score.png)

**4. Online evaluation rule** — `fastpilot-hallucination`, an LLM-as-judge rule (the
`_trigger_eval` pattern), samples a fraction of live `rag-query` traces and scores each for
hallucination, so production traffic is continuously evaluated without a batch job. It's doing
real work: across sampled traces most score `Hallucination=0.0` (faithful to the retrieved
context) but at least one scored **`0.85`** — the rule flagged a likely hallucination on live
traffic, which is exactly the signal a production guardrail should surface.

![Online evaluation rule scoring live traces (one flagged at 0.85)](opik/08-online-eval-rule.png)

## Deployment

> **Update 2026-11-22:** the Railway deployment below is offline, and the free Qdrant Cloud and Redis
> Cloud databases lapsed. The project is moving to a self-hosted VPS (see *Decisions, 2026-11-22* at
> the end of this file). This section describes the original Railway setup. The stack now has a third
> service, the `runner` (see the D6 update above); it is not part of the Railway setup below.

**Railway, two services in one project**:
- **`frontend`** (Streamlit) — the **only** service with a public domain.
- **`backend`** (FastAPI) — **private**, reached by the frontend at `backend.railway.internal`; no
  public domain, so only the UI is internet-facing.
- Each service has its own `Dockerfile` and binds Railway's injected **`$PORT`** (`uvicorn … --port
  $PORT` / `streamlit … --server.port $PORT`) — hardcoding 8000/8501 is the #1 first-deploy failure,
  avoided here. Backend healthcheck on `/health`, restart-on-failure.

**State is managed, not deployed** (D4): conversation memory + semantic cache live in **Redis Cloud**,
the corpus in **Qdrant Cloud** — both reached over TLS, both the same instances dev uses. Nothing
stateful runs in a Railway container.

**Secrets** are set in the Railway dashboard, never in the repo: backend gets `QDRANT_URL/API_KEY`,
`GOOGLE_API_KEY`, `VOYAGE_API_KEY`, `REDIS_*` (TLS), `OPIK_*`; frontend gets
`API_BASE_URL=http://backend.railway.internal:<PORT>`. `.env` and `.streamlit/secrets.toml` are git- and
gitingest-ignored.

**Local dev & CI parity:** `docker compose up backend frontend` mirrors the service topology (now three services: backend, frontend, runner)
against the same managed Redis/Qdrant; a profiled `redis-stack` container (port 6380) is a
RediSearch stand-in for `pytest -m integration` only — it is never used by the running app.

**Accepted tradeoff — cache-lookup RTT:** using managed Redis Cloud (vs an in-cluster Redis) adds a
network round-trip to every cache lookup. We accept it: the cache embeds the query *once* and reuses
that vector (no extra Voyage cost), the managed instance removes an ops burden, and the economics
still favour a hit (a cached answer is ~$0 + one RTT vs a full Voyage-rerank-Gemini generation).

> **Deployed verification:** deployed `/health` reports healthy and chat + agent mode stream end-to-end through
> Railway's proxy — verified on the public URL before recording the demo (SSE must arrive
> token-by-token, not as one buffered blob).

## Decisions, 2026-11-22 (relaunch after the free services lapsed)

Recorded from the founder's answers in the project review session.

| Decision | Founder's choice | Context |
|---|---|---|
| Where the live demo runs | "I have a VPS" | Railway returned 404; host on the founder's own VPS instead. |
| Sandbox before relaunch | "Fix it, then relaunch (Recommended)" | Shell escapes found in the denylist scan; fixed in the sandbox-allowlist PR. |
| Qdrant and Redis | "Self-host on the VPS (Recommended)" | The free cloud tiers went inactive (Qdrant refusing connections, Redis DNS gone). Self-hosted containers are never paused for being idle; needs backups. |
| VPS size | "4 GB+ RAM, Docker installed" | Room for backend, frontend, Qdrant and Redis Stack together. |
| Agent and Playground | "Keep both, add container isolation (Recommended)" | They are the core of the showcase. |
| How to isolate code runs | "Runner sidecar (Recommended)" | Per-run containers need the Docker socket, which the infra rules do not allow for apps. A separate runner container with no keys, an internal-only network and a read-only filesystem. |
| Staging vs production | "Replace staging with production (Recommended)" | One FastPilot stack at fastpilot.olaheavy.dev; fastpilot-staging.olaheavy.dev is retired. Saves RAM on the 4 GB server. |
| Qdrant/Redis backups | "Treat as rebuildable (Recommended)" | No backups: Qdrant is rebuilt with the reindex script, and Redis holds only cache and chat memory. |
| Timing of the VPS move | "After PR #85, behind Cloudflare (Recommended)" | Wait for infra Phase 21d-1, then move FastPilot as its own infra phase in Cloudflare edge mode. |
| Staging during the fix | "Stop the whole stack" | The staging stack ran the old sandbox as root with live keys; both containers were stopped on 2026-11-22 (`docker compose start` brings them back). |
| Rotate API keys | "Don't rotate" | No evidence of a leak; the founder chose to keep the current Gemini, Voyage and Opik keys. |
| Container images (23 Nov 2026) | "Public (Recommended)" | Publishing to `ghcr.io/sunkanmi-olawuwo/...` failed after the repository moved to `olaheavy-dev`. Images now publish to `ghcr.io/olaheavy-dev/fastpilot-{backend,frontend,runner}`, public: the repository is public and the images hold no secrets, so the server pulls them without a token. GitHub creates new packages private, so an organisation owner sets each of the three to public once, after the first publish (`DEPLOY.md`). The alternative (private, with a read-only token on the server) was turned down. |
| How to split the code work | "Two PRs: hardening now, runner next (Recommended)" | This PR hardens the executor and adds `AGENT_ENABLED`; the runner sidecar follows. |
| Runner memory budget | "256 MB per run, 2 at once, 768 MB cap (Recommended)" | Leaves about 2 GB for Qdrant, Redis, the backend and other apps on the 4 GB VPS. During the build the review showed the limit is per process, so each run is also capped at 48 processes. |
| Privacy between visitors | "Kill leftovers after every run (Recommended)" | Each slot has its own user; after every run its processes are killed and its files deleted. |
| Runner link | "Unix socket, runner has no network (Recommended)" | The runner has no network at all; the backend reaches it through a socket file. |
| Design approval | "Approve + visual page (Recommended)" | Runner design approved; a private visual page shows the before/after. |
| Build mode | "Subagent-driven (Recommended)" | A fresh builder and a fresh reviewer per task, then a whole-branch review. |
| When Codex reviews the runner work | "After the final review (Recommended)" | Codex reviews the PR once, after the whole-branch review's fixes. |
| Showcase plan | "Both, in stages"; video tool "Remotion"; website "Add GSAP scroll story" | Case-study page on the personal website first, demo and explainer video after the VPS move. Tracked in #20 and personal-website#161. Remotion and GSAP are new packages, so those PRs are founder-merge. |
