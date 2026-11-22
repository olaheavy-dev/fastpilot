"""Run slots (one uid each) and the leftover-process killer."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import subprocess
import sys
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


MAX_KILL_PASSES = 10


class KillerError(RuntimeError):
    """The slot's uid may still have live processes: the slot must not be used again."""


def _live_uid(status_path: str) -> int | None:
    """The real uid of a live process from its ``/proc/<pid>/status``.

    ``None`` when the file can't be read (the process has exited) or the process is a zombie or dead:
    it can't run code any more and can't be killed again (nobody reaps orphans in the container).
    """
    try:
        with open(status_path, encoding="utf-8", errors="replace") as fh:
            uid: int | None = None
            for line in fh:
                if line.startswith("State:") and line.split()[1:2] in (["Z"], ["X"]):
                    return None
                if line.startswith("Uid:"):
                    uid = int(line.split()[1])  # real, effective, saved, filesystem
            return uid
    except (OSError, ValueError, IndexError):
        return None  # the process exited while we were looking, or the file is malformed


def kill_uid_processes(
    uid: int,
    proc_root: str = "/proc",
    kill: Callable[[int, int], None] = os.kill,
    max_passes: int = MAX_KILL_PASSES,
    pause_s: float = 0.02,
) -> int:
    """Send ``SIGKILL`` to every live process whose real uid is ``uid``; return how many were found.

    One pass is not enough: escaped code can fork a new child just after the list is read. So the
    scan repeats until a pass finds nothing. Raises ``KillerError`` (fail closed) if ``proc_root``
    can't be listed, if any pid can't be signalled, or if processes are still found after
    ``max_passes`` passes. Pids that vanish before the kill are ignored.
    """
    total = 0
    for _ in range(max_passes):
        try:
            entries = os.listdir(proc_root)
        except OSError as exc:
            raise KillerError(f"cannot list {proc_root}: {exc}") from exc
        found = 0
        failed: list[int] = []
        for name in entries:
            if not name.isdigit():
                continue  # "self", "cpuinfo" and other non-process entries
            if _live_uid(os.path.join(proc_root, name, "status")) != uid:
                continue
            found += 1
            try:
                kill(int(name), signal.SIGKILL)
            except ProcessLookupError:
                continue
            except PermissionError:
                failed.append(int(name))
        total += found
        if failed:
            raise KillerError(f"cannot signal pid(s) {failed} of uid {uid}")
        if not found:
            if total:
                logger.info("killed %d leftover process(es) for uid %s", total, uid)
            return total
        if pause_s:
            time.sleep(pause_s)  # give killed processes a moment to leave /proc
    raise KillerError(f"uid {uid} still had live processes after {max_passes} passes")


# Runs as the slot uid (root in the runner has no DAC_OVERRIDE/FOWNER, so only the owner can delete).
# Removes every top-level entry of the folder owned by that uid; symlinks are removed, never followed.
_CLEAN_SCRIPT = """
import os, shutil, stat, sys
root, uid = sys.argv[1], int(sys.argv[2])
failed = 0
for name in os.listdir(root):
    path = os.path.join(root, name)
    try:
        st = os.lstat(path)
        if st.st_uid != uid:
            continue
        if stat.S_ISDIR(st.st_mode):
            os.chmod(path, 0o700)
            for top, dirs, _files in os.walk(path):
                for d in dirs:
                    sub = os.path.join(top, d)
                    if not os.path.islink(sub):
                        os.chmod(sub, 0o700)  # the owner can always open its own folders again
            shutil.rmtree(path)
        else:
            os.unlink(path)
    except OSError as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        failed = 1
sys.exit(failed)
"""


def clean_uid_tmp(uid: int, gid: int | None = None, tmp_root: str = "/tmp") -> None:
    """Delete every top-level entry in ``tmp_root`` owned by ``uid``, as that uid. Logs, never raises.

    Runs after the killer, so no leftover process can recreate files. The user switch happens only
    when we are root (as in the runner container); otherwise the child runs as the current user.
    """
    gid = uid if gid is None else gid
    drop = os.geteuid() == 0
    try:
        done = subprocess.run(
            [sys.executable, "-I", "-c", _CLEAN_SCRIPT, tmp_root, str(uid)],
            user=uid if drop else None,
            group=gid if drop else None,
            extra_groups=[] if drop else None,
            timeout=5,
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("clean-up of %s as uid %s failed: %s", tmp_root, uid, exc)
        return
    if done.returncode != 0:
        logger.warning("clean-up of %s as uid %s failed: %s", tmp_root, uid, done.stderr.strip()[-500:])


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
