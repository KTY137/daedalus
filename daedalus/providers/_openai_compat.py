"""Minimal OpenAI-compatible chat client built on the stdlib (no deps).

Both DeepSeek and Ollama expose an OpenAI-style ``/chat/completions`` endpoint,
so a single tiny client serves both. We deliberately avoid ``requests`` /
``openai`` to keep the harness dependency-free.
"""

from __future__ import annotations

import hashlib
import json
import math
import queue
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any


class ProviderHTTPError(RuntimeError):
    pass


class ProviderCancelled(RuntimeError):
    """A caller's cancellation probe fired while a request was in flight.

    Deliberately NOT a :class:`ProviderHTTPError`. A caller that catches the
    HTTP error to mean "the provider failed" must not read a cancellation as a
    provider failure -- the kill switch working is not the vendor breaking. It
    is also not a timeout: nothing here decides how long a call may run.
    """


# How often a cancellable call asks its probe whether it should still be
# waiting. THIS IS NOT A CAP. It bounds how long a cancellation takes to be
# noticed, not how long a call may run: while the probe stays False the call
# waits exactly as long as the caller's ``timeout_s`` allows, and a
# ``timeout_s`` of None still means no deadline at all (master plan 4.1 -- a
# disabled cap is never a magic number). Raising this value delays the kill
# switch; it can never end a call.
DEFAULT_CANCEL_POLL_S = 0.2


def _poll_interval(value: float | None) -> float:
    if value is None:
        return DEFAULT_CANCEL_POLL_S
    interval = float(value)
    if not math.isfinite(interval) or interval <= 0:
        raise ValueError("poll_interval_s must be > 0 and finite")
    return interval


def _budget_explicit_bridge() -> Callable[[], None]:
    """Carry the budget interposer's per-thread "already reserved" mark along.

    ``budget_process`` suppresses a second reservation with a
    ``threading.local()`` depth counter, so a call made from a worker thread
    would look unreserved and be booked a SECOND time whenever the caller had
    already reserved explicitly (``budget.spend``). Capturing the mark on the
    calling thread and re-entering it on the worker keeps a cancellable call
    reserved exactly as often as a blocking one.

    Failure to import is not fatal: without the interposer there is no mark to
    carry, and the worker then behaves like today's main-thread call.
    """
    try:
        from ..budget import _enter_explicit, _inside_explicit
    except Exception:  # noqa: BLE001 - a missing facade must not break egress
        return lambda: None
    if not _inside_explicit():
        return lambda: None
    return _enter_explicit


