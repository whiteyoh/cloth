"""Shared utilities for the Cloth application."""
from __future__ import annotations

import hashlib
import json
from contextvars import ContextVar

# Holds the current request's correlation ID.  Set by timing_and_csp_middleware
# in main.py at the start of each request; read by _emit() to tag every log event.
_request_id: ContextVar[str] = ContextVar("request_id", default="")


def _emit(event: dict) -> None:
    rid = _request_id.get()
    if rid:
        event = {**event, "request_id": rid}
    print(json.dumps(event))  # noqa: T201


def _hash_ip(ip: str) -> str:
    """Return a short, non-reversible hash of an IP address for log events."""
    return hashlib.sha256(ip.encode()).hexdigest()[:12]
