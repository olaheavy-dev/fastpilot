"""Frontend side of issue #12: the visitor's address is forwarded with the shared key."""

from __future__ import annotations

from types import SimpleNamespace

import api_client
import pytest
import visitor


@pytest.fixture(autouse=True)
def _reset_provider():
    yield
    api_client.set_client_ip_provider(lambda: "")


class _Resp:
    ok = True
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {}


def test_no_headers_without_a_key(monkeypatch):
    monkeypatch.delenv("FRONTEND_PROXY_KEY", raising=False)
    api_client.set_client_ip_provider(lambda: "203.0.113.7")
    assert api_client.identity_headers() == {}


def test_no_headers_without_an_address(monkeypatch):
    monkeypatch.setenv("FRONTEND_PROXY_KEY", "k")
    assert api_client.identity_headers() == {}


def test_provider_error_sends_nothing(monkeypatch):
    monkeypatch.setenv("FRONTEND_PROXY_KEY", "k")

    def boom():
        raise RuntimeError("no context")

    api_client.set_client_ip_provider(boom)
    assert api_client.identity_headers() == {}


def test_execute_and_query_send_address_and_key(monkeypatch):
    monkeypatch.setenv("FRONTEND_PROXY_KEY", "k")
    api_client.set_client_ip_provider(lambda: "203.0.113.7")
    sent = []
    monkeypatch.setattr(api_client.requests, "post", lambda *a, **kw: sent.append(kw["headers"]) or _Resp())
    api_client.execute_code("print(1)")
    api_client.fix_code("x", "err")
    api_client.send_query("hi")
    want = {"X-FastPilot-Client-IP": "203.0.113.7", "X-FastPilot-Proxy-Key": "k"}
    assert sent == [want, want, want]


def _fake_st(headers=None, ip=None):
    return SimpleNamespace(context=SimpleNamespace(headers=headers or {}, ip_address=ip))


def test_visitor_ip_prefers_the_proxy_header(monkeypatch):
    monkeypatch.delenv("VISITOR_IP_HEADER", raising=False)
    monkeypatch.setattr(visitor, "st", _fake_st({"CF-Connecting-IP": " 203.0.113.7 "}, "10.0.0.2"))
    assert visitor.visitor_ip() == "203.0.113.7"


def test_visitor_ip_falls_back_to_the_connection(monkeypatch):
    monkeypatch.setattr(visitor, "st", _fake_st({}, "198.51.100.9"))
    assert visitor.visitor_ip() == "198.51.100.9"


def test_visitor_ip_header_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("VISITOR_IP_HEADER", "")
    monkeypatch.setattr(visitor, "st", _fake_st({"CF-Connecting-IP": "203.0.113.7"}, None))
    assert visitor.visitor_ip() == ""


def test_visitor_ip_never_raises(monkeypatch):
    monkeypatch.setattr(visitor, "st", SimpleNamespace())  # no st.context at all
    assert visitor.visitor_ip() == ""
