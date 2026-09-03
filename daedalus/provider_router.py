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

import logging
import os
from dataclasses import dataclass

from .config import external_write_lanes_for_repo
from .providers import available_providers
from .runtimes.providers.personas import culture, persona_for
from .orchestration.semantic_route import FALLBACK, LATENT, semantic_route_explained
from .sensitivity import Policy, change_risk, classify_data

logger = logging.getLogger(__name__)

#: Operator kill switch for the latent (embedding) stage-1 route. Absent or any
#: non-off value = ON. The latent route is wired ON by default because an
#: opt-in flag that nothing sets is indistinguishable from the dead module this
#: replaced; the switch exists so a box with a sick embedder can be pinned to
#: keyword routing without an edit.
LATENT_ENV = "DAEDALUS_LATENT_ROUTE"
_LATENT_OFF = {"0", "false", "no", "off", ""}

#: Mechanism recorded when the operator switched the latent route off. This is
#: deliberately NOT ``FALLBACK``: "told not to run" and "tried and could not
#: run" are different operator situations, and collapsing them is the exact
#: defect the provenance rebuild exists to remove.
LATENT_DISABLED = "disabled"

#: The latent route RAN, produced a role, and was overruled because that role
#: would have moved the task to a different provider lane or write mode. A
#: fourth distinct situation: not a failure, not a design skip, not a route.
LATENT_OVERRULED = "latent_overruled_lane_change"

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


def _deepseek_write_allowed(
    write_lanes: tuple[str, ...], review_only: bool, risk: str
) -> bool:
    """May the DeepSeek lane APPLY this task rather than only advise it?

    Three conditions, ANDed, and each one is load-bearing:

    * the repository named "deepseek" in its policy ``external_write_lanes``
      (:func:`daedalus.config.resolve_external_write_lanes`). Absent the key --
      which is the default, and the state of every repo that has not opted in
      -- this is False and routing is byte-identical to the advisory-only era.
    * ``risk == "low"``. An external paid lane gets the SAME reduced rights the
      local bench has, not more: MID risk advises, HIGH never reaches here at
      all (branch 2 sends high-risk writes to Claude before this is asked).
    * not ``review_only``. A review task has nothing to apply, so "write" on one
      would only be a chance to apply something nobody asked for.

    Sensitivity is not re-checked here because it cannot be true at this point:
    branch 3 returns local-only for sensitive data before branch 4 runs. The
    provider re-checks it anyway, per file, before any byte leaves.

    The single source of truth for this question. :func:`_mode` decides the mode
    from it and branch 4 words its reason from it, so the two can never
    disagree -- a decision that says "write" with a reason that says
    "(read-only)" is how a paid write lane gets switched on by accident.
    """
    return "deepseek" in write_lanes and risk == "low" and not review_only


