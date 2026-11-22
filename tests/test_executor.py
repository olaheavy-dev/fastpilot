"""Sandbox executor safety suite (AC3.3) — the highest-value tests in the repo.

These run *real* subprocesses (no network, no creds). Small limits keep them fast.
The memory-limit case only enforces reliably on Linux (RLIMIT_AS), so it's skipped
elsewhere.
"""

from __future__ import annotations

import sys

import pytest

from app.augmentations.code_executor import SubprocessExecutor, scan_code

# Fast limits so the timeout case doesn't take 15s.
EXEC = SubprocessExecutor(wall_timeout_s=4, cpu_seconds=3, mem_mb=256)

HAPPY = """
from fastapi import FastAPI
from fastapi.testclient import TestClient

app = FastAPI()

@app.get("/ping")
def ping():
    return {"pong": True}

client = TestClient(app)
r = client.get("/ping")
print("status", r.status_code, r.json())
assert r.status_code == 200
"""


def test_happy_path_testclient():
    result = EXEC.run(HAPPY)
    assert result.ok, result.stderr
    assert "status 200" in result.stdout
    assert result.exit_code == 0


def test_testclient_import_warning_suppressed():
    """Starlette's httpx-deprecation warning must not pollute learner-facing stderr."""
    result = EXEC.run(HAPPY)
    assert "StarletteDeprecationWarning" not in result.stderr
    assert result.stderr.strip() == ""


def test_stderr_and_nonzero_exit_captured():
    result = EXEC.run("import logging\nlogging.warning('to err')\nraise ValueError('boom')\n")
    assert not result.ok
    assert result.exit_code != 0
    assert "boom" in result.stderr
    assert "to err" in result.stderr


def test_infinite_loop_killed():
    result = EXEC.run("while True:\n    pass\n")
    assert not result.ok
    assert result.duration_ms <= 16_000  # killed by CPU/wall limit, not hung


def test_network_modules_blocked_at_scan():
    result = EXEC.run("import urllib.request\nurllib.request.urlopen('http://example.com', timeout=3)\n")
    assert result.blocked and "urllib" in (result.block_reason or "")


def test_network_prelude_blocks_connect_at_runtime(tmp_path):
    # The prelude is the second net layer for anything that slips the scan. Exercise it directly.
    from app.augmentations.code_executor import _NET_PRELUDE

    script = tmp_path / "net.py"
    script.write_text(_NET_PRELUDE + "import urllib.request\nurllib.request.urlopen('http://example.com', timeout=3)\n")
    import subprocess

    proc = subprocess.run([sys.executable, "-I", str(script)], capture_output=True, text=True, timeout=20)
    assert proc.returncode != 0
    assert "network access is disabled" in proc.stderr


@pytest.mark.parametrize(
    "code,needle",
    [
        ("import subprocess\nsubprocess.run(['ls'])\n", "subprocess"),
        ("import os\nos.system('echo hi')\n", "'os'"),
        ("eval('1+1')\n", "eval"),
        # Reflection escapes: reach denied objects without naming them. All blocked at scan.
        ("print(().__class__.__bases__[0].__subclasses__())\n", "__subclasses__"),
        ("getattr((), '__cl' + 'ass__')\n", "getattr"),
        ("print(globals())\n", "globals"),
        ("print(open('/etc/passwd').read())\n", "open"),
    ],
)
def test_scan_rejects_before_execution(code, needle):
    result = EXEC.run(code)
    assert result.blocked is True
    assert needle in (result.block_reason or "")
    assert result.duration_ms == 0  # never ran


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="RLIMIT_AS enforced on Linux")
def test_memory_limit_enforced():
    result = EXEC.run("x = bytearray(2 * 1024 * 1024 * 1024)\nprint('allocated')\n")
    assert not result.ok
    assert "allocated" not in result.stdout


def test_file_access_modules_blocked():
    for mod in ("pathlib", "os", "io", "sys", "shutil"):
        ok, reason = scan_code(f"import {mod}\n")
        assert ok is False and mod in reason


# --- scan_code units (no subprocess) --------------------------------------
def test_scan_allows_normal_fastapi():
    ok, reason = scan_code(HAPPY)
    assert ok and reason is None


def test_scan_allows_syntax_error_through():
    ok, _ = scan_code("def f(:\n  pass")  # let the sandbox surface the traceback
    assert ok


def test_scan_rejects_import_from_denied_module():
    ok, reason = scan_code("from subprocess import run\nrun(['ls'])\n")
    assert ok is False
    assert "subprocess" in reason


def test_scan_rejects_os_exec_family():
    ok, reason = scan_code("import os\nos.execv('/bin/sh', ['sh'])\n")
    assert ok is False
    assert "'os'" in reason


