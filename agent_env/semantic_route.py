"""Semantic stage-1 routing (semantic-router pattern, aurelio-labs) -- zero-dep.

Keyword/path scoring is brittle on prose objectives ("make the plot legible").
This routes by *embedding* similarity instead: embed the objective and each
role's example text with a local Ollama embedding model, pick the nearest role.
No LLM call, near-zero cost.

Precise path ownership still wins (a path under a role's `owns` is a hard
signal), and ANY failure -- embedder down, model missing -- falls back to the
existing keyword router. So this only ever helps; it never breaks routing.
"""

from __future__ import annotations

import json
import math
import os
import urllib.error
import urllib.request
from functools import lru_cache

from .providers.ollama import DEFAULT_HOST
from .router import load_agents, route_task

EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")


def _embed(text: str, host: str, model: str) -> list[float] | None:
    url = host.rstrip("/") + "/api/embeddings"
    body = json.dumps({"model": model, "prompt": text}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode("utf-8")).get("embedding")
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _role_text(agent: dict) -> str:
    return " ".join([agent.get("name", ""), *agent.get("triggers", []), *agent.get("owns", [])])


@lru_cache(maxsize=1)
def _role_vectors(host: str, model: str) -> tuple[tuple[str, tuple[float, ...]], ...] | None:
    vecs = []
    for agent in load_agents():
        v = _embed(_role_text(agent), host, model)
        if v is None:
            return None
        vecs.append((agent["name"], tuple(v)))
    return tuple(vecs)


def _path_owned(paths: list[str]) -> bool:
    low = [p.replace("\\", "/").lower() for p in paths]
    for agent in load_agents():
        if any(o.lower() in p for o in agent.get("owns", []) for p in low):
            return True
    return False


def semantic_route(objective: str, paths: list[str] | None = None,
                   host: str | None = None, model: str | None = None) -> dict:
    """Return the chosen agent dict. Falls back to keyword routing on any miss."""
    paths = paths or []
    # Path ownership is precise -- let the keyword router handle those directly.
    if _path_owned(paths):
        return route_task(objective, paths)

    host = host or os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
    model = model or EMBED_MODEL
    role_vecs = _role_vectors(host, model)
    q = _embed(objective, host, model) if role_vecs else None
    if not role_vecs or q is None:
        return route_task(objective, paths)  # embedder unavailable -> fallback

    best_name = max(role_vecs, key=lambda rv: _cosine(q, list(rv[1])))[0]
    return next(a for a in load_agents() if a["name"] == best_name)
