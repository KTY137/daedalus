"""Kairos concurrent-write dispatch -- gated candidates via the spine, never a
second isolation mechanism.

BACKGROUND. An earlier draft of this module hand-rolled worktree creation,
commit, and patch capture for each concurrent write task. That was wrong: it
duplicated ``daedalus.spine.attempt.TaskAttempt``, which already does exactly
that -- isolated worktree (``GitWorktreeManager``), a runner (``offload()``
via ``offload_runner``), hardened patch capture (``git diff --no-ext-diff
--no-textconv``, with ``--git-dir``/``--work-tree`` pinned to a pointer read
BEFORE the runner executes, so a candidate cannot redirect it by rewriting
``<worktree>/.git``), a gate, and cleanup -- and it is independently tested to
leave the primary checkout byte-identical
(``tests/test_spine_attempt.py::test_happy_path_artifact_and_primary_untouched``)
and to expose NO apply/promote/land path
(``tests/test_spine_attempt.py::test_module_exposes_no_apply_path``). This
module does not repeat any of that. It has two responsibilities:

PHASE 1 -- CONCURRENT GATING (``gate_candidates``). Turn each write
Assignment into a ``TaskSpec``, run it through ``TaskAttempt`` with
``offload()`` as the runner (offload's own verify+rollback cascade stays the
authority for per-task correctness -- see ``_relay_gate``), fanned out across
a thread pool, every attempt in its own worktree. Output: one
``GatedCandidate`` per assignment, each carrying an ``AttemptResult`` whose
``.artifact`` is a ``PatchArtifact`` (inert bytes) when the candidate is
clean. The primary checkout is untouched -- that is ``TaskAttempt``'s own
structural guarantee, not something re-implemented or re-verified here.
``run_write_wave`` additionally asks Phase 1 to persist those bytes in the
checkout-external Daedalus artifact archive.  That is load-bearing for a held
candidate: its attempt branch is reaped before this function returns, so an
in-memory-only patch could not honestly be described as waiting for review.

PHASE 2 -- PROMOTION (``promote_candidates``; opt-in, a separate call, NOT
wired into ``KairosScheduler.dispatch()``'s default path -- see
``daedalus/kairos/scheduler.py``). Landing N candidates is itself a
shared-mutable-state problem -- the same shape hazard concurrent writes
started from, moved from "N offload() calls" to "N candidate merges" -- so
promotion is:

  * guarded by ONE cross-process lock (``_PromotionLock``, the same
    msvcrt/fcntl pattern as ``daedalus.budget._BudgetLock`` and
    ``runs/council/room.py``'s ``_RoomLock``, independently written here
    because both of those are private to modules this file does not own),
  * applied into ONE dedicated "integration" worktree, one candidate at a
    time, NEVER into the primary checkout,
  * cumulatively RE-GATED after every apply (the project's configured test
    command, re-run against the integration state via
    ``daedalus.spine.attempt.command_gate`` -- not just a syntactic
    ``git apply --check``), and
  * for any candidate whose artifact was captured against a base the
    integration branch has since moved past -- true for EVERY candidate
    after the first, whenever 2+ writes were gated concurrently against the
    same starting commit, which is the normal case this module exists for --
    RE-ATTEMPTED (a fresh ``TaskAttempt``, same objective, ``base_revision``
    = the current integration HEAD) rather than force-applied stale.

This is a deliberate correction (cross-vendor review, Codex, 2026-07-29) to an
earlier draft that proposed ``git apply --check`` as the sole conflict
detector: a check that passes only proves the bytes still match: it does not
prove the SEMANTIC content is still correct once an earlier candidate has
landed ahead of it.

WHAT THIS MODULE DID NOT DECIDE, UNTIL 2026-07-29. ``daedalus.spine.attempt``
(and the ``daedalus improve`` CLI built on it) is deliberately apply-less:
"There is no --apply flag and there will not be one here. Promotion is a
human act." Auto-landing N concurrent writes is a DIFFERENT contract than
that one-attempt, human-reviewed shape -- and it is also different from what
``offload()`` does for a single sequential write outside a gated wave, which
still auto-lands into the primary checkout with no review step at all.
Reconciling those was a product decision, not an isolation-engineering one,
and the owner answered it: "eigentlich automatisch aber das soll
unteranderem einstellbar sein" (automatic by default, but configurable). See
PHASE 3 below (``run_write_wave``) for the wiring, and ``daedalus.config``'s
``write_wave_policy`` docs for the three-level contract. The answer composes
with, and never bypasses, this repo's proof-of-discrimination gate
(``daedalus.core.get_governance``) -- "automatic" governs whether a HUMAN
must click promote, never whether the PROOF that the gate can catch a bad
patch is still required.
"""

from __future__ import annotations

import hashlib
import os
import shlex
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, replace as _dc_replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping

from .worktree import GitWorktreeManager

#: Fallback timeout for a curated command gate that names none. Mirrors
#: ``daedalus.spine.attempt.DEFAULT_GATE_TIMEOUT_S`` without importing it at
#: module scope -- this module imports spine.attempt lazily inside functions
#: (see _spec_for/_attempt_assignment) and adding a top-level import would
#: change that deliberate import order.
_DEFAULT_GATE_TIMEOUT_S = 900.0

if TYPE_CHECKING:
    from daedalus.spine.attempt import AttemptResult, TaskSpec

    from .scheduler import Assignment


# --------------------------------------------------------------------------- #
# declared-path rebasing                                                      #
# --------------------------------------------------------------------------- #
def rebase_declared_path(raw: str, primary_root: Path) -> str:
    """Repo-relative form of one declared write path.

    ``Assignment.paths`` are collected from whatever the caller supplied to
    ``KairosScheduler`` -- ``kairos/decompose.py``'s own system prompt asks
    the local model for "repo-relative path", but other callers (the web API,
    an editor extension) hand through whatever the client sent, which can be
    an ABSOLUTE path into the PRIMARY checkout.

    That matters here because ``TaskSpec.target_paths`` is compared, verbatim,
    against ``PatchArtifact.changed_paths`` -- which are always repo-relative
    POSIX strings from ``git diff --name-only`` inside the WORKTREE (see
    ``daedalus.spine.attempt.TaskAttempt._capture_patch``/the "escaped
    target_paths" check in ``_run_with_ledger``). An absolute path never
    equals a relative one, so an un-rebased absolute path would make every
    correctly-scoped write look like it "escaped" its declared scope and get
    refused as ``GATES_FAILED`` -- a silent, wrong task failure, not a silent
    bypass, but still unacceptable for a P0 concurrency fix.

    An absolute path that resolves under ``primary_root`` is rebased to its
    repo-relative form. An absolute path that resolves OUTSIDE
    ``primary_root`` is returned unchanged -- out of scope for rebasing, and
    left for downstream guards (offload's own path confinement) to refuse
    exactly as they do today.
    """
    raw = str(raw)
    p = Path(raw)
    if not p.is_absolute():
        return raw
    try:
        rel = p.resolve().relative_to(primary_root.resolve())
    except ValueError:
        return raw
    return rel.as_posix()