@pytest.mark.parametrize(
    "code,needle",
    [
        # `from os import system` rebinds the call to a bare name, sidestepping the dotted
        # os.system path scan — the import itself must be rejected. (Regression: this bypass
        # previously passed the scan.)
        ("from os import system\nsystem('id')\n", "\'os\'"),
        ("from os import system as s\ns('id')\n", "\'os\'"),
        ("from os import popen\npopen('id')\n", "\'os\'"),
        ("from os import execv\n", "\'os\'"),
    ],
)
def test_scan_rejects_denied_member_from_import(code, needle):
    ok, reason = scan_code(code)
    assert ok is False
    assert needle in reason


@pytest.mark.parametrize(
    "code",
    [
        # Everything the captured agent runs uses (evaluations/eval_results/agent_code/).
        "from typing import Annotated\nfrom fastapi import FastAPI, Depends\nfrom pydantic import BaseModel, Field\n",
        "from datetime import datetime\nfrom enum import Enum\nimport json, uuid, asyncio\n",
        'if __name__ == "__main__":\n    print({"status": "open", "x": "__main__"})\n',
        'from fastapi import FastAPI\napp = FastAPI()\n'
        '@app.get("/items/{item_id}")\ndef f(item_id: "int"):\n    return 1\n',
    ],
)
def test_scan_allows_normal_example_code(code):
    ok, reason = scan_code(code)
    assert ok, reason


@pytest.mark.parametrize(
    "code",
    [
        # Each of these passed the old denylist scan and ran (found in the Nov 2026 review).
        'import posix\nposix.system("echo x")\n',
        'import os\nos.spawnlp(os.P_WAIT, "echo", "echo")\n',
        'import os\nos.posix_spawnp("echo", ["echo"], {})\n',
        '__builtins__.eval("1")\n',
        'e = eval\ne("1")\n',
        'import typing\ntyping.sys.modules["os"]\n',
        "import asyncio\nasyncio.subprocess.PIPE\n",
        "import asyncio\nasyncio.create_subprocess_shell('id')\n",
        "import logging\nlogging.os.getpid()\n",
        # String routes: FastAPI evaluates string annotations; pydantic imports ImportString values.
        "def f(x: \"__import__('os').system('id')\"):\n    pass\n",
        "from pydantic import ImportString\n",
        "import pydantic\npydantic.ImportString\n",
        # getattr-by-string helpers.
        "import operator\noperator.attrgetter('x')\n",
        "import string\nstring.Formatter().get_field('0', [1], {})\n",
        # Frame walking to reach a module's globals.
        "def g():\n    yield 1\ng().gi_frame.f_globals\n",
        "from . import x\n",
    ],
)
def test_scan_blocks_known_escapes(code):
    ok, reason = scan_code(code)
    assert ok is False, f"escape passed the scan: {code!r}"
    assert reason


def test_privileges_dropped_only_as_root(monkeypatch):
    from app.augmentations import code_executor as ce

    monkeypatch.setattr(ce.os, "geteuid", lambda: 0)
    assert ce._should_drop_privileges() is True
    monkeypatch.setattr(ce.os, "geteuid", lambda: 1000)
    assert ce._should_drop_privileges() is False


