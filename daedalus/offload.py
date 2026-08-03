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
import subprocess
from pathlib import Path
from typing import Any

from . import metrics
from .kairos.scheduler import FREE_LANES
from .provider_router import route_and_select
from .verifier import (DEFAULT_TEST_TIMEOUT_S, VerifyResult,
                       prose_before_images, verify)

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
                  ".daedalus_worktrees",
                  # MEASURED 2026-07-30: this checkout contains
                  # ``.captures/cdp-edge-*/Default/Login Data`` and
                  # ``.../Network/Cookies`` -- a browser profile captured by the
                  # CDP tooling. It is gitignored, so the git-based listing below
                  # already excludes it; this entry exists for the DEGRADED
                  # fallback path, which is the one that walked it.
                  ".captures"}
_SNAPSHOT_MAX = 400_000  # per-file byte cap: skip large/binary blobs


def _tracked_rels(repo_root: str) -> list[str] | None:
    """Repo-relative paths git considers part of the tree, or None if it cannot say.

    ``--cached`` (tracked) plus ``--others --exclude-standard`` (untracked but
    NOT ignored). That second half is why a file the model creates still shows
    up, and the ``--exclude-standard`` is the entire point: it is git's answer to
    "is this part of the project", and it is the answer .gitignore was written to
    give.
    """
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=repo_root, capture_output=True, text=True, timeout=60, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return [r for r in out.stdout.split("\0") if r]


def _repo_snapshot(repo_root: str) -> dict[str, str]:
    """Content-hash every smallish text file IN THE TREE, path-agnostic.

    The write-mode gate diffs a before/after snapshot to find what ACTUALLY
    changed on disk -- so a genuine write is detected even when the caller passed
    no --paths, or the worker wrote a file it wasn't explicitly told to (the local
    write tool isn't restricted to the hint list).

    "In the tree" means ``git ls-files``, NOT ``rglob``. MEASURED 2026-07-30, and
    the reason this changed: an ``rglob`` from the repo root with a hand-written
    skip set does not know what .gitignore says, and this checkout has a
    gitignored ``.captures/`` holding captured Edge profile data -- including
    ``Login Data`` and ``Network/Cookies``. Two consequences, both bad:

    * the gate READ credential stores off disk in order to hash them;
    * ``result["wrote"]``, which is labelled GROUND TRUTH and is what arms the
      test gate, could name files no agent ever touched -- a browser writing its
      own cookie jar mid-run is indistinguishable here from a model editing code.

    ``tools/mutation_score.py`` already excluded ``.captures``. That knowledge
    simply never reached this function, which is the defect class this repo keeps
    finding in itself: built, correct, and not connected to the consumer.

    TRADE-OFF, stated rather than discovered later: a write into an IGNORED path
    is now invisible to this snapshot. That is deliberate -- an ignored path is by
    definition not the project -- and it is not the control that stops such a
    write. ``sensitivity.path_write_blocked`` and the lane guards are, and they
    run whether or not this function can see the file.

    Degrades, and says so: if git cannot answer (not a repo, no git binary), this
    falls back to the old walk with the skip set, which now excludes
    ``.captures`` explicitly.
    """
    root = Path(repo_root)
    snap: dict[str, str] = {}
    if not root.is_dir():
        return snap

    tracked = _tracked_rels(repo_root)
    if tracked is not None:
        for rel in tracked:
            p = root / rel
            try:
                if not p.is_file() or p.stat().st_size > _SNAPSHOT_MAX:
                    continue
                snap[Path(rel).as_posix()] = hashlib.sha256(p.read_bytes()).hexdigest()
            except OSError:
                continue
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


_AUTO_MINT_ENV = "DAEDALUS_AUTO_MINT"
_AUTO_MINT_TRUE = {"1", "true", "yes", "on"}


def _auto_mint_enabled() -> bool:
    """Whether a landed write should be turned into an eval task automatically.

    Default OFF. Minting is not free: ``mint_task_from_landed_edit`` shells out
    to git (``rev-parse`` + one ``show`` per changed file, 30s timeout each) and
    builds/loads the structcore index for the whole repo, then rewrites the mint
    store on disk. That is fine for an operator-triggered flywheel run and wrong
    to impose on every write offload -- so the seam ships dark and is turned on
    explicitly with ``DAEDALUS_AUTO_MINT=1``. Anything else (unset, empty, "0")
    reads as off, and the run still reports WHY it did not mint.
    """
    return os.environ.get(_AUTO_MINT_ENV, "").strip().lower() in _AUTO_MINT_TRUE


