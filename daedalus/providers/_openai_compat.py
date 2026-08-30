# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Minimal OpenAI-compatible chat client built on the stdlib (no deps).

Both DeepSeek and Ollama expose an OpenAI-style ``/chat/completions`` endpoint,
so a single tiny client serves both. We deliberately avoid ``requests`` /
``openai`` to keep the harness dependency-free.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class ProviderHTTPError(RuntimeError):
    pass


def chat_raw(
    *,
    base_url: str,
    model: str,
    messages: list[dict[str, Any]],
    api_key: str | None = None,
    timeout_s: int = 300,
    tools: list[dict[str, Any]] | None = None,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Send a full message list (optionally with tools) and return the raw
    assistant message dict — including any ``tool_calls``. Used by the agentic
    read-loop where the model drives which files it reads."""
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }
    if tools:
        body["tools"] = tools
    return _post(base_url, body, api_key, timeout_s)["choices"][0]["message"]


def _post(base_url: str, body: dict[str, Any], api_key: str | None, timeout_s: int) -> dict[str, Any]:
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST"
    )
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
    timeout_s: int = 300,
    force_json: bool = True,
    json_schema: dict[str, Any] | None = None,
    temperature: float = 0.2,
    extra: dict[str, Any] | None = None,
) -> str:
    """POST a chat completion and return the assistant message content.

    ``json_schema`` is sent as OpenAI ``response_format: json_schema`` when
    provided; otherwise ``force_json`` falls back to ``json_object`` mode. The
    caller still validates the parsed result against our report schema.
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

    payload = _post(base_url, body, api_key, timeout_s)
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

    Additive sibling of :func:`chat_completion` — that function keeps its exact
    signature and blocking behavior because several callers (decompose,
    compaction, eval, deepseek, the ollama provider) depend on it. This one is
    a generator: it yields text fragments as they arrive so a UI can render
    tokens instead of waiting for the whole reply.

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
