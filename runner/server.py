"""The runner's HTTP app, served on a Unix socket that our own code binds.

``POST /run`` takes a free slot (or waits for one), runs the code there with that slot's uid, then
always kills every process left behind by that uid and gives the slot back. After ``max_runs`` runs or
``max_age_s`` seconds, the runner finishes its current runs and exits with code 0, so Docker's
``restart: always`` starts a clean container.
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
from runner.slots import SlotPool, kill_uid_processes

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


def create_app(
    executor_factory: Callable[[int], Executor],
    uids: list[int],
    max_runs: int = 200,
    max_age_s: int = 21600,
    killer: Callable[[int], Any] = kill_uid_processes,
) -> FastAPI:
    app = FastAPI(title="FastPilot runner", docs_url=None, redoc_url=None, openapi_url=None)
    pool = SlotPool(uids)
    started = time.monotonic()
    app.state.uids = list(uids)
    app.state.executor_factory = executor_factory
    app.state.runs = 0
    app.state.should_exit = False

    def _check_restart() -> None:
        if app.state.runs >= max_runs or time.monotonic() - started >= max_age_s:
            app.state.should_exit = True

    def ready_to_exit() -> bool:
        """True once the restart rule has fired and no slot is busy."""
        _check_restart()
        return app.state.should_exit and pool.busy == 0

    app.state.ready_to_exit = ready_to_exit

    @app.post("/run")
    async def run(req: RunRequest) -> dict[str, Any]:
        uid = await pool.acquire()
        try:
            result = await asyncio.to_thread(executor_factory(uid).run, req.code)
        except Exception:
            logger.exception("executor failed in slot %s", uid)
            result = ExecutionResult(-1, "", "[runner] internal error", 0, unavailable=True)
        finally:
            try:
                await asyncio.to_thread(killer, uid)
            except Exception:
                logger.exception("leftover killer failed for slot %s", uid)
            finally:
                pool.release(uid)
                app.state.runs += 1
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
    server = uvicorn.Server(uvicorn.Config(app, log_level="info", lifespan="off"))
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
