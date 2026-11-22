"""Run slots (one uid each) and the leftover-process killer."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from collections.abc import Callable

logger = logging.getLogger(__name__)


def _real_uid(status_path: str) -> int | None:
    """The real uid from a ``/proc/<pid>/status`` file, or ``None`` if it can't be read."""
    try:
        with open(status_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("Uid:"):
                    return int(line.split()[1])  # real, effective, saved, filesystem
    except (OSError, ValueError, IndexError):
        return None  # the process exited while we were looking, or the line is malformed
    return None


def kill_uid_processes(
    uid: int,
    proc_root: str = "/proc",
    kill: Callable[[int, int], None] = os.kill,
) -> int:
    """Send ``SIGKILL`` to every process whose real uid is ``uid``; return how many were signalled.

    Pids that vanish between the listing and the kill are ignored.
    """
    try:
        entries = os.listdir(proc_root)
    except OSError:
        logger.warning("cannot list %s; no leftover processes killed for uid %s", proc_root, uid)
        return 0
    count = 0
    for name in entries:
        if not name.isdigit():
            continue  # "self", "cpuinfo" and other non-process entries
        if _real_uid(os.path.join(proc_root, name, "status")) != uid:
            continue
        try:
            kill(int(name), signal.SIGKILL)
        except ProcessLookupError:
            continue
        count += 1
    if count:
        logger.info("killed %d leftover process(es) for uid %s", count, uid)
    return count


class SlotPool:
    """A queue of free slot uids. ``acquire`` waits until one is free."""

    def __init__(self, uids: list[int]) -> None:
        self.uids = list(uids)
        self._free: asyncio.Queue[int] = asyncio.Queue()
        for uid in self.uids:
            self._free.put_nowait(uid)

    @property
    def free(self) -> int:
        return self._free.qsize()

    @property
    def busy(self) -> int:
        return len(self.uids) - self.free

    async def acquire(self) -> int:
        return await self._free.get()

    def release(self, uid: int) -> None:
        self._free.put_nowait(uid)