def rebase_declared_paths(paths, primary_root: Path) -> tuple[str, ...]:
    return tuple(rebase_declared_path(p, primary_root) for p in (paths or []))


# --------------------------------------------------------------------------- #
# PHASE 1 -- concurrent gating                                                #
# --------------------------------------------------------------------------- #
@dataclass
class GatedCandidate:
    """One write Assignment's outcome from Phase 1.

    ``spec`` is retained (not just ``result``) because ``AttemptResult`` does
    not carry the originating ``TaskSpec`` -- and Phase 2's staleness retry
    needs to re-attempt the SAME instruction/target_paths against a NEW
    ``base_revision``, which requires the original spec, not just its result.
    """

    assignment: Any  # daedalus.kairos.scheduler.Assignment
    spec: Any         # daedalus.spine.attempt.TaskSpec
    result: Any        # daedalus.spine.attempt.AttemptResult


def _artifact_root_for(repo_root: Path) -> Path:
    """Durable, checkout-external storage for gated candidate patch bytes.

    A held candidate cannot live only in ``AttemptResult.artifact``:
    ``run_write_wave`` returns plain dictionaries and ``TaskAttempt`` reaps its
    candidate branch, so those bytes otherwise disappear as soon as the call
    returns.  Keep the archive beside the worktree/control state, namespaced by
    checkout identity, and let ``TaskAttempt._persist`` apply its primary-tree
    fence before it creates or writes anything.
    """
    local_appdata = os.environ.get("LOCALAPPDATA")
    base = Path(local_appdata) if local_appdata else Path(tempfile.gettempdir())
    digest = hashlib.sha256(
        str(Path(repo_root).resolve()).encode("utf-8")
    ).hexdigest()[:12]
    return base / "daedalus" / "artifacts" / digest / "patches"


def _relay_gate(box: dict):
    """A TaskAttempt gate that judges by offload()'s OWN verdict, not a
    second test run.

    A gate callable only ever receives a ``RunnerContext`` (worktree/branch/
    base/task/is_cancelled) -- never the runner's return value -- so there is
    no direct way to ask "did offload() call this clean". ``box`` is a
    mutable cell the paired runner (``_recording_runner``) writes its result
    into before returning; this closure reads it back.

    Why not TaskAttempt's own default (``pytest_gate(task.gate_paths)``, a
    bare ``python -m pytest``)? It assumes pytest, which is not every
    project's test runner -- ``offload()``'s own ``verify()`` already runs
    the PROJECT'S configured ``test_command``, whatever that is. Running it
    again here would be a SECOND, independent verify of the same change,
    which is the "raw provider call" the standing orders say must not
    happen: offload's verify+rollback cascade is meant to stay the one
    authority for per-task correctness.

    This still catches a real failure mode a bare "is the diff non-empty"
    check would miss: offload can finish with
    ``action == "escalated_after_verify_fail"`` while ``wrote`` is
    NON-EMPTY, because a write it could not fully roll back is reported in
    ``dirty_unreverted`` and kept in ``wrote`` so it stays visible. That
    leaves a non-empty artifact for a run offload itself considers FAILED,
    and only checking ``action == "offloaded"`` (not "artifact exists")
    refuses it.
    """

    def _gate(ctx):
        from daedalus.spine.attempt import GateResult

        res = box.get("result") or {}
        ok = res.get("action") == "offloaded" and bool(res.get("wrote"))
        verify = res.get("verify") or {}
        detail = (f"offload action={res.get('action')!r} wrote={res.get('wrote')!r} "
                  f"verify.ok={verify.get('ok')!r}")
        return GateResult(passed=ok, name="offload-verify", output=detail)

    return _gate


def _recording_runner(**offload_kwargs):
    """``offload_runner(**offload_kwargs)``, wrapped to remember its own result.

    Returns ``(runner, box)``. ``box["result"]`` is set the instant the
    runner returns, which is always BEFORE ``TaskAttempt`` calls the gate
    (see ``daedalus.spine.attempt.TaskAttempt._run_with_ledger``: runner,
    then artifact capture, then gate) -- so ``_relay_gate`` reading ``box``
    always sees this attempt's own result, never a stale or missing one.
    """
    from daedalus.spine.attempt import offload_runner

    box: dict = {}
    base_runner = offload_runner(**offload_kwargs)

    def _runner(ctx):
        res = base_runner(ctx)
        box["result"] = res
        return res

    return _runner, box


def _provider_receipt(result: Any) -> dict[str, Any] | None:
    """Project the small operational part of an offload runner result.

    The full provider result lives on ``AttemptResult.runner_detail``. The
    write-wave projection used to drop it, collapsing every provider refusal
    into ``the runner produced no change to gate``. Keep only routing/action
    facts, measured writes, and rewrite activation/skip provenance -- never
    prompts, repository content, or arbitrary model prose.
    """
    detail = getattr(result, "runner_detail", None)
    if not isinstance(detail, Mapping):
        return None
    report = detail.get("report")
    report = report if isinstance(report, Mapping) else {}
    handoff = report.get("handoff")
    handoff = handoff if isinstance(handoff, Mapping) else {}
    visible_handoff = {
        key: handoff[key]
        for key in ("windowed_rewrite", "skipped", "slice_context_dropped")
        if key in handoff
    }
    receipt: dict[str, Any] = {
        key: detail[key]
        for key in ("provider", "model", "action", "wrote", "did_work")
        if key in detail
    }
    if report.get("status") is not None:
        receipt["report_status"] = report.get("status")
    verify = detail.get("verify")
    if isinstance(verify, Mapping):
        receipt["verify"] = dict(verify)
    if visible_handoff:
        receipt["handoff"] = visible_handoff
    return receipt or None


