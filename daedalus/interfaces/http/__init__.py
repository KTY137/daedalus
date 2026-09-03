"""HTTP compatibility surface for the Daedalus web API.

The registered effect targets intentionally remain in :mod:`daedalus.interfaces.http.web_api`.
This package exposes those exact objects lazily while implementation modules
below it own route parsing, read projections, mutations, SSE delivery, and
host-bind admission.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

_COMPAT_EXPORTS = frozenset({
    "ALLOW_REMOTE_ENV",
    "AUTH_TOKEN_ENV",
    "DESKTOP_STARTUP_NONCE_ENV",
    "MIN_AUTH_TOKEN_CHARS",
    "DaedalusHandler",
    "NonLoopbackBindRefused",
    "main",
    "run",
    "_desktop_startup_nonce",
    "_json_safe",
    "_read_body",
    "_resolve_bind",
})

__all__ = tuple(sorted(_COMPAT_EXPORTS))


def __getattr__(name: str) -> Any:
    """Resolve legacy exports without creating a second HTTP authority."""

    if name not in _COMPAT_EXPORTS:
        raise AttributeError(name)
    legacy = import_module("daedalus.interfaces.http.web_api")
    return getattr(legacy, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | _COMPAT_EXPORTS)