def _auto_mint(result: dict, repo_root: str) -> dict:
    """Mint one quarantined eval task from a LANDED write, fail-soft and loud.

    This is the flywheel seam: a write that actually changed disk and passed the
    gate becomes a labelled eval task, so the next measurement reflects the edit
    that just landed. Returns the block stamped on ``result["auto_mint"]`` -- it
    is written for EVERY write-mode run, minted or not, so a seam that declined
    to fire is observable in the result an operator reads rather than invisible.

    Fires only on a genuinely landed edit: ``action == "offloaded"`` (the verify
    gate passed, nothing was rolled back) AND a non-empty ``wrote`` (the
    before/after disk-hash diff, never the model's self-reported files_changed).
    An escalated, rolled-back, advisory or dry run never reaches the minter.

    A minting failure must never fail or roll back the offload -- the write has
    already landed and been verified, and losing it over a bookkeeping error
    would be strictly worse than not minting. So every failure below is caught
    and reported as ``status == "error"``; the offload result stays successful.
    """
    if not _auto_mint_enabled():
        return {"status": "disabled",
                "reason": f"{_AUTO_MINT_ENV} is not set (default off)"}
    if result.get("action") != "offloaded":
        return {"status": "skipped",
                "reason": f"run did not land (action={result.get('action')!r})"}
    if not result.get("wrote"):
        return {"status": "skipped", "reason": "no verified on-disk change"}
    try:
        from .eval.mint import add_minted_task, mint_task_from_landed_edit

        task = mint_task_from_landed_edit(result, repo_root)
        if not task:
            return {"status": "skipped",
                    "reason": "minter found no independent label in the landed edit"}
        # QUARANTINE ONLY. mint.py stamps this itself; the write path re-checks
        # it because minting at write time is the one caller that could quietly
        # inject a self-graded label into the corpus a promotion decision reads.
        # An unexpected tier is refused, not downgraded -- if the minter's
        # contract changed, a human decides what it means.
        if task.get("tier") != "quarantine":
            return {"status": "error",
                    "reason": f"refusing to persist minted task with tier "
                              f"{task.get('tier')!r} (expected 'quarantine')"}
        store = add_minted_task(task)
        return {"status": "minted", "task_id": task["id"], "tier": task["tier"],
                "must_include": len(task.get("must_include") or []),
                "store": store}
    except Exception as exc:    # noqa: BLE001 -- minting NEVER fails a landed write
        return {"status": "error", "reason": f"{type(exc).__name__}: {exc}"}


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


