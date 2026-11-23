"""The visitor's address, for the backend's rate limits (issue #12).

The browser talks to Streamlit, and Streamlit's server calls the backend, so the backend
can't see who the visitor is. This module reads the visitor's address from the request
that opened this Streamlit session, and ``api_client`` forwards it with a shared key.

``VISITOR_IP_HEADER`` names the header the reverse proxy sets (default Cloudflare's
``CF-Connecting-IP``). Only trust it when the frontend can be reached through that
proxy alone: anyone who reaches Streamlit directly can set the header to any value.
Without the header, we fall back to the address of the connection itself.
"""

from __future__ import annotations

import os

import streamlit as st


def visitor_ip() -> str:
    header = os.environ.get("VISITOR_IP_HEADER", "CF-Connecting-IP")
    try:
        if header:
            value = st.context.headers.get(header)
            if value:
                return value.strip()
        return st.context.ip_address or ""
    except Exception:  # noqa: BLE001 - st.context may be absent (e.g. AppTest); never break a request
        return ""
