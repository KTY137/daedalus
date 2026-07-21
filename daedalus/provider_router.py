"""Second-stage routing: given the chosen agent + task, pick the *provider*.

Stage 1 (:mod:`daedalus.router`) picks WHO (which specialist role).
Stage 2 (here) picks WHERE that role runs, on two axes:

* data sensitivity  -> may bytes leave the machine to an untrusted API?
* change risk       -> may a read-only free model do more than review?

Policy (confirmed with the user):
  - Not external-eligible role            -> Claude (trusted, write).
  - Sensitive data                        -> local Ollama (read-only); Claude
                                             applies any change. NEVER DeepSeek,
                                             NEVER Codex (both external).
  - Non-sensitive, high-risk *write*      -> Claude writes.
  - Non-sensitive, low-risk / review-only -> DeepSeek (cheap) else Ollama else
                                             Codex CLI else Claude. Codex sits
                                             between the local bench and the
                                             Claude lane in the auto fallback.

Free providers are read-only: their ``advisory`` output is reviewed and applied
by a write-capable, trusted provider. A free model can propose; never merge.
"""

from __future__ import annotations

from dataclasses import dataclass

from .providers import available_providers
from .providers.personas import culture, persona_for
from .sensitivity import Policy, change_risk, classify_data

_REVIEW_ONLY_TERMS = (
    "review", "audit", "summar", "draft", "docstring", "comment", "changelog",
    "explain", "describe", "critique", "proofread", "lint",
)


def _is_review_only(objective: str) -> bool:
    obj = objective.lower()
    return any(term in obj for term in _REVIEW_ONLY_TERMS)


# Above this share of newly-escalated modules the fence stops being a signal
# about THIS edit and becomes a property of the repo: "reaches something fenced"
# would be true of nearly every file, every task would land on the paid lane,
# and the operator's rational response is to switch the whole feature off --
# trading a partial fence for no fence. 0.75 is deliberately generous (it keeps
# the guard ON well past the 0.5 no-information point) because a false
# escalation costs one Claude call and a missed one costs a hardware interlock;
# the fallback is to today's path-local risk, which still fences the repo's
# safety trees literally.
FENCE_DOMINANCE_THRESHOLD = 0.75
# ...but a fraction over a handful of modules is noise, not dominance. A 3-file
# repo whose one leaf feeds its one controller scores 100% and would stand the
# fence down on the strength of two data points -- while the failure the
# guardrail exists to prevent (an operator buried in escalations who disables
# the feature) cannot happen at that size, because escalating everything in a
# 3-module repo costs three Claude calls. Below this many candidate modules the
# fraction is ignored and the fence stays UP.
FENCE_DOMINANCE_MIN_SAMPLE = 20


def _mode(provider: str, review_only: bool, risk: str) -> str:
    """write = may apply; advisory = read-only proposal.
      - Claude: always write.
      - Ollama: writes only LOW-risk (reduced rights); MID-risk it may only
        read + advise; review-only is advisory.
      - Codex: same reduced rights as Ollama -- LOW-risk may edit in place
        (read-only sandbox otherwise); routing already keeps sensitive and
        high-risk work away from it.
      - DeepSeek: always advisory (external, read-only)."""
    if provider == "deepseek":
        return "advisory"
    if provider in ("ollama", "codex_cli"):
        # LOW-risk always writes directly (zero Claude tokens); MID only advises.
        # review_only tasks just won't touch files, so "write" is harmless there.
        return "write" if risk == "low" else "advisory"
    return "write"                 # claude_cli


@dataclass
class ProviderDecision:
    provider: str          # claude_cli | deepseek | ollama | codex_cli
    mode: str              # "write" (may apply) | "advisory" (read-only proposal)
    persona: str           # shadow persona name for this (provider, role)
    reason: str
    sensitive: bool
    risk: str              # "low" | "high"
    # Blast-radius verdict, present ONLY when a repo_root/idx was supplied.
    # Defaulted + omitted from as_dict() when absent so a caller that never asked
    # for the check gets a byte-identical dict to before it existed.
    reachability: dict | None = None

    @property
    def culture(self) -> str:
        return culture(self.provider)

    def as_dict(self) -> dict:
        out = {
            "provider": self.provider,
            "mode": self.mode,
            "persona": self.persona,
            "reason": self.reason,
            "sensitive": self.sensitive,
            "risk": self.risk,
            "culture": self.culture,
        }
        if self.reachability is not None:
            out["reachability"] = self.reachability
        return out


