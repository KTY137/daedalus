"""Real-loopback tests for the bounded Gate-0 Ollama HTTP transport.

These tests never replace ``urlopen`` or the transport opener.  Every request
crosses a real ephemeral TCP listener so proxy handling, redirect behavior,
exact POST bytes, response framing, socket deadlines, and call counts are
measured through the stdlib HTTP stack used in production.
"""
from __future__ import annotations

import os
import socket
import threading
import time
import unittest
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable
from unittest import mock

from daedalus.kernel.ollama_http import (
    OllamaHTTPCallOrderError,
    OllamaHTTPConfigurationError,
    OllamaHTTPDeadlineExceeded,
    OllamaHTTPProtocolError,
    OllamaHTTPRedirectRefused,
    OllamaHTTPResponseTooLarge,
    OllamaHTTPStatusError,
    OllamaHTTPTransport,
    _set_stream_timeout,
)


@dataclass(frozen=True)
class _Reply:
    status: int = 200
    body: bytes = b""
    headers: tuple[tuple[str, str], ...] = ()
    chunked: bool = False
    chunks: tuple[bytes, ...] = ()
    delay_before_headers_s: float = 0.0
    delay_between_chunks_s: float = 0.0
    auto_content_length: bool = True
    raw_header_chunks: tuple[bytes, ...] = ()


