# Deploying FastPilot

> **Status 2026-11-23:** production moves to the founder's VPS through infra Phase 22: the stack is
> `deploy/docker-compose.prod.yml` (see "Production on the VPS" below). Railway is offline, and the
> Railway sections below are **historical**. Do not use them for a new deployment.

## Services

FastPilot's own code runs as **three services** (production adds Qdrant and Redis, see below):

| Service | Image | Role |
|---|---|---|
| `backend` | `fastpilot-backend` | FastAPI. Holds the API keys. Sends generated code to the runner. |
| `frontend` | `fastpilot-frontend` | Streamlit. The only service with a public address. |
| `runner` | `fastpilot-runner` | Runs generated code. No network, no keys, read-only filesystem. |

The backend and the runner share a Docker volume (`runner_sock`) that holds only the runner's Unix
socket. The runner has `network_mode: none`, so nothing can reach it over a network. Compose sets
`EXECUTOR_MODE=runner` and `ALLOW_LOCAL_EXECUTOR=false` on the backend, so Agent and Playground turn off
if the runner is not used. Run everything locally with `docker compose up backend frontend --build`
(the runner starts as a dependency).

Do not make Agent and Playground public until the VPS move is done.

**Rate limits (issue #12).** Limits count per visitor address: Chat 15 questions a day, Agent 2 runs a
minute and 5 a day, Playground 3 runs a minute and 30 a day (`/execute` and `/fix` together). The
browser only talks to Streamlit, so the frontend forwards the visitor's address to the backend. For
that to work on a public host:
- Set the same random `FRONTEND_PROXY_KEY` on the backend and the frontend (`openssl rand -hex 32`).
  Without it, the backend ignores the forwarded address and all visitors share one limit.
- Make the frontend reachable only through Cloudflare (for example, Cloudflare edge mode or a tunnel,
  with no open port). The frontend reads the visitor's address from `CF-Connecting-IP`, and anyone who
  reaches Streamlit directly can set that header to any value.
- Keep the backend off the public internet. The shared key protects it if a port opens by mistake.
- `docker-compose.yml` publishes `8000:8000` and `8501:8501` on every host interface, and ports Docker
  publishes bypass host firewalls such as ufw. On the VPS, remove the backend's `ports:` entry and bind
  the frontend to `127.0.0.1:8501:8501` (or publish no port at all behind a tunnel), for example in a
  compose override file. Otherwise anyone can reach Streamlit directly with a made-up
  `CF-Connecting-IP` on each request and get a fresh limit every time.

## Production on the VPS (infra Phase 22)

`deploy/docker-compose.prod.yml` is the production stack: `fastpilot-prod-{backend,frontend,runner,qdrant,redis}`,
no published ports (Caddy reaches the frontend on `caddy_net`), Qdrant 1.18 and Redis 8 pinned by digest, a
memory cap on every service (1,728 MB in total) and one env file per service, so the internet-facing frontend
holds no API keys. Copy the `deploy/*.env.example` files and `deploy/redis.conf.example`, fill them in, and never
commit them (`.gitignore` covers `deploy/*.env` and `deploy/redis.conf`). The infra repository's
`deploy-fastpilot.sh` replaces `__FASTPILOT_TAG__` with a `sha-<commit>` tag, checks the file and deploys it.

**Index.** Build it on the Mac (the corpus lives in the capstone repository):
`FASTPILOT_CORPUS_ROOT=~/source/code/rag/rag-accelerator-capstone uv run python scripts/07_reindex_production.py --full`
into a local Qdrant, then take a snapshot. Qdrant and Redis sit on an internal network, so the snapshot is
restored from inside: copy it into `/qdrant/snapshots/<collection>/` and call
`PUT /collections/<collection>/snapshots/recover` with `file://` and the checksum, from the backend container.
The 23 Nov 2026 snapshot (4,241 points, SHA-256 `762a6402…`) is kept on the Mac in
`~/source/code/portfolio/fastpilot-index-snapshots/`.

**Local measuring:** `docker network create caddy_net` once, then
`docker compose -f deploy/docker-compose.prod.yml -f deploy/docker-compose.local.yml up -d --build`.

## Historical: Railway (offline)

The original setup was **two services in one Railway project** (class week-5 topology): a private
`backend` (FastAPI) and a public `frontend` (Streamlit). The runner container needs a volume shared by
two containers and a no-network service, which the old Railway setup did not have. State is managed and external (Redis Cloud and
Qdrant Cloud); nothing stateful runs in a container.

## How it deploys — Railway's native GitHub integration (NOT GitHub Actions)

Railway connects to the GitHub repo directly and **auto-builds + deploys each service on every push**
to the connected branch, using each service's `Dockerfile` + `railway.toml`. There is **no deploy
GitHub Actions workflow** — and there shouldn't be:

- **`.github/workflows/ci.yml` stays CI-only** (hermetic tests + ruff). It never deploys.
- Railway's own pipeline does the build/deploy from the repo. This is the simplest, class-standard path.
- *(A GitHub Actions deploy via the `railway` CLI + a `RAILWAY_TOKEN` secret is possible, but it
  duplicates what the native integration already does and adds a secret + a workflow to maintain.
  Not used here.)*

So the deploy trigger is: **push to the branch Railway watches → Railway rebuilds the changed service.**

## Deploy gating (chosen policy)

**Straight from `main`, gated on CI.** No deploy branch, no PR-approval step (solo project) — but
a broken build must never reach production:

- In each Railway service → **Settings → enable "Wait for CI"** (check status before deploying).
  Railway then holds the deploy until the GitHub `ci.yml` checks pass on that commit. Push to `main`
  → CI runs ruff, the constraints check and the tests → green → Railway deploys; red → no deploy.
- This reuses the existing CI as the gate, so there is **no GitHub Actions deploy workflow** to
  maintain (a `railway`-CLI deploy job would only duplicate the native integration).
- **During a demo/recording window:** flip the service to **manual deploy** (or just don't push) so
  the live app is a frozen, known-good build while you record.
- *(If this repo ever becomes collaborative and you want a hard approval gate, point Railway at a
  `production` branch and promote `main → production` via PR — not needed today.)*

## One-time setup (Railway dashboard)

1. **New Project → Deploy from GitHub repo** → pick this repo.
2. Add **two services** from the same repo:
   - **backend** — Settings → **Root Directory = `app`**. Railway finds
     `app/railway.toml` + `app/Dockerfile`. Healthcheck `/health` is already configured.
   - **frontend** — Settings → **Root Directory = `frontend`**.
3. **Env vars** (Railway dashboard → each service → Variables; never in the repo). Use the **same
   values as your local `.env`** — copy them straight across:
   - **backend:** `QDRANT_URL`, `QDRANT_API_KEY`, `GOOGLE_API_KEY`, `VOYAGE_API_KEY`,
     `REDIS_HOST`, `REDIS_PORT`, `REDIS_PASSWORD`, `REDIS_SSL=true`, `QDRANT_COLLECTION=rag_accelerator_capstone_final`,
     `CACHE_DISTANCE_THRESHOLD=0.16`, `OPIK_API_KEY`, `OPIK_WORKSPACE`, `OPIK_PROJECT_NAME=fastpilot`,
     `PLAYGROUND_ENABLED=false` for staging or production unless you have explicitly accepted the risk.
   - **frontend:** `API_BASE_URL=http://backend.railway.internal:${{backend.PORT}}`
     (Railway's cross-service reference — resolves to the backend's injected port over the private network).
     `BACKEND_URL` is accepted as an alias if `API_BASE_URL` is unset; set the full base URL
     (scheme, no trailing slash). The client appends `/query`, `/health`, etc. Also set
     `PLAYGROUND_ENABLED=false` to hide Playground from the Streamlit sidebar.
4. **Public domain:** Settings → Networking → **Generate Domain on the `frontend` service ONLY**.
   Leave the backend with **no** public domain — it's reachable only at `backend.railway.internal`.
5. `$PORT` is handled — both Dockerfiles bind Railway's injected `$PORT`
   (`uvicorn … --port $PORT` / `streamlit … --server.port $PORT`).
6. **Gate on CI:** in each service → Settings → enable **"Wait for CI"** so a deploy only runs after
   `ci.yml` passes on that commit (see [Deploy gating](#deploy-gating-chosen-policy) above).

## Verify before recording the demo

- Backend (from the frontend, or a one-off `railway run`): `/health` → `{"status":"healthy"}`.
- Open the public frontend URL → **Chat streams token-by-token** (SSE must arrive incrementally
  through Railway's proxy, not as one buffered blob) → **Agent mode** writes/runs/self-corrects.
- **Real-phone pass** over the public URL (mobile layout).
- Pre-demo warmup: hit `/health` + run one query ~5 min before recording (warms the model clients).

## Record the demo (for the README + portfolio)

A short screen recording is what turns a 10-second README skim into a real look. Record against the
**deployed public URL** (Loom, or QuickTime → convert to GIF). Keep it **under 2 minutes**, hit these
beats, then paste the link into the two placeholders in `README.md` (live demo + walkthrough):

1. **Chat** — ask "How do I add JWT auth?" → show the streamed answer + a `[n]` citation.
2. **Follow-up** — a short follow-up that hits the conversation memory / semantic cache.
3. **Agent** — "Write and run a POST /items endpoint that returns the created item with HTTP 201,
   with a self-test asserting status 201" → show the timeline self-correct (Run → error → Fix &
   rerun → exit 0). This task reliably fails the first attempt then recovers (~6/7 runs), so the
   self-correct beat actually shows; do a dry-run first and re-run on the rare clean first pass.
4. **Playground** — tweak the agent's code and re-run it yourself.

For an animated hero GIF in the README, drop the file at `docs/screenshots/hero.gif` and swap the
`<img src="docs/screenshots/01-welcome.png">` tag at the top of `README.md` to point at it.
Talking points for the recording live in [`video-transcript.md`](video-transcript.md).

## Local parity
`docker compose up backend frontend` (from the repo root) starts all three services against the same
managed Redis/Qdrant — same Dockerfiles as the images below.

## GHCR images

The `publish-ghcr.yml` workflow builds the backend, frontend and runner Docker images for the VPS.
The images are to be **public** (founder, 23 Nov 2026: "Public (Recommended)"): the repository is
public and the images hold no secrets, so the server pulls them without a token. Production deploys
pin a `sha-<short-sha>` tag (infra Phase 22); `:main` is for local use only.

The three packages came out **public** on the first publish (23 Nov 2026): they are linked to this
public repository and took its visibility, so no settings change was needed. Checked with a logged-out
pull: `DOCKER_CONFIG=$(mktemp -d) docker pull --platform linux/amd64 ghcr.io/olaheavy-dev/fastpilot-backend:main`.
The images are built for `linux/amd64` (the server) only.

On pull requests, the workflow builds all three images without pushing them. On push to `main`, or a
manual workflow dispatch, it publishes:

```text
ghcr.io/olaheavy-dev/fastpilot-backend:main
ghcr.io/olaheavy-dev/fastpilot-backend:sha-<short-sha>
ghcr.io/olaheavy-dev/fastpilot-frontend:main
ghcr.io/olaheavy-dev/fastpilot-frontend:sha-<short-sha>
ghcr.io/olaheavy-dev/fastpilot-runner:main
ghcr.io/olaheavy-dev/fastpilot-runner:sha-<short-sha>
```

Runtime secrets are supplied by the target platform, to the backend only. The runner gets none. Do not bake Qdrant, Redis, Voyage,
Google, or Opik credentials into the images.
