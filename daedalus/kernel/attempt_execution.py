"""Kernel-owned TaskAttempt lifecycle core.

The registered effect doors and legacy default composition remain at
``daedalus.spine.attempt``.  This owner contains the lifecycle implementation
but deliberately cannot discover a Kairos workspace manager or an evaluator:
both capabilities arrive through neutral ports.

ONE way to attempt a task. The loop ("Daedalus writes Daedalus") needs exactly
one seam between "we decided to try this" and "here is a patch a human may
promote", and that seam must be crash-safe and incapable of touching the
developer's working tree. This module is that seam.

    storage -> intent -> worktree -> runner -> patch -> gates -> resolve -> cleanup

Each arrow is a place the process can die; the intent is committed to the spine
ledger BEFORE the first external effect, so a crash can never leave a worktree
or a branch the ledger has no record of intending. The ``effect_key`` is the
candidate BRANCH NAME -- a token you can go and look for afterwards
(``git branch --list <effect_key>``), which is what actually closes the crash
window (see :mod:`daedalus.spine.ledger`).

WHY THIS CAN NOT WRITE THE PRIMARY CHECKOUT
-------------------------------------------
Not a convention, not a review rule -- four structural properties:

1. ONE git choke point. Every git invocation in this module goes through
   :func:`_git`, which raises :class:`PrimaryCheckoutWrite` if the working
   directory OVERLAPS the primary checkout IN EITHER DIRECTION -- it is the
   checkout, is under it, or CONTAINS it -- and the verb is not in
   :data:`READ_ONLY_REPO_VERBS`. Overlap is decided by file IDENTITY as well as
   by path text, because ``Path.resolve()`` does not canonicalise DOS-device or
   UNC admin-share spellings and a text-only guard was measured allowing
   ``git add -A`` to stage files in the checkout through them (see
   :func:`_overlap_reason`). The guard runs BEFORE ``subprocess`` is
   reached, so a mutating command aimed at the repo never executes. Mutating
   git (``add``) is only ever run with ``cwd`` set to the worktree, which lives
   outside the repo by construction (``GitWorktreeManager`` places worktrees
   under ``%LOCALAPPDATA%``).
2. THE RUNNER IS NEVER TOLD WHERE THE REPO IS. :class:`RunnerContext` -- the
   only thing handed to injected runner/gate callables -- carries the worktree
   path and nothing else path-shaped. There is deliberately no ``repo_root``
   field to reach for.
3. THERE IS NO APPLY PATH. The deliverable is :class:`PatchArtifact`: inert
   bytes. This module defines no function that applies a patch, checks out a
   ref, resets, merges, or commits to the primary checkout, and
   :data:`READ_ONLY_REPO_VERBS` makes adding one fail loudly rather than
   quietly work. Promotion is a separate, human-invoked act, and that is the
   whole point: an unvalidated metric must never gate autonomy.
4. THE ONE CALLER-CHOSEN OUTPUT PATH IS FENCED. Properties 1-3 hold because
   every path this module writes is one it CONSTRUCTS -- the worktree under
   ``%LOCALAPPDATA%``, the gate's scratch tree under ``%TEMP%``. ``artifact_dir``
   is the exception: a plain constructor argument naming a directory to deposit
   patch bytes into, and it was unchecked, so ``artifact_dir=<repo>/runs/patches``
   wrote candidate bytes into the primary checkout and created the directories
   to do it. :meth:`TaskAttempt._persist` now clears
   :func:`daedalus.primary_tree.assert_write_allowed` BEFORE ``mkdir``, and a
   refusal is reported on the result rather than raised, because failing to
   save a file must not throw away a gated candidate.

WHAT IS DELIBERATELY *NOT* FENCED, because it is not the attempt writing itself:
the SPINE LEDGER. ``SpineLedger()`` defaults to ``<repo>/runs/spine/spine.sqlite3``
(MEASURED), inside the primary checkout, and that is correct -- a durable record
that an attempt happened is the opposite of the attempt leaking into the tree,
and moving it outside the repo would put the crash-recovery evidence somewhere
the developer does not look. It writes only under ``runs/``, never a tracked
source file, so ``git status --porcelain`` is unaffected. Stated here so the
list of primary-checkout writes is deliberate rather than discovered later.

What this DOES write in the primary repo's ``.git``: a branch ref and a
worktree registration, created by ``git worktree add -b`` via
``GitWorktreeManager``. That is how the effect becomes findable after a crash.
HEAD does not move, no tracked file changes, and ``git status --porcelain``
stays byte-identical -- which the test suite asserts after every scenario.

FAILURE IS A STATE, NOT AN EXCEPTION
------------------------------------
:meth:`TaskAttempt.run` returns an :class:`AttemptResult` in every case. The
states:

``storage_unavailable``  the watermark refused before anything was recorded or
                         created (fail closed; never spill onto another volume)
``worktree_failed``      no isolated checkout could be produced, or the patch
                         could not be captured out of one
``runner_failed``        the injected runner raised
``no_change``            the runner finished but changed nothing
``gates_failed``         a patch exists and the gates rejected it
``clean``                a patch exists and the gates passed
``cancelled``            the cancel token fired at a checkpoint

``no_change`` and ``cancelled`` are additions to the five states the brief
named. ``cancelled`` is required by the cancellation contract. ``no_change``
exists because gates run against an UNMODIFIED tree are a vacuous pass: without
this state a runner that did nothing returns ``clean``, which is exactly the
kind of unearned green this project forbids. Gates are skipped in that state --
there is nothing to judge.

LEDGER RESOLUTION
-----------------
The recorded intent is "produce a candidate patch", so it is COMPLETED whenever
an artifact exists -- including ``gates_failed``, because a rejected candidate
is a successfully produced candidate, and the gate verdict is a judgement ABOUT
the effect, not the effect. ``effect_id`` is the patch digest. Intents are
marked FAILED only when no artifact was produced at all.
"""
from __future__ import annotations

import hashlib
import os
import re
# NOT `import shutil`. This module has no recursive delete of its own: the gate
# scratch directory goes through the injected cleanup port. Keeping the import
# out means re-introducing `shutil.rmtree` costs a visible line in the diff
# rather than passing as ordinary use of something already imported.
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field, replace
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence, runtime_checkable

from daedalus.limit_policy import ExecutionLimitPolicy, load_from_env
# THE FENCE LIVES IN ONE MODULE, and this file no longer owns a copy of it.
# `_identity` and `_overlap_reason` were defined here; `eval/correctness.py`
# then grew a SECOND answer to the same question that fails OPEN where this one
# fails closed (see :mod:`daedalus.primary_tree` for the measurement). Importing
# rather than re-deriving is the whole point -- a caller that needs the
# comparison must get THIS one.
from daedalus.primary_tree import (
    PrimaryCheckoutWrite,
    _identity,
    assert_write_allowed,
    nearest_existing,
    overlap_reason as _overlap_reason,
    planned_overlap_reason as _planned_overlap_reason,
)
from daedalus.kernel.contracts.base import ContractProvenance
from daedalus.kernel.contracts.resources import ResourceBudget, ResourceUsage
from daedalus.kernel.events.durability import open_gate0_spine_writer
from daedalus.kernel.events.envelope import current_trace_id
from daedalus.kernel.events.ledger import SpineLedger, canonical_json
from daedalus.storage import (
    ArtifactLocator,
    ArtifactStore,
    StorageUnavailable,
    require_storage,
)

__all__ = [
    "ATTEMPT_STATES",
    "AttemptEvaluatorPort",
    "AttemptPortMissing",
    "AttemptResult",
    "AttemptWorkspacePort",
    "GateResult",
    "GitCommandError",
    "INTENT_KIND",
    "OffloadPort",
    "PatchArtifact",
    "PrimaryCheckoutWrite",
    "READ_ONLY_REPO_VERBS",
    "RunnerContext",
    "ScratchCleanupPort",
    "STATE_CANCELLED",
    "STATE_CLEAN",
    "STATE_GATES_FAILED",
    "STATE_NO_CHANGE",
    "STATE_RUNNER_FAILED",
    "STATE_STORAGE_UNAVAILABLE",
    "STATE_WORKTREE_FAILED",
    "STATE_LEASE_REFUSED",
    "TaskAttempt",
    "TaskSpec",
    "offload_runner",
    "pytest_gate_argv",
]

ROOT = Path(__file__).resolve().parents[2]

INTENT_KIND = "attempt.candidate"

STATE_CLEAN = "clean"
STATE_GATES_FAILED = "gates_failed"
STATE_NO_CHANGE = "no_change"
STATE_RUNNER_FAILED = "runner_failed"
STATE_WORKTREE_FAILED = "worktree_failed"
STATE_STORAGE_UNAVAILABLE = "storage_unavailable"
STATE_CANCELLED = "cancelled"
#: The handed python.attempt Effect Lease refused to begin this execution --
#: a replayed execution identity, an expired or revoked lease, a stopped kill
#: switch. Its own state rather than ``worktree_failed`` because the receipt
#: must not name a cause that never happened (Momus, 2026-08-23 item 7): no
#: worktree existed and none was attempted.
STATE_LEASE_REFUSED = "lease_refused"

ATTEMPT_STATES = (
    STATE_CLEAN,
    STATE_GATES_FAILED,
    STATE_NO_CHANGE,
    STATE_RUNNER_FAILED,
    STATE_WORKTREE_FAILED,
    STATE_STORAGE_UNAVAILABLE,
    STATE_CANCELLED,
    STATE_LEASE_REFUSED,
)

# The only git verbs this module may aim at the primary checkout. Every one of
# them reports; none of them writes. Adding a verb here is the single place a
# reviewer has to look to know whether the no-write property still holds.
READ_ONLY_REPO_VERBS = frozenset({
    "rev-parse", "status", "diff", "log", "show", "cat-file", "ls-files",
    "config",
})

# Gate output is retained in full on GateResult. Only the ledger copy is
# trimmed -- an unbounded pytest log inside a SQLite row would grow the ledger
# without making any decision better; the digest keeps the trimmed copy honest.
GATE_OUTPUT_TAIL_CHARS = 4000

DEFAULT_GATE_TIMEOUT_S = 900.0
DEFAULT_GIT_TIMEOUT_S = 120.0
BRANCH_PREFIX = "daedalus-attempt"


#: Re-exported from :mod:`daedalus.primary_tree`, which now owns it. It is the
#: SAME class object, so every existing ``except PrimaryCheckoutWrite`` and
#: ``pytest.raises(PrimaryCheckoutWrite)`` against this module keeps working.
PrimaryCheckoutWrite = PrimaryCheckoutWrite


class GitCommandError(RuntimeError):
    """A git command run by this module exited non-zero."""


class TaskSpecInvalid(ValueError):
    """A declared path in a :class:`TaskSpec` names no location in the tree.

    A ``ValueError`` on purpose: the picker builds specs out of JSON payloads
    and already treats ``ValueError`` as "this candidate is not usable", so an
    unusable declaration is refused where it is written instead of travelling
    as far as the containment gate.
    """


class AttemptPortMissing(RuntimeError):
    """A lifecycle capability was not injected at the composition boundary."""


@runtime_checkable
class OffloadPort(Protocol):
    """The offload WORKLOAD, as a capability the kernel may hold.

    ``daedalus.offload`` sits ABOVE the kernel, so the kernel may not import
    it -- that import was this repository's single recorded boundary violation
    until G1-SCC-CUT1 retired it (see :func:`offload_runner`).

    DECLARED AS A PROTOCOL, AND CALLED AS A METHOD, ON PURPOSE. The effect
    derivation in ``tests/test_registry_new_doors.py`` follows an injected port
    through its parameter ANNOTATION: a Protocol expands to the repository-local
    classes that define its declared methods, and the walk then continues into
    those method bodies. That hop fires only for ``receiver.method(...)``; a
    bare ``callable(...)`` parameter annotated ``Callable[..., Any]`` yields
    nothing (``_annotation_names`` discards ``Callable`` because its arguments
    describe contents, not the receiver).

    So the annotation is what keeps ``cli.picker`` and ``cli.bootstrap`` able to
    justify NETWORK_EGRESS, SECRETS and SPEND after the import was removed. It
    is not a bridge absorbing a lost hop -- the walk really does reach
    ``daedalus.offload`` again, through the contract written here. Keep
    ``run_offload`` distinctively named: the Protocol expands to EVERY local
    class defining its whole method set, so a generic name like ``run`` would
    widen the closure instead of resolving it.
    """

    def run_offload(self, objective: str, repo_root: str, **kwargs: Any) -> Any:
        ...


@runtime_checkable
class AttemptWorkspacePort(Protocol):
    """Neutral checkout-external workspace capability used by an Attempt."""

    worktree_root: Path

    def create_worktree(self, base_commit: str, branch_name: str) -> Path: ...

    def cleanup_worktree(self, path: str | Path) -> None: ...

    def reap_branches(self) -> list[dict]: ...


@runtime_checkable
class AttemptEvaluatorPort(Protocol):
    """Neutral gate construction capability selected outside the kernel."""

    def command_gate(
        self,
        argv: Sequence[str],
        *,
        timeout_s: float | None,
        name: str,
    ) -> Callable[["RunnerContext"], "GateResult"]: ...

    def correctness_gate(
        self,
        task: "TaskSpec",
        repo_root: Path,
        *,
        timeout_s: float | None,
    ) -> Callable[["RunnerContext"], "GateResult"]: ...

    def pytest_gate(
        self,
        paths: Sequence[str],
        *,
        timeout_s: float | None,
        use_default_timeout: bool,
    ) -> Callable[["RunnerContext"], "GateResult"]: ...


ScratchCleanupPort = Callable[[Path], str | None]


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()


def _slug(text: str, limit: int = 32) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:limit].strip("-")
    return slug or "task"


