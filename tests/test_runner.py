"""Runner service (``runner/``): slots, the leftover-process killer, the HTTP app and the socket.

All hermetic: a ``FakeExecutor`` stands in for ``SubprocessExecutor``, the killer reads a fake
``/proc`` tree, and real Unix sockets live in a short ``/tmp`` folder (macOS limits AF_UNIX paths
to about 104 bytes, so pytest's long ``tmp_path`` is not used for them).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import socket
import stat
import tempfile
import threading
import time
from dataclasses import dataclass, field

import httpx
import pytest
from fastapi.testclient import TestClient

from app.augmentations.code_executor import ExecutionResult
from runner import server as runner_server
from runner.server import bind_socket, create_app
from runner.slots import SlotPool, kill_uid_processes

UIDS = [61001, 61002]
_REAL_CONNECT = socket.socket.connect  # captured at import, before the conftest guard patches it


@dataclass
class FakeExecutor:
    """Returns a fixed result, optionally after a sleep; counts how many runs overlap."""

    uid: int
    delay_s: float = 0.0
    raises: bool = False
    tracker: dict = field(default_factory=dict)

    def run(self, code: str) -> ExecutionResult:
        lock = self.tracker.setdefault("lock", threading.Lock())
        with lock:
            self.tracker["now"] = self.tracker.get("now", 0) + 1
            self.tracker["max"] = max(self.tracker.get("max", 0), self.tracker["now"])
            self.tracker.setdefault("uids", []).append(self.uid)
        try:
            if self.delay_s:
                time.sleep(self.delay_s)
            if self.raises:
                raise RuntimeError("boom")
            return ExecutionResult(0, f"ran {code!r}\n", "", 5)
        finally:
            with lock:
                self.tracker["now"] -= 1


def _factory(delay_s: float = 0.0, raises: bool = False, tracker: dict | None = None):
    shared = tracker if tracker is not None else {}
    return lambda uid: FakeExecutor(uid, delay_s=delay_s, raises=raises, tracker=shared)


def _write_status(root, pid: str, uid: int) -> None:
    d = root / pid
    d.mkdir()
    (d / "status").write_text(f"Name:\tpython\nState:\tS (sleeping)\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")


# --- Leftover killer --------------------------------------------------------------------------


def test_kill_uid_processes_kills_only_matching_uid(tmp_path):
    # fake /proc: pid 10 Uid 61001, pid 11 Uid 61002, pid 12 Uid 0, pid "self" ignored, pid 13 vanished
    _write_status(tmp_path, "10", 61001)
    _write_status(tmp_path, "11", 61002)
    _write_status(tmp_path, "12", 0)
    _write_status(tmp_path, "self", 61001)
    (tmp_path / "13").mkdir()  # the process exited between listing and reading: no status file
    (tmp_path / "cpuinfo").write_text("not a pid")
    killed = []
    n = kill_uid_processes(61001, proc_root=str(tmp_path), kill=lambda pid, sig: killed.append(pid))
    assert n == 1 and killed == [10]


def test_kill_uid_processes_ignores_pid_that_vanishes_before_kill(tmp_path):
    _write_status(tmp_path, "20", 61001)
    _write_status(tmp_path, "21", 61001)

    def kill(pid: int, sig: int) -> None:
        if pid == 20:
            raise ProcessLookupError

    assert kill_uid_processes(61001, proc_root=str(tmp_path), kill=kill) == 1


def test_kill_uid_processes_missing_proc_root_returns_zero(tmp_path):
    assert kill_uid_processes(61001, proc_root=str(tmp_path / "nope"), kill=lambda p, s: None) == 0


async def test_slot_pool_hands_out_and_takes_back_uids():
    pool = SlotPool(UIDS)
    assert pool.free == 2
    a = await pool.acquire()
    b = await pool.acquire()
    assert {a, b} == set(UIDS) and pool.free == 0
    pool.release(a)
    assert pool.free == 1 and await pool.acquire() == a


# --- HTTP app ----------------------------------------------------------------------------------


def test_run_returns_execution_result_fields():
    killed: list[int] = []
    client = TestClient(create_app(_factory(), UIDS, killer=killed.append))
    r = client.post("/run", json={"code": "print(1)"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["exit_code"] == 0
    assert body["stdout"] == "ran 'print(1)'\n" and body["stderr"] == ""
    assert body["blocked"] is False and body["unavailable"] is False
    assert body["timed_out"] is False and body["block_reason"] is None and body["duration_ms"] == 5
    assert len(killed) == 1 and killed[0] in UIDS


def test_run_rejects_a_body_without_code():
    client = TestClient(create_app(_factory(), UIDS, killer=lambda uid: 0))
    assert client.post("/run", json={}).status_code == 422


def test_killer_runs_after_every_run_even_on_error():
    killed: list[int] = []
    app = create_app(_factory(raises=True), [61001], killer=killed.append)
    client = TestClient(app)
    body = client.post("/run", json={"code": "x"}).json()
    assert body["unavailable"] is True and body["ok"] is False
    assert body["exit_code"] == -1 and body["stderr"] == "[runner] internal error"
    assert killed == [61001]
    # The slot came back, so a second run still gets it.
    client.post("/run", json={"code": "x"})
    assert killed == [61001, 61001]
    assert client.get("/health").json()["slots_free"] == 1


def test_slot_is_released_even_if_the_killer_fails():
    def bad_killer(uid: int) -> int:
        raise PermissionError("no CAP_KILL")

    client = TestClient(create_app(_factory(), [61001], killer=bad_killer))
    assert client.post("/run", json={"code": "x"}).json()["ok"] is True
    assert client.get("/health").json()["slots_free"] == 1


async def test_third_request_waits_for_a_slot():
    tracker: dict = {}
    app = create_app(_factory(delay_s=0.3, tracker=tracker), UIDS, killer=lambda uid: 0)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://runner") as client:
        rs = await asyncio.gather(*(client.post("/run", json={"code": str(i)}) for i in range(3)))
    assert all(r.status_code == 200 and r.json()["ok"] for r in rs)
    assert tracker["max"] == 2
    assert sorted(set(tracker["uids"])) == UIDS


async def test_restart_waits_for_in_flight_runs():
    tracker: dict = {}

    def factory(uid: int) -> FakeExecutor:
        # Slot 61001 is slow, slot 61002 is quick.
        return FakeExecutor(uid, delay_s=0.4 if uid == 61001 else 0.0, tracker=tracker)

    app = create_app(factory, UIDS, max_runs=1, killer=lambda uid: 0)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://runner") as client:
        slow = asyncio.create_task(client.post("/run", json={"code": "slow"}))
        await asyncio.sleep(0.05)  # the slow run has taken 61001
        quick = await client.post("/run", json={"code": "quick"})
        assert quick.json()["ok"] is True
        assert app.state.should_exit is True
        assert app.state.ready_to_exit() is False  # the slow slot is still busy
        assert (await slow).json()["ok"] is True
    assert app.state.ready_to_exit() is True


def test_restart_after_max_age():
    app = create_app(_factory(), UIDS, max_age_s=0, killer=lambda uid: 0)
    assert app.state.ready_to_exit() is True
    assert app.state.should_exit is True


def test_not_ready_to_exit_before_the_limits():
    app = create_app(_factory(), UIDS, killer=lambda uid: 0)
    assert app.state.ready_to_exit() is False


def test_health_reports_runs_and_free_slots():
    client = TestClient(create_app(_factory(), UIDS, killer=lambda uid: 0))
    assert client.get("/health").json() == {"status": "ok", "runs": 0, "slots_free": 2}
    client.post("/run", json={"code": "x"})
    client.post("/run", json={"code": "y"})
    assert client.get("/health").json() == {"status": "ok", "runs": 2, "slots_free": 2}


# --- Socket ------------------------------------------------------------------------------------


@pytest.fixture
def short_dir():
    d = tempfile.mkdtemp(dir="/tmp")
    yield d
    shutil.rmtree(d, ignore_errors=True)


def test_serve_replaces_stale_socket(short_dir):
    path = os.path.join(short_dir, "r.sock")
    with open(path, "w") as fh:
        fh.write("stale")
    sock = bind_socket(path)
    try:
        assert stat.S_ISSOCK(os.stat(path).st_mode)
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o660
        assert sock.getsockname() == path
    finally:
        sock.close()


def test_bind_socket_as_root_sets_owner_and_parent(short_dir, monkeypatch):
    path = os.path.join(short_dir, "r.sock")
    chowns: list[tuple[str, int, int]] = []
    chmods: list[tuple[str, int]] = []
    real_chmod = os.chmod
    monkeypatch.setattr(runner_server.os, "geteuid", lambda: 0)
    monkeypatch.setattr(runner_server.os, "chown", lambda p, u, g: chowns.append((p, u, g)))

    def chmod(p: str, mode: int) -> None:
        chmods.append((p, mode))
        if p == path:
            real_chmod(p, mode)

    monkeypatch.setattr(runner_server.os, "chmod", chmod)
    sock = bind_socket(path, gid=1500)
    try:
        assert (short_dir, 0, 0) in chowns and (path, 0, 1500) in chowns
        assert (short_dir, 0o755) in chmods and (path, 0o660) in chmods
    finally:
        sock.close()


def test_bound_socket_serves_the_app(short_dir, monkeypatch):
    """The socket from ``bind_socket`` works with ``uvicorn.Server.run(sockets=...)``."""
    import uvicorn

    # The conftest network guard blocks every ``connect``; allow local Unix sockets only.
    guarded = socket.socket.connect

    def connect(self: socket.socket, address) -> None:  # noqa: ANN001
        if self.family != socket.AF_UNIX:
            return guarded(self, address)
        return _REAL_CONNECT(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    path = os.path.join(short_dir, "r.sock")
    sock = bind_socket(path)
    app = create_app(_factory(), UIDS, killer=lambda uid: 0)
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.02)
        with httpx.Client(transport=httpx.HTTPTransport(uds=path), base_url="http://runner") as c:
            assert c.post("/run", json={"code": "x"}).json()["ok"] is True
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()


# --- main() ------------------------------------------------------------------------------------


def test_main_builds_app_from_env_and_serves_the_socket(monkeypatch):
    seen: dict = {}

    class FakeServer:
        def __init__(self, config) -> None:
            seen["config"] = config
            self.should_exit = False

        def run(self, sockets=None) -> None:
            seen["sockets"] = sockets

    monkeypatch.setenv("EXECUTOR_WALL_TIMEOUT_S", "7")
    monkeypatch.setenv("EXECUTOR_CPU_SECONDS", "5")
    monkeypatch.setenv("EXECUTOR_MEM_MB", "128")
    monkeypatch.setenv("RUNNER_SLOTS", "1")
    monkeypatch.setattr(runner_server.uvicorn, "Server", FakeServer)
    monkeypatch.setattr(runner_server, "bind_socket", lambda path, gid=1500: f"sock:{path}:{gid}")
    runner_server.main()

    assert seen["sockets"] == ["sock:/run/fastpilot/runner.sock:1500"]
    app = seen["config"].app
    assert app.state.uids == [61001]
    ex = app.state.executor_factory(61001)
    assert (ex.wall_timeout_s, ex.cpu_seconds, ex.mem_bytes) == (7, 5, 128 * 1024 * 1024)
    assert (ex.sandbox_uid, ex.sandbox_gid) == (61001, 61001)


def test_watch_stops_server_once_ready():
    class S:
        should_exit = False

    s = S()
    calls = iter([False, False, True])
    runner_server._watch_for_exit(lambda: next(calls), s, interval_s=0.0)
    assert s.should_exit is True


def test_watch_ends_when_told_done():
    class S:
        should_exit = False

    s = S()
    done = threading.Event()
    done.set()
    runner_server._watch_for_exit(lambda: False, s, interval_s=0.0, done=done)
    assert s.should_exit is False