def _spec_for(assignment: "Assignment", base_revision: str, primary_root: Path,
              nonce: str, gate: Mapping[str, Any] | None = None,
              model: str | None = None) -> "TaskSpec":
    """The TaskSpec for one assignment.

    ``gate`` is the task's OWN curated command gate ({"argv", "cwd",
    "timeout_s"}), forwarded by the caller from the picker candidate that
    produced this work. ``None``/empty reproduces the previous behaviour
    byte-for-byte, including the effect-key digest: ``TaskSpec.body()`` admits
    ``gate`` into the canonical body only when ``gate_argv`` is non-empty, so
    no task that lacks one sees its digest move.

    WHY THIS IS NOT A NEW EXECUTION RISK. The argv is repo-authored, not
    model-authored: ``spine/picker.py`` builds it (docref's is
    ``sys.executable -m daedalus.spine.docref_gate ...``), and the work-queue
    source validates it as a NUL-free string array out of a repo-curated file.
    It is then executed by ``spine.attempt.command_gate`` as an argv list with
    no shell, at LOW INTEGRITY inside containment, in a Job Object, in the
    candidate's own worktree -- the same instrument, with the same containment,
    that already runs every default pytest gate. A model-written patch cannot
    reach this path without a human `git merge` first, because the picker reads
    the primary checkout and promotion stops at an integration branch.
    """
    from daedalus.spine.attempt import TaskSpec

    rel_paths = rebase_declared_paths(assignment.paths, primary_root)
    argv = tuple(str(a) for a in ((gate or {}).get("argv") or ()))
    metadata: dict[str, Any] = {
        "kairos_owner": assignment.owner,
        "kairos_lane": assignment.lane,
        "kairos_worker": assignment.worker,
    }
    rewrite_windows = (gate or {}).get("rewrite_windows")
    if isinstance(rewrite_windows, Mapping) and rewrite_windows:
        # Preserve the exact measured hint on the attempt intent as well as
        # handing it to offload below. This makes "window requested or silently
        # lost?" answerable from one ledger row.
        metadata["rewrite_windows"] = dict(rewrite_windows)
    if model:
        metadata["model"] = str(model)
    return TaskSpec(
        task_id=f"kairos-{assignment.lane}-{nonce}",
        instruction=assignment.objective,
        base_revision=base_revision,
        target_paths=rel_paths,
        gate_argv=argv,
        gate_cwd=str((gate or {}).get("cwd") or "."),
        gate_timeout_s=float((gate or {}).get("timeout_s") or _DEFAULT_GATE_TIMEOUT_S),
        metadata=metadata,
    )


def _curated_relay_gate(box: dict, spec: Any):
    """``_relay_gate`` AND the task's own curated command gate, in that order.

    THIS COMPOSITION IS THE WHOLE POINT, and it exists because putting
    ``gate_argv`` on the TaskSpec alone would have done NOTHING: ``TaskAttempt.
    __init__`` gives an explicitly-passed ``gate=`` precedence over
    ``task.gate_argv``, and this module always passes one. A curated gate that
    is silently ignored is worse than none.

    Order matters, and it is not arbitrary:

    1. ``_relay_gate`` first, as a PRECONDITION. It is the only check that
       catches ``offload()`` finishing ``escalated_after_verify_fail`` with a
       NON-EMPTY ``wrote`` -- a write it could not fully roll back, kept
       visible on purpose. Those bytes are a failed run's debris; judging them
       with a docref re-scan could well return "references resolve" and would
       promote debris. Replacing the relay gate rather than preceding it would
       have opened exactly that hole.
    2. The curated command gate second, as the DISCRIMINATOR -- the thing that
       actually knows whether THIS task succeeded.

    Both verdicts are returned UNCHANGED (never re-wrapped into a fresh
    GateResult), so containment attestations and gate output survive whichever
    one decides. Fail-closed: both must pass.
    """
    relay = _relay_gate(box)

    def _gate(ctx):
        from daedalus.spine.attempt import command_gate

        first = relay(ctx)
        if not first.passed:
            return first
        return command_gate(spec.gate_argv,
                            timeout_s=float(spec.gate_timeout_s),
                            name="queue-command")(ctx)

    return _gate


def _attempt_assignment(assignment: "Assignment", base_revision: str, primary_root: Path,
                         *, project, availability, ledger_path, cancel: Any = None,
                         gate: Mapping[str, Any] | None = None,
                         model: str | None = None,
                         artifact_dir: Path | None = None,
                         ) -> GatedCandidate:
    from daedalus.spine.attempt import run_attempt

    spec = _spec_for(assignment, base_revision, primary_root, uuid.uuid4().hex[:10],
                     gate=gate, model=model)
    runner_kwargs: dict[str, Any] = {
        "project": project,
        "availability": availability,
        "live": True,
    }
    rewrite_windows = (gate or {}).get("rewrite_windows")
    if isinstance(rewrite_windows, Mapping) and rewrite_windows:
        runner_kwargs["rewrite_windows"] = dict(rewrite_windows)
    if model:
        runner_kwargs["model"] = str(model)
    runner, box = _recording_runner(**runner_kwargs)
    gate_fn = _curated_relay_gate(box, spec) if spec.gate_argv else _relay_gate(box)
    result = run_attempt(
        spec, runner=runner, gate=gate_fn, repo_root=str(primary_root),
        ledger_path=ledger_path, keep_worktree=False, reap=True, cancel=cancel,
        artifact_dir=artifact_dir,
    )
    return GatedCandidate(assignment=assignment, spec=spec, result=result)


def _rev_parse_head(repo_root: Path, timeout: int = 30) -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "HEAD"], cwd=str(repo_root),
        capture_output=True, timeout=timeout, env=_hardened_env(), check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"git rev-parse HEAD failed in {repo_root}: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout.decode("utf-8", "replace").strip()


def gate_candidates(repo_root: str, assignments: list, *, project: str | None,
                     availability: dict, max_workers: int,
                     base_commit: str | None = None, ledger_path=None,
                     cancel: Any = None,
                     gates: list[Mapping[str, Any] | None] | None = None,
                     artifact_dir: Path | None = None,
                     ) -> list[GatedCandidate]:
    """PHASE 1: run every write Assignment through ``TaskAttempt``, concurrently.

    Returns one ``GatedCandidate`` per assignment, in ``assignments`` order
    (not completion order). Never touches the primary checkout -- see module
    docstring.

    ``cancel``, when given, is forwarded to every ``TaskAttempt`` unchanged --
    ``daedalus.spine.attempt._as_predicate`` normalises it (a bare callable, or
    anything exposing ``is_set()``, both work with no adapter here). ``None``
    (the default) reproduces today's behaviour exactly: no attempt in this
    batch is cooperatively cancellable. This is deliberately request-scoped,
    not a module-level killswitch lookup -- a caller (e.g. a loop driver) that
    wants every attempt in one batch to share one cancel token passes it once,
    here; this module does not reach for global cancellation state on its own.

    ``artifact_dir`` is optional for direct callers. ``run_write_wave`` always
    supplies the checkout-external content-addressed archive because it returns
    dictionaries rather than the live ``GatedCandidate`` objects.
    """
    root = Path(repo_root).resolve()
    if gates is not None and len(gates) != len(assignments):
        raise RuntimeError(
            f"gate_candidates: {len(gates)} gate hint(s) for "
            f"{len(assignments)} assignment(s)")
    if ledger_path is None:
        from daedalus.spine.picker import resolve_spine_db_path

        ledger_path, ledger_error = resolve_spine_db_path(root)
        if ledger_error or ledger_path is None:
            raise RuntimeError(f"repo-bound spine ledger unavailable: {ledger_error}")
    if base_commit is None:
        base_commit = _rev_parse_head(root)

    # Resolve model assignments against the PRIMARY checkout. The isolated
    # worktree is cut from committed HEAD and therefore (correctly) excludes
    # dirty policy edits; letting offload rediscover the assignment there
    # silently changed Lucia's measured 14B run back to the .env default.
    try:
        from daedalus.config import resolve_project

        primary_data = resolve_project(str(root), project) or {}
        model_assignments = (
            (primary_data.get("team") or {}).get("model_assignments") or {})
    except Exception:  # fail to the provider default, never abort isolation
        model_assignments = {}

    from concurrent.futures import ThreadPoolExecutor

    results: list[GatedCandidate | None] = [None] * len(assignments)
    with ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        futs = {
            pool.submit(
                _attempt_assignment, a, base_commit, root,
                project=project, availability=availability,
                ledger_path=ledger_path, cancel=cancel,
                gate=(gates[i] if gates is not None else None),
                model=(str(model_assignments.get(a.owner))
                       if model_assignments.get(a.owner) else None),
                artifact_dir=artifact_dir,
            ): i
            for i, a in enumerate(assignments)
        }
        for fut in futs:
            results[futs[fut]] = fut.result()
    return results  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# PHASE 2 -- promotion                                                        #
