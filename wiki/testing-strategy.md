# Testing Strategy

> How the suite is structured, what's expected of new tests, and the patterns to copy.
> Conventions in [[coding-conventions]]; the code under test in [[component-architecture]].

## Framework + layout
- **pytest** (+ `pytest-asyncio` in `auto` mode, `pytest-cov`).
- Config in `pyproject.toml`: `testpaths = ["tests"]`, `pythonpath = [".", "frontend"]`
  (so `import app` and `import api_client` both resolve).
- **~210 test functions** across `tests/` (`test_api`, `test_pipeline`, `test_services`,
  `test_agent`, `test_agent_endpoints`, `test_executor`, `test_security`, `test_components`,
  `test_observability`, `test_registry`, `test_sse_parser`, `test_frontend`, `test_units`,
  `test_integration`, `test_visual`, `test_smoke`, plus `test_runner`, `test_runner_client` and
  `test_runner_integration` for the runner sidecar).

## Test tiers (markers)
The **default run is hermetic and instant** — no network, no keys, < 10 s. Heavier tiers are
opt-in via markers (`addopts = -m 'not integration and not live and not visual'`):

| Marker | Needs | Run with |
|---|---|---|
| _(default)_ | nothing | `uv run pytest` |
| `integration` | local redis-stack container; `test_runner_integration.py` needs Docker (builds and runs the runner image: no network, no keys, read-only FS, slot isolation, leftovers killed, stopped runner gives `unavailable`) | `docker compose --profile test up -d redis-test` then `-m integration` |
| `live` | real Qdrant/Voyage/Gemini/Opik keys | `-m live` |
| `visual` | Playwright + chromium | `playwright install chromium` then `-m visual` |
| `slow` | nothing (just long, e.g. executor timeouts) | included by default |

`--strict-markers` is on — an unregistered marker is an error.

## Hermeticity (autouse fixtures in `tests/conftest.py`)
Three autouse fixtures make every test safe and offline by default:
- **`_no_network`** — monkeypatches `socket.connect`/`connect_ex` to raise, so no test can
  accidentally hit the network.
- **`_no_opik`** — forces `OPIK_AVAILABLE = False` and stubs `configure_opik` (live tests
  re-enable it themselves).
- **`_no_dogfood`** — stubs the dogfood append so unit tests never touch the real
  repo-root `dogfood/sessions.jsonl`.

## Fakes + the client builder
`conftest.py` provides lightweight fakes — `FakePipeline`, `FakeCache`, `FakeRouter`, and a
real `ConversationService` on **`fakeredis`** — plus a `build_client(...)` helper and an
`api_client` fixture that wires them into the app via `app.state`. This means:
- **Inject fakes, don't mock internals.** Construct the unit with fake collaborators (the
  agent/executor/pipeline all take their dependencies as args) rather than patching deep.
- Memory + query-rewrite are exercised *for real* against `fakeredis`, not stubbed.

## Key invariants under test
- **SSE contract round-trip** (`test_sse_parser`) — the frontend parser must consume exactly
  what the backend emits; `app/models.py` is the shared source of truth (see [[endpoint-summary]]).
- **Requirements drift tripwire** (`test_smoke`) — every package in the three images'
  `requirements.txt` must be a `pyproject.toml` dependency **and** be pinned in `constraints.txt`, so
  the images, dev and CI can't silently diverge. Versions
  are pinned too: the images install with `-c constraints.txt` generated from `uv.lock`, and CI
  fails if those files drift (`scripts/export_constraints.sh --check`). CI installs with
  `uv sync --frozen --all-extras`, so it tests the locked versions the images ship (issue #25).
- **Sandbox scan** (`test_executor`, `test_security`) — import allowlist, a regression test per known escape (reflection, shell, string-eval,
  `getattr`/`open`), network, and resource overruns are all asserted blocked.
- **Resilience** — degraded paths (no Redis, no keys) return `degraded`/structured guards,
  never 5xx.

## Coverage expectations
- **90% line coverage gate** on `app/` and `runner/`, enforced in CI (`--cov=app --cov=runner --cov-fail-under=90`).
  Branch coverage is on (`tool.coverage.run`).
- The deliberately-uncovered remainder is live-only code (real Redis/Qdrant/Opik build paths,
  the executor's forked-child `preexec_fn`), reached under `integration`/`live`.
- **New code should ship with tests that keep the gate green.** If a path is only reachable
  live, mark it `integration`/`live` and note why.

## Running
```bash
uv run pytest                 # hermetic (default)
uv run --frozen pytest --cov=app --cov=runner --cov-report=term-missing --cov-fail-under=90   # like CI
docker compose --profile test up -d redis-test
REDIS_HOST=localhost REDIS_PORT=6380 REDIS_SSL=false uv run pytest -m integration
```

CI (`.github/workflows/ci.yml`) installs exactly what `uv.lock` pins (`uv sync --locked`), runs ruff,
checks the image constraints against the lock, then the hermetic suite with the coverage gate, on
every push/PR (see [[overview]] → badges).
