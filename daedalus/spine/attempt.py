"""spine/attempt.py -- TaskAttempt: produce a candidate change, never in the primary checkout.

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
``reconciliation_required``
                         a leased external effect started but its terminal
                         receipt could not be persisted; the intent and
                         worktree stay open for operator reconciliation
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
marked FAILED only when no artifact was produced at all. The exception is
``reconciliation_required``: an external effect may already exist without a
terminal receipt, so its intent deliberately remains open.
"""
from __future__ import annotations

import hashlib
import os
import re
# NOT `import shutil`. This module has no recursive delete of its own any more:
# the only one it had (the gate's scratch directory) goes through
# `remove_tree_no_follow` below. Keeping the import out means re-introducing
# `shutil.rmtree` costs a visible line in the diff rather than passing as an
# ordinary use of something already imported.
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field, replace
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from daedalus.kairos.worktree import GitWorktreeManager, remove_tree_no_follow
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
)
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import current_trace_id
from daedalus.spine.ledger import SpineLedger, canonical_json
from daedalus.storage import (
    ArtifactLocator,
    ArtifactStore,
    StorageUnavailable,
    require_storage,
)

__all__ = [
    "ATTEMPT_STATES",
    "AttemptResult",
    "GateResult",
    "GitCommandError",
    "INTENT_KIND",
    "PatchArtifact",
    "PrimaryCheckoutWrite",
    "READ_ONLY_REPO_VERBS",
    "RunnerContext",
    "STATE_CANCELLED",
    "STATE_CLEAN",
    "STATE_GATES_FAILED",
    "STATE_NO_CHANGE",
    "STATE_RECONCILIATION_REQUIRED",
    "STATE_RUNNER_FAILED",
    "STATE_STORAGE_UNAVAILABLE",
    "STATE_WORKTREE_FAILED",
    "TaskAttempt",
    "TaskSpec",
    "command_gate",
    "offload_runner",
    "pytest_gate",
    "pytest_gate_argv",
    "run_attempt",
]

ROOT = Path(__file__).resolve().parents[2]

INTENT_KIND = "attempt.candidate"

STATE_CLEAN = "clean"
STATE_GATES_FAILED = "gates_failed"
STATE_NO_CHANGE = "no_change"
STATE_RECONCILIATION_REQUIRED = "reconciliation_required"
STATE_RUNNER_FAILED = "runner_failed"
STATE_WORKTREE_FAILED = "worktree_failed"
STATE_STORAGE_UNAVAILABLE = "storage_unavailable"
STATE_CANCELLED = "cancelled"

