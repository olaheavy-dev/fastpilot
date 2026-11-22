"""The runner's HTTP app, served on a Unix socket that our own code binds.

``POST /run`` takes a free slot (or waits for one) and runs the code there with that slot's uid. Then,
always: kill every process left behind by that uid (looped), delete that uid's files in ``/tmp`` and
``/dev/shm`` as that uid, and give the slot back. If the kill or the clean-up fails, the slot is held
back and the runner restarts (fail closed). After ``max_runs`` runs or ``max_age_s`` seconds, new
requests get a "restarting" answer, the runs in flight finish, and the runner exits with code 0, so
Docker's ``restart: always`` starts a clean container.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import os
import socket
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

from app.augmentations.code_executor import ExecutionResult, SubprocessExecutor
from runner.slots import SlotPool, clean_uid_tmp, kill_uid_processes

logger = logging.getLogger(__name__)

SLOT_UIDS = [61001, 61002]
SOCKET_PATH = "/run/fastpilot/runner.sock"
SOCKET_GID = 1500


class Executor(Protocol):
    def run(self, code: str) -> ExecutionResult: ...


class RunRequest(BaseModel):
    code: str


def _result_json(result: ExecutionResult) -> dict[str, Any]:
    return {**dataclasses.asdict(result), "ok": result.ok}


def _restarting() -> dict[str, Any]:
    return _result_json(ExecutionResult(-1, "", "[runner] restarting", 0, unavailable=True))


def create_app(
    executor_factory: Callable[[int], Executor],
    uids: list[int],
    max_runs: int = 200,
    max_age_s: int = 21600,
    killer: Callable[[int], Any] = kill_uid_processes,
    cleaner: Callable[[int], Any] | None = None,
) -> FastAPI:
    """Build the runner app. ``cleaner`` defaults to ``clean_uid_tmp`` (looked up at call time)."""
    app = FastAPI(title="FastPilot runner", docs_url=None, redoc_url=None, openapi_url=None)
    pool = SlotPool(uids)
    started = time.monotonic()
    app.state.uids = list(uids)
    app.state.executor_factory = executor_factory
    app.state.runs = 0
    app.state.in_flight = 0
    app.state.held_back: list[int] = []  # slots whose leftovers could not be killed: never reused
    app.state.should_exit = False

    def _check_restart() -> None:
        if app.state.runs >= max_runs or time.monotonic() - started >= max_age_s:
            app.state.should_exit = True

    def ready_to_exit() -> bool:
        """True once the restart rule has fired and no run is in flight (held-back slots don't count)."""
        _check_restart()
        return app.state.should_exit and app.state.in_flight == 0

    app.state.ready_to_exit = ready_to_exit

    async def _take_slot() -> int | None:
        """A free slot uid, or ``None`` once the runner is restarting (also wakes requests that wait)."""
        while not app.state.should_exit:
            try:
                return await asyncio.wait_for(pool.acquire(), timeout=0.1)
            except TimeoutError:
                _check_restart()
        return None

    async def _kill_and_clean(uid: int) -> bool:
        """Kill the slot uid's leftovers, then delete its files as that uid. False if either failed."""
        try:
            await asyncio.to_thread(killer, uid)
        except Exception:
            logger.exception("leftover killer failed for slot %s; holding the slot back and restarting", uid)
            return False
        clean = cleaner if cleaner is not None else clean_uid_tmp
        try:
            cleaned = await asyncio.to_thread(clean, uid)
        except Exception:
            logger.exception("clean-up failed for slot %s; holding the slot back and restarting", uid)
            return False
        if not cleaned:  # timed out or exited non-zero: the uid's files may still be there
            logger.error("clean-up failed for slot %s; holding the slot back and restarting", uid)
            return False
        return True

    @app.post("/run")
    async def run(req: RunRequest) -> dict[str, Any]:
        uid = await _take_slot()
        if uid is None:
            return _restarting()
        if app.state.should_exit:  # the restart rule fired while this request waited
            pool.release(uid)
            return _restarting()
        app.state.in_flight += 1
        safe = False
        try:
            try:
                result = await asyncio.to_thread(executor_factory(uid).run, req.code)
            except Exception:
                logger.exception("executor failed in slot %s", uid)
                result = ExecutionResult(-1, "", "[runner] internal error", 0, unavailable=True)
            finally:
                safe = await _kill_and_clean(uid)
        finally:
            app.state.in_flight -= 1
            app.state.runs += 1
            if safe:
                pool.release(uid)
            else:  # fail closed: this uid may still have live processes
                app.state.held_back.append(uid)
                app.state.should_exit = True
            _check_restart()
        return _result_json(result)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "runs": app.state.runs, "slots_free": pool.free}

    return app


def bind_socket(path: str, gid: int = SOCKET_GID) -> socket.socket:
    """Bind a Unix socket at ``path`` with mode ``0660`` (owner root, group ``gid`` when root).

    Binding it ourselves matters: ``uvicorn --uds`` sets a new socket to ``0666``, which would let
    escaped sandbox code connect. As root, the parent folder is set to ``root:root`` ``0755`` so slot
    uids cannot delete or replace the socket.
    """
    parent = os.path.dirname(path) or "."
    is_root = os.geteuid() == 0
    if is_root:
        os.chown(parent, 0, 0)
        os.chmod(parent, 0o755)
    try:
        os.unlink(path)  # a stale socket (or any file) from an earlier run
    except FileNotFoundError:
        pass
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(path)
        os.chmod(path, 0o660)
        if is_root:
            os.chown(path, 0, gid)
    except BaseException:
        sock.close()
        raise
    return sock  # uvicorn (asyncio ``create_server(sock=...)``) calls ``listen`` itself


def _watch_for_exit(
    ready: Callable[[], bool], server: Any, interval_s: float = 1.0, done: threading.Event | None = None
) -> None:
    """Poll ``ready`` and stop the server once it is true. Runs in a daemon thread; ``done`` ends it early."""
    done = done or threading.Event()
    while not ready():
        if done.wait(interval_s):
            return
    logger.info("restart rule reached and no run in flight; stopping the runner")
    server.should_exit = True


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    return int(raw) if raw else default


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    wall = _env_int("EXECUTOR_WALL_TIMEOUT_S", 15)
    cpu = _env_int("EXECUTOR_CPU_SECONDS", 10)
    mem = _env_int("EXECUTOR_MEM_MB", 256)
    slots = max(1, min(_env_int("RUNNER_SLOTS", 2), len(SLOT_UIDS)))

    def factory(uid: int) -> SubprocessExecutor:
        return SubprocessExecutor(
            wall_timeout_s=wall, cpu_seconds=cpu, mem_mb=mem, sandbox_uid=uid, sandbox_gid=uid
        )

    app = create_app(factory, SLOT_UIDS[:slots])
    server = uvicorn.Server(uvicorn.Config(app, log_level="info", lifespan="off", timeout_graceful_shutdown=wall + 15))
    sock = bind_socket(SOCKET_PATH, gid=SOCKET_GID)
    done = threading.Event()
    watcher = threading.Thread(
        target=_watch_for_exit, args=(app.state.ready_to_exit, server), kwargs={"done": done}, daemon=True
    )
    watcher.start()
    try:
        server.run(sockets=[sock])
    finally:
        done.set()


if __name__ == "__main__":  # pragma: no cover
    main()