def _jsonable(value: Any) -> Any:
    """Coerce to something :func:`canonical_json` accepts.

    A caller's metadata must never be able to abort an attempt: an
    unserialisable value is degraded to its repr rather than raising out of the
    ledger write, which would strand the attempt between intent and effect.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(v) for v in value]
    return repr(value)


#: The nearest existing directory at or above a path.
#:
#: ``shutil.disk_usage`` raises on a missing path, so checking the worktree
#: root directly would report ``storage_unavailable`` on a first run purely
#: because the directory has not been created yet. Walking up asks the question
#: that was actually meant: does the VOLUME have room -- and it asks it without
#: creating anything, so the storage check stays side-effect free.
#:
#: This was a third private copy of the same walk (the fence needs it to find
#: the GROUND a not-yet-created file will land on). Same function, same
#: semantics, so it is an alias rather than a reimplementation.
_existing_ancestor = nearest_existing


def _as_predicate(cancel: Any) -> Callable[[], bool]:
    """Normalise a cancel token to a zero-arg predicate.

    Accepts ``None``, a callable, or anything with ``is_set()`` (so a
    ``threading.Event`` works unwrapped). A token that raises is treated as
    "not cancelled": a broken token must not be able to abort work it was only
    supposed to observe.
    """
    if cancel is None:
        return lambda: False
    if callable(cancel):
        def _call() -> bool:
            try:
                return bool(cancel())
            except Exception:
                return False
        return _call
    is_set = getattr(cancel, "is_set", None)
    if callable(is_set):
        def _event() -> bool:
            try:
                return bool(is_set())
            except Exception:
                return False
        return _event
    raise TypeError("cancel must be None, a callable, or expose is_set()")


# `_identity` and `_overlap_reason` USED TO BE DEFINED HERE, ~90 lines of
# identity-vs-lexical path comparison. They now live in
# :mod:`daedalus.primary_tree` and are imported at the top of this file under
# the same names, so `attempt_mod._overlap_reason` still resolves and the git
# choke point below is unchanged in behaviour. The move is not tidying: a
# second copy of this comparison had already appeared in `eval/correctness.py`
# and had already diverged on the fail-closed case, which is the failure mode
# this codebase keeps re-living. There is now one comparison, asked in one
# direction for a write and in both for a working directory.


#: Config keys git will consult that name a program to EXECUTE. Every one of
#: them is pinned empty on the command line, where no config file can override
#: it. See :func:`_git` for the measurement that made this necessary.
_GIT_EXEC_CONFIG = (
    "core.attributesFile=",     # a global attributes file selecting a filter
    "core.hooksPath=",          # hooks, for any verb that fires them
    "core.fsmonitor=",          # git runs this to ask what changed
    "core.sshCommand=",
    "diff.external=",           # belt to --no-ext-diff's braces
    "protocol.ext.allow=never",  # ext:: URLs are a shell command by design
    "credential.helper=",
    "uploadpack.packObjectsHook=",
)


def _read_gitdir_pointer(worktree: str | Path) -> Path | None:
    """The real admin directory of a linked worktree, read from its ``.git``.

    A linked worktree's ``.git`` is a FILE containing ``gitdir: <abs path>``.
    Read once, before any candidate code exists, so later git invocations can
    name the directory explicitly instead of re-resolving a pointer the
    candidate may since have rewritten.

    Returns ``None`` when the shape is not the expected one -- a plain
    directory (an ordinary clone rather than a linked worktree), a missing
    file, or an unreadable one. ``None`` means "do not pin", which leaves git's
    normal discovery in place; it is the pre-existing behaviour, so a caller is
    never worse off than before this existed. It is emphatically NOT a claim
    that the worktree is safe.
    """
    p = Path(worktree) / ".git"
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


#: Config keys that decide what a file's CONTENT IS, rather than what runs.
#: None of them can name a program, so all of them are safe to carry over.
#:
#: They must be carried over, and that was measured rather than foreseen.
#: Emptying GIT_CONFIG_GLOBAL removes ``core.autocrlf`` along with everything
#: else, and on Windows that setting is what makes a CRLF working tree compare
#: equal to an LF index. Without it `git add -A` staged a committed, unmodified
#: file, `_capture_patch` returned a non-empty diff for a runner that changed
#: nothing, and the attempt reported `clean` instead of `no_change` -- an
#: unearned green, and every candidate patch would have carried the whole tree.
_GIT_INHERITED_CONFIG = (
    "core.autocrlf", "core.eol", "core.safecrlf", "core.fileMode",
    "core.symlinks", "core.ignorecase", "core.longpaths", "core.precomposeUnicode",
)


@lru_cache(maxsize=1)
def _inherited_config_args() -> tuple[str, ...]:
    """Read the allowlisted keys from the operator's REAL config, once.

    Read with git's ordinary environment on purpose: the question is what this
    checkout was created under, and the answer lives in the config the hardened
    environment is about to hide. Cached because it cannot change mid-run and
    the alternative is a subprocess per key per git call.

    Failure is silent BY DESIGN and is the safe direction: a key we cannot read
    is simply not passed, which leaves git's own default. The dangerous
    direction would be inheriting something we did not mean to.
    """
    args: list[str] = []
    for key in _GIT_INHERITED_CONFIG:
        try:
            proc = _git(["config", "--get", key], cwd=ROOT, repo_root=ROOT,
                        harden=False, check=False, timeout=10)
        except Exception:                        # noqa: BLE001
            continue
        value = proc.stdout.decode("utf-8", "replace").strip()
        if proc.returncode == 0 and value:
            args += ["-c", f"{key}={value}"]
    return tuple(args)


def _git_env() -> dict:
    """The environment git is spawned with: no config it did not get from us.

    ``GIT_CONFIG_NOSYSTEM`` and an empty ``GIT_CONFIG_GLOBAL`` remove the system
    and per-user config files from the lookup, which is where a ``filter.*``
    definition would otherwise live. On this box that is not hypothetical --
    ``git config --list --show-origin`` shows ``filter.lfs.*`` in BOTH the
    system and the user config, so a candidate that writes ``* filter=lfs``
    into ``.gitattributes`` makes ``git add`` spawn ``git-lfs`` with no config
    of its own at all.

    ``GIT_EXTERNAL_DIFF`` and friends are dropped rather than emptied: an empty
    value for some of these is a *valid command*, not an absence.

    Promotion secrets are stripped first (Phase-0 case A9a, MEASURED: a plain
    child of the verifier read ``DAEDALUS_OWNER_APPROVAL_SECRET_CANARY``
    verbatim out of an inherited environment). Git has no use for one, and a
    hook or a ``filter.*`` command git spawns is a child like any other.
    """
    from daedalus.kernel.promotion_trust_root import scrubbed_child_env

    env = scrubbed_child_env()
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_ATTR_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    for leaky in ("GIT_EXTERNAL_DIFF", "GIT_DIR", "GIT_WORK_TREE",
                  "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY",
                  "GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_ATTR_SYSTEM",
                  "GIT_CONFIG", "GIT_CONFIG_COUNT", "GIT_SSH", "GIT_SSH_COMMAND",
                  "GIT_PROXY_COMMAND", "GIT_ASKPASS"):
        env.pop(leaky, None)
    return env


def _git(args: Sequence[str], *, cwd: str | Path, repo_root: str | Path,
         git_dir: str | Path | None = None,
         work_tree: str | Path | None = None,
         harden: bool = True,
         timeout: float = DEFAULT_GIT_TIMEOUT_S,
         check: bool = True) -> subprocess.CompletedProcess:
    """Run git and return the RAW BYTES it produced.

    The single choke point (see the module docstring). ``cwd`` inside the
    primary checkout is restricted to :data:`READ_ONLY_REPO_VERBS`; anything
    else raises :class:`PrimaryCheckoutWrite` before the process is spawned.

    Output is not decoded: a patch digest must be taken over the bytes git
    emitted, so a lossy decode can never change what was hashed.

    GIT IS A PROCESS LAUNCHER, AND THE CANDIDATE CHOOSES WHAT IT LAUNCHES.
    This was measured on this box (git 2.38.1.windows.1), not reasoned about.
    ``<worktree>/.gitattributes`` is plain candidate content; it selects a
    ``filter.<name>.clean`` program, and ``git add -A`` runs it. In a probe
    reproducing this module's exact call shape the spawned program executed and
    wrote its marker, and ``git add`` returned 0 with empty stderr. Worse, the
    two follow-up diffs also returned 0 and produced ~1.6 kB of plausible diff,
    so the attempt continued to ``STATE_CLEAN`` and returned an ordinary
    ``AttemptResult`` with no error field. Nothing would have been noticed.

    Three properties close it, and all three are needed:

    1. ``--git-dir``/``--work-tree`` ON THE COMMAND LINE. A candidate can
       rewrite ``<worktree>/.git`` -- ``open(p, "w")`` fails on the hidden file
       but ``open(p, "r+")`` succeeds -- to point at a gitdir it authored,
       whose config then supplies arbitrary filter commands. Measured: a
       from-scratch static gitdir is enough, so the attack needs NO prior code
       execution, only bytes a patch can carry. Naming the real admin directory
       explicitly makes that pointer irrelevant, and the caller reads it BEFORE
       any candidate code has run.
    2. :func:`_git_env`, so the system and user config cannot supply a filter.
    3. :data:`_GIT_EXEC_CONFIG` pinned with ``-c``, which no config file can
       override, for the keys that name a program directly.

    WHY NOT CONTAINMENT INSTEAD. This runs in the PARENT process, before the
    gate, and the plan of containing only the gate leaves it entirely open. The
    attack also needs only worktree-local writes plus reads, and
    ``daedalus.spine.containment`` states ``CONFIDENTIALITY: NONE`` -- a
    write-contained candidate can still read and still plant these bytes.
    """
    args = [str(a) for a in args]
    if not args:
        raise ValueError("_git requires at least a verb")
    verb = args[0]
    if verb.startswith("-"):
        raise ValueError(f"_git expects the verb first, got {verb!r}")
    cwd_path = Path(cwd).resolve()
    repo_path = Path(repo_root).resolve()
    if verb not in READ_ONLY_REPO_VERBS:
        overlap = _overlap_reason(cwd_path, repo_path)
        if overlap is not None:
            raise PrimaryCheckoutWrite(
                f"refusing to run 'git {verb}' in {cwd_path}, which overlaps "
                f"the primary checkout {repo_path} ({overlap}): an attempt may "
                f"only read there. Candidate changes belong in the isolated "
                f"worktree; promotion is a human act outside this module."
            )
    # THE ONE DELIBERATE EXCEPTION, and it is narrowed so it cannot be reused.
    # `_inherited_config_args` has to read the operator's REAL config -- that is
    # the whole question it asks -- and the hardened environment exists to hide
    # exactly that. So the exception is allowed only for a `config` read, which
    # cannot write and cannot execute anything. Any other verb asking for it is
    # a bug in this module, so it raises rather than degrading.
    if not harden and verb != "config":
        raise ValueError(
            f"harden=False is only for reading git config, not 'git {verb}'")
    pre: list[str] = []
    if harden and git_dir is not None:
        pre += [f"--git-dir={Path(git_dir)}"]
    if harden and work_tree is not None:
        pre += [f"--work-tree={Path(work_tree)}"]
    if harden:
        # Content semantics first, execution pinning second: a later -c wins, so
        # the exec pins can never be undone by an inherited value.
        pre += list(_inherited_config_args())
        for kv in _GIT_EXEC_CONFIG:
            pre += ["-c", kv]
    # ONE subprocess call in this module, and a test asserts there is exactly
    # one -- a second would be a way around the primary-checkout guard above.
    # `harden` therefore changes the ARGUMENTS to this call, never whether the
    # call goes through here.
    proc = subprocess.run(["git", *pre, *args], cwd=str(cwd_path),
                          capture_output=True, timeout=timeout,
                          env=_git_env() if harden else None)
    if check and proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", "replace").strip()
        raise GitCommandError(
            f"git {' '.join(args)} failed in {cwd_path} "
            f"(exit {proc.returncode}): {detail or 'no stderr'}")
    return proc


# --------------------------------------------------------------------------- #
# records                                                                      #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TaskSpec:
    """What is being attempted. Immutable, and digestible into an effect key."""

    task_id: str
    instruction: str
    base_revision: str | None = None
    gate_paths: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)
    # Empty values preserve the original/manual harness: no declared target
    # scope means the attempt is unconstrained, and no command argv means the
    # existing pytest gate derived from ``gate_paths`` is used.
    target_paths: tuple[str, ...] = ()
    gate_argv: tuple[str, ...] = ()
    gate_cwd: str = "."
    gate_timeout_s: float = DEFAULT_GATE_TIMEOUT_S
    # SWE-bench's FAIL_TO_PASS / PASS_TO_PASS schema (docs/ABSORPTION.md F1),
    # a per-task discrimination criterion instead of "the whole suite is
    # green": node ids that must go from failing to passing, and node ids that
    # must stay passing. Empty (the default) means no correctness task is
    # declared and the gate falls through to gate_argv/gate_paths exactly as
    # before -- see the precedence note on TaskAttempt.__init__.
    #
    # ``correctness_before_state`` is the FROZEN, PRE-VERIFIED receipt these
    # lists were measured under (the shape ``daedalus.eval.correctness.
    # seed_task_from_commit``/the correctness corpus already produces:
    # ``verified``, ``base_revision``, ``selection_digest``, per-node status
    # maps). It is carried here, not re-derived, because the candidate's
    # worktree already has the patch applied by the time a gate runs -- the
    # before-state CANNOT be measured there, only checked against a receipt
    # made earlier. Present but unverified/mismatched is refused at gate time
    # by ``daedalus.eval.correctness.correctness_gate`` itself, never treated
    # as passing; that fail-closed behaviour is the existing, tested one, not
    # reimplemented here.
    fail_to_pass: tuple[str, ...] = ()
    pass_to_pass: tuple[str, ...] = ()
    #: Paths INSIDE the candidate tree that state this task's gate criterion.
    #: Declared, never inferred, and joined to body() so it is inside the task
    #: digest -- a criterion that could be widened after the fact would be no
    #: criterion. Empty keeps today's behaviour exactly.
    gate_criterion_paths: tuple[str, ...] = ()
    #: This gate is DECLARED to be a conformance test of the task's own write
    #: scope -- a FAIL_TO_PASS test that imports the code the candidate writes,
    #: which is what such a test is for. It relaxes exactly one of the six
    #: criterion-seal checks (an in-tree import that lands inside the scope);
    #: the criterion file itself and everything on its collection path must
    #: still be outside the scope. Joined to body() when set, so the permission
    #: is inside the task digest and cannot be granted after the fact.
    gate_reads_scope: bool = False
    correctness_before_state: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Settle the declared paths into one normal form, or refuse the task.

        THE DECLARATION HAD MORE READERS THAN THE REFUSAL. ``target_paths`` was
        accepted as any string at construction and only checked at the
        containment boundary, so the picker's policy pre-check, the runner's
        ``paths`` argument, ``writable_paths`` on the receipt, and the task
        digest all saw the raw spelling while only the gate turned it away.
        Normalising here gives every one of those readers the same answer, and
        makes the digest a function of the LOCATION rather than of how it
        happened to be typed.
        """

        from daedalus.spine.receipts import normalise_declared_paths

        for field_name in ("target_paths", "gate_criterion_paths"):
            try:
                settled = normalise_declared_paths(
                    getattr(self, field_name) or (), field=field_name)
            except ValueError as exc:
                raise TaskSpecInvalid(f"task {self.task_id!r}: {exc}") from None
            object.__setattr__(self, field_name, settled)

    def body(self) -> dict:
        """The canonical, JSON-safe view -- the thing that gets digested."""
        body = {
            "task_id": str(self.task_id),
            "instruction": str(self.instruction),
            "base_revision": self.base_revision,
            "gate_paths": [str(p) for p in self.gate_paths],
            "metadata": _jsonable(dict(self.metadata)),
        }
        # Preserve every legacy TaskSpec digest/effect key byte-for-byte.
        # Curated fields join the canonical body only when that task actually
        # declares them.
        if self.target_paths:
            body["target_paths"] = [str(p) for p in self.target_paths]
        if self.gate_argv:
            body["gate"] = {
                "argv": [str(arg) for arg in self.gate_argv],
                "cwd": str(self.gate_cwd),
                "timeout_s": float(self.gate_timeout_s),
            }
        if self.fail_to_pass or self.pass_to_pass:
            body["correctness"] = {
                "fail_to_pass": [str(t) for t in self.fail_to_pass],
                "pass_to_pass": [str(t) for t in self.pass_to_pass],
                "before_state": _jsonable(dict(self.correctness_before_state)),
            }
        if self.gate_criterion_paths:
            body["gate_criterion_paths"] = [str(p) for p in self.gate_criterion_paths]
        if self.gate_reads_scope:
            body["gate_reads_scope"] = True
        return body

    @property
    def digest(self) -> str:
        return _sha256_text(canonical_json(self.body()))


