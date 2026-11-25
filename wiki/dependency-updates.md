# Dependency updates

How FastPilot's packages stay current and safe. The config is `.github/dependabot.yml`. Pull requests merge under the founder's house rules for agents ("Shipping work": checks, review, and the small-dependency-update rule). Those rules are kept outside this repository; this page describes the steps but does not restate or change them.

## Two kinds of Dependabot work

| Kind | What it does | Turned on |
|---|---|---|
| **Alerts** | Reports a known vulnerability in any package in `uv.lock`, including indirect ones. Shown under the repository's Security tab. | 25 Nov 2026 (before then they were off) |
| **Version updates** | Opens pull requests each Monday at 06:00 (London time) for newer versions of the **direct** `uv` dependencies (the packages named in `pyproject.toml`), GitHub Actions, and the pinned Qdrant and Redis images in `deploy/docker-compose.prod.yml`. Adding or changing the config also starts a check straight away. | 25 Nov 2026 |
| **Security updates** | Opens a pull request for an alert, including in indirect packages. Each needs the constraints step below. | 25 Nov 2026 (founder: "Yes, turn them on (Recommended)") |

The first alert scan found 138 open alerts, all in **indirect** packages; PR #47 cleared all of them (see [[log]], 25 Nov 2026). Weekly version updates do not cover indirect packages. Security updates now open a pull request for such an alert; if one cannot (for example when a parent package caps the version), fix it by hand with `uv lock --upgrade-package <name>`, then follow the steps below.

## What the config does

- **7-day cooldown:** a new release is proposed only 7 days after it comes out. This gives the maintainers time to withdraw a bad release.
- **Patch releases are grouped** into one pull request. Minor and major updates stay one pull request each, because for a package whose version starts with `0.`, a minor bump counts as major.
- **`qdrant-client` stays below 1.19 and the `qdrant/qdrant` image gets patch releases only (v1.18.x)**, so the client matches the production server. Move the client and the server together, in one planned change. Image updates in `deploy/docker-compose.prod.yml` keep their `@sha256` digest pin; a pull request always changes the digest, and changes the tag only for a new patch release (Redis `8.4` refreshes keep the tag).
- **Haystack major versions are never proposed** (`*haystack*`, major updates ignored). Haystack 3 is a planned migration; a major Haystack change broke every Chat answer on 23 Nov 2026.
- **`lockfile-only`:** Dependabot changes only `uv.lock`, never `pyproject.toml` (every bound there is an open `>=`). Check the first pull request's diff to confirm.
- At most 5 open pull requests per ecosystem.

## Handling a `uv` pull request

Dependabot changes only `uv.lock`. The images install from `app/constraints.txt` and `frontend/constraints.txt`, and CI checks that they match the lock. So **every `uv` pull request fails CI at first.** That is expected, not a broken update.

Work on **one pull request at a time**, the one you are about to merge:

1. `gh pr checkout <number>`.
2. Run `scripts/export_constraints.sh` with the uv version CI pins (`uv==0.13.7` in `.github/workflows/ci.yml`; check with `uv --version`). Another uv version can format the export differently, and the check would still fail.
3. `git add app/constraints.txt frontend/constraints.txt`, commit, and push to the same branch. Never force-push.
4. Run the check command (see [[testing-strategy]]). If the update touches `fastembed`, `voyageai`, `haystack-ai` or its integrations, also do the checks below.
5. Merge by the house rules (small dependency updates merge on green checks; a major bump, or a minor bump of a direct dependency whose version starts with `0.`, needs the full review).
6. Then let Dependabot rebase the next pull request **before** you touch it. Every uv pull request changes `uv.lock` and both constraints files, so merging one puts the others in conflict. Once someone else has pushed to a Dependabot branch, Dependabot stops rebasing it, and `@dependabot recreate` would drop the constraints commit.

On the first uv pull request, also check the `uv.lock` diff for header or format changes: Dependabot's own uv version may differ from CI's.

## Handling a `docker-compose` pull request

These update the pinned Qdrant and Redis images in `deploy/docker-compose.prod.yml`. Only patch releases arrive: Qdrant `v1.18.x`, and Redis digest refreshes of `8.4`. **CI never starts these images**, so a green check proves nothing about them.

**Rule (founder, 25 Nov 2026: "No, review first (Recommended)"):** image pull requests never merge on green checks alone, even though they are small updates. They merge only after steps 1 and 2 below pass and the result is written in the pull request.

1. Check the `@sha256` digest changed, and that it belongs to the tag shown. A Qdrant patch release changes the tag (`v1.18.0` → `v1.18.1`) and the digest; a Redis refresh keeps the tag `8.4` and changes only the digest. Both are expected.
2. **Redis:** start the new image by itself on the test port and point the integration tests at it. The local Compose stack keeps Redis on an internal network with no published port, so the tests would not reach it there. Run `docker run --rm -d --name redis-candidate -p 6380:6379 <image>@<digest>`, then `REDIS_TEST_URL=redis://localhost:6380 uv run --frozen pytest -m integration tests/test_integration.py`, then `docker stop redis-candidate`. These tests cover the semantic cache's search index (RediSearch, built into Redis 8). **Qdrant:** start the new image with the local stack (`deploy/docker-compose.local.yml`) and restore the production snapshot into it, then run a search.
3. Deploy with the infra helper at a quiet time. A Redis image change restarts Redis with no persistence: rate-limit counters, chat memory and the answer cache start empty (accepted by decision; they rebuild).
4. After deploy, check that `/health` shows the cache available and the index's point count unchanged.

### Extra checks for search packages

These packages change how documents are found. A version change can quietly make search worse without breaking any test.

- **`fastembed`** builds the BM25 sparse vectors. Compare its output on the old and new versions with the same texts: the sparse vectors must be identical, or the production index needs rebuilding. On 25 Nov 2026, 0.8.0 → 0.9.1 was checked this way: 111 chunks and 8 queries, all identical.
- **`voyageai` and `voyage-embedders-haystack`:** run a live smoke test (`embed` at 2,048 dimensions, `rerank`, and Haystack's `VoyageTextEmbedder` against a direct call).
- **`haystack-ai` and its integrations:** these are a planned migration, not a weekly update. Haystack 3 is a major release.

## Deploying

Merging builds new images (`publish-ghcr.yml`) but deploys nothing: production runs a fixed image tag set at deploy time. Deploy by following the infra runbook. After an update that touches `fastembed`, check that the first backend boot loads `Qdrant/bm25`. Since 0.9, fastembed downloads it only from Hugging Face.