def run_cancellable(
    work: Callable[[], Any],
    *,
    cancelled: Callable[[], bool],
    poll_interval_s: float | None = None,
    name: str = "provider-call",
) -> Any:
    """Run one blocking provider call so the caller can stop waiting for it.

    ``work`` runs unchanged on a daemon worker thread; this thread waits on an
    Event and asks ``cancelled()`` between waits. When the probe fires,
    :class:`ProviderCancelled` is raised HERE and the caller gets control back.

    WHY THE BLOCKING CALL MOVES AND THE WATCHER DOES NOT. The obvious shape is
    the mirror image -- keep the request on this thread and have a watcher tear
    the socket down -- and it was rejected on two measured points:

    * ``urlopen`` hands back no socket until it has already returned, and the
      measured hang is INSIDE ``urlopen`` (a non-streaming completion sends its
      status line only once generation has finished). A watcher therefore has
      nothing to close during exactly the window that matters, short of a
      private ``resp.fp.raw._sock`` reach-through and a custom opener.
    * Reading the body in bounded slices under a short socket timeout is not a
      substitute either. It does not cover the ``urlopen`` window at all, the
      short timeout would be a Daedalus-set duration in disguise, and it does
      not even work: MEASURED on CPython 3.13.14, a 4043-byte reply whose
      second half is late returns ZERO bytes from the slice loop -- the
      buffered first half is discarded with the raising read -- and every
      retry afterwards raises ``OSError: cannot read from timed out object``,
      because ``socket.SocketIO`` latches ``_timeout_occurred`` and refuses the
      response object for good. See the G1-KERNEL-02 evidence directory.

    Inverting the roles needs neither the socket handle nor a portable way to
    wake a thread parked in ``recv``.

    THE HONEST COST. Cancelling abandons the worker; the request keeps running
    until the peer answers or the process exits, and its result is discarded.
    So a cancelled call MUST NOT be retried: the budget interposer settles that
    reservation when the abandoned thread unwinds, and a retry books a second
    worst-case call for one question.
    """
    interval = _poll_interval(poll_interval_s)
    if cancelled():
        # Refused before a connection is opened: a call that was already
        # cancelled must not cost a reservation.
        raise ProviderCancelled(f"cancelled before {name} opened a connection")

    adopt = _budget_explicit_bridge()
    box: dict[str, Any] = {}
    done = threading.Event()

    def _run() -> None:
        try:
            adopt()
            box["value"] = work()
        except BaseException as exc:  # noqa: BLE001 - re-raised on the caller's thread
            box["error"] = exc
        finally:
            done.set()

    threading.Thread(target=_run, name=f"daedalus-{name}", daemon=True).start()
    while not done.wait(interval):
        # ``done.is_set()`` is re-read after the probe so a reply that landed
        # during the same interval is returned rather than paid for and thrown
        # away; cancellation wins only when there is nothing to win.
        if cancelled() and not done.is_set():
            raise ProviderCancelled(f"cancelled while {name} was in flight")
    if "error" in box:
        raise box["error"]
    return box["value"]


def chat_raw(
    *,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    api_key: str | None = None,
    timeout_s: float | None = 300,
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.0,
    cancelled: Callable[[], bool] | None = None,
    poll_interval_s: float | None = None,
) -> dict[str, Any]:
    """Send a full message list (optionally with tools) and return the raw
    assistant message dict — including any ``tool_calls``. Used by the agentic
    read-loop where the model drives which files it reads.

    ``cancelled`` is the optional kill-switch probe; see :func:`chat_completion`."""
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if tools:
        body["tools"] = tools
    if cancelled is None:
        payload = _post(base_url, body, api_key, timeout_s)
    else:
        payload = _post(
            base_url, body, api_key, timeout_s,
            cancelled=cancelled, poll_interval_s=poll_interval_s,
        )
    return payload["choices"][0]["message"]