def test_popen_switches_to_nobody_as_root(monkeypatch):
    from app.augmentations import code_executor as ce

    captured = {}

    class _Proc:
        pid = 1
        returncode = 0

        def communicate(self, timeout=None):
            return "", ""

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        return _Proc()

    monkeypatch.setattr(ce.os, "geteuid", lambda: 0)
    monkeypatch.setattr(ce.os, "chown", lambda *a: None)
    monkeypatch.setattr(ce.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(ce, "_cleanup_as", lambda *a: None)  # the clean-up helper must not really spawn
    ce.SubprocessExecutor(wall_timeout_s=2).run("print(1)\n")
    assert captured["user"] == 65534 and captured["group"] == 65534 and captured["extra_groups"] == []
    assert captured["start_new_session"] is True


def _fake_root(monkeypatch, ce, captured):
    class _Proc:
        pid = 1
        returncode = 0

        def communicate(self, timeout=None):
            return "", ""

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        return _Proc()

    monkeypatch.setattr(ce.os, "geteuid", lambda: 0)
    monkeypatch.setattr(ce.os, "chown", lambda *a: None)
    monkeypatch.setattr(ce.subprocess, "Popen", fake_popen)


def test_popen_uses_configured_slot_uid_as_root(monkeypatch):
    from app.augmentations import code_executor as ce

    captured = {}
    _fake_root(monkeypatch, ce, captured)
    monkeypatch.setattr(ce, "_cleanup_as", lambda *a: None)
    ce.SubprocessExecutor(wall_timeout_s=2, sandbox_uid=61001, sandbox_gid=61001).run("print(1)\n")
    assert captured["user"] == 61001 and captured["group"] == 61001 and captured["extra_groups"] == []


def test_cleanup_runs_as_slot_uid_when_root(monkeypatch):
    from app.augmentations import code_executor as ce

    calls = []
    _fake_root(monkeypatch, ce, {})
    monkeypatch.setattr(ce, "_cleanup_as", lambda *a: calls.append(a))
    ce.SubprocessExecutor(wall_timeout_s=2, sandbox_uid=61001, sandbox_gid=61001).run("print(1)\n")
    assert len(calls) == 1
    path, uid, gid = calls[0]
    assert path.startswith("/") and "fastpilot_sbx_" in path and (uid, gid) == (61001, 61001)


def test_no_cleanup_helper_when_not_root(monkeypatch):
    from app.augmentations import code_executor as ce

    calls = []
    monkeypatch.setattr(ce.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(ce, "_cleanup_as", lambda *a: calls.append(a))
    ce.SubprocessExecutor(wall_timeout_s=4).run("print(1)\n")
    assert calls == []


def test_cleanup_as_logs_and_swallows_errors(monkeypatch):
    from app.augmentations import code_executor as ce

    def boom(*a, **k):
        raise OSError("no such uid")

    monkeypatch.setattr(ce.subprocess, "run", boom)
    ce._cleanup_as("/nonexistent", 61001, 61001)  # must not raise


def test_cleanup_as_runs_rmtree_as_uid(monkeypatch):
    from app.augmentations import code_executor as ce

    captured = {}
    monkeypatch.setattr(ce.subprocess, "run", lambda *a, **k: captured.update(args=a, kwargs=k))
    ce._cleanup_as("/x/y", 61002, 61002)
    cmd = captured["args"][0]
    assert cmd[1:3] == ["-I", "-c"] and cmd[-1] == "/x/y" and "rmtree" in cmd[3]
    kw = captured["kwargs"]
    assert kw["user"] == 61002 and kw["group"] == 61002 and kw["extra_groups"] == [] and kw["timeout"] == 5


@pytest.mark.parametrize(
    "code",
    [
        # Found by the fresh-context security review (Nov 2026); each passed the first allowlist scan.
        "import asyncio\nasync def m():\n    l = asyncio.get_running_loop()\n"
        "    await l.subprocess_shell(asyncio.SubprocessProtocol, 'echo x')\n",
        "import asyncio\nasyncio.get_event_loop().subprocess_exec\n",
        "import logging.config\n",
        "from logging import config\n",
        "from fastapi.responses import FileResponse\n",
        "import fastapi\nfastapi.responses.FileResponse('/etc/passwd')\n",
        "from starlette.staticfiles import StaticFiles\n",
        "from starlette.config import Config\n",
        "import http.server\n",
        "print(__fp_sock__)\n",  # the network prelude's names are unreachable
        "import asyncio\nasyncio.get_event_loop().create_datagram_endpoint\n",
    ],
)
def test_scan_blocks_review_findings(code):
    ok, reason = scan_code(code)
    assert ok is False, f"passed the scan: {code!r}"


@pytest.mark.parametrize(
    "code",
    [
        # Everyday code the first allowlist wrongly refused (review finding P2-1).
        "import re\npattern = re.compile(r'^[a-z]+$')\n",
        "class AppError(Exception):\n    def __init__(self, msg):\n        super().__init__(msg)\n",
        "def h(exc):\n    return type(exc).__name__\n",
        "def r(input: str):\n    return {'input': input}\n",
        "from pydantic import BaseModel\nclass M(BaseModel):\n    system: str\nM(system='x').system\n",
    ],
)
def test_scan_allows_everyday_code(code):
    ok, reason = scan_code(code)
    assert ok, reason


@pytest.mark.xfail(strict=True, reason="Known limit: strings built at run time are invisible to a static scan. "
                   "FastAPI evaluates them as annotations. Only OS isolation (the runner sidecar) contains this.")
def test_runtime_built_annotation_is_not_caught_by_scan():
    code = 's = "int if __imp" + "ort__(\'o\'+\'s\') else int"\ndef f(q: s = 1):\n    pass\n'
    ok, _ = scan_code(code)
    assert ok is False


def test_timeout_returns_even_if_escaped_grandchild_holds_pipes(monkeypatch):
    """Review finding P1-2: a grandchild in a new session survives killpg and keeps stdout open;
    the second wait must be bounded so a server thread is never pinned."""
    from app.augmentations import code_executor as ce

    monkeypatch.setattr(ce, "scan_code", lambda code: (True, None))  # simulate a scan escape
    ex = ce.SubprocessExecutor(wall_timeout_s=1, cpu_seconds=5, mem_mb=512)
    code = "import subprocess, time\nsubprocess.Popen(['sleep', '20'], start_new_session=True)\ntime.sleep(20)\n"
    result = ex.run(code)
    assert result.timed_out
    assert result.duration_ms < 8_000


def test_launch_failure_returns_result_not_500(monkeypatch):
    """Codex review (PR #17): if `nobody` can't execute the interpreter (root-only pyenv/uv), Popen
    raises PermissionError. The executor must return a sandbox result, never raise into the endpoint."""
    from app.augmentations import code_executor as ce

    def boom(*a, **k):
        raise PermissionError(13, "Permission denied", sys.executable)

    monkeypatch.setattr(ce.subprocess, "Popen", boom)
    result = ce.SubprocessExecutor(wall_timeout_s=2).run("print(1)\n")
    assert result.unavailable is True
    assert result.blocked is False
    assert not result.ok
