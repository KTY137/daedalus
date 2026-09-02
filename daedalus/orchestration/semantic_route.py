"""Semantic stage-1 routing (semantic-router pattern, aurelio-labs) -- zero-dep.

Keyword/path scoring is brittle on prose objectives ("make the plot legible").
This routes by *embedding* similarity instead: embed the objective and each
role's example text with a local Ollama embedding model, pick the nearest role.
No LLM call, near-zero cost.

Precise path ownership still wins (a path under a role's `owns` is a hard
signal), and ANY failure -- embedder down, model missing -- falls back to the
existing keyword router. So this only ever helps; it never breaks routing.

HONESTY CONTRACT
----------------
The fallback above is the *point* of this module, and it was also its defect:
the old version returned a bare agent dict on every path, so "the latent route
ran and chose ui-ux-dev" and "the latent route never ran because the embedding
model is not installed" were byte-for-byte indistinguishable to the caller. A
capability that silently degrades to a keyword guess reads as a working
capability forever.

So every route now carries provenance. :func:`semantic_route_explained` returns
a :class:`LatentRouteResult` stating which MECHANISM produced the agent and, if
the latent path did not run, the ERROR KIND that stopped it. The legacy
:func:`semantic_route` still returns just the agent dict, but a skipped latent
route now also emits a ``logging.WARNING`` -- silence is no longer an option.

Three failure modes here were measured, not theorised (2026-07-29):

* **Cache poisoning.** ``_role_vectors`` was ``@lru_cache``d and returned
  ``None`` on failure, so the ``None`` was cached. One transient blip at
  process start disabled the latent route for the whole process lifetime, and
  no later recovery could revive it. Failures are no longer cached.
* **Degenerate vectors.** A backend answering ``{"embedding": []}`` (or all
  zeros) gave every role cosine 0.0, and ``max()`` returned whichever role
  sorted first -- an arbitrary pick wearing the costume of a decision. Vectors
  are now validated, and a degenerate answer is a FAILURE, not a route.
* **Dimension drift.** ``zip()`` silently truncates, so comparing a 768-dim
  role vector against a 384-dim query (two different models) scored a prefix
  and reported confidence. Mismatched dimensions are now a failure.
* **A cold model read as a dead host.** The single hardcoded ``timeout=10``
  was applied to the call that loads the model. MEASURED 2026-07-29 on the
  shipped backend: cold ``nomic-embed-text`` answers in 15.48s, warm in 0.18s.
  Every fresh process therefore blew the cap on its first role, aborted the
  batch, and routed by keyword while reporting ``host_unreachable`` about a
  host that was up -- so the feature was wired, tested, and had never once run
  in production (0 of 5 live probes). The first call of a batch now gets a
  separate cold budget, and a blown deadline is ``embed_timeout``, not a dead
  host. See :data:`DEFAULT_EMBED_COLD_TIMEOUT_S`.

None of the five is theoretical, and note what they have in common: each one
turned a broken latent route into a *plausible* keyword answer. That is why
provenance is not decoration here -- it is the only thing that can tell you the
feature is dead.
"""

from __future__ import annotations

import json
import logging
import math
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from ..providers.ollama import DEFAULT_HOST
from ..router import load_agents, route_task

logger = logging.getLogger(__name__)

EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text")

#: The latent (embedding) route actually ran and picked the winner.
LATENT = "latent"
#: A supplied path sits under a role's ``owns`` -- a hard signal that beats
#: embeddings, so the latent route is skipped BY DESIGN (not by failure).
PATH_OWNED = "keyword_path_owned"
#: The latent route could not run; the keyword router produced the agent.
FALLBACK = "keyword_fallback"

# Two roles scoring within this of each other is a coin flip, not a decision.
_TIE_EPS = 1e-12

# Success-only cache. Keyed by (host, model, roster fingerprint) so that a
# changed roster re-embeds, and -- critically -- so that a FAILURE is never
# stored. See "Cache poisoning" in the module docstring.
_ROLE_VEC_CACHE: dict[tuple, tuple[tuple[str, tuple[float, ...]], ...]] = {}


def _default_host() -> str:
    return os.environ.get("OLLAMA_HOST", DEFAULT_HOST)


