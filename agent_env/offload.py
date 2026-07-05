"""The offload bridge -- the single seam that actually hands work to the free
bench, verifies the result, and either accepts it or escalates to Claude.

Live flow (the FrugalGPT cascade):

    load project policy -> route (policy-aware) -> local worker runs (guarded)
      -> VERIFIER GATE
          pass -> accept (zero Claude tokens)
          fail -> roll back the write + escalate to Claude

SAFETY (per Mary's review): the write-guard and egress scan are only real when
the *project policy* is loaded. So offload loads it and threads it everywhere,
and REFUSES any live write when no policy is available (fail-closed) -- otherwise
DEFAULT_POLICY's empty deny-list would leave hardware/safety code writable.
"""

from __future__ import annotations

import argparse
import json

from . import metrics
from .ikarus import FREE_LANES
from .provider_router import route_and_select
from .verifier import verify

_ALL = {"claude_cli": True, "ollama": True, "deepseek": True}


def offload(
    objective: str,
    repo_root: str,
    paths: list[str] | None = None,
    live: bool = False,
    availability: dict | None = None,
    run_tests: bool = False,
    project: str | None = None,
) -> dict:
    if availability is None:
        from .doctor import check
        ready = check()
        availability = {
            "claude_cli": ready["claude_cli"],
            "ollama": ready["can_offload_local"],
            "deepseek": ready["deepseek_key"],
        }

    # The policy is what makes the guards real. Resolve it from the registry or
    # the target repo's own .agentenv/agentenv.json. Only an explicit 'policy'
    # block enables writes; otherwise pol stays None and we fail closed.
    from .config import resolve_project
    from .sensitivity import load_policy
    pdata = resolve_project(repo_root, project)
    pol = load_policy(pdata) if (pdata and pdata.get("policy")) else None

    # Intended lane (all up) vs actual lane (given availability) -- both policy-aware.
    _, intended = route_and_select(objective, paths or [], _ALL, pol)
    agent, decision = route_and_select(objective, paths or [], availability, pol)
    eligible = intended.provider in FREE_LANES

    result = {
        "objective": objective, "owner": agent["name"], "provider": decision.provider,
        "persona": decision.persona, "mode": decision.mode, "risk": decision.risk,
        "sensitive": decision.sensitive, "eligible": eligible,
    }

    def _escalate(note: str, provider: str = "claude_cli") -> dict:
        result["action"] = "escalate_to_claude" if eligible else "senior"
        result["note"] = note
        metrics.record(provider=provider, action=result["action"], owner=agent["name"],
                       risk=decision.risk, eligible=eligible, note=note)
        return result

    if decision.provider not in FREE_LANES:
        return _escalate(decision.reason)

    if not live:
        result["action"] = "would_offload"
        metrics.record(provider=decision.provider, action="would_offload",
                       owner=agent["name"], risk=decision.risk, eligible=True)
        return result

    # FAIL-CLOSED: never let the bench WRITE without a loaded policy -- the guards
    # would be running under DEFAULT_POLICY (empty deny-list) and safety code
    # would be writable. Refuse and send it to Claude.
    if decision.mode == "write" and pol is None:
        return _escalate("refusing live write: no project policy loaded (guards off) -- pass --project")

    # --- live cascade -------------------------------------------------
    from .providers import get_provider
    worker = get_provider(decision.provider)
    run_kwargs = dict(objective=objective, repo_root=repo_root, paths=paths or [],
                      agent=agent, policy=pol)
    if decision.provider == "ollama":
        run_kwargs["writable"] = (decision.mode == "write")   # advisory truly can't write
    out = worker.run(**run_kwargs)
    report = out["report"]

    # For live writes, run the project test suite in the gate when we have it.
    test_command = test_cwd = None
    if pdata and (run_tests or report.get("files_changed")):
        test_command, test_cwd = pdata.get("test_command"), pdata.get("test_cwd")

    # Write-mode work MUST actually change files -- otherwise it's a silent no-op
    # that would fake acceptance (zero Claude tokens, zero work done). Advisory
    # work legitimately produces no writes (Claude applies the draft later).
    vr = verify(report, repo_root, test_command=test_command, test_cwd=test_cwd,
                require_changes=(decision.mode == "write"))
    result["verify"] = vr.as_dict()

    if vr.ok:
        result["action"] = "offloaded"
        result["report"] = report
        metrics.record(provider=decision.provider, action="offloaded",
                       owner=agent["name"], risk=decision.risk, eligible=True)
    else:
        rolled = worker.rollback() if hasattr(worker, "rollback") else []
        dirty = getattr(worker, "rollback_failures", [])
        result["action"] = "escalated_after_verify_fail"
        result["rolled_back"] = rolled
        if dirty:
            result["dirty_unreverted"] = dirty   # could not be reverted -- needs manual attention
        result["report"] = report
        metrics.record(provider=decision.provider, action="escalated_after_verify_fail",
                       owner=agent["name"], risk=decision.risk, eligible=True,
                       note=",".join(vr.failed))
    return result


def main() -> None:
    p = argparse.ArgumentParser(description="Offload one task to the free bench (verified).")
    p.add_argument("objective")
    p.add_argument("--repo-root", required=True)
    p.add_argument("--paths", nargs="*", default=[])
    p.add_argument("--live", action="store_true", help="actually run + verify (default: plan only)")
    p.add_argument("--run-tests", action="store_true", help="force the project test suite in the gate")
    p.add_argument("--project", help="project name -- REQUIRED for live writes (loads the safety policy)")
    a = p.parse_args()
    print(json.dumps(offload(a.objective, a.repo_root, a.paths, a.live,
                             run_tests=a.run_tests, project=a.project), indent=2, default=str))


if __name__ == "__main__":
    main()
