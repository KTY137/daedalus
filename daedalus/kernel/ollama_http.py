"""Bounded, effect-agnostic HTTP transport for Gate-0 Ollama offload.

The transport deliberately stops below JSON, model, authority, evidence, and
filesystem concerns.  Its complete job is to turn one already-authorized,
canonical numeric-loopback origin into at most one ``GET /api/tags`` followed
by at most one ``POST /api/chat`` while retaining the exact response bytes.

No ambient proxy configuration is consulted, redirects are never followed,
calls are never retried, and both calls spend one monotonic deadline fixed when
the transport is constructed.  A caller-provided checkpoint is invoked at
every network seam and between bounded reads; it may raise its own cancellation
exception, which is intentionally allowed to propagate unchanged.

This module grants no effect authority.  The executor that eventually calls it
must consume the canonical lease and enforce the plan's request/response
digests, call ceilings, artifact retention, and terminal receipt.
"""
from __future__ import annotations

import http.client
import math
import socket
import threading
import time
from dataclasses import dataclass
from email.message import Message
from typing import BinaryIO, Callable
from urllib.parse import urlsplit

from .contracts import _loopback_ollama_endpoint


_READ_CHUNK_BYTES = 64 * 1024
_ERROR_PREVIEW_BYTES = 256
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})


class _CheckpointRaised(BaseException):
    """Carry a caller exception through transport-only exception translation."""

    def __init__(self, original: BaseException) -> None:
        self.original = original
        super().__init__(str(original))


class OllamaHTTPTransportError(RuntimeError):
    """Base class for bounded transport refusals and failures."""

    def __init__(self, message: str) -> None:
        # The executor uses this conservative fact to distinguish a pre-call
        # refusal from an external result that may require reconciliation.
        self.request_started = False
        super().__init__(message)


class OllamaHTTPConfigurationError(OllamaHTTPTransportError, ValueError):
    """The caller did not supply the exact canonical transport inputs."""


class OllamaHTTPCallOrderError(OllamaHTTPTransportError):
    """A call was repeated or attempted outside ``tags -> chat`` order."""


class OllamaHTTPDeadlineExceeded(OllamaHTTPTransportError, TimeoutError):
    """The one shared monotonic deadline was exhausted."""

    def __init__(
        self,
        message: str,
        *,
        response: "OllamaHTTPResponse | None" = None,
    ) -> None:
        self.response = response
        super().__init__(message)


class OllamaHTTPNetworkError(OllamaHTTPTransportError):
    """The one permitted network attempt failed without an HTTP response."""


class OllamaHTTPProtocolError(OllamaHTTPTransportError):
    """The peer returned framing that cannot be retained unambiguously."""


@dataclass(frozen=True, slots=True)
class OllamaHTTPResponse:
    """One inert HTTP response or bounded response prefix.

    ``body`` is byte-for-byte transport output.  It is deliberately not decoded
    or parsed here.  ``complete`` is false only on a byte-limit refusal, where
    the exception retains either the ``cap + 1`` prefix actually read or an
    empty body when an oversized Content-Length allowed refusal before reading.
    Header order and duplicates are retained as immutable pairs.
    """

    method: str
    url: str
    status: int
    reason: str
    headers: tuple[tuple[str, str], ...]
    body: bytes
    complete: bool = True


class OllamaHTTPResponseTooLarge(OllamaHTTPTransportError):
    """A declared length or bounded read proved the response exceeds its cap."""

    def __init__(
        self,
        *,
        limit: int,
        response: OllamaHTTPResponse,
        declared_content_length: int | None,
    ) -> None:
        self.limit = limit
        self.response = response
        self.declared_content_length = declared_content_length
        if declared_content_length is not None:
            evidence = f"declared {declared_content_length} bytes"
        else:
            evidence = f"read a bounded {len(response.body)}-byte prefix"
        super().__init__(
            f"Ollama HTTP response exceeds {limit} bytes ({evidence})"
        )


