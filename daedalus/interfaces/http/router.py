"""Pure parsing for legacy HTTP request targets."""
from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse


@dataclass(frozen=True)
class RequestTarget:
    """Parsed request target with the path deliberately left percent-encoded.

    PUT and POST historically split the raw path before decoding individual
    segments. Keeping that order preserves encoded-slash behavior.
    """

    path: str
    query: dict[str, list[str]]


def parse_request_target(raw_target: str) -> RequestTarget:
    parsed = urlparse(raw_target)
    return RequestTarget(path=parsed.path, query=parse_qs(parsed.query))
