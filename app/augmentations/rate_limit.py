"""Rate limiter for Chat, Agent and Playground (D11, issue #12).

Each limiter holds one or more fixed windows, for example "3 a minute" and "30 a day".
A call is allowed only when every window has room, and then it counts against all of
them. Windows reset on fixed boundaries: a minute window at the top of the minute, a
day window at midnight UTC.

Counts live in Redis when it is available, so they hold across workers and restarts.
Without Redis, or when a Redis call fails, the limiter uses an in-process counter. It
never lets a call through just because Redis has a problem: once visitor code runs in
public, a Redis outage must not switch the limit off.

The key is the visitor's address, worked out by ``client_identity.client_key``. It is
never a value the client chooses, such as the session id.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Sequence
from typing import NamedTuple

logger = logging.getLogger(__name__)

MINUTE = 60
DAY = 86_400

_MEM_PRUNE_AT = 10_000  # prune expired in-memory counters once there are this many


class Decision(NamedTuple):
    allowed: bool
    retry_after: int  # seconds until the blocking window resets; 0 when allowed
    window_s: int  # the window that blocked the call (MINUTE, DAY, ...); 0 when allowed


class RateLimiter:
    """Fixed-window limiter. ``limits`` is a list of ``(window_seconds, max_calls)``.

    A limit with ``max_calls <= 0`` is switched off. ``namespace`` keeps the Chat, Agent
    and Playground counters apart.
    """

    def __init__(self, *, limits: Sequence[tuple[int, int]], namespace: str, redis_client=None):
        # Longest window first: when the day is used up, say "tomorrow", not "in 20 seconds".
        self.limits = sorted(((w, n) for w, n in limits if n > 0), key=lambda wn: wn[0], reverse=True)
        self.namespace = namespace
        self.redis = redis_client
        self._mem: dict[str, tuple[int, float]] = {}  # key -> (count, expires_at)

    def check(self, key: str) -> Decision:
        """Decide for this caller. Counts the call when it is allowed."""
        key = key or "unknown"
        if not self.limits:
            return Decision(True, 0, 0)
        if self.redis is not None:
            try:
                return self._decide(key, self._redis_get, self._redis_incr)
            except Exception as exc:  # noqa: BLE001 - fall back to memory, never fail open
                logger.warning("rate-limit redis error, using in-process counter: %s", exc)
        return self._decide(key, self._mem_get, self._mem_incr)

    def _decide(self, key: str, get: Callable[[str], int], incr: Callable[[str, int], None]) -> Decision:
        now = time.time()
        buckets = []
        for window, max_calls in self.limits:
            bucket_key = f"rl:{self.namespace}:{window}:{key}:{int(now) // window}"
            if get(bucket_key) >= max_calls:
                return Decision(False, max(1, window - int(now) % window), window)
            buckets.append((bucket_key, window))
        for bucket_key, window in buckets:
            incr(bucket_key, window)
        return Decision(True, 0, 0)

    # --- Redis store ---
    def _redis_get(self, key: str) -> int:
        return int(self.redis.get(key) or 0)

    def _redis_incr(self, key: str, ttl: int) -> None:
        if self.redis.incr(key) == 1:
            self.redis.expire(key, ttl)

    # --- in-process store ---
    def _mem_get(self, key: str) -> int:
        count, expires_at = self._mem.get(key, (0, 0.0))
        return count if expires_at > time.time() else 0

    def _mem_incr(self, key: str, ttl: int) -> None:
        now = time.time()
        if len(self._mem) >= _MEM_PRUNE_AT:
            self._mem = {k: v for k, v in self._mem.items() if v[1] > now}
        count = self._mem_get(key)
        expires_at = self._mem[key][1] if count else now + ttl
        self._mem[key] = (count + 1, expires_at)
