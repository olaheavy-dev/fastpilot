"""Rate limiter for Chat, Agent and Playground (D11, issue #12).

Each limiter holds one or more fixed windows, for example "3 a minute" and "30 a day".
A call is allowed only when every window has room, and then it counts against all of
them. A blocked call counts against none. Windows reset on fixed boundaries: a minute
window at the top of the minute, a day window at midnight UTC.

**Atomic without a script.** The limiter adds the call to every window first, then
checks. If any window is over its limit, it takes the call back off again. Two callers
racing at the edge can therefore never both get through; at worst one is blocked a
moment early.

**Privacy.** The key is the visitor's address, but it is stored only as a keyed hash
(HMAC-SHA256, shortened), and every counter expires at the end of its window, so a day
counter is gone by midnight UTC.

Counts live in Redis when it is available, so they hold across workers and restarts.
Without Redis, or when a Redis call fails, the limiter uses an in-process counter. It
never lets a call through just because Redis has a problem: once visitor code runs in
public, a Redis outage must not switch the limit off.

``check`` does blocking I/O: call it from a worker thread (``asyncio.to_thread``), not
from the event loop.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading
import time
from collections.abc import Sequence
from typing import NamedTuple

logger = logging.getLogger(__name__)

MINUTE = 60
DAY = 86_400

_MEM_PRUNE_AT = 10_000  # prune expired in-memory counters once there are this many
_TTL_SLACK_S = 5  # keep a counter a few seconds past its window end, for clock skew
_WARN_EVERY_S = 60  # at most one "Redis is failing" warning a minute
_DEFAULT_HASH_SECRET = "fastpilot-rate-limit"  # used when no FRONTEND_PROXY_KEY is set


class Decision(NamedTuple):
    allowed: bool
    retry_after: int  # seconds until the blocking window resets; 0 when allowed
    window_s: int  # the window that blocked the call (MINUTE, DAY, ...); 0 when allowed


class RateLimiter:
    """Fixed-window limiter. ``limits`` is a list of ``(window_seconds, max_calls)``.

    A limit with ``max_calls <= 0`` is switched off. ``namespace`` keeps the Chat, Agent
    and Playground counters apart. ``hash_secret`` keys the hash of the visitor's address.
    """

    def __init__(
        self,
        *,
        limits: Sequence[tuple[int, int]],
        namespace: str,
        redis_client=None,
        hash_secret: str = "",
    ):
        # Longest window first: when the day is used up, say "tomorrow", not "in 20 seconds".
        self.limits = sorted(((w, n) for w, n in limits if n > 0), key=lambda wn: wn[0], reverse=True)
        self.namespace = namespace
        self.redis = redis_client
        self._secret = (hash_secret or _DEFAULT_HASH_SECRET).encode()
        self._mem: dict[str, tuple[int, float]] = {}  # key -> (count, expires_at)
        self._lock = threading.Lock()
        self._last_warn = 0.0

    def check(self, key: str) -> Decision:
        """Decide for this caller. Counts the call when it is allowed."""
        if not self.limits:
            return Decision(True, 0, 0)
        now = time.time()
        buckets = self._buckets(key or "unknown", now)
        if self.redis is not None:
            try:
                counts = self._redis_add(buckets, +1)
                return self._settle(buckets, counts, now, self._redis_add)
            except Exception as exc:  # noqa: BLE001 - fall back to memory, never fail open
                self._warn_redis(exc, now)
        with self._lock:
            counts = self._mem_add(buckets, +1, now)
            return self._settle(buckets, counts, now, lambda b, d: self._mem_add(b, d, now))

    def _buckets(self, key: str, now: float) -> list[tuple[str, int, int]]:
        """(storage key, max calls, ttl) per window. The visitor's address is hashed."""
        digest = hmac.new(self._secret, key.encode(), hashlib.sha256).hexdigest()[:24]
        out = []
        for window, max_calls in self.limits:
            ttl = window - int(now) % window + _TTL_SLACK_S  # gone soon after the window ends
            out.append((f"rl:{self.namespace}:{window}:{digest}:{int(now) // window}", max_calls, ttl))
        return out

    def _settle(self, buckets, counts, now: float, add) -> Decision:  # noqa: ANN001
        """Allow, or take the call back off every window and report the longest one that is full."""
        for (_, max_calls, _), count, (window, _) in zip(buckets, counts, self.limits, strict=True):
            if count > max_calls:
                add(buckets, -1)
                return Decision(False, max(1, window - int(now) % window), window)
        return Decision(True, 0, 0)

    def _warn_redis(self, exc: Exception, now: float) -> None:
        if now - self._last_warn >= _WARN_EVERY_S:
            self._last_warn = now
            logger.warning("rate-limit redis error, using in-process counter: %s", exc)

    # --- Redis store: one round trip per add ---
    def _redis_add(self, buckets, delta: int) -> list[int]:  # noqa: ANN001
        pipe = self.redis.pipeline(transaction=False)
        for key, _, ttl in buckets:
            pipe.incrby(key, delta)
            pipe.expire(key, ttl)
        results = pipe.execute()
        return [int(results[i]) for i in range(0, len(results), 2)]

    # --- in-process store (caller holds the lock) ---
    def _mem_add(self, buckets, delta: int, now: float) -> list[int]:  # noqa: ANN001
        if len(self._mem) >= _MEM_PRUNE_AT:
            self._mem = {k: v for k, v in self._mem.items() if v[1] > now}
        counts = []
        for key, _, ttl in buckets:
            count, expires_at = self._mem.get(key, (0, 0.0))
            if expires_at <= now:
                count, expires_at = 0, now + ttl
            count = max(0, count + delta)
            self._mem[key] = (count, expires_at)
            counts.append(count)
        return counts
