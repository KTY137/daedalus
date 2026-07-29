"""Native Ollama ``/api/chat`` client (stdlib-only), for the local offload lane.

Why a second client beside :mod:`_openai_compat`: Ollama's OpenAI-compat
``/v1`` shim IGNORES a top-level ``options`` block (measured this box,
2026-07-26), so it cannot request a larger context window -- an over-budget
``/v1`` request is head-truncated at ~2050 tokens with the 4096 default ctx.
The native ``/api/chat`` endpoint honors ``options.num_ctx``, ``format:"json"``
and ``keep_alive`` -- the three fields the shim silently drops. DeepSeek is a
real external OpenAI API and keeps using :mod:`_openai_compat`; only the local
Ollama provider uses this module.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import os
from typing import Any

from ._openai_compat import ProviderHTTPError

# Sized by MEASUREMENT on the 15.7GB reference box (2026-07-26), not by the
# model's 32k max: the runner needs weights (~5GB) PLUS a context-scaled
# compute/KV buffer, and Ollama OOM-kills the runner when it doesn't fit.
#   num_ctx=16384 -> ~3.9GB buffer: loads on an IDLE box, OOMs mid-session.
#   num_ctx= 8192 -> OOM at 4.3GB free (typical mid-session).
#   num_ctx= 6144 -> loads under the same pressure (~20s cold).
# Keep this at the measured VRAM-safe value. Input callers may use the full
# context less the explicit generation reserve below; boxes with headroom opt
# into more via env.
DEFAULT_NUM_CTX = 6144

# Tokens held back for response generation inside Ollama's full context window.
# This is a generation reserve, not a num_ctx/2 "halving law".
OUTPUT_RESERVE_TOKENS = 1024


def num_ctx_value() -> int:
    """Context window to request from Ollama (``options.num_ctx``).

    Env ``OLLAMA_NUM_CTX`` overrides the default (see the measured sizing note
    above; e.g. ``OLLAMA_NUM_CTX=16384`` on an idle box); the value is clamped
    to ``>= 2048``. An unset or non-integer env value falls back to the
    default -- this never raises, so a typo in the environment degrades to the
    safe default instead of crashing an offload.
    """
    raw = os.environ.get("OLLAMA_NUM_CTX")
    if raw is None:
        return DEFAULT_NUM_CTX
    try:
        val = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_NUM_CTX
    return max(2048, val)


def effective_input_window(output_reserve: int = OUTPUT_RESERVE_TOKENS) -> int:
    """Usable input tokens = the full requested context minus generation reserve.

    Measured on the RTX bench with qwen2.5-coder:7b (2026-07-28), fresh unique
    prompts at ``num_ctx=16384`` evaluated 3971 and 14375 prompt tokens with
    first-word recall. Only over-budget prompts fell to about ``num_ctx/2``
    (8194 at 16384; 4098 at 8192) and lost head recall. That truncation penalty
    persisted with ``OLLAMA_NUM_PARALLEL=1``; it is not a per-slot halving law.

    Ollama HEAD-truncates an over-long prompt, eating the SYSTEM prompt first.
    Callers must fail loud against this reserved input budget rather than let
    the server truncate. Rewrite callers may pass a larger output reserve when
    they need to generate a complete file.
    """
    return max(0, num_ctx_value() - max(0, output_reserve))


def _adapt_message(message: dict[str, Any]) -> dict[str, Any]:
    """Adapt a native ``/api/chat`` assistant message to the OpenAI shape that
    :mod:`daedalus.providers.ollama` already parses.

    Native ``tool_calls`` arrive as ``{"function": {"name", "arguments": <dict>}}``
    with NO id; the OpenAI loop expects ``arguments`` to be a JSON STRING and a
    stable ``id`` per call. So we re-serialize arguments with ``json.dumps`` and
    synthesize ``call_N`` ids. The ``tool_calls`` key is OMITTED entirely when
    the native response has none, so callers can do ``msg.get("tool_calls") or []``.
    """
    content = message.get("content")
    out: dict[str, Any] = {
        "role": message.get("role", "assistant"),
        "content": content if isinstance(content, str) else "",
    }
    native_calls = message.get("tool_calls") or []
    if native_calls:
        adapted: list[dict[str, Any]] = []
        for i, call in enumerate(native_calls):
            call = call if isinstance(call, dict) else {}
            fn = call.get("function", {}) if isinstance(call.get("function"), dict) else {}
            args = fn.get("arguments")
            if not isinstance(args, str):  # native returns a dict -> JSON string
                args = json.dumps(args if args is not None else {})
            adapted.append({
                "id": call.get("id") or f"call_{i}",
                "type": "function",
                "function": {"name": fn.get("name", ""), "arguments": args},
            })
        out["tool_calls"] = adapted
    return out


def _native_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return ``messages`` with any OpenAI-shaped assistant ``tool_calls``
    converted back to native form for re-POSTing.

    The agentic loop appends our own :func:`_adapt_message` output (arguments as
    a JSON STRING, plus synthesized ``id``/``type``) back into the history for
    the next round. Native ``/api/chat`` unmarshals ``arguments`` into an object
    and 400s on a string, so here we parse it back to a dict and drop the
    OpenAI-only ``id``/``type`` keys. Messages without ``tool_calls`` pass
    through untouched (same object)."""
    out: list[dict[str, Any]] = []
    for m in messages:
        calls = m.get("tool_calls") if isinstance(m, dict) else None
        if not calls:
            out.append(m)
            continue
        native_calls = []
        for c in calls:
            fn = c.get("function", {}) if isinstance(c, dict) else {}
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args or "{}")
                except json.JSONDecodeError:
                    args = {}
            native_calls.append({"function": {"name": fn.get("name", ""), "arguments": args or {}}})
        nm = {k: v for k, v in m.items() if k != "tool_calls"}
        nm["tool_calls"] = native_calls
        out.append(nm)
    return out


