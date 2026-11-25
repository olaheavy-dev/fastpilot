# Change / Session Log

Newest first. Append one entry per working session or notable change (see [[CLAUDE.md]]
rule 4). Keep entries short: what changed, why, and which wiki pages were touched.

---

## 2026-11-25 — Backend telemetry off (#64)

- The review of #61 found that haystack-ai sends anonymous telemetry to PostHog (`eu.posthog.com`) unless `HAYSTACK_TELEMETRY_ENABLED` is false; nothing set it. Founder, 25 Nov 2026: "Turn it off (Recommended)".
- The fresh review found more: Opik starts Sentry crash reporting to Comet on import, even without a key (founder: "Turn it off too (Recommended)"; Opik traces unaffected), and `scripts/07_reindex_production.py` imported Haystack before `app`.
- `app/__init__.py` **forces** `HAYSTACK_TELEMETRY_ENABLED=False`, `OPIK_SENTRY_ENABLE=false` and `HF_HUB_DISABLE_TELEMETRY=1` (founder: "Force off (Recommended)"), before any of those libraries load. It is in code, not the Compose file, because infra's allow-list fixes the backend's `environment` keys. `scripts/_bootstrap.py`, the reindex script and `tests/conftest.py` import `app` first; the refresh plan says `corpus/__init__.py` will too; [[coding-conventions]] states the rule; `docs/production-decisions.md` records the decisions. `tests/test_telemetry.py` checks all three in fresh processes, including that an env file setting them on can't; it fails without the change.

## 2026-11-25 — Streamlit usage statistics off (#61)

- Found in the 22d 24-hour watch: the production frontend logged "Collecting usage statistics", because Streamlit's `browser.gatherUsageStats` defaults to on, so visitors' browsers sent anonymous usage data to Streamlit. The privacy note names only Opik.
- `frontend/.streamlit/config.toml` now sets `[browser] gatherUsageStats = false` (founder, 25 Nov 2026: "Turn it off (Recommended)"). `streamlit config show` confirms it, and `test_streamlit_usage_statistics_are_off` guards it.

## 2026-11-25 — Weekly Dependabot updates

- **#47 merged:** all 138 alerts cleared on `main` (deploy after the 48-hour watch).
- **`.github/dependabot.yml`:** weekly version updates for `uv` and `github-actions` on Mondays at 06:00 London time. It has a 7-day cooldown, groups patch releases, and holds `qdrant-client` below 1.19 to match the server. The options were checked against GitHub's options reference (`cooldown` supports `uv` and `github-actions`).
- **`docker-compose` ecosystem** for `deploy/docker-compose.prod.yml` (Qdrant and Redis images), as the infra Phase 22 plan expects. Qdrant gets patch releases only, and Redis only digest refreshes of `8.4`: CI never runs these images, so a green check proves nothing; [[dependency-updates]] has the local integration check. The refresh plan now reads the Qdrant image from the Compose file (one pin), so a Dependabot update needs no second edit. Dependabot's Compose fetcher matches `docker-compose*.yml`.
- **Codex (P2, fixed):** the checklist allows digest-only Redis refreshes (tag `8.4` unchanged), instead of requiring the tag to change.
- **Codex (P2, fixed):** the Compose checklist now runs the candidate Redis image by itself on port 6380 with `REDIS_TEST_URL`, because the local stack publishes no Redis port.
- **Decisions (founder, 25 Nov 2026):** Compose image PRs are reviewed first, never merged on green alone ("No, review first (Recommended)"); Dependabot security updates turned on ("Yes, turn them on (Recommended)"; the repository setting now reads `enabled: true`).
- **Known step:** Dependabot changes only `uv.lock` (`versioning-strategy: lockfile-only`), so each `uv` PR fails CI's constraints check until `scripts/export_constraints.sh` is run on its branch with CI's uv version. Handle one PR at a time.
- **Fresh review before the PR** (1 P1, 4 P2, 4 P3, all fixed): Haystack major versions are now ignored (P1); the strategy is lockfile-only; the page says weekly PRs cover direct dependencies only; the merge rules are referenced, not restated; the refresh plan's Part 3 needs no `dependabot.yml` change. Open for the founder: whether to turn on Dependabot security updates.
- New page [[dependency-updates]]; [[index]] updated.

## 2026-11-25 — Uptime check moves to FastPilot

