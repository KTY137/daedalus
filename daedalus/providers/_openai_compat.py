"""Minimal OpenAI-compatible chat client built on the stdlib (no deps).

Both DeepSeek and Ollama expose an OpenAI-style ``/chat/completions`` endpoint,
so a single tiny client serves both. We deliberately avoid ``requests`` /
``openai`` to keep the harness dependency-free.
"""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Callable
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
    if interval <= 0:
        raise ValueError("poll_interval_s must be > 0")
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
        adopt()
        try:
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
    payload = _post(base_url, body, api_key, timeout_s, cancelled, poll_interval_s)
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

    payload = _post(base_url, body, api_key, timeout_s, cancelled, poll_interval_s)
    try:
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ProviderHTTPError(f"unexpected response shape: {payload}") from exc


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
):
    """Yield assistant text deltas from an OpenAI-compatible ``/chat/completions``
    with ``stream: true``.

    Additive sibling of :func:`chat_completion` — that function keeps its exact
    signature and blocking behavior because several callers (decompose,
    compaction, eval, deepseek, the ollama provider) depend on it. This one is
    a generator: it yields text fragments as they arrive so a UI can render
    tokens instead of waiting for the whole reply.

    Note: ``keep_alive`` is NOT accepted here — Ollama's OpenAI-compat shim
    silently drops it (measured). Pin residency with
    ``providers.ollama.warm_model`` against the native API instead.

    Re-measured 2026-09-05 against Ollama 0.33.3, and it is worse than "drops
    the field": a ``/v1`` call sent ``keep_alive: "30m"`` and got the 5-minute
    default back from ``/api/ps``, AND reloaded the natively-warmed instance
    from a 6144 context down to the 4096 default. The same TTL and
    ``options.num_ctx`` on ``/api/generate`` were both honoured. So routing a
    caller through this module instead of the native client costs a reload per
    call and a smaller window. Numbers in the G1-KERNEL-02 evidence directory;
    the repair is a routing change, not a change here.

    NOT cancellable (G1-KERNEL-02 residual, named rather than half-fixed). The
    ``cancelled`` probe :func:`chat_completion` accepts is deliberately absent
    here: a stream yields between frames, so a caller already regains control
    on every delta, but a peer that stalls mid-stream still parks this
    generator in ``resp``'s line iterator. Covering the ``urlopen`` window
    alone would advertise a cancellation that only works before the first
    token, which is worse than none. Wiring this needs a producer thread and a
    queue, on :func:`run_cancellable`; it is a separate packet.
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
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as resp:
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