def _default_model() -> str:
    # Re-read at call time: reading only at import made the module blind to an
    # env var set after import (the env-var-drift class this repo has hit).
    return os.environ.get("OLLAMA_EMBED_MODEL", EMBED_MODEL)


@dataclass(frozen=True)
class LatentRouteResult:
    """Why this agent was chosen -- and whether the latent route ran at all.

    ``mechanism`` is the load-bearing field. ``ran`` is true only for
    :data:`LATENT`; for anything else ``error_kind``/``reason`` say what
    stopped it. A caller that ignores this and reads ``.agent`` gets exactly
    the old behaviour, which is why the legacy wrapper also logs.
    """

    agent: dict
    mechanism: str
    reason: str
    attempted: bool
    host: str | None = None
    model: str | None = None
    error_kind: str | None = None
    detail: str | None = None
    scores: tuple[tuple[str, float], ...] = ()
    margin: float | None = None
    dimension: int | None = None
    embed_calls: int = 0

    @property
    def ran(self) -> bool:
        """True iff the embedding route produced this choice."""
        return self.mechanism == LATENT

    @property
    def name(self) -> str:
        return self.agent.get("name", "")

    def explain(self) -> str:
        """One line a human or a log reader can act on."""
        if self.mechanism == LATENT:
            margin = "n/a" if self.margin is None else f"{self.margin:.4f}"
            return (f"latent route RAN and chose {self.name!r} "
                    f"(model={self.model}, margin={margin}, dim={self.dimension})")
        if self.mechanism == PATH_OWNED:
            return (f"latent route SKIPPED BY DESIGN ({self.reason}); "
                    f"keyword router chose {self.name!r}")
        return (f"latent route NEVER RAN [{self.error_kind}]: {self.reason}; "
                f"fell back to keyword router, which chose {self.name!r}")

    def to_dict(self) -> dict:
        return {
            "agent": self.name,
            "mechanism": self.mechanism,
            "ran": self.ran,
            "attempted": self.attempted,
            "reason": self.reason,
            "error_kind": self.error_kind,
            "detail": self.detail,
            "host": self.host,
            "model": self.model,
            "scores": [list(s) for s in self.scores],
            "margin": self.margin,
            "dimension": self.dimension,
            "embed_calls": self.embed_calls,
        }


def _classify_http(exc: urllib.error.HTTPError) -> tuple[str, str]:
    """Map an embedding-endpoint HTTP error onto a cause the operator can fix.

    'The host is down' and 'the host is up but has no embedding model' need
    completely different remedies, and the old code collapsed both to ``None``.
    """
    try:
        body = exc.read().decode("utf-8", "replace")[:300]
    except Exception:  # pragma: no cover - body already consumed/closed
        body = ""
    low = body.lower()
    if exc.code == 404 or "not found" in low or "try pulling it" in low:
        return "model_not_found", body or f"HTTP 404 from embeddings endpoint"
    if "does not support embeddings" in low or "--embeddings" in low:
        return "embeddings_unsupported", body
    return "http_error", body or f"HTTP {exc.code}"


def _validate_vector(v: object) -> tuple[list[float] | None, str | None, str | None]:
    """Reject answers that are shaped like embeddings but carry no signal.

    Returns ``(vector, error_kind, detail)``. An empty list, a non-numeric
    element, a NaN/inf, or a zero-norm vector are all FAILURES -- each one
    would otherwise flow into ``_cosine`` and yield 0.0 for every role, which
    ``max()`` turns into an arbitrary pick that looks authoritative.
    """
    if v is None:
        return None, "bad_response", "response had no 'embedding' field"
    if not isinstance(v, list) or not v:
        return None, "empty_embedding", f"embedding was {type(v).__name__} of length 0"
    out: list[float] = []
    for x in v:
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            return None, "bad_response", f"non-numeric element {type(x).__name__}"
        fx = float(x)
        if not math.isfinite(fx):
            return None, "degenerate_vector", "embedding contained NaN/inf"
        out.append(fx)
    if math.sqrt(sum(x * x for x in out)) == 0.0:
        return None, "degenerate_vector", "embedding had zero norm (all zeros)"
    return out, None, None