def _index_rel(path: str, roots: tuple[str, ...]) -> str:
    """An edited path expressed the way the index keys its nodes (repo-relative,
    forward slashes). Absolute paths are stripped of whichever known root they
    sit under; case-insensitively, because Windows hands us both spellings."""
    norm = path.replace("\\", "/")
    for root in roots:
        r = root.replace("\\", "/").rstrip("/")
        if r and norm.lower().startswith(r.lower() + "/"):
            norm = norm[len(r) + 1:]
            break
    return norm[2:] if norm.startswith("./") else norm


def _looks_like_missed_source(raw: str, rel: str, roots: tuple[str, ...]) -> bool:
    """True when ``rel`` is a file the blast-radius graph SHOULD have known
    about: a language structcore can parse, present on disk, yet not a node.

    Existence is only ever checked UNDER a known root (or on an absolute path
    the caller supplied). Resolving a bare relative path against the process cwd
    would make the verdict depend on where the harness happens to be started --
    a fence whose answer moves with the working directory is not a fence.
    """
    import os
    from pathlib import Path

    from .structcore.languages import spec_for

    if spec_for(rel) is None:
        return False
    candidates = [Path(raw)] if os.path.isabs(raw) else []
    candidates += [Path(r) / rel for r in roots]
    for c in candidates:
        try:
            if c.is_file():
                return True
        except OSError:                    # unreadable path is not evidence
            continue
    return False


def _reachability_precheck(
    paths: list[str],
    policy: Policy | None,
    repo_root: str | None,
    idx: dict | None,
) -> dict | None:
    """Ask the import graph whether any edited path FEEDS a fenced module.

    Returns None when no check was requested (no ``repo_root``/``idx``) -- the
    caller must then behave exactly as it did before this existed. Otherwise a
    verdict dict; ``escalate`` True means the local write lane must be refused.

    FAIL-CLOSED. Once the caller has asked "is this edit's blast radius safe?",
    an index we could not build, a traversal we had to truncate, or a crash
    anywhere in the walk is an *unknown* answer, and handing an unknown to a 7B
    model with write rights is precisely the under-escalation this check exists
    to remove. The whole computation is therefore inside the guard -- an
    exception from a parser three layers down must not land the task on the
    local write lane by default.
    """
    if idx is None and not repo_root:
        return None
    # Lazy, like the sensitivity imports elsewhere: the safety modules must not
    # drag the whole structcore parser stack into every process that routes.
    from .sensitivity import DEFAULT_POLICY

    verdict: dict = {"checked": True, "escalate": False, "reason": None,
                     "hops": None, "chain": [], "fenced_node": None,
                     "dominance": None, "unresolved": [], "error": None}
    try:
        return _reachability_verdict(
            paths, (policy or DEFAULT_POLICY).high_risk_path_substrings,
            repo_root, idx, verdict)
    except Exception as exc:                       # noqa: BLE001 - see docstring
        verdict["error"] = f"{type(exc).__name__}: {exc}"
        verdict["escalate"] = True
        verdict["reason"] = (
            f"blast-radius index unavailable ({verdict['error']}); "
            "cannot prove this edit's dependents are safe -> trusted lane")
        return verdict


