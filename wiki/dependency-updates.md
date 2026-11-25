# Dependency updates

How FastPilot's packages stay current and safe. The config is `.github/dependabot.yml`; the merge rules come from the house rules (see [[coding-conventions]] and the status file).

## Two kinds of Dependabot work

| Kind | What it does | Turned on |
|---|---|---|
| **Alerts** | Reports a known vulnerability in any package in `uv.lock`, including indirect ones. Shown under the repository's Security tab. | 25 Nov 2026 (before then they were off) |
| **Version updates** | Runs once when the config is merged, then opens pull requests each Monday at 06:00 (London time) for newer versions of `uv` packages and GitHub Actions. | 25 Nov 2026 |

The first alert scan found 138 open alerts; PR #47 cleared all of them (see [[log]], 25 Nov 2026).

## What the config does

- **7-day cooldown:** a new release is proposed only 7 days after it comes out. This gives the maintainers time to withdraw a bad release.
- **Patch releases are grouped** into one pull request. Minor and major updates stay one pull request each, because for a package whose version starts with `0.`, a minor bump counts as major.
- **`qdrant-client` stays below 1.19**, to match the Qdrant server in production (`v1.18.0` in `deploy/docker-compose.prod.yml`). Move the client and the server together, in one planned change.
- At most 5 open pull requests per ecosystem.

## Handling a `uv` pull request

Dependabot changes only `uv.lock`. The images install from `app/constraints.txt` and `frontend/constraints.txt`, and CI checks that they match the lock. So **every `uv` pull request fails CI at first.** That is expected, not a broken update.

1. Check out the pull request's branch.
2. Run `scripts/export_constraints.sh`, then commit and push the two constraints files to the same branch. Never force-push.
3. Run the check command (see [[testing-strategy]]). If the update touches `fastembed`, `voyageai`, `haystack-ai` or its integrations, also follow the checks below.
4. Merge by the house rules:
   - A patch or minor update of a package whose version is 1.0 or above, changing only the manifest, lock or constraints files, merges on green checks.
   - A major update, or a minor update of a `0.x` package, needs a review first.

### Extra checks for search packages

These packages change how documents are found. A version change can quietly make search worse without breaking any test.

- **`fastembed`** builds the BM25 sparse vectors. Compare its output on the old and new versions with the same texts: the sparse vectors must be identical, or the production index needs rebuilding. On 25 Nov 2026, 0.8.0 → 0.9.1 was checked this way: 111 chunks and 8 queries, all identical.
- **`voyageai` and `voyage-embedders-haystack`:** run a live smoke test (`embed` at 2,048 dimensions, `rerank`, and Haystack's `VoyageTextEmbedder` against a direct call).
- **`haystack-ai` and its integrations:** these are a planned migration, not a weekly update. Haystack 3 is a major release.

## Deploying

Merging builds new images (`publish-ghcr.yml`) but deploys nothing: production runs a fixed image tag set at deploy time. Deploy by following the infra runbook. After an update that touches `fastembed`, check that the first backend boot loads `Qdrant/bm25`. Since 0.9, fastembed downloads it only from Hugging Face.
