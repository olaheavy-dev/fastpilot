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
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field

import httpx
import pytest
from fastapi.testclient import TestClient

from app.augmentations.code_executor import ExecutionResult
from runner import server as runner_server
from runner import slots as runner_slots
from runner.server import bind_socket, create_app
from runner.slots import KillerError, SlotPool, clean_uid_tmp, kill_uid_processes

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


@pytest.fixture(autouse=True)
def cleaned(monkeypatch) -> list:
    """Never let an app test delete real files in /tmp: record ``"clean <uid>"`` instead."""
    calls: list = []

    def fake(uid: int) -> bool:
        calls.append(f"clean {uid}")
        return True

    monkeypatch.setattr(runner_server, "clean_uid_tmp", fake)
    return calls


def _write_status(root, pid: str, uid: int) -> None:
    d = root / pid
    d.mkdir()
    (d / "status").write_text(f"Name:\tpython\nState:\tS (sleeping)\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")


# --- Leftover killer --------------------------------------------------------------------------


def _fake_kill(root, killed: list[int]):
    """A fake ``os.kill`` that records the pid and makes the process vanish from the fake /proc."""

    def kill(pid: int, sig: int) -> None:
        killed.append(pid)
        shutil.rmtree(root / str(pid), ignore_errors=True)

    return kill


def test_kill_uid_processes_kills_only_matching_uid(tmp_path):
    # fake /proc: pid 10 Uid 61001, pid 11 Uid 61002, pid 12 Uid 0, pid "self" ignored, pid 13 vanished
    _write_status(tmp_path, "10", 61001)
    _write_status(tmp_path, "11", 61002)
    _write_status(tmp_path, "12", 0)
    _write_status(tmp_path, "self", 61001)
    (tmp_path / "13").mkdir()  # the process exited between listing and reading: no status file
    (tmp_path / "cpuinfo").write_text("not a pid")
    killed: list[int] = []
    n = kill_uid_processes(61001, proc_root=str(tmp_path), kill=_fake_kill(tmp_path, killed), pause_s=0)
    assert n == 1 and killed == [10]


def _write_task(root, pid: str, tid: str, state: str, uid: int = 61001) -> None:
    d = root / pid / "task" / tid
    d.mkdir(parents=True)
    (d / "status").write_text(f"Name:\tpython\nState:\t{state}\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")


def _write_zombie_leader(root, pid: str, uid: int = 61001) -> None:
    (root / pid).mkdir()
    (root / pid / "status").write_text(f"Name:\tpython\nState:\tZ (zombie)\nUid:\t{uid}\t{uid}\t{uid}\t{uid}\n")


def test_kill_uid_processes_true_zombie_is_signalled_but_does_not_loop(tmp_path):
    # A real zombie (every thread dead, waiting to be reaped) stays in /proc whatever we send it.
    _write_zombie_leader(tmp_path, "14")
    _write_task(tmp_path, "14", "14", "Z (zombie)")
    killed: list[int] = []
    assert kill_uid_processes(61001, proc_root=str(tmp_path), kill=lambda p, s: killed.append(p), pause_s=0) == 0
    assert killed == [14]  # signalled once, then the loop ends


def test_kill_uid_processes_zombie_leader_with_live_thread_is_killed(tmp_path):
    # The main thread called pthread_exit (status shows Z) but another thread still runs as the uid.
    _write_zombie_leader(tmp_path, "15")
    _write_task(tmp_path, "15", "15", "Z (zombie)")
    _write_task(tmp_path, "15", "16", "S (sleeping)")
    killed: list[int] = []
    assert kill_uid_processes(61001, proc_root=str(tmp_path), kill=_fake_kill(tmp_path, killed), pause_s=0) == 1
    assert killed == [15]


def test_kill_uid_processes_zombie_leader_with_live_thread_that_survives_fails(tmp_path):
    _write_zombie_leader(tmp_path, "17")
    _write_task(tmp_path, "17", "17", "Z (zombie)")
    _write_task(tmp_path, "17", "18", "R (running)")
    with pytest.raises(KillerError, match="10 passes"):
        kill_uid_processes(61001, proc_root=str(tmp_path), kill=lambda p, s: None, pause_s=0)


def test_kill_uid_processes_zombie_without_task_dir_counts_as_gone(tmp_path):
    _write_zombie_leader(tmp_path, "19")  # the task folder vanished: the process was reaped meanwhile
    assert kill_uid_processes(61001, proc_root=str(tmp_path), kill=lambda p, s: None, pause_s=0) == 0


def test_kill_uid_processes_repeats_until_a_clean_pass(tmp_path):
    # Escaped code forks a new child just after the first scan: the next pass must catch it.
    _write_status(tmp_path, "10", 61001)
    killed: list[int] = []

    def kill(pid: int, sig: int) -> None:
        killed.append(pid)
        shutil.rmtree(tmp_path / str(pid))
        if pid == 10:
            _write_status(tmp_path, "30", 61001)

    assert kill_uid_processes(61001, proc_root=str(tmp_path), kill=kill, pause_s=0) == 2
    assert killed == [10, 30]