def native_chat(
    *,
    host: str,
    model: str,
    messages: list[dict[str, Any]],
    tools: list | None = None,
    # bool keeps every existing caller byte-identical; a dict opts that call
    # into schema-constrained decoding. Typed as ``object`` rather than
    # ``bool | dict`` so a caller passing a schema is not a type error in the
    # many places that still pass True.
    force_json: object = False,
    num_ctx: int | None = None,
    keep_alive: str | None = None,
    timeout_s: int = 300,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """POST ``messages`` to Ollama's native ``/api/chat`` and return the assistant
    message adapted to the OpenAI shape (see :func:`_adapt_message`).

    ``options.num_ctx`` (defaulting to :func:`num_ctx_value`) is the whole point
    of this path -- it is the only way to lift the ~2050-token ``/v1`` cap.
    ``format:"json"`` is sent only when ``force_json``; ``keep_alive`` and
    ``tools`` only when provided. Raises :class:`ProviderHTTPError` on any HTTP
    error or an unreachable host, mirroring ``_openai_compat._post``.
    """
    url = host.rstrip("/") + "/api/chat"
    body: dict[str, Any] = {
        "model": model,
        "messages": _native_messages(messages),
        "stream": False,
        "options": {"num_ctx": num_ctx or num_ctx_value(), "temperature": temperature},
    }
    if force_json:
        # A dict is a JSON *schema*, and that distinction is load-bearing.
        # ``format:"json"`` only promises valid JSON of any shape; a schema
        # constrains the SHAPE at the sampler, masking invalid tokens instead of
        # validating after the fact.
        #
        # MEASURED 2026-07-29 on the bench, 3 trials x 2 tasks per model, native
        # `tools` array vs schema-constrained decoding:
        #
        #     qwen2.5-coder:7b     0%  ->  100%
        #     qwen2.5-coder:14b    0%  ->  100%
        #     devstral:latest      0%  ->  100%
        #     qwen3.6:latest     100%  ->  100%
        #
        # The three that scored zero were not failing to *decide* -- they were
        # failing to EMIT the decision in the structured form, narrating it in
        # prose instead, which the harness reads as a successful turn that did
        # nothing. Constraining the shape removes the failure entirely, on the
        # 4.5GB model as well as the 22GB one.
        body["format"] = force_json if isinstance(force_json, dict) else "json"
    if keep_alive is not None:
        body["keep_alive"] = keep_alive
    if tools:
        body["tools"] = tools

    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ProviderHTTPError(f"HTTP {exc.code} from {url}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise ProviderHTTPError(f"cannot reach {url}: {exc.reason}") from exc

    message = payload.get("message")
    if not isinstance(message, dict):
        raise ProviderHTTPError(f"unexpected response shape: {payload}")
    return _adapt_message(message)
