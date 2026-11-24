# Corpus refresh: design

Status: approved by the founder (24 Nov 2026); updated after the plan review the same day. Issue: #29. Repositories: `olaheavy-dev/fastpilot` (the refresh) and `olaheavy-dev/infra` (the server updater).

## Intent

FastPilot answers from a corpus built on **14 May 2026**: 156 official FastAPI doc pages, 58 files of the Full Stack FastAPI Template, 200 GitHub issues and 100 discussions (514 documents, 4,241 chunks in production). FastAPI, its docs site and its community move on, so answers about anything since May are missing or stale. The refresh keeps FastPilot's knowledge current for as long as it is public, without a Mac, manual steps or anyone remembering.

A refresh changes what FastPilot says. It is treated as a **release of FastPilot's knowledge**: gated, compared with the version it replaces, recorded, and reversible.

## Goals (the founder's four, 23 Nov 2026: "all the above")

1. **Answers never get worse silently.** Every refresh is evaluated and blocked if quality drops.
2. **A broken source can't produce a quietly broken corpus.** Each source is checked before anything is built; any failure stops the whole run and says which source and why.
3. **The live site can't break.** The server installs only a published, checksum-verified snapshot, checks FastPilot's health afterwards, and puts the previous snapshot back automatically if that fails.
4. **It keeps happening.** Scheduled, unattended; the founder's effort is reading a notice and, rarely, rolling back.

## Non-goals

- Changing the retrieval design (chunking, embedding model, hybrid search, reranking). The refresh rebuilds the same pipeline on new content.
- Changing the golden evaluation set inside a refresh run. That is a normal reviewed pull request (see Evaluation).
- Backups of Qdrant beyond the snapshots (Qdrant is rebuildable by decision).

## Anti-goals (would be a failure even if it technically works)

- A refresh that lowers answer quality and goes live because nothing measured it.
- A judge or model change that passes for a quality change (scores must always say which judge produced them).
- Partial corpora: three sources fresh and one silently empty or stale.
- A refresh that needs secrets or write access on the internet-facing server, or opens a way into it.

## Constraints