def test_kill_uid_processes_gives_up_after_max_passes(tmp_path):
    # A fork loop that always stays one step ahead: after 10 passes it counts as a failure.
    _write_status(tmp_path, "100", 61001)
    state = {"next": 101}

    def kill(pid: int, sig: int) -> None:
        shutil.rmtree(tmp_path / str(pid))
        _write_status(tmp_path, str(state["next"]), 61001)
        state["next"] += 1

    with pytest.raises(KillerError, match="10 passes"):
        kill_uid_processes(61001, proc_root=str(tmp_path), kill=kill, pause_s=0)
    assert state["next"] == 111  # exactly 10 passes


def test_kill_uid_processes_ignores_pid_that_vanishes_before_kill(tmp_path):
    _write_status(tmp_path, "20", 61001)
    _write_status(tmp_path, "21", 61001)
    killed: list[int] = []
    fake = _fake_kill(tmp_path, killed)

    def kill(pid: int, sig: int) -> None:
        if pid == 20:
            shutil.rmtree(tmp_path / "20")
            raise ProcessLookupError
        fake(pid, sig)

    assert kill_uid_processes(61001, proc_root=str(tmp_path), kill=kill, pause_s=0) == 2
    assert killed == [21]


def test_kill_uid_processes_permission_error_continues_then_fails(tmp_path):
    _write_status(tmp_path, "40", 61001)
    _write_status(tmp_path, "41", 61001)
    killed: list[int] = []
    fake = _fake_kill(tmp_path, killed)

    def kill(pid: int, sig: int) -> None:
        if pid == 40:
            raise PermissionError("no CAP_KILL")
        fake(pid, sig)

    with pytest.raises(KillerError, match="40"):
        kill_uid_processes(61001, proc_root=str(tmp_path), kill=kill, pause_s=0)
    assert killed == [41]  # the other pid was still killed


def test_kill_uid_processes_missing_proc_root_fails(tmp_path):
    # Not being able to look is not the same as "nothing left": fail closed.
    with pytest.raises(KillerError):
        kill_uid_processes(61001, proc_root=str(tmp_path / "nope"), kill=lambda p, s: None)


# --- Clean-up of the slot uid's files ---------------------------------------------------------


def test_clean_uid_tmp_removes_only_that_uids_entries(tmp_path):
    root = tmp_path / "tmp"
    root.mkdir()
    outside = tmp_path / "keep.txt"
    outside.write_text("not in tmp")
    (root / "a.txt").write_text("left behind")
    nested = root / "b" / "locked"
    nested.mkdir(parents=True)
    (nested / "f").write_text("x")
    nested.chmod(0o500)  # the owner can still chmod it back and delete it
    (root / "c").symlink_to(outside)
    assert clean_uid_tmp(os.getuid(), os.getgid(), roots=[str(root)]) is True
    assert list(root.iterdir()) == []
    assert outside.read_text() == "not in tmp"  # the symlink went, not its target


def test_clean_uid_tmp_leaves_other_uids_alone(tmp_path):
    (tmp_path / "a.txt").write_text("mine, not the slot's")
    assert clean_uid_tmp(os.getuid() + 1, os.getgid(), roots=[str(tmp_path)]) is True
    assert (tmp_path / "a.txt").exists()


def test_clean_uid_tmp_cleans_every_root_and_skips_a_missing_one(tmp_path):
    tmp, shm = tmp_path / "tmp", tmp_path / "shm"
    tmp.mkdir()
    shm.mkdir()
    (tmp / "a.txt").write_text("left in /tmp")
    (shm / "b.bin").write_text("left in /dev/shm")
    assert clean_uid_tmp(os.getuid(), os.getgid(), roots=[str(tmp), str(tmp_path / "missing"), str(shm)]) is True
    assert list(tmp.iterdir()) == [] and list(shm.iterdir()) == []


def test_clean_uid_tmp_default_roots_are_tmp_and_dev_shm(monkeypatch):
    seen: dict = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(runner_slots.subprocess, "run", fake_run)
    clean_uid_tmp(61001)
    assert seen["cmd"][-3:] == ["61001", "/tmp", "/dev/shm"]


def test_clean_uid_tmp_logs_and_never_raises(tmp_path, caplog):
    not_a_folder = tmp_path / "file"
    not_a_folder.write_text("x")
    assert clean_uid_tmp(os.getuid(), os.getgid(), roots=[str(not_a_folder)]) is False
    assert "clean-up" in caplog.text


def test_clean_uid_tmp_logs_when_the_child_cannot_start(tmp_path, monkeypatch, caplog):
    def boom(*a, **k):
        raise OSError("cannot switch user")

    monkeypatch.setattr(runner_slots.subprocess, "run", boom)
    assert clean_uid_tmp(os.getuid(), os.getgid(), roots=[str(tmp_path)]) is False
    assert "cannot switch user" in caplog.text


def test_clean_uid_tmp_timeout_is_a_failure(tmp_path, monkeypatch, caplog):
    def slow(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw["timeout"])

    monkeypatch.setattr(runner_slots.subprocess, "run", slow)
    assert clean_uid_tmp(61001, roots=[str(tmp_path)]) is False
    assert "clean-up" in caplog.text


