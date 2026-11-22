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


_DEAD_STATES = ("Z", "X")  # zombie, dead


def _read_status(status_path: str) -> tuple[int | None, str | None]:
    """``(real uid, state letter)`` from a ``/proc`` status file; ``(None, None)`` if it can't be read."""
    uid: int | None = None
    state: str | None = None
    try:
        with open(status_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if line.startswith("State:"):
                    state = line.split()[1]
                elif line.startswith("Uid:"):
                    uid = int(line.split()[1])  # real, effective, saved, filesystem
    except (OSError, ValueError, IndexError):
        return None, None  # the process exited while we were looking, or the file is malformed
    return uid, state


def _has_live_thread(task_dir: str) -> bool:
    """True if any thread under ``/proc/<pid>/task`` is not a zombie or dead.

    The main thread shows ``Z`` after ``pthread_exit`` while other threads keep running, so the
    leader's own state is not enough. A missing task folder means the process is gone; any other
    error counts as live (fail closed).
    """
    try:
        tids = os.listdir(task_dir)
    except FileNotFoundError:
        return False
    except OSError:
        return True
    for tid in tids:
        _uid, state = _read_status(os.path.join(task_dir, tid, "status"))
        if state is not None and state not in _DEAD_STATES:
            return True
    return False


def _match(proc_root: str, pid: str, uid: int) -> tuple[bool, bool]:
    """``(owned by uid, still live)`` for one pid."""
    owner, state = _read_status(os.path.join(proc_root, pid, "status"))
    if owner != uid:
        return False, False
    if state not in _DEAD_STATES:
        return True, True
    return True, _has_live_thread(os.path.join(proc_root, pid, "task"))


def kill_uid_processes(
    uid: int,
    proc_root: str = "/proc",
    kill: Callable[[int, int], None] = os.kill,
    max_passes: int = MAX_KILL_PASSES,
    pause_s: float = 0.02,
) -> int:
    """Send ``SIGKILL`` to every process whose real uid is ``uid``; return how many live ones were found.

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
        found = 0  # live processes of the uid seen in this pass
        failed: list[int] = []
        for name in entries:
            if not name.isdigit():
                continue  # "self", "cpuinfo" and other non-process entries
            owned, live = _match(proc_root, name, uid)
            if not owned:
                continue
            # Signal zombies too: for a zombie leader with live threads this kills the whole thread
            # group; for a true zombie it simply succeeds. Only live ones keep the loop going.
            found += live
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


CLEAN_ROOTS = ["/tmp", "/dev/shm"]  # both writable in the runner container

# Runs as the slot uid (root in the runner has no DAC_OVERRIDE/FOWNER, so only the owner can delete).
# Removes every top-level entry of each root owned by that uid; symlinks are removed, never followed.
# A root that doesn't exist is skipped.
_CLEAN_SCRIPT = """
import os, shutil, stat, sys
uid, roots = int(sys.argv[1]), sys.argv[2:]
failed = 0
for root in roots:
    if not os.path.lexists(root):
        continue
    try:
        names = os.listdir(root)
    except OSError as exc:
        print(f"{root}: {exc}", file=sys.stderr)
        failed = 1
        continue
    for name in names:
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


def clean_uid_tmp(uid: int, gid: int | None = None, roots: list[str] | None = None) -> bool:
    """Delete every top-level entry owned by ``uid`` in each of ``roots`` (default ``/tmp`` and
    ``/dev/shm``), as that uid. A missing root is skipped. Never raises: returns False (and logs) if the
    child can't start, times out or exits non-zero, so the caller can hold the slot back.

    Runs after the killer, so no leftover process can recreate files. The user switch happens only
    when we are root (as in the runner container); otherwise the child runs as the current user.
    """
    gid = uid if gid is None else gid
    roots = list(CLEAN_ROOTS if roots is None else roots)
    drop = os.geteuid() == 0
    try:
        done = subprocess.run(
            [sys.executable, "-I", "-c", _CLEAN_SCRIPT, str(uid), *roots],
            user=uid if drop else None,
            group=gid if drop else None,
            extra_groups=[] if drop else None,
            timeout=5,
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("clean-up of %s as uid %s failed: %s", roots, uid, exc)
        return False
    if done.returncode != 0:
        logger.warning("clean-up of %s as uid %s failed: %s", roots, uid, done.stderr.strip()[-500:])
        return False
    return True


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
