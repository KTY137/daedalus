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
import os
from pathlib import Path

from . import metrics
from .kairos.scheduler import FREE_LANES
from .provider_router import route_and_select
from .verifier import VerifyResult, verify

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
                  ".mypy_cache", ".pytest_cache", ".ruff_cache",
                  ".daedalus_worktrees"}
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


_SLICE_BUDGET_ENV = "OFFLOAD_SLICE_TOKENS"


def _slice_budget() -> int:
    """Token budget for distilled slice context on the LOCAL lane. Default 0 =
    OFF: the wire ships dark until the live A/B (the landing gate) shows the
    local model does better work with the neighborhood in view. Set
    OFFLOAD_SLICE_TOKENS to a positive int to enable; anything unparsable or
    negative reads as off."""
    try:
        return max(0, int(os.environ.get(_SLICE_BUDGET_ENV, "0")))
    except ValueError:
        return 0


def _slice_context(repo_root: str, targets: list[str], pol,
                   include_focus: bool, budget: int) -> tuple[dict[str, str], dict]:
    """Gated distilled context for the LOCAL (trusted) lane -- the slice→offload
    wire (Horizon Phase 2, static import graph only).

    Returns ``(slice_texts, meta)``: rel -> slice_text for every declared
    target the slicer could serve, plus a provenance block for the result dict.
    A slice that failed to build, was refused by the egress gate, or came back
    empty is REPORTED in ``meta``, never silent -- a withheld or degraded
    context must be visible at the seam the operator reads.

    Fail-OPEN on build (a broken index/slicer never blocks the task; the worker
    just runs context-free, exactly as before this wire existed). Fail-CLOSED
    on content: the gates inside ``semantic_slice`` do the withholding -- the
    secret floor runs on every lane, and a focus-refused file injects NOTHING
    (its breadcrumb is a refusal notice, not context).

    ``lane="trusted"`` is only correct because this is called for the local
    bench alone (ollama: no bytes leave the machine, and its agentic loop may
    already read any repo file). NEVER route this output to an external
    provider -- that invariant is enforced at the call site, which builds the
    slice exclusively inside the ollama branch.
    """
    meta: dict = {"injected": False, "budget_tokens": budget, "targets": []}
    texts: dict[str, str] = {}
    if budget <= 0:
        meta["reason"] = f"disabled ({_SLICE_BUDGET_ENV}=0)"
        return texts, meta
    if not targets:
        meta["reason"] = "no declared paths to focus on"
        return texts, meta
    try:
        from .structcore.index import cached_index
        from .structcore.slice import semantic_slice

        # Warm for write tasks: the routing reachability precheck already built
        # this index; the cache makes the wire near-free at dispatch time.
        idx = cached_index(repo_root)
        per_target = max(256, budget // len(targets))
        for rel in targets:
            entry: dict = {"target": rel}
            try:
                res = semantic_slice(repo_root, rel, idx=idx, lane="trusted",
                                     policy=pol, max_tokens=per_target,
                                     include_focus=include_focus)
            except ValueError:
                # Not in the index: a create target or an unindexed tree --
                # nothing to distill; the worker proceeds exactly as before.
                entry.update(status="skipped", reason="target not in index")
                meta["targets"].append(entry)
                continue
            focus_refused = any(w.get("role") == "focus"
                                for w in res.get("withheld") or ())
            text = (res.get("slice_text") or "").strip()
            if focus_refused or not text:
                rule = next((w.get("rule") for w in res.get("withheld") or ()
                             if w.get("role") == "focus"), None)
                entry.update(status="skipped",
                             reason=(f"focus withheld by egress gate ({rule})"
                                     if focus_refused else "empty slice"))
                meta["targets"].append(entry)
                continue
            texts[rel] = text
            entry.update(
                status="injected",
                slice_tokens=int(res.get("slice_tokens", 0)),
                included=int(res.get("n_included", 0)),
                withheld_count=int(res.get("withheld_count", 0)),
                trimmed_count=int(res.get("trimmed_count", 0)),
                shell_boundary_stops=int(res.get("shell_boundary_stops", 0)),
            )
            meta["targets"].append(entry)
    except Exception as exc:  # noqa: BLE001 -- fail-open: context is optional, the task is not
        texts.clear()
        return texts, {"injected": False, "budget_tokens": budget, "targets": [],
                       "reason": f"slice build failed: {exc}"}
    meta["injected"] = bool(texts)
    if not texts and "reason" not in meta:
        meta["reason"] = "no target produced an injectable slice"
    return texts, meta


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
    # Surface the blast-radius verdict at the seam the operator actually reads.
    # The escalating case already reaches them via decision.reason -> note, but
    # the NON-escalating diagnostics -- the dominance stand-down notice, the
    # "index contains no modules" degenerate-index error, the unresolved-path
    # list -- live only on decision.reachability and were dropped here, so a run
    # where the graph fence stood down looked identical to a clean low-risk
    # offload. A degraded/withheld safety measurement must never be silent.
    # Omitted entirely when no repo_root/idx was supplied, so a caller that never
    # asked for the check gets a byte-identical result dict (matches as_dict()).
    if decision.reachability is not None:
        result["reachability"] = decision.reachability

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
    slice_meta = None
    if decision.provider == "ollama":
        run_kwargs["writable"] = (decision.mode == "write")   # advisory truly can't write
        model_assignments = ((pdata or {}).get("team") or {}).get("model_assignments") or {}
        preferred_model = model_assignments.get(agent["name"])
        if preferred_model:
            run_kwargs["model"] = str(preferred_model)
        # THE WIRE (Horizon Phase 2, static-only): hand the LOCAL bench a gated
        # distilled slice of the declared targets. Built exclusively in this
        # branch -- ollama is local and trusted with IP, so lane="trusted"
        # (secret floor ON, default-deny OFF). codex/deepseek NEVER get a
        # slice: external lanes keep their existing egress posture (the
        # bootstrap's Cerberus invariant, kept here on purpose).
        from .providers.ollama import MAX_REWRITE_FILES
        slice_targets = list(dict.fromkeys(
            p.replace("\\", "/") for p in (paths or [])))[:MAX_REWRITE_FILES]
        rewrite_bound = (decision.mode == "write" and bool(paths)
                        and len(paths) <= MAX_REWRITE_FILES)
        # The rewrite prompt already carries the full file body, so its slice
        # omits the FOCUS body (neighborhood only) rather than paying for a
        # duplicate. Agentic/advisory workers haven't read the file yet -- they
        # get the full slice. This mirrors the provider's own dispatch rule.
        slice_texts, slice_meta = _slice_context(
            repo_root, slice_targets, pol,
            include_focus=not rewrite_bound, budget=_slice_budget())
        if slice_texts:
            run_kwargs["slice_texts"] = slice_texts
    elif decision.provider == "codex_cli":
        # Same reduced-rights grant as ollama: advisory runs in codex's
        # read-only sandbox and structurally cannot write.
        run_kwargs["writable"] = (decision.mode == "write")

    # FAIL-CLOSED writable grant: the verify-fail path below undoes a bad write
    # via worker.rollback(), so a provider without a callable rollback() must
    # never hold write rights -- a failed verify would leave the primary
    # checkout dirty while the result reported rolled_back=[] with no flag
    # (today that's codex_cli; only the ollama provider implements rollback).
    # The downgrade is EXPLICIT, mirroring core._codex_report's
    # mutation_blocked stamp: the notice + needs_stronger_lane ride the result,
    # and the write-mode verify gate (require_changes) then fails the run into
    # escalated_after_verify_fail -- never a silent advisory acceptance.
    if run_kwargs.get("writable") and not callable(getattr(worker, "rollback", None)):
        run_kwargs["writable"] = False
        result["mutation_blocked"] = (
            f"routed {decision.provider} write is advisory-only until Forge: "
            "provider has no rollback capability")
        result["needs_stronger_lane"] = True

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

    # Slice-context provenance rides the result even on escalation: what the
    # worker actually saw (or why it saw nothing) must never be reconstructable
    # only from logs. A file whose context was dropped to fit the local window
    # is surfaced from the worker's report here.
    if slice_meta is not None:
        dropped = (report.get("handoff") or {}).get("slice_context_dropped")
        if dropped:
            slice_meta["dropped_for_window"] = list(dropped)
        result["slice_context"] = slice_meta

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

    # POST-WRITE BLAST-RADIUS FENCE. The routing-time reachability check in
    # select_provider only ever saw the DECLARED --paths. A writable agentic run
    # can write a file it was never told about (empty --paths -> the worker is
    # told to "explore from the repo root", and the local write tool isn't
    # restricted to the hint list), and that leaf may transitively feed a fenced
    # module -- the exact leak the routing fence closes for declared paths but
    # NOT for undeclared writes. So re-run the fence over what ACTUALLY landed on
    # disk (the verified before/after diff, not the model's self-report) and, if
    # any changed file reaches a fenced module, fail the gate -- the write is
    # rolled back and escalated to Claude below, never silently accepted.
    # Only meaningful with a loaded policy (writes without one are already
    # refused above); fail-closed like the routing precheck (an unbuildable index
    # escalates rather than passes).
    if decision.mode == "write" and pol is not None and disk_changed:
        from .provider_router import _reachability_precheck
        from .structcore.index import cached_index
        try:
            # A FRESH index is load-bearing here: the routing-time index predates
            # these writes, so a just-CREATED leaf would read as "absent from the
            # graph" and the fail-closed precheck would (wrongly) escalate every
            # legitimate new-file write. Rebuilding over the post-write tree gives
            # a TRUE reachability verdict for what actually landed.
            fence = _reachability_precheck(
                disk_changed, pol, repo_root, cached_index(repo_root, refresh=True))
            escalate = bool(fence and fence.get("escalate"))
            detail = (fence or {}).get("reason") or "edit reaches a fenced module"
        except Exception as exc:                    # noqa: BLE001 - unknown == unsafe
            escalate, detail = True, f"post-write blast-radius re-check failed ({exc})"
        if escalate:
            vr = VerifyResult(ok=False, checks=[*vr.checks, {
                "name": "blast_radius", "ok": False, "detail": detail}])
    result["verify"] = vr.as_dict()

    if vr.ok:
        result["action"] = "offloaded"
        result["report"] = report
        # Advisory proposals used to evaporate with the result dict. Persist
        # them so `daedalus drafts` can list/review/apply later (Era 3 #1).
        if decision.mode == "advisory":
            try:
                from .kairos.drafts import save_draft
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
