# Runner Sidecar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move execution of visitor-influenced code out of the FastPilot backend into a `runner` container with no network, no keys and a per-run clean-up, reached over HTTP on a Unix socket.

**Architecture:** A tiny FastAPI app (`runner/server.py`) wraps the existing `SubprocessExecutor` behind `POST /run`, with two slots (one uid each) and a leftover-process killer. The backend gets a `RunnerClient` with the same `run(code) -> ExecutionResult` interface, chosen by `EXECUTOR_MODE`, and fails closed with `unavailable=True`. Compose wires `runner_sock` as a shared volume; GHCR publishes a third image.

**Tech Stack:** Python 3.12, FastAPI, uvicorn (server on a pre-bound Unix socket), httpx (`HTTPTransport(uds=...)`), Docker Compose, pytest.

**Spec:** `docs/superpowers/specs/2026-11-22-runner-sidecar-design.md`

## Global Constraints

- Runner: `network_mode: none`, `read_only: true`, tmpfs `/tmp:size=64m,mode=1777` and `/dev/shm:size=8m,mode=1777`, `cap_drop: [ALL]`, `cap_add: [SETUID, SETGID, CHOWN, KILL]`, `security_opt: [no-new-privileges:true]`, `mem_limit: 768m`, `pids_limit: 128`, `restart: always`, never `env_file`, never a key.
- Runner environment (non-secret only): `EXECUTOR_WALL_TIMEOUT_S=15`, `EXECUTOR_CPU_SECONDS=10`, `EXECUTOR_MEM_MB=256`, `RUNNER_SLOTS=2`; compose sets the same values for the backend from one YAML anchor.
- Slot uids/gids: `61001`, `61002`. Socket: `/run/fastpilot/runner.sock`, folder `root:root 0755`, socket `root:1500 0660`, bound by our code (never `uvicorn --uds`).
- Restart freshness: runner exits 0 after 200 runs or 6 hours (6 × 3600 s), after finishing in-flight runs.
- Backend settings: `executor_mode: Literal["local", "runner"] = "local"`, `runner_socket: str = "/run/fastpilot/runner.sock"`, `allow_local_executor: bool = True`. Client timeout = `executor_wall_timeout_s + 10`.
- Fail closed: runner unreachable/timeout → `ExecutionResult(unavailable=True)`; never run locally in runner mode.
- Startup gate: if (`agent_enabled` or `playground_enabled`) and `executor_mode == "local"` and not `allow_local_executor` → log an error, set both flags False.
- Hermetic default: `uv run pytest` needs no Docker. Docker tests are `@pytest.mark.integration`. Coverage gate 90% on `app` (add `runner` to coverage source).
- Lint: ruff `E/F/I/B`, line length 120. No agent attribution in commits or PRs.

## Review Focus

1. More concurrent requests than slots (3+ at once): the extra request waits, then either runs or returns `unavailable` at the client timeout — never two runs in one slot. → Task 2 `test_third_request_waits_for_a_slot`.
2. A stale socket file left by a previous container: the runner must unlink it before binding, or it fails to start forever. → Task 2 `test_serve_replaces_stale_socket`.
3. The runner restarting mid-request (restart trigger hit while another slot is busy): the in-flight run must finish before exit. → Task 2 `test_restart_waits_for_in_flight_runs`.
4. Backend starts before the runner (compose order, or the runner is crash-looping): `/health` shows the runner down and `/execute` returns the `unavailable` guard, not 500. → Task 3 `test_execute_with_runner_down_is_unavailable_guard`.
5. Output near the cap and non-UTF-8 bytes in stdout: the JSON round-trip must not crash the client. → Task 3 `test_client_round_trips_large_and_odd_output`.

---

### Task 1: Executor accepts a run uid and cleans up as that uid

**Files:**
- Modify: `app/augmentations/code_executor.py` (`SubprocessExecutor.__init__`, `run`, constants `SANDBOX_UID`/`SANDBOX_GID`)
- Test: `tests/test_executor.py`

**Interfaces:**
- Produces: `SubprocessExecutor(..., sandbox_uid: int = 65534, sandbox_gid: int = 65534)`; when dropping privileges, `Popen(user=sandbox_uid, group=sandbox_gid, extra_groups=[])`, `os.chown(tmp/script, sandbox_uid, sandbox_gid)`, and folder clean-up via `_cleanup_as(path: str, uid: int, gid: int) -> None` (a second `python -I -c "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)" <path>` run with `user=uid, group=gid`, 5 s timeout, errors logged not raised). `TemporaryDirectory(..., ignore_cleanup_errors=True)` so root's own final attempt never raises.