# --------------------------------------------------------------------------- #
class PromotionUnavailable(RuntimeError):
    """The cross-process promotion lock could not be taken."""


class _PromotionLock:
    """Cross-process exclusive lock guarding promotion into ONE repo's
    integration worktree.

    Same primitives as ``daedalus.budget._BudgetLock`` and
    ``runs/council/room.py``'s ``_RoomLock`` (``msvcrt`` on Windows,
    ``fcntl`` on POSIX), independently written here -- both of those are
    private to modules this file does not own. Same fail-closed posture as
    the budget lock, and for the same reason: two promotions racing into one
    integration worktree is exactly the shared-mutable-state hazard this
    whole module exists to close, just moved one layer up. An unobtainable
    lock RAISES; it never silently proceeds unserialised.
    """

    def __init__(self, path: Path, timeout_s: float = 120.0) -> None:
        self.path = Path(path)
        self.timeout_s = timeout_s
        self._fh: Any = None

    def __enter__(self) -> "_PromotionLock":
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "a+b")
        except OSError as exc:
            self._fh = None
            raise PromotionUnavailable(
                f"cannot open promotion lock {self.path}: {exc}; refusing to "
                "promote without serialisation") from exc

        deadline = time.monotonic() + self.timeout_s
        last: Exception | None = None
        while time.monotonic() < deadline:
            try:
                self._acquire()
                return self
            except OSError as exc:
                last = exc
                time.sleep(0.2)
        try:
            self._fh.close()
        except OSError:
            pass
        self._fh = None
        raise PromotionUnavailable(
            f"could not take the promotion lock {self.path} within "
            f"{self.timeout_s:g}s ({last}); another promotion holds it. "
            "Refusing rather than landing unserialised.")

    def _acquire(self) -> None:
        self._fh.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def __exit__(self, *exc: Any) -> bool:
        if self._fh is None:
            return False
        try:
            self._fh.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            self._fh.close()
        except OSError:
            pass
        self._fh = None
        return False


_GIT_EXEC_CONFIG = (
    "core.attributesFile=",
    "core.hooksPath=",
    "core.fsmonitor=",
    "core.sshCommand=",
    "diff.external=",
    "protocol.ext.allow=never",
    "credential.helper=",
    "uploadpack.packObjectsHook=",
)


def _hardened_env() -> dict:
    env = dict(os.environ)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_ATTR_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    for leaky in ("GIT_EXTERNAL_DIFF", "GIT_SSH", "GIT_SSH_COMMAND",
                  "GIT_PROXY_COMMAND", "GIT_ASKPASS", "GIT_DIR", "GIT_WORK_TREE",
                  "GIT_INDEX_FILE"):
        env.pop(leaky, None)
    return env


def _read_gitdir_pointer(worktree: Path) -> Path | None:
    """Mirrors ``daedalus.spine.attempt._read_gitdir_pointer`` (private there,
    reimplemented here rather than imported). See ``_PinnedWorktreeGit``."""
    p = worktree / ".git"
    try:
        if p.is_dir():
            return p
        text = p.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    if not text.startswith("gitdir:"):
        return None
    target = text.split(":", 1)[1].strip()
    return Path(target) if target else None


class _PinnedWorktreeGit:
    """Every git call against ONE worktree, pinned to the admin dir read
    BEFORE any candidate-authored patch is applied into it.

    Mirrors ``daedalus.spine.attempt``'s ``_read_gitdir_pointer`` +
    ``_git(..., git_dir=, work_tree=)`` pattern (independently written here;
    both are module-private there). The reason is the same one that pattern
    exists for: a linked worktree's ``.git`` is a FILE containing
    ``gitdir: <path>``. Once candidate-authored bytes have landed via
    ``git apply`` (see ``promote_candidates``), a later git call that
    re-resolves that pointer from disk is trusting a file the applied patch
    could have rewritten (measured, in ``attempt.py``'s own history, to let a
    candidate-authored ``.gitattributes`` spawn an arbitrary program via a
    config-bound filter/textconv driver). So the pointer is read ONCE, at
    construction -- callers must construct this immediately after
    ``create_worktree`` and before the first ``git apply`` -- and every
    subsequent call is pinned to that captured path explicitly, never
    re-resolved from the (by-then possibly candidate-controlled) working
    tree.
    """

    def __init__(self, worktree: Path):
        self.worktree = Path(worktree)
        self.admin_dir = _read_gitdir_pointer(self.worktree)

    def run(self, args, *, input_bytes: bytes | None = None, timeout: int = 120,
            check: bool = True) -> subprocess.CompletedProcess:
        pre: list[str] = []
        if self.admin_dir is not None:
            pre += [f"--git-dir={self.admin_dir}", f"--work-tree={self.worktree}"]
        for kv in _GIT_EXEC_CONFIG:
            pre += ["-c", kv]
        proc = subprocess.run(
            ["git", *pre, *args], cwd=str(self.worktree), input=input_bytes,
            capture_output=True, timeout=timeout, env=_hardened_env(), check=False)
        if check and proc.returncode != 0:
            detail = proc.stderr.decode("utf-8", "replace").strip()
            raise RuntimeError(f"git {' '.join(args)} failed in {self.worktree}: {detail}")
        return proc


