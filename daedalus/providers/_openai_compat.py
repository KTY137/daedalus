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
    """A caller cancelled while a blocking provider call was in flight.

    Cancellation is deliberately distinct from :class:`ProviderHTTPError` and
    from a timeout: the provider did not fail, and this layer did not invent a
    deadline. Callers must treat this outcome as terminal and must not replay the
    same paid request automatically.
    """


# Polling bounds cancellation-observation latency only. It is not a runtime cap:
# a probe that stays false leaves ``timeout_s`` as the sole call deadline.
DEFAULT_CANCEL_POLL_S = 0.2


def _poll_interval(value: float | None) -> float:
    if value is None:
        return DEFAULT_CANCEL_POLL_S
    interval = float(value)
    if interval <= 0:
        raise ValueError("poll_interval_s must be > 0")
    return interval


def _budget_explicit_bridge() -> Callable[[], None]:
    """Carry the process-budget interposer's explicit-reservation mark.

    ``run_cancellable`` moves the blocking syscall to a worker thread. The
    budget guard stores its "already reserved" depth in ``threading.local``;
    without this bridge, a call made inside an explicit reservation would look
    unreserved on the worker and be charged a second time.
    """
    try:
        from ..budget import _enter_explicit, _inside_explicit
    except Exception:  # noqa: BLE001 - no installed budget marker to inherit
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
    """Run one blocking provider operation behind a cancellation probe.

    The operation itself remains unchanged on a daemon worker. The caller polls
    only the supplied cancellation probe and returns control by raising
    :class:`ProviderCancelled`; the worker is deliberately not retried and its
    eventual result is discarded. This makes an in-flight blocking call
    reachable by the kill-switch without replacing ``timeout_s`` with a hidden
    Daedalus deadline.
    """
    interval = _poll_interval(poll_interval_s)
    if cancelled():
        raise ProviderCancelled(f"cancelled before {name} opened a connection")

    adopt_budget_mark = _budget_explicit_bridge()
    box: dict[str, Any] = {}
    done = threading.Event()

    def _run() -> None:
        adopt_budget_mark()
        try:
            box["value"] = work()
        except BaseException as exc:  # noqa: BLE001 - re-raised on caller thread
            box["error"] = exc
        finally:
            done.set()

    threading.Thread(
        target=_run,
        name=f"daedalus-{name}",
        daemon=True,
    ).start()
    while not done.wait(interval):
        # Prefer a result that became ready in the same interval over throwing
        # away an already-completed paid answer.
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
    """Send a full message list and return the raw assistant message.

    ``cancelled`` is optional. Without it the transport remains the same
    blocking call as before; with it an in-flight wait can be abandoned without
    changing the caller-owned timeout.
    """
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if tools:
        body["tools"] = tools
    payload = _post(
        base_url,
        body,
        api_key,
        timeout_s,
        cancelled=cancelled,
        poll_interval_s=poll_interval_s,
    )
    return payload["choices"][0]["message"]


def _post(
    base_url: str,
    body: dict[str, Any],
    api_key: str | None,
    timeout_s: float | None,
    *,
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
        # Compatibility path: no helper thread and no second opinion on timeout.
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

    Passing ``cancelled`` makes only the in-flight wait interruptible. It does
    not change ``timeout_s`` and a cancellation must never be auto-retried.
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

    payload = _post(
        base_url,
        body,
        api_key,
        timeout_s,
        cancelled=cancelled,
        poll_interval_s=poll_interval_s,
    )
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
    timeout_s: int = 300,
    temperature: float = 0.2,
    extra: dict[str, Any] | None = None,
):
    """Yield assistant text deltas from an OpenAI-compatible ``/chat/completions``
    with ``stream: true``.

    This stream remains deliberately outside the blocking cancellation helper:
    honest mid-stream cancellation needs ownership of the response/socket or a
    producer queue. Advertising a probe that only works before the first token
    would create a false Stop contract.

    Note: ``keep_alive`` is NOT accepted here — Ollama's OpenAI-compat shim
    silently drops it (measured). Pin residency with
    ``providers.ollama.warm_model`` against the native API instead.
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