- [ ] **Step 1: Write the failing tests**

```python
def test_popen_uses_configured_slot_uid_as_root(monkeypatch):
    # same fake Popen pattern as test_popen_switches_to_nobody_as_root
    ce.SubprocessExecutor(wall_timeout_s=2, sandbox_uid=61001, sandbox_gid=61001).run("print(1)\n")
    assert captured["user"] == 61001 and captured["group"] == 61001

def test_cleanup_runs_as_slot_uid_when_root(monkeypatch):
    # geteuid -> 0, chown no-op, fake Popen; record calls to ce._cleanup_as
    assert cleanup_calls == [(ANY_TMP_PATH, 61001, 61001)]

def test_no_cleanup_helper_when_not_root(monkeypatch):
    # geteuid -> 1000; ce._cleanup_as must not be called
```

- [ ] **Step 2: Run and see them fail**

Run: `uv run pytest tests/test_executor.py -k "slot_uid or cleanup" -v`
Expected: FAIL (`unexpected keyword argument 'sandbox_uid'`)

- [ ] **Step 3: Implement** the parameters, `_cleanup_as`, and the call after the run (inside the `with` block, before it exits) only when `drop` is true.

- [ ] **Step 4: Run the whole suite**

Run: `uv run ruff check . && uv run pytest -q`
Expected: all pass (existing `test_popen_switches_to_nobody_as_root` still sees 65534).

- [ ] **Step 5: Commit** — `git commit -m "Executor: configurable run uid, clean-up as that uid"`

---

### Task 2: Runner service (slots, leftover killer, server, socket)

**Files:**
- Create: `runner/__init__.py`, `runner/slots.py`, `runner/server.py`
- Modify: `pyproject.toml` (`[tool.coverage.run] source = ["app", "runner"]`; `[tool.hatch...] packages = ["app", "runner"]`)
- Modify: `.github/workflows/ci.yml` (add `uvicorn` to the curated install list; `--cov=app --cov=runner`)
- Test: `tests/test_runner.py`

**Interfaces:**
- Consumes: `SubprocessExecutor(wall_timeout_s, cpu_seconds, mem_mb, sandbox_uid, sandbox_gid)` and `ExecutionResult` from Task 1.
- Produces:
  - `runner/slots.py`: `kill_uid_processes(uid: int, proc_root: str = "/proc", kill=os.kill) -> int` (reads `<proc_root>/<pid>/status`, matches the real uid on the `Uid:` line, sends `SIGKILL`, ignores vanished pids, returns the count). `class SlotPool: __init__(uids: list[int]); async acquire() -> int; release(uid: int) -> None` (an `asyncio.Queue` of free uids).
  - `runner/server.py`: `create_app(executor_factory: Callable[[int], Executor], uids: list[int], max_runs: int = 200, max_age_s: int = 21600, killer=kill_uid_processes) -> FastAPI` with `POST /run {"code": str} -> ExecutionResult fields as JSON` and `GET /health -> {"status": "ok", "runs": int, "slots_free": int}`. The run executes in `asyncio.to_thread`; afterwards, always (`finally`), `killer(uid)` then `pool.release(uid)`. When `runs >= max_runs` or age ≥ `max_age_s`, set `app.state.should_exit = True`; a background check stops the server once no slot is busy.
  - `bind_socket(path: str, gid: int = 1500) -> socket.socket` (unlink a stale file, `chmod` the parent `0o755` owned by root when root, bind, `chmod 0o660`, `chown` to `(0, gid)` when root).
  - `main()` reads `EXECUTOR_*`/`RUNNER_SLOTS` from the environment, builds the app with uids `[61001, 61002][:slots]`, and runs `uvicorn.Server(config).run(sockets=[bind_socket(...)])`.

- [ ] **Step 1: Write the failing tests** (all hermetic; `FakeExecutor` returns a fixed `ExecutionResult`, optionally sleeping)

