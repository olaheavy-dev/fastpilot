"""Container proof for the runner sidecar (``-m integration``): the hardening holds in a real container.

These tests build and start the compose ``runner`` and ``backend`` services (``docker compose up -d
--build runner backend``) and probe them from outside. They are skipped when ``docker`` is not on
PATH or the Docker daemon is not running, and they are deselected from the default run.

Probes that act as a slot user run ``docker compose exec -u 61001:61001 runner ...``. The group
matters: ``-u 61001`` alone gives the process gid 0 (root's group), which a real slot never has.

Run with ``uv run pytest -m integration tests/test_runner_integration.py -v``.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parent.parent
AGENT_CODE = sorted((ROOT / "evaluations" / "eval_results" / "agent_code").glob("*.py"))
BACKEND = os.getenv("FASTPILOT_BACKEND_URL", "http://localhost:8000")
SLOT = "61001:61001"  # a slot uid with its own group, as the runner starts it
SOCKET = "/run/fastpilot/runner.sock"

# Lists the pids whose real uid is argv[1] (procps/pgrep is not in the slim image).
_PIDS_OF_UID = (
    "import os,sys\n"
    "u=sys.argv[1]\n"
    "for p in filter(str.isdigit, os.listdir('/proc')):\n"
    "    try:\n"
    "        s=open(f'/proc/{p}/status').read()\n"
    "    except OSError:\n"
    "        continue\n"
    "    if [l.split()[1] for l in s.splitlines() if l.startswith('Uid:')]==[u]:\n"
    "        print(p)\n"
)


def _compose(*args: str, check: bool = False, timeout: float = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", *args], cwd=ROOT, capture_output=True, text=True, timeout=timeout, check=check
    )


def _exec(*cmd: str, user: str | None = SLOT) -> subprocess.CompletedProcess[str]:
    """Run ``cmd`` in the runner container (as a slot user by default; ``user=None`` for root)."""
    opts = ["-T"] + (["-u", user] if user else [])
    return _compose("exec", *opts, "runner", *cmd)


def _execute(code: str) -> dict:
    import httpx

    # A fresh session per call keeps the Playground's 3-runs-a-minute limit out of the way.
    resp = httpx.post(f"{BACKEND}/execute", json={"code": code, "session_id": f"itest-{uuid.uuid4()}"}, timeout=60)
    resp.raise_for_status()
    return resp.json()


def _wait_for_backend(timeout_s: float = 180) -> None:
    import httpx

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{BACKEND}/health", timeout=5).json().get("components", {}).get("code_runner") == "healthy":
                return
        except (httpx.HTTPError, ValueError):
            pass
        time.sleep(1)
    pytest.fail(f"backend at {BACKEND} did not report a healthy code_runner within {timeout_s}s")


@pytest.fixture(scope="module", autouse=True)
def stack():
    if shutil.which("docker") is None:
        pytest.skip("docker is not on PATH")
    if subprocess.run(["docker", "info"], capture_output=True, timeout=30).returncode != 0:
        pytest.skip("the Docker daemon is not running")
    up = _compose("up", "-d", "--build", "runner", "backend", timeout=900)
    assert up.returncode == 0, up.stderr
    _wait_for_backend()
    yield
    _compose("rm", "--stop", "--force", "runner", "backend")


def test_runner_logs_the_socket_path():
    assert SOCKET in _compose("logs", "runner").stdout


def test_captured_agent_programs_pass_through_execute():
    assert AGENT_CODE, "no captured agent programs found"
    for path in AGENT_CODE:
        result = _execute(path.read_text(encoding="utf-8"))
        assert result["guard"] is None and result["exit_code"] == 0, (path.name, result)


def test_runner_has_no_network():
    probe = _exec("python", "-c", "import socket; socket.create_connection(('1.1.1.1', 53), 2)")
    assert probe.returncode != 0
    assert "Network is unreachable" in probe.stderr or "unreachable" in probe.stderr.lower(), probe.stderr


# Set by the official python base image: the public fingerprint of the CPython release signing key.
_PUBLIC_NAMES = {"GPG_KEY"}


def test_runner_has_no_keys():
    container_env = _exec("env", user=None).stdout
    pid1_env = _exec("sh", "-c", "tr '\\0' '\\n' < /proc/1/environ", user=None).stdout
    names = {line.split("=", 1)[0] for line in (container_env + pid1_env).splitlines() if "=" in line}
    leaked = [
        n
        for n in names - _PUBLIC_NAMES
        if any(t in n.upper() for t in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
    ]
    assert names and not leaked, leaked


def test_runner_filesystem_is_read_only():
    as_root = _exec("touch", "/srv/x", user=None)
    assert as_root.returncode != 0 and "Read-only file system" in as_root.stderr, as_root.stderr
    as_slot = _exec("touch", "/srv/x")
    assert as_slot.returncode != 0
    scratch = f"/tmp/itest-{uuid.uuid4().hex}"
    assert _exec("sh", "-c", f"touch {scratch} && rm {scratch}").returncode == 0


def test_slot_user_cannot_touch_socket():
    connect = _exec(
        "python", "-c", f"import socket; s = socket.socket(socket.AF_UNIX); s.connect('{SOCKET}')"
    )
    assert connect.returncode != 0 and "PermissionError" in connect.stderr, connect.stderr
    remove = _exec("rm", "-f", SOCKET)
    assert remove.returncode != 0
    assert _exec("test", "-S", SOCKET, user=None).returncode == 0  # still there


def test_other_slot_cannot_read_a_running_program():
    """While a run is in flight, the other slot uid can neither list nor read its folder."""
    marker = uuid.uuid4().hex
    code = f"import time\nsecret = '{marker}'\ntime.sleep(4)\nprint('done')\n"
    worker = threading.Thread(target=_execute, args=(code,))
    worker.start()
    try:
        owner = ""
        for _ in range(30):
            owner = _exec("sh", "-c", "stat -c %u /tmp/fastpilot_sbx_* 2>/dev/null", user=None).stdout.strip()
            if owner in ("61001", "61002"):  # just after mkdtemp the folder is still root's ("0"): keep polling
                break
            time.sleep(0.1)
        assert owner in ("61001", "61002"), owner
        other = "61002" if owner == "61001" else "61001"
        probe = _exec("sh", "-c", "cat /tmp/fastpilot_sbx_*/main.py; ls /tmp/fastpilot_sbx_*", user=f"{other}:{other}")
        assert probe.returncode != 0 and marker not in probe.stdout, probe.stdout
    finally:
        worker.join(timeout=30)


def test_leftover_process_is_killed_after_next_run():
    started = _compose("exec", "-d", "-u", SLOT, "runner", "setsid", "sleep", "600")
    assert started.returncode == 0, started.stderr
    time.sleep(1)
    assert _exec("python", "-c", _PIDS_OF_UID, "61001", user=None).stdout.strip(), "the leftover did not start"
    # Two slots are used in turn, so two runs are enough to give slot 61001 a clean-up pass.
    for _ in range(2):
        assert _execute("print('hello')\n")["exit_code"] == 0
    left = _exec("python", "-c", _PIDS_OF_UID, "61001", user=None).stdout.strip()
    assert left == "", f"processes still owned by 61001: {left}"


def test_stopped_runner_gives_unavailable_guard():
    """Runs last: it stops the runner, then starts it again."""
    import httpx

    _compose("stop", "runner", check=True)
    try:
        result = _execute("print('hello')\n")
        assert result["guard"] == "unavailable", result
        health = httpx.get(f"{BACKEND}/health", timeout=10).json()
        assert health["executor"] == "runner" and health["components"]["code_runner"] == "degraded", health
    finally:
        _compose("start", "runner")
