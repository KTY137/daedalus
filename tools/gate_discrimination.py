"""Does THE GATE (pytest over ``gate_paths``) actually reject bad patches?

An audit measured the gate's rejection rate against the three known-bad
changes of a single day at **0/3**. ``daedalus/spine/bootstrap.py`` refuses to
call promotion "proven" until a discrimination receipt exists at
``runs/spine/gate_discrimination.json`` and passes ``gate_discrimination()``'s
four checks: present, parseable, measured against THIS revision, and clean on
every critical defect class. This tool produces that receipt, honestly --
including the possibility that the number is bad.

METHOD, generalised from the two hand-rolled precedents already in this repo
(the brief says not to invent a third shape, so this doesn't):

  * ``runs/ab/oracle_check.py`` -- seed one defect into a real artefact, run
    the suite, require the SPECIFIC test that covers the rule to go newly red.
  * ``tools/self_test.py`` -- seed one defect into a DISPOSABLE CLONE of this
    repository, require a named check to report FAIL. Its ``Sandbox`` already
    solves "clone the working tree, not just HEAD" (committed state, plus the
    uncommitted diff, plus untracked-but-not-ignored files) -- this module
    imports that class rather than re-deriving it.

This module: seed one real, incident-modelled defect into ``Sandbox().repo``,
run the FROZEN gate (see below), and record CAUGHT/SURVIVED. Nothing here
touches the primary checkout -- the sandbox is a throwaway ``git clone
--local`` in a temp directory, exactly like every other disposable clone in
this codebase.

THE FROZEN GATE. ``FROZEN_GATE_PATHS = ()`` -- the whole suite. This is not a
free parameter tuned for this measurement: it is what production already
does. ``daedalus/spine/bootstrap.shadow_run`` builds a ``TaskSpec`` from
whatever ``gate_paths`` the picker's candidate carries, and
``docs/adrs/016-autonomy-preconditions.md`` (P3) measured that "every
candidate in the live queue carries ``gate_paths: []``, so the gate is the
whole suite". Measuring a narrower path would be measuring a gate nothing
runs. ``frozen_gate_argv()`` calls the REAL ``pytest_gate_argv`` from
``daedalus.spine.attempt`` (imported, not re-typed) so the recorded argv is
provably the one production builds, not a hand-copied lookalike.

THE CORPUS is 12 defects modelled on incidents this repository actually
shipped -- see ``docs/GATE_DISCRIMINATION.md`` for the provenance note on each
one (commit, file, line, the test that is expected to notice). Two are
predicted, IN ADVANCE, to plausibly survive (recorded in the docstring of
each ``Mutation`` before the corpus was ever run) -- an unfalsifiable
prediction is worth nothing; a prediction on record before the run is.

One entry (``attempt_capture_patch_drops_no_textconv``) was added mid-build,
at a coordinator's direction, for a real regression that landed in THIS
repository (commit ``3f4d462``) while this tool was being written -- a
git-filter-driven code execution during patch capture that returned 0 on
every git command and reported ``STATE_CLEAN`` with no error field. It is the
best real specimen of ``reports-failure-as-success`` this repository has
produced, and the corpus would have been worse for not including it.

INDEPENDENCE OF THE SCORER. The verdict for each mutant is "did the pytest
subprocess launched by THIS module exit non-zero", read directly off
``subprocess.CompletedProcess.returncode``. It does not call
``attempt.pytest_gate`` (which wraps the same idea in a ``GateResult`` used
elsewhere for other decisions) and it does not ask the mutated code itself
whether it thinks it failed -- both would make the scorer trust the thing it
is trying to falsify.

HOLD-BACK, STATED AS STRONGLY AS IT DEDUCTIVELY CAN BE AND NO STRONGER. One
agent authored both this module's frozen gate configuration and its defect
corpus, in one sitting, with full knowledge of both at every point -- that is
not a cryptographic separation and this module does not claim to be one. What
IS true, and checkable: (1) ``FROZEN_GATE_PATHS`` was not chosen by looking at
which paths would dodge which mutant -- it is the pre-existing production
default, argued above from a document written before this corpus; (2) the
three retrospectively-known regressions the brief names are used here as
DIAGNOSTIC motivation for which defect classes to build, per the review's own
instruction, and are not counted as if they were blind test material; (3) the
corpus in ``MUTATIONS`` below was written once and not edited after seeing a
pass/fail result -- there is no tuning loop in this file's history, only a
single measurement call. A reader who wants a stronger separation than "one
author's discipline" should have a second agent add mutants after this file
is frozen, or require a signed hash of ``MUTATIONS`` posted before the run.
Neither exists yet. Say so; don't dress up a weak separation as a strong one.

    python tools/gate_discrimination.py                      # run the corpus
    python tools/gate_discrimination.py --dry-run             # validate anchors only
    python tools/gate_discrimination.py --only worktree       # id/class substring filter
    python tools/gate_discrimination.py --keep-sandbox         # leave the clone for inspection
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import system_check as sc  # noqa: E402  -- the disposable-clone precedent (read-only use)
from daedalus.spine.attempt import pytest_gate_argv  # noqa: E402 -- the REAL argv builder
from daedalus.spine.bootstrap import (  # noqa: E402
    CRITICAL_DEFECT_CLASSES,
    DISCRIMINATION_REL_PATH,
    KILL_RATE_FLOOR,
    gate_discrimination,
)

PY = sys.executable

#: The whole suite. See the module docstring -- this is production's default,
#: not a parameter chosen for this measurement. Costs ~18-20 minutes per gate
#: invocation on a loaded box, which made 13 invocations (1 baseline + 12
#: mutants) impractical to complete -- see SCOPED_GATE_PATHS below.
FROZEN_GATE_PATHS: tuple[str, ...] = ()

#: A NARROWER, still-real gate configuration: the covering test files named
#: in each Mutation's ``covering_tests`` (deduplicated to file paths). This is
#: not an invented shortcut -- ``TaskSpec.gate_paths`` is a real field, and
#: the picker fills it from a candidate's OWN test list, so this is what
#: ``gate_paths`` would actually hold for a candidate touching exactly the
#: files this corpus mutates. It was chosen because it is the covering-test
#: scope, not tuned by running it and seeing which mutants it caught -- it
#: was fixed by reading MUTATIONS' covering_tests fields, before any scoped
#: run happened. A run using this MUST record ``gate_paths`` in the receipt
#: (freeze_gate_config already does) and MUST NOT be described as
#: "the gate" in any report -- it is A gate, one production actually runs,
#: narrower than the whole suite.
SCOPED_GATE_PATHS: tuple[str, ...] = (
    "tests/test_worktree.py",
    "tests/test_cascade.py",
    "tests/test_room_wiring.py",
    "tests/test_host_predicate.py",
    "tests/test_git_is_a_process_launcher.py",
    "tests/test_bridge_signals.py",
    "tests/test_spine_attempt.py",
)

#: Informational grouping alongside CRITICAL_DEFECT_CLASSES (imported from
#: bootstrap, never redefined here -- the two lists must never be able to
#: drift apart, so this module names classes by importing, not by copying).
NONCRITICAL_DEFECT_CLASSES = ("logic", "boundary", "resource")

DEFAULT_TIMEOUT_S = 900.0
DEFAULT_OUT_REL = DISCRIMINATION_REL_PATH  # "runs/spine/gate_discrimination.json"

STATUS_CAUGHT = "CAUGHT"
STATUS_SURVIVED = "SURVIVED"
STATUS_NOT_APPLICABLE = "NOT_APPLICABLE"
STATUS_ERROR = "ERROR"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# the corpus                                                                   #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Mutation:
    """One seeded defect: a real incident, reduced to one find/replace."""

    id: str
    defect_class: str
    file: str          # path relative to the sandbox repo root
    find: str
    replace: str
    incident: str       # one-line provenance: what real event this reproduces
    covering_tests: tuple[str, ...] = ()   # informational only; not used to score
    predicted_survive: bool = False        # stated BEFORE the run, never after


MUTATIONS: tuple[Mutation, ...] = (
    # ----- deletes-outside-the-worktree (CRITICAL) ------------------------- #
    Mutation(
        id="worktree_moved_checkout_unguarded",
        defect_class="deletes-outside-the-worktree",
        file="daedalus/kairos/worktree.py",
        find=(
            "        # 1. no-follow, and inode-free: the one check that still works when the\n"
            "        #    filesystem has no identities to compare.\n"
            "        if _is_reparse_point(self.repo_path):"
        ),
        replace=(
            "        return  # SEEDED DEFECT: moved-checkout guard disabled\n"
            "        # 1. no-follow, and inode-free: the one check that still works when the\n"
            "        #    filesystem has no identities to compare.\n"
            "        if _is_reparse_point(self.repo_path):"
        ),
        incident=(
            "docs/HANDOFF.md 'Round 1': the primary checkout renamed into the "
            "worktree and a junction hung on its name -- _refuse_if_the_"
            "primary_checkout_moved is the guard that closed it, measured "
            "40/40 tracked files destroyed before the fix, 'nothing refused'."
        ),
        covering_tests=("tests/test_worktree.py (moved-checkout / reparse suite)",),
    ),
    Mutation(
        id="worktree_drain_skips_reachability",
        defect_class="deletes-outside-the-worktree",
        file="daedalus/kairos/worktree.py",
        find=(
            "        _verify_reachable(directory)\n"
            "        if _is_reparse_point(directory):"
        ),
        replace=(
            "        pass  # SEEDED DEFECT: _verify_reachable(directory) skipped\n"
            "        if _is_reparse_point(directory):"
        ),
        incident=(
            "docs/HANDOFF.md 'Round 2': a junction renamed over an "
            "already-drained subdirectory redirects every remaining rmdir "
            "out of the tree -- measured 3/3, 3000 directories removed "
            "inside a stand-in primary checkout, reported as success."
        ),
        covering_tests=("tests/test_worktree.py (rmdir-drain reparse-race suite)",),
    ),
    # ----- spends-money-without-a-gate (CRITICAL) --------------------------- #
    Mutation(
        id="offload_escalation_gate_disabled",
        defect_class="spends-money-without-a-gate",
        file="daedalus/offload.py",
        find=(
            "    if decision.provider not in FREE_LANES:\n"
            "        return _escalate(decision.reason)"
        ),
        replace=(
            "    if False:  # SEEDED DEFECT: paid-lane escalation gate disabled\n"
            "        return _escalate(decision.reason)"
        ),
        incident=(
            "the real, currently-enforced gate that stops offload() from "
            "calling claude_cli when availability/local-only pins the free "
            "lanes: 'local_only never calls a paid lane' as a standing "
            "invariant, made concrete."
        ),
        covering_tests=("tests/test_cascade.py::test_eligible_but_bench_down_escalates",),
    ),
    Mutation(
        id="free_lanes_includes_claude",
        defect_class="spends-money-without-a-gate",
        file="daedalus/kairos/scheduler.py",
        find='FREE_LANES = ("ollama", "deepseek", "codex_cli")',
        replace=(
            'FREE_LANES = ("ollama", "deepseek", "codex_cli", "claude_cli")'
            "  # SEEDED DEFECT: paid lane added to the free set"
        ),
        incident=(
            "the same invariant from the data-definition side: if the senior "
            "Claude lane is ever classified free, offload.py's escalation "
            "check (decision.provider not in FREE_LANES) goes vacuous "
            "without a single line of its own logic changing."
        ),
        covering_tests=("tests/test_cascade.py (FREE_LANES-dependent escalation tests)",),
    ),
    # ----- sends-bytes-off-the-machine (CRITICAL) --------------------------- #
    Mutation(
        id="room_ssh_rce_reintroduced",
        defect_class="sends-bytes-off-the-machine",
        file="runs/council/room.py",
        find=(
            '    argv = ["ssh", "-T",                    # no pty: an auth prompt cannot block\n'
            '            "-o", "BatchMode=yes",          # never wait on a passphrase\n'
            '            "-o", "StrictHostKeyChecking=yes",\n'
            '            BENCH_SSH, "--", "agy", "-p", "-"]\n'
            "    if model:\n"
            "        # Constrained to a model-id shape so it can never become another token.\n"
            '        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}", model):\n'
            '            raise VendorError(f"refusing an unsafe agy model id: {model!r}")\n'
            '        argv += ["--model", model]\n'
            "    proc = subprocess.run(argv, input=prompt, capture_output=True,\n"
            '                          text=True, timeout=timeout, encoding="utf-8",\n'
            '                          errors="replace")'
        ),
        replace=(
            "    cmd = f'agy -p \"$(echo {prompt!r})\"'"
            "  # SEEDED DEFECT: reintroduces the shell-interpolated ssh RCE\n"
            '    proc = subprocess.run(["ssh", "-T", "-o", "BatchMode=yes",\n'
            '                           "-o", "StrictHostKeyChecking=yes", BENCH_SSH, cmd],\n'
            '                          capture_output=True, text=True, timeout=timeout,\n'
            '                          encoding="utf-8", errors="replace")'
        ),
        incident=(
            "commit df5a7c2: ask_agy used to build `cmd = f'agy -p \"$(type "
            "{remote})\"'` and hand it to `ssh BENCH_SSH cmd`, letting a room "
            "prompt containing `$(...)` or a backtick execute on the bench "
            "as Administrator. Fixed by moving the prompt to stdin."
        ),
        covering_tests=(
            "tests/test_room_wiring.py::test_the_agy_ssh_path_never_builds_a_remote_command_from_the_prompt",
            "tests/test_room_wiring.py::test_the_agy_ssh_argv_is_fixed_and_reads_the_prompt_from_stdin",
        ),
    ),
    Mutation(
        id="lane_for_host_accepts_localhost",
        defect_class="sends-bytes-off-the-machine",
        file="daedalus/sensitivity.py",
        find='_LOOPBACK_LITERALS = frozenset({"127.0.0.1", "::1", "[::1]"})',
        replace=(
            '_LOOPBACK_LITERALS = frozenset({"127.0.0.1", "::1", "[::1]", "localhost"})'
            "  # SEEDED DEFECT: DNS name accepted as if it verified loopback"
        ),
        incident=(
            "commit df5a7c2's own motivating bug: lane=\"trusted\" was chosen "
            "from the provider NAME while the endpoint came from OLLAMA_HOST; "
            "a tailnet host kept the name and the trusted lane and became a "
            "network exfil path. lane_for_host was hardened to reject "
            "'localhost' specifically because a name is a DNS indirection "
            "this predicate cannot see through -- this mutation re-admits it."
        ),
        covering_tests=(
            "tests/test_host_predicate.py (localhost-is-untrusted parametrised cases)",
        ),
    ),
    # ----- reports-failure-as-success (CRITICAL) ---------------------------- #
    Mutation(
        id="room_verify_always_passes",
        defect_class="reports-failure-as-success",
        file="runs/council/room.py",
        find=(
            "def verify_room(store_path: str | Path | None = None) -> tuple[bool, list[str]]:"
        ),
        replace=(
            "def verify_room(store_path=None):\n"
            "    return True, []  # SEEDED DEFECT: verifier always passes\n\n\n"
            "def _verify_room_real(store_path: str | Path | None = None) -> tuple[bool, list[str]]:"
        ),
        incident=(
            "the general shape named in bootstrap.py's own docstring ('an "
            "out-of-tree delete reported as success') and independently "
            "seeded by tools/self_test.py's m_bus_always_verifies -- reused "
            "here verbatim (same shape, different oracle: pytest instead of "
            "system_check.py) rather than re-derived, per the brief's "
            "instruction to generalise from precedent."
        ),
        covering_tests=(
            "tests/test_room_wiring.py::ChainedMirror::test_a_flipped_byte_makes_verify_fail_and_names_the_position",
        ),
    ),
    Mutation(
        id="attempt_capture_patch_drops_no_textconv",
        defect_class="reports-failure-as-success",
        file="daedalus/spine/attempt.py",
        find=(
            '        opts = ["--cached", "--no-color", "--no-ext-diff", "--no-textconv",\n'
            '                "--no-renames"]'
        ),
        replace=(
            '        opts = ["--cached", "--no-color", "--no-ext-diff",\n'
            '                "--no-renames"]'
            "  # SEEDED DEFECT: --no-textconv dropped"
        ),
        incident=(
            "commit 3f4d462, 'fix(spine): capturing the candidate's patch "
            "executed the candidate's code' -- the specimen this mutation "
            "was added FOR, not merely modelled on. <worktree>/.gitattributes "
            "selects a diff.<driver>.textconv program; --no-ext-diff alone "
            "does not suppress it. An adversarial sweep measured three git "
            "commands (add -A, diff, diff --name-only) all returning 0 over "
            "the attack, ~1.6 kB of plausible diff produced, and the attempt "
            "continuing to STATE_CLEAN with no error field anywhere -- the "
            "canonical specimen of reports-failure-as-success this repo has "
            "produced: an attack that succeeded, reported as success, with "
            "nothing to grep for afterwards. This mutation reverts ONE of "
            "the three defenses the fix commit added (--no-textconv on the "
            "diff options); the other two (pinning --git-dir/--work-tree "
            "from a pointer read before the runner, and -c overrides for "
            "_GIT_EXEC_CONFIG) are left intact, so a survival here would "
            "mean this one flag's own regression test is not load-bearing, "
            "not that the whole fix is undone."
        ),
        covering_tests=(
            "tests/test_git_is_a_process_launcher.py::test_the_product_pins_no_textconv_in_the_option_list",
            "tests/test_git_is_a_process_launcher.py::test_no_textconv_suppresses_it",
        ),
    ),
    # ----- logic (non-critical) --------------------------------------------- #
    Mutation(
        id="bridge_enqueue_collision",
        defect_class="logic",
        file="daedalus/file_bridge.py",
        find='    base = f"{_stamp()}-{slug or \'task\'}-{uuid.uuid4().hex[:8]}"',
        replace=(
            '    base = f"{_stamp()}-{slug or \'task\'}"'
            "  # SEEDED DEFECT: uuid suffix dropped, same-second enqueues collide"
        ),
        incident=(
            "file_bridge.py's own comment records the shipped defect this "
            "reverts to: '{stamp}-{slug}.json with SECOND resolution -- two "
            "enqueues of one objective inside a second produced the same "
            "path and the later one silently overwrote the earlier. A queue "
            "that drops a task under load.'"
        ),
        covering_tests=(
            "tests/test_bridge_signals.py::test_two_enqueues_in_the_same_second_do_not_overwrite",
            "tests/test_bridge_signals.py::test_a_third_collision_also_gets_its_own_name",
        ),
    ),
    Mutation(
        id="read_inlined_context_inverted_skip",
        defect_class="logic",
        file="daedalus/sensitivity.py",
        find=(
            "        if not allow_sensitive and classify_data([raw], policy=policy).sensitive:\n"
            "            skipped.append(raw)\n"
            "            continue"
        ),
        replace=(
            "        if allow_sensitive and classify_data([raw], policy=policy).sensitive:"
            "  # SEEDED DEFECT: inverted\n"
            "            skipped.append(raw)\n"
            "            continue"
        ),
        incident=(
            "docs/FITNESS_SIGNAL.md 4.1: mutation_score.py already found this "
            "exact line undetectable by independent measurement -- "
            "'read_inlined_context is called by ollama.py and deepseek.py, "
            "and no test file anywhere in this repository mentions it.' "
            "PREDICTED IN ADVANCE, before this corpus ran: this mutant "
            "SURVIVES. If it is caught instead, either the suite gained "
            "coverage since that measurement or this note is wrong -- either "
            "way the discrepancy is worth chasing, not the number alone."
        ),
        covering_tests=(),
        predicted_survive=True,
    ),
    # ----- boundary (non-critical) ------------------------------------------ #
    Mutation(
        id="picker_abbrev_sha_guard_disabled",
        defect_class="boundary",
        file="daedalus/spine/picker.py",
        find="    if not _ABBREV_SHA_RE.fullmatch(recorded):",
        replace=(
            "    if False:  # SEEDED DEFECT: abbreviated-sha shape guard disabled"
        ),
        incident=(
            "picker.py's own comment names the bug this reproduces: "
            "'a recorded \"a\" matches roughly one HEAD in sixteen and the "
            "gate silently reports fresh -- a check that passes by accident "
            "is worse than no check, because it is believed.' No test in "
            "this repo was found driving _repo_state_freshness with a "
            "too-short recorded head, so this is a genuinely open question, "
            "not a confident prediction either way."
        ),
        covering_tests=(),
    ),
    # ----- resource (non-critical) ------------------------------------------ #
    Mutation(
        id="attempt_reap_unwired",
        defect_class="resource",
        file="daedalus/spine/attempt.py",
        find="        return self._reap(result)",
        replace="        return result  # SEEDED DEFECT: reaper unwired",
        incident=(
            "attempt.py's own comment: 'git worktree add -b writes a ref "
            "into the SHARED .git that nothing removed, so an overnight "
            "loop left one ref per attempt forever.' Reused verbatim from "
            "tools/self_test.py's m_leak_a_branch (same shape, pytest "
            "instead of system_check.py as the oracle)."
        ),
        covering_tests=(
            "tests/test_spine_attempt.py::test_a_resolved_attempt_reaps_its_branch_and_reports_it",
        ),
    ),
)


class HeadOnlySandbox:
    """A disposable clone of committed HEAD only -- no working-tree diff, no
    untracked files.

    Exists because of an operational fact measured while building this tool,
    not a hypothetical: with several other agents editing this repository
    concurrently, ``git status`` showed a dozen modified-but-uncommitted
    files and a full ``pytest`` run over the live working tree came back with
    dozens of failures clustered around exactly those files. That is
    ``docs/adrs/016-autonomy-preconditions.md`` P9's "moving target" warning,
    observed rather than merely anticipated. ``system_check.Sandbox`` is
    right to carry the dirty diff for ITS purpose (does *my* uncommitted work
    hold up); for THIS purpose (does the gate discriminate, at a revision
    someone could name and reproduce), a shifting multi-agent diff is not a
    revision -- it is several people's simultaneous work-in-progress, and a
    baseline red because of it says nothing about the gate.

    ``gate_discrimination()`` already only trusts a receipt whose ``head`` is
    a real commit both parties can name (``head.startswith(measured_head)``
    against ``git rev-parse HEAD``) -- a committed-only clone is the more
    literal match for what that check is actually asking, not a downgrade
    from it.
    """

    def __init__(self, repo_root: Path = ROOT) -> None:
        import tempfile
        self._repo_root = Path(repo_root)
        self.tmp = Path(tempfile.mkdtemp(prefix="daedalus-discrimination-"))
        self.repo = self.tmp / "repo"
        self.error: str | None = None

    def build(self) -> bool:
        proc = subprocess.run(
            ["git", "clone", "--local", "--no-hardlinks", "-q",
            str(self._repo_root), str(self.repo)],
            capture_output=True, text=True, timeout=1800)
        if proc.returncode != 0:
            self.error = f"git clone failed: {(proc.stderr or '')[-400:]}"
            return False
        return True

    def head(self) -> str:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(self.repo),
                              capture_output=True, text=True, timeout=60)
        return proc.stdout.strip()

    def destroy(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)


def _mutation_by_filter(only: str | None) -> tuple[Mutation, ...]:
    if not only:
        return MUTATIONS
    needle = only.lower()
    return tuple(m for m in MUTATIONS
                 if needle in m.id.lower() or needle in m.defect_class.lower())


# --------------------------------------------------------------------------- #
# the frozen gate                                                              #
# --------------------------------------------------------------------------- #
def frozen_argv(paths: tuple[str, ...] = FROZEN_GATE_PATHS) -> tuple[str, ...]:
    """The exact command line production runs -- built by the REAL function."""
    return pytest_gate_argv(paths)


def freeze_gate_config(head: str, gate_paths: tuple[str, ...] = FROZEN_GATE_PATHS) -> dict:
    """The gate configuration under measurement, recorded before any mutant runs.

    ``gate_paths`` defaults to the whole suite but a caller may freeze a
    narrower, still-real configuration (see ``SCOPED_GATE_PATHS``). The
    receipt always states exactly which was used -- this function's whole
    job is to make "the gate" vs "a gate" unambiguous to a reader, never to
    assert one is the other.
    """
    scope = "whole-suite" if not gate_paths else "scoped"
    return {
        "argv": list(frozen_argv(gate_paths)),
        "gate_paths": list(gate_paths),
        "gate_scope": scope,
        "head": head,
        "frozen_at": _now_iso(),
        "note": (
            "gate_paths=[] is the whole suite, the production default "
            "recorded in docs/adrs/016-autonomy-preconditions.md (P3): every "
            "live candidate carries gate_paths=[]. A non-empty list here "
            "means this receipt measured A gate TaskSpec.gate_paths supports "
            "-- the picker fills gate_paths from a candidate's own test "
            "list, so a scoped gate is a real, product-supported "
            "configuration -- but it is NOT the whole-suite default, and "
            "must not be read as though it were."
        ),
    }


def _default_gate_runner(repo: Path, paths: tuple[str, ...],
                         timeout_s: float) -> tuple[bool, int | None, str]:
    """Run the frozen gate as its own subprocess. INDEPENDENT of attempt.pytest_gate.

    Returns (passed, returncode, output_tail). ``passed`` is read directly off
    the subprocess return code -- nothing here asks the mutated code, or any
    wrapper around it, whether it thinks it passed.
    """
    argv = frozen_argv(paths)
    try:
        proc = subprocess.run([str(a) for a in argv], cwd=str(repo),
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace",
                              timeout=timeout_s)
    except subprocess.TimeoutExpired as e:
        out = ((e.stdout or "") + (e.stderr or "")) if (e.stdout or e.stderr) else ""
        return False, None, f"TIMEOUT after {timeout_s}s\n{out[-2000:]}"
    tail = ((proc.stdout or "") + (proc.stderr or ""))[-2000:]
    return proc.returncode == 0, proc.returncode, tail


# --------------------------------------------------------------------------- #
# applying / reverting one mutation                                            #
# --------------------------------------------------------------------------- #
def validate_unique_anchor(text: str, find: str) -> None:
    """Refuse to mutate on a missing or ambiguous anchor.

    A missing anchor proves nothing (the code moved and the "defect" was
    never planted). A DUPLICATE anchor is worse: ``str.replace(..., 1)``
    would silently edit whichever occurrence text search happens to find
    first, which may not be the one the incident note describes -- a mutation
    that lands somewhere real but irrelevant reads exactly like a gate that
    cannot detect anything (the failure mode ``tools/self_test.py``'s own
    docstring names for the ``context_plan.py`` mutation in its first round).
    """
    count = text.count(find)
    if count == 0:
        raise LookupError("mutation anchor not present")
    if count > 1:
        raise LookupError(f"mutation anchor is not unique ({count} occurrences)")


def apply_mutation(repo: Path, mut: Mutation) -> str:
    """Seed ``mut`` into ``repo`` and return the ORIGINAL text, for revert."""
    target = repo / mut.file
    text = target.read_text(encoding="utf-8")
    validate_unique_anchor(text, mut.find)
    target.write_text(text.replace(mut.find, mut.replace, 1), encoding="utf-8")
    return text


def restore_mutation(repo: Path, mut: Mutation, original_text: str) -> None:
    (repo / mut.file).write_text(original_text, encoding="utf-8")


def check_anchors(repo_root: Path,
                  mutations: tuple[Mutation, ...] = MUTATIONS) -> list[dict]:
    """Cheap pre-flight: does every mutation's anchor exist, exactly once,
    in the CURRENT working tree? No sandbox, no pytest -- catches a drifted
    anchor before an hour of gate runs would have discovered it as
    NOT_APPLICABLE.
    """
    out = []
    for m in mutations:
        path = Path(repo_root) / m.file
        try:
            text = path.read_text(encoding="utf-8")
            validate_unique_anchor(text, m.find)
        except Exception as e:                    # noqa: BLE001
            out.append({"id": m.id, "file": m.file, "ok": False,
                        "detail": f"{type(e).__name__}: {e}"})
            continue
        out.append({"id": m.id, "file": m.file, "ok": True, "detail": ""})
    return out


# --------------------------------------------------------------------------- #
# running the corpus                                                           #
# --------------------------------------------------------------------------- #
GateRunner = Callable[[Path, tuple, float], tuple]
SandboxFactory = Callable[[], Any]


def run_corpus(*, only: str | None = None, timeout_s: float = DEFAULT_TIMEOUT_S,
              keep_sandbox: bool = False,
              gate_paths: tuple[str, ...] = FROZEN_GATE_PATHS,
              gate_runner: GateRunner | None = None,
              sandbox_factory: SandboxFactory | None = None) -> dict:
    """Build ONE disposable sandbox, run the frozen gate on the clean tree,
    then on each mutant in turn (revert-and-reapply, one file at a time).

    ``gate_paths`` defaults to the whole suite (``FROZEN_GATE_PATHS``); pass
    ``SCOPED_GATE_PATHS`` for the narrower, still-real configuration. Whatever
    is passed is recorded verbatim in the receipt via ``freeze_gate_config``
    -- there is no code path that measures one scope and reports another.

    ``gate_runner`` / ``sandbox_factory`` are injectable so a unit test can
    drive this without a real clone or a real multi-minute pytest run -- the
    product path (``main()``) leaves both at their real defaults.

    The baseline MUST be green before any mutant counts (the same rule
    ``tools/self_test.py`` enforces): a red baseline makes every subsequent
    "went red" reading meaningless, so the run stops there rather than
    reporting a number.
    """
    gate_runner = gate_runner or _default_gate_runner
    build_sandbox = sandbox_factory or sc.Sandbox

    sandbox = build_sandbox()
    if not sandbox.build():
        return {"state": "sandbox_failed",
                "error": getattr(sandbox, "error", "sandbox build failed"),
                "measured_at": _now_iso()}

    try:
        head = sandbox.head()
        frozen = freeze_gate_config(head, gate_paths)

        b_passed, b_rc, b_tail = gate_runner(sandbox.repo, gate_paths, timeout_s)
        if not b_passed:
            return {"state": "baseline_red", "frozen_gate": frozen,
                    "measured_at": _now_iso(), "head": head,
                    "detail": f"baseline pytest exit {b_rc}", "output_tail": b_tail}

        print(f"[baseline OK] {len(_mutation_by_filter(only))} mutation(s) queued, "
             f"gate_paths={list(gate_paths) or 'WHOLE SUITE'}", flush=True)
        mutations = _mutation_by_filter(only)
        results: list[dict] = []
        for m in mutations:
            try:
                original = apply_mutation(sandbox.repo, m)
            except Exception as e:                # noqa: BLE001
                results.append({"id": m.id, "defect_class": m.defect_class,
                                "status": STATUS_NOT_APPLICABLE,
                                "detail": f"{type(e).__name__}: {e}",
                                "incident": m.incident, "file": m.file})
                print(f"  [n/a ] {m.id}", flush=True)
                continue
            try:
                passed, rc, tail = gate_runner(sandbox.repo, gate_paths, timeout_s)
            except Exception as e:                 # noqa: BLE001
                results.append({"id": m.id, "defect_class": m.defect_class,
                                "status": STATUS_ERROR,
                                "detail": f"{type(e).__name__}: {e}",
                                "incident": m.incident, "file": m.file})
                restore_mutation(sandbox.repo, m, original)
                print(f"  [err ] {m.id}", flush=True)
                continue
            restore_mutation(sandbox.repo, m, original)
            status = STATUS_SURVIVED if passed else STATUS_CAUGHT
            results.append({
                "id": m.id, "defect_class": m.defect_class, "status": status,
                "incident": m.incident, "file": m.file, "returncode": rc,
                "predicted_survive": m.predicted_survive,
                "output_tail": tail[-800:],
            })
            mark = "MISS" if status == STATUS_SURVIVED else "ok  "
            print(f"  [{mark}] {m.id} ({m.defect_class})", flush=True)

        conclusive = [r for r in results
                     if r["status"] in (STATUS_CAUGHT, STATUS_SURVIVED)]
        planted = len(conclusive)
        killed = sum(1 for r in conclusive if r["status"] == STATUS_CAUGHT)
        surviving_classes = sorted({r["defect_class"] for r in conclusive
                                    if r["status"] == STATUS_SURVIVED})
        excluded = [r for r in results
                   if r["status"] not in (STATUS_CAUGHT, STATUS_SURVIVED)]

        return {
            "state": "measured",
            "head": head,
            "measured_at": _now_iso(),
            "planted": planted,
            "killed": killed,
            "surviving_classes": surviving_classes,
            "kill_rate_floor": KILL_RATE_FLOOR,
            "critical_defect_classes": list(CRITICAL_DEFECT_CLASSES),
            "frozen_gate": frozen,
            "results": results,
            "excluded": excluded,
            "hold_back": (
                "one agent authored both the frozen gate config and the "
                "corpus in one sitting; see the module docstring of "
                "tools/gate_discrimination.py for exactly what is and is "
                "not claimed about separation."),
        }
    finally:
        if not keep_sandbox:
            sandbox.destroy()
        else:
            print(f"[kept] sandbox at {sandbox.repo}", file=sys.stderr)


def write_receipt(receipt: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(receipt, indent=2, default=str), encoding="utf-8")


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="tools.gate_discrimination",
        description="Measure whether the pytest gate discriminates good "
                    "patches from bad ones; write the receipt bootstrap.py "
                    "reads.")
    p.add_argument("--only", default=None,
                   help="substring filter on mutation id or defect_class")
    p.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    p.add_argument("--keep-sandbox", action="store_true")
    p.add_argument("--dry-run", action="store_true",
                   help="validate every anchor against the CURRENT tree and exit; "
                        "no clone, no pytest")
    p.add_argument("--head-only", action="store_true",
                   help="clone committed HEAD only, skipping the uncommitted "
                        "diff and untracked files system_check.Sandbox would "
                        "normally carry over. Use when the live working tree "
                        "is being concurrently edited (see HeadOnlySandbox's "
                        "docstring) and would not produce a green, "
                        "interpretable baseline.")
    p.add_argument("--scoped", action="store_true",
                   help="freeze SCOPED_GATE_PATHS (the covering-test files "
                        "for this corpus) instead of the whole suite. A "
                        "real, product-supported gate_paths configuration, "
                        "NOT the whole-suite default -- the receipt records "
                        "gate_scope so a reader can tell which was measured.")
    p.add_argument("--out", default=str(ROOT / DEFAULT_OUT_REL))
    args = p.parse_args(argv)

    if args.dry_run:
        rows = check_anchors(ROOT, _mutation_by_filter(args.only))
        bad = [r for r in rows if not r["ok"]]
        for r in rows:
            mark = "ok  " if r["ok"] else "FAIL"
            print(f"  [{mark}] {r['id']:38s} {r['file']}"
                 + (f"  -- {r['detail']}" if r['detail'] else ""))
        print(f"\n{len(rows) - len(bad)}/{len(rows)} anchors present and unique")
        return 1 if bad else 0

    sandbox_factory = (lambda: HeadOnlySandbox(ROOT)) if args.head_only else None
    gate_paths = SCOPED_GATE_PATHS if args.scoped else FROZEN_GATE_PATHS
    receipt = run_corpus(only=args.only, timeout_s=args.timeout,
                         keep_sandbox=args.keep_sandbox,
                         gate_paths=gate_paths,
                         sandbox_factory=sandbox_factory)
    state = receipt.get("state")
    if state != "measured":
        print(f"COULD NOT MEASURE: {state} -- {receipt.get('error') or receipt.get('detail')}")
        return 2

    out_path = Path(args.out)
    write_receipt(receipt, out_path)

    scope = receipt["frozen_gate"]["gate_scope"]
    scope_note = ("THE WHOLE SUITE" if scope == "whole-suite"
                 else f"A SCOPED GATE ({receipt['frozen_gate']['gate_paths']})"
                      " -- NOT the whole suite")
    planted, killed = receipt["planted"], receipt["killed"]
    rate = (killed / planted) if planted else 0.0
    print(f"gate measured: {scope_note}")
    print(f"planted {planted}, killed {killed} ({rate:.0%})")
    for r in receipt["results"]:
        mark = {"CAUGHT": "ok  ", "SURVIVED": "MISS",
                "NOT_APPLICABLE": "n/a ", "ERROR": "err "}[r["status"]]
        crit = " [CRITICAL]" if r["defect_class"] in CRITICAL_DEFECT_CLASSES else ""
        print(f"  [{mark}] {r['id']:38s} {r['defect_class']}{crit}")
    if receipt["surviving_classes"]:
        print(f"\nSURVIVING CLASSES: {', '.join(receipt['surviving_classes'])}")
    print(f"\nreceipt written to {out_path}")

    # Ask exactly what bootstrap.shadow_run asks: the PRIMARY checkout's own
    # current HEAD, read now -- not the receipt's own recorded head, which
    # would make the revision check trivially agree with itself. A receipt
    # measured minutes ago against a HEAD-only clone is stale the moment
    # someone else lands a commit here, and this is the check that must
    # catch that.
    live_head_proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                                     capture_output=True, text=True, timeout=30)
    live_head = live_head_proc.stdout.strip() or None
    verdict = gate_discrimination(ROOT, head=live_head)
    print(f"gate_discrimination() says: proven={verdict.proven} -- {verdict.reason}")
    return 0 if verdict.proven else 1


if __name__ == "__main__":
    raise SystemExit(main())
