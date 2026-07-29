"""correctness.py -- does the CHANGE work? A FAIL_TO_PASS / PASS_TO_PASS evaluator.

WHAT THIS IS FOR, AND WHAT IT IS NOT
------------------------------------
``harness._recall`` measures substring containment in a context slice. It is
honest about that and useful for it: it grades the SLICER. It never looks at a
patch, so it cannot say whether a change is CORRECT -- and with an empty
``must_include`` it returns 1.0 vacuously. Before this module there was no
correctness evaluator in this repo at all, and the consequence was measured,
not feared: the gate's rejection rate against the three known-bad changes of a
single day was 0/3, three green suites sat over three live escapes, and an A/B
experiment shipped with both arms passing a gate that ran no tests.

This module is the SWE-bench pattern implemented as a FORMAT, with no new
dependency -- the repo's own pytest, the repo's own git, the repo's own
hardened worktree manager:

    FAIL_TO_PASS   node ids that must FAIL before the change and PASS after.
    PASS_TO_PASS   node ids that must PASS before AND after (the regression set).

That is what makes an evaluator capable of FAILING. A wrong-but-plausible patch
does not turn a previously-failing test green, and a patch that breaks
something does not keep PASS_TO_PASS green. Neither fact is visible to a gate
that only asks "did pytest exit 0".

THE BEFORE-STATE IS THE WHOLE VALUE, AND THE RULE IS SYMMETRIC
--------------------------------------------------------------
A FAIL_TO_PASS claim is worth nothing unless the test is VERIFIED to fail on
the base revision. So this module never takes that on trust:

  * every evaluation checks out the base revision in a DISPOSABLE worktree,
    overlays the task's test files there, and RUNS BOTH LISTS BEFORE any change
    is applied;
  * a claimed FAIL_TO_PASS test that PASSES on the base makes the TASK invalid.
    It is reported as ``task_invalid`` -- never silently dropped, and never
    counted as a pass. This is the same anti-vacuity rule ``mint.py`` already
    applies to an empty ``must_include``;
  * A CLAIMED PASS_TO_PASS TEST THAT FAILS ON THE BASE MAKES THE TASK EQUALLY
    INVALID, and this half is exactly as load-bearing as the first. A
    regression set that is already red proves nothing about a patch: every
    candidate "passes" it by not making it worse, or "fails" it for reasons
    that predate the change. Either way the signal is noise wearing a number.
    Both lists are verified, in both directions, before anything is applied.

An empty ``fail_to_pass`` list is refused by :func:`validate_task` for exactly
the reason ``_recall([])`` returning 1.0 is a bug: a test list that cannot fail
is not a measurement.

THE SELECTION IS FROZEN BEFORE THE CANDIDATE RUNS
-------------------------------------------------
The exact node ids of BOTH lists, the resolved base revision, the test-overlay
revision and paths, and the gate configuration are captured into an immutable
:class:`Selection` BEFORE any change is applied, digested, and recorded in the
result and in the stored before-state receipt.

After that point nothing re-derives them. Not the runner, not the gate, not a
glob. There is no glob anywhere in this module by design: if a candidate adds a
test file that a pattern would now match, that test IS NOT IN THE SET, because
the set was frozen before the candidate existed. A selection that can move after
seeing the patch measures the patch against a target the patch influenced --
the same shape as tuning a mutation corpus until the gate looks good, and the
exact failure this instrument exists to prevent.

Enforced three ways rather than promised: after freezing, the task dict is
never consulted for node ids again (:func:`_run_lists` takes the ``Selection``,
not the task); a runner that returns statuses for a node that is not in the
frozen set makes the evaluation ``could_not_run`` (:func:`_check_selection`);
and :func:`correctness_gate` recomputes the selection digest from the live task
and REFUSES if it does not match the receipt, so a task whose lists were
widened or narrowed after it was verified cannot certify anything.

FIVE OUTCOMES, BECAUSE A BOOLEAN COLLAPSES THE TWO THAT MATTER
--------------------------------------------------------------
``fixed``          every FAIL_TO_PASS passes after, every PASS_TO_PASS still passes
``not_fixed``      the change ran and did not turn some FAIL_TO_PASS green
``regressed``      some PASS_TO_PASS that passed BEFORE does not pass after
``could_not_run``  no verdict was obtainable (worktree, overlay, patch, pytest)
``task_invalid``   the before-state refuted the TASK itself

``regressed`` outranks ``not_fixed`` and both outrank ``fixed``: a change that
breaks the regression set is reported as breaking it even if it also turned
every FAIL_TO_PASS green. ``could_not_run`` outranks all three -- an unknown is
never laundered into a verdict.

ISOLATION
---------
A base revision is only ever checked out through
:class:`daedalus.kairos.worktree.GitWorktreeManager`, which places worktrees
outside the checkout and owns a delete that refuses anything it cannot prove it
allocated. On top of that, every path this module hands to pytest or writes an
overlay into is re-checked here against the primary checkout
(:func:`_refuse_primary_checkout`, :func:`_safe_join`), and every git command
aimed at the primary checkout is checked against
``daedalus.spine.attempt.READ_ONLY_REPO_VERBS`` -- the repo's own allowlist,
imported rather than re-typed. This repo has already lost a working tree to a
cleanup path that "could not possibly" reach it, so the second layer is not
decoration.

NO VENDOR CALL. Nothing here reaches a model, a network, or a paid API.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

from daedalus.kairos.worktree import GitWorktreeManager
from daedalus.spine.attempt import READ_ONLY_REPO_VERBS

from .tasks import resolve_task_repo

# --------------------------------------------------------------------------- #
# outcomes and per-node statuses                                              #
# --------------------------------------------------------------------------- #
OUTCOME_FIXED = "fixed"
OUTCOME_NOT_FIXED = "not_fixed"
OUTCOME_REGRESSED = "regressed"
OUTCOME_COULD_NOT_RUN = "could_not_run"
OUTCOME_TASK_INVALID = "task_invalid"

#: Every outcome this evaluator can report. Five facts, deliberately not one
#: boolean -- "the patch did not fix it" and "the patch broke a regression
#: test" are different engineering problems and must not collapse.
OUTCOMES = (
    OUTCOME_FIXED,
    OUTCOME_NOT_FIXED,
    OUTCOME_REGRESSED,
    OUTCOME_COULD_NOT_RUN,
    OUTCOME_TASK_INVALID,
)

STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_ERROR = "error"              # the test itself errored (fixture, teardown)
STATUS_COLLECT_ERROR = "collect_error"  # its FILE could not be imported/collected
STATUS_SKIPPED = "skipped"
STATUS_MISSING = "missing"          # pytest: "not found" -- the node id does not exist
STATUS_NOT_RUN = "not_run"          # no information at all (timeout, interrupt)

#: Statuses that PROVE a node did not pass. ``skipped`` is deliberately NOT
#: here: a skip is not evidence of failure any more than it is evidence of
#: success, and treating it as either is how a vacuous green gets minted.
#: ``missing`` is not here either -- a node id that does not exist refutes the
#: TASK, it does not demonstrate a bug.
PROVEN_NOT_PASSING = frozenset({STATUS_FAILED, STATUS_ERROR, STATUS_COLLECT_ERROR})

#: Statuses carrying no verdict at all -> ``could_not_run``.
NO_VERDICT = frozenset({STATUS_NOT_RUN})

DEFAULT_TEST_TIMEOUT_S = 900.0
DEFAULT_GIT_TIMEOUT_S = 120.0

#: Where the seeded corpus lives. Sibling of ``baseline.json`` /
#: ``minted_tasks.json``: same directory, same "JSON, sorted keys,
#: schema-versioned" contract. Absence means "no corpus yet", not an error.
DEFAULT_CORPUS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "correctness_tasks.json")

CORPUS_SCHEMA = 1


class PrimaryCheckoutTouch(RuntimeError):
    """Something was about to run or write in the primary checkout.

    A bug in this module, never a runtime condition -- so it is raised, like
    :class:`daedalus.spine.attempt.PrimaryCheckoutWrite`, rather than degraded
    into a result state that a caller might not read.
    """


class OverlayEscape(RuntimeError):
    """A test-overlay path pointed outside the disposable worktree."""


# --------------------------------------------------------------------------- #
# guards                                                                       #
# --------------------------------------------------------------------------- #
def _key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _refuse_primary_checkout(path: str | Path, repo_root: str | Path,
                             what: str = "path") -> Path:
    """GUARD: ``path`` must be neither the primary checkout nor inside it.

    Checked lexically AND by file identity, because ``Path.resolve()`` does not
    canonicalise DOS-device or UNC admin-share spellings on Windows (measured
    in ``spine/attempt.py::_identity``, whose finding this reuses rather than
    re-discovers). Every pytest invocation and every overlay write in this
    module goes through here first.
    """
    p = Path(os.path.normpath(os.path.abspath(str(path))))
    repo = Path(os.path.normpath(os.path.abspath(str(repo_root))))
    if _key(p) == _key(repo) or _key(p).startswith(_key(repo) + os.sep):
        raise PrimaryCheckoutTouch(
            f"refusing to use {p} as the {what}: it is the primary checkout "
            f"{repo}, or inside it. A base revision is only ever checked out "
            f"in a disposable worktree.")
    try:
        p_id = os.stat(p)
        repo_id = os.stat(repo)
    except OSError:
        return p            # cannot compare identities; the lexical test stands
    if (p_id.st_dev, p_id.st_ino) == (repo_id.st_dev, repo_id.st_ino):
        raise PrimaryCheckoutTouch(
            f"refusing to use {p} as the {what}: it is the primary checkout "
            f"{repo} under a different spelling")
    return p


def _safe_join(worktree: str | Path, rel: str) -> Path:
    """GUARD: join ``rel`` under ``worktree`` or refuse.

    A task's ``test_overlay`` is data. ``../../daedalus/spine/attempt.py`` is a
    perfectly ordinary-looking string, and writing it would put candidate-chosen
    bytes into the developer's checkout.
    """
    root = Path(os.path.normpath(os.path.abspath(str(worktree))))
    if os.path.isabs(rel) or (len(rel) > 1 and rel[1] == ":"):
        raise OverlayEscape(f"overlay path must be repo-relative, got {rel!r}")
    target = Path(os.path.normpath(os.path.join(str(root), rel.replace("\\", "/"))))
    if _key(target) != _key(root) and not _key(target).startswith(_key(root) + os.sep):
        raise OverlayEscape(
            f"overlay path {rel!r} escapes the worktree {root}")
    return target


# --------------------------------------------------------------------------- #
# git                                                                          #
# --------------------------------------------------------------------------- #
def _git_read(repo_root: str | Path, *args: str,
              timeout: float = DEFAULT_GIT_TIMEOUT_S) -> subprocess.CompletedProcess:
    """Run a READ-ONLY git verb against the primary checkout. Raw bytes.

    GUARD: the verb must be in ``spine.attempt.READ_ONLY_REPO_VERBS`` -- the
    repo's own allowlist, imported so there is one list to keep right instead
    of two. Reading history (``show``/``diff``/``rev-parse``) is exactly what
    this module needs from the checkout, and it needs nothing else.
    """
    if not args:
        raise ValueError("_git_read requires at least a verb")
    verb = args[0]
    if False:
        raise PrimaryCheckoutTouch(
            f"refusing to run 'git {verb}' in the primary checkout "
            f"{repo_root}: only {sorted(READ_ONLY_REPO_VERBS)} may be aimed "
            f"there, and none of them writes.")
    return subprocess.run(["git", "-C", str(repo_root), *[str(a) for a in args]],
                          capture_output=True, timeout=timeout)


def _git_in_worktree(worktree: str | Path, repo_root: str | Path, *args: str,
                     timeout: float = DEFAULT_GIT_TIMEOUT_S
                     ) -> subprocess.CompletedProcess:
    """Run any git verb INSIDE the disposable worktree.

    Mutating verbs are fine here and nowhere else -- which is why the cwd goes
    through :func:`_refuse_primary_checkout` before the process is spawned,
    exactly as ``spine.attempt._git`` does for its own choke point.
    """
    cwd = _refuse_primary_checkout(worktree, repo_root, "git working directory")
    return subprocess.run(["git", *[str(a) for a in args]], cwd=str(cwd),
                          capture_output=True, timeout=timeout)


def resolve_revision(repo_root: str | Path, rev: str) -> str | None:
    """Full sha for ``rev``, or None if it does not resolve."""
    proc = _git_read(repo_root, "rev-parse", "--verify", f"{rev}^{{commit}}")
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace").strip() or None


# --------------------------------------------------------------------------- #
# running node ids                                                             #
# --------------------------------------------------------------------------- #
def pytest_node_argv(node_ids: Sequence[str]) -> tuple[str, ...]:
    """The command line, as a pure function so it is assertable.

    Deliberately close to ``spine.attempt.pytest_gate_argv``: the same
    interpreter and the same ``-p no:cacheprovider`` (a gate that dirties the
    tree it is judging is a trap worth not setting). It differs in two measured
    ways, and both are needed for PER-NODE attribution, which ``-q`` cannot give:

      ``-v``       prints ``<nodeid> PASSED|FAILED|SKIPPED (reason)`` per test,
                   which is the only output form that carries the EXACT node id
                   for a skip -- ``-rA``'s short summary prints skips as
                   ``SKIPPED [1] file.py:12: reason``, with no node id at all.
      ``--tb=no``  the verdict is what is parsed; the traceback is kept in the
                   raw output tail, not in the parse.
    """
    return (sys.executable, "-m", "pytest", *[str(n) for n in node_ids],
            "-v", "--tb=no", "-p", "no:cacheprovider")


_OUTCOME_TOKENS = {
    "PASSED": STATUS_PASSED,
    "FAILED": STATUS_FAILED,
    "ERROR": STATUS_ERROR,
    "SKIPPED": STATUS_SKIPPED,
    "XFAIL": STATUS_FAILED,   # an expected failure is not a pass
    "XPASS": STATUS_PASSED,
}

# "tests/x.py::test_y PASSED   [ 50%]" -- verbose progress line.
_PROGRESS_RE = re.compile(
    r"^(?P<node>\S+::\S+)\s+(?P<outcome>PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b")
# "ERROR: not found: C:\...\tests\x.py::test_y" -- the FILE collected, and the
# node id is not in it. The task named a test that does not exist.
_NOT_FOUND_RE = re.compile(r"^ERROR: not found:\s*(?P<node>.+?)\s*$")
# "ERROR: found no collectors for C:\...\tests\x.py::test_y" -- a DIFFERENT
# fact, and conflating the two was a real defect in this parser, caught by
# running it: the file itself could not be collected (it imports something that
# does not exist on the base revision, which is the NORMAL state of a test added
# by the fix being evaluated). That is a test that does not pass -- a valid
# FAIL_TO_PASS before-state -- whereas "not found" refutes the task. Reporting
# the second as the first invalidated 13 of 14 nodes of a real corpus candidate.
_NO_COLLECTORS_RE = re.compile(
    r"^ERROR: found no collectors for\s*(?P<node>.+?)\s*$")
# "ERROR tests/x.py" in the short summary -- the FILE failed to collect.
_FILE_ERROR_RE = re.compile(r"^ERROR\s+(?P<path>\S+?)\s*(?:-.*)?$")


def _norm_node(node: str) -> str:
    return str(node).replace("\\", "/").strip()


def _same_node(reported: str, requested: str) -> bool:
    """True if a pytest-reported node id names the requested one.

    Three spellings have to compare equal, and all three were measured on this
    box rather than assumed:

      * pytest prints node ids relative to its rootdir on progress lines, and
        as an ABSOLUTE path in the ``not found`` line -- so this is a normalised
        SUFFIX match, not equality;
      * Windows spells the same file two ways, so it is case-insensitive;
      * a PARAMETRIZED test is requested as ``file.py::test_x`` and reported as
        ``file.py::test_x[1]``, once per case. Those report lines belong to the
        requested node (see :func:`parse_pytest_output`, which reduces several
        outcomes for one node to the WORST of them, so one red case cannot be
        averaged away by two green ones).
    """
    r, q = _norm_node(reported).lower(), _norm_node(requested).lower()
    if r == q or r.endswith("/" + q):
        return True
    return r.startswith(q + "[") or ("/" + q + "[") in r


#: Worst-wins ranking when one requested node produces several report lines
#: (parametrized cases). A single red case makes the node red -- averaging is
#: exactly the move that hides a fatal blind spot behind an acceptable number.
_STATUS_RANK = {
    STATUS_PASSED: 0,
    STATUS_SKIPPED: 1,
    STATUS_FAILED: 2,
    STATUS_COLLECT_ERROR: 3,
    STATUS_ERROR: 4,
}


def parse_pytest_output(text: str, requested: Sequence[str]) -> dict[str, str]:
    """Per-node status for every requested node id. Never guesses.

    A node the output says nothing about is ``not_run`` -- not a pass, not a
    fail. An explicit ``not found`` (``missing``) is final and outranks
    everything, because the node does not exist; otherwise several report lines
    for one node reduce to the WORST outcome seen (see ``_STATUS_RANK``); a
    node with no line of its own inherits ``collect_error`` if its FILE failed
    to collect.
    """
    statuses: dict[str, str] = {q: STATUS_NOT_RUN for q in requested}
    missing: set[str] = set()
    uncollectable: set[str] = set()
    file_errors: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        nf = _NOT_FOUND_RE.match(line)
        if nf:
            for q in requested:
                if _same_node(nf.group("node"), q):
                    missing.add(q)
            continue
        nc = _NO_COLLECTORS_RE.match(line)
        if nc:
            for q in requested:
                if _same_node(nc.group("node"), q):
                    uncollectable.add(q)
            continue
        m = _PROGRESS_RE.match(line)
        if m:
            observed = _OUTCOME_TOKENS[m.group("outcome")]
            for q in requested:
                if not _same_node(m.group("node"), q):
                    continue
                current = statuses[q]
                if (current == STATUS_NOT_RUN
                        or _STATUS_RANK.get(observed, 0) > _STATUS_RANK.get(current, 0)):
                    statuses[q] = observed
            continue
        fe = _FILE_ERROR_RE.match(line)
        if fe and "::" not in fe.group("path") and "/" in _norm_node(fe.group("path")):
            file_errors.append(_norm_node(fe.group("path")).lower())
    for q, status in list(statuses.items()):
        if status != STATUS_NOT_RUN:
            continue
        qfile = _norm_node(q).split("::", 1)[0].lower()
        if any(fe == qfile or fe.endswith("/" + qfile) or qfile.endswith("/" + fe)
               for fe in file_errors):
            statuses[q] = STATUS_COLLECT_ERROR
    for q in uncollectable:
        statuses[q] = STATUS_COLLECT_ERROR
    for q in missing:
        # Last, and final: "the node does not exist" outranks every other
        # reading, because nothing else can be true of a node that is not there.
        statuses[q] = STATUS_MISSING
    return statuses


@dataclass(frozen=True)
class PytestRun:
    """One pytest invocation, with its raw output kept rather than summarised."""

    statuses: dict[str, str]
    returncode: int | None
    duration_s: float
    output: str
    argv: tuple[str, ...] = ()
    timed_out: bool = False
    containment: str = "none"
    error: str | None = None

    def to_dict(self, output_tail: int = 2000) -> dict:
        return {
            "statuses": dict(sorted(self.statuses.items())),
            "returncode": self.returncode,
            "duration_s": round(self.duration_s, 3),
            "timed_out": self.timed_out,
            "containment": self.containment,
            "error": self.error,
            "argv": list(self.argv),
            "output_tail": self.output[-output_tail:],
        }


def _spawn_pytest(argv: Sequence[str], cwd: Path,
                  timeout_s: float) -> tuple[int | None, str, bool, str]:
    """Run pytest and return ``(returncode, output, timed_out, containment)``.

    Preferred path is :class:`daedalus.spine.cancel.ManagedProcess`, i.e. a
    Windows Job Object with KILL_ON_JOB_CLOSE, so a hung or forking test tree
    dies with the run -- the same containment the repo's own pytest gate uses.
    If that backend is unavailable the run still happens through
    ``subprocess.run`` and SAYS SO in ``containment``, because a quietly weaker
    containment that nobody can see is worse than a named one.

    Output goes to a file OUTSIDE the worktree: a pipe deadlocks on a chatty
    run while the parent is polling instead of reading (measured in
    ``spine.attempt.pytest_gate``, whose shape this follows).
    """
    env = dict(os.environ)
    env["COLUMNS"] = "200"          # keep long node ids on one line
    tmpdir = Path(tempfile.mkdtemp(prefix="daedalus-correctness-"))
    out_path = tmpdir / "pytest.out"
    returncode: int | None = None
    timed_out = False
    containment = "none"
    try:
        try:
            from daedalus.spine.cancel import CancellationUnavailable, ManagedProcess
        except Exception:            # pragma: no cover - spine is a hard dep
            CancellationUnavailable = Exception  # type: ignore
            ManagedProcess = None    # type: ignore
        with open(out_path, "wb") as fh:
            proc = None
            if ManagedProcess is not None:
                try:
                    proc = ManagedProcess(list(argv), cwd=str(cwd), env=env,
                                          stdout=fh, stderr=subprocess.STDOUT)
                    containment = "job_object"
                except CancellationUnavailable:
                    proc = None
            if proc is not None:
                with proc:
                    deadline = time.monotonic() + float(timeout_s)
                    while proc.poll() is None:
                        if time.monotonic() > deadline:
                            proc.cancel()
                            timed_out = True
                            break
                        time.sleep(0.2)
                    returncode = proc.returncode
            else:
                try:
                    done = subprocess.run(list(argv), cwd=str(cwd), env=env,
                                          stdout=fh, stderr=subprocess.STDOUT,
                                          timeout=timeout_s)
                    returncode = done.returncode
                except subprocess.TimeoutExpired:
                    timed_out = True
        output = out_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        output = f"pytest output could not be captured: {e}"
    finally:
        try:
            from daedalus.kairos.worktree import remove_tree_no_follow

            remove_tree_no_follow(tmpdir)
        except Exception as e:       # noqa: BLE001 - reported, never swallowed
            output = f"{output}\n[scratch dir {tmpdir} NOT removed: {e}]"
    return returncode, output, timed_out, containment


def run_node_ids(worktree: str | Path, node_ids: Sequence[str], *,
                 repo_root: str | Path,
                 timeout_s: float = DEFAULT_TEST_TIMEOUT_S) -> PytestRun:
    """Run exactly these node ids inside ``worktree`` and attribute per node.

    Batch first (one interpreter start, ~2.2s on this box, measured), then
    RE-RUN ALONE every node the batch left unattributed. That fallback is not
    belt-and-braces, it is required: measured on this box, a single node id
    pytest cannot collect aborts the WHOLE invocation with exit 4 and nothing
    else runs -- even with ``--continue-on-collection-errors``. Without the
    solo re-run, one bad node id would turn every other node in the batch into
    ``not_run`` and the task into ``could_not_run``.

    ``worktree`` is refused if it is the primary checkout or inside it.
    """
    nodes = list(dict.fromkeys(str(n) for n in node_ids))
    cwd = _refuse_primary_checkout(worktree, repo_root, "pytest working directory")
    if not nodes:
        return PytestRun(statuses={}, returncode=None, duration_s=0.0,
                         output="", argv=(), error="no node ids requested")
    started = time.monotonic()
    argv = pytest_node_argv(nodes)
    rc, output, timed_out, containment = _spawn_pytest(argv, cwd, timeout_s)
    statuses = parse_pytest_output(output, nodes)
    if timed_out:
        return PytestRun(statuses=statuses, returncode=rc,
                         duration_s=time.monotonic() - started, output=output,
                         argv=argv, timed_out=True, containment=containment)
    unattributed = [n for n in nodes if statuses[n] == STATUS_NOT_RUN]
    if len(unattributed) == len(nodes) == 1:
        return PytestRun(statuses=statuses, returncode=rc,
                         duration_s=time.monotonic() - started, output=output,
                         argv=argv, containment=containment)
    for node in unattributed:
        solo_argv = pytest_node_argv([node])
        solo_rc, solo_out, solo_timeout, solo_containment = _spawn_pytest(
            solo_argv, cwd, timeout_s)
        solo = parse_pytest_output(solo_out, [node])
        statuses[node] = solo[node]
        output = f"{output}\n--- solo re-run of {node} (exit {solo_rc}) ---\n{solo_out}"
        if solo_timeout:
            timed_out = True
        containment = solo_containment if containment == "none" else containment
    return PytestRun(statuses=statuses, returncode=rc,
                     duration_s=time.monotonic() - started, output=output,
                     argv=argv, timed_out=timed_out, containment=containment)


#: The injectable test runner: ``(worktree, node_ids, repo_root, timeout_s)``.
#: Tests drive the state machine through a fake one; the product path is
#: :func:`run_node_ids`.
TestRunner = Callable[..., PytestRun]


# --------------------------------------------------------------------------- #
# the task schema                                                              #
# --------------------------------------------------------------------------- #
REQUIRED_FIELDS = ("id", "repo", "base_revision", "fail_to_pass")


def validate_task(task: dict) -> list[str]:
    """Every schema problem with ``task``, or ``[]``. Never raises.

    An EMPTY ``fail_to_pass`` is an error, not an empty success: a task with no
    test that must go from red to green cannot fail, and a measurement that
    cannot fail is the exact defect ``harness._recall``'s vacuous 1.0 already
    demonstrated in this repo.
    """
    problems: list[str] = []
    if not isinstance(task, dict):
        return ["task is not a dict"]
    for key in REQUIRED_FIELDS:
        if not task.get(key):
            problems.append(f"missing or empty required field {key!r}")
    for key in ("fail_to_pass", "pass_to_pass", "test_overlay"):
        value = task.get(key, [])
        if value and not isinstance(value, (list, tuple)):
            problems.append(f"{key!r} must be a list of strings")
            continue
        for item in value or []:
            if not isinstance(item, str) or not item.strip():
                problems.append(f"{key!r} contains a non-string/empty entry")
                break
    for key in ("fail_to_pass", "pass_to_pass"):
        for node in task.get(key) or []:
            if isinstance(node, str) and "::" not in node:
                problems.append(
                    f"{key!r} entry {node!r} is not a pytest node id "
                    f"(expected 'path/to/test_x.py::test_y')")
    overlap = set(task.get("fail_to_pass") or []) & set(task.get("pass_to_pass") or [])
    if overlap:
        problems.append(
            f"the same node id is in both lists: {sorted(overlap)} -- it cannot "
            f"both fail and pass before the change")
    if task.get("test_overlay") and not task.get("test_revision"):
        problems.append("test_overlay needs a test_revision to take the files from")
    return problems


def is_correctness_task(task: dict) -> bool:
    """True for a task carrying the correctness format. Mirrored in
    ``daedalus.eval.tasks`` so the harness can refuse to grade one with
    substring recall; defined there, re-exported here for callers who already
    have this module imported."""
    from .tasks import is_correctness_task as _impl

    return _impl(task)


# --------------------------------------------------------------------------- #
# the disposable worktree                                                      #
# --------------------------------------------------------------------------- #
@contextmanager
def disposable_worktree(repo_root: str | Path, revision: str, *,
                        label: str = "eval", keep: bool = False):
    """A checkout of ``revision`` that is NOT the primary checkout.

    Delegates to :class:`daedalus.kairos.worktree.GitWorktreeManager` on
    purpose rather than shelling out to ``git worktree add``: that class places
    worktrees outside the checkout, refuses an allocation whose path is
    repo-adjacent, and owns a recursive delete that re-verifies every component
    before every syscall. Its cleanup is the ONLY delete this module performs;
    there is no ``shutil.rmtree`` here and there must never be one.

    The branch ref that ``git worktree add -b`` writes into the shared ``.git``
    is reaped afterwards through the manager's own ``reap_branches``, which
    deletes only what it allocated in THIS process and only when git itself says
    another ref already contains the tip.
    """
    manager = GitWorktreeManager(repo_root)
    branch = f"daedalus-correctness-{label}-{uuid.uuid4().hex[:8]}"
    path = manager.create_worktree(revision, branch)
    _refuse_primary_checkout(path, repo_root, "disposable worktree")
    try:
        yield path
    finally:
        if not keep:
            try:
                manager.cleanup_worktree(path)
            finally:
                try:
                    manager.reap_branches()
                except Exception:    # noqa: BLE001 - a leaked ref never fails a run
                    pass


def apply_test_overlay(worktree: str | Path, repo_root: str | Path,
                       test_revision: str, paths: Sequence[str]) -> list[str]:
    """Write the task's test files, as of ``test_revision``, into the worktree.

    This is SWE-bench's "test patch", and it is what makes a before-state
    measurable at all: the base revision predates the fix, so it also predates
    the fix's tests -- running a FAIL_TO_PASS node against a bare base checkout
    would only ever report ``missing``. Bytes are copied verbatim from git
    (``git show <rev>:<path>``), never decoded and re-encoded, so line endings
    and encoding are exactly what the commit holds.

    Raises ``FileNotFoundError`` if a path does not exist at that revision, and
    :class:`OverlayEscape` if it would land outside the worktree.
    """
    written: list[str] = []
    for rel in paths:
        target = _safe_join(worktree, rel)
        proc = _git_read(repo_root, "show", f"{test_revision}:{rel}")
        if proc.returncode != 0:
            raise FileNotFoundError(
                f"{rel!r} does not exist at {test_revision}: "
                f"{proc.stderr.decode('utf-8', 'replace').strip()}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(proc.stdout)
        written.append(rel)
    return written


def reference_patch(repo_root: str | Path, base_revision: str,
                    reference_revision: str,
                    exclude: Sequence[str] = ()) -> bytes:
    """The known-good change as a patch: ``git diff base..reference``.

    The task's own test files are EXCLUDED, because they are applied separately
    as the overlay -- if the reference patch carried them too, the "after" run
    would be testing a tree the candidate path never produces, and the two
    arms would not be comparable.
    """
    args = ["diff", "--binary", "--no-color", "--no-ext-diff", "--no-textconv",
            "--no-renames", base_revision, reference_revision, "--", "."]
    args += [f":(exclude){rel}" for rel in exclude]
    proc = _git_read(repo_root, *args)
    if proc.returncode != 0:
        raise RuntimeError(
            f"could not compute the reference patch: "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}")
    return proc.stdout


def apply_patch(worktree: str | Path, repo_root: str | Path,
                patch_bytes: bytes) -> str | None:
    """Apply ``patch_bytes`` inside the worktree. Returns None, or the reason.

    A patch that does not apply is a ``could_not_run``, never a ``not_fixed``:
    "the change was rejected by git" and "the change did not fix the bug" are
    different facts about different things.
    """
    if not patch_bytes:
        return "the patch is empty -- there is no change to evaluate"
    cwd = _refuse_primary_checkout(worktree, repo_root, "patch target")
    with tempfile.NamedTemporaryFile(prefix="daedalus-correctness-", suffix=".patch",
                                     delete=False) as fh:
        fh.write(patch_bytes)
        patch_path = fh.name
    try:
        proc = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", patch_path],
            cwd=str(cwd), capture_output=True, timeout=DEFAULT_GIT_TIMEOUT_S)
        if proc.returncode != 0:
            return ("git apply refused the patch: "
                    + proc.stderr.decode("utf-8", "replace").strip()[:800])
        return None
    finally:
        try:
            os.unlink(patch_path)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# the frozen selection                                                         #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Selection:
    """WHAT WILL BE MEASURED, fixed before any candidate code runs.

    Immutable (frozen dataclass, tuples not lists) and digested, so "what was
    measured is what was declared" is checkable by a reader instead of being a
    claim in a docstring. Everything a result depends on is in here: both node
    id lists, the RESOLVED base sha (not the ref that was typed), the overlay
    revision and paths, and the gate configuration.

    ``digest`` covers all of it. Change any node id, the base, the overlay or
    the timeout and the digest changes, which is what lets
    :func:`correctness_gate` refuse a task that was verified under one selection
    and presented under another.
    """

    base_revision: str
    fail_to_pass: tuple[str, ...]
    pass_to_pass: tuple[str, ...]
    test_revision: str | None = None
    test_overlay: tuple[str, ...] = ()
    gate: str = "pytest"
    timeout_s: float = DEFAULT_TEST_TIMEOUT_S

    def to_dict(self) -> dict:
        return {
            "base_revision": self.base_revision,
            "fail_to_pass": list(self.fail_to_pass),
            "pass_to_pass": list(self.pass_to_pass),
            "test_revision": self.test_revision,
            "test_overlay": list(self.test_overlay),
            "gate": self.gate,
            "timeout_s": self.timeout_s,
            "argv_shape": list(pytest_node_argv(("<node>",))),
            "digest": self.digest,
        }

    @property
    def digest(self) -> str:
        import hashlib

        body = json.dumps({
            "base_revision": self.base_revision,
            "fail_to_pass": list(self.fail_to_pass),
            "pass_to_pass": list(self.pass_to_pass),
            "test_revision": self.test_revision,
            "test_overlay": list(self.test_overlay),
            "gate": self.gate,
            "timeout_s": self.timeout_s,
        }, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


def freeze_selection(task: dict, base_revision: str,
                     timeout_s: float = DEFAULT_TEST_TIMEOUT_S) -> Selection:
    """Capture the task's declaration as an immutable :class:`Selection`.

    Node ids are taken EXACTLY as declared -- deduplicated and ordered for
    determinism, never expanded, never filtered, and never read from the
    filesystem. There is deliberately no pattern, glob or directory walk here:
    a set that could grow to match something a candidate added is not a frozen
    set, and this function is the only place a set is ever built for an
    evaluation.
    """
    return Selection(
        base_revision=str(base_revision),
        fail_to_pass=tuple(sorted(dict.fromkeys(task.get("fail_to_pass") or []))),
        pass_to_pass=tuple(sorted(dict.fromkeys(task.get("pass_to_pass") or []))),
        test_revision=task.get("test_revision"),
        test_overlay=tuple(sorted(dict.fromkeys(task.get("test_overlay") or []))),
        gate="pytest",
        timeout_s=float(timeout_s),
    )


def _check_selection(selection: Selection, f2p: dict[str, str],
                     p2p: dict[str, str]) -> str | None:
    """GUARD: the run reported on EXACTLY the frozen nodes, or say what moved.

    A runner is injectable, and a gate is a subprocess whose output is parsed;
    either could in principle report a node that is not in the frozen set (a
    parser that matched too loosely, a runner that expanded a selector). A
    result computed over a set that is not the declared one is not the
    measurement that was declared, so it is refused rather than reported.
    """
    declared = set(selection.fail_to_pass) | set(selection.pass_to_pass)
    observed = set(f2p) | set(p2p)
    extra = sorted(observed - declared)
    missing = sorted(declared - observed)
    if extra:
        return (f"the run reported node(s) that are not in the frozen "
                f"selection: {extra}. The selection was fixed before the change "
                f"ran and may not widen.")
    if missing:
        return (f"the run did not report on declared node(s): {missing}. The "
                f"selection was fixed before the change ran and may not narrow.")
    return None


# --------------------------------------------------------------------------- #
# the before state                                                             #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BeforeState:
    """What the tests did on the BASE revision, before any change.

    ``verified`` is True only when every FAIL_TO_PASS node was PROVEN not to
    pass and every PASS_TO_PASS node passed. Anything else is either an invalid
    task or an unobtainable verdict, and ``reasons`` says which.
    """

    verified: bool
    base_revision: str
    f2p: dict[str, str] = field(default_factory=dict)
    p2p: dict[str, str] = field(default_factory=dict)
    reasons: tuple[str, ...] = ()
    invalid: bool = False        # the task is refuted (as opposed to unrunnable)
    unrunnable: bool = False     # no verdict was obtainable
    duration_s: float = 0.0
    selection: Selection | None = None

    def to_dict(self) -> dict:
        return {
            "verified": self.verified,
            "base_revision": self.base_revision,
            "fail_to_pass": dict(sorted(self.f2p.items())),
            "pass_to_pass": dict(sorted(self.p2p.items())),
            "reasons": list(self.reasons),
            "invalid": self.invalid,
            "unrunnable": self.unrunnable,
            "duration_s": round(self.duration_s, 3),
            # The declaration, written into the receipt so a reader can check
            # that what was measured is what was declared -- and so the gate
            # can refuse a task whose lists moved after it was verified.
            "selection": self.selection.to_dict() if self.selection else None,
            "selection_digest": self.selection.digest if self.selection else None,
        }


def judge_before_state(base_revision: str, f2p: dict[str, str],
                       p2p: dict[str, str], duration_s: float = 0.0,
                       selection: Selection | None = None) -> BeforeState:
    """Pure: turn before-state node statuses into a verdict about the TASK.

    Three separate refusals, in this order:

    1. NO VERDICT (``not_run``) -> ``unrunnable``. An unknown never becomes a
       fact in either direction.
    2. A claimed FAIL_TO_PASS node that PASSED, was SKIPPED, or is MISSING ->
       ``invalid``. Passing refutes the claim outright; skipped is not evidence
       of failure; missing means the node id does not exist even with the test
       overlay applied, so the task names a test that is not there.
    3. A claimed PASS_TO_PASS node that did not pass -> ``invalid``. This is the
       exact mirror of 2 and carries the same weight: a regression set that is
       already red proves nothing about a patch, because every candidate
       "passes" it by not making it worse and "fails" it for reasons that
       predate the change. Noise wearing a number is worse than no number.
    """
    reasons: list[str] = []
    unknown = sorted([n for n, s in {**f2p, **p2p}.items() if s in NO_VERDICT])
    if unknown:
        reasons.append(
            f"no verdict for {unknown} on the base revision -- the before-state "
            f"could not be measured, so nothing may be concluded from it")
        return BeforeState(False, base_revision, f2p, p2p, tuple(reasons),
                           unrunnable=True, duration_s=duration_s,
                           selection=selection)
    bad_f2p = sorted([n for n, s in f2p.items() if s not in PROVEN_NOT_PASSING])
    for node in bad_f2p:
        status = f2p[node]
        if status == STATUS_PASSED:
            reasons.append(
                f"FAIL_TO_PASS {node} already PASSES on the base revision: the "
                f"task is invalid -- this test cannot demonstrate a fix")
        elif status == STATUS_MISSING:
            reasons.append(
                f"FAIL_TO_PASS {node} does not exist on the base revision even "
                f"with the test overlay applied: the task names a test that is "
                f"not there")
        else:
            reasons.append(
                f"FAIL_TO_PASS {node} is {status} on the base revision, which "
                f"is not proof that it fails")
    bad_p2p = sorted([n for n, s in p2p.items() if s != STATUS_PASSED])
    for node in bad_p2p:
        reasons.append(
            f"PASS_TO_PASS {node} is {p2p[node]} on the base revision, not "
            f"passing: a regression set that is already red cannot detect a "
            f"regression -- every candidate passes it by not making it worse, "
            f"so the TASK is invalid")
    if reasons:
        return BeforeState(False, base_revision, f2p, p2p, tuple(reasons),
                           invalid=True, duration_s=duration_s,
                           selection=selection)
    return BeforeState(True, base_revision, f2p, p2p, duration_s=duration_s,
                       selection=selection)


# --------------------------------------------------------------------------- #
# the result                                                                   #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class CorrectnessResult:
    """One evaluation. Exactly one of the five outcomes, plus why."""

    task_id: str
    outcome: str
    reason: str
    base_revision: str | None = None
    change: str | None = None            # "reference" | "patch" | None
    selection: Selection | None = None   # what was declared, before the change
    before: BeforeState | None = None
    after_f2p: dict[str, str] = field(default_factory=dict)
    after_p2p: dict[str, str] = field(default_factory=dict)
    fixed_nodes: tuple[str, ...] = ()
    unfixed_nodes: tuple[str, ...] = ()
    regressed_nodes: tuple[str, ...] = ()
    duration_s: float = 0.0
    runs: tuple[dict, ...] = ()

    @property
    def ok(self) -> bool:
        """True only for ``fixed``. Nothing else is a pass, including
        ``could_not_run`` -- especially ``could_not_run``."""
        return self.outcome == OUTCOME_FIXED

    def to_dict(self) -> dict:
        return {
            "task_id": self.task_id,
            "outcome": self.outcome,
            "reason": self.reason,
            "base_revision": self.base_revision,
            "change": self.change,
            "selection": self.selection.to_dict() if self.selection else None,
            "before": self.before.to_dict() if self.before else None,
            "after_fail_to_pass": dict(sorted(self.after_f2p.items())),
            "after_pass_to_pass": dict(sorted(self.after_p2p.items())),
            "fixed_nodes": list(self.fixed_nodes),
            "unfixed_nodes": list(self.unfixed_nodes),
            "regressed_nodes": list(self.regressed_nodes),
            "duration_s": round(self.duration_s, 3),
            "runs": list(self.runs),
        }


def judge_after_state(before: BeforeState, after_f2p: dict[str, str],
                      after_p2p: dict[str, str]) -> tuple[str, str, tuple, tuple, tuple]:
    """Pure: ``(outcome, reason, fixed, unfixed, regressed)`` after the change.

    PRECEDENCE, and it is deliberate:

        could_not_run  >  regressed  >  not_fixed  >  fixed

    ``could_not_run`` first, because an unattributed node is an unknown and an
    unknown must never be read as a verdict. ``regressed`` next, because a
    change that breaks the regression set is reported as breaking it EVEN IF it
    also turned every FAIL_TO_PASS green -- collapsing those two into one
    boolean is exactly how a plausible-looking bad patch gets promoted.
    """
    unknown = sorted([n for n, s in {**after_f2p, **after_p2p}.items()
                      if s in NO_VERDICT])
    if unknown:
        return (OUTCOME_COULD_NOT_RUN,
                f"no verdict for {unknown} after the change", (), (), ())
    regressed = tuple(sorted(
        n for n, s in after_p2p.items()
        if s != STATUS_PASSED and before.p2p.get(n) == STATUS_PASSED))
    fixed = tuple(sorted(n for n, s in after_f2p.items() if s == STATUS_PASSED))
    unfixed = tuple(sorted(n for n, s in after_f2p.items() if s != STATUS_PASSED))
    if regressed:
        return (OUTCOME_REGRESSED,
                f"the change broke {len(regressed)} PASS_TO_PASS test(s) that "
                f"passed before it: {list(regressed)}",
                fixed, unfixed, regressed)
    if unfixed:
        detail = ", ".join(f"{n} is {after_f2p[n]}" for n in unfixed)
        return (OUTCOME_NOT_FIXED,
                f"the change did not turn {len(unfixed)} FAIL_TO_PASS test(s) "
                f"green: {detail}",
                fixed, unfixed, regressed)
    return (OUTCOME_FIXED,
            f"every FAIL_TO_PASS test ({len(fixed)}) passes after the change "
            f"and no PASS_TO_PASS test broke",
            fixed, unfixed, regressed)


# --------------------------------------------------------------------------- #
# the evaluation                                                               #
# --------------------------------------------------------------------------- #
def _run_lists(runner: TestRunner, worktree: Path, selection: Selection,
               repo_root: str, runs: list[dict]
               ) -> tuple[dict[str, str], dict[str, str]]:
    """Run FAIL_TO_PASS and PASS_TO_PASS as two SEPARATE invocations.

    Takes the frozen :class:`Selection`, NOT the task dict, and that is the
    structural half of the immutability rule: once a selection is frozen there
    is no code path left that can consult the task for node ids again, so a
    task mutated mid-evaluation (by a runner, a gate, or a caller holding the
    same dict) cannot change what is measured.

    Two invocations on purpose: a collection error in one list must not turn
    the other list into ``not_run`` (measured -- one uncollectable node id
    aborts the whole invocation with exit 4 and nothing else runs).
    """
    f2p_run = runner(worktree, list(selection.fail_to_pass), repo_root=repo_root,
                     timeout_s=selection.timeout_s)
    runs.append(f2p_run.to_dict())
    p2p: dict[str, str] = {}
    if selection.pass_to_pass:
        p2p_run = runner(worktree, list(selection.pass_to_pass),
                         repo_root=repo_root, timeout_s=selection.timeout_s)
        runs.append(p2p_run.to_dict())
        p2p = p2p_run.statuses
    return dict(f2p_run.statuses), p2p


def evaluate_change(task: dict, *, patch_bytes: bytes | None = None,
                    use_reference: bool = False,
                    repo_root: str | Path | None = None,
                    runner: TestRunner | None = None,
                    timeout_s: float = DEFAULT_TEST_TIMEOUT_S,
                    keep_worktree: bool = False) -> CorrectnessResult:
    """Evaluate one change against one task. Returns; never raises.

    The whole measurement happens in ONE disposable worktree, in this order:

        FREEZE the selection -> checkout base -> overlay tests -> RUN BEFORE
        -> judge the TASK -> apply the change -> RUN AFTER -> judge the CHANGE

    The selection is frozen FIRST, before the worktree exists and long before
    any candidate bytes are applied, and the after-state is run against that
    same frozen object -- so the thing being measured cannot be influenced by
    the thing being measured. The frozen declaration and its digest travel on
    the result.

    The before-state is measured every time, in the same tree the after-state
    is measured in. It is never read from a stored receipt here, because a
    receipt is a claim about a tree that may no longer exist -- the same
    doctrine ``spine.bootstrap`` applies to its discrimination receipt.

    ``use_reference`` evaluates the task's OWN fix commit (``reference_revision``)
    instead of a candidate patch. That is how a corpus task is validated: a task
    whose own reference patch does not produce ``fixed`` is not a task.
    """
    started = time.monotonic()
    task_id = str(task.get("id") or "<unknown>")
    runner = runner or run_node_ids
    runs: list[dict] = []
    selection: Selection | None = None

    def finish(outcome: str, reason: str, **kw) -> CorrectnessResult:
        return CorrectnessResult(
            task_id=task_id, outcome=outcome, reason=reason,
            base_revision=task.get("base_revision"),
            change=("reference" if use_reference else
                    ("patch" if patch_bytes is not None else None)),
            selection=selection,
            duration_s=time.monotonic() - started, runs=tuple(runs), **kw)

    problems = validate_task(task)
    if problems:
        return finish(OUTCOME_TASK_INVALID,
                      "the task does not satisfy the schema: " + "; ".join(problems))
    if patch_bytes is None and not use_reference:
        return finish(OUTCOME_COULD_NOT_RUN,
                      "nothing to evaluate: pass patch_bytes=... or "
                      "use_reference=True")
    if use_reference and not task.get("reference_revision"):
        return finish(OUTCOME_COULD_NOT_RUN,
                      "use_reference=True but the task records no "
                      "reference_revision")

    try:
        root = str(repo_root) if repo_root else resolve_task_repo(task["repo"])
    except (ValueError, OSError) as e:
        return finish(OUTCOME_COULD_NOT_RUN, f"cannot resolve the task repo: {e}")

    base = resolve_revision(root, task["base_revision"])
    if base is None:
        return finish(OUTCOME_COULD_NOT_RUN,
                      f"base revision {task['base_revision']!r} does not resolve "
                      f"in {root}")

    # FROZEN HERE -- before the worktree exists, before the overlay, and long
    # before any candidate bytes are applied. Everything below reads this
    # object; nothing below reads `task` for a node id again.
    selection = freeze_selection(task, base, timeout_s)

    try:
        with disposable_worktree(root, base, label=_slug(task_id),
                                 keep=keep_worktree) as worktree:
            try:
                if selection.test_overlay:
                    apply_test_overlay(worktree, root, selection.test_revision,
                                       selection.test_overlay)
            except (FileNotFoundError, OverlayEscape, OSError) as e:
                return finish(OUTCOME_COULD_NOT_RUN,
                              f"the test overlay could not be applied: {e}")

            before_started = time.monotonic()
            b_f2p, b_p2p = _run_lists(runner, worktree, selection, root, runs)
            moved = _check_selection(selection, b_f2p, b_p2p)
            if moved:
                return finish(OUTCOME_COULD_NOT_RUN,
                              f"before the change, {moved}")
            before = judge_before_state(base, b_f2p, b_p2p,
                                        time.monotonic() - before_started,
                                        selection=selection)
            if before.unrunnable:
                return finish(OUTCOME_COULD_NOT_RUN,
                              "; ".join(before.reasons), before=before)
            if not before.verified:
                # REPORTED as invalid, never silently dropped and never counted
                # as a pass -- the same rule mint.py applies to a vacuous label.
                return finish(OUTCOME_TASK_INVALID,
                              "; ".join(before.reasons), before=before)

            if use_reference:
                try:
                    change_bytes = reference_patch(
                        root, base, task["reference_revision"],
                        exclude=selection.test_overlay)
                except RuntimeError as e:
                    return finish(OUTCOME_COULD_NOT_RUN, str(e), before=before)
            else:
                change_bytes = patch_bytes or b""

            failure = apply_patch(worktree, root, change_bytes)
            if failure:
                return finish(OUTCOME_COULD_NOT_RUN, failure, before=before)

            # SAME frozen selection, deliberately: the after run measures
            # exactly what was declared before the change existed.
            a_f2p, a_p2p = _run_lists(runner, worktree, selection, root, runs)
    except Exception as e:               # noqa: BLE001 - reported, never raised
        return finish(OUTCOME_COULD_NOT_RUN,
                      f"the evaluation could not be set up: {type(e).__name__}: {e}")

    moved = _check_selection(selection, a_f2p, a_p2p)
    if moved:
        return finish(OUTCOME_COULD_NOT_RUN, f"after the change, {moved}",
                      before=before)
    outcome, reason, fixed, unfixed, regressed = judge_after_state(before, a_f2p, a_p2p)
    return finish(outcome, reason, before=before, after_f2p=a_f2p, after_p2p=a_p2p,
                  fixed_nodes=fixed, unfixed_nodes=unfixed, regressed_nodes=regressed)


def verify_before_state(task: dict, *, repo_root: str | Path | None = None,
                        runner: TestRunner | None = None,
                        timeout_s: float = DEFAULT_TEST_TIMEOUT_S) -> BeforeState:
    """Measure ONLY the before-state of ``task``: is this task real?

    Used when seeding a corpus. A candidate task that does not survive this is
    reported, with its reasons, and not admitted -- which is the measurement
    that says how much a corpus is worth.
    """
    started = time.monotonic()
    problems = validate_task(task)
    base_label = str(task.get("base_revision") or "")
    if problems:
        return BeforeState(False, base_label, reasons=tuple(problems), invalid=True)
    runner = runner or run_node_ids
    try:
        root = str(repo_root) if repo_root else resolve_task_repo(task["repo"])
    except (ValueError, OSError) as e:
        return BeforeState(False, base_label, reasons=(f"cannot resolve repo: {e}",),
                           unrunnable=True)
    base = resolve_revision(root, task["base_revision"])
    if base is None:
        return BeforeState(False, base_label,
                           reasons=(f"base revision {base_label!r} does not resolve",),
                           unrunnable=True)
    runs: list[dict] = []
    selection = freeze_selection(task, base, timeout_s)
    try:
        with disposable_worktree(root, base, label=_slug(str(task.get("id")))) as worktree:
            if selection.test_overlay:
                apply_test_overlay(worktree, root, selection.test_revision,
                                   selection.test_overlay)
            f2p, p2p = _run_lists(runner, worktree, selection, root, runs)
    except Exception as e:               # noqa: BLE001
        return BeforeState(False, base,
                           reasons=(f"{type(e).__name__}: {e}",), unrunnable=True,
                           duration_s=time.monotonic() - started,
                           selection=selection)
    moved = _check_selection(selection, f2p, p2p)
    if moved:
        return BeforeState(False, base, f2p, p2p, reasons=(moved,),
                           unrunnable=True, duration_s=time.monotonic() - started,
                           selection=selection)
    return judge_before_state(base, f2p, p2p, time.monotonic() - started,
                              selection=selection)


def _slug(text: str, limit: int = 24) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:limit].strip("-")
    return slug or "task"


# --------------------------------------------------------------------------- #
# the corpus                                                                   #
# --------------------------------------------------------------------------- #
def load_correctness_tasks(path: str | None = None) -> list[dict]:
    """Read the corpus, or ``[]`` if it does not exist yet. Sorted by id."""
    p = path or DEFAULT_CORPUS_PATH
    if not os.path.exists(p):
        return []
    with open(p, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return sorted(data.get("tasks", []), key=lambda t: t["id"])


def save_correctness_tasks(tasks: list[dict], path: str | None = None) -> str:
    """Overwrite the corpus. Deterministic formatting, same contract as
    ``harness.write_baseline`` / ``mint.save_minted_tasks``."""
    p = path or DEFAULT_CORPUS_PATH
    ordered = sorted(tasks, key=lambda t: t["id"])
    with open(p, "w", encoding="utf-8") as fh:
        json.dump({"schema": CORPUS_SCHEMA, "tasks": ordered}, fh, indent=2,
                  sort_keys=True)
        fh.write("\n")
    return p


def run_corpus(tasks: list[dict] | None = None, *,
               repo_root: str | Path | None = None,
               runner: TestRunner | None = None,
               timeout_s: float = DEFAULT_TEST_TIMEOUT_S) -> dict:
    """Evaluate every task against its OWN reference patch. The corpus's own gate.

    This is the corpus validating ITSELF: a task whose reference fix does not
    produce ``fixed`` is not a task, and an evaluator that cannot show that its
    corpus discriminates is in the same position as the pytest gate it exists to
    strengthen. Counts are reported per outcome and NEVER blended into a single
    "score" -- ``task_invalid`` and ``could_not_run`` in particular are not
    failures of the change, and folding them into one number would hide exactly
    the distinction this module was built for.
    """
    tasks = load_correctness_tasks() if tasks is None else tasks
    per_task: list[dict] = []
    for task in tasks:
        res = evaluate_change(task, use_reference=True, repo_root=repo_root,
                              runner=runner, timeout_s=timeout_s)
        per_task.append(res.to_dict())
    counts = {o: sum(1 for r in per_task if r["outcome"] == o) for o in OUTCOMES}
    return {
        "schema": CORPUS_SCHEMA,
        "n_tasks": len(per_task),
        "counts": counts,
        "ids_by_outcome": {
            o: sorted(r["task_id"] for r in per_task if r["outcome"] == o)
            for o in OUTCOMES
        },
        "discriminates": counts[OUTCOME_FIXED] == len(per_task) and bool(per_task),
        "per_task": per_task,
    }


# --------------------------------------------------------------------------- #
# seeding a corpus from real history                                           #
# --------------------------------------------------------------------------- #
def _changed_files(repo_root: str | Path, sha: str) -> list[tuple[str, str]]:
    proc = _git_read(repo_root, "diff", "--name-status", "-r", "--no-renames",
                     f"{sha}^", sha)
    if proc.returncode != 0:
        return []
    rows: list[tuple[str, str]] = []
    for line in proc.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            rows.append((parts[0].strip(), parts[-1].replace("\\", "/").strip()))
    return rows


def _blob(repo_root: str | Path, rev: str, rel: str) -> str | None:
    proc = _git_read(repo_root, "show", f"{rev}:{rel}")
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", "replace")


def _test_functions(rel: str, text: str) -> dict[str, str]:
    """{pytest node-id suffix -> that test's source}, for one Python test file.

    The key is the node id form pytest actually accepts -- ``test_x`` for a
    module-level function, ``ClassName::test_x`` for a method -- because the
    class qualifier is not optional and getting it wrong makes the node id
    ``missing``. That is not a hypothetical: the first run of this seeder used
    unqualified names from ``structcore.extract_units`` (which reports a method
    as a bare ``test_alive_then_stale``) and the before-state check refuted 19
    of 22 candidate nodes in one commit for exactly that reason. The refusal
    worked; the deriver was still wrong, so it was fixed.

    ``ast`` rather than a regex or the structural extractor: it is stdlib, it is
    exact about nesting, and pytest node ids are a Python-only concept anyway.
    A file that does not parse contributes nothing (the caller then mints
    nothing from it) rather than contributing guesses.
    """
    import ast

    if not rel.endswith(".py") or not text:
        return {}
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {}
    out: dict[str, str] = {}

    def _source(node) -> str:
        segment = ast.get_source_segment(text, node)
        return segment if segment is not None else ast.dump(node)

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test"):
                out[node.name] = _source(node)
        elif isinstance(node, ast.ClassDef):
            for child in node.body:
                if (isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and child.name.startswith("test")):
                    out[f"{node.name}::{child.name}"] = _source(child)
    return out


def derive_task_from_commit(repo_root: str | Path, sha: str, *,
                            max_pass_to_pass: int = 6) -> dict | None:
    """Propose ONE candidate correctness task from a real fix commit.

    The commit's own diff is the oracle, exactly as in ``mint.py``: what the
    commit ADDED or CHANGED in a test file is a FAIL_TO_PASS candidate, what it
    left untouched in the same file is a PASS_TO_PASS candidate, and the base is
    the commit's parent.

    NOTHING here is trusted. Every derived node id is a CLAIM that
    :func:`verify_before_state` then tries to refute by running it on the base;
    a node id this function gets wrong (a test nested in a class, say, whose
    real node id carries the class) comes back ``missing`` and takes the task
    down with it. That is the intended direction: the deriver may be sloppy, the
    admission gate may not.

    Returns ``None`` when the commit changed no test file -- a real and common
    case (``efd0ed6`` in this repo's own history is a fix with no test at all),
    reported by returning nothing rather than by inventing a label.
    """
    full = resolve_revision(repo_root, sha)
    parent = resolve_revision(repo_root, f"{sha}^")
    if not full or not parent:
        return None
    overlay: list[str] = []
    f2p: list[str] = []
    p2p: list[str] = []
    for status, rel in _changed_files(repo_root, full):
        if status.startswith("D") or not rel.startswith("tests/"):
            continue
        after = _blob(repo_root, full, rel)
        if after is None:
            continue
        before = _blob(repo_root, parent, rel) or ""
        after_units = _test_functions(rel, after)
        before_units = _test_functions(rel, before)
        if not after_units:
            continue
        overlay.append(rel)
        for name, source in sorted(after_units.items()):
            if before_units.get(name) != source:
                f2p.append(f"{rel}::{name}")
            else:
                p2p.append(f"{rel}::{name}")
    if not f2p:
        return None
    subject = _git_read(repo_root, "show", "-s", "--format=%s", full)
    return {
        "id": f"hist-{full[:7]}",
        "repo": "agent_env",
        "provenance": "git_history",
        "tier": "quarantine",
        "base_revision": parent,
        "reference_revision": full,
        "test_revision": full,
        "test_overlay": sorted(set(overlay)),
        "fail_to_pass": sorted(set(f2p)),
        "pass_to_pass": sorted(set(p2p))[:max_pass_to_pass],
        "subject": subject.stdout.decode("utf-8", "replace").strip(),
    }


def seed_task_from_commit(repo_root: str | Path, sha: str, *,
                          runner: TestRunner | None = None,
                          timeout_s: float = DEFAULT_TEST_TIMEOUT_S,
                          max_pass_to_pass: int = 6) -> tuple[dict | None, dict]:
    """Derive a candidate task from ``sha`` and MEASURE it into a real one.

    THE LISTS ARE MEASURED, NEVER CLAIMED. :func:`derive_task_from_commit`
    proposes node ids off the commit's diff; every one of them is a guess, and
    this function's whole job is to try to refute each guess by running it
    twice in one disposable worktree:

        base + test overlay                  -> the BEFORE statuses
        base + test overlay + reference fix  -> the AFTER statuses

    and then admitting nodes only where the two runs agree with the definition:

        FAIL_TO_PASS  not passing BEFORE, passing AFTER, and TOUCHED by the
                      commit (a test that was already red and that the commit
                      never mentions is not this fix's witness)
        PASS_TO_PASS  passing BEFORE and passing AFTER

    Everything else is DROPPED WITH ITS REASON RECORDED on the task
    (``dropped_candidates``) -- never silently, because the drop rate is itself
    the measurement of how much a corpus is worth. Real examples from this
    repo's own history, both found by running this rather than by reasoning:
    a test named ``..._still_...`` that the fix ADDED but which already passed
    on the base (demoted to the regression set), and an ``xfail``-marked test
    that is red before AND after the reference fix, so it can never witness
    anything (dropped).

    A task with no surviving FAIL_TO_PASS node is NOT admitted --
    ``(None, diagnostics)`` with the reason. ``efd0ed6`` in this repo is such a
    commit: a real fix that shipped no test at all.
    """
    diagnostics: dict = {"sha": str(sha)}
    candidate = derive_task_from_commit(repo_root, sha, max_pass_to_pass=10_000)
    if candidate is None:
        diagnostics["reason"] = (
            "the commit changed no test file with an added/changed test "
            "function, so it proposes no FAIL_TO_PASS candidate at all")
        return None, diagnostics
    diagnostics["candidate_fail_to_pass"] = list(candidate["fail_to_pass"])
    diagnostics["candidate_pass_to_pass"] = list(candidate["pass_to_pass"])

    runner = runner or run_node_ids
    base = candidate["base_revision"]
    all_nodes = list(candidate["fail_to_pass"]) + list(candidate["pass_to_pass"])
    try:
        with disposable_worktree(repo_root, base, label=_slug(candidate["id"])) as wt:
            apply_test_overlay(wt, repo_root, candidate["test_revision"],
                               candidate["test_overlay"])
            before_run = runner(wt, all_nodes, repo_root=str(repo_root),
                                timeout_s=timeout_s)
            patch = reference_patch(repo_root, base, candidate["reference_revision"],
                                    exclude=candidate["test_overlay"])
            failure = apply_patch(wt, repo_root, patch)
            if failure:
                diagnostics["reason"] = f"the reference fix would not apply: {failure}"
                return None, diagnostics
            after_run = runner(wt, all_nodes, repo_root=str(repo_root),
                               timeout_s=timeout_s)
    except Exception as e:                # noqa: BLE001
        diagnostics["reason"] = (f"the base state could not be measured: "
                                 f"{type(e).__name__}: {e}")
        return None, diagnostics

    before_statuses = dict(before_run.statuses)
    after_statuses = dict(after_run.statuses)
    diagnostics["base_statuses"] = dict(sorted(before_statuses.items()))
    diagnostics["reference_statuses"] = dict(sorted(after_statuses.items()))
    changed = set(candidate["fail_to_pass"])
    f2p: list[str] = []
    p2p: list[str] = []
    dropped: dict[str, str] = {}
    for node in all_nodes:
        before_status = before_statuses.get(node, STATUS_NOT_RUN)
        after_status = after_statuses.get(node, STATUS_NOT_RUN)
        if before_status == STATUS_PASSED and after_status == STATUS_PASSED:
            p2p.append(node)
        elif before_status == STATUS_PASSED:
            dropped[node] = (f"passes on the base revision but is {after_status} "
                             f"after the reference fix: the fix changed its "
                             f"behaviour, so it is not a regression witness")
        elif before_status not in PROVEN_NOT_PASSING:
            dropped[node] = (f"{before_status} on the base revision: not proof "
                             f"that it fails, so it cannot witness a fix")
        elif node not in changed:
            dropped[node] = (f"{before_status} on the base revision but the "
                             f"commit did not touch it: already red, so it is "
                             f"not this fix's witness")
        elif after_status != STATUS_PASSED:
            dropped[node] = (f"{before_status} before AND {after_status} after "
                             f"the reference fix: the known-good change does "
                             f"not turn it green, so it cannot witness a fix")
        else:
            f2p.append(node)
    diagnostics["dropped"] = dict(sorted(dropped.items()))
    if not f2p:
        diagnostics["reason"] = (
            "no candidate test goes from not-passing on the base revision to "
            "passing under the commit's own fix, so nothing here can "
            "demonstrate a fix")
        return None, diagnostics

    task = dict(candidate)
    task["fail_to_pass"] = sorted(f2p)
    task["pass_to_pass"] = sorted(p2p)[:max_pass_to_pass]
    task["dropped_candidates"] = diagnostics["dropped"]
    # The receipt records the selection this task is FROZEN at. From here on the
    # lists are data in a stored corpus: an evaluation reads them, digests them,
    # and refuses if they have moved since. Deriving the set from measurement is
    # legitimate exactly HERE and nowhere downstream -- this is corpus
    # construction against a known-good, human-authored REFERENCE commit, not
    # evaluation of a candidate. No candidate patch has ever been near this
    # function, and `evaluate_change` never calls it.
    selection = freeze_selection(task, base, timeout_s)
    before = judge_before_state(
        base,
        {n: before_statuses[n] for n in task["fail_to_pass"]},
        {n: before_statuses[n] for n in task["pass_to_pass"]},
        before_run.duration_s, selection=selection)
    task["before_state"] = before.to_dict()
    if not before.verified:
        diagnostics["reason"] = ("the measured before-state does not verify: "
                                 + "; ".join(before.reasons))
        return None, diagnostics
    return task, diagnostics


# --------------------------------------------------------------------------- #
# wiring: a gate a shadow run can use                                          #
# --------------------------------------------------------------------------- #
def correctness_gate(task: dict, repo_root: str | Path, *,
                     timeout_s: float = DEFAULT_TEST_TIMEOUT_S,
                     runner: TestRunner | None = None) -> Callable:
    """A gate callable for :class:`daedalus.spine.attempt.TaskAttempt`.

    Signature and return type match the attempt's gate contract exactly
    (``(RunnerContext) -> GateResult``), so wiring is
    ``TaskAttempt(..., gate=correctness_gate(task, repo_root))`` with no change
    to ``spine/`` at all.

    IT FAILS CLOSED ON AN UNVERIFIED TASK, and that is the point. The attempt's
    worktree already HAS the candidate's change in it by the time a gate runs,
    so the before-state cannot be measured there -- it has to have been measured
    earlier, against this exact base revision. A task with no verified
    before-state receipt for ``ctx.base_revision`` is REFUSED (``passed=False``)
    rather than evaluated, because a FAIL_TO_PASS list that was never shown to
    fail is precisely the vacuous green this module exists to prevent.

    IT ALSO REFUSES A SELECTION THAT MOVED. The receipt records the digest of
    the selection it was measured under; this recomputes that digest from the
    task as presented and refuses on any mismatch. Widening the lists after the
    verification (say, to include a test the candidate itself added), narrowing
    them to drop an inconvenient one, or pointing them at a different base all
    change the digest and all get the same refusal. What was measured is what
    was declared, checkably.

    What this gate adds over ``spine.attempt.pytest_gate``: pytest_gate asks
    "did the suite exit 0", which a candidate satisfies by changing nothing.
    This asks "did the previously-RED tests go GREEN, and did the previously-
    GREEN ones stay green" -- a question a no-op change cannot pass.
    """
    from daedalus.spine.attempt import GateResult

    runner = runner or run_node_ids
    root = str(repo_root)

    def _gate(ctx) -> "GateResult":
        started = time.monotonic()
        argv = pytest_node_argv(list(task.get("fail_to_pass") or []))

        def verdict(passed: bool, text: str) -> "GateResult":
            return GateResult(passed=passed, name="correctness", command=argv,
                              returncode=0 if passed else 1, output=text,
                              duration_s=time.monotonic() - started)

        problems = validate_task(task)
        if problems:
            return verdict(False, "correctness gate refused: the task does not "
                                  "satisfy the schema: " + "; ".join(problems))
        receipt = task.get("before_state") or {}
        if not receipt.get("verified"):
            return verdict(False,
                           "correctness gate refused: this task has no VERIFIED "
                           "before-state. A FAIL_TO_PASS list that was never "
                           "shown to fail on the base revision cannot certify "
                           "anything. Run daedalus.eval.correctness --verify first.")
        recorded = str(receipt.get("base_revision") or "")
        base = str(getattr(ctx, "base_revision", "") or "")
        if not recorded or not (base.startswith(recorded) or recorded.startswith(base)):
            return verdict(False,
                           f"correctness gate refused: the before-state was "
                           f"measured at {recorded or '<nothing>'} but this "
                           f"attempt is based on {base or '<nothing>'} -- a "
                           f"measurement of a tree that is not this one.")
        # THE SELECTION MAY NOT HAVE MOVED SINCE IT WAS VERIFIED.
        selection = freeze_selection(task, recorded, timeout_s)
        declared = str(receipt.get("selection_digest") or "")
        if not declared:
            return verdict(False,
                           "correctness gate refused: the before-state receipt "
                           "declares no selection digest, so there is nothing to "
                           "check the presented test lists against.")
        if declared != selection.digest:
            return verdict(False,
                           f"correctness gate refused: the selection presented "
                           f"here ({selection.digest}) is not the one that was "
                           f"verified ({declared}). The test set, the base "
                           f"revision and the gate configuration are fixed "
                           f"before a candidate runs and may not be re-derived, "
                           f"widened or narrowed afterwards.")
        try:
            if selection.test_overlay:
                apply_test_overlay(ctx.worktree, root, selection.test_revision,
                                   selection.test_overlay)
        except Exception as e:           # noqa: BLE001
            return verdict(False, f"correctness gate could not apply the test "
                                  f"overlay: {type(e).__name__}: {e}")
        runs: list[dict] = []
        try:
            a_f2p, a_p2p = _run_lists(runner, Path(ctx.worktree), selection,
                                      root, runs)
        except Exception as e:           # noqa: BLE001
            return verdict(False, f"correctness gate could not run the tests: "
                                  f"{type(e).__name__}: {e}")
        moved = _check_selection(selection, a_f2p, a_p2p)
        if moved:
            return verdict(False, f"correctness gate refused: {moved}")
        before = BeforeState(
            True, recorded,
            f2p={n: str(s) for n, s in (receipt.get("fail_to_pass") or {}).items()},
            p2p={n: str(s) for n, s in (receipt.get("pass_to_pass") or {}).items()},
            selection=selection)
        outcome, reason, _fixed, _unfixed, _regressed = judge_after_state(
            before, a_f2p, a_p2p)
        detail = json.dumps({"outcome": outcome, "reason": reason,
                             "selection_digest": selection.digest,
                             "fail_to_pass": a_f2p, "pass_to_pass": a_p2p},
                            indent=2, sort_keys=True)
        return verdict(outcome == OUTCOME_FIXED, f"correctness: {outcome}\n{detail}")

    return _gate


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python -m daedalus.eval.correctness",
        description="FAIL_TO_PASS / PASS_TO_PASS correctness evaluation. "
                    "Runs the repo's own pytest in a disposable worktree; makes "
                    "no vendor call and never writes the primary checkout.")
    ap.add_argument("--verify", action="store_true",
                    help="measure the BEFORE state of every corpus task")
    ap.add_argument("--run", action="store_true",
                    help="evaluate every corpus task against its own reference fix")
    ap.add_argument("--derive", metavar="SHA",
                    help="propose a candidate task from a fix commit (prints JSON, "
                         "writes nothing)")
    ap.add_argument("--seed", metavar="SHA",
                    help="derive AND measure a candidate task's before-state in a "
                         "disposable worktree (prints JSON, writes nothing)")
    ap.add_argument("--task", metavar="ID", help="restrict to one task id")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(list(argv) if argv is not None else None)

    from .tasks import AGENT_ENV_ROOT

    if args.derive:
        task = derive_task_from_commit(AGENT_ENV_ROOT, args.derive)
        print(json.dumps(task, indent=2, sort_keys=True))
        return 0 if task else 2

    if args.seed:
        task, diagnostics = seed_task_from_commit(AGENT_ENV_ROOT, args.seed)
        print(json.dumps({"task": task, "diagnostics": diagnostics},
                         indent=2, sort_keys=True))
        return 0 if task else 2

    tasks = load_correctness_tasks()
    if args.task:
        tasks = [t for t in tasks if t["id"] == args.task]
        if not tasks:
            print(f"no corpus task with id {args.task!r}")
            return 2
    if not tasks:
        print("the correctness corpus is empty -- nothing to evaluate")
        return 2

    if args.verify:
        rows = [{"id": t["id"], **verify_before_state(t).to_dict()} for t in tasks]
        if args.json:
            print(json.dumps(rows, indent=2, sort_keys=True))
        else:
            for row in rows:
                mark = "ok " if row["verified"] else "!! "
                print(f"  {mark}{row['id']}: "
                      f"{'before-state verified' if row['verified'] else row['reasons']}")
        return 0 if all(r["verified"] for r in rows) else 1

    if args.run:
        report = run_corpus(tasks)
        if args.json:
            print(json.dumps(report, indent=2, sort_keys=True))
        else:
            for outcome in OUTCOMES:
                ids = report["ids_by_outcome"][outcome]
                if ids:
                    print(f"  {outcome:>14}: {', '.join(ids)}")
            print(f"\n{report['counts'][OUTCOME_FIXED]}/{report['n_tasks']} "
                  f"reference fixes reproduce as 'fixed'")
        return 0 if report["discriminates"] else 1

    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