def _post(
    base_url: str,
    body: dict[str, Any],
    api_key: str | None,
    timeout_s: float | None,
    cancelled: Callable[[], bool] | None = None,
    poll_interval_s: float | None = None,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
    if cancelled is None:
        # No probe: the exact call this module has always made, on this thread.
        return _send(request, url, timeout_s)
    return run_cancellable(
        lambda: _send(request, url, timeout_s),
        cancelled=cancelled,
        poll_interval_s=poll_interval_s,
        name="chat-completions",
    )


def _send(
    request: urllib.request.Request,
    url: str,
    timeout_s: float | None,
) -> dict[str, Any]:
    """The request itself. ``timeout_s`` is passed through untouched, including
    None -- how long a call may run is decided upstream by
    ``runtimes.providers.execution_policy.provider_http_timeout``, and this
    module does not get a second opinion."""
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ProviderHTTPError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ProviderHTTPError(f"cannot reach {url}: {exc.reason}") from exc


# ---------------------------------------------------------------------------
# Provider-reported usage (G1-EVAL-USAGE-01)
#
# A provider's ``usage`` block is a SELF-REPORT in a tokenizer this module does
# not know (Ollama's ``prompt_tokens`` is ``prompt_eval_count`` and may exclude
# a cached prompt). It is retained as evidence with provenance; it is never a
# budget-equality measurement and is never summed with a local estimate.
# ---------------------------------------------------------------------------

PROVIDER_TOKENIZER_UNKNOWN = "provider-reported (tokenizer unknown)"

# Bound on the retained canonical ``usage`` JSON. The digest always covers the
# full canonical bytes, so a truncated retention is still verifiable.
_MAX_USAGE_RAW_CHARS = 2048
_MAX_USAGE_ERROR_REPR_CHARS = 80


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _short_repr(value: Any) -> str:
    text = repr(value)
    if len(text) <= _MAX_USAGE_ERROR_REPR_CHARS:
        return text
    return text[: _MAX_USAGE_ERROR_REPR_CHARS - 3] + "..."


@dataclass(frozen=True)
class ProviderUsage:
    """Token counts exactly as one provider reported them.

    ``input_tokens`` and ``output_tokens`` are the provider's ``prompt_tokens``
    and ``completion_tokens``; ``total_tokens`` is its own total when it sent
    one. A reported zero is a valid report. ``tokenizer`` names what counted --
    today always unknown, so two ProviderUsage values from different providers
    are not comparable and no code here compares them.
    """

    input_tokens: int
    output_tokens: int
    total_tokens: int | None
    tokenizer: str = PROVIDER_TOKENIZER_UNKNOWN

    def __post_init__(self) -> None:
        for name in ("input_tokens", "output_tokens"):
            value = getattr(self, name)
            if not _is_count(value):
                raise ValueError(f"{name} must be a non-negative int, got {_short_repr(value)}")
        if self.total_tokens is not None and not _is_count(self.total_tokens):
            raise ValueError(
                f"total_tokens must be a non-negative int or None, got "
                f"{_short_repr(self.total_tokens)}"
            )


def parse_usage(raw: Any) -> tuple[ProviderUsage | None, str | None]:
    """Classify one ``usage`` value as reported, absent or malformed.

    Total function: never raises. Returns ``(usage, error)``:

    * ``(ProviderUsage, None)`` -- reported;
    * ``(None, None)`` -- absent: ``None``, ``{}``, or a block without either
      primary counter (a details-only block counts as absent);
    * ``(None, reason)`` -- malformed: not an object, exactly one primary
      counter, a counter that is not a non-bool int >= 0, or a present
      ``total_tokens`` that is not the sum of the two. A self-inconsistent
      report is not a measurement, so it is deliberately not typed.
    """
    if raw is None:
        return None, None
    if not isinstance(raw, dict):
        return None, f"usage is {type(raw).__name__}"
    has_input = "prompt_tokens" in raw
    has_output = "completion_tokens" in raw
    if not has_input and not has_output:
        return None, None
    if not has_input:
        return None, "prompt_tokens missing"
    if not has_output:
        return None, "completion_tokens missing"
    prompt, completion = raw["prompt_tokens"], raw["completion_tokens"]
    if not _is_count(prompt):
        return None, f"prompt_tokens={_short_repr(prompt)}"
    if not _is_count(completion):
        return None, f"completion_tokens={_short_repr(completion)}"
    total: int | None = None
    if "total_tokens" in raw:
        total = raw["total_tokens"]
        if not _is_count(total):
            return None, f"total_tokens={_short_repr(total)}"
        if total != prompt + completion:
            return None, "total mismatch"
    return ProviderUsage(prompt, completion, total), None


@dataclass(frozen=True)
class ChatReceipt:
    """One completed ``/chat/completions`` call: its text plus usage provenance.

    ``text`` is the assistant content verbatim (``None`` when the provider sent
    ``null``). ``usage_raw_json`` is the canonical serialization of the
    provider's ``usage`` value, bounded to ``_MAX_USAGE_RAW_CHARS``;
    ``usage_raw_sha256`` covers the full canonical bytes whenever a ``usage``
    key existed. ``endpoint`` is the base URL reduced to scheme, host, port and
    path -- userinfo, query and fragment never enter a receipt.
    """

    text: Any
    usage: ProviderUsage | None
    usage_error: str | None
    usage_raw_json: str | None
    usage_raw_truncated: bool
    usage_raw_sha256: str | None
    response_model: str | None
    finish_reason: str | None
    endpoint: str
    request_model: str

    @property
    def usage_status(self) -> str:
        if self.usage is not None:
            return "reported"
        if self.usage_error:
            return "malformed"
        return "absent"


def _usage_raw_evidence(payload: dict[str, Any]) -> tuple[str | None, bool, str | None]:
    if "usage" not in payload:
        return None, False, None
    canonical = json.dumps(payload["usage"], sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if len(canonical) <= _MAX_USAGE_RAW_CHARS:
        return canonical, False, digest
    return canonical[:_MAX_USAGE_RAW_CHARS], True, digest


def _endpoint_identity(base_url: str) -> str:
    """Scheme, host, port and path only: an ``OLLAMA_HOST`` may carry userinfo."""
    parts = urllib.parse.urlsplit(base_url)
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    netloc = host if parts.port is None else f"{host}:{parts.port}"
    return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, "", ""))


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def chat_completion_receipt(
    *,
    base_url: str,
    model: str,
    system: str,
    user: str,
    api_key: str | None = None,
    timeout_s: float | None = 300,
    force_json: bool = True,
    json_schema: dict[str, Any] | None = None,
    temperature: float = 0.2,
    extra: dict[str, Any] | None = None,
    cancelled: Callable[[], bool] | None = None,
    poll_interval_s: float | None = None,
) -> ChatReceipt:
    """:func:`chat_completion` that also returns the provider's usage report.

    Same signature, same request body, same transport call, same errors:
    :class:`ProviderCancelled` and :class:`ProviderHTTPError` propagate
    unchanged and a cancelled call builds no receipt. The only addition is
    what is read from the parsed reply after it arrived.
    """
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "stream": False,
    }
    if json_schema is not None:
        body["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "agent_report_v1", "strict": True, "schema": json_schema},
        }
    elif force_json:
        body["response_format"] = {"type": "json_object"}
    if extra:
        body.update(extra)

    if cancelled is None:
        payload = _post(base_url, body, api_key, timeout_s)
    else:
        payload = _post(
            base_url, body, api_key, timeout_s,
            cancelled=cancelled, poll_interval_s=poll_interval_s,
        )
    try:
        choice = payload["choices"][0]
        text = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderHTTPError(f"unexpected response shape: {payload}") from exc

    usage, usage_error = parse_usage(payload.get("usage"))
    raw_json, raw_truncated, raw_sha256 = _usage_raw_evidence(payload)
    return ChatReceipt(
        text=text,
        usage=usage,
        usage_error=usage_error,
        usage_raw_json=raw_json,
        usage_raw_truncated=raw_truncated,
        usage_raw_sha256=raw_sha256,
        response_model=_optional_str(payload.get("model")),
        finish_reason=_optional_str(choice.get("finish_reason")) if isinstance(choice, dict) else None,
        endpoint=_endpoint_identity(base_url),
        request_model=model,
    )