def _mode(provider: str, review_only: bool, risk: str,
          write_lanes: tuple[str, ...] = ()) -> str:
    """write = may apply; advisory = read-only proposal.
      - Claude: always write.
      - Ollama: writes only LOW-risk (reduced rights); MID-risk it may only
        read + advise; review-only is advisory.
      - Codex: same reduced rights as Ollama -- LOW-risk may edit in place
        (read-only sandbox otherwise); routing already keeps sensitive and
        high-risk work away from it.
      - DeepSeek: advisory, UNLESS the repository opted this lane into
        ``external_write_lanes`` and the task is low-risk and not review-only.

    ``write_lanes`` defaults to empty so every caller that predates the toggle
    -- and every repo that has not set the key -- gets exactly the mode table
    this function had before it existed."""
    if provider == "deepseek":
        return "write" if _deepseek_write_allowed(write_lanes, review_only, risk) else "advisory"
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
    # HOW stage 1 picked the role: embedding, path-ownership skip, or a keyword
    # fallback and the reason it fell back. Set only by :func:`route_and_select`,
    # which is the function that actually routes; ``select_provider`` is HANDED a
    # role and has no provenance to report, so it leaves this None and its dict
    # stays byte-identical. Without this the whole latent route is invisible one
    # layer up -- "chose by embedding" and "embedding never ran, keyword guessed"
    # would read the same to every caller, which is how the capability went quiet
    # the first time.
    latent_route: dict | None = None

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
        if self.latent_route is not None:
            out["latent_route"] = self.latent_route
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
    # Which UNTRUSTED external lanes this repository lets APPLY a change. Read
    # from the repo that will be WRITTEN, and empty for every repo that has not
    # opted in -- including every caller that passes no repo_root, so absence
    # keeps the pre-toggle routing exactly. Every failure mode inside the
    # resolver (no file, bad JSON, unknown lane name) also lands on empty.
    write_lanes = external_write_lanes_for_repo(repo_root)

    def decide(provider: str, reason: str) -> ProviderDecision:
        # Any provider that is chosen but unreachable degrades to Claude.
        if provider != "claude_cli" and not avail.get(provider, False):
            return ProviderDecision(
                "claude_cli", "write", persona_for("claude_cli", name),
                f"{provider} unavailable; fell back to Claude ({reason})",
                data.sensitive, risk, reach,
            )
        return ProviderDecision(
            provider, _mode(provider, review_only, risk, write_lanes),
            persona_for(provider, name),
            reason, data.sensitive, risk, reach,
        )

    # 1. Roles that must never leave the trusted lane may still use the local
    # on-machine bench for review-only advisory work -- and, since 2026-07-29,
    # for LOW-risk writes when the bench itself IS the trusted lane.
    #
    # "External" is a property of WHERE THE BYTES GO, and this repo already has
    # exactly one implementation of that question: ``lane_for_host``. This
    # branch used to answer it a second way -- by treating every non-Claude
    # provider as external -- and the two answers agreed right up until the
    # operator declared the RTX bench trusted. Then a trusted-only role's
    # docref write bounced off the free-lane gate as "belongs to the senior
    # crew", and the self-improvement loop's first three live attempts died
    # of it (MEASURED, first activation run). One predicate per question:
    # a trusted-only role may not reach an UNTRUSTED endpoint; a host the
    # single fence certifies as trusted is not one.
    if not external_ok:
        # Reachability is a safety escalation, not merely a price/routing hint.
        # It must dominate even a review-looking objective: a trusted-only role
        # plus a path that feeds a fenced module stays on the senior lane.
        if reach and reach["escalate"]:
            return decide("claude_cli", reach["reason"])
        if avail.get("ollama", False):
            from .sensitivity import lane_for_host
            ollama_host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
            if lane_for_host(ollama_host) == "trusted":
                if review_only:
                    return ProviderDecision(
                        "ollama", "advisory", persona_for("ollama", name),
                        f"role '{name}' is trusted-only and the local bench IS "
                        "the trusted lane (advisory review)",
                        data.sensitive, risk, reach,
                    )
                if risk == "low":
                    return ProviderDecision(
                        "ollama", "write", persona_for("ollama", name),
                        f"role '{name}' is trusted-only and the local bench IS "
                        "the trusted lane (low-risk write)",
                        data.sensitive, risk, reach,
                    )
            if review_only:
                # An untrusted bench still never sees repository content from a
                # trusted-only role -- the provider itself also refuses
                # (providers/ollama.py), but routing must not rely on that.
                return decide(
                    "claude_cli",
                    f"role '{name}' is trusted-only and OLLAMA_HOST is not a "
                    f"trusted lane")
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
    #
    # ORDER CHANGED 2026-07-29, and the reason is a measurement, not taste.
    # DeepSeek-first dated from when the local model could not reliably emit a
    # structured write (0% tool-call success) -- an advisory draft from a
    # smarter external model beat a write that never landed. Schema-constrained
    # decoding took the same 4.5GB model to 100% on this bench, so for LOW risk
    # the calculus inverted: a FREE lane that can WRITE (and whose work then
    # faces the gate) beats a PAID lane that may only advise. The trusted-host
    # check composes the single egress predicate rather than re-deriving it;
    # on an untrusted or absent bench the old order stands, and MID risk still
    # prefers the smarter advisory voice.
    if (risk == "low" and not review_only and avail.get("ollama", False)):
        from .sensitivity import lane_for_host as _lane
        if _lane(os.environ.get("OLLAMA_HOST",
                                "http://127.0.0.1:11434")) == "trusted":
            return decide("ollama",
                          "non-sensitive low -> trusted bench writes for free")
    # Opted-in external WRITE lane, second only to the free bench: a paid lane
    # that applies its own change is still worth less than a free one that
    # does, so this never outranks the trusted-bench branch above -- it is what
    # the bench being down or untrusted degrades TO, instead of degrading
    # straight to advisory. Off by default; `external_write_lanes` is the
    # operator's explicit, per-repo, version-controlled opt-in.
    if avail.get("deepseek", False) and _deepseek_write_allowed(
            write_lanes, review_only, risk):
        return decide("deepseek",
                      "non-sensitive low -> DeepSeek write lane "
                      "(repo opted in via external_write_lanes; PAID)")
    if avail.get("deepseek", False):
        return decide("deepseek", "non-sensitive low/mid -> DeepSeek (read-only)")
    if avail.get("ollama", False):
        return decide("ollama", "non-sensitive low/mid -> local bench")
    return decide("codex_cli", "non-sensitive low/mid -> Codex CLI (bench down)")


