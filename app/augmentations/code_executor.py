"""Sandboxed code executor (D6) — the one net-new piece with no class equivalent.

Runs agent-generated / user FastAPI code with layered defenses:
  1. AST pre-scan           — an import *allowlist* (fastapi, pydantic and a safe slice of the
                              stdlib; everything else is rejected), plus a denylist of reflection
                              routes: dunder names/attributes, the eval/open/getattr builtins
                              wherever they appear, attribute names that lead to dangerous
                              modules (``typing.sys``, ``asyncio.subprocess``, ``logging.os``) and
                              string constants that themselves parse as dangerous code (FastAPI
                              and pydantic evaluate string annotations / ``ImportString``).
  2. Subprocess isolation   — a separate ``python -I`` process in a fresh temp dir, scrubbed env
                              (no API keys), own process group.
  3. Privilege drop         — ONLY when the server runs as root (the Docker image does): the
                              child runs as ``nobody`` (via Popen ``user=``/``group=``), so it
                              cannot read the server's ``/proc/<pid>/environ``. As non-root
                              (local dev) there is no drop and a warning is logged.
  4. Resource limits        — RLIMIT_CPU / RLIMIT_AS / RLIMIT_FSIZE via preexec_fn.
  5. Wall-clock timeout     — killpg the whole group on overrun.
  6. Network guard          — a prelude patches ``socket`` methods to raise. A convenience against
                              accidental network use only: escaped code can open raw sockets.

The static scan is a FILTER, NOT A SECURITY BOUNDARY. Known, confirmed bypass: a string built at
run time and used as a type annotation is evaluated by FastAPI/pydantic as code, and no static scan
can see it (``test_runtime_built_annotation_is_not_caught_by_scan`` pins this). Escaped code can run
a shell, read world-readable files and use the network. The boundary is OS isolation: the planned
runner sidecar (no secrets, internal-only network, read-only filesystem). Until it ships, keep
``AGENT_ENABLED`` and ``PLAYGROUND_ENABLED`` off on any public host.

The generated code self-verifies in-process with ``fastapi.testclient.TestClient`` (D7),
so "running" never binds a port and stdout is a clean request/response log.
"""

from __future__ import annotations

import ast
import logging
import os
import resource
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# --- AST scan -------------------------------------------------------------
# Top-level modules a self-contained FastAPI example may import. Deliberately excludes os, sys,
# pathlib, io, subprocess, socket, importlib, inspect, operator (attrgetter = getattr by string),
# string (Formatter.get_field = getattr by string) and anything that touches files or processes.
_ALLOWED_IMPORTS = frozenset(
    {
        "__future__", "fastapi", "starlette", "pydantic", "pydantic_core", "annotated_types",
        "typing", "typing_extensions", "dataclasses", "enum", "abc", "datetime", "time", "zoneinfo",
        "json", "uuid", "decimal", "fractions", "math", "statistics", "random", "re", "collections",
        "functools", "itertools", "copy", "contextlib", "asyncio", "http", "base64", "hashlib",
        "hmac", "secrets", "textwrap", "ipaddress", "logging", "warnings",
    }
)
# eval/exec/compile/__import__ run arbitrary code; getattr & co. reach objects by *string*,
# sidestepping the name-based scan; open is file access. Denied as names *and* attributes, in any
# context — so `e = eval`, `__builtins__.eval` and `io.open` are all caught, not only direct calls.
_DENIED_BUILTINS = frozenset(
    {
        "eval", "exec", "compile", "__import__", "getattr", "setattr", "delattr", "vars", "globals",
        "locals", "breakpoint", "open",
    }
)
# Attribute names that lead from an allowed module to a dangerous one (``typing.sys``,
# ``logging.os``, ``asyncio.subprocess``), run processes, walk frames to reach globals, or load
# code by string (pydantic's ``ImportString``/``import_string``).
_DENIED_ATTRS = frozenset(
    {
        "os", "sys", "posix", "nt", "subprocess", "builtins", "importlib", "modules", "pathlib",
        "shutil", "socket", "_socket", "ctypes", "signal", "resource", "pty", "mmap",
        "popen", "fork", "forkpty", "environ", "getenv", "putenv",
        "execl", "execle", "execlp", "execlpe", "execv", "execve", "execvp", "execvpe",
        "spawnl", "spawnle", "spawnlp", "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
        "posix_spawn", "posix_spawnp", "create_subprocess_exec", "create_subprocess_shell",
        "open_code", "FileIO", "f_globals", "f_locals", "f_builtins", "f_back", "f_code",
        "gi_frame", "cr_frame", "ag_frame", "tb_frame", "tb_next", "ImportString", "import_string",
        "v1", "load_module", "exec_module", "get_data",
        # asyncio's event loop can start processes and open raw network endpoints directly.
        "subprocess_shell", "subprocess_exec", "getaddrinfo", "getnameinfo", "create_connection",
        "create_datagram_endpoint", "create_server", "create_unix_server", "create_unix_connection",
        "open_connection", "open_unix_connection", "start_server", "start_unix_server", "sock_connect",
        "sock_sendto", "SocketType",
        # File serving / reading helpers in starlette + fastapi, and logging's config-by-dict loader.
        "FileResponse", "StaticFiles", "dictConfig", "fileConfig",
    }
)
# `re.compile(...)` is everyday code, so the compile *builtin* is denied only as a bare name.
_DENIED_ATTRS = _DENIED_ATTRS | (_DENIED_BUILTINS - {"compile"})
# Submodules of allowed packages that reach processes, files, the network or code-by-config.
_DENIED_MODULES = frozenset(
    {
        "logging.config", "logging.handlers", "asyncio.subprocess", "asyncio.base_subprocess",
        "asyncio.unix_events", "http.server", "http.client", "http.cookiejar", "starlette.config",
        "starlette.staticfiles", "fastapi.staticfiles", "pydantic.v1",
    }
)
# Dunder names with a legitimate use in an example (`if __name__ == "__main__":`).
_ALLOWED_DUNDER_NAMES = frozenset({"__name__", "__main__", "__doc__", "__file__"})
# Dunder attributes everyday code reads: `super().__init__(...)`, `type(exc).__name__`, `f.__doc__`.
_ALLOWED_DUNDER_ATTRS = frozenset({"__init__", "__name__", "__qualname__", "__doc__"})
_MAX_STRING_DEPTH = 3

