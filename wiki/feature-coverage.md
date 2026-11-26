# Feature Coverage

> Inventory of what's built vs deferred, plus the measured results and honest limitations.
> The "why" behind each design choice lives in `docs/` and [[component-architecture]].

## Implemented ✅

### Product modes
- **Chat** — cited, grounded answers (`[n]` sources); streaming + non-streaming.
- **Agent** — grounded code-runner: plan → retrieve → write → run → self-correct (≤2 fixes)
  → explain, streamed as a live timeline.
- **Playground** — edit + run the agent's code in the same sandbox; LLM "fix from traceback".

### Retrieval + generation
- **Hybrid chunking** — AST (tree-sitter) for code, markdown-aware recursive for prose;
  BGE→Voyage-4-lite migration removed 27.9% silent truncation.
  ([full essay](https://github.com/olaheavy-dev/fastpilot/blob/main/docs/chunking-strategy.md))
- **T1b pipeline** — dense + BM25 → RRF → Voyage rerank-2.5 → top 10; won 30/36 pairwise, rerank +21.
  ([full essay](https://github.com/olaheavy-dev/fastpilot/blob/main/docs/retrieval-strategy.md))
- **Retrieval-confidence guard** — latency-free `low_confidence` flag (CRAG slice).
- **Query router** — classification + type-specific prompts.

### Production system
- **SSE token streaming** (chat + agent), with mid-stream disconnect cancellation.
- **Semantic cache** — Redis HNSW, safety-tuned threshold.
- **Conversation memory** — sliding window + conditional follow-up rewrite.
- **Security** — prompt-injection InputGuard + PII OutputValidator.
- **Sandboxed executor** — subprocess with an AST import allowlist (a filter, not a boundary),
  scrubbed env, privilege drop when root, CPU/memory/process limits and a bounded timeout.
- **Runner sidecar** — the boundary: a separate container (no network, no keys, read-only FS,
  dropped capabilities, two uid slots) that runs the code; the backend fails closed if it is down.
  ([[component-architecture]])
- **Kill switches** — `AGENT_ENABLED` and `PLAYGROUND_ENABLED` (backend 404 + frontend hides the mode).
- **Rate limiting** — per visitor address (issue #12): Chat 15/day, Agent 2/min + 5/day, Playground
  3/min + 30/day. ([[component-architecture]])
- **Graceful degradation** — every service degrades; `/health` reports truth.
- **Observability** — Opik tracing, prompt versioning/registry, feedback scores, online-eval rule.

### Engineering
- **210 tests**, hermetic by default; **90% coverage gate** in CI; ruff-clean. ([[testing-strategy]])
- **Dockerized** three-service topology (backend, frontend, runner); Railway deploy config kept as history (`DEPLOY.md`).
- **Eval harness + evidence** in `evaluations/` and `scripts/05`–`12`.
- **Dogfood logging** + harvested log (`evaluations/dogfood_log.md`).

## Measured results
All measured **live through the production pipeline** (`POST /query`); evidence in
`evaluations/eval_results/`. The instrument — a triangulated eval (LLM faithfulness +
deterministic coverage + a human probe) — is described in the
[evaluation-strategy essay](https://github.com/olaheavy-dev/fastpilot/blob/main/docs/evaluation-strategy.md):

| Metric | Result | Evidence |
|---|---|---|
| Production faithfulness (LLM judge) | **0.992** | `production_parity.json` |
| Production answer-coverage (deterministic) | **0.941** | `production_parity.json` |
| Agent success: first-attempt → with self-correction | **5/10 → 10/10** (+50 pts) | `agent_eval.json` |
| Agent grounding (cited chunks mention the API) | **93%** (25/27) | `agent_quality.json` |
| Fix-with-AI on broken snippets | **3/3** | `agent_quality.json` |
| Soak (20-call mixed session) | **0 × 5xx** | `soak_session.json` |
| Concurrent load (8 sessions + 2 agents, 24 live gens) | **0 × 5xx**, metrics reconcile | `concurrent_soak.json` |

## Deferred / planned 🔜
Tracked here (and as plans in [[plans/README]] when picked up):

| Item | Why deferred |
|---|---|
| **Live deploy + public URL** | Railway deploy went offline (Nov 2026). Live again since 24 Nov 2026 at [fastpilot.olaheavy.dev](https://fastpilot.olaheavy.dev), on the founder's VPS with self-hosted Qdrant + Redis (infra Phase 22c). |
| **Demo video / hero GIF** | Recorded against the deployed URL; placeholders marked in `README.md`. |
| **Agent and Playground public** | Needs the VPS move (after infra PR #85), with `FRONTEND_PROXY_KEY` set and the frontend reachable only through Cloudflare (see `DEPLOY.md`). Issue #12 (rate limit) is fixed. The runner sidecar itself is built; it is not yet running on a public host. |
| **Playground keystroke autocomplete** | Streamlit rerun + iframe latency; UX nicety. |
| **Broader multi-user dogfooding** | Current evidence is single-user (the builder); logging path is proven. |

## Honest limitations (named, not hidden)
- **The sandbox scan is not a security boundary** — confirmed escapes reach a shell, files and the
  network; one (run-time strings evaluated as annotations) cannot be closed by any static scan.
  The boundary is the runner sidecar. Escaped code can still use the runner's CPU and memory, within
  its limits. Agent and Playground should not go public until the VPS move is done.
  ([[component-architecture]])
- **Cache is conservative by design** — threshold 0.16 favours zero wrong-answer serving over
  hit-rate; the paraphrase/near-miss embedding bands overlap.
- **Agent self-verification only tests what it thought to test** — a human probe found a
  negative-pagination gap the agent's own tests missed (`human_verification.json`).
- **Single-user dogfooding** — genuine usage evidence, but one user.

> When any of these changes, update this page **and** note the change in [[log]] (per
> [[CLAUDE.md]] rule 8).