def _resolved_ollama_lane() -> tuple[str, str]:
    """``(lane, host)`` for the Ollama endpoint that will ACTUALLY be called.

    The lane is a fact about where bytes go, not about which provider name was
    selected. See :func:`daedalus.sensitivity.lane_for_host` for the breach this
    closes: ``OLLAMA_HOST`` is an environment variable, so "provider == ollama"
    never implied "local", and treating it as though it did turned a no-egress
    lane into a network one without changing a line of code.
    """
    from .providers.ollama import DEFAULT_HOST
    from .sensitivity import lane_for_host

    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
    return lane_for_host(host), host


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
    lane, resolved_host = _resolved_ollama_lane()
    meta: dict = {"injected": False, "budget_tokens": budget, "targets": [],
                  "lane": lane, "resolved_host": resolved_host}
    texts: dict[str, str] = {}
    if lane != "trusted":
        # The endpoint is NOT this machine, so this is an egress lane wearing
        # the name "ollama". Refused outright rather than downgraded: the
        # untrusted lane's default-deny would still ship whatever survives the
        # allow-list to a host the operator pointed an env var at, and this wire
        # exists specifically because the destination was believed to be local.
        # A human decides what a remote bench may read.
        meta["reason"] = (
            f"refused: OLLAMA_HOST resolves to {resolved_host!r}, which is not "
            f"this machine, so the distilled-context wire would be a network "
            f"egress lane rather than the local one it was built for")
        return texts, meta
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
                res = semantic_slice(repo_root, rel, idx=idx, lane=lane,
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


def _offload_impl(
    objective: str,
    repo_root: str,
    paths: list[str] | None = None,
    live: bool = False,
    availability: dict | None = None,
    run_tests: bool = False,
    project: str | None = None,
    isolate_paths: bool = False,
    # WINDOWED REWRITE hint: ``{rel_path: [window, ...]}``, where a window is a
    # line number, ``{"line": L, "radius": R}`` or ``{"start": S, "end": E}``.
    # A caller that already MEASURED which lines are wrong (the docref scan
    # does) can ask the local model to correct those lines instead of
    # reprinting a 2500-line document it will only truncate. Purely additive:
    # no hint means the existing full-file rewrite, unchanged. Consumed only by
    # the local (ollama) write lane -- external lanes never see it, so it opens
    # no new egress path.
    rewrite_windows: dict[str, Any] | None = None,
    # Explicit assignment resolved by the PRIMARY scheduler before an isolated
    # worktree is created. Dirty repo-local policy is intentionally absent from
    # a HEAD-based worktree, so relying on the worktree to rediscover this can
    # silently switch models mid-attempt.
    model: str | None = None,
    _attempt_workspace: dict[str, str] | None = None,
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
    # Same argument for stage 1: WHICH role ran this task, and whether an
    # embedding or a keyword guess picked it, is invisible from `owner` alone.
    # Carries the lane-guard verdict too, so an overruled latent re-route is
    # visible here rather than only in the logs of the process that made it.
    if decision.latent_route is not None:
        result["latent_route"] = decision.latent_route

    def _escalate(note: str, provider: str = "claude_cli") -> dict:
        result["action"] = "escalate_to_claude" if eligible else "senior"
        result["note"] = note
        # A dry call must not record a routing metric: doing so creates a
        # directory and appends a file before any Effect Lease exists.  This
        # only removes that specific hidden write.  The legacy router may still
        # consult StructCore caches/processes, so `_offload_impl(live=False)` is
        # NOT yet a generally effect-free planning boundary.
        if live:
            metrics.record(provider=provider, action=result["action"], owner=agent["name"],
                           risk=decision.risk, eligible=eligible, note=note)
        return result

    if decision.provider not in FREE_LANES:
        return _escalate(decision.reason)

    if not live:
        result["action"] = "would_offload"
        return result

    # A live write may only run inside the isolated TaskAttempt worktree that
    # produced this private workspace grant. Direct callers can still plan or
    # run advisory work, but they cannot mutate the primary checkout.
    if decision.mode == "write":
        granted = (_attempt_workspace or {}).get("worktree")
        try:
            same_workspace = (
                granted is not None
                and Path(granted).resolve() == Path(repo_root).resolve()
            )
        except OSError:
            same_workspace = False
        if not same_workspace:
            result["action"] = "isolated_attempt_required"
            result["note"] = (
                "refusing live write outside TaskAttempt; use "
                "daedalus.spine.attempt.offload_runner() so the primary "
                "checkout remains read-only"
            )
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
        preferred_model = model or model_assignments.get(agent["name"])
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
        # Only a WRITE run can splice anything; handing the hint to an advisory
        # or agentic run would be dead weight on the prompt budget.
        if rewrite_windows and rewrite_bound:
            run_kwargs["rewrite_windows"] = {
                str(k).replace("\\", "/"): v for k, v in rewrite_windows.items()}
    elif decision.provider == "codex_cli":
        # Same reduced-rights grant as ollama: advisory runs in codex's
        # read-only sandbox and structurally cannot write.
        run_kwargs["writable"] = (decision.mode == "write")
    elif decision.provider == "deepseek":
        # External writes require BOTH the router's explicit per-project
        # opt-in and this per-call grant. DeepSeekProvider defaults writable
        # to False, so omitting the seam turns a legitimate write route into
        # an unexplained advisory no-op.
        run_kwargs["writable"] = (decision.mode == "write")

    # FAIL-CLOSED writable grant: the verify-fail path below undoes a bad write
    # via worker.rollback(), so a provider without a callable rollback() must
    # never hold write rights -- a failed verify would leave the primary
    # checkout dirty while the result reported rolled_back=[] with no flag
    # Providers with an explicit write mode implement rollback; any future
    # provider that does not is automatically downgraded here.
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
    used_model = run_kwargs.get("model") or getattr(worker, "model", None)
    if used_model:
        result["model"] = str(used_model)
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
    #
    # ARMED BY DISK TRUTH, not by the self-report. This used to key off
    # ``report["files_changed"]``, which is the model's own claim -- the exact
    # field the did_work gate above refuses to trust. That let a worker DODGE
    # the test gate entirely: write files to disk, report ``files_changed: []``,
    # and the suite never ran while did_work still passed on the disk diff. In
    # write mode ``disk_changed`` is always the before/after content-hash diff,
    # so use it; advisory runs (``disk_changed is None``) keep the old
    # self-report fallback, since they legitimately write nothing.
    test_command = test_cwd = None
    test_timeout_s = DEFAULT_TEST_TIMEOUT_S
    changed_for_tests = disk_changed if disk_changed is not None else report.get("files_changed")
    if pdata and (run_tests or changed_for_tests):
        test_command, test_cwd = pdata.get("test_command"), pdata.get("test_cwd")
        # Per-project budget; absent -> the 120 s default, so repos that never
        # declare one are timed exactly as they were before this key existed.
        if pdata.get("test_timeout_s") is not None:
            test_timeout_s = pdata["test_timeout_s"]

    # Write-mode work MUST actually change files -- otherwise it's a silent no-op
    # that would fake acceptance (zero Claude tokens, zero work done). Advisory
    # work legitimately produces no writes (Claude applies the draft later).
    # The prose check needs the text from the instant BEFORE the write, and the
    # writer is the only thing that has it -- ``git show HEAD:`` is a lie the
    # moment the tree was already dirty. The provider keeps exact original bytes
    # for rollback; this hands the same bytes to the verifier as before-images.
    # A prose file with no before-image is refused, not waved through.
    vr = verify(report, repo_root, test_command=test_command, test_cwd=test_cwd,
                timeout_s=test_timeout_s,
                require_changes=(decision.mode == "write"), disk_changed=disk_changed,
                prose_before=prose_before_images(
                    getattr(worker, "_backups", None), repo_root))

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
        # Label the recorded reason with the tests check's machine-readable
        # status. Without this the metrics DB stores a bare "tests" for BOTH a
        # genuinely red suite and a suite we killed for overrunning its budget,
        # so the lane statistics that decide future routing would blame the
        # local lane for a timeout we configured. Only "tests" is annotated;
        # every other check name is recorded exactly as before.
        note = ",".join(
            f"tests:{c.get('status')}" if c["name"] == "tests" and c.get("status")
            else c["name"]
            for c in vr.checks if not c["ok"]
        )
        metrics.record(provider=decision.provider, action="escalated_after_verify_fail",
                       owner=agent["name"], risk=decision.risk, eligible=True,
                       note=note)

    # THE FLYWHEEL SEAM (closed here): a landed write mints its own eval task.
    # Stamped on every write-mode run -- including the ones that did NOT mint --
    # so the seam is observable instead of silent. Advisory/dry runs get no
    # field at all, keeping their result dict byte-identical to before.
    if decision.mode == "write":
        result["auto_mint"] = _auto_mint(result, repo_root)
    return result



def offload(
    objective: str,
    repo_root: str,
    paths: list[str] | None = None,
    live: bool = False,
    availability: dict | None = None,
    run_tests: bool = False,
    project: str | None = None,
    isolate_paths: bool = False,
    rewrite_windows: dict[str, Any] | None = None,
    model: str | None = None,
    *,
    effect_authorization: "LeasedEffectAuthorization | None" = None,
    effect_execution: "EffectExecutionRequest | None" = None,
    _attempt_workspace: dict[str, str] | None = None,
) -> dict:
    """Run the legacy dry route or execute behind one persisted Effect Lease.

    ``live=False`` does not invoke a provider and does not append routing
    metrics, but the legacy routing/index path is not yet guaranteed globally
    effect-free.  Every live call, including advisory/provider work, must
    present an already-issued and persisted authorization for the canonical
    ``python.offload`` entrypoint.  The entrypoint consumes the capability; it
    never discovers issuer secrets or mints its own lease from ambient
    configuration.
    """

    if not live:
        return _offload_impl(
            objective, repo_root, paths, live, availability, run_tests, project,
            isolate_paths, rewrite_windows, model, _attempt_workspace
        )

    if effect_authorization is None or effect_execution is None:
        return {
            "objective": objective,
            "action": "effect_lease_required",
            "note": (
                "refusing live offload without a persisted Effect Lease and "
                "exact execution request for python.offload"
            ),
            "wrote": [],
        }

    if effect_authorization.lease.entrypoint_id != "python.offload":
        return {
            "objective": objective,
            "action": "effect_lease_refused",
            "note": "authorization is not bound to python.offload",
            "wrote": [],
        }

    from .spine.effect_boundary import REGISTRY_BY_ID
    required_effects = {
        effect.value for effect in REGISTRY_BY_ID["python.offload"].effects
    }
    if set(effect_execution.requested_effects) != required_effects:
        return {
            "objective": objective,
            "action": "effect_lease_refused",
            "note": (
                "python.offload execution must bind the complete declared "
                "effect set: " + ", ".join(sorted(required_effects))
            ),
            "wrote": [],
        }

    start = effect_authorization.begin_effect(effect_execution)
    if not start.execute:
        return {
            "objective": objective,
            "action": "effect_replay",
            "note": "idempotent replay refused a second external effect",
            "wrote": [],
            "effect_start_receipt": start.receipt.to_dict(),
        }

    from .kernel.effects import (
        EffectLeaseStateError,
        EffectReconciliationRequired,
        freeze_effect_terminal_receipt,
    )
    from .spine.envelope import canonical_sha

    def finish_or_require_reconciliation(
        *,
        outcome: str,
        phase: str,
        output_digests: tuple[str, ...] = (),
        detail_sha256: str | None = None,
    ):
        """Publish one terminal receipt or surface an inert STARTED row.

        Once ``begin_effect`` returns ``execute=True``, an external effect may
        already have happened.  A terminal-write failure must therefore never
        look like an ordinary retryable provider failure: the persisted STARTED
        identity is retained and replay remains non-effectful until an operator
        reconciles it.
        """

        pending_terminal = freeze_effect_terminal_receipt(
            start.receipt,
            outcome=outcome,
            output_digests=output_digests,
            detail_sha256=detail_sha256,
        )
        completion_capability = start.completion_capability
        if completion_capability is None:
            raise EffectLeaseStateError(
                "live start returned without completion capability"
            )
        terminal_authorization = completion_capability.authorize(
            pending_terminal
        )
        try:
            return effect_authorization.finish_terminal(
                pending_terminal,
                authorization=terminal_authorization,
            )
        except Exception as exc:
            persistence_error_sha256 = hashlib.sha256(
                f"{type(exc).__name__}: {exc}".encode("utf-8", "replace")
            ).hexdigest()
            raise EffectReconciliationRequired(
                pending_terminal_receipt=pending_terminal,
                execution_request_sha256=(
                    start.receipt.execution_request_sha256
                ),
                phase=phase,
                persistence_error_sha256=persistence_error_sha256,
            ) from exc

    try:
        result = _offload_impl(
            objective, repo_root, paths, live, availability, run_tests, project,
            isolate_paths, rewrite_windows, model, _attempt_workspace
        )
    except (KeyboardInterrupt, SystemExit) as exc:
        detail_sha256 = hashlib.sha256(
            f"{type(exc).__name__}: {exc}".encode("utf-8", "replace")
        ).hexdigest()
        finish_or_require_reconciliation(
            outcome="CANCELLED",
            phase="cancelled-terminal-write",
            detail_sha256=detail_sha256,
        )
        raise
    except Exception as exc:
        detail_sha256 = hashlib.sha256(
            f"{type(exc).__name__}: {exc}".encode("utf-8", "replace")
        ).hexdigest()
        finish_or_require_reconciliation(
            outcome="FAILED",
            phase="failed-terminal-write",
            detail_sha256=detail_sha256,
        )
        raise

    try:
        output_digest = canonical_sha(result)
    except Exception as exc:
        detail_sha256 = hashlib.sha256(
            (
                "output-canonicalization: "
                f"{type(exc).__name__}: {exc}"
            ).encode("utf-8", "replace")
        ).hexdigest()
        finish_or_require_reconciliation(
            outcome="FAILED",
            phase="output-canonicalization-terminal-write",
            detail_sha256=detail_sha256,
        )
        raise

    terminal = finish_or_require_reconciliation(
        outcome="COMPLETED",
        phase="completed-terminal-write",
        output_digests=(output_digest,),
    )
    result["effect_start_receipt"] = start.receipt.to_dict()
    result["effect_terminal_receipt"] = terminal.to_dict()
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