def _reattempt(candidate: GatedCandidate, new_base: str, root: Path, *, project,
               availability, ledger_path, cancel: Any = None) -> GatedCandidate:
    """Re-run the SAME instruction/target_paths against a NEW base commit.

    Used only when the integration branch has moved past the base a
    candidate's artifact was built against -- see ``promote_candidates``. A
    fresh ``TaskSpec`` (same content, new ``base_revision``) through the same
    ``TaskAttempt``/``offload_runner`` path as Phase 1: no new isolation
    mechanism, just the existing one invoked again with an updated base.

    ``cancel`` is forwarded unchanged to this regeneration's own
    ``TaskAttempt`` -- see ``gate_candidates``' docstring for what it accepts.
    """
    from daedalus.spine.attempt import run_attempt

    fresh_spec = _dc_replace(candidate.spec, base_revision=new_base)
    runner_kwargs: dict[str, Any] = {
        "project": project,
        "availability": availability,
        "live": True,
    }
    rewrite_windows = fresh_spec.metadata.get("rewrite_windows")
    if isinstance(rewrite_windows, Mapping) and rewrite_windows:
        runner_kwargs["rewrite_windows"] = dict(rewrite_windows)
    assigned_model = fresh_spec.metadata.get("model")
    if assigned_model:
        runner_kwargs["model"] = str(assigned_model)
    runner, box = _recording_runner(**runner_kwargs)
    gate_fn = (
        _curated_relay_gate(box, fresh_spec)
        if fresh_spec.gate_argv else _relay_gate(box)
    )
    result = run_attempt(
        fresh_spec, runner=runner, gate=gate_fn, repo_root=str(root),
        ledger_path=ledger_path, keep_worktree=False, reap=True, cancel=cancel,
    )
    return GatedCandidate(assignment=candidate.assignment, spec=fresh_spec, result=result)


def _as_cancel_predicate(cancel: Any) -> "Callable[[], bool]":
    """Normalise a cancel token to a zero-arg predicate, for the ONE call site
    in this module (the cumulative re-gate's ``RunnerContext.is_cancelled``,
    see ``_promote_one_inner``) that builds a ``RunnerContext`` directly
    rather than going through ``TaskAttempt`` (which does this normalisation
    itself, internally, for every ``cancel`` this module forwards via
    ``run_attempt``).

    Deliberately NOT an import of ``daedalus.spine.attempt._as_predicate`` --
    that name is module-private there, and this file's own convention is to
    mirror a small private helper rather than reach across another module's
    underscore boundary (see ``_read_gitdir_pointer`` above, which does the
    same for the same reason). Same three-way contract as the original:
    ``None`` -> never cancelled; a callable -> called, a broken callable
    treated as "not cancelled" (a token that raises must not be able to abort
    work it was only supposed to observe); anything exposing ``is_set()`` (a
    ``threading.Event``, a ``KillSwitch``) -> that, same broken-token rule.
    """
    if cancel is None:
        return lambda: False
    if callable(cancel):
        def _call() -> bool:
            try:
                return bool(cancel())
            except Exception:                      # noqa: BLE001
                return False
        return _call
    is_set = getattr(cancel, "is_set", None)
    if callable(is_set):
        def _event() -> bool:
            try:
                return bool(is_set())
            except Exception:                       # noqa: BLE001
                return False
        return _event
    raise TypeError("cancel must be None, a callable, or expose is_set()")


class _CumulativeGateCancelled(RuntimeError):
    """The cumulative re-gate stopped because ``cancel`` fired, not because a
    test genuinely failed. Raised (never silently swallowed) so the SAME
    fabricated-verdict shape this repo already fixed once -- a cooperative
    stop reported as an ordinary gate failure -- cannot recur here: the
    ``except`` block below still resets the integration worktree exactly as
    it does for a real failure (that reset is unconditional and was already
    safe for cancellation before this class existed -- see the comment on
    that reset), but the REASON string a caller sees now says ``cancelled``,
    not ``gate failed``, so a loop driver reading ``reason`` back cannot
    mistake "I was asked to stop" for "this candidate is bad."
    """


def _promote_one_inner(candidate: GatedCandidate, integration_branch: str,
                        integration_worktree: Path, git: _PinnedWorktreeGit, *,
                        root: Path, project, availability, ledger_path,
                        test_command: str | None, test_cwd: str | None,
                        gate_timeout_s: float, _retried: bool,
                        cancel: Any = None) -> dict:
    result = candidate.result
    task_id = result.task_id
    artifact = result.artifact
    current_head = git.run(["rev-parse", "--verify", "HEAD"]).stdout.decode(
        "utf-8", "replace").strip()

    # STALENESS. Every candidate after the first, in the normal case of 2+
    # writes gated concurrently against one shared starting commit, WILL have
    # artifact.base_revision != current_head the moment it is this
    # candidate's turn -- that inequality is not an edge case here, it is the
    # expected shape. A `git apply --check` passing would only prove the
    # bytes still match; it says nothing about whether the change is still
    # semantically correct now that an earlier candidate has landed ahead of
    # it. So: regenerate against the current integration state instead of
    # trusting a check. Bounded to ONE retry -- a second staleness hit means
    # something is landing candidates faster than this one can be recomputed,
    # which is a reason to stop and report, not to loop.
    if artifact.base_revision != current_head:
        if _retried:
            return {"task_id": task_id, "promoted": False, "retried": True,
                    "reason": ("base moved again during its own retry; refusing a "
                               "second regeneration in one promotion pass")}
        fresh = _reattempt(candidate, current_head, root, project=project,
                            availability=availability, ledger_path=ledger_path,
                            cancel=cancel)
        if not fresh.result.ok or not fresh.result.artifact:
            return {"task_id": task_id, "promoted": False, "retried": True,
                    "reason": (f"base moved from {artifact.base_revision[:10]} to "
                               f"{current_head[:10]}; regeneration produced "
                               f"state={fresh.result.state}"
                               + (f": {fresh.result.error}" if fresh.result.error else ""))}
        return _promote_one_inner(
            fresh, integration_branch, integration_worktree, git, root=root,
            project=project, availability=availability, ledger_path=ledger_path,
            test_command=test_command, test_cwd=test_cwd,
            gate_timeout_s=gate_timeout_s, _retried=True, cancel=cancel)

    apply_proc = git.run(["apply", "--whitespace=nowarn", "-"],
                         input_bytes=artifact.diff_bytes, check=False)
    if apply_proc.returncode != 0:
        # NOTHING WRITTEN. `git apply` (no --3way, no --reject) validates the
        # whole patch before writing anything; a non-zero exit here means the
        # integration worktree is exactly as it was before this call. Refused
        # and reported, never retried with a fuzzier match and never merged
        # with conflict markers.
        return {"task_id": task_id, "promoted": False, "retried": _retried,
                "reason": f"git apply refused: {apply_proc.stderr.decode('utf-8', 'replace').strip()}"}

    try:
        if test_cwd not in (None, "", "."):
            raise RuntimeError(
                f"cumulative re-gate needs test_cwd='.'; project configures {test_cwd!r}")
        git.run(["add", "-A"])
        git.run(["commit", "-m", f"kairos candidate {task_id}: {result.branch}"])
        if test_command:
            from daedalus.spine.attempt import RunnerContext, TaskSpec, command_gate

            argv = shlex.split(test_command)
            ctx = RunnerContext(
                worktree=integration_worktree, branch=integration_branch,
                base_revision=current_head,
                task=TaskSpec(task_id="kairos-cumulative-gate",
                              instruction="cumulative re-gate"),
                # WAS `lambda: False` (uncancellable) -- this is the one gate
                # in the promote path that runs the project's WHOLE test
                # command, so it is the longest-running thing a stop request
                # can land inside. Safe to make cancellable: the `except`
                # block just below already resets the integration worktree
                # to `current_head` unconditionally on ANY failure here,
                # cancellation included, so honouring `cancel` adds no new
                # way to leave that worktree in a worse state than finishing
                # would -- it only shortens how long a stop takes to land.
                is_cancelled=_as_cancel_predicate(cancel))
            gate_result = command_gate(argv, timeout_s=gate_timeout_s,
                                       name="cumulative")(ctx)
            if not gate_result.passed:
                if gate_result.cancelled:
                    # Distinct exception type on purpose -- see
                    # _CumulativeGateCancelled's own docstring: the reason
                    # string a caller reads back must say "cancelled", never
                    # "gate failed", or this reintroduces the exact
                    # fabricated-verdict shape this parameter exists to close.
                    raise _CumulativeGateCancelled(
                        f"cumulative gate cancelled after "
                        f"{gate_result.duration_s:.1f}s (cancel requested "
                        f"before the test command finished): "
                        f"{gate_result.output[-400:]}")
                raise RuntimeError(f"cumulative gate failed: {gate_result.output[-400:]}")
    except Exception as e:                                       # noqa: BLE001
        # Whatever partial state add/commit/gate left behind, the integration
        # worktree must come back to EXACTLY current_head with a clean tree
        # before the NEXT candidate's staleness check above runs -- otherwise
        # that check is comparing against a lie.
        git.run(["reset", "--hard", current_head], check=False)
        git.run(["clean", "-fd"], check=False)
        return {"task_id": task_id, "promoted": False, "retried": _retried,
                "reason": f"{type(e).__name__}: {e}"}

    return {"task_id": task_id, "promoted": True, "retried": _retried,
            "reason": "applied and cumulative-gated",
            "changed_paths": list(artifact.changed_paths)}


