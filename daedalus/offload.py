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
import hashlib
import json
from pathlib import Path

from . import metrics
from .ikarus import FREE_LANES
from .provider_router import route_and_select
from .verifier import verify

_ALL = {"claude_cli": True, "ollama": True, "deepseek": True, "codex_cli": True}


def _content_hash(repo_root: str, rel: str) -> str | None:
    """SHA-256 of a target file's bytes on disk, or None if it doesn't exist.

    Used to prove a REAL edit happened. A missing file hashes to None, so a
    create (None -> hash) and an in-place edit (hashA -> hashB) both register as
    a change, while a no-op (model narrated but never wrote) stays identical.
    """
    try:
        return hashlib.sha256((Path(repo_root) / rel).read_bytes()).hexdigest()
    except OSError:
        return None


_SNAPSHOT_SKIP = {".git", "node_modules", "__pycache__", ".venv", "venv",
                  ".mypy_cache", ".pytest_cache", ".ruff_cache"}
_SNAPSHOT_MAX = 400_000  # per-file byte cap: skip large/binary blobs


def _repo_snapshot(repo_root: str) -> dict[str, str]:
    """Content-hash every smallish text file under the repo, path-agnostic.

    The write-mode gate diffs a before/after snapshot to find what ACTUALLY
    changed on disk -- so a genuine write is detected even when the caller
    passed no --paths, or the worker wrote a file it wasn't explicitly told to
    (the local write tool isn't restricted to the hint list). Junk dirs and
    oversized blobs are skipped so this stays cheap.
    """
    root = Path(repo_root)
    snap: dict[str, str] = {}
    if not root.is_dir():
        return snap
    for p in root.rglob("*"):
        try:
            if not p.is_file() or p.stat().st_size > _SNAPSHOT_MAX:
                continue
            rel = p.relative_to(root)
            if any(part in _SNAPSHOT_SKIP for part in rel.parts):
                continue
            snap[rel.as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
        except OSError:
            continue
    return snap


def _scoped_snapshot(repo_root: str, rels: list[str]) -> dict[str, str]:
    """Content-hash ONLY the given repo-relative paths (present ones). Used for
    per-task change attribution when tasks run concurrently on one repo -- a
    whole-repo diff would cross-attribute another task's writes. Safe because
    the scoped-write lane writes exactly its declared paths."""
    snap: dict[str, str] = {}
    root = Path(repo_root)
    for rel in rels:
        h = _content_hash(repo_root, rel)
        if h is not None:
            snap[Path(rel).as_posix()] = h
    return snap


def offload(
    objective: str,
    repo_root: str,
    paths: list[str] | None = None,
    live: bool = False,
    availability: dict | None = None,
    run_tests: bool = False,
    project: str | None = None,
    isolate_paths: bool = False,
) -> dict:
    if availability is None:
        from .doctor import check
        ready = check()
        availability = {
            "claude_cli": ready["claude_cli"],
            "ollama": ready["can_offload_local"],
            "deepseek": ready["deepseek_key"],
            "codex_cli": ready.get("codex_cli", False),
        }

    # The policy is what makes the guards real. Resolve it from the registry or
    # the target repo's own .agentenv/agentenv.json. Only an explicit 'policy'
    # block enables writes; otherwise pol stays None and we fail closed.
    from .config import resolve_project
    from .sensitivity import load_policy
    pdata = resolve_project(repo_root, project)
    pol = load_policy(pdata) if (pdata and pdata.get("policy")) else None
    active_agents = None
    if pdata:
        active = (pdata.get("team") or {}).get("active_agents")
        if isinstance(active, list):
            active_agents = [str(a) for a in active if str(a).strip()]

    # Intended lane (all up) vs actual lane (given availability) -- both policy-aware.
    # repo_root threads through so the target repo's own .agentenv agents route.
    _, intended = route_and_select(objective, paths or [], _ALL, pol, active_agents,
                                   repo_root=repo_root)
    agent, decision = route_and_select(objective, paths or [], availability, pol,
                                       active_agents, repo_root=repo_root)
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
        model_assignments = ((pdata or {}).get("team") or {}).get("model_assignments") or {}
        preferred_model = model_assignments.get(agent["name"])
        if preferred_model:
            run_kwargs["model"] = str(preferred_model)
    elif decision.provider == "codex_cli":
        # Same reduced-rights grant as ollama: advisory runs in codex's
        # read-only sandbox and structurally cannot write.
        run_kwargs["writable"] = (decision.mode == "write")

    # Snapshot the repo BEFORE the run so we can prove a real on-disk change
    # afterward -- the write-mode gate must NOT trust the model's self-reported
    # files_changed (a narrating model claims edits it never made). Path-agnostic
    # so a genuine write is caught even with no --paths.
    # isolate_paths (parallel dispatch): attribute changes by hashing ONLY this
    # task's declared paths, so a sibling task writing concurrently to the same
    # repo can't leak into this task's diff. Default stays the whole-repo snapshot
    # (catches sneaky writes outside --paths; correct for sequential runs).
    def _snap() -> dict[str, str]:
        return _scoped_snapshot(repo_root, paths or []) if isolate_paths else _repo_snapshot(repo_root)

    before_snap = _snap() if decision.mode == "write" else {}

    out = worker.run(**run_kwargs)
    report = out["report"]

    # Which files ACTUALLY changed on disk (create, edit, or delete) -- this,
    # not report["files_changed"], is what the write-mode gate trusts.
    disk_changed = None
    if decision.mode == "write":
        after_snap = _snap()
        disk_changed = sorted(rel for rel in (set(before_snap) | set(after_snap))
                              if before_snap.get(rel) != after_snap.get(rel))
    # GROUND TRUTH for callers: which files this task really changed on disk.
    # Advisory tasks legitimately write nothing (they produce a draft) -- []
    # here plus mode=="advisory" is a draft, NOT a no-op. Callers must render
    # "wrote" from THIS field, never from action=="offloaded"/verify.ok alone
    # (the op-test harness once printed 'wrote yes' for pure drafts that way).
    result["wrote"] = list(disk_changed or [])

    # For live writes, run the project test suite in the gate when we have it.
    test_command = test_cwd = None
    if pdata and (run_tests or report.get("files_changed")):
        test_command, test_cwd = pdata.get("test_command"), pdata.get("test_cwd")

    # Write-mode work MUST actually change files -- otherwise it's a silent no-op
    # that would fake acceptance (zero Claude tokens, zero work done). Advisory
    # work legitimately produces no writes (Claude applies the draft later).
    vr = verify(report, repo_root, test_command=test_command, test_cwd=test_cwd,
                require_changes=(decision.mode == "write"), disk_changed=disk_changed)
    result["verify"] = vr.as_dict()

    if vr.ok:
        result["action"] = "offloaded"
        result["report"] = report
        # Advisory proposals used to evaporate with the result dict. Persist
        # them so `daedalus drafts` can list/review/apply later (Era 3 #1).
        if decision.mode == "advisory":
            try:
                from .drafts import save_draft
                result["draft"] = save_draft(
                    objective, paths or [], agent["name"], decision.provider,
                    decision.persona, report, repo_root=repo_root).stem
            except OSError:
                result["draft"] = None   # persistence is best-effort, never fatal
        metrics.record(provider=decision.provider, action="offloaded",
                       owner=agent["name"], risk=decision.risk, eligible=True)
    else:
        rolled = worker.rollback() if hasattr(worker, "rollback") else []
        dirty = getattr(worker, "rollback_failures", [])
        result["action"] = "escalated_after_verify_fail"
        result["rolled_back"] = rolled
        # After rollback the disk is (mostly) restored -- only paths that could
        # NOT be reverted remain truly changed. Keep "wrote" ground-truthful.
        # (rollback_failures holds ABSOLUTE paths; normalize to repo-relative.)
        if rolled or dirty:
            root = Path(repo_root).resolve()
            still_dirty = []
            for ap in dirty:
                try:
                    still_dirty.append(Path(ap).resolve().relative_to(root).as_posix())
                except ValueError:
                    still_dirty.append(ap)
            result["wrote"] = still_dirty
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