class _QuietThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request, client_address):  # noqa: ANN001
        # Timeout/oversize tests deliberately close while the handler still has
        # bytes to write.  The client refusal is the assertion; server-side
        # BrokenPipe/ConnectionReset noise would obscure it.
        return None


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _serve(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        request = {
            "method": self.command,
            "path": self.path,
            "headers": tuple(self.headers.raw_items()),
            "body": body,
        }
        reply = self.server.take(request)
        if reply.delay_before_headers_s:
            time.sleep(reply.delay_before_headers_s)
        if reply.raw_header_chunks:
            for chunk in reply.raw_header_chunks:
                self.wfile.write(chunk)
                self.wfile.flush()
                if reply.delay_between_chunks_s:
                    time.sleep(reply.delay_between_chunks_s)
            return
        self.send_response(reply.status)
        for name, value in reply.headers:
            self.send_header(name, value)
        if reply.chunked:
            self.send_header("Transfer-Encoding", "chunked")
        elif (
            reply.auto_content_length
            and not any(name.lower() == "content-length" for name, _ in reply.headers)
        ):
            self.send_header("Content-Length", str(len(reply.body)))
        self.end_headers()
        if reply.chunked:
            chunks = reply.chunks or (reply.body,)
            for chunk in chunks:
                self.wfile.write(f"{len(chunk):x}\r\n".encode("ascii"))
                self.wfile.write(chunk)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                if reply.delay_between_chunks_s:
                    time.sleep(reply.delay_between_chunks_s)
            self.wfile.write(b"0\r\n\r\n")
        else:
            self.wfile.write(reply.body)
        self.wfile.flush()

    do_GET = _serve
    do_POST = _serve

    def log_message(self, *_args) -> None:
        return None


class _LocalOllama:
    def __init__(self, replies: list[_Reply]) -> None:
        self._replies = list(replies)
        self._lock = threading.Lock()
        self.requests: list[dict[str, object]] = []

    def __enter__(self) -> "_LocalOllama":
        server = _QuietThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        server.owner = self

        def take(request: dict[str, object]) -> _Reply:
            with self._lock:
                self.requests.append(request)
                if self._replies:
                    return self._replies.pop(0)
            return _Reply(status=599, body=b"unexpected extra request")

        server.take = take
        self._server = server
        self.origin = f"http://127.0.0.1:{server.server_port}"
        self._thread = threading.Thread(
            target=server.serve_forever,
            kwargs={"poll_interval": 0.01},
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=1.0)


def _transport(
    origin: str,
    *,
    timeout_s: float = 2.0,
    cap: int = 1024,
    checkpoint: Callable[[], None] = lambda: None,
) -> OllamaHTTPTransport:
    return OllamaHTTPTransport(
        origin=origin,
        deadline_monotonic=time.monotonic() + timeout_s,
        max_response_bytes=cap,
        checkpoint=checkpoint,
    )


class OllamaHTTPConfigurationTests(unittest.TestCase):
    def test_only_exact_canonical_numeric_loopback_origin_is_accepted(self) -> None:
        invalid = (
            "http://localhost:11434",
            "http://127.0.0.1:11434/",
            "https://127.0.0.1:11434",
            "http://127.0.0.2:11434",
            "http://127.0.0.1",
        )
        for origin in invalid:
            with self.subTest(origin=origin):
                with self.assertRaises(OllamaHTTPConfigurationError):
                    _transport(origin)

    def test_chat_requires_successful_tags_and_frozen_bytes(self) -> None:
        with _LocalOllama([_Reply(body=b"tags")]) as server:
            transport = _transport(server.origin)
            with self.assertRaises(OllamaHTTPCallOrderError):
                transport.chat(b"{}")
            transport.fetch_tags()
            with self.assertRaises(OllamaHTTPConfigurationError):
                transport.chat(bytearray(b"{}"))  # type: ignore[arg-type]
        self.assertEqual(len(server.requests), 1)

    def test_shared_deadline_socket_binding_fails_closed(self) -> None:
        with self.assertRaisesRegex(OllamaHTTPProtocolError, "locate"):
            _set_stream_timeout(object(), 0.1)

        closed_socket = socket.socket()
        closed_socket.close()
        with self.assertRaisesRegex(OllamaHTTPProtocolError, "bind"):
            _set_stream_timeout(closed_socket, 0.1)


class OllamaHTTPRealServerTests(unittest.TestCase):
    def test_proxy_environment_is_ignored_and_raw_tags_are_inert(self) -> None:
        raw = b"\xffnot-json-and-not-utf8"
        checkpoints: list[int] = []

        def checkpoint() -> None:
            checkpoints.append(len(checkpoints) + 1)

        proxy_environment = {
            "HTTP_PROXY": "http://127.0.0.1:1",
            "HTTPS_PROXY": "http://127.0.0.1:1",
            "http_proxy": "http://127.0.0.1:1",
            "https_proxy": "http://127.0.0.1:1",
            "NO_PROXY": "",
            "no_proxy": "",
        }
        with _LocalOllama(
            [_Reply(body=raw, headers=(("X-Proof", "raw"),))]
        ) as server:
            with mock.patch.dict(os.environ, proxy_environment, clear=False):
                transport = _transport(server.origin, checkpoint=checkpoint)
                response = transport.fetch_tags()

            self.assertEqual(response.status, 200)
            self.assertEqual(response.body, raw)
            self.assertTrue(response.complete)
            self.assertIn(("X-Proof", "raw"), response.headers)
            self.assertEqual(server.requests[0]["method"], "GET")
            self.assertEqual(server.requests[0]["path"], "/api/tags")
            with self.assertRaises(OllamaHTTPCallOrderError):
                transport.fetch_tags()

        self.assertEqual(len(server.requests), 1)
        self.assertGreaterEqual(len(checkpoints), 3)

    def test_tags_then_chat_posts_the_exact_frozen_bytes_once(self) -> None:
        request_body = b'{"z":1, "literal":"\\u2603", "spacing": true}'
        chat_response = b"\x00raw-chat-response"
        with _LocalOllama(
            [_Reply(body=b"raw-tags"), _Reply(body=chat_response)]
        ) as server:
            transport = _transport(server.origin)
            tags = transport.fetch_tags()
            chat = transport.chat(request_body)
            with self.assertRaises(OllamaHTTPCallOrderError):
                transport.chat(request_body)

        self.assertEqual(tags.body, b"raw-tags")
        self.assertEqual(chat.body, chat_response)
        self.assertEqual(len(server.requests), 2)
        post = server.requests[1]
        self.assertEqual(post["method"], "POST")
        self.assertEqual(post["path"], "/api/chat")
        self.assertEqual(post["body"], request_body)
        headers = {str(k).lower(): v for k, v in post["headers"]}
        self.assertEqual(headers["content-type"], "application/json")
        self.assertEqual(int(headers["content-length"]), len(request_body))

    def test_redirect_is_retained_and_never_followed(self) -> None:
        with _LocalOllama(
            [
                _Reply(
                    status=302,
                    body=b"move",
                    headers=(("Location", "/redirect-target"),),
                ),
                _Reply(body=b"must-not-be-reached"),
            ]
        ) as server:
            transport = _transport(server.origin)
            with self.assertRaises(OllamaHTTPRedirectRefused) as caught:
                transport.fetch_tags()

        response = caught.exception.response
        self.assertEqual(response.status, 302)
        self.assertEqual(response.body, b"move")
        self.assertIn(("Location", "/redirect-target"), response.headers)
        self.assertEqual(
            [(request["method"], request["path"]) for request in server.requests],
            [("GET", "/api/tags")],
        )

    def test_declared_oversize_refuses_before_reading_body(self) -> None:
        cap = 8
        with _LocalOllama([_Reply(body=b"x" * (cap + 1))]) as server:
            transport = _transport(server.origin, cap=cap)
            with self.assertRaises(OllamaHTTPResponseTooLarge) as caught:
                transport.fetch_tags()

        error = caught.exception
        self.assertEqual(error.limit, cap)
        self.assertEqual(error.declared_content_length, cap + 1)
        self.assertEqual(error.response.status, 200)
        self.assertEqual(error.response.body, b"")
        self.assertFalse(error.response.complete)
        self.assertEqual(len(server.requests), 1)

    def test_chunked_oversize_retains_exactly_cap_plus_one_bytes(self) -> None:
        cap = 8
        with _LocalOllama(
            [
                _Reply(
                    chunked=True,
                    chunks=(b"12345", b"67890", b"unread-tail"),
                )
            ]
        ) as server:
            transport = _transport(server.origin, cap=cap)
            with self.assertRaises(OllamaHTTPResponseTooLarge) as caught:
                transport.fetch_tags()

        error = caught.exception
        self.assertIsNone(error.declared_content_length)
        self.assertEqual(error.response.body, b"123456789")
        self.assertEqual(len(error.response.body), cap + 1)
        self.assertFalse(error.response.complete)
        self.assertEqual(len(server.requests), 1)

    def test_http_error_retains_raw_body_and_is_not_retried(self) -> None:
        raw_error = b"\xff" + (b"bench-unavailable-" * 50)
        with _LocalOllama(
            [_Reply(status=503, body=raw_error), _Reply(body=b"retry-would-pass")]
        ) as server:
            transport = _transport(server.origin)
            with self.assertRaises(OllamaHTTPStatusError) as caught:
                transport.fetch_tags()

        response = caught.exception.response
        self.assertEqual(response.status, 503)
        self.assertEqual(response.body, raw_error)
        self.assertTrue(response.complete)
        self.assertIn("HTTP 503", str(caught.exception))
        self.assertLess(len(str(caught.exception)), 400)
        self.assertEqual(len(server.requests), 1)

    def test_chunked_http_error_is_bounded_by_the_same_cap(self) -> None:
        cap = 5
        with _LocalOllama(
            [
                _Reply(
                    status=500,
                    chunked=True,
                    chunks=(b"abc", b"def", b"unread-tail"),
                )
            ]
        ) as server:
            transport = _transport(server.origin, cap=cap)
            with self.assertRaises(OllamaHTTPResponseTooLarge) as caught:
                transport.fetch_tags()

        self.assertEqual(caught.exception.response.status, 500)
        self.assertEqual(caught.exception.response.body, b"abcdef")
        self.assertEqual(len(caught.exception.response.body), cap + 1)
        self.assertEqual(len(server.requests), 1)

    def test_ambiguous_or_unsupported_response_framing_is_refused(self) -> None:
        cases = {
            "content-length-plus-transfer-encoding": (
                ("Content-Length", "3"),
                ("Transfer-Encoding", "chunked"),
            ),
            "duplicate-transfer-encoding": (
                ("Transfer-Encoding", "chunked"),
                ("Transfer-Encoding", "chunked"),
            ),
            "unsupported-transfer-encoding": (
                ("Transfer-Encoding", "gzip"),
            ),
            "multiple-transfer-codings": (
                ("Transfer-Encoding", "gzip, chunked"),
            ),
        }
        for label, headers in cases.items():
            with self.subTest(label=label):
                with _LocalOllama(
                    [
                        _Reply(
                            body=b"abc",
                            headers=headers,
                            auto_content_length=False,
                        )
                    ]
                ) as server:
                    transport = _transport(server.origin)
                    with self.assertRaises(OllamaHTTPProtocolError):
                        transport.fetch_tags()
                self.assertEqual(len(server.requests), 1)

    def test_malformed_header_blocks_are_rejected_instead_of_silently_dropped(
        self,
    ) -> None:
        raw_responses = {
            "space-before-colon": (
                b"HTTP/1.1 200 OK\r\nContent-Length : 3\r\n\r\nabc"
            ),
            "header-without-colon": (
                b"HTTP/1.1 200 OK\r\nBadHeader\r\nContent-Length: 3\r\n\r\nabc"
            ),
            "hidden-conflicting-length": (
                b"HTTP/1.1 200 OK\r\nContent-Length: 3\r\n"
                b"Content-Length : 4\r\n\r\nabc"
            ),
        }
        for label, raw in raw_responses.items():
            with self.subTest(label=label):
                with _LocalOllama(
                    [_Reply(raw_header_chunks=(raw,))]
                ) as server:
                    with self.assertRaisesRegex(
                        OllamaHTTPProtocolError, "malformed header syntax"
                    ) as caught:
                        _transport(server.origin).fetch_tags()
                self.assertTrue(caught.exception.request_started)
                self.assertEqual(len(server.requests), 1)

    def test_both_calls_share_one_deadline_and_second_never_starts_when_spent(self) -> None:
        with _LocalOllama(
            [_Reply(body=b"tags"), _Reply(body=b"must-not-be-called")]
        ) as server:
            transport = _transport(server.origin, timeout_s=0.20)
            transport.fetch_tags()
            time.sleep(0.25)
            with self.assertRaises(OllamaHTTPDeadlineExceeded):
                transport.chat(b"{}")

        self.assertEqual(len(server.requests), 1)

    def test_socket_wait_is_bounded_by_shared_deadline(self) -> None:
        with _LocalOllama(
            [_Reply(body=b"too-late", delay_before_headers_s=1.00)]
        ) as server:
            transport = _transport(server.origin, timeout_s=0.15)
            started = time.monotonic()
            with self.assertRaises(OllamaHTTPDeadlineExceeded):
                transport.fetch_tags()
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.75)
        self.assertEqual(len(server.requests), 1)

    def test_header_trickle_cannot_reset_the_shared_deadline(self) -> None:
        # Each write arrives faster than the original per-operation timeout.
        # A plain HTTPConnection/urllib timeout therefore lets this response
        # exceed the total budget; the live-socket deadline watchdog must cut
        # it off while headers are still being parsed.
        chunks = (
            b"HTTP/1.1 200 OK\r\n",
            b"X-Trickle-1: one\r\n",
            b"X-Trickle-2: two\r\n",
            b"X-Trickle-3: three\r\n",
            b"Content-Length: 2\r\n\r\n{}",
        )
        with _LocalOllama(
            [
                _Reply(
                    raw_header_chunks=chunks,
                    delay_between_chunks_s=0.08,
                )
            ]
        ) as server:
            transport = _transport(server.origin, timeout_s=0.22)
            started = time.monotonic()
            with self.assertRaises(OllamaHTTPDeadlineExceeded):
                transport.fetch_tags()
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.60)
        self.assertEqual(len(server.requests), 1)

    def test_chunk_trickle_cannot_reset_the_shared_deadline(self) -> None:
        with _LocalOllama(
            [
                _Reply(
                    chunked=True,
                    chunks=(b"x",) * 10,
                    delay_between_chunks_s=0.08,
                )
            ]
        ) as server:
            transport = _transport(server.origin, timeout_s=0.22, cap=100)
            started = time.monotonic()
            with self.assertRaises(OllamaHTTPDeadlineExceeded):
                transport.fetch_tags()
            elapsed = time.monotonic() - started

        self.assertLess(elapsed, 0.60)
        self.assertEqual(len(server.requests), 1)

    def test_checkpoint_runs_between_bounded_read_chunks(self) -> None:
        calls: list[int] = []

        def checkpoint() -> None:
            calls.append(len(calls) + 1)

        body = b"x" * (130 * 1024)
        with _LocalOllama([_Reply(body=body)]) as server:
            response = _transport(
                server.origin,
                cap=140 * 1024,
                checkpoint=checkpoint,
            ).fetch_tags()

        self.assertEqual(response.body, body)
        self.assertGreaterEqual(len(calls), 7)
        self.assertEqual(len(server.requests), 1)

    def test_checkpoint_exception_during_read_propagates_without_retry(self) -> None:
        class Halted(RuntimeError):
            pass

        calls = 0

        def checkpoint() -> None:
            nonlocal calls
            calls += 1
            if calls == 4:
                raise Halted("stop")

        with _LocalOllama(
            [_Reply(body=b"body"), _Reply(body=b"retry-must-not-run")]
        ) as server:
            transport = _transport(server.origin, checkpoint=checkpoint)
            with self.assertRaisesRegex(Halted, "stop"):
                transport.fetch_tags()

        self.assertEqual(len(server.requests), 1)

    def test_checkpoint_timeout_and_oserror_propagate_without_reclassification(
        self,
    ) -> None:
        exception_cases = (
            TimeoutError("policy timeout"),
            OSError("kill-switch unavailable"),
        )
        for original in exception_cases:
            with self.subTest(kind=type(original).__name__):
                calls = 0

                def checkpoint() -> None:
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        raise original

                with _LocalOllama([_Reply(body=b"must-not-complete")]) as server:
                    transport = _transport(server.origin, checkpoint=checkpoint)
                    with self.assertRaises(type(original)) as caught:
                        transport.fetch_tags()

                self.assertIs(caught.exception, original)
                self.assertFalse(transport.last_call_request_started)
                self.assertEqual(server.requests, [])

    def test_checkpoint_exception_after_request_has_external_phase_evidence(
        self,
    ) -> None:
        original = OSError("kill-switch failed after request")
        calls = 0

        def checkpoint() -> None:
            nonlocal calls
            calls += 1
            if calls == 3:
                raise original

        with _LocalOllama([_Reply(body=b"response")]) as server:
            transport = _transport(server.origin, checkpoint=checkpoint)
            with self.assertRaises(OSError) as caught:
                transport.fetch_tags()

        self.assertIs(caught.exception, original)
        self.assertTrue(transport.last_call_request_started)
        self.assertEqual(len(server.requests), 1)

    def test_slow_post_connect_checkpoint_expires_before_request_start(self) -> None:
        calls = 0

        def checkpoint() -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                time.sleep(0.16)

        with _LocalOllama([_Reply(body=b"must-not-run")]) as server:
            transport = _transport(
                server.origin,
                timeout_s=0.08,
                checkpoint=checkpoint,
            )
            with self.assertRaises(OllamaHTTPDeadlineExceeded) as caught:
                transport.fetch_tags()

        self.assertFalse(caught.exception.request_started)
        self.assertFalse(transport.last_call_request_started)
        self.assertEqual(server.requests, [])

    def test_response_failures_report_that_request_may_have_started(self) -> None:
        with _LocalOllama([_Reply(status=503, body=b"unavailable")]) as server:
            transport = _transport(server.origin)
            with self.assertRaises(OllamaHTTPStatusError) as caught:
                transport.fetch_tags()
        self.assertTrue(caught.exception.request_started)
        self.assertTrue(transport.last_call_request_started)

    def test_checkpoint_refusal_before_network_start_makes_no_request(self) -> None:
        class Halted(RuntimeError):
            pass

        def checkpoint() -> None:
            raise Halted("pre-network stop")

        with _LocalOllama([_Reply(body=b"must-not-run")]) as server:
            transport = _transport(server.origin, checkpoint=checkpoint)
            with self.assertRaisesRegex(Halted, "pre-network stop"):
                transport.fetch_tags()

        self.assertEqual(server.requests, [])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