# Prepended by the executor (never scanned): imports socket itself, which user code may not.
# Its names are dunders so user code (which may not reference dunder names) cannot reach them.
# This is a convenience guard against accidental network use, not a security control: a process
# that escapes the scan can open raw sockets. Real network isolation needs OS isolation.
_NET_PRELUDE = (
    "import socket as __fp_sock__\n"
    "def __fp_no_net__(*a, **k):\n"
    "    raise OSError('network access is disabled in the FastPilot sandbox')\n"
    "for __fp_m__ in ('connect', 'connect_ex', 'bind', 'sendto', 'sendmsg'):\n"
    "    setattr(__fp_sock__.socket, __fp_m__, __fp_no_net__)\n"
    "del __fp_m__\n"
)


def _is_dunder(name: str) -> bool:
    return name.startswith("__") and name.endswith("__")


def _denied_module(name: str) -> bool:
    return any(name == m or name.startswith(m + ".") for m in _DENIED_MODULES)


def _scan_tree(tree: ast.AST, *, in_string: bool, depth: int) -> str | None:
    """Return a block reason, or None. ``in_string`` = scanning code found inside a string
    constant: only clearly dangerous shapes are flagged there, so ordinary strings like
    ``"open"`` or ``"__main__"`` never cause a false refusal."""
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.level:
                return "relative imports are not allowed in the sandbox"
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
            if isinstance(node, ast.ImportFrom):  # `from logging import config` reaches a submodule too
                names += [f"{node.module}.{a.name}" for a in node.names]
            for name in names:
                if name.split(".")[0] not in _ALLOWED_IMPORTS or _denied_module(name):
                    return f"import of '{name}' is not allowed in the sandbox"
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name in _DENIED_ATTRS or _is_dunder(alias.name):
                        return f"import of '{node.module}.{alias.name}' is not allowed in the sandbox"
        elif isinstance(node, ast.Attribute):
            if _is_dunder(node.attr) and node.attr not in _ALLOWED_DUNDER_ATTRS:
                return f"access to '{node.attr}' (reflection) is not allowed in the sandbox"
            if node.attr in _DENIED_ATTRS:
                return f"access to '.{node.attr}' is not allowed in the sandbox"
        elif isinstance(node, ast.Name):
            if _is_dunder(node.id) and node.id not in _ALLOWED_DUNDER_NAMES:
                return f"use of '{node.id}' is not allowed in the sandbox"
            if node.id in _DENIED_BUILTINS and not in_string:
                return f"use of '{node.id}' is not allowed in the sandbox"
        elif isinstance(node, ast.Call) and in_string:
            if isinstance(node.func, ast.Name) and node.func.id in _DENIED_BUILTINS:
                return f"use of '{node.func.id}' is not allowed in the sandbox"
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and depth < _MAX_STRING_DEPTH:
            # FastAPI/pydantic evaluate string annotations (forward refs) and ImportString values,
            # so a string can be code. Scan any string that parses as Python.
            try:
                sub = ast.parse(node.value.strip(), mode="eval")
            except (SyntaxError, ValueError):
                continue
            reason = _scan_tree(sub, in_string=True, depth=depth + 1)
            if reason:
                return reason + " (found inside a string)"
    return None


