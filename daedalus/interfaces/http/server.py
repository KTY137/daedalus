"""Host-bind admission for the local HTTP interface.

This module decides whether bytes may leave the machine and validates the
desktop parent nonce.  Socket creation and the registered CLI/effect doors stay
in :mod:`daedalus.web_api`; this owner has no server, process, ledger, provider,
or network side effect at import time.
"""
from __future__ import annotations

import os
import re


ALLOW_REMOTE_ENV = "DAEDALUS_WEB_ALLOW_REMOTE_CLIENTS"
AUTH_TOKEN_ENV = "DAEDALUS_WEB_TOKEN"
DESKTOP_STARTUP_NONCE_ENV = "DAEDALUS_DESKTOP_STARTUP_NONCE"
MIN_AUTH_TOKEN_CHARS = 32


class NonLoopbackBindRefused(RuntimeError):
    """A non-local HTTP bind was not explicitly and safely authorized."""


def desktop_startup_nonce() -> str:
    """Return the parent-issued desktop nonce or refuse malformed evidence."""

    nonce = os.environ.get(DESKTOP_STARTUP_NONCE_ENV, "").strip()
    if nonce and not re.fullmatch(r"[0-9a-f]{64}", nonce):
        raise ValueError(
            f"{DESKTOP_STARTUP_NONCE_ENV} must be exactly 64 lowercase hex characters"
        )
    return nonce


def refusal(host: str, why: str, remedy: str) -> str:
    """Render the stable fail-closed bind diagnostic."""

    return (
        f"REFUSED: daedalus web will not serve {host!r}.\n\n"
        f"{why}\n\n"
        f"This server has NO AUTHENTICATION on its loopback path, because on "
        f"loopback the operating system is the boundary. Every endpoint is "
        f"reachable by anyone who can reach the port: the spine ledger (what "
        f"the loop has attempted), the picker queue (what it is working on), "
        f"PUT endpoints that rewrite agent roles, and POST endpoints that "
        f"queue work and invoke models -- that last one is remote SPEND, not "
        f"just remote read. ADR-002 rejected a subsystem for being exactly "
        f"this shape: an independent, unauthenticated network server.\n\n"
        f"The server was NOT started, and it was NOT quietly downgraded to "
        f"loopback.\n\n{remedy}"
    )


def resolve_bind(host: str, allow_remote_clients: bool) -> str:
    """Return the request token for an admitted bind, otherwise refuse.

    An empty result is valid only for a numeric loopback literal.  A non-local
    bind requires both explicit opt-in and a sufficiently long bearer token.
    Egress trust declarations never widen this ingress boundary.
    """

    from ...sensitivity import is_loopback_host

    host = str(host or "").strip()
    if is_loopback_host(host):
        return ""

    if not (
        allow_remote_clients
        or os.environ.get(ALLOW_REMOTE_ENV, "").strip().lower()
        in ("1", "true", "yes")
    ):
        named = repr(host) if host else "an empty host (every interface)"
        raise NonLoopbackBindRefused(
            refusal(
                host or "",
                f"{named} is not this machine. sensitivity.lane_for_host reports "
                f"it as UNTRUSTED, which in this project means 'bytes leave this "
                f"host'.",
                f"  * to serve this machine only:  --host 127.0.0.1  (the default)\n"
                f"  * 'localhost' is refused ON PURPOSE: it is a NAME, and a name "
                f"that resolves to loopback when it is checked can resolve "
                f"elsewhere when it is connected. Use the numeric literal.\n"
                f"  * to genuinely serve other machines, opt in explicitly AND "
                f"authenticate:\n"
                f"        set {AUTH_TOKEN_ENV} to a secret of at least "
                f"{MIN_AUTH_TOKEN_CHARS} characters\n"
                f"        pass --allow-remote-clients (or {ALLOW_REMOTE_ENV}=1)\n"
                f"    every request must then carry "
                f"'Authorization: Bearer <token>'.",
            )
        )

    token = os.environ.get(AUTH_TOKEN_ENV, "").strip()
    if len(token) < MIN_AUTH_TOKEN_CHARS:
        state = "is not set" if not token else f"is only {len(token)} characters long"
        raise NonLoopbackBindRefused(
            refusal(
                host,
                f"--allow-remote-clients was given, but {AUTH_TOKEN_ENV} {state}. "
                f"An opt-in is a decision to expose this, not a decision to expose "
                f"it to ANYONE -- so the escape hatch carries authentication with "
                f"it and cannot be opened without.",
                f"  * set {AUTH_TOKEN_ENV} to at least {MIN_AUTH_TOKEN_CHARS} "
                f"characters and try again.",
            )
        )
    return token


__all__ = [
    "ALLOW_REMOTE_ENV",
    "AUTH_TOKEN_ENV",
    "DESKTOP_STARTUP_NONCE_ENV",
    "MIN_AUTH_TOKEN_CHARS",
    "NonLoopbackBindRefused",
    "desktop_startup_nonce",
    "refusal",
    "resolve_bind",
]