ATTEMPT_STATES = (
    STATE_CLEAN,
    STATE_GATES_FAILED,
    STATE_NO_CHANGE,
    STATE_RECONCILIATION_REQUIRED,
    STATE_RUNNER_FAILED,
    STATE_WORKTREE_FAILED,
    STATE_STORAGE_UNAVAILABLE,
    STATE_CANCELLED,
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
    """
    env = dict(os.environ)
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
    correctness_before_state: Mapping[str, Any] = field(default_factory=dict)

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
    reconciliation: Mapping[str, str] | None = None
    reaped: tuple = ()
    reap_error: str | None = None

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
            "reconciliation": _jsonable(self.reconciliation),
            "reaped": _jsonable(list(self.reaped)),
            "reap_error": self.reap_error,
        }


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


def _remove_gate_tmpdir(tmpdir: Path) -> str | None:
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
        remove_tree_no_follow(tmpdir)
        return None
    except Exception as e:                      # noqa: BLE001 - reported, not raised
        return (f"[gate scratch directory {tmpdir} was NOT removed: "
                f"{type(e).__name__}: {e}]")


def _poll_until_done(proc: Any, ctx: RunnerContext, started: float,
                     timeout_s: float, poll_s: float) -> tuple[bool, bool, Any]:
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
    deadline = started + float(timeout_s)
    while proc.poll() is None:
        if ctx.is_cancelled():
            proc.cancel()
            cancelled = True
            break
        if time.monotonic() > deadline:
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
    """
    from daedalus.spine import containment

    containment.label_low_integrity(worktree)
    worktree_label = containment.integrity_label(worktree)
    low_temp = tmpdir / "lowtemp"
    low_temp.mkdir()
    containment.label_low_integrity(low_temp)

    log = containment.open_low_append_log(out_path)
    try:
        env = dict(os.environ)
        env["TEMP"] = env["TMP"] = str(low_temp)
        proc = containment.spawn_contained(
            argv, cwd=worktree, env=env, log=log,
            worktree_label=worktree_label)
    except BaseException:
        log.close()
        raise
    return proc, log


def command_gate(argv: Sequence[str], *,
                 timeout_s: float = DEFAULT_GATE_TIMEOUT_S,
                 poll_s: float = 0.25,
                 name: str = "command",
                 executes_candidate: bool = True
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
            scratch_error = _remove_gate_tmpdir(tmpdir)
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


def pytest_gate(paths: Sequence[str] = (), *,
                timeout_s: float = DEFAULT_GATE_TIMEOUT_S,
                poll_s: float = 0.25,
                name: str = "pytest",
                executes_candidate: bool = True
                ) -> Callable[[RunnerContext], GateResult]:
    """Run the repository's pytest gate through :func:`command_gate`."""
    return command_gate(
        pytest_gate_argv(paths),
        timeout_s=timeout_s,
        poll_s=poll_s,
        name=name,
        executes_candidate=executes_candidate,
    )


def offload_runner(**offload_kwargs: Any) -> Callable[[RunnerContext], Any]:
    """Opt-in runner backed by :func:`daedalus.offload.offload`.

    ``repo_root`` is pinned to the WORKTREE, so offload's snapshot / verify /
    rollback machinery operates entirely inside the isolated checkout.

    Deliberately not the default: :class:`TaskAttempt` refuses to construct
    without an explicit runner, so no attempt can quietly reach a model because
    a caller forgot an argument.
    """
    def _runner(ctx: RunnerContext) -> Any:
        from daedalus.offload import offload
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
        return offload(ctx.task.instruction, str(ctx.worktree), **kwargs)
    return _runner


# --------------------------------------------------------------------------- #
# the attempt                                                                  #
# --------------------------------------------------------------------------- #
class TaskAttempt:
    """Produce one candidate change for one task, outside the primary checkout.

    :meth:`run` NEVER applies its result. There is no code path in this class
    that writes the primary working tree -- see the module docstring for the
    three properties that make that structural rather than promised.
    """

    def __init__(self, task: TaskSpec, *,
                 runner: Callable[[RunnerContext], Any],
                 repo_root: str | Path | None = None,
                 gate: Callable[[RunnerContext], Any] | None = None,
                 ledger: SpineLedger | None = None,
                 ledger_path: str | Path | None = None,
                 cancel: Any = None,
                 worktree_manager: GitWorktreeManager | None = None,
                 keep_worktree: bool = False,
                 reap: bool = True,
                 artifact_dir: str | Path | None = None) -> None:
        if not isinstance(task, TaskSpec):
            raise TypeError("task must be a TaskSpec")
        if runner is None or not callable(runner):
            raise ValueError(
                "TaskAttempt requires an explicit runner callable; there is no "
                "implicit model-backed default (use offload_runner() to opt in)")
        if ledger is not None and ledger_path is not None:
            raise ValueError("pass ledger or ledger_path, not both")
        if task.gate_argv and str(task.gate_cwd) != ".":
            raise ValueError(
                "TaskSpec command gates currently require gate_cwd='.'; "
                "subdirectory execution is not implemented")
        self.task = task
        self.repo_root = Path(repo_root).resolve() if repo_root else ROOT
        self._runner = runner
        if gate is not None:
            self._gate = gate
        elif task.gate_argv:
            self._gate = command_gate(
                task.gate_argv,
                timeout_s=float(task.gate_timeout_s),
                name="queue-command")
        elif task.fail_to_pass or task.pass_to_pass:
            # FAIL_TO_PASS/PASS_TO_PASS beats the plain pytest_gate default but
            # loses to an explicit gate/gate_argv override, matching the
            # existing "explicit beats implicit" precedence above. Lazy import:
            # daedalus.eval.correctness imports daedalus.spine.attempt
            # (READ_ONLY_REPO_VERBS) at ITS module top level, so importing it
            # from THIS module's top level would be circular; by the time
            # __init__ actually runs, both modules are already fully loaded.
            # correctness_gate is the existing, tested instrument (its own
            # docstring: "Signature and return type match the attempt's gate
            # contract exactly") -- this wires it rather than re-deriving its
            # fail-closed-on-an-unverified-receipt behaviour here.
            from daedalus.eval.correctness import correctness_gate as _correctness_gate
            self._gate = _correctness_gate(
                {
                    "id": task.task_id,
                    "base_revision": task.base_revision,
                    "fail_to_pass": list(task.fail_to_pass),
                    "pass_to_pass": list(task.pass_to_pass),
                    "before_state": dict(task.correctness_before_state),
                },
                self.repo_root,
                timeout_s=float(task.gate_timeout_s))
        else:
            self._gate = pytest_gate(task.gate_paths)
        self._manager = worktree_manager or GitWorktreeManager(self.repo_root)
        self._is_cancelled = _as_predicate(cancel)
        self._keep_worktree = bool(keep_worktree)
        # Default ON because the leak is unbounded: one ref per attempt, in the
        # SHARED .git, forever. Off is for an operator who wants the branch left
        # behind for forensics -- the patch bytes are already persisted
        # separately, so this costs nothing but a ref.
        self._reap_enabled = bool(reap)
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
        # Filled in by run() from the fresh worktree, BEFORE the runner is
        # invoked. None until then, and None afterwards for a worktree whose
        # `.git` was not the expected pointer file.
        self._admin_dir: Path | None = None

    # -- entry point -------------------------------------------------------- #
    def run(self) -> AttemptResult:
        """Attempt the task and return an :class:`AttemptResult`. Never raises.

        The returned artifact is data. Applying it to the primary checkout is a
        separate, human-invoked act that this module intentionally does not
        provide.
        """
        started = time.monotonic()
        started_ts = _now_iso()

        def finish(state: str, **kw: Any) -> AttemptResult:
            return AttemptResult(
                state=state, task_id=self.task.task_id, started_ts=started_ts,
                finished_ts=_now_iso(), duration_s=time.monotonic() - started,
                effect_key=self.effect_key, branch=self.branch, **kw)

        # 1. storage, fail closed and BEFORE anything is recorded or created.
        try:
            require_storage(str(_existing_ancestor(self._manager.worktree_root)))
        except StorageUnavailable as e:
            return finish(STATE_STORAGE_UNAVAILABLE, error=str(e))
        except OSError as e:
            return finish(STATE_STORAGE_UNAVAILABLE,
                          error=f"storage_unavailable: {e}")

        if self._is_cancelled():
            return finish(STATE_CANCELLED, error="cancelled before any effect")

        # Resolving the base is a READ of the primary checkout, not an effect,
        # so it happens before the intent -- the payload can then name the exact
        # revision the candidate was built on.
        try:
            base_revision = self._resolve_base()
        except Exception as e:
            return finish(STATE_WORKTREE_FAILED,
                          error=f"could not resolve base revision: {e}")

        try:
            ledger = self._get_ledger()
        except Exception as e:
            # No durable record is possible, so no effect may be performed.
            return finish(STATE_WORKTREE_FAILED,
                          base_revision=base_revision,
                          error=f"spine ledger unavailable: {e}")

        try:
            result = self._run_with_ledger(ledger, base_revision, finish)
        finally:
            if self._owns_ledger:
                try:
                    ledger.close()
                except Exception:
                    pass

        # 9. reap the candidate branch -- and ONLY here.
        #
        # `git worktree add -b` writes a ref into the SHARED .git that nothing
        # removed, so an overnight loop left one ref per attempt forever. This
        # is the one safe moment to consider removing it: ordinary intents are
        # RESOLVED by the time `_run_with_ledger` returns, while a
        # `reconciliation_required` result is explicitly excluded by `_reap`.
        # Doing it inside cleanup's `finally:`
        # would be strictly worse than the leak, because the branch IS the
        # effect key -- the documented way to answer "did this attempt happen?"
        # after a crash is `git branch --list <effect_key>`, and cleanup runs
        # BEFORE resolution. That would open a window where an OPEN intent has
        # no findable effect.
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

        # A reconciliation result deliberately leaves both the TaskAttempt
        # intent and the worktree open.  Do not even ask the manager to reap:
        # the branch is the durable world-side effect key an operator needs to
        # inspect before deciding how to close the indeterminate execution.
        if (not self._reap_enabled
                or result.state == STATE_RECONCILIATION_REQUIRED):
            return result
        try:
            report = self._manager.reap_branches()
        except Exception as e:                  # noqa: BLE001 - reported, not raised
            return _replace(result,
                            reap_error=f"{type(e).__name__}: {e}")
        return _replace(result, reaped=tuple(report))

    # -- the recorded part -------------------------------------------------- #
    def _run_with_ledger(self, ledger: SpineLedger, base_revision: str,
                         finish: Callable[..., AttemptResult]) -> AttemptResult:
        # Resolve this typed dependency before recording an intent or creating
        # a worktree. If the kernel module itself cannot load, no attempt-side
        # effect has happened and the caller gets the ordinary exception.
        from daedalus.kernel.effects import EffectReconciliationRequired

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
        reconciliation: dict[str, str] | None = None

        try:
            if self._is_cancelled():
                state, error = STATE_CANCELLED, "cancelled before the runner ran"
            else:
                # 4. the work, inside the worktree and nowhere else.
                try:
                    runner_detail = self._runner(ctx)
                except EffectReconciliationRequired as exc:
                    state = STATE_RECONCILIATION_REQUIRED
                    error = str(exc)
                    reconciliation = {
                        "execution_id": exc.execution_id,
                        "start_receipt_sha256": exc.start_receipt_sha256,
                        "phase": exc.phase,
                    }
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
                    allowed = {
                        str(path).replace("\\", "/").removeprefix("./")
                        for path in self.task.target_paths
                    }
                    escaped = tuple(
                        path for path in artifact.changed_paths
                        if self.task.target_paths
                        and path.replace("\\", "/").removeprefix("./")
                        not in allowed)
                    if escaped:
                        state = STATE_GATES_FAILED
                        error = (
                            "artifact changed path(s) outside declared "
                            f"target_paths: {', '.join(escaped)}")
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
            if state == STATE_RECONCILIATION_REQUIRED:
                # The external outcome is indeterminate.  Preserve the exact
                # candidate workspace and its branch, and leave the enclosing
                # TaskAttempt intent INTENDED.  Cleanup/resolution would erase
                # the evidence needed to reconcile or falsely make a retry
                # appear safe.
                removed, cleanup_error = False, None
            else:
                # 8. cleanup, reported rather than swallowed.
                removed, cleanup_error = self._cleanup(worktree)

        if state == STATE_RECONCILIATION_REQUIRED:
            return finish(
                state,
                intent_id=intent.id,
                base_revision=base_revision,
                error=error,
                worktree_path=str(worktree),
                worktree_removed=removed,
                cleanup_error=cleanup_error,
                runner_detail=runner_detail,
                reconciliation=reconciliation,
            )

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
        return finish(state, intent_id=intent_id, artifact=artifact,
                      gates=gates, ledger_error=ledger_error, **kw)

    def _get_ledger(self) -> SpineLedger:
        if self._ledger is None:
            self._ledger = (
                SpineLedger(self._ledger_path)
                if self._ledger_path is not None else SpineLedger())
        return self._ledger


def run_attempt(task: TaskSpec, **kwargs: Any) -> AttemptResult:
    """Construct and run one :class:`TaskAttempt`. Returns, never raises."""
    return TaskAttempt(task, **kwargs).run()