- **Server:** CX23, Qdrant capped at 256 MB (today's index peaks at about 82 MB); the D6 firewall lock allows HTTPS from Cloudflare only and SSH over WireGuard, so the server can only **pull** (outbound), never be pushed to.
- **The server only restores snapshots; it never builds them** (Phase 22 decision).
- **Gemini:** the paid tier is required for a public site serving the UK (Gemini API terms: "You may use only Paid Services when making API Clients available to users in the European Economic Area, Switzerland, or the United Kingdom"). The refresh uses the capped `fastpilot-prod` key. `gemini-2.5-flash` is gone for new projects and rerouted for everyone from 1 Dec 2026.
- **CI:** adding secrets and a scheduled workflow is a founder merge (CI permissions); the `cron` line is added from the founder's own account (GitHub mails scheduled-run failures to whoever last changed it).
- **Free first:** GitHub Actions minutes are free for this public repository; Cloudflare R2 is free up to 10 GB of storage with no egress fees (a corpus version is about 110 MB; at most 4 are kept); model spend per run is a few dollars inside the Gemini cap.
- **Corpus files are private.** Snapshots and sources contain the full text of about 300 GitHub threads written by other people. "Publicly visible" is not a clear licence to republish them in bulk, so every corpus file lives in a private bucket. Only scores, counts and links go into the public GitHub notice. Nothing private may enter the corpus either.

## Decisions (founder's words, 23 Nov 2026)

| Decision | Answer | Meaning |
|---|---|---|
| When to refresh | "After go-live, on a schedule (Recommended)" | Launch on the May corpus; the refresh comes after. |
| Storage | "Private R2 for everything (Recommended)", 24 Nov 2026, replacing "GitHub Releases (Recommended)" | A private Cloudflare R2 bucket holds every corpus version (snapshot, sources, report). Changed after the founder asked whether public threads can be republished: visible is not the same as licensed for bulk redistribution, so private storage removes the question. |
| Approval | "Auto-publish, I can roll back" (replaces the earlier "publish the draft = approval") | A refresh that passes every gate goes live by itself; the founder gets a notice and a one-step rollback (a workflow button). The gates are the approval. |
| GitHub threads | "Fixed size, best of all time + newest (Recommended)" | Totals stay about 200 issues and 100 discussions; old low-value threads rotate out. |
| New-content checks | "Auto freshness probes, report only (Recommended)" | Generated probes are reported, never a gate. |
| Schedule | "Monthly check, build only if changed (Recommended)" | Monthly; stops cheaply when nothing meaningful changed. |
| Build approach | "A: one staged pipeline (Recommended)" | See below. |
| Stale golden questions | "Flag, exclude, keep ≥10 of 12 (Recommended)" | See Golden-question health. |
| Score noise | "Floors + re-run on a dip (Recommended)" | See Evaluation. |
| Release retention | "Keep 3 + the bootstrap" | See Retention. |

## Approaches considered

- **A. One staged pipeline in FastPilot, one GitHub Actions workflow (chosen).** All-or-nothing in one run, one report, simple rollback, same command locally and in CI.
- **B. One workflow per source, merged at the end.** Faster and parallel, but partial states (some sources fresh, some stale) and harder all-or-nothing guarantees, which work against goal 2.
- Dropped: building on the server (breaks "the server only restores", uses reserved memory, puts build keys on the public machine); a workflow orchestrator such as Dagster (a new service to run for one monthly job).

## Design

### Where the code lives

A new package `corpus/` in FastPilot, with the source code **moved out of the private capstone repository** (`week-1/scripts/00_preprocess_html.py`, `week-1-bettercorpus/scripts/00`–`05`, `week-3/scripts/indexing/01_create_hybrid_pipeline.py` and its AST chunker, `_corpus.py`, `_github.py`, `_network.py`) and adapted. `scripts/07_reindex_production.py` and `scripts/05`/`06` evaluation scripts call into it. After the move FastPilot no longer needs `FASTPILOT_CORPUS_ROOT` or the capstone repository. The Week-4 evaluation instruments the RAG evaluation uses (`run_decomposed_judge`, `run_semantic_metrics`, `_eval_common`) move into `evaluations/instruments/` with their behaviour unchanged except the judge model, which becomes a setting.

One command runs everything, in CI and locally: `uv run python -m corpus.refresh [--stage <name>] [--force]`.

### Stages

Each stage reads the previous stage's **manifest** (JSON: status, inputs, counts, hashes, versions, timings) and writes its own. A stage refuses to start if any earlier manifest is missing or not `ok`. All manifests go into the release.

1. **check-changes.** Compares the live sources with the current published corpus (its manifest): the docs site's page list and content hashes, the template's latest release or commit, and GitHub threads updated since the last corpus. If nothing passes the change threshold (below), it writes `no-change`, the run ends green in about a minute with no model calls, and the notice says so. `--force` skips the check.
2. **fetch.** All four sources into a clean work folder:
   - **Official docs:** a scripted mirror of `https://fastapi.tiangolo.com/` (English only, the same exclusions as May's manual `wget` steps, now in code), then the HTML-to-Markdown converter. The converter is updated for the site's current generator (Zensical; May was MkDocs Material 9.7.6) and tested on the whole site, not one page.
   - **Template:** `fastapi/full-stack-fastapi-template` at its latest release tag (or `main` if it has none); the commit is recorded.
   - **Issues** (GitHub REST) and **discussions** (GitHub GraphQL): closed or answered threads only, as in May, selected as below.
3. **validate.** Per-source checks; any failure fails the run (goal 2):
   - counts within bounds (docs within ±15% of the last corpus, template ≥ 40 files, issues and discussions at their targets ±10%);
   - every document has its required fields (`source`, `file_path`, `title`, non-empty content above a minimum length);
   - **sample checks:** a fixed list of must-exist pages (for example `tutorial/first-steps`, `tutorial/security/oauth2-jwt`, `advanced/websockets`) is present and contains its known headings; no page is mostly navigation or banner text (a ratio check);
   - no duplicates; no non-English pages;
   - nothing private: every thread is from `fastapi/fastapi`, public.
4. **build.** Documents with harmonised metadata (`05_build_documents.py` logic), `file_path` normalised to forward slashes everywhere (May's `source_html` field carried Windows backslashes; the category map's keys already use `/`), and a **category** for every document from a rebuilt categoriser (below). The build fails if any document has no category or if the category counts shift more than a set margin from the last corpus without the change report explaining it.
5. **index.** The proven hybrid pipeline (AST chunker, `voyage-4-lite` 2048-d dense, `Qdrant/bm25` sparse, named vectors `text-dense` and `text-sparse`) into a Qdrant 1.18 service container, collection `rag_accelerator_capstone_final`. Fails if the chunk count changes more than **25%** from the last corpus (catches, for example, a site change that splits pages into thousands of fragments). Then a snapshot and its SHA-256. The index settings (collection, models, dimension, vector names) come from `app/config.py`, the same source the app queries with, and each version records them as a **settings fingerprint**; the server refuses a version whose fingerprint differs from what the running backend reports (my call, 24 Nov 2026, after the founder asked how the settings stay the same; a mismatch would make search quietly worse, not fail).
6. **evaluate.** The gate and the report (below), against the new index.
7. **decide.** `pass` only if every gate holds; otherwise `fail` with the reasons. On `fail`, nothing is published; the run is red, and one issue "Corpus refresh failed" is opened (or updated) with the reasons and the stage that failed. A `no-change` run shows only in the workflow's run summary (no issue), so quiet months make no noise.
8. **publish.** On `pass`: the six files (`rag_accelerator_capstone_final.snapshot`, its `.sha256`, `documents.jsonl`, `sources.tar.gz`, `manifests.tar.gz`, `report.json`) are uploaded to the private bucket under `corpus/<tag>/`, where `<tag>` is `corpus-YYYY-MM-DD` (a second version on the same day gets `.2`, then `.3`). Only after every upload is verified (size and SHA-256 read back) does the stage add the version to `corpus/index.json` with status `published`. `index.json` is the single list the server and the next refresh read: each entry has the tag, the date, the status (`published` or `rolled-back`), the chunk count and the snapshot's SHA-256. It is replaced in one write, so it is never half-updated. Then a notice issue opens on GitHub ("Corpus refresh: <tag> live") with the scores, stale questions, probes, per-source counts, cost, duration and the rollback button's name; it never contains thread text. Then retention (below).

### Retention (founder: "Keep 3 + the bootstrap")

After a new version is live, the publish stage deletes the folders of `published` versions older than the **3 newest**, never the bootstrap `corpus-2026-05-14`, and of `rolled-back` versions older than 90 days, removing their `index.json` entries in the same write. The server holds at most the live index and one previous snapshot. Local test volumes and the old Qdrant Cloud cluster are cleaned by hand (the cluster is the founder's).

### GitHub thread selection (fixed size)

Targets: **100 all-time + 100 recent issues, 50 all-time + 50 recent discussions** (my proposal; the founder can change the numbers).

- **Scores** (my call; May used comments for issues and comments + upvotes for discussions, and "most comments" is not the same as "best": a long thread can be an unresolved argument):
  - issue: positive reactions (👍 ❤️ 🎉 🚀) + a bonus for `answered` or `confirmed` labels + comments at half weight; must be closed with at least one useful label (May's `USEFUL_LABELS`) and a maintainer reply or a linked fix;
  - discussion: must be answered; the discussion's upvotes + the accepted answer's upvotes + comments at half weight.
- **All-time:** the top of those scores over the repository's whole history.
- **Recent** (my call; the builder check found too few new closed issues per month for "since the last corpus"): the top of the same scores among threads closed or answered in the **last 12 months**, not already in the all-time list. If fewer qualify than the target, the gap is filled from the next all-time threads, and the report says so; this never fails the run.
- **Pinned** (my call, from the plan review): every thread cited by a golden question's reference contexts always stays in the corpus, counted within the totals, so rotation alone can never make a golden question stale. The fetch manifest lists each pinned thread and which question cites it.
- Threads that fall out of every list leave the corpus. The selection and each thread's score and reason (`pinned`, `all-time`, `recent`, `fill`) are written into the fetch manifest.

### The categoriser

The Week-3 map (`category_map.json`, 514 entries, 11 categories) has no source code left: it assigned 383 files from metadata and 131 from path patterns. The refresh rebuilds this as deterministic code (no model calls): GitHub labels and docs section paths first, then path and keyword patterns, then `general`. **Acceptance test:** on May's 514 documents the rebuilt categoriser must reproduce May's map for at least 95% of files; every difference is listed and reviewed once when the code is written.

### Evaluation

- **Gate (blocks publishing):**
  - RAG: the 12 golden questions, faithfulness and answer coverage each ≥ **0.90**;
  - Agent: the 10 golden tasks, success with self-correction ≥ **0.80**;
  - **and** no real drop against the currently published corpus. Floors always apply. If the new corpus scores below the current one at all, the run re-scores **both** corpora side by side once more, with the same judge and model and the **same set of valid golden questions** (the previous release's snapshot is restored into the CI Qdrant as a second collection, and the answer runner is pointed at each in turn); it blocks only if the new one is worse on both runs: RAG faithfulness or coverage lower by more than **0.03**, or Agent success lower by **2 or more tasks**. (The 10 Agent tasks move in steps of 0.10, so one chance failure must not block a refresh.) The metrics compared are those three; completeness and first-attempt success are reported only.
- **Judge:** fixed to `gemini-3.8-flash` (the 2.5 judge is no longer available to new projects). The judge model and FastPilot's model are recorded with every score; if either differs from the previous corpus's, the run re-scores the previous snapshot (restored as the second collection, as above) with the current judge and model before comparing, so a judge change can never pass for a quality change.
- **The baseline** is always the newest `published` version in `index.json`, the same one the server installs, so a rolled-back version is never the comparison.
- **Report (never blocks):** freshness probes, a handful of questions generated from what changed (new doc pages, new release notes), each checked for whether retrieval returns the new page in the top results; per-source counts and changes; chunk count; cost and duration.
- **The golden set** is reviewed by a person once a year, or when probes keep showing gaps; changes are a reviewed pull request, never part of a run. Freshness probes that keep proving useful are suggested in the notice as golden candidates.

### Golden-question health (before the gate)

The 12 golden questions have reference answers written against May's corpus; the coverage score measures how much of that answer the retrieved text supports, so a question goes stale when its sources change, not only when FastPilot gets worse. From May's `golden_dataset.json` (`reference_contexts[].metadata.source`): six cite Full Stack Template files (Q3, Q4, Q5, Q8, Q10, Q12) and are most at risk when the template moves on; Q6, Q7 and Q11 cite only GitHub threads, and Q1 and Q9 mostly threads, which pinning (above) keeps in the corpus.

On every run, for each golden question:
1. Did the documents its reference answer relied on change between the two corpora? If not, it stays in the gate.
2. If they did, the judge checks whether the reference answer is still true according to the new documents. Still true: it stays in the gate. Not true: it is marked **stale**, left out of this run's gate, listed in the notice, and an issue is opened ("Golden Q4 needs updating: …"), one per stale question, updated rather than duplicated on later runs.
3. **Floor:** at least **10 of 12** must be valid; below that the run does not publish and waits for a person to update the set.

The Agent tasks need no such check: each writes and runs code, so a FastAPI change that breaks one is a real failure.

### Change threshold (for check-changes)

A refresh builds when any of these holds: at least 5 docs pages added, removed or changed in content; the template has a new release; at least 20 threads have entered the recent lists since the last corpus; or 90 days have passed since the last corpus (so it never goes stale even if each month changes little).

### Schedule and workflow

`.github/workflows/corpus-refresh.yml`: monthly `schedule` (the founder adds the `cron` line from their own account) and `workflow_dispatch` (with a `force` input). One job; Qdrant as a service container; secrets `GOOGLE_API_KEY` (the capped `fastpilot-prod` key), `VOYAGE_API_KEY` and an R2 token with **read and write on the `fastpilot-corpus` bucket only** (`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`); `permissions: contents: read`, `issues: write` (the notice). A second input, `rollback: <tag>`, runs only the rollback (below). Concurrency group so two runs never overlap. Timeout 120 minutes.

### Rollback

From GitHub: Actions, "Corpus refresh", **Run workflow** with `rollback` set to the bad version's tag. The workflow marks that version `rolled-back` in `index.json` (nothing else), so the server falls back to the previous `published` version on its next check; an immediate rollback is that plus running the updater by hand. The founder needs no token on their own machine.

### The server updater (infra)

`scripts/deploy-fastpilot-index-updater.sh` installs a small updater and a systemd timer (daily) on the server:

1. Read `corpus/index.json` from the private bucket with a **read-only** R2 token scoped to `fastpilot-corpus` (kept on the server mode 600, `/home/apps/fastpilot-prod/r2-read.env`) and pick the newest `published` version.
2. If its tag equals the installed one (`/home/apps/fastpilot-prod/INDEX_RELEASE`), stop.
3. Download the snapshot and `.sha256` to a temporary folder; verify the checksum against both the file and `index.json`; refuse anything not named for the one collection.
4. Restore with the same logic as `restore-fastpilot-index.sh --replace` (copy into the Qdrant container, recover from inside the internal network), then check the point count against the release's manifest and run a retrieval health check through the backend.
5. Clear FastPilot's semantic-cache keys (answers are cached for 24 hours, so without this visitors would keep getting the old corpus's answers, including after a rollback). My call: the updater does it directly in the Redis container, with the password read from `redis.conf` the way the health check does; no new endpoint, and no secret leaves the server.
6. On success, record the tag. On any failure, restore the previous snapshot (kept on the server until the next success), record the failed tag in `INDEX_FAILED_RELEASE` and log it; the updater does not retry that tag, and tries again only when a newer release appears (or the founder clears the file).

The updater's only secret is the read-only R2 token: it can read corpus files and nothing else, and a leak exposes only corpus text. It talks to Qdrant through the backend container, which already holds the Qdrant key. The S3 client it uses (an official container image or a single binary) is the builder's proposal for the founder's package approval.

## Left to the builder

- Exact bounds and margins beyond those stated, tuned on the first two runs and recorded.
- The must-exist page list and the navigation-ratio threshold.
- The freshness-probe generator (a cheap model call or a template from page titles).
- Test layout, as long as every gate and refusal has a test (CI stays hermetic: stages are tested with recorded fixtures; the live run is the workflow).
- Order of the pull requests: (0, infra) the private R2 bucket `fastpilot-corpus` in the existing `terraform/r2-backups` root style, with two tokens (workflow read-write, server read-only), founder merge; (1) move the code and the evaluation instruments, with the categoriser test; (2) the stages and the local command; (3) the workflow (founder merge); (4) the first version: today's May corpus and the 23 Nov snapshot, uploaded as `corpus-2026-05-14`, so the current production index is preserved; (5) the infra updater.