def _reachability_verdict(paths: list[str], fenced, repo_root: str | None,
                          idx: dict | None, verdict: dict) -> dict:
    """The traversal itself. Raises freely; ``_reachability_precheck`` owns the
    fail-closed translation of any failure into an escalation."""
    from .structcore import graph as _graph

    if idx is None:
        from .structcore.index import cached_index
        idx = cached_index(repo_root)

    # A DEGENERATE index is the fail-open trap here: pointing at something that
    # is not a repo does not RAISE, it returns an index with no modules, and
    # every lookup then answers "no known dependents" -- which reads exactly
    # like "safe". Recorded so it is never invisible, but not escalated on its
    # own: a tree with no parseable source also has no fenced module to reach,
    # and blanket-escalating would take the cheap lane away from every docs-only
    # repo. The dangerous half of this case -- a real source file that exists on
    # disk and is still missing from the graph -- is caught per path below,
    # which is the check that keeps working when the index is empty.
    if not (idx.get("modules") or idx.get("import_edges")):
        verdict["error"] = "index contains no modules"

    dom = _graph.fenced_dominance(idx, fenced)
    fallback = (dom["fraction"] > FENCE_DOMINANCE_THRESHOLD
                and dom["candidates"] >= FENCE_DOMINANCE_MIN_SAMPLE)
    verdict["dominance"] = {**dom, "threshold": FENCE_DOMINANCE_THRESHOLD,
                            "min_sample": FENCE_DOMINANCE_MIN_SAMPLE,
                            "fallback": fallback}
    if fallback:
        # NEVER silent: the operator has to be able to see that the graph fence
        # is standing down and only path-local risk is holding the line.
        verdict["reason"] = (
            f"fence dominates the graph ({dom['escalated']}/{dom['candidates']} "
            f"= {dom['fraction']:.0%} of editable modules reach it, over the "
            f"{FENCE_DOMINANCE_THRESHOLD:.0%} threshold); reachability check "
            "stood down, path-local risk only")
        return verdict

    roots = tuple(r for r in (str(idx.get("root") or ""), str(repo_root or "")) if r)
    best: tuple | None = None
    for raw in paths:
        rel = _index_rel(raw, roots)
        r = _graph.fenced_reachability(idx, rel, fenced)
        if r["truncated"]:
            verdict["escalate"] = True
            verdict["reason"] = (
                f"blast radius of '{rel}' exceeded {_graph.REACH_VISIT_CAP} "
                "modules before a verdict; treating as unproven -> trusted lane")
            return verdict
        if not r["known"]:
            verdict["unresolved"].append(rel)
            # An unknown path is normally harmless: docs and data have no
            # importers, and a file that does not exist yet has no dependents at
            # all, so escalating those would price the cheap lane out of exactly
            # the work it is for. What is NOT harmless is a source file that
            # EXISTS on disk in a language this index parsed and is still absent
            # from the graph -- a mis-scoped repo_root or a stale index. There
            # the graph is wrong about the repo, not silent about a non-module,
            # and its silence must not be read as a clean bill of health.
            if _looks_like_missed_source(raw, rel, roots):
                verdict["escalate"] = True
                verdict["reason"] = (
                    f"'{rel}' exists on disk but is absent from the blast-radius "
                    "graph (mis-scoped or stale index); its dependents are "
                    "unknown -> trusted lane")
                return verdict
        if not r["reaches"]:
            continue
        # Total order over candidates so two processes name the same chain.
        key = (r["hops"], rel, r["fenced_node"])
        if best is None or key < best[0]:
            best = (key, rel, r)
    verdict["unresolved"] = sorted(verdict["unresolved"])
    if best is not None:
        _, rel, r = best
        verdict["escalate"] = True
        verdict["hops"] = r["hops"]
        verdict["chain"] = r["chain"]
        verdict["fenced_node"] = r["fenced_node"]
        # A blocked write the operator cannot explain is a blocked write the
        # operator will disable, so the chain is spelled out, not summarised.
        verdict["reason"] = (
            f"blast-radius fence: {r['via']} ({r['hops']} hops) -- edit reaches "
            f"fenced '{r['fenced_node']}' (rule '{r['fragment']}') -> trusted lane")
    return verdict