def chat_completion(
    *,
    base_url: str,
    model: str,
    system: str,
    user: str,
    api_key: str | None = None,
    timeout_s: float | None = 300,
    force_json: bool = True,
    json_schema: dict[str, Any] | None = None,
    temperature: float = 0.2,
    extra: dict[str, Any] | None = None,
    cancelled: Callable[[], bool] | None = None,
    poll_interval_s: float | None = None,
) -> str:
    """POST a chat completion and return the assistant message content.

    ``json_schema`` is sent as OpenAI ``response_format: json_schema`` when
    provided; otherwise ``force_json`` falls back to ``json_object`` mode. The
    caller still validates the parsed result against our report schema.

    ``cancelled`` is an optional zero-argument probe -- typically a kill-switch
    or mission-cancellation check. Passing one makes an in-flight request
    interruptible: when the probe returns True this raises
    :class:`ProviderCancelled` instead of waiting for the peer. Without it the
    call is byte-for-byte the blocking call it has always been, so no existing
    caller changes behaviour.

    It is NOT a deadline and does not interact with one. ``timeout_s`` still
    decides how long a call may run and still reaches ``urlopen`` untouched,
    None included; ``poll_interval_s`` only decides how promptly a
    cancellation is noticed. A caller that wants a deadline asks
    ``runtimes.providers.execution_policy.provider_http_timeout``, which is the
    one place allowed to answer that question.

    A cancelled call must not be retried -- see :func:`run_cancellable`.

    Since G1-EVAL-USAGE-01 the body construction and transport call live in
    :func:`chat_completion_receipt`; this is that call's ``text``. Callers that
    need the provider's usage report ask for the receipt instead.
    """
    return chat_completion_receipt(
        base_url=base_url,
        model=model,
        system=system,
        user=user,
        api_key=api_key,
        timeout_s=timeout_s,
        force_json=force_json,
        json_schema=json_schema,
        temperature=temperature,
        extra=extra,
        cancelled=cancelled,
        poll_interval_s=poll_interval_s,
    ).text