@dataclass(frozen=True)
class RunnerContext:
    """Everything an injected runner or gate is given.

    There is no ``repo_root`` field, and that absence is load-bearing: a runner
    that cannot name the primary checkout cannot write it by accident.
    """

    worktree: Path
    branch: str
    base_revision: str
    task: TaskSpec
    is_cancelled: Callable[[], bool]


@dataclass(frozen=True)
class GateResult:
    """A gate verdict with its raw output kept, not summarised."""

    passed: bool
    name: str = "gate"
    command: tuple[str, ...] = ()
    returncode: int | None = None
    output: str = ""
    duration_s: float = 0.0
    cancelled: bool = False
    timed_out: bool = False
    #: EFFECTIVE containment, not the request -- see
    #: :class:`daedalus.spine.containment.ContainmentAttestation`. A verdict on
    #: candidate code is only worth as much as the boundary it ran behind, so
    #: the boundary that ACTUALLY held travels with the verdict into the ledger.
    #: ``None`` only for a gate result some other code path constructed.
    containment: "ContainmentAttestation | None" = None

    @property
    def output_sha256(self) -> str:
        return _sha256_text(self.output)

    def summary(self) -> dict:
        """The trimmed view written to the ledger (see GATE_OUTPUT_TAIL_CHARS)."""
        tail = self.output[-GATE_OUTPUT_TAIL_CHARS:]
        return {
            "name": self.name,
            "passed": bool(self.passed),
            "returncode": self.returncode,
            "command": list(self.command),
            "duration_s": round(self.duration_s, 3),
            "cancelled": bool(self.cancelled),
            "timed_out": bool(self.timed_out),
            "output_sha256": self.output_sha256,
            "output_chars": len(self.output),
            "output_tail": tail,
            "output_truncated": len(tail) < len(self.output),
            "containment": (self.containment.summary()
                            if self.containment is not None else None),
        }


@dataclass(frozen=True)
class PatchArtifact:
    """A candidate change as inert data. Nothing here applies itself.

    ``diff_bytes`` is authoritative and ``diff_sha256`` is taken over it; a
    human promoting the patch should write those bytes, not the decoded
    ``diff``, because a decode round-trip can corrupt a diff containing bytes
    that are not valid UTF-8.
    """

    task_id: str
    branch: str
    base_revision: str
    diff_bytes: bytes
    diff_sha256: str
    changed_paths: tuple[str, ...]
    created_ts: str

    @property
    def diff(self) -> str:
        """Convenience view for humans and logs; not the digested form."""
        return self.diff_bytes.decode("utf-8", "replace")

    @property
    def is_empty(self) -> bool:
        return not self.diff_bytes

    @property
    def byte_length(self) -> int:
        return len(self.diff_bytes)

    def summary(self) -> dict:
        return {
            "task_id": self.task_id,
            "branch": self.branch,
            "base_revision": self.base_revision,
            "diff_sha256": self.diff_sha256,
            "changed_paths": list(self.changed_paths),
            "byte_length": self.byte_length,
            "created_ts": self.created_ts,
        }


@dataclass(frozen=True)
class AttemptResult:
    """The complete, exception-free outcome of one attempt."""

    state: str
    task_id: str
    started_ts: str
    finished_ts: str
    duration_s: float
    effect_key: str
    branch: str
    base_revision: str | None = None
    intent_id: int | None = None
    artifact: PatchArtifact | None = None
    gates: GateResult | None = None
    error: str | None = None
    worktree_path: str | None = None
    worktree_removed: bool = False
    cleanup_error: str | None = None
    ledger_error: str | None = None
    artifact_path: str | None = None
    artifact_locator: dict[str, Any] | None = None
    persist_error: str | None = None
    runner_detail: Any = None
    reaped: tuple = ()
    reap_error: str | None = None
    #: The handed attempt lease's identity, terminal outcome, and any error the
    #: lease bookkeeping hit. Reported, never raised: losing a finished result
    #: to lease bookkeeping would be worse than a missing receipt row.
    lease_id: str | None = None
    lease_outcome: str | None = None
    lease_error: str | None = None
    #: The canonical Gate-0 projection of this attempt --
    #: ``AttemptContract`` / ``EvidencePacket`` / ``AttemptReceipt`` plus the
    #: ``PolicyDecision`` and ``RuntimeManifest`` they bind -- as the wire dict
    #: written to the spine ledger. See :mod:`daedalus.spine.receipts`. ``None``
    #: only for the early refusals that never reached the ledger at all.
    contracts: dict[str, Any] | None = None
    #: Why the canonical projection is incomplete, when it is. An attempt is
    #: never failed for this: losing a gated candidate because its projection
    #: could not be built would be strictly worse than reporting the gap.
    contracts_error: str | None = None

    @property
    def ok(self) -> bool:
        """True only for a real, gated candidate. ``no_change`` is not ok."""
        return self.state == STATE_CLEAN

    @property
    def has_artifact(self) -> bool:
        return self.artifact is not None

    def to_dict(self) -> dict:
        """JSON-safe view. Carries the gate SUMMARY, not the full log."""
        return {
            "state": self.state,
            "task_id": self.task_id,
            "started_ts": self.started_ts,
            "finished_ts": self.finished_ts,
            "duration_s": round(self.duration_s, 3),
            "effect_key": self.effect_key,
            "branch": self.branch,
            "base_revision": self.base_revision,
            "intent_id": self.intent_id,
            "artifact": self.artifact.summary() if self.artifact else None,
            "gates": self.gates.summary() if self.gates else None,
            "error": self.error,
            "worktree_path": self.worktree_path,
            "worktree_removed": self.worktree_removed,
            "cleanup_error": self.cleanup_error,
            "ledger_error": self.ledger_error,
            "artifact_path": self.artifact_path,
            "artifact_locator": _jsonable(self.artifact_locator),
            "persist_error": self.persist_error,
            "runner_detail": _jsonable(self.runner_detail),
            "reaped": _jsonable(list(self.reaped)),
            "reap_error": self.reap_error,
            "lease_id": self.lease_id,
            "lease_outcome": self.lease_outcome,
            "lease_error": self.lease_error,
            "contracts": _jsonable(self.contracts),
            "contracts_error": self.contracts_error,
        }

    def contract_set(self) -> "Any":
        """Read this attempt's canonical records back as contracts, not dicts.

        The consuming half of the wiring lives here so a caller never has to
        interpret the projection by hand: a tampered or malformed record fails
        to reconstruct instead of quietly reappearing as a plausible object.
        """
        from daedalus.spine.receipts import AttemptContractSet

        if self.contracts is None:
            return None
        return AttemptContractSet.from_dict(self.contracts)


# --------------------------------------------------------------------------- #
# default gate                                                                 #
# --------------------------------------------------------------------------- #
def pytest_gate_argv(paths: Sequence[str] = ()) -> tuple[str, ...]:
    """The gate command line, as a pure function so it is assertable.

    ``-p no:cacheprovider`` keeps pytest from writing ``.pytest_cache`` into the
    candidate worktree; the patch is captured before gates run, but a gate that
    dirties the tree it is judging is a trap worth not setting.
    """
    return (sys.executable, "-m", "pytest", *[str(p) for p in paths],
            "-q", "-p", "no:cacheprovider")


def _remove_gate_tmpdir(
    tmpdir: Path,
    cleanup: ScratchCleanupPort,
) -> str | None:
    """Delete the gate's scratch directory through the GUARDED walker.

    Returns ``None`` on success, or a one-line report of what stopped it.

    WHY NOT ``shutil.rmtree(tmpdir, ignore_errors=True)``, which is what this
    was. Two reasons, and only the second one is about reparse points:

    1. ``ignore_errors=True`` is a SILENT delete failure in a ``finally:``. A
       recursive delete this module cannot complete is exactly the thing the
       rest of this file refuses to swallow (see ``cleanup_worktree``, whose
       failures are raised), so it is reported here and appended to the gate's
       own output rather than discarded.
    2. ``tmpdir`` is ``%TEMP%/daedalus-gate-*``, created while candidate code is
       running as THIS user with THIS user's privileges, and the prefix is a
       public constant in this file. Candidate code can therefore create paths
       inside it. Measured on this box (CPython 3.10.11): ``shutil.rmtree`` is
       safe against a junction that is ALREADY in place, and unsafe against one
       renamed in mid-walk, because its check reads the Windows ``scandir``
       stat cache and never refreshes it -- with the victim in the last entry
       position it destroyed the target 3/3.

    THE CONTAINMENT THAT IS NOT WRITTEN DOWN ANYWHERE ELSE, so it is written
    here: the gate child runs under
    :class:`daedalus.spine.cancel.ManagedProcess`, i.e. inside a Windows Job
    Object with ``KILL_ON_JOB_CLOSE``, and ``release()`` runs on the ``with``
    exit BEFORE this function is reached -- so by the time this deletes, the
    candidate's test process tree is normally already dead. Cerberus could not
    demonstrate a live candidate at this point (two job-escape attempts failed
    on this box). That is a reason to believe the window is small; it is not a
    reason to leave an unguarded recursive delete behind it, because "the
    process was probably dead" is not a property this module can check, and a
    Job Object is not a filesystem guard -- anything the candidate planted
    while it WAS alive is still on disk when this runs.
    """
    try:
        cleanup(tmpdir)
        return None
    except Exception as e:                      # noqa: BLE001 - reported, not raised
        return (f"[gate scratch directory {tmpdir} was NOT removed: "
                f"{type(e).__name__}: {e}]")


def _poll_until_done(proc: Any, ctx: RunnerContext, started: float,
                     timeout_s: float | None,
                     poll_s: float) -> tuple[bool, bool, Any]:
    """Poll one gate child, honouring the cancel token and the deadline.

    Returns ``(cancelled, timed_out, returncode)``.

    POLLING RATHER THAN READING IS WHY OUTPUT GOES TO A FILE. With a pipe this
    loop would have to drain it; a chatty child fills the pipe buffer and
    blocks while we are asking the cancel token, so the attempt becomes
    uncancellable at exactly the moment cancelling matters. Shared by both
    spawn paths so the contained and uncontained children are cancelled by the
    same code -- a second copy is a second place for that deadlock to reappear.
    """
    cancelled = False
    timed_out = False
    deadline = None if timeout_s is None else started + float(timeout_s)
    while proc.poll() is None:
        if ctx.is_cancelled():
            proc.cancel()
            cancelled = True
            break
        if deadline is not None and time.monotonic() > deadline:
            proc.cancel()
            timed_out = True
            break
        time.sleep(poll_s)
    return cancelled, timed_out, proc.returncode


def _contained_gate_child(argv: Sequence[str], worktree: Path, out_path: Path,
                          tmpdir: Path):
    """Launch the gate at Low integrity. Raises ``ContainmentUnavailable``.

    Three things are set up, and each is a measured requirement rather than
    tidiness:

    1. THE WORKTREE IS LABELLED LOW, because a contained child that cannot
       write the tree it is testing is an outage, not a boundary.
    2. A LOW-LABELLED TEMP DIRECTORY, inside the gate's own scratch tree and
       NOT inside the worktree. A Low child cannot write %TEMP% (Medium), and
       pointing TEMP at the worktree would dirty the tree the gate is judging.
       The scratch tree is removed afterwards through the guarded walker, which
       is exactly the delete-against-attacker-reachable-ground that guard is
       for -- this directory is now writable by candidate code by design.
    3. THE OUTPUT FILE IS CREATED AND LABELLED BY US, then opened append-only,
       and exactly that one handle is allowlisted into the child. See
       :mod:`daedalus.spine.containment` for what was measured about each of
       those words.
    4. NO PROMOTION SECRET REACHES THE CHILD. Phase-0 case A9a measured a plain
       child reading ``DAEDALUS_OWNER_APPROVAL_SECRET_CANARY`` straight out of
       an inherited environment. This is the process that runs CANDIDATE CODE,
       so it is the one child for which that leak is not a hypothetical: a
       candidate that can read the approval secret can mint the approval for
       its own promotion. The D5 root needs no secret to verify, and after this
       neither does anything the child can see.
    """
    from daedalus.kernel.promotion_trust_root import scrubbed_child_env
    from daedalus.spine import containment

    containment.label_low_integrity(worktree)
    worktree_label = containment.integrity_label(worktree)
    low_temp = tmpdir / "lowtemp"
    low_temp.mkdir()
    containment.label_low_integrity(low_temp)

    log = containment.open_low_append_log(out_path)
    try:
        env = scrubbed_child_env()
        env["TEMP"] = env["TMP"] = str(low_temp)
        proc = containment.spawn_contained(
            argv, cwd=worktree, env=env, log=log,
            worktree_label=worktree_label)
    except BaseException:
        log.close()
        raise
    return proc, log