def select_provider(
    agent: dict,
    objective: str,
    paths: list[str] | None = None,
    availability: dict[str, bool] | None = None,
    policy: Policy | None = None,
    repo_root: str | None = None,
    idx: dict | None = None,
) -> ProviderDecision:
    """``repo_root`` (or a pre-built ``idx``) is what turns on the SAFETY-CLASS
    REACHABILITY check: the literal path fence in ``change_risk`` only asks "is
    this file dangerous?", never "does this file feed something dangerous?".
    Both default to None, and with them absent every decision is byte-identical
    to the pre-check-less router -- opting in is the operator's move."""
    paths = paths or []
    avail = availability if availability is not None else available_providers()
    data = classify_data(paths, extra_text=objective, policy=policy)
    risk = change_risk(objective, paths, policy=policy)
    # Only worth the index when the cheap path-local check has NOT already
    # fenced this edit: reachability can only raise risk to "high", so on an
    # already-high task it cannot change the outcome and would just cost a scan.
    reach = None
    if risk != "high":
        reach = _reachability_precheck(paths, policy, repo_root, idx)
        if reach and reach["escalate"]:
            risk = "high"
    review_only = _is_review_only(objective)
    external_ok = bool(agent.get("external_ok", False))
    name = agent.get("name", "")

    def decide(provider: str, reason: str) -> ProviderDecision:
        # Any provider that is chosen but unreachable degrades to Claude.
        if provider != "claude_cli" and not avail.get(provider, False):
            return ProviderDecision(
                "claude_cli", "write", persona_for("claude_cli", name),
                f"{provider} unavailable; fell back to Claude ({reason})",
                data.sensitive, risk, reach,
            )
        return ProviderDecision(
            provider, _mode(provider, review_only, risk), persona_for(provider, name),
            reason, data.sensitive, risk, reach,
        )

    # 1. Roles that must never leave the trusted lane may still use the local
    # on-machine bench for review-only advisory work. They never go to an
    # external provider and they never write locally.
    if not external_ok:
        if review_only and avail.get("ollama", False):
            return ProviderDecision(
                "ollama", "advisory", persona_for("ollama", name),
                f"role '{name}' is trusted-only; local Ollama advisory review",
                data.sensitive, risk, reach,
            )
        return decide("claude_cli", f"role '{name}' is not external-eligible")

    # 2. High-risk *write* stays senior -- covers sensitive+high too. When the
    # reachability pre-check is what raised the risk, its chain becomes the
    # reason: the operator must be able to see WHICH fenced module this leaf
    # feeds, or the block reads as arbitrary and gets switched off.
    if risk == "high" and not review_only:
        if reach and reach["escalate"]:
            return decide("claude_cli", reach["reason"])
        return decide("claude_cli", "high change-risk write stays on Claude")

    # 3. Sensitive data: local Ollama only (low->write, mid->advise). NEVER an
    # external lane (DeepSeek/Codex) -- if the bench is down this degrades to
    # Claude via decide(), still never external.
    if data.sensitive:
        return decide("ollama", "sensitive content -> local bench (stays on machine)")

    # 4. Non-sensitive low/mid (or review): cheapest eligible worker. Codex is
    # the external fallback BETWEEN the local bench and the Claude lane.
    if avail.get("deepseek", False):
        return decide("deepseek", "non-sensitive low/mid -> DeepSeek (read-only)")
    if avail.get("ollama", False):
        return decide("ollama", "non-sensitive low/mid -> local bench")
    return decide("codex_cli", "non-sensitive low/mid -> Codex CLI (bench down)")


def route_and_select(
    objective: str,
    paths: list[str] | None = None,
    availability: dict[str, bool] | None = None,
    policy: Policy | None = None,
    active_agents: list[str] | None = None,
    repo_root: str | None = None,
) -> tuple[dict, ProviderDecision]:
    """Convenience: pick both the role and the provider in one call.

    ``repo_root`` threads through to :func:`router.route_task` so per-repo
    agent rosters (``<repo>/.agentenv/agents/``) are visible to routing --
    without it, only the global registry is consulted and a repo whose crew
    lives entirely in its own ``.agentenv`` cannot route at all. It ALSO reaches
    :func:`select_provider`, which is what puts the live mutate path
    (``offload`` -> here) behind the blast-radius fence rather than leaving the
    check available but unwired."""
    from .router import route_task

    agent = route_task(objective, paths or [], repo_root=repo_root,
                       active_agents=active_agents)
    decision = select_provider(agent, objective, paths, availability, policy,
                               repo_root=repo_root)
    return agent, decision
