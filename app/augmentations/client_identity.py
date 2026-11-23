"""Work out which visitor a request comes from, for rate limiting (issue #12).

The browser never talks to the backend. It talks to the Streamlit frontend, and the
frontend's server calls the backend. So the backend's own view of the caller is always
the frontend container. The frontend therefore reads the visitor's address (from
Cloudflare's ``CF-Connecting-IP`` header) and passes it on in ``X-FastPilot-Client-IP``,
together with a shared secret in ``X-FastPilot-Proxy-Key``.

The backend believes the forwarded address only when the secret matches
``FRONTEND_PROXY_KEY``. In every other case it uses the address of the connection
itself. A client can therefore never pick its own rate-limit key.

IPv6 addresses are grouped by their /64 block, because one home or phone connection is
usually given a whole /64 and can switch address inside it freely.
"""

from __future__ import annotations

import hmac
import ipaddress

from starlette.requests import Request

CLIENT_IP_HEADER = "X-FastPilot-Client-IP"
PROXY_KEY_HEADER = "X-FastPilot-Proxy-Key"


def normalise_ip(raw: str) -> str:
    """Return the rate-limit form of an address, or ``""`` when it isn't one.

    IPv4 stays as it is; IPv6 becomes its /64 network; an IPv4-mapped IPv6 address
    (``::ffff:1.2.3.4``) becomes the plain IPv4 address.
    """
    try:
        ip = ipaddress.ip_address((raw or "").strip())
    except ValueError:
        return ""
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.IPv6Network(f"{ip}/64", strict=False))
    return str(ip)


def client_key(request: Request, proxy_key: str) -> str:
    """The rate-limit key for this request: the visitor's address, never a client-chosen id."""
    if proxy_key:
        sent = request.headers.get(PROXY_KEY_HEADER, "")
        if sent and hmac.compare_digest(sent.encode(), proxy_key.encode()):
            forwarded = normalise_ip(request.headers.get(CLIENT_IP_HEADER, ""))
            if forwarded:
                return forwarded
    peer = request.client.host if request.client else ""
    return normalise_ip(peer) or "unknown"
