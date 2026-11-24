# Corpus Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A monthly, unattended refresh that rebuilds FastPilot's corpus from FastAPI's docs, template and GitHub threads, publishes it as a GitHub Release only if every gate passes, and lets the server install it (and roll back) by itself.

**Architecture:** A `corpus/` package in FastPilot runs eight stages (check-changes → fetch → validate → build → index → evaluate → decide → publish), each writing a JSON manifest the next stage requires. One GitHub Actions workflow runs it monthly; a small infra updater on the server pulls the newest published `corpus-*` release, verifies, restores, health-checks, clears the answer cache and rolls back on failure.

**Tech Stack:** Python 3.12, Haystack 2.30 (pinned by `uv.lock`), Voyage `voyage-4-lite`, FastEmbed `Qdrant/bm25`, Qdrant 1.18, Gemini via `google-genai` 2.9, GitHub REST and GraphQL, GitHub Actions, bash + systemd on the server.

**Spec:** `docs/superpowers/specs/2026-11-23-corpus-refresh-design.md` (approved 24 Nov 2026). Read it with this plan.

**When:** after FastPilot production is live (infra Phase 22c). Five pull requests, in order: Part 1 → Part 2 → Part 3 → Part 4 (FastPilot), Part 5 (infra).

## Global Constraints

- Collection name `rag_accelerator_capstone_final`; named vectors `text-dense` (2048, cosine) and `text-sparse`; dense model `voyage-4-lite`; sparse model `Qdrant/bm25`; chunker: the existing AST code chunker + markdown-aware recursive splitter, unchanged.
- Qdrant image `qdrant/qdrant:v1.18.0@sha256:b3063c673f3973877c038eeecc392bad5011f072ee7892b56c9a8e204a3bdea9`.
- Judge model `gemini-3.8-flash`, a setting (`JUDGE_MODEL`), recorded with every score.
- Gate: RAG faithfulness ≥ 0.90 and answer coverage ≥ 0.90; Agent success with self-correction ≥ 0.80; dip rule: block only if worse on **both** of two side-by-side runs: RAG faithfulness or coverage lower by more than 0.03, or Agent success lower by 2 or more tasks.
- Golden health floor: at least 10 of 12 golden questions valid.
- Validate bounds: docs within ±15% of the previous corpus; template ≥ 40 files; issues 200 and discussions 100 (±10%); chunk count within ±25% of the previous corpus.
- Thread targets: 100 all-time + 100 recent issues; 50 all-time + 50 recent discussions; recent window 365 days; shortfall filled from all-time, never fails.
- Change threshold: ≥ 5 docs pages added, removed or changed; a new template release; ≥ 20 threads entered the recent lists; or ≥ 90 days since the last corpus.
- Categoriser: deterministic, no model calls; must reproduce May's `category_map.json` for ≥ 95% of the 514 files.
- Releases: tag `corpus-YYYY-MM-DD`; assets `rag_accelerator_capstone_final.snapshot`, `…snapshot.sha256`, `documents.jsonl`, `sources.tar.gz`, `manifests.tar.gz`, `report.json`; a pre-release is never installed.
- Only public content: docs from `https://fastapi.tiangolo.com/` (English), template `fastapi/full-stack-fastapi-template`, threads from `fastapi/fastapi`.
- No agent attribution in commits or pull requests. Each part ends with `make`-equivalent check green: `uv run --frozen ruff check .`, `scripts/export_constraints.sh --check`, `uv run --frozen pytest --cov=app --cov=runner --cov=corpus --cov-fail-under=90` (FastPilot); `./scripts/check-app-scripts.sh`, `./scripts/check-wiki.sh`, `./scripts/plan-diverge` (infra).
- CI stays hermetic: stage tests use recorded fixtures under `tests/corpus/fixtures/`; network and model calls are only in `-m live` tests and in the workflow.

## Review Focus