```python
def test_kill_uid_processes_kills_only_matching_uid(tmp_path):
    # fake /proc: pid 10 Uid 61001, pid 11 Uid 61002, pid 12 Uid 0, pid "self" ignored, pid 13 vanished
    killed = []
    n = kill_uid_processes(61001, proc_root=str(tmp_path), kill=lambda pid, sig: killed.append(pid))
    assert n == 1 and killed == [10]

def test_run_returns_execution_result_fields(): ...          # POST /run → ok, exit_code, stdout, stderr, blocked, unavailable
def test_killer_runs_after_every_run_even_on_error(): ...    # executor raises → killer still called with the slot uid; response is unavailable=True
def test_third_request_waits_for_a_slot(): ...                # 2 uids, 3 concurrent runs of a 0.3 s fake → max 2 in flight, all 3 succeed
def test_restart_waits_for_in_flight_runs(): ...              # max_runs=1, a second slot busy → should_exit True but server stop only after it finishes
def test_serve_replaces_stale_socket(tmp_path): ...           # create a regular file at the path → bind_socket succeeds, mode is 0o660
def test_health_reports_runs_and_free_slots(): ...
```

- [ ] **Step 2: Run and see them fail** — `uv run pytest tests/test_runner.py -v` → FAIL (`No module named 'runner'`)

- [ ] **Step 3: Implement** `runner/slots.py`, then `runner/server.py`.

- [ ] **Step 4: Run** — `uv run ruff check . && uv run pytest -q --cov=app --cov=runner --cov-fail-under=90` → all pass.

- [ ] **Step 5: Commit** — `git commit -m "Runner service: slots, leftover killer, socket server"`

---

### Task 3: Backend RunnerClient, settings, startup gate, health

**Files:**
- Create: `app/augmentations/runner_client.py`
- Modify: `app/config.py`, `app/augmentations/code_executor.py` (`get_executor`), `app/main.py` (lifespan gate, `/health`), `app/models.py` (`HealthResponse.executor: Optional[str] = None`), `.env.example`
- Test: `tests/test_runner_client.py`, `tests/test_agent_endpoints.py`

**Interfaces:**
- Consumes: `create_app`, `bind_socket` from Task 2 (tests serve the real runner app with a fake executor on a temp socket via `uvicorn.Server` in a thread).
- Produces: `class RunnerClient: __init__(socket_path: str, timeout_s: float); run(code: str) -> ExecutionResult; is_healthy() -> bool`. Any `httpx.HTTPError`, `OSError` or bad JSON → `ExecutionResult(-1, "", "[sandbox] code runner unavailable", 0, unavailable=True)`. `get_executor()` returns `RunnerClient(settings.runner_socket, settings.executor_wall_timeout_s + 10)` when `executor_mode == "runner"`. `apply_execution_gate(settings) -> bool` in `app/main.py` returns True when it turned the flags off.

- [ ] **Step 1: Write the failing tests**

```python
def test_client_runs_code_through_runner(runner_socket): ...                 # ok=True, stdout "hi"
def test_client_missing_socket_is_unavailable(tmp_path): ...                 # unavailable=True, never raises
def test_client_timeout_is_unavailable(slow_runner_socket): ...              # timeout_s=0.5 vs fake 2 s → unavailable
def test_client_round_trips_large_and_odd_output(runner_socket): ...         # 20_000-char stdout with "�" and "\x00" survives
def test_get_executor_returns_runner_client_in_runner_mode(monkeypatch): ...
def test_gate_turns_flags_off_when_local_not_allowed(): ...                  # local + allow_local_executor=False → both False, returns True
def test_gate_leaves_flags_in_runner_mode(): ...
async def test_execute_with_runner_down_is_unavailable_guard(): ...          # build(executor=RunnerClient("/nonexistent.sock", 1)) → 200, guard "unavailable"
async def test_health_reports_executor_mode(): ...                           # "/health" → executor == "local"
```

- [ ] **Step 2: Run and see them fail** — `uv run pytest tests/test_runner_client.py -v` → FAIL (`No module named 'app.augmentations.runner_client'`)

- [ ] **Step 3: Implement** the client, settings, `get_executor` branch, `apply_execution_gate` called in `lifespan` before `get_executor()`, and the `/health` field. Add `EXECUTOR_MODE=local` and `ALLOW_LOCAL_EXECUTOR=true` to `.env.example` with a one-line comment each.

- [ ] **Step 4: Run** — `uv run ruff check . && uv run pytest -q --cov=app --cov=runner --cov-fail-under=90` → all pass.

- [ ] **Step 5: Commit** — `git commit -m "Backend: RunnerClient, executor mode, fail-closed gate"`

---

### Task 4: Runner image, compose, GHCR, and container proof