def _cancellable_stream(
    open_response: Callable[[], Any],
    deltas: Callable[[Any], Iterator[str]],
    *,
    cancelled: Callable[[], bool],
    poll_interval_s: float | None,
    name: str,
    url: str,
) -> Iterator[str]:
    """Read one response with backpressure and interruptible consumer waits.

    The queue's finite capacity supplies backpressure, not an execution limit:
    every delta is delivered while the caller keeps consuming. Closing a
    stdlib response may wait on its read lock, so closure runs on a daemon
    thread. Cancellation returns without claiming a remote stop or replaying
    the request, including when connection establishment is still blocked.
    """
    interval = _poll_interval(poll_interval_s)
    if cancelled():
        raise ProviderCancelled(f"cancelled before {name} opened a connection")

    events: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=64)
    stop_requested = threading.Event()
    response_lock = threading.Lock()
    response_box: dict[str, Any] = {}
    close_started = threading.Event()
    adopt = _budget_explicit_bridge()

    def publish(kind: str, value: Any) -> bool:
        while not stop_requested.is_set():
            try:
                events.put((kind, value), timeout=interval)
                return True
            except queue.Full:
                continue
        return False

    def close_response() -> None:
        with response_lock:
            response = response_box.get("response")
            if response is None or close_started.is_set():
                return
            close_started.set()

        def close() -> None:
            try:
                response.close()
            except Exception:  # noqa: BLE001 - best-effort transport teardown
                pass

        closer = threading.Thread(
            target=close, name="daedalus-stream-close", daemon=True,
        )
        closer.start()
        # Give an immediate close time to finish, without waiting indefinitely
        # for a response lock held by a blocked read.
        closer.join(interval)

    def produce() -> None:
        try:
            adopt()
            with open_response() as response:
                with response_lock:
                    response_box["response"] = response
                if stop_requested.is_set():
                    return
                for piece in deltas(response):
                    if not publish("delta", piece):
                        return
        except urllib.error.HTTPError as exc:
            # Reading an error body may block too. Keep that read on the
            # cancellable worker, never move it onto the consumer's thread.
            with response_lock:
                response_box["response"] = exc
            try:
                if stop_requested.is_set():
                    return
                detail = exc.read(500).decode("utf-8", errors="replace")
            except BaseException as read_error:  # noqa: BLE001 - preserve read failure
                publish("error", read_error)
            else:
                publish("error", ProviderHTTPError(f"HTTP {exc.code} from {url}: {detail}"))
            finally:
                # urlopen raised, so its error response never entered the
                # normal context manager. This also disposes a late error
                # arriving after cancellation saw no response to close.
                close_response()
        except urllib.error.URLError as exc:
            publish("error", ProviderHTTPError(f"cannot reach {url}: {exc.reason}"))
        except BaseException as exc:  # noqa: BLE001 - re-raised by the consumer
            publish("error", exc)
        finally:
            with response_lock:
                response_box.pop("response", None)
            publish("done", None)

    threading.Thread(
        target=produce, name="daedalus-" + name.replace(" ", "-"), daemon=True,
    ).start()
    try:
        while True:
            if cancelled():
                raise ProviderCancelled(f"cancelled while {name} was in flight")
            try:
                kind, value = events.get(timeout=interval)
            except queue.Empty:
                continue
            if kind == "delta":
                yield value
            elif kind == "error":
                raise value
            elif kind == "done":
                return
            else:  # pragma: no cover - private producer vocabulary
                raise RuntimeError(f"unknown provider stream event: {kind}")
    finally:
        stop_requested.set()
        close_response()