def test_clean_uid_tmp_switches_user_when_root(tmp_path, monkeypatch):
    seen: dict = {}

    def fake_run(cmd, **kw):
        seen.update(kw)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(runner_slots.os, "geteuid", lambda: 0)
    monkeypatch.setattr(runner_slots.subprocess, "run", fake_run)
    assert clean_uid_tmp(61001, 61001, roots=[str(tmp_path)]) is True
    assert (seen["user"], seen["group"], seen["extra_groups"], seen["timeout"]) == (61001, 61001, [], 5)


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


def test_order_is_run_kill_clean_release(cleaned):
    events = cleaned  # the fake cleaner records into the same list

    class Ex:
        def run(self, code: str) -> ExecutionResult:
            events.append("run")
            return ExecutionResult(0, "", "", 1)

    app = create_app(lambda uid: Ex(), [61001], killer=lambda uid: events.append(f"kill {uid}"))
    TestClient(app).post("/run", json={"code": "x"})
    assert events == ["run", "kill 61001", "clean 61001"]


@pytest.mark.parametrize("error", [PermissionError("no CAP_KILL"), KillerError("still forking after 10 passes")])
def test_killer_failure_holds_the_slot_back_and_restarts(error, cleaned):
    def bad_killer(uid: int) -> int:
        raise error

    app = create_app(_factory(), UIDS, killer=bad_killer)
    client = TestClient(app)
    assert client.post("/run", json={"code": "x"}).json()["ok"] is True  # the code itself ran fine
    assert app.state.should_exit is True
    assert client.get("/health").json()["slots_free"] == 1  # that slot never goes back to the pool
    assert app.state.ready_to_exit() is True  # a held-back slot doesn't block the restart
    assert cleaned == []  # no clean-up as a uid that may still have live processes
    body = client.post("/run", json={"code": "y"}).json()
    assert body["unavailable"] is True and body["stderr"] == "[runner] restarting"


@pytest.mark.parametrize("outcome", ["false", "raises"])
def test_cleanup_failure_holds_the_slot_back_and_restarts(outcome):
    def bad_cleaner(uid: int) -> bool:
        if outcome == "raises":
            raise RuntimeError("boom")
        return False  # the child timed out or exited non-zero

    app = create_app(_factory(), UIDS, killer=lambda uid: 0, cleaner=bad_cleaner)
    client = TestClient(app)
    assert client.post("/run", json={"code": "x"}).json()["ok"] is True
    assert app.state.should_exit is True
    assert client.get("/health").json()["slots_free"] == 1
    assert app.state.ready_to_exit() is True
    body = client.post("/run", json={"code": "y"}).json()
    assert body["unavailable"] is True and body["stderr"] == "[runner] restarting"


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


async def test_requests_after_should_exit_get_restarting_and_restart_is_not_delayed():
    tracker: dict = {}

    def factory(uid: int) -> FakeExecutor:
        return FakeExecutor(uid, delay_s=0.4 if uid == 61001 else 0.0, tracker=tracker)

    app = create_app(factory, UIDS, max_runs=1, killer=lambda uid: 0)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://runner") as client:
        slow = asyncio.create_task(client.post("/run", json={"code": "slow"}))
        await asyncio.sleep(0.05)
        assert (await client.post("/run", json={"code": "quick"})).json()["ok"] is True  # runs == max_runs now
        # A steady stream keeps arriving: none of it takes a slot, so it can't put off the restart.
        stream = await asyncio.gather(*(client.post("/run", json={"code": str(i)}) for i in range(5)))
        for r in stream:
            body = r.json()
            assert r.status_code == 200 and body["unavailable"] is True
            assert body["exit_code"] == -1 and body["stderr"] == "[runner] restarting"
        assert app.state.ready_to_exit() is False
        await slow
    assert app.state.ready_to_exit() is True
    assert tracker["uids"].count(61002) == 1  # the stream never ran


async def test_request_waiting_for_a_slot_gets_restarting_once_should_exit_is_set():
    app = create_app(_factory(delay_s=0.3), [61001], max_runs=1, killer=lambda uid: 0)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://runner") as client:
        first, second = await asyncio.gather(
            client.post("/run", json={"code": "a"}), client.post("/run", json={"code": "b"})
        )
    assert first.json()["ok"] is True
    assert second.json()["stderr"] == "[runner] restarting"
    assert app.state.ready_to_exit() is True


async def test_waiter_wakes_when_every_slot_is_held_back():
    # The only slot is held back after a failed kill: a waiting request must not hang the shutdown.
    def bad_killer(uid: int) -> int:
        raise KillerError("boom")

    app = create_app(_factory(delay_s=0.2), [61001], killer=bad_killer)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://runner") as client:
        first, second = await asyncio.wait_for(
            asyncio.gather(client.post("/run", json={"code": "a"}), client.post("/run", json={"code": "b"})), 3
        )
    assert first.json()["ok"] is True
    assert second.json()["stderr"] == "[runner] restarting"


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
