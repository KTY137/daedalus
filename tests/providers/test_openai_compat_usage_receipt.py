"""G1-EVAL-USAGE-01 -- provider-reported token usage reaches the caller with provenance.

``chat_completion_receipt`` is ``chat_completion`` with the parsed ``usage``
block, its raw canonical JSON and digest, and the endpoint identity attached.
``chat_completion`` itself is unchanged in signature and return value: it is
now ``chat_completion_receipt(...).text``.

Three classifications are pinned here and must never blur into one another:

* ``reported``  -- both primary counters present, non-bool ints >= 0, and a
  present ``total_tokens`` equals their sum;
* ``absent``    -- no ``usage`` key, ``null``, ``{}``, or a details-only block;
* ``malformed`` -- anything else. A self-inconsistent report is not a
  measurement; it is retained raw and never typed.

Every server below is a loopback ``http.server`` in the same shape as
``tests/providers/test_openai_compat_cancellation.py``.
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
import json
import re
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

from daedalus.providers import _openai_compat as compat
from daedalus.providers._openai_compat import (
    PROVIDER_TOKENIZER_UNKNOWN,
    ChatReceipt,
    ProviderCancelled,
    ProviderUsage,
    chat_completion,
    chat_completion_receipt,
    parse_usage,
)

REPORTED_USAGE = {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}


def _reply(content: Any = "the answer", **top: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": "m-served",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
    }
    payload.update(top)
    return payload


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


@contextmanager
def reply_server(payload: dict[str, Any] | bytes, *, delay_s: float = 0.0):
    """A loopback endpoint that records request bodies and answers ``payload``.

    ``delay_s`` stalls before the status line -- the measured production shape
    of a non-streaming completion -- so the cancellation test parks the caller
    inside ``urlopen`` exactly as G1-KERNEL-02 measured it.
    """
    body = payload if isinstance(payload, bytes) else json.dumps(payload).encode("utf-8")
    state: dict[str, Any] = {"requests": 0, "payloads": [], "release": threading.Event()}

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self) -> None:  # noqa: N802 - stdlib naming
            state["requests"] += 1
            length = int(self.headers.get("Content-Length") or 0)
            state["payloads"].append(self.rfile.read(length))
            try:
                if delay_s:
                    state["release"].wait(delay_s)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except OSError:
                pass  # an abandoned client is the point of the cancellation test

        def log_message(self, *args: object) -> None:
            pass

    class Server(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, *args: object) -> None:
            pass

    server = Server(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    state["base_url"] = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        yield state
    finally:
        state["release"].set()
        server.shutdown()
        server.server_close()


@pytest.fixture(autouse=True)
def _no_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("no_proxy", "NO_PROXY"):
        monkeypatch.setenv(name, "*")
    for name in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.delenv(name, raising=False)


def _receipt(base_url: str, **kwargs: Any) -> ChatReceipt:
    return chat_completion_receipt(
        base_url=base_url, model="m", system="s", user="u",
        timeout_s=None, force_json=False, **kwargs,
    )


# ---------------------------------------------------------------------------
# ProviderUsage and parse_usage: the typed boundary
# ---------------------------------------------------------------------------

def test_provider_usage_accepts_a_reported_zero_and_defaults_to_unknown_tokenizer() -> None:
    usage = ProviderUsage(0, 0, 0)
    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (0, 0, 0)
    assert usage.tokenizer == PROVIDER_TOKENIZER_UNKNOWN
    assert "unknown" in PROVIDER_TOKENIZER_UNKNOWN
    with pytest.raises(Exception):
        usage.input_tokens = 5  # type: ignore[misc] - frozen


@pytest.mark.parametrize("bad", [True, False, -1, 1.0, None, "3"])
@pytest.mark.parametrize("field", ["input_tokens", "output_tokens"])
def test_provider_usage_refuses_non_count_primary_fields(field: str, bad: Any) -> None:
    kwargs: dict[str, Any] = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
    kwargs[field] = bad
    with pytest.raises(ValueError, match=field):
        ProviderUsage(**kwargs)


@pytest.mark.parametrize("bad", [True, -1, 1.5, "2"])
def test_provider_usage_refuses_a_non_count_total_but_allows_none(bad: Any) -> None:
    with pytest.raises(ValueError, match="total_tokens"):
        ProviderUsage(1, 1, bad)
    assert ProviderUsage(1, 1, None).total_tokens is None


def test_parse_usage_reported() -> None:
    usage, error = parse_usage(dict(REPORTED_USAGE))
    assert error is None
    assert usage == ProviderUsage(10, 2, 12)
    without_total, error = parse_usage({"prompt_tokens": 3, "completion_tokens": 0})
    assert error is None
    assert without_total == ProviderUsage(3, 0, None)


@pytest.mark.parametrize("raw", [
    None,
    {},
    {"prompt_tokens_details": {"cached_tokens": 5}},
    {"completion_tokens_details": {"reasoning_tokens": 5}, "note": "x"},
])
def test_parse_usage_absent(raw: Any) -> None:
    assert parse_usage(raw) == (None, None)


@pytest.mark.parametrize("raw, fragment", [
    ("12", "usage is str"),
    ([10, 2], "usage is list"),
    (12, "usage is int"),
    ({"prompt_tokens": 10}, "completion_tokens missing"),
    ({"completion_tokens": 2}, "prompt_tokens missing"),
    ({"prompt_tokens": "10", "completion_tokens": 2}, "prompt_tokens='10'"),
    ({"prompt_tokens": 10, "completion_tokens": -2}, "completion_tokens=-2"),
    ({"prompt_tokens": True, "completion_tokens": 2}, "prompt_tokens=True"),
    ({"prompt_tokens": 10, "completion_tokens": 2.0}, "completion_tokens=2.0"),
    ({"prompt_tokens": None, "completion_tokens": 2}, "prompt_tokens=None"),
    ({"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 13}, "total mismatch"),
    ({"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": None}, "total_tokens=None"),
    ({"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": "12"}, "total_tokens='12'"),
])
def test_parse_usage_malformed(raw: Any, fragment: str) -> None:
    usage, error = parse_usage(raw)
    assert usage is None
    assert error is not None and fragment in error


def test_parse_usage_error_text_is_bounded_for_huge_values() -> None:
    usage, error = parse_usage({"prompt_tokens": "x" * 100_000, "completion_tokens": 1})
    assert usage is None
    assert error is not None and len(error) < 256


def test_usage_status_is_derived_from_usage_and_error() -> None:
    def receipt(usage: ProviderUsage | None, error: str | None) -> ChatReceipt:
        return ChatReceipt(
            text="t", usage=usage, usage_error=error, usage_raw_json=None,
            usage_raw_truncated=False, usage_raw_sha256=None, response_model=None,
            finish_reason=None, endpoint="http://127.0.0.1:1/v1", request_model="m",
        )

    assert receipt(ProviderUsage(1, 1, 2), None).usage_status == "reported"
    assert receipt(None, "total mismatch").usage_status == "malformed"
    assert receipt(None, None).usage_status == "absent"
    assert receipt(None, "").usage_status == "absent"


# ---------------------------------------------------------------------------
# chat_completion_receipt over a real loopback transport
# ---------------------------------------------------------------------------

def test_reported_usage_is_typed_and_raw_is_retained_with_digest() -> None:
    with reply_server(_reply(usage=dict(REPORTED_USAGE))) as state:
        receipt = _receipt(state["base_url"] + "/v1")
    assert receipt.text == "the answer"
    assert receipt.usage == ProviderUsage(10, 2, 12)
    assert receipt.usage_status == "reported"
    assert receipt.usage_error is None
    canonical = _canonical(REPORTED_USAGE)
    assert receipt.usage_raw_json == canonical
    assert receipt.usage_raw_truncated is False
    assert receipt.usage_raw_sha256 == hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    assert receipt.response_model == "m-served"
    assert receipt.finish_reason == "stop"
    assert receipt.request_model == "m"
    assert receipt.endpoint == state["base_url"] + "/v1"


@pytest.mark.parametrize("top, raw_json", [
    ({}, None),
    ({"usage": None}, "null"),
    ({"usage": {}}, "{}"),
    ({"usage": {"prompt_tokens_details": {"cached_tokens": 1}}},
     '{"prompt_tokens_details":{"cached_tokens":1}}'),
])
def test_absent_usage_keeps_text_and_records_only_what_was_there(
    top: dict[str, Any], raw_json: str | None,
) -> None:
    with reply_server(_reply(**top)) as state:
        receipt = _receipt(state["base_url"])
    assert receipt.text == "the answer"
    assert receipt.usage is None
    assert receipt.usage_error is None
    assert receipt.usage_status == "absent"
    assert receipt.usage_raw_json == raw_json
    assert receipt.usage_raw_truncated is False
    if raw_json is None:
        assert receipt.usage_raw_sha256 is None
    else:
        assert receipt.usage_raw_sha256 == hashlib.sha256(raw_json.encode()).hexdigest()


@pytest.mark.parametrize("usage", [
    "12",
    {"prompt_tokens": -1, "completion_tokens": 2},
    {"prompt_tokens": True, "completion_tokens": 2},
    {"prompt_tokens": 10, "completion_tokens": 2.5},
    {"prompt_tokens": 10},
    {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 99},
])
def test_malformed_usage_is_retained_raw_never_typed_and_text_still_returned(usage: Any) -> None:
    with reply_server(_reply(usage=usage)) as state:
        receipt = _receipt(state["base_url"])
        answer = chat_completion(
            base_url=state["base_url"], model="m", system="s", user="u",
            timeout_s=None, force_json=False,
        )
    assert receipt.text == "the answer"
    assert answer == "the answer"
    assert receipt.usage is None
    assert receipt.usage_status == "malformed"
    assert receipt.usage_error
    assert receipt.usage_raw_json == _canonical(usage)
    assert receipt.usage_raw_sha256 == hashlib.sha256(
        _canonical(usage).encode("utf-8")).hexdigest()


def test_chat_completion_is_the_receipt_text_with_a_byte_identical_request_body() -> None:
    with reply_server(_reply(usage=dict(REPORTED_USAGE))) as state:
        plain = chat_completion(
            base_url=state["base_url"], model="m", system="s", user="u",
            timeout_s=None, force_json=False, temperature=0.0,
            extra={"options": {"num_ctx": 8}},
        )
        receipt = chat_completion_receipt(
            base_url=state["base_url"], model="m", system="s", user="u",
            timeout_s=None, force_json=False, temperature=0.0,
            extra={"options": {"num_ctx": 8}},
        )
        bodies = list(state["payloads"])
    assert plain == receipt.text == "the answer"
    assert len(bodies) == 2
    assert bodies[0] == bodies[1]


def test_receipt_signature_mirrors_chat_completion_exactly() -> None:
    plain = inspect.signature(chat_completion)
    rich = inspect.signature(chat_completion_receipt)
    assert list(plain.parameters.values()) == list(rich.parameters.values())
    assert rich.return_annotation in (ChatReceipt, "ChatReceipt")


def test_receipt_without_probe_keeps_the_legacy_four_positional_post_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str | None, float | None]] = []

    # Accepts only the historic four positional arguments, exactly like the
    # boundary test for chat_completion: a cancellation keyword on the opt-out
    # path fails here.
    def legacy_post(
        base_url: str, body: dict[str, Any], api_key: str | None, timeout_s: float | None,
    ) -> dict[str, Any]:
        assert body["model"] == "m"
        calls.append((base_url, api_key, timeout_s))
        return {"choices": [{"message": {"content": "unchanged"}}], "usage": REPORTED_USAGE}

    monkeypatch.setattr(compat, "_post", legacy_post)
    receipt = chat_completion_receipt(
        base_url="http://provider.invalid", model="m", system="system", user="user",
        api_key="key", timeout_s=None, force_json=False,
    )
    assert receipt.text == "unchanged"
    assert receipt.usage == ProviderUsage(10, 2, 12)
    assert receipt.response_model is None
    assert receipt.finish_reason is None
    assert calls == [("http://provider.invalid", "key", None)]


def test_cancellation_mid_call_raises_and_builds_no_receipt(monkeypatch: pytest.MonkeyPatch) -> None:
    built: list[Any] = []
    real = compat.ChatReceipt

    def spy(*args: Any, **kwargs: Any) -> Any:
        built.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(compat, "ChatReceipt", spy)
    with reply_server(_reply(usage=dict(REPORTED_USAGE)), delay_s=60.0) as state:
        first_request_at: float | None = None

        def cancelled() -> bool:
            nonlocal first_request_at
            if not state["requests"]:
                return False
            if first_request_at is None:
                first_request_at = time.monotonic()
            return time.monotonic() - first_request_at >= 0.15

        started = time.monotonic()
        with pytest.raises(ProviderCancelled, match="in flight"):
            _receipt(state["base_url"], cancelled=cancelled, poll_interval_s=0.01)
        assert time.monotonic() - started < 5.0
        assert state["requests"] == 1
        assert not state["release"].is_set()
    assert built == []


def test_null_content_passes_through_as_none_for_both_entrypoints() -> None:
    # Pins today's chat_completion behaviour: a null ``content`` is returned as
    # None (the annotation says str; the transport never enforced it).
    with reply_server(_reply(content=None, usage=dict(REPORTED_USAGE))) as state:
        plain = chat_completion(
            base_url=state["base_url"], model="m", system="s", user="u",
            timeout_s=None, force_json=False,
        )
        receipt = _receipt(state["base_url"])
    assert plain is None
    assert receipt.text is None
    assert receipt.usage == ProviderUsage(10, 2, 12)


def test_unexpected_shape_still_raises_provider_http_error() -> None:
    with reply_server({"usage": REPORTED_USAGE, "choices": []}) as state:
        with pytest.raises(compat.ProviderHTTPError, match="unexpected response shape"):
            _receipt(state["base_url"])


def test_endpoint_identity_drops_userinfo_query_and_fragment(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_post(base_url: str, body: dict[str, Any], api_key: Any, timeout_s: Any) -> dict[str, Any]:
        return _reply(usage=dict(REPORTED_USAGE))

    monkeypatch.setattr(compat, "_post", fake_post)
    receipt = _receipt("http://u:p@127.0.0.1:1/v1?token=abc#frag")
    assert receipt.endpoint == "http://127.0.0.1:1/v1"
    dumped = json.dumps(dataclasses.asdict(receipt))
    assert "u:p" not in dumped
    assert "token=abc" not in dumped
    assert "frag" not in dumped


def test_oversized_usage_block_is_bounded_hashed_and_leaves_text_intact() -> None:
    blob = "x" * (1024 * 1024)
    usage = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "blob": blob}
    with reply_server(_reply(usage=usage)) as state:
        receipt = _receipt(state["base_url"])
    canonical = _canonical(usage)
    assert receipt.text == "the answer"
    assert receipt.usage == ProviderUsage(1, 1, 2)
    assert receipt.usage_raw_truncated is True
    assert len(receipt.usage_raw_json or "") == compat._MAX_USAGE_RAW_CHARS
    assert receipt.usage_raw_json == canonical[: compat._MAX_USAGE_RAW_CHARS]
    assert receipt.usage_raw_sha256 == hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def test_exactly_one_send_per_call_and_no_new_transport_call(monkeypatch: pytest.MonkeyPatch) -> None:
    sends: list[str] = []

    def counting_send(request: Any, url: str, timeout_s: Any) -> dict[str, Any]:
        sends.append(url)
        return _reply(usage=dict(REPORTED_USAGE))

    monkeypatch.setattr(compat, "_send", counting_send)
    chat_completion(base_url="http://provider.invalid", model="m", system="s", user="u")
    assert len(sends) == 1
    chat_completion_receipt(base_url="http://provider.invalid", model="m", system="s", user="u")
    assert len(sends) == 2
    chat_completion_receipt(
        base_url="http://provider.invalid", model="m", system="s", user="u",
        cancelled=lambda: False, poll_interval_s=0.01,
    )
    assert len(sends) == 3

    # The kill-switch transport seam gains no new urlopen call. Measured
    # 2026-09-08 at base 24e229c0: _send, chat_stream (twice), server_reachable.
    source = Path(compat.__file__).read_text(encoding="utf-8")
    assert len(re.findall(r"urlopen\(", source)) == 4


# ---------------------------------------------------------------------------
# Independent-review repairs (2026-09-08): two paths that could raise where an
# absolute claim said they could not.
# ---------------------------------------------------------------------------

class _ExplodingRepr:
    """A value whose ``repr`` raises. Not producible by ``json.loads`` -- but
    ``parse_usage`` is a public helper and its docstring says *never raises*."""

    def __repr__(self) -> str:  # pragma: no cover - the raise is the point
        raise RuntimeError("repr exploded")


def test_parse_usage_stays_total_when_a_value_cannot_be_repred() -> None:
    usage, error = compat.parse_usage(
        {"prompt_tokens": _ExplodingRepr(), "completion_tokens": 1}
    )
    assert usage is None
    assert error == "prompt_tokens=<unrepresentable>"


def test_short_repr_never_propagates_a_value_s_own_exception() -> None:
    assert compat._short_repr(_ExplodingRepr()) == "<unrepresentable>"


def test_endpoint_identity_survives_an_unparseable_port_without_echoing_userinfo() -> None:
    """This runs AFTER ``_send`` returned: a raise here discards a paid answer.

    ``urlsplit(...).port`` raises ``ValueError`` for a non-numeric port. The
    replacement marker must not contain the userinfo the function exists to
    strip, and must not be the raw ``base_url``.
    """
    identity = compat._endpoint_identity("http://user:s3cr3tpw@host:notaport/v1")
    assert identity == "http://<unparseable-host>"
    assert "s3cr3tpw" not in identity
    assert "notaport" not in identity


def test_a_receipt_is_still_built_when_the_host_url_has_an_unparseable_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        compat, "_send",
        lambda request, url, timeout_s: _reply(usage=dict(REPORTED_USAGE)),
    )
    receipt = chat_completion_receipt(
        base_url="http://user:s3cr3tpw@host:notaport/v1",
        model="m", system="s", user="u",
    )
    assert receipt.text == "the answer"
    assert receipt.usage == ProviderUsage(10, 2, 12)
    assert "s3cr3tpw" not in json.dumps(dataclasses.asdict(receipt))
