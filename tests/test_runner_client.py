"""RunnerClient against a real runner app on a real Unix socket (short /tmp path: AF_UNIX limit)."""

from __future__ import annotations

import shutil
import socket
import tempfile
import threading
import time

import pytest
import uvicorn

from app.augmentations.code_executor import ExecutionResult
from app.augmentations.runner_client import RunnerClient
from runner.server import bind_socket, create_app


class _Exec:
    def __init__(self, uid: int, stdout: str = "hi", delay_s: float = 0.0):
        self.uid, self.stdout, self.delay_s = uid, stdout, delay_s

    def run(self, code: str) -> ExecutionResult:
        time.sleep(self.delay_s)
        return ExecutionResult(0, self.stdout, "", 5)


def _serve(stdout: str = "hi", delay_s: float = 0.0):
    d = tempfile.mkdtemp(dir="/tmp")
    path = f"{d}/r.sock"
    sock = bind_socket(path)
    app = create_app(
        lambda uid: _Exec(uid, stdout, delay_s), [61001], killer=lambda uid: 0, cleaner=lambda uid: True
    )
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    try:
        yield path
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def runner_socket():
    yield from _serve()


@pytest.fixture
def slow_runner_socket():
    yield from _serve(delay_s=2.0)


@pytest.fixture
def odd_runner_socket():
    yield from _serve(stdout="a\x00�" * 7000)


def test_client_runs_code_through_runner(runner_socket):
    r = RunnerClient(runner_socket, 5).run("print('hi')")
    assert r.exit_code == 0 and r.stdout == "hi" and not r.unavailable


def test_client_health(runner_socket):
    assert RunnerClient(runner_socket, 5).is_healthy() is True


def test_client_missing_socket_is_unavailable(tmp_path):
    client = RunnerClient(str(tmp_path / "none.sock"), 1)
    r = client.run("x")
    assert r.unavailable and r.exit_code == -1 and r.stderr == "[sandbox] code runner unavailable"
    assert client.is_healthy() is False


def test_client_timeout_is_unavailable(slow_runner_socket):
    r = RunnerClient(slow_runner_socket, 0.5).run("x")
    assert r.unavailable


def test_client_round_trips_large_and_odd_output(odd_runner_socket):
    r = RunnerClient(odd_runner_socket, 5).run("x")
    assert r.stdout == "a\x00�" * 7000 and len(r.stdout) == 21_000 and not r.unavailable


def test_client_bad_json_is_unavailable(runner_socket, monkeypatch):
    client = RunnerClient(runner_socket, 5)
    monkeypatch.setattr(client._client, "post", lambda *a, **k: type("R", (), {
        "raise_for_status": lambda s: None, "json": lambda s: {"nope": 1}})())
    assert client.run("x").unavailable


def test_get_executor_returns_runner_client_in_runner_mode(monkeypatch):
    import app.augmentations.code_executor as ce
    import app.config as cfg

    cfg.get_settings.cache_clear()
    s = cfg.get_settings()
    monkeypatch.setattr(s, "executor_mode", "runner")
    monkeypatch.setattr(s, "runner_socket", "/nonexistent.sock")
    monkeypatch.setattr(ce, "_executor", None)
    ex = ce.get_executor()
    assert isinstance(ex, RunnerClient) and ex.timeout_s == s.executor_wall_timeout_s + 15
    assert ex.max_in_flight == s.runner_max_in_flight == 3
    monkeypatch.setattr(ce, "_executor", None)
    cfg.get_settings.cache_clear()


def _blocking_post(started: threading.Event, release: threading.Event, calls: list):
    def post(*a, **k):
        calls.append(1)
        started.set()
        release.wait(5)
        return type("R", (), {"raise_for_status": lambda s: None, "json": lambda s: {
            "exit_code": 0, "stdout": "ok", "stderr": "", "duration_ms": 1}})()
    return post