def _is_timeout(exc: BaseException) -> bool:
    """Did this failure come from OUR deadline rather than from the network?

    A socket deadline surfaces two ways depending on where urllib gives up:
    directly as :class:`TimeoutError` (``socket.timeout`` is an alias for it
    since 3.10), or wrapped in a ``URLError`` whose ``reason`` is that same
    object. Both are the same event and must classify the same way.
    """
    if isinstance(exc, TimeoutError):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, TimeoutError)


def _timeout_s(env: str, default: float) -> float:
    """A positive float from ``env``, else ``default``. Never raises: a typo in
    an operator's environment must not take routing down."""
    raw = os.environ.get(env, "")
    if not raw.strip():
        return default
    try:
        val = float(raw)
    except (TypeError, ValueError):
        logger.warning("semantic_route: %s=%r is not a number; using %.1fs",
                       env, raw, default)
        return default
    if val <= 0 or not math.isfinite(val):
        logger.warning("semantic_route: %s=%r is not a positive duration; "
                       "using %.1fs", env, raw, default)
        return default
    return val


#: Deadline for an embedding call against a backend that has already answered
#: once in this batch. 10s was the ONLY timeout this module had, and it is
#: correct for the warm case: MEASURED 2026-07-29, a warm ``nomic-embed-text``
#: on 127.0.0.1 answers in 0.18s.
EMBED_TIMEOUT_ENV = "DAEDALUS_EMBED_TIMEOUT_S"
DEFAULT_EMBED_TIMEOUT_S = 10.0

#: Deadline for the FIRST embedding call of a batch, which is the one that may
#: have to pull the model off disk and into VRAM.
#:
#: THIS IS THE BUG THAT MADE THE WHOLE FEATURE DEAD, and it is worth stating
#: plainly because nothing else in the module could have revealed it. The single
#: 10s deadline above was applied to the cold call too. MEASURED 2026-07-29 on
#: this repo's own box, against the very backend the harness ships with:
#:
#:     cold `nomic-embed-text` first call ... 15.48s   -> exceeded the 10s cap
#:     the same call once warm ..............  0.18s
#:
#: So on every freshly started process the first role embedding hit the cap,
#: `_role_vectors_detailed` aborted the batch, and the route degraded to the
#: keyword router -- reporting ``host_unreachable`` about a host that was up,
#: healthy and 0.18s away. Because failures are deliberately never cached (see
#: the docstring), every subsequent call in that process paid another 10s and
#: degraded again. The latent route was fully wired into
#: ``provider_router.route_and_select``, fully tested, and had MEASURED never
#: run in production: 0 of 5 live probes.
#:
#: Only the first call of a batch pays this, and a genuinely absent daemon
#: still fails in milliseconds with ECONNREFUSED rather than timing out -- a
#: timeout means something ACCEPTED the connection and is thinking, which is
#: exactly the case worth waiting for. 60s is ~4x the measured cold load, for
#: a slower disk or a larger embedding model.
EMBED_COLD_TIMEOUT_ENV = "DAEDALUS_EMBED_COLD_TIMEOUT_S"
DEFAULT_EMBED_COLD_TIMEOUT_S = 60.0