- **New workflow `.github/workflows/uptime.yml`** ("Uptime"): every 15 minutes it checks `https://fastpilot.olaheavy.dev` for HTTP 200 with a non-empty page. It has a 2-minute timeout and read-only permissions, and a manual run accepts another domain.
- **Why here:** founder's choice, "Move it to fastpilot (Recommended)". In the private infra repository, GitHub bills each run as at least one minute, so the check would use about 2,900 of the organisation's 3,000 shared private minutes a month. Public repositories run free. Infra's "Staging uptime" is removed in the infra 22e PR.
- **Failure emails** go to the account that first adds the workflow to `main`, then whoever changes its `cron` line or re-enables it (GitHub docs), so the founder merges this PR. GitHub also pauses scheduled workflows in a public repository after 60 days without activity.
- **Fresh review before push** (all fixed): the schedule runs off the hour (`7,22,37,52`; GitHub delays or drops runs at the start of each hour); a manual run can no longer cancel a scheduled one; the check retries twice and bypasses Cloudflare's cache; the email rule now includes "the account that first created the workflow", so the founder merges this PR.
- New page [[uptime-check]]; [[index]] updated.

## 2026-11-25 — UI fixes from the upgrade review (#44, #45, #46)

- **#46:** a switched-off sidebar toggle was a faint tint (20% at rest, 15% on hover) that nearly vanished, most of all in light mode. Its track now uses a new token, `--fp-toggle-off` (`#878079` light, `#6B7489` dark). Each clears 3:1 against the sidebar and against the knob (WCAG 1.4.11): light 3.89:1 and 3.89:1, dark 3.59:1 and 3.86:1. Disabled toggles keep Streamlit's look. The new test `test_toggle_off_track_is_visible` measures the resting state in both themes, track and knob; it fails on the old CSS and passes on the new.
- **Fresh review** (1 P1, 2 P2, 5 P3, all fixed): a first attempt used `--fp-muted`, which left the dark knob at 2.51:1, and the test measured the hover state.
- **#44:** the mobile rule now targets `stColumn` (Streamlit's current test id). At 390 px nothing changes visibly, because Streamlit already stacks the chips; the rule is a guard.
- **#45:** `use_container_width=True` → `width="stretch"` (four buttons), the replacement Streamlit 1.67 documents.

## 2026-11-25 — Dependency alerts cleared

- **Dependabot alerts turned on** (they were off): 138 open alerts (8 critical, 83 high, 44 moderate, 3 low), all in indirect packages in `uv.lock`. Each one ships in the backend image, the frontend image or both: for example GitPython only in the frontend (through Streamlit), litellm only in the backend (through Opik), and Pillow in both.
- **Founder's choice: "Do everything in one go"** (over a lock-only fix with Pillow later). The lock upgrade clears all 138, and an OSV scan of the new lock (162 packages) finds none. The main moves:
  - Pillow 12.2 → 13.0. This needs Streamlit 1.58 → 1.67 and fastembed 0.8.0 → 0.9.1, because both capped Pillow below 13.
  - voyageai 0.4.1 → 0.6.0, which also drops ffmpeg-python and future.
  - GitPython removed (Streamlit 1.67 no longer needs it).
  - certifi, anyio, aiohttp, cryptography, urllib3, pyasn1, filelock, h2, hpack and multidict.
  - litellm 1.89 → 1.111.0 (through Opik).
  - Our own `pyproject.toml` is unchanged.
- **litellm and `boto3`.** litellm 1.95–1.100.3 has a high alert (GHSA-7hp6-4w63-5g45), and from 1.98 on litellm needs `boto3`. Founder's choice: "Upgrade, approve boto3 (Recommended)". `boto3` (Apache-2.0), botocore, s3transfer and jmespath are now in the backend image. A first pick of 1.95.1 would have added a new alert; the pre-push review caught it.
- **Code:** voyageai 0.6 no longer raises without a key, so `_CacheEmbedder` checks the Voyage key itself. The cache then degrades to no-op instead of reporting itself available. Test: `test_cache_embedder_refuses_missing_voyage_key`.
- **Checks:**
  - fastembed 0.8.0 and 0.9.1 give byte-identical BM25 vectors (111 chunks, 8 queries), so no re-index is needed.
  - A live Voyage smoke test passes: embed at 2,048 dimensions, rerank, and Haystack's `VoyageTextEmbedder` (cosine 1.0 against a direct call).
  - A new visual test, `test_playground_edit_reaches_run`, proves that an edit typed in Monaco reaches `/execute`.
  - The old and new Streamlit screenshots (both themes, 390 and 1280 px, and the toggles switched off) match apart from a pixel or two of spacing.