class OllamaHTTPStatusError(OllamaHTTPTransportError):
    """A non-success HTTP response with its complete raw result attached."""

    def __init__(self, response: OllamaHTTPResponse) -> None:
        self.response = response
        preview = response.body[:_ERROR_PREVIEW_BYTES].decode(
            "utf-8", errors="replace"
        )
        preview = " ".join(preview.split())
        if len(response.body) > _ERROR_PREVIEW_BYTES:
            preview += "..."
        detail = f": {preview}" if preview else ""
        super().__init__(
            f"HTTP {response.status} from {response.url}{detail}"
        )


class OllamaHTTPRedirectRefused(OllamaHTTPStatusError):
    """A redirect response was retained but its Location was never followed."""


def _response_headers(headers: Message) -> tuple[tuple[str, str], ...]:
    defects = tuple(getattr(headers, "defects", ()) or ())
    if defects:
        kinds = ", ".join(type(defect).__name__ for defect in defects)
        raise OllamaHTTPProtocolError(
            "Ollama HTTP response contains malformed header syntax "
            f"({kinds})"
        )
    raw_items = getattr(headers, "raw_items", None)
    items = raw_items() if callable(raw_items) else headers.items()
    return tuple((str(name), str(value)) for name, value in items)


def _response_framing(headers: Message) -> int | None:
    content_lengths = headers.get_all("Content-Length", failobj=[]) or []
    transfer_encodings = headers.get_all("Transfer-Encoding", failobj=[]) or []
    if content_lengths and transfer_encodings:
        raise OllamaHTTPProtocolError(
            "Ollama HTTP response combines Content-Length and Transfer-Encoding"
        )
    if transfer_encodings:
        if len(transfer_encodings) != 1:
            raise OllamaHTTPProtocolError(
                "Ollama HTTP response contains multiple Transfer-Encoding headers"
            )
        if transfer_encodings[0].strip().lower() != "chunked":
            raise OllamaHTTPProtocolError(
                "Ollama HTTP response uses an unsupported Transfer-Encoding"
            )
        return None
    if not content_lengths:
        return None
    # Multiple framing claims are unnecessary for this loopback protocol and
    # create ambiguity even when their text happens to match.  Refuse them.
    if len(content_lengths) != 1:
        raise OllamaHTTPProtocolError(
            "Ollama HTTP response contains multiple Content-Length headers"
        )
    text = content_lengths[0].strip()
    if not text.isascii() or not text.isdecimal():
        raise OllamaHTTPProtocolError(
            "Ollama HTTP response has an invalid Content-Length"
        )
    return int(text, 10)


def _set_stream_timeout(stream: object, timeout_s: float) -> None:
    """Tighten the live socket timeout to the shared deadline remainder.

    The direct client exposes a ``http.client.HTTPResponse``.  The short
    bounded walk finds its retained socket without depending on a re-openable
    endpoint or global socket defaults.  The watchdog enforces the hard total
    deadline; tightening the live timeout before every body read additionally
    avoids starting a blocking operation with stale remaining time.  Inability
    to bind the live socket is a hard protocol refusal.
    """

    pending = [stream]
    seen: set[int] = set()
    visited_types: list[str] = []
    for _ in range(8):
        if not pending:
            break
        current = pending.pop(0)
        identity = id(current)
        if identity in seen:
            continue
        seen.add(identity)
        visited_types.append(type(current).__name__)
        set_timeout = getattr(current, "settimeout", None)
        if callable(set_timeout):
            try:
                set_timeout(timeout_s)
            except OSError as exc:
                raise OllamaHTTPProtocolError(
                    "could not bind the live response socket to the shared deadline"
                ) from exc
            return
        for attribute in ("fp", "raw", "_sock", "sock"):
            child = getattr(current, attribute, None)
            if child is not None:
                pending.append(child)
    raise OllamaHTTPProtocolError(
        "could not locate the live response socket for shared-deadline reads "
        f"(visited: {', '.join(visited_types) or 'none'})"
    )