def _embed_detailed(text: str, host: str, model: str,
                    timeout: float | None = None,
                    ) -> tuple[list[float] | None, str | None, str | None]:
    """The backend boundary. Returns ``(vector, error_kind, detail)``.

    ``timeout`` defaults to the WARM budget; callers that know they may be
    triggering a model load pass the cold one.
    """
    if timeout is None:
        timeout = _timeout_s(EMBED_TIMEOUT_ENV, DEFAULT_EMBED_TIMEOUT_S)
    url = host.rstrip("/") + "/api/embeddings"
    body = json.dumps({"model": model, "prompt": text}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        # Must precede URLError: HTTPError is a subclass of it.
        kind, detail = _classify_http(exc)
        return None, kind, detail
    except (urllib.error.URLError, OSError) as exc:
        # A DEADLINE and an ABSENT HOST are different findings with different
        # remedies, and collapsing them sent an operator to restart a daemon
        # that was already running. "embed_timeout" names the budget it blew so
        # the receipt says which knob to turn.
        if _is_timeout(exc):
            return None, "embed_timeout", (
                f"no answer within {timeout:g}s (the host accepted the "
                f"connection, so it is up); raise {EMBED_COLD_TIMEOUT_ENV} / "
                f"{EMBED_TIMEOUT_ENV} or pre-load the model")
        return None, "host_unreachable", f"{type(exc).__name__}: {exc}"
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        return None, "bad_response", f"non-JSON response: {exc}"
    if not isinstance(payload, dict):
        return None, "bad_response", f"response was {type(payload).__name__}, not object"
    return _validate_vector(payload.get("embedding"))


def _embed(text: str, host: str, model: str) -> list[float] | None:
    """Back-compat shim: the vector, or None on any failure."""
    return _embed_detailed(text, host, model)[0]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (na * nb)


def _role_text(agent: dict) -> str:
    return " ".join([agent.get("name", ""), *agent.get("triggers", []), *agent.get("owns", [])])


def _roster_fingerprint(agents: list[dict]) -> tuple:
    return tuple((a.get("name", ""), _role_text(a)) for a in agents)


def _role_vectors_detailed(
    host: str, model: str, agents: list[dict] | None = None,
) -> tuple[tuple[tuple[str, tuple[float, ...]], ...] | None, str | None, str | None, int]:
    """Embed every role. Returns ``(vectors, error_kind, detail, embed_calls)``.

    Only SUCCESSES are cached. Caching the ``None`` -- as the previous
    ``@lru_cache`` did -- meant one blip killed the route for the process.
    """
    if agents is None:
        agents = load_agents()
    if not agents:
        return None, "no_agents", "no agent roles configured", 0
    key = (host, model, _roster_fingerprint(agents))
    cached = _ROLE_VEC_CACHE.get(key)
    if cached is not None:
        return cached, None, None, 0
    vecs: list[tuple[str, tuple[float, ...]]] = []
    calls = 0
    cold = _timeout_s(EMBED_COLD_TIMEOUT_ENV, DEFAULT_EMBED_COLD_TIMEOUT_S)
    warm = _timeout_s(EMBED_TIMEOUT_ENV, DEFAULT_EMBED_TIMEOUT_S)
    for agent in agents:
        calls += 1
        # Only the FIRST call may be paying for a model load. Handing the cold
        # budget to all of them would let a wedged backend hold routing for
        # roles*cold seconds; as written the worst case is one cold budget,
        # because the first failure aborts the batch.
        v, kind, detail = _embed_detailed(_role_text(agent), host, model,
                                          timeout=cold if calls == 1 else warm)
        if v is None:
            # Deliberately NOT cached.
            return None, kind, f"embedding role {agent.get('name','?')!r} failed: {detail}", calls
        vecs.append((agent.get("name", ""), tuple(v)))
    result = tuple(vecs)
    _ROLE_VEC_CACHE[key] = result
    return result, None, None, calls


def _role_vectors(host: str, model: str) -> tuple[tuple[str, tuple[float, ...]], ...] | None:
    """Back-compat shim: the role vectors, or None on any failure."""
    return _role_vectors_detailed(host, model)[0]


def _cache_clear() -> None:
    """Drop memoised role vectors (roster change, or test isolation)."""
    _ROLE_VEC_CACHE.clear()


# Keep the lru_cache-shaped call site working for anyone who used it.
_role_vectors.cache_clear = _cache_clear  # type: ignore[attr-defined]
cache_clear = _cache_clear


def _path_owned(paths: list[str], agents: list[dict] | None = None) -> bool:
    low = [p.replace("\\", "/").lower() for p in paths]
    for agent in (load_agents() if agents is None else agents):
        if any(o.lower() in p for o in agent.get("owns", []) for p in low):
            return True
    return False


def semantic_route_explained(
    objective: str,
    paths: list[str] | None = None,
    host: str | None = None,
    model: str | None = None,
    repo_root: str | None = None,
    active_agents: list[str] | None = None,
) -> LatentRouteResult:
    """Route, and say HOW -- the honest entry point.

    ``repo_root``/``active_agents`` thread through to the roster so the latent
    route sees the same agents the keyword router does. Without them a repo
    whose crew lives in ``<repo>/.agentenv/agents/`` would be embedded against
    the global roster and routed to a role it does not have.
    """
    paths = paths or []
    host = host or _default_host()
    model = model or _default_model()
    agents = load_agents(repo_root, active_agents)

    def _keyword(mechanism: str, reason: str, *, attempted: bool,
                 error_kind: str | None = None, detail: str | None = None,
                 calls: int = 0) -> LatentRouteResult:
        agent = route_task(objective, paths, repo_root=repo_root,
                           active_agents=active_agents)
        return LatentRouteResult(
            agent=agent, mechanism=mechanism, reason=reason, attempted=attempted,
            host=host, model=model, error_kind=error_kind, detail=detail,
            embed_calls=calls,
        )

    # Path ownership is precise -- let the keyword router handle those directly.
    if _path_owned(paths, agents):
        return _keyword(PATH_OWNED,
                        "a supplied path is under a role's `owns`, which is a "
                        "harder signal than embedding similarity",
                        attempted=False)

    role_vecs, kind, detail, calls = _role_vectors_detailed(host, model, agents)
    if role_vecs is None:
        return _keyword(FALLBACK, f"could not embed the agent roles ({kind})",
                        attempted=calls > 0, error_kind=kind, detail=detail,
                        calls=calls)

    # ``calls == 0`` means the role vectors came from the cache, so nothing in
    # THIS call has proven the backend warm -- the model may well have been
    # evicted since. That makes the objective embed the cold call, and giving
    # it the warm budget would reintroduce the same silent degradation one
    # cache hit later.
    q, kind, detail = _embed_detailed(
        objective, host, model,
        timeout=(_timeout_s(EMBED_COLD_TIMEOUT_ENV, DEFAULT_EMBED_COLD_TIMEOUT_S)
                 if calls == 0 else None))
    calls += 1
    if q is None:
        return _keyword(FALLBACK, f"could not embed the objective ({kind})",
                        attempted=True, error_kind=kind, detail=detail, calls=calls)

    dim = len(q)
    bad_dims = sorted({len(v) for _, v in role_vecs} - {dim})
    if bad_dims:
        # zip() would silently score a truncated prefix and call it confidence.
        return _keyword(
            FALLBACK, "role and objective embeddings have different dimensions",
            attempted=True, error_kind="dimension_mismatch",
            detail=f"objective dim={dim}, role dims={bad_dims}", calls=calls)

    scored = sorted(((name, _cosine(q, list(vec))) for name, vec in role_vecs),
                    key=lambda nv: nv[1], reverse=True)
    margin = scored[0][1] - scored[1][1] if len(scored) > 1 else None
    if margin is not None and margin <= _TIE_EPS:
        # Every role equidistant means the backend gave us no signal; picking
        # the first one and calling it a route is the defect, not the fix.
        return _keyword(
            FALLBACK, "every role scored identically, so the embedding carried "
                      "no discriminating signal",
            attempted=True, error_kind="ambiguous",
            detail=f"top score {scored[0][1]:.6f} tied across "
                   f"{sum(1 for _, s in scored if s >= scored[0][1] - _TIE_EPS)} roles",
            calls=calls)

    best_name = scored[0][0]
    # Resolve against the SAME roster we embedded; a fresh load_agents() here
    # could raise StopIteration if the roster changed underneath us.
    agent = next((a for a in agents if a.get("name") == best_name), None)
    if agent is None:  # pragma: no cover - roster changed mid-call
        return _keyword(FALLBACK, "winning role vanished from the roster",
                        attempted=True, error_kind="roster_changed",
                        detail=best_name, calls=calls)

    return LatentRouteResult(
        agent=agent, mechanism=LATENT,
        reason=f"nearest role embedding to the objective (cos={scored[0][1]:.4f})",
        attempted=True, host=host, model=model,
        scores=tuple(scored), margin=margin, dimension=dim, embed_calls=calls,
    )


def semantic_route(objective: str, paths: list[str] | None = None,
                   host: str | None = None, model: str | None = None,
                   repo_root: str | None = None,
                   active_agents: list[str] | None = None) -> dict:
    """Return the chosen agent dict. Falls back to keyword routing on any miss.

    Back-compatible with the original signature. Callers that need to know
    WHICH route fired should use :func:`semantic_route_explained`; this wrapper
    cannot express it in its return type, so it logs instead -- a skipped
    latent route is never silent.
    """
    result = semantic_route_explained(objective, paths, host, model,
                                      repo_root=repo_root, active_agents=active_agents)
    if result.mechanism == FALLBACK:
        logger.warning("semantic_route: %s", result.explain())
    else:
        logger.info("semantic_route: %s", result.explain())
    return result.agent