- **Local finding:** `.venv/bin/pytest` still pointed at the pre-move `~/source/code/rag/fastpilot/.venv`, so local `uv run pytest` ran old packages. Rebuilt `.venv`. CI was not affected (fresh install).
- **Deploy after the 48-hour watch (26 Nov).** fastembed 0.9 downloads `Qdrant/bm25` from Hugging Face only, so check that the first backend boot loads it. Next: a weekly `.github/dependabot.yml` (founder: "Yes, after the alert fix (Recommended)"), one file shared with the refresh plan's Part 3 `github-actions` entry.

## 2026-11-25 — Refresh plan follow-ups (#34, #35, #36)

- **#34:** version files in R2 are now create-only. Publish claims `corpus/<tag>/` with `If-None-Match: *` and writes every file the same way. A `412` fails the run and deletes nothing, so two publishers that pick the same tag can't overwrite each other's files. `next_tag` skips leftover folders, and retention deletes unlisted folders after 7 days. R2 support was checked in Cloudflare's conditional-operations docs.
- **#35:** `evaluate` rescores the previous release when a valid question has no stored baseline score (a stale question that is valid again). `Scores.mean` raises on a missing score instead of averaging fewer questions.
- **#36:** when Qdrant reports that the live collection is missing, the updater skips the live snapshot and installs the verified version. If Qdrant is unreachable, it still skips the run.
- **Fresh review before push** (1 P1, 5 P2, 6 P3, all fixed): a missing collection counts as a mismatch in the same-tag check; `/health` stays 200 with `points: 0`; a failed install with no live copy retries the next day; `--clean-partial` for a half-finished bootstrap; `Stubber` tests prove the condition is on `PutObject` and `CompleteMultipartUpload`; the tag is chosen inside publish; R2's default multipart-abort rule is kept.
- **`pyrightconfig.json` committed** (founder, 25 Nov 2026: "Commit it (Recommended)"), with `pythonVersion` changed from 3.13 to 3.11 to match the lowest supported version; noted in [[Coding Conventions]].
- Pages: `docs/superpowers/plans/2026-11-24-corpus-refresh.md`, `docs/superpowers/specs/2026-11-23-corpus-refresh-design.md`, `docs/planning/status.md`. No wiki page changed (`wiki/corpus-refresh.md` arrives with Part 2).

## 2026-11-25 — Session hand-over

- **Merged 24 Nov:** #33 (refresh design and plan), #37 (Voyage and Gemini spend decisions), #39 (live), #40 (themes), #41 (deploy record); infra #112 (DNS record). **Open:** infra #114 (founder merge).
- **Production:** live at fastpilot.olaheavy.dev on `sha-7517b7a`. Next: the 22d watch at about 21:20 UTC on 25 and 26 Nov, then 22e, then the refresh plan follow-ups (#34, #35, #36).
- The status file holds the full list of next steps and founder to-dos.

## 2026-11-24 — Themes: follow the system, fix component colours

- **Review** (screenshots of the live site in all four system × toggle combinations): when the in-app
  toggle disagreed with the system, Streamlit's own widgets stayed in the other theme (dark code blocks
  on a light page, unreadable toggle halves, invisible captions and icons). Also: inline code was
  Streamlit's default green, light code panels matched the page, and three small texts failed
  contrast through opacity (3.18:1 to 1.93:1).
- **Founder, 24 Nov 2026:** "Follow the system only (Recommended)". The toggle is removed; one rule
  (`prefers-color-scheme`) drives Streamlit and our CSS. `config.toml` now sets code, link and border
  colours for both themes; the forced overrides in `styles.py` are deleted; text no longer fades through opacity (the running-step pulse animation stays); light `--fp-muted` darkened from `#78716C` to `#736C67` (4.73:1 on the badge surface).
- New `tests/test_theme.py` (contrast and token completeness, both themes); [[component-architecture]]
  gains a "Frontend themes" section.
