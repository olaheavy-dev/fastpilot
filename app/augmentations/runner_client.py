"""Client for the ``runner`` sidecar: sends code over HTTP on a Unix socket.

It never raises. Any transport or decoding failure becomes an ``unavailable`` result, which
``/execute`` reports as ``guard="unavailable"`` and the agent treats as a reason to stop.
"""

from __future__ import annotations

import logging
import threading

import httpx

from app.augmentations.code_executor import ExecutionResult

logger = logging.getLogger(__name__)

_UNAVAILABLE_MSG = "[sandbox] code runner unavailable"
_BUSY_MSG = "[sandbox] code runner busy"


def _unavailable(msg: str = _UNAVAILABLE_MSG) -> ExecutionResult:
    return ExecutionResult(-1, "", msg, 0, unavailable=True)


class RunnerClient:
    def __init__(self, socket_path: str, timeout_s: float, max_in_flight: int = 3):
        """``max_in_flight`` caps calls waiting on the runner (its slots + 1). A call over the cap
        gets "busy" at once, so waiting calls cannot fill the thread pool that Chat also uses."""
        self.socket_path = socket_path
        self.timeout_s = timeout_s
        self.max_in_flight = max_in_flight
        self._in_flight = threading.BoundedSemaphore(max_in_flight)
        self._client = httpx.Client(
            transport=httpx.HTTPTransport(uds=socket_path), base_url="http://runner", timeout=timeout_s
        )

    def run(self, code: str) -> ExecutionResult:
        if not self._in_flight.acquire(blocking=False):
            logger.warning("Code runner call refused: %d calls already in flight", self.max_in_flight)
            return _unavailable(_BUSY_MSG)
        try:
            return self._post(code)
        finally:
            self._in_flight.release()

    def _post(self, code: str) -> ExecutionResult:
        try:
            resp = self._client.post("/run", json={"code": code})
            resp.raise_for_status()
            data = resp.json()
            return ExecutionResult(
                exit_code=int(data["exit_code"]),
                stdout=str(data["stdout"]),
                stderr=str(data["stderr"]),
                duration_ms=int(data["duration_ms"]),
                timed_out=bool(data.get("timed_out", False)),
                blocked=bool(data.get("blocked", False)),
                block_reason=data.get("block_reason"),
                unavailable=bool(data.get("unavailable", False)),
            )
        except (httpx.HTTPError, OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("Code runner call failed: %s", type(exc).__name__)  # never log the code
            return _unavailable()

    def is_healthy(self) -> bool:
        try:
            resp = self._client.get("/health", timeout=min(self.timeout_s, 2.0))
            return resp.status_code == 200 and resp.json().get("status") == "ok"
        except (httpx.HTTPError, OSError, ValueError, AttributeError):
            return False