def _stream_deltas(resp: Any) -> Iterator[str]:
    """Decode OpenAI-compatible SSE frames from one already-open response."""
    for raw in resp:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            if payload == "[DONE]":
                break
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue  # tolerate keep-alive / partial frames
        for choice in obj.get("choices") or []:
            piece = (choice.get("delta") or {}).get("content")
            if piece:
                yield piece


def chat_stream(
    *,
    base_url: str,
    model: str,
    system: str,
    user: str,
    api_key: str | None = None,
    timeout_s: float | None = 300,
    temperature: float = 0.2,
    extra: dict[str, Any] | None = None,
    cancelled: Callable[[], bool] | None = None,
    poll_interval_s: float | None = None,
):
    """Yield assistant text deltas from ``/chat/completions`` with ``stream:true``.

    With no cancellation probe this preserves the historical direct blocking
    transport: ``urlopen`` and response iteration stay on the caller thread.

    With a probe, the worker owns the response/socket and the caller owns only a
    bounded queue of decoded deltas. Cancellation is checked before opening the
    connection and between queue reads. Once a response exists, cancellation
    requests its closure on a daemon thread and returns control. A response
    close can itself block behind an in-flight read, so this does not prove
    that the response iterator or remote generation has already stopped. If
    cancellation happens while ``urlopen`` itself is still blocked, stdlib exposes no portable
    handle to close yet; the daemon worker may finish that connection attempt in
    the background, but its result is discarded and is never replayed. This is
    therefore a transport cancellation primitive, not evidence that a remote
    provider has already stopped billing.

    ``poll_interval_s`` only bounds cancellation-observation latency. It never
    replaces or shortens ``timeout_s``.

    Ollama callers use ``_ollama_native.native_chat_stream`` so ``keep_alive``
    and the context window travel on the same request; its compatibility shim
    silently drops those native options (see G1-KERNEL-02 retained evidence).
    """
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "stream": True,
    }
    if extra:
        body.update(extra)

    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )

    if cancelled is None:
        try:
            with urllib.request.urlopen(request, timeout=timeout_s) as resp:
                yield from _stream_deltas(resp)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise ProviderHTTPError(f"HTTP {exc.code} from {url}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ProviderHTTPError(f"cannot reach {url}: {exc.reason}") from exc
        return

    try:
        yield from _cancellable_stream(
            lambda: urllib.request.urlopen(request, timeout=timeout_s),
            _stream_deltas,
            cancelled=cancelled,
            poll_interval_s=poll_interval_s,
            name="chat stream",
            url=url,
        )
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ProviderHTTPError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ProviderHTTPError(f"cannot reach {url}: {exc.reason}") from exc


def server_reachable(base_url: str, timeout_s: float = 2.0, path: str = "") -> bool:
    """Cheap liveness probe (used by the local Ollama provider)."""
    url = base_url.rstrip("/") + path
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as resp:
            return 200 <= resp.status < 500
    except (urllib.error.URLError, OSError):
        return False
