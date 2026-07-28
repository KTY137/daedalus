"""Dynamic task decomposition -- turn ONE objective into a bounded list of
scoped subtasks the bench can fan out over.

Two paths, in order of preference:

  * PRIMARY (dynamic): ask the local Ollama model to propose a JSON breakdown.
    Nothing leaves the machine (local server), so this is cheap and private.
  * FALLBACK (deterministic): if the local server is unreachable, the call
    errors, or the response can't be parsed, split by path -- one subtask per
    supplied path (or a single passthrough subtask when there is <=1 path).

Contract: :func:`decompose` NEVER raises and ALWAYS returns >=1 subtask. It is
import-safe -- no network I/O happens at import time, only inside the call.
"""

from __future__ import annotations

import json
import os
from typing import Any

from ..providers._openai_compat import ProviderHTTPError, chat_completion, server_reachable
from ..providers.ollama import DEFAULT_HOST, DEFAULT_MODEL

# Keep the breakdown prompt tiny (token-efficiency rules): we only need a shape.
_SYSTEM = (
    "You are a planning assistant that splits one software objective into a few "
    "small, independent subtasks a junior worker could each pick up alone. "
    "Return ONLY a json object of the form "
    '{"subtasks": [{"objective": "<what to do>", "paths": ["<repo-relative path>"]}]}. '
    "Keep each objective short and concrete. Use only the supplied candidate "
    "paths; never invent files. Do not add any prose outside the json."
)


def _user_prompt(objective: str, paths: list[str], max_subtasks: int) -> str:
    known = ", ".join(paths) if paths else "(none supplied)"
    return (
        f"Objective:\n{objective}\n\n"
        f"Candidate paths: {known}\n\n"
        f"Break this into at most {max_subtasks} json subtasks."
    )


def _coerce_item(item: Any) -> dict | None:
    """Normalise one proposed subtask into {"objective": str, "paths": [str]}."""
    if isinstance(item, str):
        text = item.strip()
        return {"objective": text, "paths": []} if text else None
    if not isinstance(item, dict):
        return None
    objective = item.get("objective") or item.get("task") or item.get("goal") or item.get("title")
    if not objective:
        return None
    raw_paths = item.get("paths")
    if raw_paths is None:
        raw_paths = item.get("files") or item.get("path") or []
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths]
    if not isinstance(raw_paths, (list, tuple)):
        raw_paths = []
    paths = [str(p) for p in raw_paths if p]
    return {"objective": str(objective).strip(), "paths": paths}


def _parse_subtasks(raw: str, max_subtasks: int) -> list[dict]:
    """Defensively parse a model response into a list of subtask dicts.

    Accepts a top-level JSON array, or an object wrapping the array under
    ``subtasks``/``tasks``/``items``, or a single subtask object. Any junk is
    dropped. Returns [] when nothing usable is found (caller then falls back)."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        # Salvage a JSON substring if the model wrapped it in prose.
        start = raw.find("[") if isinstance(raw, str) else -1
        obj_start = raw.find("{") if isinstance(raw, str) else -1
        try:
            if start != -1 and (obj_start == -1 or start < obj_start):
                data = json.loads(raw[start : raw.rfind("]") + 1])
            elif obj_start != -1:
                data = json.loads(raw[obj_start : raw.rfind("}") + 1])
            else:
                return []
        except (json.JSONDecodeError, ValueError):
            return []

    if isinstance(data, dict):
        items = (
            data.get("subtasks")
            or data.get("tasks")
            or data.get("items")
            or data.get("steps")
        )
        if not isinstance(items, list):
            items = [data] if (data.get("objective") or data.get("task")) else []
    elif isinstance(data, list):
        items = data
    else:
        return []

    out: list[dict] = []
    for item in items:
        coerced = _coerce_item(item)
        if coerced:
            out.append(coerced)
        if len(out) >= max_subtasks:
            break
    return out


def _fallback(objective: str, paths: list[str]) -> list[dict]:
    if len(paths) > 1:
        return [{"objective": objective, "paths": [p]} for p in paths]
    return [{"objective": objective, "paths": list(paths)}]


def _ask_model(objective: str, paths: list[str], max_subtasks: int) -> list[dict]:
    """Best-effort dynamic breakdown via the local Ollama server. Returns []
    (never raises) when the server is down, the call fails, or parsing fails."""
    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
    model = os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
    if not server_reachable(host, path="/api/tags"):
        return []
    try:
        raw = chat_completion(
            base_url=host.rstrip("/") + "/v1",
            model=model,
            system=_SYSTEM,
            user=_user_prompt(objective, paths, max_subtasks),
            api_key=None,
            timeout_s=60,
            force_json=True,
            temperature=0.0,
        )
    except (ProviderHTTPError, ValueError, OSError):
        return []
    except Exception:  # defence in depth -- decompose must never raise
        return []
    return _parse_subtasks(raw, max_subtasks)


def decompose(
    objective: str,
    repo_root: str,
    paths: list[str] | None = None,
    max_subtasks: int = 4,
) -> list[dict]:
    """Split ``objective`` into >=1 scoped subtask dict(s).

    Each subtask is ``{"objective": str, "paths": list[str]}``. Tries the local
    model first (dynamic), then falls back to a deterministic per-path split.
    Never raises; always returns at least one subtask.
    """
    paths = [str(p) for p in (paths or [])]
    subtasks = _ask_model(objective, paths, max_subtasks)
    if subtasks:
        return subtasks[:max_subtasks]
    return _fallback(objective, paths)