def _promote_one(candidate: GatedCandidate, integration_branch: str,
                  integration_worktree: Path, git: _PinnedWorktreeGit, **kw) -> dict:
    """``_promote_one_inner``, with a catch-all so ONE candidate's unexpected
    failure (a git plumbing error, a timeout) reports as a refusal rather
    than aborting the whole promotion batch. ``_promote_one_inner`` already
    resets the integration worktree to ``current_head`` on any failure it
    anticipates; this is the net under that for the failures it does not."""
    retried = kw.pop("_retried", False)
    try:
        return _promote_one_inner(candidate, integration_branch, integration_worktree,
                                  git, _retried=retried, **kw)
    except Exception as e:                                       # noqa: BLE001
        return {"task_id": candidate.result.task_id, "promoted": False,
                "retried": retried,
                "reason": f"promotion step raised: {type(e).__name__}: {e}"}


def promote_candidates(repo_root: str, candidates: list[GatedCandidate], *,
                        project: str | None, availability: dict,
                        ledger_path=None, lock_timeout_s: float = 120.0,
                        gate_timeout_s: float = 900.0,
                        cancel: Any = None) -> dict:
    """PHASE 2 -- see module docstring for the full argument. NOT called
    automatically by anything in this module or by ``KairosScheduler``; an
    explicit, separate call.

    ``candidates`` is what Phase 1 (``gate_candidates``) returned, in the
    SAME order they were submitted -- that order is promotion order too, so
    "which candidate wins a real conflict" is reproducible across runs
    rather than depending on thread-scheduling luck.

    Never raises: every failure mode (lock unavailable, apply refused,
    cumulative gate failed, base moved and the retry also failed) is a
    refusal in the returned report, not an exception.

    ``cancel`` is forwarded to every STALENESS-triggered regeneration
    (``_reattempt``'s own ``TaskAttempt`` -- see ``gate_candidates``'
    docstring for what it accepts) AND to the cumulative re-gate's own
    ``command_gate`` call inside ``_promote_one_inner`` -- the longest-running
    step in this whole call, since it re-runs the project's whole test
    command. A cancellation landing there is reported distinctly
    (``_CumulativeGateCancelled`` in the refusal ``reason``, never conflated
    with an ordinary ``cumulative gate failed``), and the SAME unconditional
    ``git reset --hard``/``clean -fd`` that already runs for a genuine
    cumulative-gate failure also runs for a cancelled one -- honouring
    ``cancel`` here does not add a new way to leave the integration worktree
    in a worse state than finishing would; it only shortens how long a stop
    request takes to land.
    """
    root = Path(repo_root).resolve()
    manager = GitWorktreeManager(root)
    live = [c for c in candidates if getattr(c.result, "ok", False) and c.result.artifact
            and not c.result.artifact.is_empty]
    live_ids = {id(c) for c in live}
    # Reported, not dropped: a candidate that never reached STATE_CLEAN in
    # Phase 1 (escalated, gates_failed, no_change, ...) has nothing to
    # promote, but silently omitting it here would make this report LOOK
    # complete while actually only covering a subset of what was asked --
    # the same "silent partial result" shape this whole module exists to
    # refuse elsewhere. Filtered by object IDENTITY, not dataclass equality:
    # two distinct candidates can legitimately compare equal on fields.
    not_gated = [{"task_id": c.result.task_id, "promoted": False,
                 "reason": f"phase 1 did not produce a clean candidate (state={c.result.state})"}
                for c in candidates if id(c) not in live_ids]
    if not live:
        return {"promoted": [], "refused": [], "not_gated": not_gated,
                "integration_branch": None, "note": "no gated candidate to promote"}

    if ledger_path is None:
        from daedalus.spine.picker import resolve_spine_db_path

        ledger_path, ledger_error = resolve_spine_db_path(root)
        if ledger_error or ledger_path is None:
            return {"promoted": [], "not_gated": not_gated, "integration_branch": None,
                    "refused": [{"task_id": c.result.task_id, "promoted": False,
                                "reason": f"ledger unavailable: {ledger_error}"} for c in live]}

    lock_path = manager.worktree_root / "promotion.lock"
    try:
        with _PromotionLock(lock_path, timeout_s=lock_timeout_s):
            report = _promote_locked(root, manager, live, project=project,
                                     availability=availability, ledger_path=ledger_path,
                                     gate_timeout_s=gate_timeout_s, cancel=cancel)
    except PromotionUnavailable as e:
        report = {"promoted": [], "integration_branch": None, "refused": [
            {"task_id": c.result.task_id, "promoted": False, "reason": str(e)}
            for c in live]}
    report["not_gated"] = not_gated
    return report