def _command_gate(argv: Sequence[str], *,
                  scratch_cleanup: ScratchCleanupPort,
                  timeout_s: float | None = DEFAULT_GATE_TIMEOUT_S,
                  poll_s: float = 0.25,
                  name: str = "command",
                  executes_candidate: bool = True,
                  ) -> Callable[[RunnerContext], GateResult]:
    """Run an arbitrary command INSIDE the candidate worktree.

    THE GATE IS WHERE CANDIDATE CODE ACTUALLY RUNS. Everything else in this
    module handles the candidate's bytes; this command executes them. So by
    default the child is launched at LOW INTEGRITY through
    :mod:`daedalus.spine.containment`, and the kernel -- not our path checks --
    refuses the writes that a Python guard provably cannot close (the "move-in"
    attack among them).

    THERE IS NO ``contained=False``. A caller whose runner cannot produce
    candidate code says so with ``executes_candidate=False``, which is a
    statement about the WORKLOAD and reads as one in a diff. A security toggle
    would read as a knob, and the first person in a hurry would turn it. When
    containment cannot be established -- wrong platform, labelling refused, a
    handle that would not verify -- the gate REFUSES: ``passed=False`` with the
    reason in the output and in the attestation. It never downgrades to an
    uncontained run that looks like a contained one.

    Both children run inside a Job Object with ``KILL_ON_JOB_CLOSE``, so a
    cancelled attempt kills the whole process TREE rather than the immediate
    child -- a leaked test process still writing into a worktree that is about
    to be removed is a correctness hazard, not untidiness.

    Output goes to a file OUTSIDE the worktree: a pipe would deadlock on a
    chatty run while we are polling the cancel token instead of reading. Under
    containment that file is the ONE handle inherited by the child, opened
    append-only on a Low-labelled target and verified on the handle.

    That scratch directory is then removed through the GUARDED walker, not
    ``shutil.rmtree`` -- it lives in ``%TEMP%`` under a prefix named in this
    file while candidate code is running as this user, so it is a delete
    against attacker-reachable ground like every other delete in this system.
    See :func:`_remove_gate_tmpdir`, which also records what the Job Object
    does and does not contain.
    """
    if not callable(scratch_cleanup):
        raise AttemptPortMissing(
            "command gate requires an injected scratch-cleanup port"
        )
    effective_argv = tuple(str(arg) for arg in argv)

    def _gate(ctx: RunnerContext) -> GateResult:
        from daedalus.spine import containment
        from daedalus.spine.cancel import CancellationUnavailable, ManagedProcess

        started = time.monotonic()
        tmpdir = Path(tempfile.mkdtemp(prefix="daedalus-gate-"))
        out_path = tmpdir / "gate.out"
        cancelled = False
        timed_out = False
        returncode: int | None = None
        refusal: str | None = None
        output = ""
        attestation = containment.ContainmentAttestation(
            requested=bool(executes_candidate),
            executes_candidate=bool(executes_candidate),
            contained=False, platform=sys.platform, mechanism="none",
            reason=(None if executes_candidate else
                    "the caller declared this gate does not execute candidate "
                    "code, so no containment was requested"))
        try:
            if executes_candidate:
                try:
                    proc, log = _contained_gate_child(effective_argv, ctx.worktree,
                                                      out_path, tmpdir)
                except containment.ContainmentUnavailable as e:
                    # HARD REFUSAL. A gate that runs candidate code outside the
                    # boundary makes the boundary decorative, and a green
                    # verdict from it would be worth nothing.
                    refusal = (f"gate refused to execute candidate code "
                               f"without MIC write containment: {e}")
                    attestation = containment.refusal_attestation(str(e))
                else:
                    attestation = proc.attestation
                    try:
                        with proc:
                            cancelled, timed_out, returncode = _poll_until_done(
                                proc, ctx, started, timeout_s, poll_s)
                    finally:
                        # BEFORE the output is read and before the scratch tree
                        # is deleted: while this handle is open the share mode
                        # keeps every other opener out, including ours.
                        log.close()
            else:
                with open(out_path, "wb") as fh:
                    try:
                        proc = ManagedProcess(effective_argv, cwd=ctx.worktree,
                                              stdout=fh,
                                              stderr=subprocess.STDOUT)
                    except CancellationUnavailable as e:
                        refusal = (f"gate refused to launch outside a killable "
                                   f"container: {e}")
                    else:
                        with proc:
                            cancelled, timed_out, returncode = _poll_until_done(
                                proc, ctx, started, timeout_s, poll_s)
            if refusal is None:
                output = out_path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            output = f"gate output could not be captured: {e}"
        finally:
            # Guarded, and REPORTED -- see _remove_gate_tmpdir. A scratch
            # directory that could not be removed appends to the gate's output
            # instead of vanishing; it never changes the verdict, because
            # whether the scratch dir survived says nothing about the candidate.
            scratch_error = scratch_cleanup(tmpdir)
        if refusal is not None:
            return GateResult(passed=False, name=name, command=effective_argv,
                              returncode=None, output=refusal,
                              duration_s=time.monotonic() - started,
                              containment=attestation)
        passed = returncode == 0 and not cancelled and not timed_out
        # NO EMPTY GREEN. A gate that exits 0 having produced NOTHING has not
        # judged anything -- something ate the evidence. This is not
        # hypothetical: with the log handle opened without FILE_READ_ATTRIBUTES
        # (the first, stricter mask), os.fstat(1) raised, pytest concluded fd 1
        # was invalid, redirected everything to os.devnull, and exited 0. The
        # verdict was PASS and the report was zero bytes. The mask was fixed;
        # this stays, because the next thing to blind the channel will not
        # announce itself either, and a green with no evidence must fail.
        if passed and not output.strip():
            passed = False
            output = ("gate exited 0 but produced NO output: the evidence "
                      "channel is broken, so there is no verdict here to "
                      "trust. Refusing to report a pass nothing was written "
                      "for.")
        if scratch_error:
            output = f"{output}\n{scratch_error}"
        return GateResult(passed=passed, name=name, command=effective_argv,
                          returncode=returncode, output=output,
                          duration_s=time.monotonic() - started,
                          cancelled=cancelled, timed_out=timed_out,
                          containment=attestation)

    return _gate


def offload_runner(
    *,
    offload_port: OffloadPort | None = None,
    **offload_kwargs: Any,
) -> Callable[[RunnerContext], Any]:
    """Opt-in runner backed by an INJECTED ``offload`` capability.

    ``repo_root`` is pinned to the WORKTREE, so offload's snapshot / verify /
    rollback machinery operates entirely inside the isolated checkout.

    Deliberately not the default: :class:`TaskAttempt` refuses to construct
    without an explicit runner, so no attempt can quietly reach a model because
    a caller forgot an argument. The ``offload`` capability now obeys the same
    rule, one layer down, for the same reason.

    THE PORT, NOT AN IMPORT (G1-SCC-CUT1). ``daedalus.offload`` is a WORKLOAD
    and the kernel sits below it; importing it here was the repository's single
    recorded boundary violation (the ``baseline`` entry of
    ``docs/architecture/import-boundaries.json``, retired by this packet).
    Composition moved to layers that may legally name the workload:
    ``daedalus.orchestration.execution.offload_port`` for the picker and
    bootstrap doors, and ``daedalus.kairos.gated_writes`` for the write wave.

    The symbol does NOT move. G1-HIER-07A rejected this edge for carrying "the
    exact public offload_runner identity" -- that objection is about relocating
    the name, which would break the facade-identity assertions in
    ``tests/kernel/test_attempt_execution_hierarchy.py``. Only the thing this
    function CALLS is handed in; ``daedalus.spine.attempt.offload_runner`` is
    still this exact object.

    Refuses at COMPOSITION time rather than at runner-invocation time: a caller
    that forgot the port learns about it before a worktree, a branch or a
    provider call exists, instead of halfway through an attempt.

    The port is an :class:`OffloadPort`, not a bare callable, so that the effect
    derivation can still follow this door into the workload it reaches. See that
    class for why the annotation is load-bearing.
    """
    if not isinstance(offload_port, OffloadPort):
        raise AttemptPortMissing(
            "offload_runner requires an injected OffloadPort; the kernel does "
            "not import the daedalus.offload workload. Compose it with "
            "daedalus.orchestration.execution.offload_port()"
        )

    def _runner(ctx: RunnerContext) -> Any:
        kwargs = dict(offload_kwargs)
        kwargs.pop("repo_root", None)
        if ctx.task.target_paths:
            # The curated queue's declared scope is not merely ledger
            # metadata: it must steer routing and context construction too.
            # A caller-supplied value cannot widen it.
            kwargs["paths"] = list(ctx.task.target_paths)
        kwargs["_attempt_workspace"] = {
            "worktree": str(ctx.worktree.resolve()),
            "branch": ctx.branch,
            "base_revision": ctx.base_revision,
        }
        return offload_port.run_offload(
            ctx.task.instruction, str(ctx.worktree), **kwargs
        )
    return _runner