def test_client_returns_busy_at_once_when_in_flight_limit_is_reached(monkeypatch):
    client = RunnerClient("/nonexistent.sock", 5, max_in_flight=1)
    started, release, calls = threading.Event(), threading.Event(), []
    monkeypatch.setattr(client._client, "post", _blocking_post(started, release, calls))
    results: list = []
    t = threading.Thread(target=lambda: results.append(client.run("a")))
    t.start()
    assert started.wait(5)
    t0 = time.monotonic()
    r = client.run("b")
    assert time.monotonic() - t0 < 0.5
    assert r.unavailable and r.exit_code == -1 and r.stderr == "[sandbox] code runner busy"
    assert len(calls) == 1  # the busy call made no HTTP request
    release.set()
    t.join(5)
    assert results[0].stdout == "ok"
    assert client.run("c").stdout == "ok"  # the slot was given back
    assert len(calls) == 2


def test_client_releases_in_flight_slot_after_an_error(monkeypatch):
    import httpx

    client = RunnerClient("/nonexistent.sock", 5, max_in_flight=1)
    calls: list = []

    def failing(*a, **k):
        calls.append(1)
        raise httpx.ConnectError("down")

    monkeypatch.setattr(client._client, "post", failing)
    assert client.run("a").stderr == "[sandbox] code runner unavailable"
    assert client.run("b").stderr == "[sandbox] code runner unavailable"  # not "busy"
    assert len(calls) == 2


def test_client_releases_in_flight_slot_after_an_unexpected_error(monkeypatch):
    client = RunnerClient("/nonexistent.sock", 5, max_in_flight=1)

    def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr(client._client, "post", boom)
    with pytest.raises(RuntimeError):
        client.run("a")
    monkeypatch.setattr(client._client, "post", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    assert client.run("b").stderr == "[sandbox] code runner unavailable"


def test_gate_turns_flags_off_when_local_not_allowed():
    from types import SimpleNamespace

    from app.main import apply_execution_gate

    s = SimpleNamespace(executor_mode="local", allow_local_executor=False, playground_enabled=True, agent_enabled=True)
    assert apply_execution_gate(s) is True
    assert s.playground_enabled is False and s.agent_enabled is False


def test_gate_leaves_flags_in_runner_mode():
    from types import SimpleNamespace

    from app.main import apply_execution_gate

    s = SimpleNamespace(executor_mode="runner", allow_local_executor=False, playground_enabled=True, agent_enabled=True)
    assert apply_execution_gate(s) is False
    assert s.playground_enabled is True and s.agent_enabled is True


def test_guard_still_blocks_inet_connect():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="Network access blocked"):
            s.connect(("127.0.0.1", 9))
    finally:
        s.close()


def test_settings_runner_socket_matches_runner_default():
    from app.config import Settings
    from runner.server import SOCKET_PATH

    assert Settings().runner_socket == SOCKET_PATH


def test_settings_rejects_invalid_executor_mode(monkeypatch):
    from pydantic import ValidationError

    from app.config import Settings

    monkeypatch.setenv("EXECUTOR_MODE", "runnner")
    with pytest.raises(ValidationError):
        Settings()


def test_gate_logs_error_when_it_turns_flags_off(caplog):
    from types import SimpleNamespace

    from app.main import apply_execution_gate

    s = SimpleNamespace(executor_mode="local", allow_local_executor=False, playground_enabled=True, agent_enabled=False)
    with caplog.at_level("DEBUG"):
        assert apply_execution_gate(s) is True
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_gate_silent_when_both_flags_already_off(caplog):
    from types import SimpleNamespace

    from app.main import apply_execution_gate

    s = SimpleNamespace(
        executor_mode="local", allow_local_executor=False, playground_enabled=False, agent_enabled=False
    )
    with caplog.at_level("DEBUG"):
        assert apply_execution_gate(s) is False
    assert not caplog.records