def _promote_locked(root: Path, manager: GitWorktreeManager, live: list[GatedCandidate],
                    *, project, availability, ledger_path, gate_timeout_s,
                    cancel: Any = None) -> dict:
    from daedalus.config import resolve_project

    base_commit = live[0].result.base_revision or _rev_parse_head(root)
    integration_branch = f"kairos-integration-{uuid.uuid4().hex[:10]}"
    integration_worktree = manager.create_worktree(base_commit, integration_branch)
    git = _PinnedWorktreeGit(integration_worktree)

    if git.admin_dir is None:
        try:
            manager.cleanup_worktree(integration_worktree)
        except Exception:                                        # noqa: BLE001
            pass
        reason = ("integration worktree has no readable gitdir pointer; refusing "
                  "to promote into it unpinned")
        return {"promoted": [], "integration_branch": integration_branch, "refused": [
            {"task_id": c.result.task_id, "promoted": False, "reason": reason}
            for c in live]}

    pdata = resolve_project(str(root), project)
    test_command = (pdata or {}).get("test_command")
    test_cwd = (pdata or {}).get("test_cwd") or "."

    promoted: list[dict] = []
    refused: list[dict] = []
    for candidate in live:
        outcome = _promote_one(
            candidate, integration_branch, integration_worktree, git, root=root,
            project=project, availability=availability, ledger_path=ledger_path,
            test_command=test_command, test_cwd=test_cwd,
            gate_timeout_s=gate_timeout_s, _retried=False, cancel=cancel)
        (promoted if outcome.get("promoted") else refused).append(outcome)

    cleanup_error = None
    try:
        manager.cleanup_worktree(integration_worktree)
    except Exception as e:                                        # noqa: BLE001
        cleanup_error = f"{type(e).__name__}: {e}"
    try:
        manager.reap_branches()
    except Exception:                                              # noqa: BLE001
        pass

    report = {
        "promoted": promoted, "refused": refused,
        "integration_branch": integration_branch,
        "inspect": f"git diff {base_commit}..{integration_branch}",
        "note": ("no file in the primary checkout was changed; nothing is merged "
                 "until a human (or a separately-invoked step) acts on the "
                 "integration branch above"),
    }
    if cleanup_error:
        report["cleanup_error"] = cleanup_error
    return report


# --------------------------------------------------------------------------- #
# PHASE 3 -- wiring the auto-promote POLICY into a build-session write wave   #
# --------------------------------------------------------------------------- #
# This is the "one line change once the product decision is made" the module
# docstring pointed at, made on 2026-07-29: the owner answered "eigentlich
# automatisch aber das soll unteranderem einstellbar sein" (automatic by
# default, but configurable). ``daedalus.build_exec.WaveExecutor.run_wave``'s
# ``_WRITE_WAVE_POLICY`` call site is the only caller ``run_write_wave`` below
# is written for -- it replaces that method's old forced-sequential
# ``scheduler.dispatch(..., parallel=False)`` for the write-mode tasks in a
# wave with: gate concurrently (Phase 1), then decide per-candidate whether
# ``promote_candidates`` (Phase 2) runs automatically, using
# :data:`AUTO_PROMOTE_LEVELS` -- mirroring
# ``daedalus.config.WRITE_WAVE_POLICY_LEVELS`` exactly; see that module for
# the full three-level contract and why it composes with, and never bypasses,
# ``daedalus.core.get_governance``'s ``promotion_allowed``.
AUTO_PROMOTE_LEVELS = ("never", "low_risk", "always")


def _governance_verdict(project: str | None) -> tuple[bool, str, str]:
    """``(promotion_allowed, governance_state, headline)`` -- read straight off
    ``daedalus.core.get_governance``, never re-derived here.

    That function's own docstring is explicit that a SECOND opinion on
    ``promotion_allowed`` is how an override sneaks in ("the other gates
    inform the operator; they do not get a vote on promotion"); this module
    composes with it by calling it, not by re-implementing the discrimination
    check. Any failure to even ASK the question -- ``daedalus.core``
    unimportable, the call itself raising -- reports the vocabulary's
    ``unknown``, not a silent True. ``unknown`` and ``absent`` stay distinct
    facts (see ``daedalus.core.GOVERNANCE_STATES``): this only ever
    manufactures ``unknown`` for a failure that happened HERE; a real
    ``absent`` receipt is already reported correctly by ``get_governance``
    itself and passes through unchanged.
    """
    try:
        from daedalus.core import get_governance
    except Exception as e:                        # noqa: BLE001
        return False, "unknown", f"governance module unavailable ({type(e).__name__}: {e})"
    try:
        gov = get_governance(project)
    except Exception as e:                         # noqa: BLE001
        return False, "unknown", f"governance check raised {type(e).__name__}: {e}"
    allowed = bool(gov.get("promotion_allowed"))
    state = str(gov.get("state") or "unknown")
    verdict = str(gov.get("verdict") or "")
    return allowed, state, verdict