**Files:**
- Create: `runner/Dockerfile`, `runner/requirements.txt` (`fastapi`, `uvicorn`, `pydantic`, `httpx` with the same lower bounds as `app/requirements.txt`), `tests/test_runner_integration.py`
- Modify: `docker-compose.yml`, `.github/workflows/publish-ghcr.yml`

**Interfaces:**
- Consumes: `runner.server:main` (Task 2), `EXECUTOR_MODE=runner` (Task 3).
- Produces: image `ghcr.io/<owner>/fastpilot-runner` built with context `.` and `file: runner/Dockerfile`; it copies `app/__init__.py`, `app/augmentations/{__init__,code_executor,security}.py` and `runner/`; `CMD ["python", "-m", "runner.server"]`. Compose service `runner` exactly as in Global Constraints, volume `runner_sock`; backend gets `EXECUTOR_MODE=runner`, `ALLOW_LOCAL_EXECUTOR=false`, `runner_sock:/run/fastpilot`, `depends_on: runner`. `AGENT_ENABLED` and `PLAYGROUND_ENABLED` come from one YAML anchor shared by backend and frontend, so the two can't disagree.

- [ ] **Step 1: Write the integration tests** (`pytestmark = pytest.mark.integration`; skip when `docker` is not on PATH; bring up `runner backend` with `docker compose up -d --build`)

```python
def test_captured_agent_programs_pass_through_execute(): ...      # POST /execute for each evaluations/eval_results/agent_code/*.py → exit_code 0
def test_runner_has_no_network(): ...                             # docker compose exec -u 61001 runner python -c "socket.create_connection(('1.1.1.1',53),2)" → non-zero, "Network is unreachable" or similar
def test_runner_has_no_keys(): ...                                # exec env → no name containing KEY/TOKEN/SECRET/PASSWORD
def test_runner_filesystem_is_read_only(): ...                    # exec -u 61001 touch /app/x → fails; /tmp works
def test_slot_user_cannot_touch_socket(): ...                     # exec -u 61001 python: connect to the socket → PermissionError; rm → fails
def test_leftover_process_is_killed_after_next_run(): ...         # exec -u 61001 -d setsid sleep 600; one /execute run; pgrep -u 61001 → empty
def test_stopped_runner_gives_unavailable_guard(): ...            # docker compose stop runner; /execute → guard "unavailable"
```

- [ ] **Step 2: Build the image and the compose stack** — `docker compose up -d --build runner backend` → both healthy; `docker compose logs runner` shows the socket path.

- [ ] **Step 3: Run** — `uv run pytest -m integration tests/test_runner_integration.py -v` → all pass. Then `docker compose down`.

- [ ] **Step 4: Add the GHCR matrix entry** (`service: runner`, `context: .`, `file: runner/Dockerfile`, image `ghcr.io/sunkanmi-olawuwo/fastpilot-runner`, matching the existing owner until issue #16 is settled) and pass `file:` to `docker/build-push-action` for all entries.

- [ ] **Step 5: Commit** — `git commit -m "Runner image, compose wiring, GHCR publish, container proof tests"`

---

### Task 5: Docs, wiki and decision record

**Files:**
- Modify: `README.md` (architecture diagram adds the runner), `wiki/component-architecture.md` (runner section + diagram), `wiki/overview.md` (diagram), `wiki/feature-coverage.md` (runner moves from deferred to implemented; limitation text), `wiki/endpoint-summary.md` (runner's `/run`, `/health`; backend `/health.executor`), `wiki/testing-strategy.md` (`tests/test_runner*.py`, integration marker), `wiki/onboarding.md`, `wiki/index.md` (no new page unless one is added), `wiki/log.md`, `docs/production-decisions.md` (D6 update), `DEPLOY.md` (three services; Railway section marked historical)
- Test: none (docs); pre-flight search instead.

- [ ] **Step 1: Pre-flight search** — `git grep -n -i "two-service\|two services\|in-process\|socket.connect patched\|boundary\|AGENT_ENABLED"` and fix every stale statement.
- [ ] **Step 2: Write the updates**, keeping the honest framing: the runner is the boundary; the scan is a filter; Agent and Playground go public only after the VPS move and issue #12.
- [ ] **Step 3: Run** — `uv run ruff check . && uv run pytest -q --cov=app --cov=runner --cov-fail-under=90` → all pass.
- [ ] **Step 4: Commit** — `git commit -m "Docs: runner sidecar"`