class OllamaHTTPTransport:
    """One bounded ``/api/tags`` then ``/api/chat`` loopback session."""

    def __init__(
        self,
        *,
        origin: str,
        deadline_monotonic: float,
        max_response_bytes: int,
        checkpoint: Callable[[], None],
    ) -> None:
        if not isinstance(origin, str):
            raise OllamaHTTPConfigurationError("origin must be a string")
        try:
            canonical_origin = _loopback_ollama_endpoint(origin)
        except (TypeError, ValueError) as exc:
            raise OllamaHTTPConfigurationError(str(exc)) from exc
        if origin != canonical_origin:
            raise OllamaHTTPConfigurationError(
                "origin must already be the exact canonical numeric-loopback origin"
            )
        if (
            isinstance(deadline_monotonic, bool)
            or not isinstance(deadline_monotonic, (int, float))
            or not math.isfinite(float(deadline_monotonic))
        ):
            raise OllamaHTTPConfigurationError(
                "deadline_monotonic must be a finite monotonic timestamp"
            )
        if (
            isinstance(max_response_bytes, bool)
            or not isinstance(max_response_bytes, int)
            or max_response_bytes < 1
        ):
            raise OllamaHTTPConfigurationError(
                "max_response_bytes must be a positive integer"
            )
        if not callable(checkpoint):
            raise OllamaHTTPConfigurationError("checkpoint must be callable")

        self.origin = canonical_origin
        self.max_response_bytes = max_response_bytes
        self._checkpoint = checkpoint
        # The caller owns this absolute deadline so the same value can bound
        # model transport, subsequent filesystem publication, and the real
        # verifier.  Minting a private timeout here would create a second clock.
        self._deadline = float(deadline_monotonic)
        self._state_lock = threading.Lock()
        self._tags_started = False
        self._tags_complete = False
        self._chat_started = False
        self._last_call_request_started = False

    @property
    def deadline_monotonic(self) -> float:
        """The one immutable deadline shared by both permitted calls."""

        return self._deadline

    @property
    def last_call_request_started(self) -> bool:
        """Whether the current/latest call may have put request bytes on TCP.

        Caller checkpoint exceptions propagate as their original objects and
        therefore cannot safely be decorated with transport state.  The
        canonical executor must consult this property whenever such an
        exception escapes a transport call: true requires reconciliation,
        while false proves this call stopped before request transmission.
        The value is reset for each call, so a completed tags request cannot
        taint a pre-request chat cancellation.
        """

        with self._state_lock:
            return self._last_call_request_started

    def remaining_s(self) -> float:
        """Return positive remaining time or fail before another effect starts."""

        remaining = self._deadline - time.monotonic()
        if remaining <= 0:
            raise OllamaHTTPDeadlineExceeded(
                "shared Ollama HTTP deadline was exhausted"
            )
        return remaining

    def _run_checkpoint(self) -> None:
        """Invoke policy cancellation without reclassifying its exception."""

        try:
            self._checkpoint()
        except BaseException as exc:
            raise _CheckpointRaised(exc) from None

    def fetch_tags(self) -> OllamaHTTPResponse:
        """Perform the session's one permitted ``GET /api/tags``."""

        with self._state_lock:
            if self._tags_started:
                raise OllamaHTTPCallOrderError("GET /api/tags may run only once")
            self._tags_started = True
        response = self._request(method="GET", path="/api/tags", body=None)
        with self._state_lock:
            self._tags_complete = True
        return response

    def chat(self, request_body: bytes) -> OllamaHTTPResponse:
        """POST already-frozen JSON bytes exactly once after successful tags."""

        if not isinstance(request_body, bytes):
            raise OllamaHTTPConfigurationError(
                "request_body must be already-frozen bytes"
            )
        with self._state_lock:
            if not self._tags_complete:
                raise OllamaHTTPCallOrderError(
                    "POST /api/chat requires one successful GET /api/tags"
                )
            if self._chat_started:
                raise OllamaHTTPCallOrderError("POST /api/chat may run only once")
            self._chat_started = True
        return self._request(method="POST", path="/api/chat", body=request_body)

    def _request(
        self,
        *,
        method: str,
        path: str,
        body: bytes | None,
    ) -> OllamaHTTPResponse:
        url = self.origin + path
        with self._state_lock:
            self._last_call_request_started = False
        parsed = urlsplit(self.origin)
        host = parsed.hostname
        port = parsed.port
        if host is None or port is None:  # already canonical, defense in depth
            raise OllamaHTTPConfigurationError("canonical origin lost host or port")

        # http.client is used directly instead of urllib's ambient handler
        # stack.  Besides making proxies and redirects impossible, this exposes
        # the one live socket so a deadline watchdog can abort header parsing.
        # A socket timeout alone is insufficient: http.client may perform many
        # header recv operations and a trickling peer can reset that per-op
        # timeout indefinitely.
        self._checkpoint()
        connection = http.client.HTTPConnection(
            host,
            port,
            timeout=self.remaining_s(),
        )
        live_socket: socket.socket | None = None
        deadline_fired = threading.Event()
        watchdog: threading.Timer | None = None
        request_started = False

        def expire() -> None:
            deadline_fired.set()
            if live_socket is None:
                return
            try:
                live_socket.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                live_socket.close()
            except OSError:
                pass

        try:
            connection.connect()
            live_socket = connection.sock
            if live_socket is None:
                raise OllamaHTTPProtocolError(
                    "Ollama HTTP connection did not expose its live socket"
                )
            watchdog = threading.Timer(self.remaining_s(), expire)
            watchdog.daemon = True
            watchdog.start()
            # No caller callback may run while a connected socket is outside
            # the absolute-deadline watchdog.
            self._run_checkpoint()
            # A slow callback may have consumed the budget while the watchdog
            # closed the peer.  Refuse before recording that request bytes may
            # have crossed the socket.
            self.remaining_s()

            connection.putrequest(method, path, skip_accept_encoding=True)
            connection.putheader("Accept", "application/json")
            connection.putheader("Connection", "close")
            if body is not None:
                connection.putheader("Content-Type", "application/json")
                connection.putheader("Content-Length", str(len(body)))
            request_started = True
            with self._state_lock:
                self._last_call_request_started = True
            connection.endheaders(message_body=body)
            response = connection.getresponse()
            self._run_checkpoint()
            self.remaining_s()
            with response:
                result = self._read_response(
                    response,
                    method=method,
                    url=url,
                    status=int(response.status),
                    reason=str(response.reason or ""),
                    headers=response.headers,
                )
            self._run_checkpoint()
            if deadline_fired.is_set() or time.monotonic() >= self._deadline:
                raise OllamaHTTPDeadlineExceeded(
                    f"Ollama HTTP response completed after the shared deadline: {url}",
                    response=result,
                )
        except _CheckpointRaised as exc:
            raise exc.original from None
        except OllamaHTTPTransportError as exc:
            exc.request_started = bool(exc.request_started or request_started)
            raise
        except (TimeoutError, socket.timeout) as exc:
            error = OllamaHTTPDeadlineExceeded(
                f"Ollama HTTP call exceeded the shared deadline: {url}"
            )
            error.request_started = request_started
            raise error from exc
        except http.client.HTTPException as exc:
            if deadline_fired.is_set() or time.monotonic() >= self._deadline:
                error = OllamaHTTPDeadlineExceeded(
                    f"Ollama HTTP call exceeded the shared deadline: {url}"
                )
                error.request_started = request_started
                raise error from exc
            error = OllamaHTTPProtocolError(
                f"Ollama HTTP protocol failure for {url}: {exc}"
            )
            error.request_started = request_started
            raise error from exc
        except OSError as exc:
            if deadline_fired.is_set() or time.monotonic() >= self._deadline:
                error = OllamaHTTPDeadlineExceeded(
                    f"Ollama HTTP call exceeded the shared deadline: {url}"
                )
                error.request_started = request_started
                raise error from exc
            error = OllamaHTTPNetworkError(
                f"Ollama HTTP network failure for {url}: {exc}"
            )
            error.request_started = request_started
            raise error from exc
        finally:
            if watchdog is not None:
                watchdog.cancel()
                # No deadline callback may outlive this effect call.  The
                # callback only closes one already-owned socket and therefore
                # cannot legitimately block once cancellation wins the race.
                watchdog.join()
            connection.close()

        if deadline_fired.is_set() or time.monotonic() >= self._deadline:
            error = OllamaHTTPDeadlineExceeded(
                f"Ollama HTTP result crossed the shared deadline: {url}",
                response=result,
            )
            error.request_started = request_started
            raise error
        if result.status in _REDIRECT_STATUSES:
            error = OllamaHTTPRedirectRefused(result)
            error.request_started = request_started
            raise error
        if not 200 <= result.status < 300:
            error = OllamaHTTPStatusError(result)
            error.request_started = request_started
            raise error
        return result

    def _read_response(
        self,
        stream: BinaryIO,
        *,
        method: str,
        url: str,
        status: int,
        reason: str,
        headers: Message,
    ) -> OllamaHTTPResponse:
        frozen_headers = _response_headers(headers)
        declared_length = _response_framing(headers)
        if declared_length is not None and declared_length > self.max_response_bytes:
            partial = OllamaHTTPResponse(
                method=method,
                url=url,
                status=status,
                reason=reason,
                headers=frozen_headers,
                body=b"",
                complete=False,
            )
            raise OllamaHTTPResponseTooLarge(
                limit=self.max_response_bytes,
                response=partial,
                declared_content_length=declared_length,
            )

        chunks: list[bytes] = []
        total = 0
        read_one = getattr(stream, "read1", None)
        if not callable(read_one):
            raise OllamaHTTPProtocolError(
                "Ollama HTTP response does not expose a single-operation reader"
            )
        while declared_length is None or total < declared_length:
            room = self.max_response_bytes + 1 - total
            if room <= 0:
                break
            self._run_checkpoint()
            remaining = self.remaining_s()
            _set_stream_timeout(stream, remaining)
            read_size = min(_READ_CHUNK_BYTES, room)
            if declared_length is not None:
                read_size = min(read_size, declared_length - total)
            try:
                # HTTPResponse.read1 performs at most one underlying body read.
                # That lets this loop tighten the socket to the new absolute
                # deadline remainder before every subsequent blocking read.
                chunk = read_one(read_size)
            except (TimeoutError, socket.timeout) as exc:
                raise OllamaHTTPDeadlineExceeded(
                    f"Ollama HTTP response exceeded the shared deadline: {url}"
                ) from exc
            self._run_checkpoint()
            self.remaining_s()
            if not chunk:
                break
            if not isinstance(chunk, bytes):
                raise OllamaHTTPProtocolError(
                    "Ollama HTTP response reader returned non-byte content"
                )
            chunks.append(chunk)
            total += len(chunk)
            if total > self.max_response_bytes:
                partial = OllamaHTTPResponse(
                    method=method,
                    url=url,
                    status=status,
                    reason=reason,
                    headers=frozen_headers,
                    body=b"".join(chunks),
                    complete=False,
                )
                raise OllamaHTTPResponseTooLarge(
                    limit=self.max_response_bytes,
                    response=partial,
                    declared_content_length=declared_length,
                )
            # A known-length response is complete without one speculative read
            # on a socket http.client has already closed.  Chunked and
            # close-delimited responses continue until read1 returns EOF.
            if declared_length is not None and total == declared_length:
                break

        body = b"".join(chunks)
        if declared_length is not None and len(body) != declared_length:
            raise OllamaHTTPProtocolError(
                "Ollama HTTP response ended before its declared Content-Length"
            )
        return OllamaHTTPResponse(
            method=method,
            url=url,
            status=status,
            reason=reason,
            headers=frozen_headers,
            body=body,
        )


__all__ = [
    "OllamaHTTPCallOrderError",
    "OllamaHTTPConfigurationError",
    "OllamaHTTPDeadlineExceeded",
    "OllamaHTTPNetworkError",
    "OllamaHTTPProtocolError",
    "OllamaHTTPRedirectRefused",
    "OllamaHTTPResponse",
    "OllamaHTTPResponseTooLarge",
    "OllamaHTTPStatusError",
    "OllamaHTTPTransport",
    "OllamaHTTPTransportError",
]