1. **A source that answers but is wrong** (the docs site returns its 404 or a cookie page for every URL, GitHub returns an empty page or rate-limit JSON): validate must fail with the source named, not build a tiny corpus. → Task 2.3 `test_validate_rejects_mostly_empty_docs` and `test_github_rate_limit_body_is_an_error`.
2. **Two refresh runs at once, or a rerun after a half-finished run:** the second must not mix manifests from the first. → Task 3.1 (workflow `concurrency`), Task 2.1 `test_require_ok_rejects_manifest_from_another_run`.
3. **The previous corpus has no report yet** (the first refresh after the bootstrap release, or a release with a missing asset): the dip rule must compare against the bootstrap scores or fail clearly, never compare with nothing and pass. → Task 2.6 `test_decide_without_previous_scores_fails_closed`.
4. **A release that exists but whose snapshot asset is missing or truncated:** the server must not install it and must keep the current index. → Task 5.1 updater tests `missing_asset` and `checksum_mismatch`.
5. **A thread or page title with odd characters** (non-ASCII, slashes, very long titles): `file_path` and file names must stay safe and stable between runs. → Task 2.4 `test_file_path_is_stable_and_safe`.

---

## Part 1 (PR 1): move the code and the instruments into FastPilot

### Task 1.1: The corpus package skeleton, the sources, and the build

**Files:**
- Create: `corpus/__init__.py`, `corpus/sources/__init__.py`
- Create: `corpus/sources/docs_html.py` (from capstone `week-1/scripts/00_preprocess_html.py`)
- Create: `corpus/sources/template.py` (from `week-1-bettercorpus/scripts/00_clone_fastapi_template.py` + `01_preprocess_fastapi_template.py`)
- Create: `corpus/sources/github.py` (from `_github.py`, `02_fetch_github_issues.py`, `03_fetch_github_discussions.py`, `04_preprocess_github.py`)
- Create: `corpus/build.py` (from `05_build_documents.py`)
- Create: `corpus/index.py` (from `week-3/scripts/indexing/01_create_hybrid_pipeline.py` and `chunkers/ast_code_chunker.py` → `corpus/chunkers/ast_code_chunker.py`)
- Modify: `scripts/07_reindex_production.py` (import from `corpus`; drop `FASTPILOT_CORPUS_ROOT` and the sys.path inserts)
- Modify: `pyproject.toml` (add `beautifulsoup4`, `markdownify`, `lxml` if not already present; `uv lock`; `scripts/export_constraints.sh`)
- Test: `tests/corpus/test_build.py`, `tests/corpus/test_sources_offline.py`, fixtures `tests/corpus/fixtures/may/` (10 May documents: 4 docs pages, 2 template files, 2 issues, 2 discussions, raw and processed)

**Interfaces:**
- Produces:
  - `corpus.sources.docs_html.convert_tree(raw_dir: Path, out_dir: Path) -> list[Path]`
  - `corpus.sources.template.preprocess(clone_dir: Path, out_dir: Path) -> list[Path]`
  - `corpus.sources.github.render_issue(record: dict) -> tuple[str, dict]`, `render_discussion(d: dict) -> tuple[str, dict]`
  - `corpus.build.load_documents(processed_dir: Path) -> list[haystack.Document]` (every document has `source`, `file_path` with `/`, `title`, `priority`, and for GitHub `source_id`)
  - `corpus.index.build_index(documents: list[Document], *, qdrant_url: str, api_key: str, collection: str) -> int` (chunks written)