def _latent_enabled(explicit: bool | None) -> bool:
    """Explicit argument beats the environment; absent env means ON."""
    if explicit is not None:
        return bool(explicit)
    raw = os.environ.get(LATENT_ENV)
    if raw is None:
        return True
    return raw.strip().lower() not in _LATENT_OFF


def _latent_receipt(agent_name: str, mechanism: str, reason: str, *,
                    attempted: bool = False, error_kind: str | None = None,
                    detail: str | None = None) -> dict:
    """A receipt with EXACTLY the keys of ``LatentRouteResult.to_dict()``, plus
    :data:`lane_guard`.

    One shape whether the latent module answered, was switched off, or never
    got the chance -- a reader must never have to interpret a missing key, and
    "no ``mechanism`` field" must never be a third way of saying nothing ran.
    ``lane_guard`` is therefore always present and ``None`` when the guard did
    not fire, rather than appearing only on the runs where it did.
    """
    return {
        "agent": agent_name, "mechanism": mechanism, "ran": False,
        "attempted": attempted, "reason": reason, "error_kind": error_kind,
        "detail": detail, "host": None, "model": None, "scores": [],
        "margin": None, "dimension": None, "embed_calls": 0, "lane_guard": None,
    }


def _lane(decision: ProviderDecision, agent: dict) -> dict:
    """The part of a decision a role is allowed to move: where it runs and
    whether it may write. ``external_ok`` is carried for the reader -- it is the
    only role property ``select_provider`` consults, so it is the mechanism by
    which a stage-1 re-route moves a lane at all."""
    return {"provider": decision.provider, "mode": decision.mode,
            "external_ok": bool(agent.get("external_ok", False))}


