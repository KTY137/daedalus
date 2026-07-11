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

    @property
    def culture(self) -> str:
        return culture(self.provider)

    def as_dict(self) -> dict:
        return {
            "provider": self.provider,
            "mode": self.mode,
            "persona": self.persona,
            "reason": self.reason,
            "sensitive": self.sensitive,
            "risk": self.risk,
            "culture": self.culture,
        }


def select_provider(
    agent: dict,
    objective: str,
    paths: list[str] | None = None,
    availability: dict[str, bool] | None = None,
    policy: Policy | None = None,
) -> ProviderDecision:
    paths = paths or []
    avail = availability if availability is not None else available_providers()
    data = classify_data(paths, extra_text=objective, policy=policy)
    risk = change_risk(objective, paths, policy=policy)
    review_only = _is_review_only(objective)
    external_ok = bool(agent.get("external_ok", False))
    name = agent.get("name", "")

    def decide(provider: str, reason: str) -> ProviderDecision:
        # Any provider that is chosen but unreachable degrades to Claude.
        if provider != "claude_cli" and not avail.get(provider, False):
            return ProviderDecision(
                "claude_cli", "write", persona_for("claude_cli", name),
                f"{provider} unavailable; fell back to Claude ({reason})",
                data.sensitive, risk,
            )
        return ProviderDecision(
            provider, _mode(provider, review_only, risk), persona_for(provider, name),
            reason, data.sensitive, risk,
        )

    # 1. Roles that must never leave the trusted lane may still use the local
    # on-machine bench for review-only advisory work. They never go to an
    # external provider and they never write locally.
    if not external_ok:
        if review_only and avail.get("ollama", False):
            return ProviderDecision(
                "ollama", "advisory", persona_for("ollama", name),
                f"role '{name}' is trusted-only; local Ollama advisory review",
                data.sensitive, risk,
            )
        return decide("claude_cli", f"role '{name}' is not external-eligible")

    # 2. High-risk *write* stays senior -- covers sensitive+high too.
    if risk == "high" and not review_only:
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
    lives entirely in its own ``.agentenv`` cannot route at all."""
    from .router import route_task

    agent = route_task(objective, paths or [], repo_root=repo_root,
                       active_agents=active_agents)
    decision = select_provider(agent, objective, paths, availability, policy)
    return agent, decision