# --------------------------------------------------------------------------- #
# the attempt                                                                  #
# --------------------------------------------------------------------------- #
class TaskAttempt:
    """Kernel-owned lifecycle core for one checkout-external candidate.

    The registered ``run`` effect door is supplied by
    :mod:`daedalus.spine.attempt`.  Keeping admission at that facade preserves
    the Effect Registry target while this class owns the post-admission
    lifecycle, workspace interaction, evidence, replay, and cleanup behavior.
    """

    def __init__(self, task: TaskSpec, *,
                 runner: Callable[[RunnerContext], Any],
                 repo_root: str | Path | None = None,
                 gate: Callable[[RunnerContext], Any] | None = None,
                 ledger: SpineLedger | None = None,
                 ledger_path: str | Path | None = None,
                 cancel: Any = None,
                 worktree_manager: AttemptWorkspacePort | None = None,
                 workspace_port: AttemptWorkspacePort | None = None,
                 evaluator_port: AttemptEvaluatorPort | None = None,
                 keep_worktree: bool = False,
                 reap: bool = True,
                 artifact_dir: str | Path | None = None,
                 mission_id: str | None = None,
                 campaign_id: str | None = None,
                 budget: "ResourceBudget | None" = None,
                 spend_grant_microusd: int = 0,
                 mission_policy_sha256: str = "",
                 attempt_lease: Any = None,
                 execution_limit_policy: ExecutionLimitPolicy | None = None) -> None:
        if not isinstance(task, TaskSpec):
            raise TypeError("task must be a TaskSpec")
        if runner is None or not callable(runner):
            raise ValueError(
                "TaskAttempt requires an explicit runner callable; there is no "
                "implicit model-backed default (use offload_runner() to opt in)")
        if ledger is not None and ledger_path is not None:
            raise ValueError("pass ledger or ledger_path, not both")
        if worktree_manager is not None and workspace_port is not None:
            raise ValueError(
                "pass workspace_port or legacy worktree_manager, not both"
            )
        selected_workspace = (
            workspace_port if workspace_port is not None else worktree_manager
        )
        if selected_workspace is None:
            raise AttemptPortMissing(
                "TaskAttempt requires an injected workspace_port; the kernel "
                "does not discover a Kairos worktree manager"
            )
        if task.gate_argv and str(task.gate_cwd) != ".":
            raise ValueError(
                "TaskSpec command gates currently require gate_cwd='.'; "
                "subdirectory execution is not implemented")
        resolved_limit_policy = (
            load_from_env()
            if execution_limit_policy is None
            else execution_limit_policy
        )
        if type(resolved_limit_policy) is not ExecutionLimitPolicy:
            raise ValueError(
                "execution_limit_policy must be an exact ExecutionLimitPolicy"
            )
        self.execution_limit_policy = ExecutionLimitPolicy.from_dict(
            resolved_limit_policy.as_dict()
        )
        self.task = task
        self.repo_root = Path(repo_root).resolve() if repo_root else ROOT
        self._runner = runner
        effective_gate_timeout = (
            float(task.gate_timeout_s)
            if self.execution_limit_policy.enforces("wall_time")
            else None
        )
        if gate is not None:
            self._gate = gate
        elif task.gate_argv:
            if evaluator_port is None or not callable(
                getattr(evaluator_port, "command_gate", None)
            ):
                raise AttemptPortMissing(
                    "TaskAttempt command gate requires an evaluator_port"
                )
            self._gate = evaluator_port.command_gate(
                task.gate_argv,
                timeout_s=effective_gate_timeout,
                name="queue-command")
        elif task.fail_to_pass or task.pass_to_pass:
            # FAIL_TO_PASS/PASS_TO_PASS beats the plain pytest_gate default but
            # loses to an explicit gate/gate_argv override, matching the
            # existing "explicit beats implicit" precedence above.  The
            # evaluator remains independently owned; the kernel only invokes
            # the injected neutral capability.
            if evaluator_port is None or not callable(
                getattr(evaluator_port, "correctness_gate", None)
            ):
                raise AttemptPortMissing(
                    "TaskAttempt correctness criteria require an evaluator_port"
                )
            self._gate = evaluator_port.correctness_gate(
                task,
                self.repo_root,
                timeout_s=effective_gate_timeout)
        else:
            # Keep the legacy bounded call shape byte-for-byte: callers and
            # tests rely on the gate factory's canonical default.  Revision 10
            # only needs to spell the disabled axis explicitly.
            if evaluator_port is None or not callable(
                getattr(evaluator_port, "pytest_gate", None)
            ):
                raise AttemptPortMissing(
                    "TaskAttempt default gate requires an evaluator_port"
                )
            use_default_timeout = self.execution_limit_policy.enforces("wall_time")
            self._gate = evaluator_port.pytest_gate(
                task.gate_paths,
                timeout_s=effective_gate_timeout,
                use_default_timeout=use_default_timeout,
            )
        self._manager = selected_workspace
        self._is_cancelled = _as_predicate(cancel)
        self._keep_worktree = bool(keep_worktree)
        # Default ON because the leak is unbounded: one ref per attempt, in the
        # SHARED .git, forever. Off is for an operator who wants the branch left
        # behind for forensics -- the patch bytes are already persisted
        # separately, so this costs nothing but a ref.
        self._reap_enabled = bool(reap)
        # The attempt CONSUMES a python.attempt Effect Lease it was handed --
        # acquire_attempt_lease is the issuer and the CALLER calls it (the
        # entrypoint never discovers a capability; the scheduler rule, applied
        # here). Duck-typed on the two members used, so a test double works;
        # None means the pre-lease behaviour, unchanged.
        self._attempt_lease = attempt_lease
        self._lease_start = None
        self._lease_execution = None
        self._worktree_decision = None
        self._artifact_dir = Path(artifact_dir) if artifact_dir else None
        self._ledger = ledger
        self._ledger_path = Path(ledger_path) if ledger_path is not None else None
        self._owns_ledger = ledger is None
        # Derived from the task, plus a nonce so a retry of the SAME task does
        # not collide with the branch its predecessor left behind (and so
        # resolve_by_effect can tell two attempts apart in the world).
        self.branch = (f"{BRANCH_PREFIX}-{_slug(task.task_id)}-"
                       f"{task.digest[:8]}-{uuid.uuid4().hex[:6]}")
        self.effect_key = self.branch
        #: The ``begin_effect`` receipt for THIS attempt, set by :meth:`run`
        #: before any effect. ``None`` means the boundary was never entered --
        #: which, since :meth:`run` is the only way to perform anything here,
        #: means nothing was performed.
        self._boundary_receipt = None
        # CANONICAL IDENTITY (see daedalus.spine.receipts). The attempt id IS
        # the effect key: one string names the branch in the world, the ledger
        # row, and the AttemptContract, so no join table can drift.
        #
        # ``mission_id`` defaults to a value DERIVED from the task rather than
        # a fresh uuid, so two attempts at the same task under the same missing
        # mission land under the same mission id instead of inventing a new
        # mission per attempt. A caller that has a real MissionContract passes
        # its id and this default never applies.
        self.attempt_id = self.branch
        self.mission_id = str(mission_id) if mission_id else (
            f"mission-{_slug(task.task_id)}-{task.digest[:12]}")
        self.campaign_id = str(campaign_id) if campaign_id else None
        # The budget the CONTRACT declares. The default binds the one execution
        # bound this class actually enforces -- the gate timeout -- and binds
        # nothing else. It deliberately does NOT declare a token or cost
        # ceiling: this spine measures neither, and a ceiling nothing measures
        # is a claim, not a bound.
        self.budget = budget if budget is not None else ResourceBudget(
            max_wall_time_s=int(float(task.gate_timeout_s)))
        self.spend_grant_microusd = int(spend_grant_microusd)
        # The policy digest the MissionContract this attempt serves was compiled
        # against. Empty by default and never invented here: a caller that holds
        # a real mission passes its `policy_sha256`, and the canonical
        # projection then refuses to mint a chain whose mission and attempt name
        # two different policy texts. With it empty the projection still
        # compares the attempt's own decision against the declared registry, so
        # a registry that moved mid-attempt is caught either way.
        self.mission_policy_sha256 = str(mission_policy_sha256 or "")
        # Filled in by run() from the fresh worktree, BEFORE the runner is
        # invoked. None until then, and None afterwards for a worktree whose
        # `.git` was not the expected pointer file.
        self._admin_dir: Path | None = None

    def _close_ledger(self, ledger: SpineLedger) -> None:
        """Close the durable writer, but only when this attempt opened it.

        Extracted from ``run``'s old ``finally:`` unchanged, because the same
        two lines now have to run on the boundary-refusal returns as well as on
        the normal path -- and a second copy of "close it if we own it" is a
        second place for the ownership rule to drift.
        """
        if self._owns_ledger:
            try:
                ledger.close()
            except Exception:      # noqa: BLE001 - teardown may not fail a run
                pass

    def _released(self, ledger: SpineLedger,
                  result: AttemptResult) -> AttemptResult:
        """One early return: close the writer we own, then reap, then answer.

        The refusal paths above `_run_with_ledger` used to reach the shared
        ``finally``/``return`` tail by falling through. They now return, so the
        tail travels with them: same close, same reap, same order.
        """
        self._close_ledger(ledger)
        return self._reap(result)

    def _reap(self, result: AttemptResult) -> AttemptResult:
        """Delete this attempt's branch if the manager can prove it holds no work.

        NEVER fails the attempt. The patch has already been captured and the
        intent already resolved; losing a completed result to a bookkeeping
        error would be strictly worse than leaving a ref behind. A reap that
        could not run is REPORTED on the result instead, so a silently growing
        ref namespace stays observable.

        The decision itself is entirely the manager's, and deliberately so: it
        deletes only branches THIS manager allocated in THIS process, whose
        worktree has been through cleanup, and whose tip still matches the sha
        it read at allocation. None of those three facts is available to
        candidate code, which is why forging an allocation record on disk --
        the attack that once deleted two branches of real work -- cannot steer
        it. Passing `keep_worktree=True` therefore reaps nothing, because the
        cleanup precondition never becomes true.
        """
        from dataclasses import replace as _replace

        if not self._reap_enabled:
            return result
        try:
            report = self._manager.reap_branches()
        except Exception as e:                  # noqa: BLE001 - reported, not raised
            return _replace(result,
                            reap_error=f"{type(e).__name__}: {e}")
        return _replace(result, reaped=tuple(report))

    def _finish_lease_terminal(self, *, state_hint: str) -> tuple[str, str] | None:
        """Terminalise the handed lease's execution, once. Returns
        ``(outcome, error)`` with ``error == ""`` on success, or ``None`` when
        there is nothing to finish (no lease, or begin never happened).

        Outcome maps the EXECUTION, not the verdict: an attempt whose gate
        failed still ran its leased effect to a terminal state, so
        ``gates_failed`` is COMPLETED with the state in the detail; only the
        cancelled family is CANCELLED and everything that never produced a
        worktree or runner result is FAILED. Never raises.
        """
        lease, start = self._attempt_lease, self._lease_start
        if lease is None or start is None:
            return None
        self._lease_start = None            # exactly one terminal per start
        if state_hint == STATE_CANCELLED:
            outcome = "CANCELLED"
        elif state_hint in (STATE_CLEAN, STATE_NO_CHANGE, STATE_GATES_FAILED):
            outcome = "COMPLETED"
        else:
            outcome = "FAILED"
        execution, self._lease_execution = self._lease_execution, None
        try:
            detail = hashlib.sha256(
                f"attempt-state:{state_hint}".encode("ascii")).hexdigest()
            lease.authorization.finish_effect(
                start.receipt, outcome=outcome, detail_sha256=detail)
        except Exception as e:  # noqa: BLE001 - reported, never raised
            return outcome, f"{type(e).__name__}: {e}"
        # THE RECEIPT, not just the ledger row. `finish_effect` makes the
        # execution terminal in the effect ledger; until this call the
        # write-evidence store held a subject and an execution identity and
        # nothing saying either ended, so nothing outside the ledger could
        # trace the effect to its outcome. Retention is deliberately AFTER the
        # terminalisation and deliberately cannot fail it: the method reports
        # every refusal on the lease's own `evidence_errors` and returns None.
        if execution is not None:
            before = len(getattr(lease, "evidence_errors", ()) or ())
            lease.retain_terminal_record(execution)
            # A REFUSAL THAT ONLY THE LEASE OBJECT KNOWS ABOUT is a refusal
            # nobody reads. The disjointness retention already surfaces on the
            # result through `_lease_retention_error`; this one joins it, so a
            # store that is missing a terminal record says so where the attempt
            # is inspected and not only inside an object the caller may drop.
            fresh = list(getattr(lease, "evidence_errors", ()) or ())[before:]
            if fresh:
                existing = getattr(self, "_lease_retention_error", None)
                joined = "; ".join(fresh)
                self._lease_retention_error = (
                    f"{existing}; {joined}" if existing else joined
                )
        return outcome, ""

    def _attach_lease_terminal(self, result: AttemptResult) -> AttemptResult:
        """Report the lease identity and terminal outcome on the result."""
        from dataclasses import replace as _replace

        lease = self._attempt_lease
        if lease is None:
            return result
        finished = self._finish_lease_terminal(state_hint=result.state)
        retention = getattr(self, "_lease_retention_error", None)
        outcome: str | None
        error: str | None
        if finished is None:
            outcome, error = None, None
        else:
            outcome, error = finished[0], (finished[1] or None)
        if retention:
            error = f"{error}; {retention}" if error else retention
        return _replace(
            result,
            lease_id=str(getattr(lease, "lease_id", "") or "") or None,
            lease_outcome=outcome,
            lease_error=error,
        )

    # -- the recorded part -------------------------------------------------- #
    def _run_with_ledger(self, ledger: SpineLedger, base_revision: str,
                         finish: Callable[..., AttemptResult]) -> AttemptResult:
        # 2. intent BEFORE effect, committed by record_intent.
        payload = dict(self.task.body())
        payload.update({
            "resolved_base_revision": base_revision,
            "branch": self.branch,
            "repo_root": str(self.repo_root),
            "worktree_root": str(self._manager.worktree_root),
        })
        try:
            intent = ledger.record_intent(INTENT_KIND, payload,
                                          effect_key=self.effect_key)
        except Exception as e:
            return finish(STATE_WORKTREE_FAILED, base_revision=base_revision,
                          error=f"could not record intent: {e}")

        # 2b. THE LEASE BEGINS HERE, because the next statement is the
        # repository mutation it must cover: `git worktree add -b` writes the
        # branch ref into the shared .git (Momus item 6 -- granting after the
        # worktree would put the very writes the terminal record binds outside
        # the lease). The intent above is durable first, so a crash between
        # begin and the worktree leaves a findable effect key AND a durable
        # STARTED execution naming the same attempt.
        if self._attempt_lease is not None:
            try:
                execution = self._attempt_lease.execution_for(
                    1, writable_paths=tuple(self.task.target_paths or ()))
                start = self._attempt_lease.authorization.begin_effect(execution)
            except Exception as e:  # noqa: BLE001 - any refusal is terminal here
                return self._resolve_and_finish(
                    ledger, intent.id, finish, STATE_LEASE_REFUSED,
                    artifact=None, base_revision=base_revision,
                    error=f"the attempt lease refused to begin: {e}")
            if not start.execute:
                # A REPLAY, reported as a field, never as a raise: the ledger
                # answers "this execution identity already ran" by refusing to
                # run it again while returning the original receipt. Running
                # the attempt anyway would put fresh writes under the first
                # attempt's receipt (Momus item 5), so this is a refusal.
                return self._resolve_and_finish(
                    ledger, intent.id, finish, STATE_LEASE_REFUSED,
                    artifact=None, base_revision=base_revision,
                    error=(
                        "the attempt lease refused to begin: execution "
                        f"identity {start.receipt.execution_id} already ran "
                        "under this lease; a retry is a NEW attempt with a "
                        "NEW effect key, never a replay"))
            self._lease_start = start
            # THE EXACT EXECUTION THIS START COVERS, kept so the terminal
            # record binds the identity that actually ran instead of one
            # rediscovered by position later. `issued_execution(1)` would
            # answer today -- an attempt lease is pinned to one position -- and
            # would quietly bind the wrong row the day anything issues a
            # second.
            self._lease_execution = execution
            # The disjointness receipt RECORDS the containment.worktree
            # decision the boundary already took over the planned root.
            # Reported, never raised: retention must not revoke a capability
            # the ledger accepted (the issuer's own retention rule).
            try:
                from daedalus.kernel.offload_lease import (
                    record_primary_checkout_disjointness,
                )

                if self._worktree_decision is not None:
                    record_primary_checkout_disjointness(
                        self._worktree_decision,
                        primary_checkout=self.repo_root,
                        target_root=self._manager.worktree_root,
                        source_revision=base_revision,
                        evidence_root=self._attempt_lease.evidence_root,
                        control_root_path=self._attempt_lease.control_root_path,
                    )
            except Exception as e:  # noqa: BLE001 - reported on the result
                self._lease_retention_error = (
                    f"disjointness retention failed: {type(e).__name__}: {e}")

        # 3. isolated worktree (already outside the repo by construction).
        try:
            worktree = self._manager.create_worktree(base_revision, self.branch)
        except StorageUnavailable as e:
            return self._resolve_and_finish(
                ledger, intent.id, finish, STATE_STORAGE_UNAVAILABLE,
                artifact=None, base_revision=base_revision, error=str(e))
        except Exception as e:
            return self._resolve_and_finish(
                ledger, intent.id, finish, STATE_WORKTREE_FAILED, artifact=None,
                base_revision=base_revision,
                error=f"worktree creation failed: {e}")

        # READ THE ADMIN POINTER NOW, WHILE NO CANDIDATE CODE HAS RUN.
        # `<worktree>/.git` is a file saying `gitdir: <path>`, and a candidate
        # can rewrite it to point at a gitdir it authored, whose config then
        # names arbitrary programs for git to execute (measured; see _git).
        # Reading it here and passing --git-dir explicitly afterwards is what
        # makes the pointer irrelevant. This is not a check-then-use window:
        # the value is captured before the window opens, not validated inside
        # it.
        #
        # THIS LINE WAS `self._admin_dir = None` AND THE COMMENT ABOVE STAYED.
        # That is the whole vector: every test that calls `_git` directly went
        # on passing, because they supply `git_dir=` themselves, and only the
        # one test that goes through `run()` could see it. A guard that is
        # built and not connected is indistinguishable from a guard, right up
        # until it is measured through the product.
        self._admin_dir = _read_gitdir_pointer(worktree)

        ctx = RunnerContext(worktree=worktree, branch=self.branch,
                            base_revision=base_revision, task=self.task,
                            is_cancelled=self._is_cancelled)
        state = STATE_CLEAN
        artifact: PatchArtifact | None = None
        gates: GateResult | None = None
        error: str | None = None
        runner_detail: Any = None
        artifact_path: str | None = None
        artifact_locator: dict[str, Any] | None = None
        persist_error: str | None = None

        try:
            if self._is_cancelled():
                state, error = STATE_CANCELLED, "cancelled before the runner ran"
            else:
                # 4. the work, inside the worktree and nowhere else.
                try:
                    runner_detail = self._runner(ctx)
                except Exception as e:
                    state = STATE_RUNNER_FAILED
                    error = f"{type(e).__name__}: {e}"

            if state == STATE_CLEAN:
                # 5. the artifact.
                try:
                    artifact = self._capture_patch(worktree, base_revision)
                except Exception as e:
                    state = STATE_WORKTREE_FAILED
                    error = f"patch capture failed: {type(e).__name__}: {e}"

            if artifact is not None and self._artifact_dir is not None:
                locator, persist_error = self._persist_to_store(artifact)
                if locator is not None:
                    artifact_path = str(locator.blob_path)
                    artifact_locator = locator.summary()
                if persist_error and error is None:
                    error = persist_error

            if artifact is not None and state == STATE_CLEAN:
                if artifact.is_empty:
                    # Gates on an unmodified tree would pass without judging
                    # anything; that vacuous green is exactly what must not be
                    # reported as `clean`.
                    state = STATE_NO_CHANGE
                    error = "the runner produced no change to gate"
                else:
                    # ONE NORMAL FORM, SHARED WITH THE SEAL. This used to
                    # normalise with `.replace("\\","/").removeprefix("./")` and
                    # then test exact membership, which meant a declared
                    # DIRECTORY matched nothing and rejected the whole patch --
                    # while `receipts._criterion_seal`, reading the same field,
                    # already treated a directory as covering what is under it.
                    # `containment_escapes` is that comparison, so the boundary
                    # the receipt describes is the boundary that was enforced.
                    from daedalus.spine.receipts import containment_escapes

                    # EMPTY IS NOT "DECLARE NOTHING", IT IS "FENCE NOTHING".
                    # This branch read `if self.task.target_paths:`, so a task
                    # that declared no scope was compared against nothing and
                    # every changed path passed unexamined.
                    #
                    # MEASURED (docs/inventory/2026-08-24/DENY_FLOOR_CORPUS.md):
                    # this check is what stands between a candidate and its own
                    # evaluator. It runs BEFORE `_run_gates`, and a planted
                    # `conftest.py` -- a file the write fence admits -- flips a
                    # real Gate-1 verdict from FAIL to PASS with
                    # `pytest_sessionfinish`. Skipping the check for an
                    # undeclared scope handed that path to any task that simply
                    # named nothing.
                    #
                    # `containment_escapes` already returns EVERY changed path
                    # for an empty declaration, so the refusal needs no second
                    # comparison -- only its own name, so the receipt does not
                    # read as "you wrote outside a scope" when the truth is
                    # "there was no scope".
                    declared = tuple(self.task.target_paths or ())
                    escaped, scope_error = containment_escapes(
                        artifact.changed_paths, declared)
                    if escaped and not declared:
                        scope_error = (
                            "the task declared no target_paths at all, so no "
                            "changed path can be shown to be contained by one; "
                            "an undeclared scope is refused, never skipped")
                    if escaped:
                        state = STATE_GATES_FAILED
                        error = (
                            "artifact changed path(s) outside declared "
                            f"target_paths: {', '.join(escaped)}")
                        if scope_error:
                            error = f"{error} ({scope_error})"
                        gates = GateResult(
                            passed=False,
                            name="target-scope",
                            command=(),
                            returncode=None,
                            output=error)
                    elif self._is_cancelled():
                        state = STATE_CANCELLED
                        error = "cancelled after the patch was captured"
                    else:
                        # 6. gates, inside the worktree, raw output retained.
                        gates = self._run_gates(ctx)
                        if gates.passed:
                            try:
                                stable, binding_detail = (
                                    self._post_gate_artifact_stable(
                                        worktree, artifact))
                            except Exception as exc:
                                stable = False
                                binding_detail = (
                                    "post-gate artifact binding could not be "
                                    f"verified: {type(exc).__name__}: {exc}. "
                                    "Refusing the green verdict.")
                            if not stable:
                                state = STATE_GATES_FAILED
                                error = binding_detail
                                gates = replace(
                                    gates,
                                    passed=False,
                                    output=(
                                        f"{gates.output}\n{binding_detail}"
                                        if gates.output else binding_detail))
                        if not gates.passed and state == STATE_CLEAN:
                            state = STATE_GATES_FAILED
                            if gates.cancelled:
                                state = STATE_CANCELLED
                            error = error or (
                                f"gate {gates.name!r} failed "
                                f"(exit {gates.returncode})")
        finally:
            # 8. cleanup, reported rather than swallowed.
            removed, cleanup_error = self._cleanup(worktree)

        # 7. resolve the intent with the artifact digest as the effect id.
        return self._resolve_and_finish(
            ledger, intent.id, finish, state, artifact=artifact, gates=gates,
            base_revision=base_revision, error=error,
            worktree_path=str(worktree), worktree_removed=removed,
            cleanup_error=cleanup_error, artifact_path=artifact_path,
            artifact_locator=artifact_locator, persist_error=persist_error,
            runner_detail=runner_detail)

    # -- steps -------------------------------------------------------------- #
    def _resolve_base(self) -> str:
        ref = self.task.base_revision or "HEAD"
        out = _git(["rev-parse", ref], cwd=self.repo_root,
                   repo_root=self.repo_root)
        return out.stdout.decode("utf-8", "replace").strip()

    def _capture_patch(self, worktree: Path, base_revision: str) -> PatchArtifact:
        """Stage everything in the WORKTREE's own index and read the diff.

        ``git add -A`` writes only the worktree's private index -- worktrees do
        not share an index with the primary checkout -- and it respects
        ``.gitignore``, so the artifact contains exactly what a human would be
        asked to commit.

        ``--no-renames`` is pinned so the digest does not move with git's
        rename-detection heuristics, ``--no-ext-diff`` so a developer's
        configured external differ cannot rewrite the bytes we hash, and
        ``--no-textconv`` because IT IS NOT IMPLIED BY ``--no-ext-diff``.
        ``--no-ext-diff`` suppresses ``diff.external`` and a driver's
        ``command``; a ``diff.<driver>.textconv`` is a separate program, chosen
        by the same candidate-authored ``.gitattributes``, and it was still
        being spawned here. That was demonstrated by execution, not inferred:
        appending this flag to the exact option list below suppressed every
        spawn.

        THIS RUNS AFTER CANDIDATE CODE AND BEFORE THE GATE, in the parent
        process, so every git invocation here is pinned to the admin directory
        captured before the runner ran. See :func:`_git` for what a candidate
        does to an unpinned one.
        """
        gd, wt = self._admin_dir, worktree
        _git(["add", "-A"], cwd=worktree, repo_root=self.repo_root,
             git_dir=gd, work_tree=wt)
        opts = ["--cached", "--no-color", "--no-ext-diff", "--no-textconv",
                "--no-renames"]
        diff = _git(["diff", *opts], cwd=worktree, repo_root=self.repo_root,
                    git_dir=gd, work_tree=wt).stdout
        names = _git(["diff", *opts, "--name-only", "-z"], cwd=worktree,
                     repo_root=self.repo_root, git_dir=gd, work_tree=wt).stdout
        changed = tuple(p.decode("utf-8", "replace")
                        for p in names.split(b"\0") if p)
        return PatchArtifact(
            task_id=self.task.task_id, branch=self.branch,
            base_revision=base_revision, diff_bytes=diff,
            diff_sha256=_sha256_bytes(diff), changed_paths=changed,
            created_ts=_now_iso())

    def _post_gate_artifact_stable(
            self, worktree: Path,
            artifact: PatchArtifact) -> tuple[bool, str]:
        """Bind a green verdict to the exact pre-gate patch bytes.

        The artifact is staged before the gate so the gate judges the candidate
        tree. A gate is still code, however: it can rewrite a tracked file,
        create a new untracked file, or (without MIC containment) alter the
        index before returning 0. Without this check, the persisted artifact
        and its digest could describe bytes the green gate never finished on.

        Ignored outputs are deliberately excluded: dependency installs and
        builds legitimately create ``node_modules``/``dist``. Tracked,
        non-ignored untracked, and staged bytes must remain exactly bound.
        """
        gd, wt = self._admin_dir, worktree
        opts = ["--no-color", "--no-ext-diff", "--no-textconv",
                "--no-renames"]
        cached = _git(
            ["diff", "--cached", *opts],
            cwd=worktree, repo_root=self.repo_root,
            git_dir=gd, work_tree=wt).stdout
        cached_sha = _sha256_bytes(cached)
        unstaged = _git(
            ["diff", *opts, "--name-only", "-z"],
            cwd=worktree, repo_root=self.repo_root,
            git_dir=gd, work_tree=wt).stdout
        untracked = _git(
            ["ls-files", "--others", "--exclude-standard", "-z"],
            cwd=worktree, repo_root=self.repo_root,
            git_dir=gd, work_tree=wt).stdout
        if (cached_sha == artifact.diff_sha256
                and not unstaged and not untracked):
            return True, ""

        def _paths(raw: bytes) -> str:
            decoded = [
                part.decode("utf-8", "replace")
                for part in raw.split(b"\0") if part]
            return ", ".join(decoded) if decoded else "-"

        return False, (
            "post-gate artifact binding failed: the gate changed the "
            "candidate tree or staged patch after artifact capture "
            f"(expected_sha256={artifact.diff_sha256}, "
            f"post_gate_sha256={cached_sha}, "
            f"unstaged={_paths(unstaged)}, "
            f"untracked={_paths(untracked)}). Refusing the green verdict.")

    def _run_gates(self, ctx: RunnerContext) -> GateResult:
        started = time.monotonic()
        try:
            verdict = self._gate(ctx)
        except Exception as e:
            return GateResult(
                passed=False, name="gate",
                output=f"gate raised: {type(e).__name__}: {e}",
                duration_s=time.monotonic() - started)
        if isinstance(verdict, GateResult):
            return verdict
        # A bare bool is accepted for trivial gates, but it carries no output,
        # and that absence is recorded rather than dressed up.
        return GateResult(passed=bool(verdict), name="gate",
                          output="gate returned a bare verdict with no output",
                          duration_s=time.monotonic() - started)

    def _persist(self, artifact: PatchArtifact) -> tuple[str | None, str | None]:
        """Compatibility projection of :meth:`_persist_to_store`.

        Existing direct callers receive the verified blob path and any error.
        The normal run path also retains the immutable metadata locator.
        """
        # Call through the class so the long-standing fence test's deliberately
        # tiny stand-in object (which binds only this compatibility method)
        # still exercises the real implementation.
        locator, error = TaskAttempt._persist_to_store(self, artifact)
        return (str(locator.blob_path) if locator is not None else None, error)

    def _persist_to_store(
            self,
            artifact: PatchArtifact
            ) -> tuple[ArtifactLocator | None, str | None]:
        """Put candidate bytes through the canonical content-addressed store.

        THE ONE PLACE THIS MODULE WRITES A CALLER-CHOSEN PATH, and until now it
        wrote it unchecked. Everything else here is fenced by construction --
        the worktree lives under ``%LOCALAPPDATA%``, the gate's scratch tree
        under ``%TEMP%``, and every git invocation goes through :func:`_git`.
        ``artifact_dir`` is a plain constructor argument, so
        ``TaskAttempt(..., artifact_dir=repo_root / "runs" / "patches")``
        deposited candidate bytes straight into the primary checkout, created
        the intermediate directories to do it, and reported the path on a
        ``clean`` result as if that were the intended outcome. The module
        docstring's claim that this class cannot write the primary checkout was
        true of every path except this one.

        The fence still runs BEFORE the store can create a directory. The store
        then verifies ``diff_sha256`` against the authoritative bytes, publishes
        them atomically without replacing an existing object, and emits a
        provenance-bearing immutable locator. A corrupted existing object is a
        refusal, not something an attempt silently repairs.

        Failure is reported rather than raised because persistence is a side
        errand -- losing an in-memory gated candidate to a bad output directory
        would be strictly worse than retaining it with an explicit error.
        """
        store = ArtifactStore(self._artifact_dir)
        try:
            # Check the root, not merely one derived blob path: one put writes
            # both a blob and a locator beneath it.
            assert_write_allowed(
                store.root,
                self.repo_root,
                what="to persist a candidate artifact store to")
        except PrimaryCheckoutWrite as e:
            return None, str(e)
        try:
            task = getattr(self, "task", None)
            task_digest = getattr(task, "digest", None)
            provenance = ContractProvenance(
                origin="daedalus.spine.attempt.TaskAttempt",
                source_revision=artifact.base_revision,
                created_at=artifact.created_ts,
                input_digests=(
                    (str(task_digest),) if task_digest else ()
                ),
                trace_id=current_trace_id(),
            )
            locator = store.put_bytes(
                artifact.diff_bytes,
                expected_sha256=artifact.diff_sha256,
                media_type="text/x-diff",
                metadata={
                    "kind": "candidate_patch",
                    "task_id": artifact.task_id,
                    "branch": artifact.branch,
                    "changed_paths": list(artifact.changed_paths),
                    "filename_hint": f"{artifact.task_id}.patch",
                },
                provenance=provenance.to_dict(),
            )
            return locator, None
        except Exception as e:                 # noqa: BLE001 - reported side effect
            return None, (
                f"artifact could not be persisted: {type(e).__name__}: {e}")

    def _persist_gate_output(
            self,
            gates: GateResult | None,
            base_revision: str | None,
            created_ts: str) -> tuple[str | None, str | None]:
        """Put the RAW gate output in the content-addressed store.

        ``EvidenceItem.evidence_locator`` must be a durable
        ``artifact-locator:sha256:`` URI, and the point of that requirement is
        that a verdict has to be re-readable later. The trimmed
        ``GateResult.summary()`` tail already in the ledger is not that: it is a
        4000-character excerpt. So the FULL bytes go to the same store the
        candidate patch goes to, behind the same primary-checkout fence, and the
        locator -- not the excerpt -- is what the evidence binds.

        The bytes are encoded exactly as :func:`_sha256_text` encodes them, so
        ``expected_sha256`` is the gate's own ``output_sha256`` and the store
        verifies the two agree before publishing. A mismatch is a refusal here
        rather than an evidence item pointing at different bytes than it claims.

        Returns ``(locator_uri, error)``; failure is reported, never raised.
        """
        if gates is None:
            return None, ("no gate ran, so there is no evaluator output to bind "
                          "as evidence")
        if self._artifact_dir is None:
            return None, ("no artifact store configured (artifact_dir is None), "
                          "so the gate output has no durable locator")
        if base_revision is None:
            return None, "no resolved base revision to bind the gate output to"
        store = ArtifactStore(self._artifact_dir)
        try:
            assert_write_allowed(
                store.root,
                self.repo_root,
                what="to persist a gate output artifact store to")
        except PrimaryCheckoutWrite as e:
            return None, str(e)
        try:
            payload = gates.output.encode("utf-8", "replace")
            locator = store.put_bytes(
                payload,
                expected_sha256=gates.output_sha256,
                media_type="text/plain",
                metadata={
                    "kind": "gate_output",
                    "gate": gates.name,
                    "task_id": self.task.task_id,
                    "attempt_id": self.attempt_id,
                    "passed": bool(gates.passed),
                    "returncode": gates.returncode,
                    "filename_hint": f"{_slug(self.task.task_id)}-{gates.name}.log",
                },
                provenance=ContractProvenance(
                    origin="daedalus.spine.attempt.TaskAttempt",
                    source_revision=base_revision,
                    created_at=created_ts,
                    input_digests=(self.task.digest,),
                    trace_id=current_trace_id(),
                ).to_dict(),
            )
            return locator.locator_uri, None
        except Exception as e:                 # noqa: BLE001 - reported side effect
            return None, (
                f"gate output could not be persisted: {type(e).__name__}: {e}")

    #: What a git tree entry's mode means to the criterion seal. ``"blob"`` is a
    #: REGULAR file: a symlink (``120000``) is a blob whose content is a path,
    #: so its bytes change when the file it points at is written -- which the
    #: candidate may be allowed to do -- and a gitlink (``160000``) is a commit
    #: id in another repository whose content this tree does not pin at all.
    #: Neither seals anything, and both would pass a bare "does the path exist"
    #: check. ``"tree"`` is a directory, and it earns a name of its own because
    #: a package IS a directory and a NAMESPACE package is a directory with no
    #: ``__init__.py``: a probe that could only answer "is a regular file"
    #: reported every namespace package as absent and every import through one
    #: as unresolvable.
    _TREE_ENTRY_KINDS = {
        b"100644": "blob", b"100755": "blob", b"040000": "tree", b"40000": "tree",
    }
    _REGULAR_BLOB_MODES = tuple(
        mode for mode, kind in _TREE_ENTRY_KINDS.items() if kind == "blob")

    def _criterion_presence(
            self, base_revision: str | None) -> dict[str, bool] | None:
        """Measure each declared gate criterion against the BASE revision tree.

        ``None`` means the question could not be asked (no resolved base, or git
        refused), which the assurance seal treats as "not knowable" and
        therefore as no seal -- never as a pass. A path maps to ``True`` only
        when the frozen base tree holds a REGULAR file there.

        THE TREE IS READ, NOT THE FILESYSTEM. ``Path.exists`` on the primary
        checkout would answer about the working tree as it is now, which is not
        the revision the candidate branched from, and it would follow a symlink
        or a Windows junction straight out of the repository. Reading the tree
        entry answers the exact question the seal asks -- was this file, with
        these bytes, in the revision the attempt was built on -- and the mode
        that comes back with it is what excludes the two entry kinds that look
        like files and are not.

        ``cat-file -p <rev>:<dir>`` is used rather than ``ls-tree`` because it
        is already inside :data:`READ_ONLY_REPO_VERBS`; a presence probe is not
        a reason to widen a write-fence allowlist.

        IT DOES NOT PASS ``self._admin_dir``, unlike every other git call in
        this class, and that is deliberate rather than an omission. The pinned
        admin directory belongs to the attempt's WORKTREE, which ``_cleanup``
        has already removed by the time the projection is built -- pinning to
        it made every probe fail and every criterion read as absent, which the
        seal then correctly refused. This reads the PRIMARY repository, which is
        where the base revision lives and which the candidate never had a path
        to; ``cat-file`` on a tree object runs no filter and no textconv, so the
        hardening the pin exists to provide has nothing to defend here.
        """
        from daedalus.spine.receipts import criterion_probe_paths

        probes = criterion_probe_paths(self.task)
        if not probes:
            return {}
        if not base_revision:
            return None
        return self._tree_presence(base_revision, probes, {})

    def _tree_kinds(
            self,
            base_revision: str,
            probes: Sequence[tuple[str, str]],
            listings: dict[str, dict[bytes, bytes]],
    ) -> dict[str, str]:
        """``{key: "blob" | "tree" | ""}`` for each probe, read from the tree.

        The directory listing cache is passed IN rather than owned here, so one
        projection's criterion probe and its whole import surface read each
        shared parent directory once. See :meth:`_criterion_presence` for why
        the tree is read instead of the filesystem, and why the admin dir is not
        pinned. A symlink (``120000``) and a submodule (``160000``) fall through
        to ``""``: neither is a file whose bytes this tree authoritatively holds.
        """

        kinds: dict[str, str] = {}
        for key, path in probes:
            parent, _, name = path.rpartition("/")
            if parent not in listings:
                try:
                    out = _git(["cat-file", "-p", f"{base_revision}:{parent}"],
                               cwd=self.repo_root, repo_root=self.repo_root).stdout
                except Exception:
                    # A missing directory is a legitimate answer ("no such
                    # criterion"), and a git failure is an unanswerable one.
                    # Both are recorded as "not present" rather than as an
                    # exception that would destroy an otherwise finished
                    # attempt's projection.
                    listings[parent] = {}
                else:
                    entries: dict[bytes, bytes] = {}
                    for line in out.splitlines():
                        head, _, entry = line.partition(b"\t")
                        mode = head.split(b" ", 1)[0] if head else b""
                        if entry:
                            entries[entry] = mode
                    listings[parent] = entries
            mode = listings[parent].get(name.encode("utf-8", "replace"))
            kinds[key] = self._TREE_ENTRY_KINDS.get(mode or b"", "")
        return kinds

    def _tree_presence(
            self,
            base_revision: str,
            probes: Sequence[tuple[str, str]],
            listings: dict[str, dict[bytes, bytes]],
    ) -> dict[str, bool]:
        """``{key: is a regular file in <base_revision>}`` for each probe."""

        return {key: kind == "blob" for key, kind in
                self._tree_kinds(base_revision, probes, listings).items()}

    def _blob(self, base_revision: str, path: str) -> str | None:
        """One file's text out of the frozen base revision, or ``None``."""

        try:
            out = _git(["cat-file", "-p", f"{base_revision}:{path}"],
                       cwd=self.repo_root, repo_root=self.repo_root).stdout
        except Exception:
            return None
        return out.decode("utf-8", "replace")

    def _tree_top_level_names(self, base_revision: str) -> set[str] | None:
        """Every name in the tree a ``sys.path`` entry COULD make importable.

        Asked once per attempt, and only about an import that resolved nowhere
        under the roots this resolver modelled. It answers the one remaining
        question: could the tree satisfy this name AT ALL? If nothing is called
        ``<name>.py`` and no directory is called ``<name>``, then no ``sys.path``
        entry can make it in-tree, the import comes from an installed
        distribution, and the candidate cannot reach it -- so ``import pytest``
        does not cost every declared criterion its seal. If something IS called
        that, the surface is unknowable and the seal refuses.
        """

        cached = getattr(self, "_top_level_cache", None)
        if cached is not None and cached[0] == base_revision:
            return cached[1]
        try:
            # ls-files --with-tree, not ls-tree: `ls-files` is already inside
            # READ_ONLY_REPO_VERBS and `--with-tree` makes it report the named
            # revision's paths. Widening that allowlist to add a second listing
            # verb would be a guard change made for a convenience, and the
            # difference (index entries the revision does not have) can only
            # make MORE names look in-tree, which is the fail-closed direction.
            out = _git(["ls-files", "-z", f"--with-tree={base_revision}"],
                       cwd=self.repo_root, repo_root=self.repo_root).stdout
        except Exception:
            names = None
        else:
            names = set()
            for raw in out.split(b"\x00"):
                if not raw:
                    continue
                parts = raw.decode("utf-8", "replace").replace("\\", "/").split("/")
                names.update(parts[:-1])
                if parts[-1].endswith(".py"):
                    names.add(parts[-1][:-3])
        self._top_level_cache = (base_revision, names)
        return names

    def _import_roots(
            self,
            base_revision: str,
            criterion: str,
            source: str,
            listings: dict[str, dict[bytes, bytes]],
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """``(import roots, reasons a root could not be read)`` for one criterion.

        THE LAYOUTS THE PROJECT ACTUALLY USES, not the two the old regex
        assumed. The repository root; the directory pytest's ``prepend`` import
        mode puts on the path (the criterion's first ancestor without an
        ``__init__.py``, so a criterion inside a real test package resolves
        too); ``src/`` when the tree has one; whatever the criterion's own
        ``sys.path`` statements put there; whatever a ``conftest.py`` on its
        collection chain puts there; and whatever ``pythonpath`` / ``where`` /
        ``package-dir`` in the project config declares.

        Each of those sources answers in two ways -- roots, or a reason it could
        not be read -- and a reason travels all the way to the seal as an
        UNKNOWABLE surface. That is the whole difference from the previous
        measurement, which could only ever answer with silence.
        """

        from daedalus.spine.receipts import (
            chain_directories, config_import_roots, conventional_import_roots,
            path_config_files, pytest_basedir, sys_path_roots, tree_probes)

        chain = chain_directories(criterion)
        conftests = [f"{directory}/conftest.py" if directory else "conftest.py"
                     for directory in chain]
        configs = list(path_config_files())
        inits = [f"{directory}/__init__.py" for directory in chain if directory]
        conventional = list(conventional_import_roots())
        pairs = tree_probes(conftests + configs + inits + conventional)
        key_of = {path: key for key, path in pairs}
        kinds = self._tree_kinds(base_revision, pairs, listings)

        roots: list[str] = ["", criterion.rpartition("/")[0],
                            pytest_basedir(criterion, kinds)]
        reasons: list[str] = []
        for root in conventional:
            if kinds.get(key_of.get(root, ""), "") == "tree":
                roots.append(root)
        for declaring in conftests + configs:
            if kinds.get(key_of.get(declaring, ""), "") != "blob":
                continue
            text = self._blob(base_revision, declaring)
            if text is None:
                reasons.append(
                    f"{declaring!r} is in the base revision tree but could not "
                    "be read, so the import roots it declares are not knowable"
                )
                continue
            if declaring.endswith("conftest.py"):
                found, why = sys_path_roots(text, declaring)
            else:
                found, why = config_import_roots(declaring, text)
            roots.extend(found)
            reasons.extend(why)
        found, why = sys_path_roots(source, criterion)
        roots.extend(found)
        reasons.extend(why)
        return tuple(dict.fromkeys(roots)), tuple(dict.fromkeys(reasons))

    def _criterion_imports(self, base_revision: str | None):
        """The in-tree code each declared criterion EXECUTES, per the base tree.

        The second half of the same measurement/judgement seam as
        :meth:`_criterion_presence`: only this class can read the frozen base,
        so the reading happens here and
        :func:`daedalus.spine.receipts._criterion_seal` decides what it means.

        WHY THE BLOB AND NOT THE WORKTREE. The criterion's text in the
        candidate's worktree is the text the candidate may have written; the
        question the seal asks is what the criterion imported in the revision it
        was sealed from. ``cat-file -p <rev>:<path>`` answers exactly that, is
        already inside :data:`READ_ONLY_REPO_VERBS`, and runs no filter.

        RESOLVED FOR REAL, AND UNREADABLE IS NOT EMPTY. The previous version read
        the import surface with a line regex against two roots and declared five
        blind spots -- ``sys.path`` insertion, ``src/`` layouts, namespace
        packages, dynamic ``importlib``, relative imports inside a package. Each
        blind spot made an import INVISIBLE, and the seal scored invisible as
        "imports nothing inside the write scope". The Gate-1 ignition slice
        sealed through exactly that: measured, its conformance suite inserts
        ``<root>/src`` on ``sys.path`` and imports ``ignition_app``, whose
        package reaches the two files the code/type work item writes. The
        criterion is now parsed
        (:func:`~daedalus.spine.receipts.import_surface_plan`), every import is
        resolved against the roots the project really uses, and a construct that
        cannot be resolved becomes a REASON the seal refuses on.

        TWO ROUNDS, NOT ALL OF THEM. The criterion's own imports and THEIR
        in-tree imports are walked; files reached deeper are recorded as part of
        the surface but not re-parsed. That is a bounded read rather than a
        transitive closure of the repository, and the bound is stated in
        :data:`~daedalus.spine.receipts.MAX_IMPORT_SURFACE_FILES`, whose breach
        is reported as unknowable rather than quietly truncated.

        ``None`` means the question could not be asked at all, which the seal
        refuses on rather than passes.
        """
        from daedalus.spine.receipts import (
            MAX_IMPORT_SURFACE_FILES, CriterionImportSurface,
            criterion_probe_paths, import_surface_plan, module_dotted_name,
            resolve_import_plan)

        probes = criterion_probe_paths(self.task)
        if not probes:
            return {}
        if not base_revision:
            return None
        listings: dict[str, dict[bytes, bytes]] = {}
        surfaces: dict[str, CriterionImportSurface] = {}
        for key, criterion in probes:
            source = self._blob(base_revision, criterion)
            if source is None:
                # An unreadable criterion is already refused by the presence
                # check; an empty surface here keeps that refusal the one the
                # receipt names instead of stacking a second, vaguer one.
                surfaces[key] = CriterionImportSurface()
                continue
            roots, root_reasons = self._import_roots(
                base_revision, criterion, source, listings)
            reasons: list[str] = list(root_reasons)
            seen: dict[str, str] = {}
            own_root = self._owning_root(criterion, roots)
            _, own_package = module_dotted_name(criterion, own_root)
            frontier = [(criterion, source, own_root, own_package)]
            for round_index in range(2):
                reached: list[tuple[str, str, str]] = []
                for path, text, root, package in frontier:
                    plan = import_surface_plan(
                        text, path, roots=roots,
                        package_root=root, package=package)
                    kinds = self._tree_kinds(base_revision, plan.probes, listings)
                    surface = resolve_import_plan(plan, kinds)
                    reasons.extend(surface.errors)
                    for statement, top in surface.unresolved:
                        why = self._unresolvable_reason(
                            base_revision, path, statement, top)
                        if why:
                            reasons.append(why)
                    for found_key, found_path, found_root in surface.files:
                        if found_key in seen or found_path == criterion:
                            continue
                        if len(seen) >= MAX_IMPORT_SURFACE_FILES:
                            reasons.append(
                                f"{criterion!r} reaches more than "
                                f"{MAX_IMPORT_SURFACE_FILES} in-tree files, so "
                                "this resolver stopped walking and the rest of "
                                "its import surface is not knowable"
                            )
                            break
                        seen[found_key] = found_path
                        _, found_package = module_dotted_name(
                            found_path, found_root)
                        reached.append((found_path, found_root, found_package))
                if round_index or not reached:
                    break
                frontier = []
                for path, root, package in reached:
                    text = self._blob(base_revision, path)
                    if text is None:
                        reasons.append(
                            f"{path!r} is on {criterion!r}'s import surface but "
                            "could not be read out of the base revision, so what "
                            "the criterion executes is not knowable"
                        )
                        continue
                    frontier.append((path, text, root, package))
            surfaces[key] = CriterionImportSurface(
                paths=tuple(sorted(seen)),
                unknowable=tuple(dict.fromkeys(reasons)),
            )
        return surfaces

    @staticmethod
    def _owning_root(path: str, roots: Sequence[str]) -> str:
        """The longest declared root that contains ``path``.

        A file's relative imports resolve inside the package it was FOUND in, so
        the criterion's own package has to be read against the root the resolver
        would have reached it by -- the deepest one, because a file under
        ``src/pkg/`` is ``pkg.mod`` from ``src`` and ``src.pkg.mod`` from the
        repository root, and only the first spelling puts ``from .x`` where
        Python would.
        """

        best = ""
        for root in roots:
            if root and path.startswith(root + "/") and len(root) > len(best):
                best = root
        return best

    def _unresolvable_reason(
            self, base_revision: str, path: str, statement: str, top: str
    ) -> str | None:
        """Why an unresolved import is unknowable, or ``None`` if it is external."""

        from daedalus.spine.receipts import stdlib_top_level

        if not top or stdlib_top_level(top):
            return None
        names = self._tree_top_level_names(base_revision)
        if names is None:
            return (
                f"{path!r} states {statement!r} and the base revision's file "
                "list could not be read, so whether that module is in-tree is "
                "not knowable"
            )
        if top not in names:
            return None
        return (
            f"{path!r} states {statement!r}: it resolves to no file under the "
            "import roots this resolver modelled, yet the base revision does "
            f"contain something named {top!r}, so which code the criterion "
            "executes is not knowable"
        )

    @staticmethod
    def _shed_telemetry_from(runner_detail: Any) -> Any:
        """Lift the local lane's brief-shed rows out of whatever the runner returned.

        THE PRODUCER AND THE CONSUMER WERE BOTH LIVE AND NOTHING JOINED THEM.
        ``daedalus.providers.ollama`` writes these rows into
        ``report.handoff["shed_telemetry"]`` on every full-file prompt, and
        ``canonicalise_attempt`` has taken a ``shed_telemetry`` argument since
        it was written -- but ``_canonicalise`` never passed one, so the
        covariate was produced, carried through offload, and dropped here.

        Duck-typed and total. A runner is an injected callable that may return
        anything at all; a shape this does not recognise yields ``None``, which
        is exactly "no shed decision was reported". It deliberately does not
        validate the rows -- ``normalise_shed_telemetry`` does that, and its
        refusals are reported on the contract set rather than raised here.
        """
        if not isinstance(runner_detail, Mapping):
            return None
        report = runner_detail.get("report")
        if not isinstance(report, Mapping):
            return None
        handoff = report.get("handoff")
        if not isinstance(handoff, Mapping):
            return None
        return handoff.get("shed_telemetry")

    def _canonicalise(self, result: AttemptResult, base_revision: str | None):
        """Project one finished attempt onto the canonical Gate-0 contracts.

        THE WIRING THIS CLASS WAS MISSING. ``daedalus.schemas`` has carried
        ``AttemptContract.from_task_spec`` and
        ``EvidencePacket``/``AttemptReceipt.from_attempt_result`` -- adapters
        written for exactly these legacy records -- with no caller anywhere in
        production. Invariant 1 says Mission, Attempt, Evidence and policy
        decisions have ONE canonical contract; a contract nothing produces does
        not satisfy it. This call is what makes the live attempt path produce
        them.
        """
        from daedalus.spine.receipts import (
            adapter_identity, canonicalise_attempt, evaluator_assurance_detail)

        locator_uri, locator_error = self._persist_gate_output(
            result.gates, base_revision, result.finished_ts)
        gate_ms = (int(round(result.gates.duration_s * 1000))
                   if result.gates is not None else 0)
        # MEASURED HERE, NOT ASSUMED THERE. The seal needs to know whether the
        # declared criterion was a real file in the frozen base; only this class
        # has the pinned git invocation that can answer it, so the measurement
        # is taken here and the judgement stays in `receipts`.
        criterion_present = self._criterion_presence(base_revision)
        criterion_imports = self._criterion_imports(base_revision)
        assurance, assurance_reason = evaluator_assurance_detail(
            result, self.task, criterion_present=criterion_present,
            criterion_imports=criterion_imports)
        return canonicalise_attempt(
            result,
            task=self.task,
            mission_id=self.mission_id,
            attempt_id=self.attempt_id,
            base_revision=str(base_revision or ""),
            adapter_id=adapter_identity(self._runner),
            evidence_locator=locator_uri,
            locator_error=locator_error,
            assurance=assurance,
            assurance_reason=assurance_reason,
            criterion_present=criterion_present,
            criterion_imports=criterion_imports,
            # The measured half of usage. Spend and server-counted tokens are
            # absent because nothing on this path meters them -- see
            # receipts.UNMETERED_SPEND_REASON, which travels inside the
            # PolicyDecision digest rather than in a comment a reader of the
            # record would never see. `est_input_tokens` is filled by
            # `canonicalise_attempt` when the runner reported shed telemetry.
            usage=ResourceUsage(wall_time_ms=gate_ms),
            budget=self.budget,
            # THE COVARIATE THE LOCAL LANE ALREADY PRODUCED. Lifted off the
            # runner's own return value rather than re-derived, so the rows in
            # the receipt are the rows the prompt decision was actually made on.
            shed_telemetry=self._shed_telemetry_from(result.runner_detail),
            # The policy text the MISSION bound, when the caller knows it. Left
            # empty, `canonicalise_attempt` falls back to the declared registry
            # and still catches a registry that moved under the attempt.
            mission_policy_sha256=self.mission_policy_sha256 or None,
            execution_limit_policy=self.execution_limit_policy,
            # THE SOURCE OF THE PolicyDecision, not a decoration on it. Without
            # it `canonicalise_attempt` re-states the guard names in prose and
            # binds the registry digest by reaching for it a second time; with
            # it, the decision carries the receipt this attempt actually
            # started under.
            boundary_receipt=self._boundary_receipt,
            created_at=result.finished_ts,
            spend_grant_microusd=self.spend_grant_microusd,
            campaign_id=self.campaign_id,
            trace_id=current_trace_id(),
        )

    def _cleanup(self, worktree: Path) -> tuple[bool, str | None]:
        if self._keep_worktree:
            return False, None
        try:
            self._manager.cleanup_worktree(worktree)
        except Exception as e:
            # A leaked worktree is an operational fact the caller must see; it
            # does not invalidate the artifact, so it is reported alongside the
            # state rather than overwriting it.
            return False, f"{type(e).__name__}: {e}"
        return True, None

    def _resolve_and_finish(self, ledger: SpineLedger, intent_id: int,
                            finish: Callable[..., AttemptResult], state: str, *,
                            artifact: PatchArtifact | None,
                            gates: GateResult | None = None,
                            **kw: Any) -> AttemptResult:
        ledger_error: str | None = None
        # THE RESULT IS BUILT BEFORE THE LEDGER WRITE, not after, and that
        # ordering is load-bearing now. The canonical projection reads a
        # finished AttemptResult, and its EvidencePacket digest binds the exact
        # gate output bytes; building the projection from a result that does not
        # exist yet would mean re-deriving the same fields a second time in a
        # second place -- the drift this whole change exists to remove. The only
        # field the ledger write can still change is ``ledger_error``, and that
        # is applied by the ``replace`` below.
        result = finish(state, intent_id=intent_id, artifact=artifact,
                        gates=gates, ledger_error=None, **kw)
        contracts = self._canonicalise(result, kw.get("base_revision"))
        contract_body = contracts.to_dict()
        result_body = {
            "state": state,
            "branch": self.branch,
            "base_revision": kw.get("base_revision"),
            "cleanup_error": kw.get("cleanup_error"),
            "worktree_removed": kw.get("worktree_removed", False),
            "artifact": artifact.summary() if artifact else None,
            "artifact_path": kw.get("artifact_path"),
            "artifact_locator": kw.get("artifact_locator"),
            "persist_error": kw.get("persist_error"),
            "gates": gates.summary() if gates else None,
            "error": kw.get("error"),
            # ADDITIVE: every pre-existing key above keeps its exact shape, so
            # no existing reader of a spine row breaks. The canonical records
            # join the SAME row rather than opening a second store.
            "contracts": contract_body,
        }
        try:
            if artifact is not None:
                ledger.mark_completed(intent_id,
                                      effect_id=artifact.diff_sha256,
                                      result=_jsonable(result_body))
            else:
                ledger.mark_failed(
                    intent_id,
                    canonical_json(_jsonable(result_body)))
        except Exception as e:
            ledger_error = f"{type(e).__name__}: {e}"
        return replace(result,
                       ledger_error=ledger_error,
                       contracts=contract_body,
                       contracts_error=contracts.error)

    # -- the central effect boundary ---------------------------------------- #
    def _boundary_guard_decisions(self, ledger: SpineLedger) -> tuple:
        """Run the four ``python.attempt`` contracts and report their decisions.

        RUN, not asserted. Each of these can come back False on a real tree,
        which is the only thing that separates a boundary from a sentence:

        * ``spine.intent_ledger`` -- the Gate-0 durable writer is OPEN (WAL +
          synchronous=FULL with a machine readback), so the intent that
          precedes the worktree has somewhere durable to land. The caller
          already opened it; passing it in is what makes this a report on the
          real handle rather than a second, unrelated open.
        * ``containment.worktree`` -- :func:`daedalus.primary_tree.overlap_reason`
          over the ground this manager's worktrees will land on. Bidirectional:
          an ANCESTOR of the checkout is not inside it, and a manager handing
          back ``repo_root.parent`` would otherwise pass.
        * ``containment.attempt`` -- :class:`RunnerContext` still exposes no
          field naming the primary checkout. That absence is property 2 of the
          four in this module's docstring, and it was prose until here: this
          reads the dataclass fields, so re-adding ``repo_root`` to the runner's
          context refuses the attempt instead of quietly widening it.
        * ``budget.process_guard`` -- the process-wide spend net is really
          interposed on ``subprocess``/``urlopen`` before the gate spawns.
        """
        from dataclasses import fields as _fields

        from daedalus.budget import process_guard_boundary_decision
        from daedalus.spine.effect_boundary import GuardDecision

        # ONE bound for containment evidence, shared with the issuer that mints
        # the same family of rows. A guard row is rendered into
        # `PolicyDecision.reasons`, which refuses an entry over 1000 characters,
        # so an absolute path interpolated raw lets the checkout location decide
        # whether a refusal can be represented (G1-CHIP-01, measured at 1046).
        # Imported here, beside the other locals this method already needs, so
        # the module's import surface is unchanged.
        from daedalus.kernel.offload_lease import (
            _EVIDENCE_DETAIL_MAX_CHARS,
            _elide_middle,
            _evidence_path,
        )

        ledger_path = getattr(ledger, "path", None) or self._ledger_path
        ledger_decision = GuardDecision(
            "spine.intent_ledger",
            True,
            f"gate-0 durable spine writer open at {_evidence_path(ledger_path)}; "
            f"intent kind={INTENT_KIND!r} effect_key={self.effect_key!r} is "
            "committed before the worktree and before the runner, so a crash "
            "leaves a findable branch rather than an unrecorded effect",
        )

        # The root is a PLANNED directory: the manager creates it after this
        # check. Grounding it on its nearest existing ancestor and asking
        # `overlap_reason` refused every fresh root whose parent contains the
        # checkout (57a2e7cb); `planned_overlap_reason` asks about the name the
        # root will land on, in both directions.
        planned_root = Path(self._manager.worktree_root)
        overlap = _planned_overlap_reason(planned_root, self.repo_root)
        worktree_decision = GuardDecision(
            "containment.worktree",
            overlap is None,
            (
                f"primary_tree.planned_overlap_reason("
                f"{_evidence_path(planned_root)}, "
                f"{_evidence_path(self.repo_root)}) is None: candidate "
                f"checkouts land outside the primary checkout in both directions"
            )
            if overlap is None
            else (
                f"worktree root overlaps the primary checkout: "
                f"{_elide_middle(overlap, _EVIDENCE_DETAIL_MAX_CHARS)}"
            ),
        )

        exposed = tuple(f.name for f in _fields(RunnerContext))
        leaks = tuple(
            name
            for name in exposed
            if name in {"repo_root", "repo", "checkout", "primary_root"}
        )
        attempt_decision = GuardDecision(
            "containment.attempt",
            not leaks,
            (
                f"RunnerContext exposes {list(exposed)} and nothing naming the "
                f"primary checkout; the injected runner and gate are handed the "
                f"worktree path only, and every mutating git verb outside "
                f"{sorted(READ_ONLY_REPO_VERBS)} is refused by _git before "
                f"subprocess is reached"
            )
            if not leaks
            else (
                f"RunnerContext now exposes {list(leaks)}, so candidate code "
                f"can name the primary checkout"
            ),
        )

        # ``provider.write_policy`` -- declared on the row since 2026-08-23 so
        # the effect-lease issuer can draw the FILESYSTEM_WRITE scope from a
        # contract the row names. At THIS boundary the decision reports the
        # fences the attempt actually runs, it does not re-run them: writes
        # happen only inside the isolated worktree (containment.worktree
        # above), the primary checkout is refused byte-for-byte at persist
        # time by ``primary_tree.write_blocked_reason`` inside
        # ``ArtifactStore``/``_persist``, and the repo-path scope is the
        # TaskSpec's declared ``target_paths`` -- validated at construction
        # (``TaskSpecInvalid``) and enforced against the diff by the
        # containment gate before any patch is accepted.
        declared_scope = tuple(self.task.target_paths or ())
        write_policy_decision = GuardDecision(
            "provider.write_policy",
            True,
            (
                f"attempt-scoped write fence: writes land in the isolated "
                f"worktree only; primary checkout refused at persist by "
                f"primary_tree.write_blocked_reason; declared target_paths="
                f"{list(declared_scope)!r} validated at construction and "
                f"enforced by the containment gate on the captured diff"
            ),
        )

        # Retained for the disjointness recorder: record_primary_checkout_
        # disjointness records THIS decision, it never re-decides (its own
        # contract), so the boundary's object is kept rather than rebuilt.
        self._worktree_decision = worktree_decision

        return (
            ledger_decision,
            worktree_decision,
            attempt_decision,
            write_policy_decision,
            process_guard_boundary_decision(),
        )

    def _get_ledger(self) -> SpineLedger:
        if self._ledger is None:
            # Gate-0 writer seam: the durability factory is the only sanctioned
            # way to OPEN a writable Event Store (WAL + synchronous=FULL with a
            # machine readback, fail-closed). ``None`` resolves to the same
            # default path a bare ``SpineLedger()`` used. A raised
            # Gate0DurabilityError is absorbed by run()'s existing "spine
            # ledger unavailable" fail-closed branch before any effect.
            self._ledger = open_gate0_spine_writer(self._ledger_path)
        return self._ledger