def run_write_wave(scheduler, repo_root: str, tasks: list[dict], assignments: list,
                    *, auto_promote: str, ledger_path=None,
                    cancel: Any = None) -> list[dict]:
    """Execute one build-session wave's WRITE-mode tasks through the gated,
    isolated-worktree path, then apply ``auto_promote``'s decision about
    whether the resulting candidates advance to the integration branch
    automatically or wait for a human.

    ``cancel``, when given, is forwarded unchanged to both phases --
    ``gate_candidates`` (every concurrent attempt in this wave) and, for
    whichever candidates ``auto_promote`` submits, ``promote_candidates``
    (their staleness-retry regenerations AND the cumulative re-gate that runs
    the project's whole test command after each apply -- see
    ``promote_candidates``' own docstring for why cancelling that specific
    step is safe). ``None`` (the default) is byte-identical to this
    function's behaviour before ``cancel`` existed: no caller that does not
    pass it is affected. A caller driving a longer-lived loop (pick -> attempt
    -> gate -> promote -> re-pick) across multiple waves can pass one shared
    token/``KillSwitch`` here so a stop request reaches every in-flight
    ``TaskAttempt`` and every in-flight cumulative gate this wave started,
    cooperatively, instead of relying solely on the killswitch's process-wide
    sweep (which still works today with ``cancel=None`` -- see
    ``daedalus.spine.killswitch``'s own module docstring -- but can race a
    gate's own poll and report a fabricated verdict; that race is exactly
    what this parameter exists to close).

    ``assignments`` MUST be ``scheduler.accept(tasks, repo_root=repo_root)``'s
    own return, in the SAME order as ``tasks`` -- the caller
    (``WaveExecutor.run_wave``) already computed this to decide
    ``has_writes``/``wave_parallel``. Recomputing it here would still be SAFE
    (``accept`` is a pure classification -- no persona-cycling or other
    per-call state feeds it; two calls on the same tasks always agree) but
    would silently trust two call sites to keep agreeing forever, which is
    exactly the "two surfaces, two answers, same instant" drift
    ``daedalus.core.get_governance``'s own docstring was written to stop.
    Passed in once, length-checked, used once.

    Returns one result dict per entry in ``tasks``, position-matched -- the
    same contract ``KairosScheduler.dispatch`` already gives
    ``WaveExecutor.run_wave`` (see that method's length check immediately
    after this call). Non-write tasks in the SAME wave (advisory, or bounced
    to the senior lane) are NOT touched by the gated path: they are delegated
    back to ``scheduler.dispatch``, scoped to just their own indices, exactly
    as they would have run before this function existed.

    NEVER writes the primary checkout, at ANY ``auto_promote`` level --
    inherited from ``promote_candidates``, which lands only into a disposable
    integration worktree/branch, never ``repo_root`` itself. "auto" here
    governs candidate -> integration-branch only; integration-branch ->
    primary checkout stays a human ``git merge``, regardless of this setting.
    """
    if len(assignments) != len(tasks):
        raise RuntimeError(
            f"run_write_wave: {len(assignments)} assignment(s) for {len(tasks)} "
            "task(s) -- caller must pass scheduler.accept(tasks, ...)'s own "
            "result, position-matched")
    if auto_promote not in AUTO_PROMOTE_LEVELS:
        # Fail closed on garbage reaching this deep too -- a caller that
        # skipped daedalus.config.resolve_write_wave_policy's own validation,
        # or a value from a future level this build doesn't know, must never
        # be read as MORE permissive than "never".
        auto_promote = "never"

    from .scheduler import DEFAULT_AVAILABILITY

    root = Path(repo_root).resolve()
    n = len(tasks)
    write_idx = [i for i, a in enumerate(assignments)
                if a.accepted and a.mode == "write"]
    other_idx = [i for i in range(n) if i not in write_idx]

    results: list[dict | None] = [None] * n

    if other_idx:
        other_tasks = [tasks[i] for i in other_idx]
        other_raw = scheduler.dispatch(str(root), other_tasks, dry_run=False,
                                       parallel=False)
        if len(other_raw) != len(other_idx):
            raise RuntimeError(
                f"run_write_wave: dispatch() returned {len(other_raw)} result(s) "
                f"for {len(other_idx)} non-write task(s) -- contract drifted")
        for pos, i in enumerate(other_idx):
            results[i] = other_raw[pos]

    if not write_idx:
        return results  # type: ignore[return-value]

    avail = scheduler.availability or DEFAULT_AVAILABILITY
    write_assignments = [assignments[i] for i in write_idx]
    write_gates = [
        tasks[i].get("gate") if isinstance(tasks[i].get("gate"), Mapping) else None
        for i in write_idx
    ]
    candidates = gate_candidates(
        str(root), write_assignments, project=scheduler.project,
        availability=avail,
        max_workers=min(scheduler.max_parallel_writes, scheduler.max_workers),
        ledger_path=ledger_path, cancel=cancel, gates=write_gates,
        artifact_dir=_artifact_root_for(root))

    promotion_allowed, gov_state, gov_verdict = _governance_verdict(scheduler.project)

    to_promote: list[GatedCandidate] = []
    held: list[tuple[GatedCandidate, str]] = []  # (candidate, why-held)

    if not promotion_allowed:
        why = (f"auto_promote={auto_promote!r} but promotion is blocked by "
               f"governance (state={gov_state!r}): {gov_verdict}")
        held = [(c, why) for c in candidates]
    elif auto_promote == "never":
        held = [(c, "auto_promote='never': held for a human to promote "
                    "(daedalus.kairos.gated_writes.promote_candidates)")
                for c in candidates]
    elif auto_promote == "always":
        to_promote = list(candidates)
    else:  # "low_risk"
        from ..sensitivity import change_risk

        for c in candidates:
            risk = change_risk(c.assignment.objective, c.assignment.paths,
                               policy=scheduler.policy)
            if risk == "low":
                to_promote.append(c)
            else:
                held.append((c, f"auto_promote='low_risk' but this task's "
                               f"change-risk is {risk!r}, not 'low'; held for "
                               "a human to promote"))

    promote_report: dict | None = None
    promoted_by_task: dict[str, dict] = {}
    refused_by_task: dict[str, dict] = {}
    if to_promote:
        promote_report = promote_candidates(
            str(root), to_promote, project=scheduler.project, availability=avail,
            ledger_path=ledger_path, cancel=cancel)
        for entry in promote_report.get("promoted", []):
            tid = entry.get("task_id")
            if tid:
                promoted_by_task[tid] = entry
        for entry in (list(promote_report.get("refused", []))
                      + list(promote_report.get("not_gated", []))):
            tid = entry.get("task_id")
            if tid:
                refused_by_task[tid] = entry

    held_by_task = {c.result.task_id: why for c, why in held}
    integration_branch = (promote_report or {}).get("integration_branch")

    for pos, i in enumerate(write_idx):
        candidate = candidates[pos]
        res = candidate.result
        assignment = write_assignments[pos]
        task_id = res.task_id
        base = {
            "worker": assignment.worker, "lane": assignment.lane,
            "mode": assignment.mode, "owner": assignment.owner,
            "objective": assignment.objective, "paths": assignment.paths,
            "kairos_gated": True, "task_id": task_id,
            "attempt_state": res.state, "attempt_branch": res.branch,
            "auto_promote": auto_promote, "governance_state": gov_state,
        }
        receipt = _provider_receipt(res)
        if receipt is not None:
            base["provider_receipt"] = receipt
            if receipt.get("model"):
                base["model"] = str(receipt["model"])
        if res.artifact is not None:
            base["artifact_sha256"] = res.artifact.diff_sha256
            base["artifact_bytes"] = res.artifact.byte_length
            base["changed_paths"] = list(res.artifact.changed_paths)
        if res.artifact_path:
            base["artifact_path"] = res.artifact_path
        if res.persist_error:
            base["artifact_persist_error"] = res.persist_error
        if not res.ok or not res.artifact:
            results[i] = {**base, "status": "write_gate_failed",
                         "reason": (res.error or f"attempt state={res.state}")}
            continue
        if task_id in promoted_by_task:
            entry = promoted_by_task[task_id]
            results[i] = {**base, "status": "gated_promoted",
                         "reason": entry.get("reason"),
                         "integration_branch": integration_branch,
                         "changed_paths": entry.get("changed_paths")}
            continue
        if task_id in refused_by_task:
            entry = refused_by_task[task_id]
            results[i] = {**base, "status": "gated_refused",
                         "reason": entry.get("reason"),
                         "integration_branch": integration_branch}
            continue
        # Clean candidate, not (yet) submitted for promotion: held by policy
        # or by governance -- see `held_by_task` for exactly which.
        if not res.artifact_path:
            results[i] = {
                **base,
                "status": "gated_artifact_lost",
                "reason": (
                    "candidate passed its gates but its patch bytes could not "
                    "be persisted after the attempt branch was reaped: "
                    f"{res.persist_error or 'no artifact path reported'}"
                ),
            }
        else:
            results[i] = {**base, "status": "gated_held",
                         "reason": held_by_task.get(
                             task_id, "held for a human to promote "
                             "(daedalus.kairos.gated_writes.promote_candidates)")}

    return results  # type: ignore[return-value]