def scan_code(code: str) -> tuple[bool, str | None]:
    """Static pre-scan. Returns (ok, reason). A SyntaxError is *allowed* through so the
    sandbox runs it and the agent gets a clean traceback to fix."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return True, None
    reason = _scan_tree(tree, in_string=False, depth=0)
    return (reason is None), reason


# --- Result ---------------------------------------------------------------
@dataclass
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool = False
    blocked: bool = False
    block_reason: str | None = None
    unavailable: bool = False  # the sandbox itself couldn't run (launch failure / runner down) — not the code's fault

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out and not self.blocked


def _is_secret_key(key: str) -> bool:
    upper = key.upper()
    return any(tok in upper for tok in ("KEY", "TOKEN", "SECRET", "PASSWORD", "QDRANT", "REDIS", "OPIK"))


# Starlette 1.3+ prefers an `httpx2` package and warns at TestClient import when only
# `httpx` is present. The warning is cosmetic but lands in every sandbox run's stderr,
# which the Agent and Playground surface to learners — silence it via a `-W` filter on the
# argv below. We match on the message, not the category: a category filter needs the class
# imported at startup (before starlette is loaded) and PYTHONWARNINGS is ignored anyway under
# the `-I` isolated flag, whereas `-W` command-line options are honoured even in isolated mode.
_SUPPRESS_WARNING = "ignore:Using `httpx` with `starlette.testclient`"


def _scrubbed_env() -> dict[str, str]:
    """Pass through a minimal env with all credential-shaped vars removed."""
    return {k: v for k, v in os.environ.items() if not _is_secret_key(k)}


# Unprivileged uid/gid for sandbox children when the server runs as root ("nobody" on Debian).
SANDBOX_UID = 65534
SANDBOX_GID = 65534


def _should_drop_privileges() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


_warned_no_drop = False


def _warn_no_drop() -> None:
    """Without root the child shares the server's uid and could read its environment (API keys)
    after a scan escape. Fine for local dev; never expose Agent/Playground publicly like this."""
    global _warned_no_drop
    _warned_no_drop = True
    logger.warning(
        "Sandbox is running WITHOUT a privilege drop (server is not root): an escape could read the "
        "server's environment. Keep AGENT_ENABLED/PLAYGROUND_ENABLED off on any public host without OS isolation."
    )


def _limits(cpu_s: int, mem_bytes: int, fsize_bytes: int, nproc: int | None):  # noqa: ANN202
    """preexec_fn body: only async-signal-safe-ish setrlimit calls, no imports (``resource`` is
    imported at module level). Popen applies ``start_new_session`` and the user/group switch in C
    *before* this runs; lowering limits needs no privilege, and ``nobody`` cannot raise them back."""

    def _apply() -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_s, cpu_s + 1))
        limits = [(resource.RLIMIT_AS, mem_bytes), (resource.RLIMIT_FSIZE, fsize_bytes)]
        if nproc is not None:  # counts every process/thread of the uid, so only safe for a dedicated uid
            limits.append((resource.RLIMIT_NPROC, nproc))
        for limit, value in limits:
            try:
                resource.setrlimit(limit, (value, value))
            except (ValueError, OSError):  # not all limits enforce on every OS (macOS RLIMIT_AS)
                pass

    return _apply


def _cleanup_as(path: str, uid: int, gid: int) -> None:
    """Delete ``path`` as ``uid``/``gid``. In the runner container root has no DAC_OVERRIDE/FOWNER,
    so it cannot list or delete a 0700 folder owned by the slot uid; the owner must do it.
    Errors are logged, never raised."""
    try:
        subprocess.run(
            [sys.executable, "-I", "-c", "import shutil,sys; shutil.rmtree(sys.argv[1], ignore_errors=True)", path],
            user=uid,
            group=gid,
            extra_groups=[],
            timeout=5,
            check=False,
            capture_output=True,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("Sandbox clean-up as uid %s failed: %s", uid, exc)


class SubprocessExecutor:
    """Default executor (D6). Construct with small limits in tests for speed."""

    def __init__(
        self,
        *,
        wall_timeout_s: int = 15,
        cpu_seconds: int = 10,
        mem_mb: int = 512,
        max_output_chars: int = 20_000,
        max_file_bytes: int = 5_000_000,
        max_procs: int = 64,
        sandbox_uid: int = SANDBOX_UID,
        sandbox_gid: int = SANDBOX_GID,
    ):
        self.wall_timeout_s = wall_timeout_s
        self.cpu_seconds = cpu_seconds
        self.mem_bytes = mem_mb * 1024 * 1024
        self.max_output = max_output_chars
        self.max_file_bytes = max_file_bytes
        self.max_procs = max_procs
        self.sandbox_uid = sandbox_uid
        self.sandbox_gid = sandbox_gid

    def _spawn(self, tmp: str, drop: bool) -> subprocess.Popen:
        return subprocess.Popen(
            [sys.executable, "-I", "-W", _SUPPRESS_WARNING, "main.py"],
            cwd=tmp,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=_scrubbed_env(),
            start_new_session=True,  # own process group so a timeout can killpg the whole tree
            # Run as `nobody` when we can (server is root): the server's /proc/<pid>/environ is
            # then unreadable. Done by Popen in C, which is safe in a threaded server.
            user=self.sandbox_uid if drop else None,
            group=self.sandbox_gid if drop else None,
            extra_groups=[] if drop else None,
            preexec_fn=_limits(
                self.cpu_seconds, self.mem_bytes, self.max_file_bytes, self.max_procs if drop else None
            ),
        )

    def run(self, code: str) -> ExecutionResult:
        ok, reason = scan_code(code)
        if not ok:
            logger.info("Sandbox blocked code: %s", reason)
            return ExecutionResult(-1, "", reason or "blocked", 0, blocked=True, block_reason=reason)

        with tempfile.TemporaryDirectory(prefix="fastpilot_sbx_", ignore_cleanup_errors=True) as tmp:
            script = Path(tmp) / "main.py"
            script.write_text(_NET_PRELUDE + "\n" + code, encoding="utf-8")
            drop = _should_drop_privileges()
            if not drop and not _warned_no_drop:
                _warn_no_drop()
            if drop:  # the unprivileged child must own its cwd + script to read/write them
                for path in (tmp, script):
                    os.chown(path, self.sandbox_uid, self.sandbox_gid)
            start = time.monotonic()
            try:
                proc = self._spawn(tmp, drop)
            except OSError as exc:  # e.g. the interpreter isn't readable by `nobody` (root-only pyenv/uv)
                logger.error("Sandbox could not start the child process: %s", exc)
                return ExecutionResult(
                    exit_code=-1,
                    stdout="",
                    stderr="[sandbox] could not start the code runner process",
                    duration_ms=int((time.monotonic() - start) * 1000),
                    unavailable=True,
                )
            timed_out = False
            try:
                stdout, stderr = proc.communicate(timeout=self.wall_timeout_s)
            except subprocess.TimeoutExpired:
                timed_out = True
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:  # an escaped grandchild in a new session can hold the pipes open: don't wait forever
                    stdout, stderr = proc.communicate(timeout=2)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    for pipe in (proc.stdout, proc.stderr):
                        if pipe:
                            pipe.close()
                    proc.wait(timeout=2)
                    stdout, stderr = "", "[sandbox] output pipes held open after kill; output discarded"
            duration_ms = int((time.monotonic() - start) * 1000)
            if drop:  # root cannot always delete the slot uid's files, so the slot uid does it
                _cleanup_as(tmp, self.sandbox_uid, self.sandbox_gid)

            return ExecutionResult(
                exit_code=-9 if timed_out else (proc.returncode or 0),
                stdout=(stdout or "")[: self.max_output],
                stderr=((stderr or "") if not timed_out else (stderr or "") + "\n[sandbox] killed: wall-clock timeout")[
                    : self.max_output
                ],
                duration_ms=duration_ms,
                timed_out=timed_out,
            )


_executor: SubprocessExecutor | None = None


def get_executor() -> SubprocessExecutor:
    """Singleton executor built from settings (wall/cpu/mem from config)."""
    global _executor
    if _executor is None:
        from app.config import get_settings

        s = get_settings()
        _executor = SubprocessExecutor(
            wall_timeout_s=s.executor_wall_timeout_s,
            cpu_seconds=s.executor_cpu_seconds,
            mem_mb=s.executor_mem_mb,
        )
    return _executor
