"""Client for the ``runner`` sidecar: sends code over HTTP on a Unix socket.

It never raises. Any transport or decoding failure becomes an ``unavailable`` result, which
``/execute`` reports as ``guard="unavailable"`` and the agent treats as a reason to stop.
"""

from __future__ import annotations

import logging

import httpx

from app.augmentations.code_executor import ExecutionResult

logger = logging.getLogger(__name__)

_UNAVAILABLE_MSG = "[sandbox] code runner unavailable"


def _unavailable() -> ExecutionResult:
    return ExecutionResult(-1, "", _UNAVAILABLE_MSG, 0, unavailable=True)


class RunnerClient:
    def __init__(self, socket_path: str, timeout_s: float):
        self.socket_path = socket_path
        self.timeout_s = timeout_s
        self._client = httpx.Client(
            transport=httpx.HTTPTransport(uds=socket_path), base_url="http://runner", timeout=timeout_s
        )

    def run(self, code: str) -> ExecutionResult:
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
