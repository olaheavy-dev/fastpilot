"""Backend client for the FastPilot frontend.

Pure of Streamlit so it can be unit-tested headless. The SSE parser is the risky
bit (chunk boundaries, malformed lines) and is the most-tested function here.

SSE protocol consumed (from app/main.py):
  session → (rewrite?) → cache_status → classification → context×k → token×N → done
  refusal path: token×N → done{refused}; failure: error → done{error}
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Iterator

import requests

# Accept BACKEND_URL as an alias for API_BASE_URL (e.g. Railway env var naming).
API_BASE_URL = os.environ.get("API_BASE_URL") or os.environ.get("BACKEND_URL") or "http://localhost:8000"

# Rate limits (issue #12): the backend can't see the visitor, so we forward their address
# with a shared key. Header names must match app/augmentations/client_identity.py.
CLIENT_IP_HEADER = "X-FastPilot-Client-IP"
PROXY_KEY_HEADER = "X-FastPilot-Proxy-Key"
_client_ip_provider: Callable[[], str] = lambda: ""  # noqa: E731 - replaced by app.py


def set_client_ip_provider(provider: Callable[[], str]) -> None:
    """Register how to read the current visitor's address (``visitor.visitor_ip``)."""
    global _client_ip_provider
    _client_ip_provider = provider


def identity_headers() -> dict[str, str]:
    """The visitor's address and the shared key, or nothing when either is missing."""
    key = os.environ.get("FRONTEND_PROXY_KEY", "")
    if not key:
        return {}
    try:
        ip = _client_ip_provider() or ""
    except Exception:  # noqa: BLE001 - never break a request over this
        ip = ""
    return {CLIENT_IP_HEADER: ip, PROXY_KEY_HEADER: key} if ip else {}


# Event names the backend emits (for reference / validation in the UI).
KNOWN_EVENTS = {"session", "rewrite", "cache_status", "classification", "context", "token", "done", "error"}


def parse_sse_lines(lines: Iterable[str | bytes]) -> Iterator[tuple[str, dict]]:
    """Yield ``(event, data)`` from raw SSE lines.

    Robust to: blank lines (event boundary), comment lines (``:`` prefix), a missing
    ``event:`` (defaults to ``"message"``), and malformed ``data:`` JSON (skipped, not
    raised). ``requests.iter_lines`` already reassembles transport chunk boundaries, so
    each line handed in is complete.
    """
    event: str | None = None
    for raw in lines:
        if raw is None:
            continue
        line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
        line = line.rstrip("\r")
        if line == "":
            event = None  # dispatch boundary
            continue
        if line.startswith(":"):
            continue  # comment / heartbeat
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            payload = line[5:].strip()
            try:
                data = json.loads(payload)
            except (ValueError, json.JSONDecodeError):
                continue  # malformed data → skip this line, keep streaming
            yield (event or "message", data)


def stream_query(
    query: str,
    session_id: str | None = None,
    use_cache: bool = True,
    base_url: str | None = None,
    timeout: int = 120,
) -> Iterator[tuple[str, dict]]:
    """POST /query/stream and yield parsed ``(event, data)`` pairs."""
    url = f"{base_url or API_BASE_URL}/query/stream"
    body = {"query": query, "session_id": session_id, "use_cache": use_cache}
    headers = {"Accept": "text/event-stream", **identity_headers()}
    with requests.post(url, json=body, stream=True, headers=headers, timeout=timeout) as resp:
        resp.raise_for_status()
        yield from parse_sse_lines(resp.iter_lines(decode_unicode=True))


def send_query(
    query: str,
    session_id: str | None = None,
    use_cache: bool = True,
    base_url: str | None = None,
    timeout: int = 120,
) -> dict:
    """POST /query (non-streaming) → QueryResponse dict."""
    url = f"{base_url or API_BASE_URL}/query"
    body = {"query": query, "session_id": session_id, "use_cache": use_cache}
    resp = requests.post(url, json=body, headers=identity_headers(), timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def send_feedback(
    session_id: str,
    msg_id: str,
    rating: str,
    query: str = "",
    answer: str = "",
    comment: str = "",
    reason: str = "",
    trace_id: str = "",
    base_url: str | None = None,
) -> bool:
    """POST /feedback. Best-effort — returns True on 2xx, False otherwise."""
    url = f"{base_url or API_BASE_URL}/feedback"
    body = {
        "session_id": session_id,
        "msg_id": msg_id,
        "rating": rating,
        "query": query,
        "answer": answer,
        "comment": comment,
        "metadata": {"trace_id": trace_id, "reason": reason},
    }
    try:
        resp = requests.post(url, json=body, timeout=10)
        return resp.ok
    except requests.RequestException:
        return False


def stream_agent(
    task: str,
    session_id: str | None = None,
    base_url: str | None = None,
    timeout: int = 150,
) -> Iterator[tuple[str, dict]]:
    """POST /agent/stream and yield parsed agent events (agent_step/code/exec_result/token/done)."""
    url = f"{base_url or API_BASE_URL}/agent/stream"
    body = {"task": task, "session_id": session_id}
    headers = {"Accept": "text/event-stream", **identity_headers()}
    with requests.post(url, json=body, stream=True, headers=headers, timeout=timeout) as resp:
        resp.raise_for_status()
        yield from parse_sse_lines(resp.iter_lines(decode_unicode=True))


def execute_code(code: str, session_id: str = "", base_url: str | None = None, timeout: int = 30) -> dict:
    """POST /execute → ExecuteResult dict. Maps a disabled (404) playground to a guard."""
    resp = requests.post(
        f"{base_url or API_BASE_URL}/execute",
        json={"code": code, "session_id": session_id},
        headers=identity_headers(),
        timeout=timeout,
    )
    if resp.status_code == 404:
        return {"guard": "disabled", "stderr": "Playground is turned off on the server.", "ok": False}
    resp.raise_for_status()
    return resp.json()


def fix_code(code: str, stderr: str, session_id: str = "", base_url: str | None = None, timeout: int = 60) -> dict:
    """POST /fix → FixResponse dict."""
    resp = requests.post(
        f"{base_url or API_BASE_URL}/fix",
        json={"code": code, "stderr": stderr, "session_id": session_id},
        headers=identity_headers(),
        timeout=timeout,
    )
    if resp.status_code == 404:
        return {"fixed_code": code, "guard": "disabled"}
    resp.raise_for_status()
    return resp.json()


def get_health(base_url: str | None = None) -> dict:
    """GET /health. Returns the body, or a synthetic 'down' status on failure."""
    try:
        resp = requests.get(f"{base_url or API_BASE_URL}/health", timeout=5)
        if resp.ok:
            return resp.json()
        return {"status": "down", "components": {}}
    except requests.RequestException:
        return {"status": "down", "components": {}}