- [ ] **Step 1: Write the failing tests:** `test_load_documents_matches_may_fixtures` (the 10 fixture documents load with the same `file_path`, `source` and content hash as May's `documents.jsonl` lines for them); `test_file_path_uses_forward_slashes` (a fixture with `source_html: tutorial\first-steps\index.html` yields `file_path` `official_docs::tutorial/first-steps/index.md`); `test_convert_tree_keeps_headings` (the `tutorial/first-steps` HTML fixture converts to Markdown with 27 headings).
- [ ] **Step 2: Run** `uv run --frozen pytest tests/corpus -v`. Expected: FAIL (`ModuleNotFoundError: corpus`).
- [ ] **Step 3: Move the code** into the files above, keeping behaviour; replace capstone path constants with function parameters; delete capstone-only CLI `main()` functions (Part 2 adds the CLI).
- [ ] **Step 4: Run** the tests. Expected: PASS. Then `uv run --frozen python scripts/07_reindex_production.py --test --collection fp_smoke` against a local Qdrant (manual, `-m live`-equivalent) writes 90 chunks as on 23 Nov.
- [ ] **Step 5: Commit** `git commit -m "Move the corpus code into FastPilot (corpus/)"`.

### Task 1.2: The categoriser, with the reproduction test

**Files:**
- Create: `corpus/categorise.py`
- Create: `tests/corpus/fixtures/category_map_may.json` (copy of capstone `week-3/data_preparation/outputs/category_map.json`) and `tests/corpus/fixtures/documents_may_meta.jsonl` (May's 514 documents' metadata only: `source`, `file_path`, `title`, labels, section path; no content)
- Test: `tests/corpus/test_categorise.py`

**Interfaces:**
- Produces: `corpus.categorise.CATEGORIES: tuple[str, ...]` (the 11 May categories + `general`), `corpus.categorise.categorise(meta: dict) -> str`

- [ ] **Step 1: Write the failing tests:** `test_reproduces_may_map` (over the 514 metadata records, `categorise` equals May's category for ≥ 95%; on failure the test prints the differing `file_path`s); `test_every_result_is_a_known_category`; `test_unknown_document_is_general`.
- [ ] **Step 2: Run** `uv run --frozen pytest tests/corpus/test_categorise.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `categorise(meta: dict) -> str`:** GitHub labels and docs section paths first (May's "metadata" rule, 383 files), then path and keyword patterns (May's "pattern" rule, 131 files), then `general`. Rules are data (a list of `(predicate, category)` in the module), not branches spread through code.
- [ ] **Step 4: Run** the tests. Expected: PASS with ≥ 95%; record the exact percentage and every differing file in the PR description for one review.
- [ ] **Step 5: Commit** `git commit -m "Rebuild the categoriser as code; reproduces May's map"`.

### Task 1.3: The evaluation instruments and the judge setting

**Files:**
- Create: `evaluations/instruments/__init__.py`, `eval_common.py`, `decomposed_judge.py`, `semantic_metrics.py` (from capstone `week-4/scripts/_eval_common.py`, `run_decomposed_judge.py`, `run_semantic_metrics.py`; behaviour unchanged except the judge model)
- Create: `evaluations/golden_dataset.json` (from capstone `week-4/evaluations/golden_dataset.json`)
- Modify: `scripts/05_run_rag_eval.py` (import from `evaluations.instruments`; drop `FASTPILOT_CORPUS_ROOT`); `app/config.py` (`judge_model: str = "gemini-3.8-flash"`)
- Test: `tests/test_instruments.py`

**Interfaces:**
- Produces: `evaluations.instruments.decomposed_judge.judge_answer(version, question, answer, reference, contexts, *, call, judge_model: str) -> dict` (unchanged signature plus a required `judge_model`); `evaluations.instruments.semantic_metrics.greedy_match_fraction(...)` (unchanged)

- [ ] **Step 1: Write the failing tests:** `test_judge_model_comes_from_settings` (with a fake `call`, `judge_answer` passes `gemini-3.8-flash` through and records it in its result); `test_golden_dataset_has_12_questions_with_references`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Move the instruments;** the only behaviour change is `judge_model` read from `get_settings().judge_model` and recorded in every result.
- [ ] **Step 4: Run** the tests, then the full check. Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "Move the Week-4 evaluation instruments into FastPilot; judge model is a setting"`. Open PR 1 (wiki: `wiki/component-architecture.md` gains `corpus/`; `wiki/log.md` entry).

---

## Part 2 (PR 2): the staged pipeline and the local command

### Task 2.1: Manifests and the stage runner

**Files:**
- Create: `corpus/manifest.py`, `corpus/config.py`, `corpus/refresh.py`
- Test: `tests/corpus/test_manifest.py`, `tests/corpus/test_refresh_cli.py`

**Interfaces:**
- Produces:
  - `corpus.config.RefreshConfig` (frozen dataclass; every Global-Constraints number is a field with that default; `work_dir: Path`, `run_id: str`)
  - `corpus.manifest.Manifest` (dataclass: `stage: str`, `run_id: str`, `status: Literal["ok", "failed", "no-change"]`, `counts: dict[str, int]`, `details: dict`, `started: str`, `finished: str`)
  - `corpus.manifest.write(m: Manifest, work_dir: Path) -> Path`; `corpus.manifest.require_ok(stage: str, work_dir: Path, run_id: str) -> Manifest` (raises `StageNotReady`)
  - `corpus.refresh.STAGES: tuple[str, ...] = ("check-changes", "fetch", "validate", "build", "index", "evaluate", "decide", "publish")`; `corpus.refresh.main(argv: list[str] | None = None) -> int` (`--stage`, `--force`, `--work-dir`, `--run-id`)

- [ ] **Step 1: Write the failing tests:** `test_require_ok_rejects_failed_stage`; `test_require_ok_rejects_manifest_from_another_run` (Review Focus 2); `test_cli_runs_stages_in_order_and_stops_on_failure` (stub stages); `test_cli_no_change_ends_green_without_later_stages`.
- [ ] **Step 2: Run** `uv run --frozen pytest tests/corpus/test_manifest.py tests/corpus/test_refresh_cli.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.** `main` runs each stage function (registered by name) in `STAGES` order, each first calling `require_ok` on the previous stage; exit code 0 for `ok` and `no-change`, 1 for any `failed`.
- [ ] **Step 4: Run.** Expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "corpus: manifests and the stage runner"`.

### Task 2.2: check-changes

**Files:** Create `corpus/stages/check_changes.py`. Test: `tests/corpus/test_check_changes.py`.

**Interfaces:**
- Consumes: `RefreshConfig`, `Manifest`.
- Produces: `corpus.stages.check_changes.run(cfg: RefreshConfig, previous: dict | None, probe: ChangeProbe) -> Manifest`; `ChangeProbe` protocol with `docs_page_hashes() -> dict[str, str]`, `template_latest() -> str`, `recent_threads_since(date: str) -> int` (a live implementation and a fixture one).

- [ ] **Step 1: Write the failing tests:** `test_no_change_below_every_threshold` (4 pages changed, same template, 19 threads, 89 days → `no-change`); one test per trigger: 5 pages, new template release, 20 threads, 90 days → `ok`; `test_force_always_builds`; `test_no_previous_corpus_builds`.
- [ ] **Step 2–4:** Run (FAIL), implement, run (PASS).
- [ ] **Step 5: Commit** `git commit -m "corpus: check-changes stage"`.

### Task 2.3: fetch and validate

**Files:** Create `corpus/stages/fetch.py`, `corpus/stages/validate.py`, `corpus/sources/docs_mirror.py`. Modify `corpus/sources/github.py` (selection). Create `corpus/selection.py`. Test: `tests/corpus/test_selection.py`, `tests/corpus/test_validate.py`, `tests/corpus/test_docs_mirror.py`.

**Interfaces:**
- Produces:
  - `corpus.sources.docs_mirror.mirror(base_url: str, dest: Path, *, session) -> list[Path]` (English pages only; skips `/[a-z]{2}/` language paths, `.1.html` duplicates and `404.html`, as May's manual steps did)
  - `corpus.selection.score_issue(i: dict) -> float` (positive reactions `+1`, `heart`, `hooray`, `rocket` + 5 per `answered`/`confirmed` label + 0.5 × comments); `score_discussion(d: dict) -> float` (upvotes + accepted answer's upvotes + 0.5 × comments)
  - `corpus.selection.select(candidates: list[dict], *, score, all_time: int, recent: int, recent_days: int, now: datetime) -> list[dict]` (each selected item carries `reason: "all-time" | "recent" | "fill"`)
  - `corpus.stages.validate.run(cfg, fetched_dir: Path, previous: dict | None) -> Manifest`

- [ ] **Step 1: Write the failing tests:**
  - `test_select_fills_shortfall_from_all_time` (only 30 recent candidates → 100 all-time + 30 recent + 70 fill; never raises);
  - `test_issue_needs_closed_label_and_maintainer_reply`;
  - `test_long_argument_thread_ranks_below_well_received_answer` (90 comments, 2 reactions vs 10 comments, 40 reactions);
  - `test_validate_rejects_mostly_empty_docs` (Review Focus 1: 156 pages that are all the same 404 text → failed, `source: docs`);
  - `test_github_rate_limit_body_is_an_error` (Review Focus 1: a `{"message": "API rate limit exceeded"}` body raises, not an empty list);
  - `test_validate_bounds` (docs −16% fails, template 39 files fails, issues 179 fails);
  - `test_must_exist_pages` (`tutorial/first-steps`, `tutorial/security/oauth2-jwt`, `advanced/websockets` missing → failed);
  - `test_navigation_ratio` (a page that is mostly menu text fails);
  - `test_only_fastapi_repo_threads`;
  - `test_duplicates_and_non_english_pages_fail` (the same page twice, or a page under `/es/`, → failed).
- [ ] **Step 2–4:** Run (FAIL), implement, run (PASS). The mirror uses `requests` with a polite delay and a fixed user agent naming FastPilot (no personal details).
- [ ] **Step 5: Commit** `git commit -m "corpus: fetch with scored selection; validate"`.

### Task 2.4: build and index

**Files:** Create `corpus/stages/build.py`, `corpus/stages/index.py`. Test: `tests/corpus/test_build_stage.py`.

**Interfaces:**
- Consumes: `corpus.build.load_documents`, `corpus.categorise.categorise`, `corpus.index.build_index`.
- Produces: `build.run(cfg, previous) -> Manifest` (writes `documents.jsonl`; counts per source and per category); `index.run(cfg, previous, *, qdrant_url, api_key) -> Manifest` (writes the snapshot and `.sha256`; `counts["chunks"]`).

- [ ] **Step 1: Write the failing tests:** `test_every_document_gets_a_category`; `test_category_shift_beyond_margin_fails_without_explanation`; `test_file_path_is_stable_and_safe` (Review Focus 5: titles with non-ASCII, slashes, 300 characters → the same `file_path` on two runs, no `/` inside a segment, ≤ 200 characters); `test_chunk_count_guard` (±25% from previous fails; a fake indexer returns counts).
- [ ] **Step 2–4:** Run (FAIL), implement, run (PASS).
- [ ] **Step 5: Commit** `git commit -m "corpus: build and index stages"`.

### Task 2.5: Golden-question health

**Files:** Create `corpus/stages/golden_health.py`. Test: `tests/corpus/test_golden_health.py`.

**Interfaces:**
- Produces: `golden_health.run(cfg, golden: dict, old_docs: dict[str, str], new_docs: dict[str, str], *, still_true: Callable[[str, list[str]], bool]) -> Manifest` (`details["valid"]: list[str]`, `details["stale"]: list[dict]` with `question_id` and the reason).

- [ ] **Step 1: Write the failing tests:** `test_unchanged_sources_stay_valid` (no judge call made); `test_changed_source_still_true_stays_valid`; `test_changed_source_not_true_is_stale`; `test_floor_10_of_12` (3 stale → failed; 2 stale → ok).
- [ ] **Step 2–4:** Run (FAIL), implement (the source documents of each reference context are matched by content hash), run (PASS).
- [ ] **Step 5: Commit** `git commit -m "corpus: golden-question health"`.

### Task 2.6: evaluate, decide, publish

**Files:** Create `corpus/stages/evaluate.py`, `corpus/stages/decide.py`, `corpus/stages/publish.py`, `corpus/probes.py`. Test: `tests/corpus/test_decide.py`, `tests/corpus/test_publish.py`.

**Interfaces:**
- Consumes: `scripts/05_run_rag_eval.py` and `scripts/06_run_agent_eval.py` logic refactored into `evaluations/run_rag.py: run(golden, *, valid_ids, model, judge_model) -> dict` and `evaluations/run_agent.py: run(tasks, *, model) -> dict` (the scripts become thin wrappers).
- Produces:
  - `decide.decide(new: Scores, current: Scores | None, rerun: Callable[[], tuple[Scores, Scores]]) -> Decision` (`Scores`: `faithfulness`, `coverage`, `agent_success`, `agent_n`, `model`, `judge_model`; `Decision`: `status`, `reasons: list[str]`)
  - `publish.run(cfg, *, gh: GitHubReleases) -> Manifest` (`GitHubReleases` wraps `gh release create`, upload and issue create; a fake in tests)
  - `probes.make_probes(changed_pages: list[dict], n: int = 5) -> list[dict]`; `probes.score(probes, retrieve) -> dict` (report only)

- [ ] **Step 1: Write the failing tests:**
  - `test_floor_blocks` (faithfulness 0.89 → failed);
  - `test_dip_reruns_once_and_blocks_only_if_worse_twice` (first run −0.04, rerun −0.01 → pass; both −0.04 → failed);
  - `test_agent_one_task_dip_never_blocks`, `test_agent_two_task_dip_twice_blocks`;
  - `test_judge_or_model_change_rescores_current_first`;
  - `test_decide_without_previous_scores_fails_closed` (Review Focus 3: no `report.json` in the current release → failed with "no baseline", unless `--bootstrap-baseline` is given);
  - `test_publish_uploads_six_assets_and_opens_notice` (names exactly as in Global Constraints; the notice body contains the scores, the stale list, the probe results, probes suggested as golden candidates, per-source counts, cost and duration, and the rollback command `gh release edit corpus-<tag> --prerelease`);
  - `test_failed_decision_publishes_nothing`.
- [ ] **Step 2–4:** Run (FAIL), implement, run (PASS).
- [ ] **Step 5: Run the whole pipeline locally once** (manual): `uv run --frozen python -m corpus.refresh --force --work-dir /tmp/fp-refresh` with a local Qdrant and the `fastpilot-prod` key; it must reach `decide` and print the report (publish is skipped without `--publish`).
- [ ] **Step 6: Commit** `git commit -m "corpus: evaluate, decide, publish"`. Open PR 2 (wiki: new `wiki/corpus-refresh.md`, index and log).

---

## Part 3 (PR 3, founder merge): the workflow

### Task 3.1: `corpus-refresh.yml`

**Files:** Create `.github/workflows/corpus-refresh.yml`. Test: `tests/test_workflows.py`.

- [ ] **Step 1: Write the failing test** `test_corpus_refresh_workflow_shape` (parses the YAML): triggers are `workflow_dispatch` with a boolean `force` input and **no** `schedule` key yet (the founder adds the `cron` line from their own account, as a separate commit); `permissions` exactly `contents: write`, `issues: write`; `concurrency.group == "corpus-refresh"` with `cancel-in-progress: false`; one job, `timeout-minutes: 120`; a `services.qdrant` with the pinned image and an API key from a generated value; secrets used are only `GOOGLE_API_KEY` and `VOYAGE_API_KEY`; actions pinned by full commit SHA.
- [ ] **Step 2: Run** `uv run --frozen pytest tests/test_workflows.py -v`. Expected: FAIL.
- [ ] **Step 3: Write the workflow:** checkout, `pip install uv==0.13.7`, `uv sync --locked --all-extras --python 3.12`, then `uv run --frozen python -m corpus.refresh --publish ${{ inputs.force && '--force' || '' }}`; upload the work folder as a workflow artifact on failure (for debugging; it holds only public content).
- [ ] **Step 4: Run** the test. Expected: PASS. Run the workflow once by hand on the branch with `force: false` and check it ends `no-change` or reaches `decide`.
- [ ] **Step 5: Commit** and open PR 3. PR body lists the founder steps: add the two secrets (`GOOGLE_API_KEY` from `fastpilot-prod`, `VOYAGE_API_KEY`), merge, then add `schedule: - cron: "0 4 2 * *"` (04:00 UTC on the 2nd of each month) from the founder's account.

---

## Part 4 (PR 4): the first release (preserve May's corpus)

### Task 4.1: `--bootstrap` publish of the running corpus

**Files:** Modify `corpus/stages/publish.py` (a `bootstrap(cfg, *, snapshot: Path, documents: Path, sources_dir: Path, scores: dict, gh) -> Manifest`). Test: `tests/corpus/test_publish.py::test_bootstrap_release`.

- [ ] **Step 1: Write the failing test** `test_bootstrap_release`: tag `corpus-2026-05-14`; the six assets; `report.json` holds the production scores measured with the current judge and model (from the go-live evaluation), `chunks: 4241`, `documents: 514`, and `bootstrap: true`; it is published and **not** a pre-release.
- [ ] **Step 2–4:** Run (FAIL), implement, run (PASS).
- [ ] **Step 5: Publish it for real** (manual, founder present): `uv run --frozen python -m corpus.refresh --bootstrap --snapshot ~/source/code/portfolio/fastpilot-index-snapshots/rag_accelerator_capstone_final-3539986934266048-2026-11-23-16-14-28.snapshot --documents <capstone documents.jsonl> --sources <capstone processed dirs>`; check the six assets and the SHA-256 (`762a6402…`) on the release page.
- [ ] **Step 6: Commit** and open PR 4.

---

## Part 5 (PR 5, infra): the server updater

### Task 5.1: updater, installer and tests

**Files (infra):**
- Create: `templates/fastpilot-index-updater/fastpilot-index-updater.sh`, `fastpilot-index-updater.service`, `fastpilot-index-updater.timer`
- Create: `scripts/deploy-fastpilot-index-updater.sh` (dry run by default; `SOLOFORGE_CONFIRM_FASTPILOT_INDEX_UPDATER=yes-deploy-fastpilot-index-updater`)
- Modify: `scripts/check-app-scripts.sh` (tests), `wiki/fastpilot-production.md` (the updater and rollback), `wiki/log.md`, `wiki/plan/phase-22-fastpilot-production.md` (status)

**Interfaces:**
- Consumes: the release contract in Global Constraints; `restore-fastpilot-index.sh` remote logic (factor it into a function the updater sources, or copy it with a comment pointing to the original; keep one behaviour).
- Produces: `/home/apps/fastpilot-prod/INDEX_RELEASE` (installed tag), `/home/apps/fastpilot-prod/index-previous.snapshot` (kept until the next success), journal lines tagged `fastpilot-index-updater`.

- [ ] **Step 1: Write the failing tests** in `check-app-scripts.sh` (stub `curl` with recorded GitHub API answers, stub `docker` as today):
  - `newest_non_prerelease_wins` (releases: `corpus-2027-02-02` pre-release, `corpus-2026-12-02` published → installs `2026-12-02`);
  - `same_tag_does_nothing`;
  - `missing_asset` and `checksum_mismatch` (Review Focus 4: nothing restored, `INDEX_RELEASE` unchanged);
  - `point_count_mismatch_rolls_back` (restores `index-previous.snapshot`);
  - `cache_cleared_after_install_and_after_rollback` (a `redis-cli` call with `REDISCLI_AUTH` from `redis.conf` and the cache key pattern; never the password on a command line);
  - `timer_is_daily`.
- [ ] **Step 2: Run** `./scripts/check-app-scripts.sh`. Expected: FAIL.
- [ ] **Step 3: Implement** the updater (bash, `set -euo pipefail`, `curl -fsSL` to `https://api.github.com/repos/olaheavy-dev/fastpilot/releases`, `jq` for selection), the units (daily, `Persistent=true`, a random delay up to 1 h) and the installer (dry run plans the files; apply writes them and enables the timer).
- [ ] **Step 4: Run** all infra checks. Expected: PASS.
- [ ] **Step 5: Commit** and open PR 5 (founder merge: infrastructure). After merge, the founder approves the apply; then run the updater once by hand and check it reports `same_tag_does_nothing` against the bootstrap release.