def _apply_lane_guard(latent_agent: dict, latent_decision: ProviderDecision,
                      keyword_agent: dict, receipt: dict,
                      select) -> tuple[dict, ProviderDecision, dict]:
    """A LATENT DECISION MAY NEVER CHANGE THE LANE.

    Within a lane the embedding may steer freely -- that is where its value is
    and it costs nothing. Across a lane boundary the keyword router wins.

    The rule is principled rather than numeric on purpose. The measured trigger
    was ``the graph is hard to read``, where the live backend scored
    data-analysis-dev 0.4735 / docs-dev 0.4666 / ui-ux-dev 0.4638 -- a margin of
    0.0069, a three-way tie in all but name -- and that flipped the task from
    the trusted lane (qa-critic -> claude_cli) onto a local WRITE lane
    (data-analysis-dev -> ollama, mode=write). A margin that small is not
    evidence, and ``external_ok``/``write`` are not properties to gamble on. A
    confidence floor would have needed a number nobody had measured; this needs
    none, because it asks the question that actually matters -- did the lane
    move? -- instead of a proxy for it.

    The comparison is EMPIRICAL: both roles are run through the real
    ``select_provider``, so the guard cannot drift away from the policy it is
    guarding. Inferring the lane from ``external_ok`` alone would silently stop
    covering any future role property that reaches the decision.

    Never silent: an overrule gets its own ``mechanism`` and records both roles,
    both lanes and the margin. A filtered sample that does not announce itself
    would corrupt the very margin measurement this guard is waiting on.
    """
    if latent_agent.get("name") == keyword_agent.get("name"):
        return latent_agent, latent_decision, receipt

    keyword_decision = select(keyword_agent)
    latent_lane = _lane(latent_decision, latent_agent)
    keyword_lane = _lane(keyword_decision, keyword_agent)
    if (latent_lane["provider"], latent_lane["mode"]) == \
       (keyword_lane["provider"], keyword_lane["mode"]):
        return latent_agent, latent_decision, receipt        # steer freely

    guard = {
        "overruled": True,
        "latent_agent": latent_agent.get("name", ""),
        "latent_lane": latent_lane,
        "keyword_agent": keyword_agent.get("name", ""),
        "keyword_lane": keyword_lane,
        "margin": receipt.get("margin"),
        "reason": (
            f"the latent route chose {latent_agent.get('name','')!r} "
            f"({latent_lane['provider']}/{latent_lane['mode']}) but the keyword "
            f"router chose {keyword_agent.get('name','')!r} "
            f"({keyword_lane['provider']}/{keyword_lane['mode']}); a latent "
            "decision may not move the lane, so the keyword role stands"),
    }
    logger.warning("stage-1 route: LANE GUARD overruled the latent route -- %s "
                   "(margin=%s)", guard["reason"], receipt.get("margin"))
    # scores/margin/dimension are KEPT: they are real measurements, and the next
    # person measuring latent quality has to be able to see what was filtered.
    overruled = {**receipt, "agent": keyword_agent.get("name", ""),
                 "mechanism": LATENT_OVERRULED, "ran": False,
                 "reason": guard["reason"], "lane_guard": guard}
    return keyword_agent, keyword_decision, overruled


