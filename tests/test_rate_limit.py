"""Rate limiter + client identity (issue #12): keyed on the visitor's address, never a
client-chosen id; minute and day windows; Redis errors fall back to memory, not open."""

from __future__ import annotations

import fakeredis
import pytest
from starlette.requests import Request

from app.augmentations import rate_limit
from app.augmentations.client_identity import CLIENT_IP_HEADER, PROXY_KEY_HEADER, client_key, normalise_ip
from app.augmentations.rate_limit import DAY, MINUTE, RateLimiter


class _Clock:
    def __init__(self, now: float):
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = _Clock(1_700_000_000.0)  # a fixed instant, 20 s past the minute (1_700_000_000 % 60 == 20)
    monkeypatch.setattr(rate_limit.time, "time", c)
    return c


# --- RateLimiter ----------------------------------------------------------
def test_minute_window_allows_then_blocks_with_retry(clock):
    rl = RateLimiter(namespace="t", limits=[(MINUTE, 2)])
    assert rl.check("1.2.3.4").allowed
    assert rl.check("1.2.3.4").allowed
    d = rl.check("1.2.3.4")
    assert (d.allowed, d.window_s, d.retry_after) == (False, MINUTE, 40)  # 40 s to the next minute


def test_minute_window_resets_on_the_next_minute(clock):
    rl = RateLimiter(namespace="t", limits=[(MINUTE, 1)])
    assert rl.check("k").allowed
    assert not rl.check("k").allowed
    clock.now += 40  # top of the next minute
    assert rl.check("k").allowed


def test_keys_and_namespaces_are_separate(clock):
    a = RateLimiter(namespace="a", limits=[(MINUTE, 1)])
    b = RateLimiter(namespace="b", limits=[(MINUTE, 1)])
    assert a.check("k").allowed
    assert a.check("other").allowed  # another visitor has their own count
    assert b.check("k").allowed  # another feature has its own count
    assert not a.check("k").allowed


def test_day_window_blocks_after_minutes_pass_and_reports_the_day(clock):
    rl = RateLimiter(namespace="t", limits=[(MINUTE, 2), (DAY, 3)])
    for _ in range(2):
        assert rl.check("k").allowed
    clock.now += 60
    assert rl.check("k").allowed  # 3rd of the day, in a fresh minute
    clock.now += 60
    d = rl.check("k")
    assert (d.allowed, d.window_s) == (False, DAY)
    assert d.retry_after > MINUTE  # "tomorrow", not "in a few seconds"


def test_day_is_reported_even_when_the_minute_is_also_full(clock):
    rl = RateLimiter(namespace="t", limits=[(MINUTE, 1), (DAY, 1)])
    assert rl.check("k").allowed
    assert rl.check("k").window_s == DAY  # longest window is checked first


def test_blocked_calls_do_not_use_up_the_day(clock):
    rl = RateLimiter(namespace="t", limits=[(MINUTE, 1), (DAY, 3)])
    assert rl.check("k").allowed
    for _ in range(5):
        assert not rl.check("k").allowed  # blocked by the minute: not counted
    clock.now += 60
    assert rl.check("k").allowed
    clock.now += 60
    assert rl.check("k").allowed  # 3rd allowed call of the day


def test_zero_limit_is_switched_off(clock):
    rl = RateLimiter(namespace="t", limits=[(MINUTE, 0), (DAY, 0)])
    assert all(rl.check("k").allowed for _ in range(50))


def test_blank_key_shares_one_bucket(clock):
    rl = RateLimiter(namespace="t", limits=[(MINUTE, 1)])
    assert rl.check("").allowed
    assert not rl.check("").allowed


def test_redis_path_counts_and_sets_expiry(clock):
    r = fakeredis.FakeRedis(decode_responses=True)
    rl = RateLimiter(namespace="t", redis_client=r, limits=[(MINUTE, 2), (DAY, 5)])
    assert rl.check("k").allowed
    assert rl.check("k").allowed
    assert not rl.check("k").allowed
    keys = r.keys("rl:t:*")
    assert len(keys) == 2  # one minute bucket, one day bucket
    assert all(0 < r.ttl(k) <= DAY for k in keys)


def test_redis_error_falls_back_to_memory_not_open(clock):
    class _BoomRedis:
        def get(self, key):
            raise RuntimeError("redis down")

    rl = RateLimiter(namespace="t", redis_client=_BoomRedis(), limits=[(MINUTE, 1)])
    assert rl.check("k").allowed
    assert not rl.check("k").allowed  # still limited while Redis is down


def test_memory_store_prunes_expired_counters(clock, monkeypatch):
    monkeypatch.setattr(rate_limit, "_MEM_PRUNE_AT", 3)
    rl = RateLimiter(namespace="t", limits=[(MINUTE, 5)])
    for k in ("a", "b", "c"):
        rl.check(k)
    clock.now += 120  # all three counters have expired
    rl.check("d")
    assert len(rl._mem) == 1


# --- client identity ------------------------------------------------------
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("203.0.113.7", "203.0.113.7"),
        (" 203.0.113.7 ", "203.0.113.7"),
        ("2001:db8:1:2:aaaa::1", "2001:db8:1:2::/64"),
        ("2001:db8:1:2:ffff::9", "2001:db8:1:2::/64"),  # same /64 → same key
        ("::ffff:198.51.100.4", "198.51.100.4"),
        ("not-an-ip", ""),
        ("", ""),
        ("203.0.113.7, 10.0.0.1", ""),  # a list is not one address
    ],
)
def test_normalise_ip(raw, expected):
    assert normalise_ip(raw) == expected


def _request(headers: dict[str, str] | None = None, peer: str | None = "10.0.0.5") -> Request:
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": (peer, 1234) if peer else None,
    }
    return Request(scope)


def test_forwarded_ip_used_when_the_key_matches():
    req = _request({PROXY_KEY_HEADER: "s3cret", CLIENT_IP_HEADER: "203.0.113.7"})
    assert client_key(req, "s3cret") == "203.0.113.7"


def test_forwarded_ip_ignored_with_a_wrong_key():
    req = _request({PROXY_KEY_HEADER: "guess", CLIENT_IP_HEADER: "203.0.113.7"})
    assert client_key(req, "s3cret") == "10.0.0.5"


def test_forwarded_ip_ignored_when_no_key_is_configured():
    req = _request({PROXY_KEY_HEADER: "", CLIENT_IP_HEADER: "203.0.113.7"})
    assert client_key(req, "") == "10.0.0.5"


def test_bad_forwarded_ip_falls_back_to_the_peer():
    req = _request({PROXY_KEY_HEADER: "s3cret", CLIENT_IP_HEADER: "nonsense"})
    assert client_key(req, "s3cret") == "10.0.0.5"


def test_no_peer_gives_one_shared_unknown_key():
    assert client_key(_request(peer=None), "") == "unknown"


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (40, "40 seconds"),
        (60, "about 1 minute"),
        (150, "about 2 minutes"),
        (3600, "about 1 hour"),
        (36_000, "about 10 hours"),
    ],
)
def test_wait_text(seconds, text):
    from app.main import _wait_text

    assert _wait_text(seconds) == text