- Found by screenshotting full answers: the Playground editor (streamlit-monaco) kept Monaco's light syntax
  colours on the dark page, because its "streamlit" theme always uses base `vs`. Dark mode now asks for
  `vs-dark` (`playground_view._monaco_theme`). The founder also reported the "· N sources" caption
  showing only on hover: on the live site it is drawn in the other theme's text colour when the toggle
  and system disagree; fixed by the same change.
- Founder, 24 Nov 2026: "Stay on Streamlit (Recommended)" (no React rewrite); recorded in
  `docs/production-decisions.md`.
- **Deployed** #40 as `sha-7517b7a` (founder approved; `deploy-fastpilot.sh --stage containers`). Live after:
  200, `/health` healthy with the runner, 0 proxy-key warnings, no Theme control; the Sources title and the
  "· N sources" caption use the theme's text colour in light and dark, at rest and on hover.

## 2026-11-24 — Live: fastpilot.olaheavy.dev (Phase 22c)

- **Live at 21:22 UTC** with Chat, Agent and Playground on, image `sha-a26e1e2` (model `gemini-3.8-flash`). Steps run with the founder's approval for each: containers and index restore (4,241 points; infra #111 for a restore-helper check that fails on a brief `yellow`), runner proofs (no network, read-only, four capabilities, no keys; escape attempts failed; Playground, Agent and the per-minute limit worked), the DNS record (infra #112; Terraform `1 added`), the Caddy edge block, then public checks (200, WebSocket 101, direct connections to the server time out, Chat answers with sources, the 16th question is refused, no proxy-key warnings, about 410 MB of 1,728 MB caps). Details in infra's `wiki/log.md`.
- README: the live demo link replaces the "temporarily offline" note. Stale "not live yet" lines fixed in `wiki/feature-coverage.md`, `wiki/onboarding.md`, `wiki/overview.md`, and a dated update under the decision in `docs/production-decisions.md`.
- Next: the 48-hour watch (22d), then uptime (infra #102).

## 2026-11-24 — #33 merged; Voyage cap decision

- **#33 merged** after five Codex rounds (the last clean). Plan follow-ups open: #34, #35 (before Part 2), #36 (before Part 5).
- **Voyage:** its docs describe no spending cap, only throughput limits; its dashboard has a monthly budget alert (email only), which the founder set to $7.50. Founder, 24 Nov 2026: "Accept no cap, watch the bill"; recorded in `docs/production-decisions.md`. The status file's go-live to-do is now the Gemini cap only. Corrects the earlier to-do "Voyage (usage limit)", which assumed a setting Voyage does not document.
- **Gemini:** AI Studio monthly spend cap set to $10 on `fastpilot-prod` (it stops requests; no daily quota, founder: "No, monthly is enough (Recommended)"). The refresh project's to-do now says a monthly spend cap too. Go-live is no longer blocked.
- Pages touched: `docs/planning/status.md`, `docs/production-decisions.md`, the refresh spec and plan (spend cap wording).

## 2026-11-24 — Refresh plan: Codex round 4 on #33

- **Fixed (P1):** the plan let only publish and the failure step have `GITHUB_TOKEN`, but check-changes and fetch call GitHub GraphQL, which needs a token. Build-and-evaluate now gets it too; a new test checks the backend and runner containers never receive it or any R2 key.
- **Deferred (P2, round 4 rule):** #34 (two publishers sharing a version folder) and #35 (rescore the baseline when a stale golden question returns). Both must be fixed in the plan before Part 2 (PR 2) is built. A fresh review then had the spec record the token and the accepted risk, and the runner test check for no secrets at all.
- **Round 5:** one new P2 deferred to #36 (the updater must recover when the live collection is missing, before Part 5 is built). `main` merged into the branch to clear log conflicts with #32.
- Pages touched: `docs/superpowers/specs/2026-11-23-corpus-refresh-design.md`, `docs/superpowers/plans/2026-11-24-corpus-refresh.md`, `docs/planning/status.md`.

## 2026-11-24 — Session hand-over (open items, next steps, founder to-dos)

**Refresh plan reworked:** two fresh reviews (contracts and failures; security and operations) found 23 P1 problems the first review missed (process issue agent-workflows #60). Fixed in the design and plan: the Agent evaluation runs in the published runner image with no network and no keys; secrets in a `main`-only environment and step-scoped; per-collection backend containers (the cached pipeline scored one collection twice); contaminated answers never scored; per-question baselines; a typed previous-corpus record; a conditional `index.json` write with one schema; transient vs content failures, a live snapshot before every restore and a daily point check on the server; a status check that opens an issue. Founder answers recorded in `docs/production-decisions.md`.

**End of session (24 Nov):** #32 merged (model change). #33 has both fresh plan reviews applied (security/ops and contracts/failures: 23 P1 between them) plus six founder decisions; Codex's five points fixed and resolved; waiting for Codex on the latest commit. One decision open (how the corpus status becomes public, see the status file). Process issue agent-workflows #60 (the plan review missed cross-part contracts).

**Status file added:** [`docs/planning/status.md`](../docs/planning/status.md) now holds the current state, planned work (with a diagram) and founder to-dos; entries here keep the history.

**Merged since the 22 Nov hand-over:** #24 rate limits per visitor address (issue #12), #26 images under `ghcr.io/olaheavy-dev` (public), #27 images and CI pinned to `uv.lock` (#25), #28 Phase 22a production stack; infra #97 (Phase 22 plan), #100 and the `fastpilot-staging` retirement, #110 (Phase 22b helpers).

**Current state**
- Nothing is public yet. Staging is retired. Production is ready to deploy with infra's `deploy-fastpilot.sh` (Phase 22c), from `~/source/code/infra/work/fastpilot-prod/` (env files filled and checked; never committed).
- The index snapshot (4,241 chunks, SHA-256 `762a6402…`) is on the Mac in `~/source/code/portfolio/fastpilot-index-snapshots/`.
- **Model:** `gemini-2.5-flash` is retired for new projects (rerouted 1 Dec 2026). Chosen: `gemini-3.8-flash` with `gemini-3.5-flash-lite` as fallback (RAG 0.906 / 0.935 and 0.908 / 0.935; Agent 10/10 for both). The defaults change in a separate FastPilot PR. To rerun it: set `LLM_MODEL` and `LLM_FALLBACK_MODEL` to the model under test, run FastPilot's answers on the `fastpilot-prod` key, and run the judge as `gemini-3.8-flash`. `scripts/05_run_rag_eval.py` reads `JUDGE`-free settings today, so the 23 Nov run used a small wrapper that sets the judge model on the Week-4 `_eval_common` module before the judge is imported; Part 1 of the refresh plan replaces it with the `judge_model` setting.
- **Corpus:** from 14 May 2026, only on the Mac (capstone repo, not in git). The refresh is designed and planned (#29).

**Next steps, in order**
1. **Merge the model change** (`gemini-3.8-flash`, fallback `gemini-3.5-flash-lite`; founder's choice 24 Nov after both passed the evaluations).
2. **Phase 22c, go live** (infra plan): containers stage → index restore → runner proofs → DNS record PR → site stage → checks; then 22d (48 h watch) and 22e (uptime URL, infra #102).
3. **Corpus refresh build** (#29): subagent-driven, starting next session, per the plan; Part 4 preserves May's corpus as `corpus-2026-05-14`. Storage: a private R2 bucket (not GitHub Releases); versions kept: the 3 newest + the bootstrap.
4. **MCP server** (#30): local and hosted, after the refresh.

**Founder to-dos**
- Spend caps: Gemini (`fastpilot-prod` project: budget alert and a daily request quota) and Voyage (usage limit).
- Opik: read the `fastpilot` project's trace retention and say it, to record here.
- Before the refresh build: create the private R2 bucket's two tokens (Part 0 of the plan).
- Delete the old Qdrant Cloud cluster in its dashboard, and the `QDRANT_URL` line pointing at it in FastPilot's `.env`.

**Open issues worth knowing:** #23 (compose ports; handled by the production file), #29 (refresh), infra #102 (re-enable uptime), #105 closed, #109 (Vestagraph trap), agent-workflows #56 (one worktree per session).

## 2026-11-24 — Production model: gemini-3.8-flash, with gemini-3.5-flash-lite as fallback

`gemini-2.5-flash` is no longer available to new projects (and is rerouted for everyone from 1 Dec 2026), so production needs a current model. Founder, 24 Nov 2026: "3.8 Flash, 3.5 Lite fallback (Recommended)", after both were evaluated: RAG (judge `gemini-3.8-flash`, gate 0.90) 3.8 Flash 0.906 / 0.935, 3.5 Flash Lite 0.908 / 0.935; Agent (10 tasks) both 10/10, first try 10/10 and 9/10. A *different* fallback model means one overloaded model can't take Chat down (both were briefly overloaded on 23 Nov).
- **Changed:** `app/config.py` defaults `llm_model` and `llm_fallback_model`, `.env.example`, and the model named in `README.md`, `CLAUDE.md`, [[overview]] and [[component-architecture]]. No code path changed: the pinned `google-genai` 2.9 calls the new models as before.
- **Also:** `scripts/05_run_rag_eval.py` accepts `FASTPILOT_CORPUS_ROOT` (the Week-4 instruments live in the capstone repository until the corpus refresh moves them, #29).
- The decision and the full results are recorded in `docs/production-decisions.md`. Noticed, not changed (#31): the cost estimate still uses 2.5 Flash's price per call, and the router and rewriter have no fallback model.

## 2026-11-23 — Production stack, index snapshot and measurements (infra Phase 22a)

- **Index:** rebuilt from the capstone corpus into a local Qdrant 1.18: 514 documents, **4,241 chunks** (4,232 before; the chunker now makes 9 more), all with `file_path` and `category`. Voyage cost about $0.04 (within the free allowance). Snapshot kept on the Mac with its SHA-256; restore proven on arm64 and on amd64 (the server's chip type). `scripts/07_reindex_production.py` takes `FASTPILOT_CORPUS_ROOT`.
- **Production stack:** `deploy/docker-compose.prod.yml` + per-service env examples + `deploy/redis.conf.example` + a Mac-only `deploy/docker-compose.local.yml`. Found while running it: containers only on an `internal: true` network get no published ports, so the snapshot is restored from inside the network.
- **Measured** (Mac, real traffic: 5 browser sessions, 20 Chat questions, 5 Agent tasks, 20 Playground runs): peaks backend 264 MB, frontend 60, runner 68, Qdrant 82, Redis 14, about 490 MB in total; two maximum-size Playground programs at once (about 200 MB each, the most `RLIMIT_AS` 256 MB allows) took the runner to 455 MB, under its 768 MB cap. No container ran out of memory or restarted. 20 of 20 Chat answered, 4 of 5 Agent tasks succeeded, 20 of 20 Playground runs passed; the semantic cache answered a repeat in 0.26 s on Redis 8.
- **Fixed:** the Redis integration test built its own client without `protocol=2`, so its KNN round trip found nothing (on Redis Stack 7.4 too); the runner integration tests still bypassed the Playground limit with fresh session ids, which #12 closed, so they now start the stack with `tests/fixtures/compose.no-rate-limit.yml`. All 3 Redis and all 9 runner integration tests pass.
- **Privacy note:** the Chat page adds "Questions and answers are recorded with Opik to improve FastPilot." after the unchanged AI-generated line (founder's choice of the short note). Decisions recorded in `docs/production-decisions.md`.
- **Pre-push review (2 P1, 5 P2, 8 P3; all taken, one wording choice and one to-do for the founder):** `redis.conf.example` had end-of-line comments, which Redis refuses (it would not start); the env examples had comments after empty values, which an env file reads as the value: every comment now sits on its own line. The frontend calls the backend by its container name (`fastpilot-prod-backend`), not the short name `backend`, which another app on `caddy_net` could share. The privacy note now also covers the Agent and Playground pages (founder-chosen sentences). Redis's health check logs in (password read from the config file, never on a command line); every check has `start_interval: 2s` (stack healthy in about 9 s, was 30 to 60); the frontend has a health check; backend and frontend drop all capabilities (Chat, Playground and frontend-to-backend re-checked); the runner restarts `unless-stopped` like the rest; the local override no longer publishes Qdrant ports; `FASTPILOT_CORPUS_ROOT` expands `~`. Docs: Qdrant and Redis no longer described as Cloud services in the overview, README, CLAUDE.md and DEPLOY.md; the chunk count is now 4,241.
- **Not done, on purpose:** the cause of the 9 extra chunks was not investigated (same 514 documents and settings; the evaluations ran on the 4,232-chunk index). The runner proof tests ran against images built from this checkout, not the published `sha-` images; 22c re-runs the runner proofs on the server with the deployed images. Not taken from the review: the unprivileged Qdrant image (optional; changes the storage volume's owner).

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