def _route_role(objective: str, paths: list[str], repo_root: str | None,
                active_agents: list[str] | None,
                latent: bool | None) -> tuple[dict, dict, dict]:
    """Stage 1: pick the role, and return ``(agent, keyword_agent, receipt)``.

    ``keyword_agent`` is what the keyword router would have returned on its own,
    which is what :func:`_apply_lane_guard` needs to compare lanes against. On
    every non-latent path the two are the same object, because the keyword
    router is what produced the agent there.

    FAIL SOFT, LOUDLY. The latent route reaches a network service, so it has
    failure modes routing itself must not inherit: an embedder that is down, a
    model that was never pulled, or a defect in the latent module itself. None
    of those may take routing down with them -- the keyword router is always
    the floor -- but none of them may be silent either, because a capability
    that degrades quietly reads as a working capability forever. Every path out
    of here therefore produces both an agent AND a receipt saying which path it
    was.

    The broad ``except`` is deliberate and is the fail-soft half: an unforeseen
    exception from the latent module (or anything it imports) must cost this
    call its embedding, not its ability to route. Note that the keyword retry
    is NOT wrapped -- a genuinely unroutable task, e.g. an empty roster, still
    raises exactly the error it raised before this was wired.
    """
    from .router import route_task

    def _keyword() -> dict:
        return route_task(objective, paths, repo_root=repo_root,
                          active_agents=active_agents)

    if not _latent_enabled(latent):
        agent = _keyword()
        receipt = _latent_receipt(
            agent.get("name", ""), LATENT_DISABLED,
            f"latent route switched off by the operator ({LATENT_ENV}); "
            "the keyword router chose this role")
        logger.info("stage-1 route: latent route DISABLED; keyword router chose %r",
                    agent.get("name", ""))
        return agent, agent, receipt

    try:
        result = semantic_route_explained(objective, paths, repo_root=repo_root,
                                          active_agents=active_agents)
    except Exception as exc:                     # noqa: BLE001 - see docstring
        agent = _keyword()
        detail = f"{type(exc).__name__}: {exc}"
        logger.warning(
            "stage-1 route: the latent route RAISED (%s); fell back to the "
            "keyword router, which chose %r", detail, agent.get("name", ""))
        return agent, agent, _latent_receipt(
            agent.get("name", ""), FALLBACK,
            "the latent route raised an exception", attempted=True,
            error_kind="latent_route_crashed", detail=detail)

    # The module reports its own mechanism honestly; escalate the one case an
    # operator can act on (the backend could not be used) to WARNING.
    if result.mechanism == FALLBACK:
        logger.warning("stage-1 route: %s", result.explain())
    else:
        logger.info("stage-1 route: %s", result.explain())
    receipt = {**result.to_dict(), "lane_guard": None}
    # Only the latent path can diverge from the keyword router; on the others
    # semantic_route produced its agent BY calling route_task, so re-running it
    # would cost a roster read to learn what we already hold.
    keyword_agent = _keyword() if result.mechanism == LATENT else result.agent
    return result.agent, keyword_agent, receipt


def route_and_select(
    objective: str,
    paths: list[str] | None = None,
    availability: dict[str, bool] | None = None,
    policy: Policy | None = None,
    active_agents: list[str] | None = None,
    repo_root: str | None = None,
    latent: bool | None = None,
) -> tuple[dict, ProviderDecision]:
    """Convenience: pick both the role and the provider in one call.

    ``repo_root`` threads through to :func:`router.route_task` so per-repo
    agent rosters (``<repo>/.agentenv/agents/``) are visible to routing --
    without it, only the global registry is consulted and a repo whose crew
    lives entirely in its own ``.agentenv`` cannot route at all. It ALSO reaches
    :func:`select_provider`, which is what puts the live mutate path
    (``offload`` -> here) behind the blast-radius fence rather than leaving the
    check available but unwired.

    Stage 1 is the LATENT route (embedding similarity) with the keyword router
    underneath it; ``latent=False`` (or ``DAEDALUS_LATENT_ROUTE=0``) pins it to
    keywords. Both ``repo_root`` and ``active_agents`` are threaded into it so
    the embeddings score the SAME roster this caller would accept -- scoring the
    global crew and returning a role the caller excluded is a routing bug, not a
    near miss. Whichever way it went is on ``decision.latent_route``.

    Stage 1 decides ``external_ok``, so a latent re-route CAN move a task
    between the trusted-only and external-eligible lanes -- which is why
    :func:`_apply_lane_guard` forbids exactly that. The embedding may steer
    within a lane; it may not move one. Everything downstream still fences the
    result as before."""
    agent, keyword_agent, latent_receipt = _route_role(
        objective, paths or [], repo_root, active_agents, latent)

    def _select(role: dict) -> ProviderDecision:
        return select_provider(role, objective, paths, availability, policy,
                               repo_root=repo_root)

    decision = _select(agent)
    if latent_receipt["mechanism"] == LATENT:
        agent, decision, latent_receipt = _apply_lane_guard(
            agent, decision, keyword_agent, latent_receipt, _select)
    decision.latent_route = latent_receipt
    return agent, decision
