"""One bounded deterministic repair campaign; nomination is the terminal ceiling."""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
from dataclasses import asdict, dataclass
from xml.etree import ElementTree
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from daedalus.atomic import ExclusiveFileLock, FileLockUnavailable
from daedalus.gates.repository.head_revision import verify_repository_head_revision
from daedalus.gates.repository.tree import (
    RepositoryTreeRaceError,
    RepositoryTreeReadError,
    read_repository_source,
)
from daedalus.kernel.artifacts import ArtifactRef
from daedalus.kernel.attempt_execution import RunnerContext, TaskSpec
from daedalus.kernel.interpreter import (
    interpreter_provenance as _interpreter_provenance,
    stdlib_interpreter as _evaluator_interpreter,
)
from daedalus.kernel.attempt_contracts import AttemptTerminalReceipt
from daedalus.kernel.attempts import AttemptLedger, IsolatedAttemptCoordinator
from daedalus.kernel.effects import EffectLeaseError
from daedalus.kernel.campaigns import (
    CampaignIdentityConflict,
    CampaignLifecycleError,
    begin_campaign,
    campaign_contract_for_spec,
    complete_campaign,
    fail_campaign,
    load_attempt_contract,
    load_attempt_receipt,
    load_evidence_packet,
    lookup_campaign_read_only,
    store_contract,
)
from daedalus.kernel.contracts import (
    AttemptContract,
    CampaignBudgetEqualityEvidence,
    CampaignReceipt,
    CampaignTrialReceipt,
    ContractProvenance,
    EvidenceItem,
    EvidencePacket,
    ExperimentSpec,
    NominationReceipt,
    ResourceBudget,
    ResourceUsage,
)
from daedalus.kernel.offload_lease import (
    ATTEMPT_ENTRYPOINT_ID,
    WaveLeaseDenied,
    acquire_attempt_lease,
    acquire_effect_lease,
    control_root,
    require_retained_effect_lease_start_records,
    require_retained_effect_lease_terminal_record,
)
from daedalus.kernel.source_trees import (
    MANDATORY_IGNORED_ROOTS,
    SourceTreeEntry,
    SourceTreeManifest,
    SourceTreeStore,
    SourceTreeStoreError,
    StoredSourceTree,
)
from daedalus.orchestration.execution.attempts import command_gate
from daedalus.runtimes.contracts.repository import (
    RepositoryHeadRevisionBindingError,
    RepositoryHeadRevisionRaceError,
    RepositoryHeadRevisionShapeError,
)
from daedalus.sensitivity import Policy
from daedalus.spine.envelope import canonical_json, canonical_sha
from daedalus.spine.killswitch import KillSwitch
from daedalus.spine.picker import resolve_spine_db_path


ENTRYPOINT_ID = "python.ariadne_campaign"
EVALUATOR_SOURCE = """import hashlib,json,pathlib,sys
p=pathlib.Path(sys.argv[1]); got=hashlib.sha256(p.read_bytes()).hexdigest(); expected=sys.argv[2]
print(json.dumps({'expected_sha256':expected,'observed_sha256':got,'passed':got==expected},sort_keys=True,separators=(',',':')))
raise SystemExit(0 if got==expected else 1)
"""
EVALUATOR_SHA256 = hashlib.sha256(EVALUATOR_SOURCE.encode("utf-8")).hexdigest()
#: Retained evaluator observations: ``/1`` predates interpreter provenance,
#: ``/2`` records the path-free identity of the interpreter that ran the arm.
_EVALUATOR_OBSERVATION_SCHEMAS = (
    "daedalus-ariadne-evaluator-observation/1",
    "daedalus-ariadne-evaluator-observation/2",
)
_EVALUATOR_OBSERVATION_KEYS = (
    "schema", "variant_id", "seed", "evaluator_sha256", "passed", "returncode",
    "output", "output_sha256", "candidate_tree_sha256", "expected_sha256",
    "observed_sha256", "containment",
)
_INTERPRETER_PROVENANCE_KEYS = frozenset(
    {"implementation", "version", "platform", "binary_sha256"}
)
#: The test-command evaluator (G1-IKARUS-48). The exact-match evaluator above
#: proves that an edit landed; it says nothing about whether the project still
#: works, which is why no receipt written by it may be called self-improvement.
TEST_EVALUATOR_OBSERVATION_SCHEMA = "daedalus-ariadne-test-evaluator-observation/1"
_TEST_OBSERVATION_KEYS = (
    "schema", "variant_id", "seed", "evaluator_sha256", "passed", "returncode",
    "output", "output_sha256", "candidate_tree_sha256", "containment", "interpreter",
    "command_sha256", "timed_out", "workspace_files", "workspace_bytes", "report",
    "workspace_removed", "child_environment", "child_network", "verdict_is_self_reported",
)
#: An inline program is not a test command: it is a way to run anything at all
#: under the campaign's lease, and the argv is caller-supplied.
#: The only head a test command may have. Everything after it is arguments to
#: pytest, and those are still held to the workspace (no absolute path, no
#: traversal, no inline program smuggled through a pytest option).
_TEST_ARGV_HEAD = ("python", "-m", "pytest")
#: Options a test command may carry, by name. Everything else beginning with
#: ``-`` is refused.
#:
#: Round 1 defeated the HEAD denylist with ``-Ic``; round 2 defeated the
#: ARGUMENT denylist the same way, one token to the right. ``-pevilplugin``
#: imports and EXECUTES an arbitrary module before conftest, under the
#: campaign's lease. ``-cC:/Windows/win.ini`` makes pytest read a config file
#: outside the workspace, whose ``addopts`` re-injects any option at all --
#: including the plugin load. Both were admitted, because the loop skipped
#: every ``-``-leading token that was not an EXACT member of a forbidden set.
#:
#: A denylist of an option parser this module does not own cannot be closed.
#: This set can only grow by evidence that a campaign genuinely needs an
#: option, and each addition has to argue that the option reads nothing
#: outside the workspace and loads no code.
_TEST_ARGV_BARE_OPTIONS = frozenset({
    "-q", "--quiet", "-x", "--exitfirst", "--no-header", "--no-summary",
})
#: ``--tb=STYLE`` selects how much of a traceback is printed. The output is not
#: retained at all, so this only affects the gate's scratch, but the value is
#: still held to pytest's own closed set rather than passed through.
_TEST_ARGV_TB_STYLES = frozenset({"auto", "long", "short", "line", "native", "no"})
#: pytest builds its parser with ``fromfile_prefix_chars="@"``. A token with
#: this prefix is resolved BY ARGPARSE into the contents of the named file,
#: spliced in as arguments, with no path restriction -- so it is not a path and
#: no path rule can hold it. Measured round 3: a `conftest.py` outside the
#: workspace was imported and executed inside the gate in all three arms.
_ARGPARSE_PREFIX_CHARS = frozenset("@")
MAX_TEST_MAXFAIL = 1000
#: Only this interpreter token may open a test command. It is replaced by the
#: interpreter the campaign resolved, so an argv can never name a binary path.
_TEST_ARGV_INTERPRETER = "python"
#: Windows resolves these as devices in EVERY directory and with ANY extension,
#: so `NUL`, `nul.txt` and `sub/dir/CON.py` are all the device, not a file.
#: Writing to one succeeds and stores nothing.
_RESERVED_DEVICE_NAMES = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"}
    | {f"COM{n}" for n in range(1, 10)}
    | {f"LPT{n}" for n in range(1, 10)}
)
MAX_TEST_ARGV = 32
MAX_TEST_ARG_CHARS = 200
MAX_TEST_TIMEOUT_S = 900
#: The command's output is NOT retained. Measured 2026-09-10 (Cerberus round 1):
#: the child inherits the operator's environment, so a candidate that prints it
#: put a live API key into the retained observation. A digest and the report
#: counts say what happened; the output itself stays in the gate's scratch.
MAX_TEST_OUTPUT_CHARS = 0
#: The report the campaign appends to every test command, inside the workspace.
#: An exit code cannot distinguish "the tests passed" from "no test ran"; the
#: proven attack switched the suite off and passed (Cerberus round 1, CRITICAL 2).
TEST_REPORT_RELATIVE = "daedalus-ariadne-report.xml"
#: The campaign's own pytest config, written into the workspace and passed with
#: `-c`. Without it pytest searches UPWARD for a config, so an ini file in an
#: ancestor directory sets rootdir and its `addopts` re-injects any option --
#: including `-p <module>`, which loads and executes code inside the judging
#: process (Cerberus round 4, high 1). `--confcutdir` closes only the conftest
#: half of that; `-c` closes both. Deliberately empty apart from the section
#: header: it is a fence, not a place to configure anything.
TEST_CONFIG_RELATIVE = "daedalus-ariadne-pytest.ini"
TEST_CONFIG_BODY = b"[pytest]\n"
#: The report is hostile input to the orchestrator, so it is bounded before it
#: is parsed at all.
MAX_TEST_REPORT_BYTES = 4 * 1024 * 1024
#: Every git call this module makes is bounded.
GIT_CALL_TIMEOUT_S = 120
#: Seconds allowed per arm for building the evaluation workspace, on top of the
#: command's own timeout. Measured on this repository: 4.5-5 s for 6371 files.
WORKSPACE_BUILD_ALLOWANCE_S = 60
#: Files that CONFIGURE a test session rather than being tested by it. A
#: candidate that owns one of these owns the verdict, whatever the test files
#: say, so they are refused as targets for the whole class -- the same shape as
#: SELF_RENOVATION_PROTECTED_PREFIXES, by name at any depth.
SESSION_CONTROL_NAMES = frozenset({
    "conftest.py", "pytest.ini", "pyproject.toml", "setup.cfg", "setup.py",
    "tox.ini", "sitecustomize.py", "usercustomize.py", "conftest.pyi",
})
SESSION_CONTROL_SUFFIXES = (".pth",)
#: A workspace built from one revision of an ordinary repository. Measured on
#: this repository 2026-09-10 through the object database: 6378 files, 282 MiB,
#: 4.65 s -- the four tracked symlinks are materialised as the paths they store,
#: which is what their blobs contain, so this repository is admissible as its
#: own self-Renovation subject again.
MAX_WORKSPACE_FILES = 50_000
MAX_WORKSPACE_BYTES = 2 * 1024 * 1024 * 1024


@dataclass(frozen=True)
class TestCommandEvaluator:
    """A frozen, caller-declared test command.

    What this is, precisely, and what it is not:

    1. the candidate cannot pick its judge -- ``argv`` and ``timeout_s`` come
       from the caller, are frozen into the ``ExperimentSpec`` before any arm
       runs, and their digest is part of the campaign's identity;
    2. the candidate cannot rewrite the TEST FILES or the session configuration
       -- the workspace is the pinned revision with exactly one file
       overwritten, a target under ``test_roots`` is refused, and so is one
       named in :data:`SESSION_CONTROL_NAMES`. It is NOT true that the
       overwritten file cannot influence the run: it must be a file the suite
       exercises, or the negative control could never fail. That is the point
       of the arm, and it is also the hole a `conftest.py` target opened
       (Cerberus round 1);
    3. an exit code is not a verdict -- the campaign appends its own JUnit
       report and requires that tests actually EXECUTED, and that the repair arm
       executed exactly as many as the baseline, because a candidate that
       switched the suite off exited zero and was nominated, and a candidate
       that forged a report claiming 41 tests was nominated too;
    4. a judge that cannot tell the difference is reported -- the negative
       control arm must FAIL, and when it passes the campaign nominates nothing
       and says the suite is blind to this file.

    NOT PROOF AGAINST A HOSTILE GENERATOR, and this is the sharpest limit of
    the whole design. The target file must be one the suite imports, so the
    candidate's code runs inside the judging process. Everything the harness
    reads back afterwards -- the exit code, the output, the JUnit report in the
    workspace -- is produced by that process, and the workspace has to stay
    writable or pytest could not write the report at all. A candidate that
    executes code at import can therefore write a report and exit zero.
    Equality with the baseline's executed count closes the demonstrated attack
    and the "more but weaker" class, but a forger that counts the suite itself
    and reports that number is not caught. The verdict is a SELF-REPORT, every
    observation says so in ``verdict_is_self_reported``, and the structural fix
    -- observing the run from outside the child -- is a separate packet. What
    stands between a forged verdict and the repository is unchanged: nomination
    is not promotion, and promotion needs a one-use owner approval.

    NOT a sandbox claim. The child runs in the existing contained gate, whose
    environment is a DENYLIST, not an allowlist, and which has no network fence.
    Measured 2026-09-10: a candidate that prints its environment sees the
    operator's provider keys, and a socket to a public address connects. The
    approval secret is scrubbed; nothing else is. This evaluator therefore does
    not retain the command's output, and the receipt states the reach rather
    than implying a fence.
    """

    argv: tuple[str, ...]
    timeout_s: int = 120
    test_roots: tuple[str, ...] = ("tests/",)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": "test-command-v1",
            "argv": list(self.argv),
            "timeout_s": self.timeout_s,
            "test_roots": list(self.test_roots),
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def _admit_test_evaluator(value: object) -> TestCommandEvaluator:
    """Every refusal here happens before the repository is observed."""

    if not isinstance(value, TestCommandEvaluator):
        raise AriadneCampaignError("evaluator must be a TestCommandEvaluator")
    argv = value.argv
    if (not isinstance(argv, tuple) or not 1 <= len(argv) <= MAX_TEST_ARGV
            or any(type(item) is not str for item in argv)):
        raise AriadneCampaignError(
            f"evaluator argv must be 1-{MAX_TEST_ARGV} text arguments")
    # An ALLOWLIST, because a denylist of an option parser this module does not
    # own cannot be closed: `-Ic` bundles the inline-program switch, and so do
    # `-Sc` and `--command=`; `-` reads the program from stdin; `-m pip install`
    # writes the interpreter that judges every later campaign (Cerberus round 1
    # of this packet, CRITICAL 2). The command IS `python -m pytest`.
    if tuple(argv[:3]) != _TEST_ARGV_HEAD:
        raise AriadneCampaignError(
            "evaluator argv must be exactly " + " ".join(_TEST_ARGV_HEAD) + " followed by "
            "arguments for it")
    for item in argv:
        if not item or len(item) > MAX_TEST_ARG_CHARS or "\x00" in item:
            raise AriadneCampaignError("evaluator argv entries must be short, non-empty text")
    # Every argument is admitted BY NAME or refused. The previous version
    # skipped any `-`-leading token it did not recognise, which admitted
    # `-pevilplugin` (loads and executes a module) and `-cC:/Windows/win.ini`
    # (reads a config outside the workspace whose `addopts` re-injects
    # anything) -- Cerberus round 2 of this packet, CRITICAL 2. A path names
    # something INSIDE the workspace and nothing else.
    admitted = list(argv)
    index = 3
    while index < len(argv):
        item = argv[index]
        index += 1
        if not item.startswith("-"):
            # ADMIT a path; do not enumerate bad ones. Three rounds were lost
            # to enumeration -- `-Ic`, then `-pevilplugin` and
            # `-cC:/Windows/win.ini`, then `@C:/Windows/Temp/pwn.txt`, which is
            # not a path at all and slipped past four hand-written shape checks
            # because the leading `@` shifts every offset by one (Cerberus
            # round 3, CRITICAL 3).
            if item[:1] in _ARGPARSE_PREFIX_CHARS:
                raise AriadneCampaignError(
                    f"evaluator argv may not carry an argument FILE: {item}. A leading "
                    f"'{item[:1]}' is argparse's fromfile prefix, so this names a file "
                    "whose lines are spliced in as arguments -- with no path "
                    "restriction, before pytest sees them")
            # Use the value the primitive RETURNS. Discarding it admitted
            # `tests\\unit` and handed pytest the backslash spelling verbatim,
            # which works on Windows and exits 4 on POSIX -- validating one
            # string and executing another (Cerberus round 4, low 2).
            admitted[index - 1] = _admit_workspace_relative(
                item.rstrip("/"), label="evaluator argv path")
            continue
        if item in _TEST_ARGV_BARE_OPTIONS:
            continue
        if item.startswith("--tb="):
            if item[len("--tb="):] not in _TEST_ARGV_TB_STYLES:
                raise AriadneCampaignError(
                    f"evaluator argv has an unknown traceback style: {item}")
            continue
        if item.startswith("--maxfail="):
            digits = item[len("--maxfail="):]
            # `str.isdigit()` is true for `\xb2` while `int()` raises on it, so
            # the ascii guard is what keeps every refusal here an
            # AriadneCampaignError (Cerberus round 3, low).
            if (not digits.isascii() or not digits.isdigit()
                    or not 1 <= int(digits) <= MAX_TEST_MAXFAIL):
                raise AriadneCampaignError(
                    f"evaluator argv has an unusable --maxfail: {item}")
            continue
        consumed = _plugin_disable_tokens(item, argv, index)
        if consumed is not None:
            index += consumed
            continue
        raise AriadneCampaignError(
            "evaluator argv admits options by name only, and this is not one of them: "
            f"{item}. Permitted: " + ", ".join(sorted(_TEST_ARGV_BARE_OPTIONS))
            + ", --tb=STYLE, --maxfail=N, and '-p no:NAME' to DISABLE a plugin. A "
            "bundled short option defeats any denylist, so there is no denylist")
    # No working directory: the kernel's command gate requires ``gate_cwd='.'``
    # and runs at the workspace root, so offering one would be a promise the
    # kernel refuses. The argv carries the selection instead.
    if (isinstance(value.timeout_s, bool) or not isinstance(value.timeout_s, int)
            or not 1 <= value.timeout_s <= MAX_TEST_TIMEOUT_S):
        raise AriadneCampaignError(
            f"evaluator timeout_s must be an integer between 1 and {MAX_TEST_TIMEOUT_S}")
    roots = value.test_roots
    if not isinstance(roots, tuple) or not roots or any(type(r) is not str for r in roots):
        raise AriadneCampaignError("evaluator test_roots must be non-empty text prefixes")
    for root in roots:
        _admit_workspace_relative(root.rstrip("/"), label="evaluator test root")
    if tuple(admitted) != argv:
        # The admitted spelling is what runs. Returning a record whose argv
        # differs from the one the caller wrote would change the digest that
        # identifies the campaign, so the normalisation is reported rather than
        # applied silently.
        raise AriadneCampaignError(
            "evaluator argv paths must already be in their admitted spelling "
            f"(forward slashes, no trailing separator): {' '.join(admitted[3:])}")
    return value


def _plugin_disable_tokens(item: str, argv: tuple[str, ...], next_index: int) -> int | None:
    """How many EXTRA tokens a plugin-disabling option consumes, or ``None``
    when this is not a plugin option at all.

    ``-p`` is the one option a test command genuinely needs -- the campaign's
    own command must disable the cache plugin so pytest does not write into the
    tree it is judging -- and it is also the one that LOADS and executes an
    arbitrary module. It is admitted only in its ``no:NAME`` disabling form,
    including the bundled ``-pno:NAME`` that defeated round 2's denylist.

    ``--plugin`` was admitted here until round 3 and pytest has no such option:
    ``-p`` is registered short-only. Admitting a spelling the tool rejects is
    surface for nothing, and the packet's suite had pinned it as a GOOD campaign
    shape -- a command that exits 4 in every arm.
    """

    if item == "-p":
        value, consumed = (argv[next_index] if next_index < len(argv) else ""), 1
    elif item.startswith("-p"):
        value, consumed = item[2:], 0
    else:
        return None
    if not value.startswith("no:") or not value[3:]:
        raise AriadneCampaignError(
            "evaluator argv may only DISABLE a plugin ('-p no:NAME'), not load one: "
            f"{item}")
    return consumed


def _admit_workspace_relative(value: str, *, label: str) -> str:
    """A path that stays inside the workspace, by the same lexical rule the
    target path is held to. No absolute path, no traversal, no device name."""

    if value.startswith("/") or value.startswith("\\") or ":" in value:
        raise AriadneCampaignError(f"{label} must be relative to the workspace")
    parts = [part for part in value.replace("\\", "/").split("/")]
    if not parts or any(part in ("", ".", "..") for part in parts):
        raise AriadneCampaignError(f"{label} must have no empty or relative segments")
    for part in parts:
        if part != part.strip() or part.endswith("."):
            raise AriadneCampaignError(f"{label} has a segment the filesystem would rewrite")
        if part.split(".", 1)[0].upper() in _RESERVED_DEVICE_NAMES:
            # The docstring promised this check and did not have it. A tree of
            # `NUL` + `ok.txt` extracted as two files with ONE on disk: the
            # write to `NUL` silently succeeds, the counter still says two, and
            # nothing refuses (Cerberus round 2 of this packet, high 1). That
            # is the O2-2 shape -- the workspace silently differing from the
            # revision -- at a smaller scale.
            #
            # Refused on EVERY platform, not only Windows. The guarantee is
            # that the workspace IS the revision on every supported host, and a
            # name that cannot be materialised identically everywhere makes
            # that guarantee false wherever it is admitted.
            raise AriadneCampaignError(
                f"{label} has a segment no Windows filesystem can hold, so the workspace "
                f"could not be the revision on every host: {part}")
    return "/".join(parts)


def _read_test_report(path: Path) -> dict[str, int]:
    """The counts a JUnit report states, or a refusal.

    This is the difference between "the command exited zero" and "the tests
    ran and passed". The proven attack (Cerberus round 1) exited zero with
    every item skipped.
    """

    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AriadneCampaignError(
            f"the test command wrote no report: {type(exc).__name__}"
        ) from exc
    if len(raw) > MAX_TEST_REPORT_BYTES:
        raise AriadneCampaignError("the test report exceeds its bound")
    # Hostile input: a candidate influenced the process that wrote this file.
    # `ElementTree` does not resolve EXTERNAL entities, but it expands internal
    # ones, which is the billion-laughs shape. The parser exposes no handler to
    # assign, so the two constructs are refused textually before parsing --
    # neither belongs in a JUnit report, and the alternative is a dependency
    # (`defusedxml`) this repository does not have.
    lowered = raw[:4096].lower()
    if b"<!doctype" in lowered or b"<!entity" in raw.lower():
        raise AriadneCampaignError(
            "the test report declares a doctype or an XML entity"
        )
    try:
        root_element = ElementTree.fromstring(raw)
    except (ElementTree.ParseError, ValueError) as exc:
        raise AriadneCampaignError(
            f"the test report is not readable XML: {type(exc).__name__}"
        ) from exc
    suites = ([root_element] if root_element.tag == "testsuite"
              else list(root_element.iter("testsuite")))
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for suite in suites:
        for key in counts:
            try:
                counts[key] += int(suite.get(key, "0") or 0)
            except ValueError as exc:
                raise AriadneCampaignError(
                    "the test report has a non-numeric count"
                ) from exc
    counts["executed"] = max(0, counts["tests"] - counts["skipped"])
    return counts


def _read_test_identities(path: Path) -> tuple[str, ...]:
    """Which tests ran and what each said, as sorted `id=outcome` pairs.

    A cardinal count cannot tell a suite that ran from a suite that was
    neutered in place: `Function.runtest = lambda self: None` collects and
    "runs" exactly the same tests and reports the same number (Odysseus round 2
    on the merged packet, O2-1b). The identities can.
    """

    try:
        raw = path.read_bytes()
    except OSError:
        return ()
    if len(raw) > MAX_TEST_REPORT_BYTES or b"<!doctype" in raw[:4096].lower() or b"<!entity" in raw.lower():
        return ()
    try:
        root_element = ElementTree.fromstring(raw)
    except (ElementTree.ParseError, ValueError):
        return ()
    identities: list[str] = []
    for case in root_element.iter():
        # Namespace-blind on the way in as well as on the way down: a namespaced
        # report yielded NO identities at all, which read as "nothing ran"
        # (Cerberus round 1 of this packet, medium 1).
        if case.tag.rsplit("}", 1)[-1] != "testcase":
            continue
        name = f"{case.get('classname', '')}::{case.get('name', '')}"
        # Worst outcome wins, at any depth. First-child-wins let a `skipped`
        # element listed before a `failure` hide the failure.
        found = {child.tag.rsplit("}", 1)[-1] for child in case.iter()}
        status = str(case.get("status", "")).lower()
        if "error" in found or status in ("error", "errored"):
            outcome = "error"
        elif "failure" in found or status in ("failure", "failed"):
            outcome = "failure"
        elif "skipped" in found or status == "skipped":
            outcome = "skipped"
        else:
            outcome = "passed"
        identities.append(f"{name}={outcome}")
    return tuple(sorted(identities))


def _remove_evaluation_workspace(workspace: Path) -> bool:
    """Remove one arm's evaluation workspace. The receipt is the evidence."""

    try:
        shutil.rmtree(workspace, ignore_errors=False)
        return True
    except FileNotFoundError:
        return True
    except OSError:
        return False


def _campaign_lease_timeout_s(timeout_s: int, evaluator: "TestCommandEvaluator | None") -> int:
    """How long the whole campaign may take: three arms plus their workspaces.

    A workspace of this repository takes about 5 s to build, so the allowance is
    three times the arm timeout plus a construction margin per arm.
    """

    per_arm = timeout_s if evaluator is None else evaluator.timeout_s
    return int(per_arm * 3 + (0 if evaluator is None else 3 * WORKSPACE_BUILD_ALLOWANCE_S))


def _extract_revision(root: Path, revision: str, into: Path) -> tuple[int, int]:
    """Build an evaluation workspace from one Git revision's OBJECTS.

    Not from `git archive`. That command applies `$GIT_DIR/info/attributes`,
    which can select an export filter, a smudge filter (an arbitrary shell
    command named in an untracked config) and an end-of-line conversion. All
    three change what a campaign judges, none of them is in any revision, and
    none of them shows up in `git status`. A reviewer used one to rewrite the
    guarding test's body while the file list stayed identical, and another to
    run a command on the host (Cerberus round 1 of G1-IKARUS-49).

    Reading blobs by digest has none of those inputs, and every file is checked
    against the digest the revision names before it is counted.
    """

    entries = _revision_blobs(root, revision)
    if len(entries) > MAX_WORKSPACE_FILES:
        raise AriadneCampaignError("evaluation workspace exceeds its bounds")
    into.mkdir(parents=True, exist_ok=True)
    if not entries:
        return 0, 0
    request = b"".join(f"{digest}\n".encode("ascii") for _mode, digest, _name in entries)
    stream = _git_out(root, ["cat-file", "--batch"], stdin=request)
    files = 0
    total = 0
    seen: set[str] = set()
    cursor = 0
    for mode, digest, name in entries:
        newline = stream.find(b"\n", cursor)
        if newline == -1:
            raise AriadneCampaignError("the pinned revision's object stream ended early")
        header = stream[cursor:newline].decode("ascii", errors="strict").split()
        cursor = newline + 1
        if len(header) != 3 or header[1] != "blob":
            raise AriadneCampaignError(f"the pinned revision does not yield a blob for {name}")
        size = int(header[2])
        payload = stream[cursor:cursor + size]
        cursor += size + 1  # git writes a newline after every object
        if len(payload) != size:
            raise AriadneCampaignError(f"the pinned revision's object is truncated: {name}")
        # Bound to the oid the TREE named, NOT to `header[0]`, the oid git
        # echoed back. Checking the payload against git's own echo would verify
        # that git is self-consistent and nothing else; checking it against the
        # digest the revision names is what makes this a construction of the
        # revision (Cerberus round 2, low). A substituted object is internally
        # consistent and dies here, which is why a separate header comparison
        # would be redundant rather than defence in depth.
        if hashlib.sha1(b"blob %d\x00" % size + payload).hexdigest() != digest:
            raise AriadneCampaignError(f"the pinned revision's object does not match its digest: {name}")
        folded = name.casefold()
        if folded in seen:
            # Two names the filesystem folds together: one would silently
            # overwrite the other and the count would still say two.
            raise AriadneCampaignError(
                f"the pinned revision contains two paths this filesystem folds together: {name}")
        seen.add(folded)
        files += 1
        total += size
        if total > MAX_WORKSPACE_BYTES:
            raise AriadneCampaignError("evaluation workspace exceeds its bounds")
        target = into.joinpath(*name.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        # A symlink's blob IS its target path, and writing it as a regular file
        # is a faithful materialisation of what the revision stores. The tests
        # do not follow it, and refusing outright made this repository -- which
        # has four tracked symlinks -- an inadmissible subject for its own
        # self-Renovation strand.
        target.write_bytes(payload)
        # The name checks refuse the device names this module knows about. This
        # refuses whatever it does not: a workspace whose file count is not the
        # revision's file count is not the revision, and the count is the thing
        # every later comparison rests on.
        written = target.stat().st_size if target.is_file() else None
        if written != size:
            raise AriadneCampaignError(
                "the pinned revision did not materialise: the filesystem stored "
                f"{'nothing' if written is None else str(written) + ' bytes'} for {name}, "
                f"not {size}")
    return files, total


def _refuse_target_inside_test_roots(target_path: str, test_roots: tuple[str, ...]) -> None:
    """A candidate may not be a test when tests are the judge.

    The workspace is the pinned revision with one file replaced, so a target
    inside a test root would let the candidate rewrite the very assertions that
    decide its verdict -- the plan's section 8.1 rule, applied to the project's
    own suite rather than only to this evaluator's tests.
    """

    spelling = target_path.replace("\\", "/").strip("/").casefold()
    for root in test_roots:
        prefix = root.replace("\\", "/").strip("/").casefold()
        if spelling == prefix or spelling.startswith(prefix + "/"):
            raise AriadneCampaignError(
                "target_path is inside a declared test root, and the tests are the "
                f"evaluator for this campaign: {root}"
            )
    name = spelling.rsplit("/", 1)[-1]
    if name in SESSION_CONTROL_NAMES or name.endswith(SESSION_CONTROL_SUFFIXES):
        raise AriadneCampaignError(
            "target_path configures the test session rather than being tested by it, "
            f"so a candidate could decide its own verdict: {name}"
        )


def _git_out(root: Path, args: list[str], *, stdin: bytes | None = None) -> bytes:
    """One bounded git call with a scrubbed environment.

    The kernel scrubs exactly these variables on its own git path; the
    evaluator's calls did not, and one of them executed a filter command from
    an untracked config with the operator's environment (Cerberus round 1 of
    this packet, medium 3).
    """

    env = dict(os.environ)
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG",
                 "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_ATTR_SYSTEM",
                 "GIT_SSH_COMMAND", "GIT_EXTERNAL_DIFF", "GIT_ASKPASS"):
        env.pop(name, None)
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args], input=stdin, capture_output=True,
            check=True, timeout=GIT_CALL_TIMEOUT_S, env=env,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise AriadneCampaignError(
            f"the pinned revision could not be read: {type(exc).__name__}"
        ) from exc


def _revision_blobs(root: Path, revision: str) -> tuple[tuple[str, str, str], ...]:
    """Every entry the revision declares: (mode, blob digest, path).

    Read from the object database, not from `git archive`. `git archive`
    applies `$GIT_DIR/info/attributes`, which selects export filters AND smudge
    filters -- arbitrary shell commands named in an untracked config. The
    reviewer used one to rewrite the guarding test's content while the file
    list stayed identical, and to run a command on the host (CRITICAL 1).
    """

    listing = _git_out(root, ["ls-tree", "-r", "-z", revision]).decode("utf-8", errors="strict")
    entries: list[tuple[str, str, str]] = []
    for record in listing.split("\x00"):
        if not record:
            continue
        meta, _, name = record.partition("\t")
        parts = meta.split()
        if len(parts) != 3:
            raise AriadneCampaignError("the pinned revision's tree listing is unreadable")
        mode, kind, digest = parts
        if kind != "blob":
            # A submodule is a commit pointer, not source this evaluator reads.
            raise AriadneCampaignError(
                f"the pinned revision contains a {kind} entry this workspace cannot "
                f"represent: {name}")
        entries.append((mode, digest, _admit_workspace_relative(name, label="revision entry")))
    return tuple(sorted(entries, key=lambda item: item[2]))




_CAMPAIGN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_REPAIR_FRAGMENT_BYTES = 1 * 1024 * 1024
MAX_CAMPAIGN_FILE_BYTES = 16 * 1024 * 1024
_NEGATIVE_CONTROL_SUFFIX = "__ariadne_negative__"
_OUTER_EFFECT_BINDING_SCHEMA = "daedalus-ariadne-outer-effect-binding/1"
_INNER_EFFECT_BINDING_SCHEMA = "daedalus-ariadne-inner-effect-binding/1"
_ATTEMPT_REPORT_SCHEMA = "daedalus-ariadne-attempt-report/2"
_EVALUATOR_ERROR_SCHEMA = "daedalus-ariadne-evaluator-error/1"
_MAX_OUTER_EFFECT_BINDING_BYTES = 64 * 1024
_MAX_ATTEMPT_REPORT_BYTES = 1 * 1024 * 1024
_MAX_RECEIPT_PROVENANCE_INPUTS = 256


class AriadneCampaignError(RuntimeError):
    pass


class AriadneRequestError(AriadneCampaignError):
    """The owner-supplied campaign subject is malformed or unavailable."""


class AriadneConflictError(AriadneCampaignError):
    """A stable request binding no longer matches repository state."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _prov(origin: str, revision: str, at: str, *digests: str, trace: str):
    return ContractProvenance(
        origin=origin,
        source_revision=revision,
        created_at=at,
        input_digests=tuple(sorted(set(digests))),
        trace_id=trace,
    )


def _campaign_id(value: object) -> str:
    text = value if isinstance(value, str) else ""
    if not _CAMPAIGN_ID_RE.fullmatch(text):
        raise AriadneCampaignError(
            "campaign_id must be 1-64 path-free letters, digits, '.', '_' or '-'"
        )
    return text


def _repair_fragment(value: object, *, label: str, allow_empty: bool) -> tuple[str, bytes]:
    if type(value) is not str:
        raise AriadneCampaignError(f"{label} must be a strict string")
    if not value and not allow_empty:
        raise AriadneCampaignError(f"{label} must be non-empty")
    try:
        payload = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise AriadneCampaignError(f"{label} must be strict UTF-8") from exc
    if len(payload) > MAX_REPAIR_FRAGMENT_BYTES:
        raise AriadneCampaignError(
            f"{label} exceeds the {MAX_REPAIR_FRAGMENT_BYTES}-byte repair-fragment ceiling"
        )
    return value, payload


def _is_domain_failure(failure: BaseException) -> bool:
    """True for a campaign-domain verdict that the retained failed receipt already carries.

    Cancellation (``LoopHalted``) and foreign exceptions (a crash inside the
    gate, ``OSError``) are not verdicts about the candidate and keep raising.
    """
    from daedalus.spine.killswitch import LoopHalted

    if isinstance(failure, LoopHalted):
        return False
    if isinstance(failure, (AriadneRequestError, AriadneConflictError)):
        # A refusal (request shape, unsafe target) or a conflict (stale
        # revision, changed material) raised inside an arm is not a verdict
        # about the candidate: it keeps raising (council-20260905T134012Z, r1 claim 1).
        return False
    return isinstance(failure, AriadneCampaignError)


def _verify_head(root: Path, source_revision: str):
    try:
        return verify_repository_head_revision(root, source_revision)
    except (RepositoryHeadRevisionBindingError, RepositoryHeadRevisionRaceError) as exc:
        raise AriadneConflictError(f"source_revision conflict: {exc}") from exc
    except RepositoryHeadRevisionShapeError as exc:
        message = f"repository HEAD is unavailable or unsafe: {exc}"
        if _is_gitdir_pointer_file(root / ".git"):
            # Deliberately unsupported subject layout (G1-ARIADNE-06): a gitdir
            # pointer is bytes a candidate can rewrite, so the gate never
            # follows it (tests/test_git_is_a_process_launcher.py measured the
            # attack). Name the layout and the remedy instead of the bare
            # shape error.
            message += (
                "; the subject is a linked git worktree (.git is a gitdir pointer "
                "file), a deliberately unsupported subject layout: clone the "
                "repository or use its common checkout"
            )
        raise AriadneRequestError(message) from exc


def _is_gitdir_pointer_file(path: Path) -> bool:
    """True when ``.git`` is a regular file whose first line is ``gitdir:``."""
    try:
        if path.is_symlink() or not path.is_file():
            return False
        with path.open("rb") as stream:
            return stream.read(7) == b"gitdir:"
    except OSError:
        return False


_BASE_BINDING_SCHEMA = "daedalus-ariadne-base-tree-binding/1"


def _base_tree_binding(
    *, campaign_id: str, source_revision: str, relative: str, base_file_sha256: str
) -> dict[str, Any]:
    """What the campaign base IS: the working-tree bytes, content-addressed.

    The receipt binds ``source_revision`` (the verified HEAD) and the base
    tree (CAS). It never verified that the base bytes are the file's content
    AT that revision, and a raw byte compare against the HEAD blob would lie
    under git line-ending filters. So the claim is stated instead of faked:
    ``base_source`` is the working tree and ``head_content_verified`` is
    false until a separate packet verifies it through git itself.
    """
    return {
        "schema": _BASE_BINDING_SCHEMA,
        "campaign_id": campaign_id,
        "source_revision": source_revision,
        "target_path": relative,
        "base_file_sha256": base_file_sha256,
        "base_source": "working-tree",
        "head_content_verified": False,
    }


#: Master plan section 8.1, the self-Renovation leakage boundary, as code.
#: A candidate produced from ``daedalus/`` sources may not touch the trust
#: kernel (spine, kernel policy enforcement, promotion, approvals, contracts),
#: the plan, its amendment chain, the agent constitution, the mechanical veto
#: policy, its own evaluator (this module) or the tests of that evaluator.
#: Compared case-insensitively against the admitted repository-relative path
#: BEFORE the repository is observed. A prefix ending in "/" names a directory;
#: any other prefix matches the path itself and every path that continues it
#: (``daedalus/kernel/promotion`` covers ``promotion.py``, ``promotion_*.py``).
#: The tuple is unconditional: a foreign repository that happens to carry an
#: ``AGENTS.md`` is refused the same way, which is the safe direction.
#: Plan section 8.1 names the spine, kernel policy enforcement, the plan, the
#: amendment chain, `AGENTS.md` and "tests of its own evaluator". This list is
#: STRICTER than that text, which section 0 permits: for effects the stricter
#: mechanical policy wins, and the plan is a floor for protection rather than a
#: ceiling.
#:
#: The five `daedalus/` entries below were added after a measurement found that
#: the boundary covered `campaign.py` but NOT the code that enforces it: a
#: self-Renovation candidate could nominate an edit to its own tool door, to
#: the gate that decides whether a recurring series continues, to the module
#: where `promote_candidates` lives, and to the constant that says the write
#: wave policy is "never". Promotion still required an owner approval, so this
#: was defence in depth rather than a breach -- but a candidate that can
#: nominate a change to its own door is one approval away from a candidate
#: without one, and that is the wrong thing to be relying on when campaigns run
#: unattended.
#:
#: Protection is by FILE where the risk is a specific constant or callable, and
#: by DIRECTORY where the whole thing is boundary machinery. The cost is real
#: and stated: self-Renovation can no longer propose an improvement to any of
#: these, so improving them stays human work.
SELF_RENOVATION_PROTECTED_PREFIXES: tuple[str, ...] = (
    "daedalus/spine/",
    "daedalus/kernel/policy/",
    "daedalus/kernel/promotion",
    "daedalus/kernel/approvals.py",
    "daedalus/kernel/contracts/",
    # D1's parent, 35 lines. A conditional shim here that pre-seeds
    # `sys.modules["daedalus.ariadne"]` removes the boundary entirely, measured
    # with four suites at 193 passed either way (Odysseus round 3).
    "daedalus/__init__.py",
    # The WHOLE package, not just `campaign.py`. `__init__.py` re-exports
    # `run_campaign`, and both the HTTP door and the tool-door runner resolve
    # through it -- so one conditional shim in an admissible `__init__` used to
    # disable this entire boundary, all nine additions included, with the
    # boundary's own suite green (Odysseus round 1, D1). Protecting the
    # definition and leaving the package door open protects nothing.
    "daedalus/ariadne/",
    # The door that enforces this boundary, and the fence that admits the tool.
    "daedalus/runtimes/computer_ariadne.py",
    "daedalus/runtimes/computer.py",
    # `_repeat_permission`: whether a recurring campaign series continues.
    "daedalus/orchestration/ikarus/computer_schedule.py",
    # `promote_candidates` itself. `daedalus/kernel/promotion` covered the
    # contracts and missed the callable.
    "daedalus/kairos/gated_writes.py",
    # WRITE_WAVE_POLICY_LEVELS = ("never",) and DEFAULT_WRITE_WAVE_POLICY.
    "daedalus/config.py",
    "docs/IKARUS_ARIADNE_MASTER_PLAN.md",
    "docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl",
    "AGENTS.md",
    "CLAUDE.md",
    ".agentenv/",
    # "tests of its own evaluator" (section 8.1). `tests/test_ariadne` covered
    # four files and missed every other suite that guards this boundary.
    "tests/test_ariadne",
    "tests/test_ikarus_computer_loop_ariadne.py",
    "tests/test_ikarus_computer_schedule",
    "tests/runtimes/test_computer_ariadne.py",
    # The kernel's own suites: `daedalus/kernel/policy/`, `promotion*`,
    # `approvals.py` and `contracts/` are protected, so a candidate must not
    # reach the tests that prove they work either.
    "tests/kernel/",
    # Every protected suite loads it. One edit to the admissible root conftest
    # and the protected suites collect NOTHING -- "no tests ran in 0.23s" --
    # which removes the evidence a reviewer reads rather than changing what it
    # says (Odysseus round 1, D2).
    "tests/conftest.py",
    # One directory down, the same defect: `tests/runtimes/conftest.py` was
    # admissible while `tests/runtimes/test_computer_ariadne.py` is protected
    # here. Eleven lines of `pytest_collection_modifyitems` took that suite from
    # `66 passed` to `no tests ran` (Odysseus round 2).
    "tests/runtimes/conftest.py",
    # And with the conftest closed, this costs one consistent line: it is the
    # suite that DIRECTLY proves the release fence refuses, while the protected
    # `test_computer_ariadne.py` only catches it incidentally.
    "tests/runtimes/test_computer_service.py",
)


def protected_prefix_for(relative: str) -> str | None:
    """The boundary entry an admitted relative path falls under, or None."""
    folded = relative.casefold()
    for prefix in SELF_RENOVATION_PROTECTED_PREFIXES:
        needle = prefix.casefold()
        if folded == needle or folded.startswith(needle):
            return prefix
    return None


def _admit_target_path(value: str) -> str:
    """Pure path admission: no filesystem, no repository, no HEAD.

    Shape and mandatory-ignored-root refusals happen before the repository is
    observed at all, so a refused request leaves no trace and needs no
    ``.git``. Reading the admitted path is :func:`_safe_target`.
    """
    if type(value) is not str:
        raise AriadneRequestError("target_path must be a strict string")
    try:
        task = TaskSpec(
            task_id="ariadne-admission",
            instruction="admit",
            target_paths=(value,),
        )
    except (TypeError, ValueError) as exc:
        raise AriadneRequestError(f"target_path is invalid: {exc}") from exc
    relative = task.target_paths[0]
    ignored = {item.casefold() for item in MANDATORY_IGNORED_ROOTS}
    if relative.split("/", 1)[0].casefold() in ignored:
        raise AriadneRequestError(
            "target_path must not enter a mandatory ignored root"
        )
    protected = protected_prefix_for(relative)
    if protected is not None:
        raise AriadneRequestError(
            "target_path is inside the self-Renovation leakage boundary "
            f"(master plan section 8.1): {protected}"
        )
    return relative


def _safe_target(root: Path, value: str):
    relative = _admit_target_path(value)
    try:
        return relative, read_repository_source(root, relative)
    except RepositoryTreeRaceError as exc:
        raise AriadneConflictError(f"target_path changed during admission: {exc}") from exc
    except RepositoryTreeReadError as exc:
        raise AriadneRequestError(f"target_path is unavailable or unsafe: {exc}") from exc


def _store_scoped_tree(
    store: SourceTreeStore,
    *,
    payload: bytes,
    relative: str,
    tree_id: str,
    source_revision: str,
    created_at: str,
    trace_id: str,
    origin: str,
) -> StoredSourceTree:
    """Persist one stabilized target file in the canonical source-tree CAS."""
    blob = store.put_bytes(payload)
    manifest = SourceTreeManifest(
        tree_id=tree_id,
        source_revision=source_revision,
        entries=(SourceTreeEntry(
            path=relative, blob_sha256=blob.sha256, size=len(payload), executable=False,
        ),),
        ignored_roots=MANDATORY_IGNORED_ROOTS,
        provenance=_prov(origin, source_revision, created_at, blob.sha256, trace=trace_id),
    )
    ref = store.put_bytes(manifest.to_json().encode("ascii"))
    return StoredSourceTree(manifest=manifest, ref=ref)


def _verify_frozen_evaluator_output(
    result: Any,
    candidate: StoredSourceTree,
    *,
    relative: str,
    expected_sha256: str,
) -> dict[str, Any]:
    """Bind the evaluator verdict to the exact candidate blob it observed."""

    entries = tuple(candidate.manifest.entries)
    if len(entries) != 1 or entries[0].path != relative:
        raise AriadneCampaignError(
            "candidate tree is not the frozen one-file evaluator subject"
        )
    try:
        value = json.loads(result.output)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise AriadneCampaignError("frozen evaluator output is invalid") from exc
    if (
        not isinstance(value, dict)
        or set(value) != {"expected_sha256", "observed_sha256", "passed"}
        or canonical_json(value) + "\n" != result.output
        or type(value.get("passed")) is not bool
        or value.get("expected_sha256") != expected_sha256
        or value.get("observed_sha256") != entries[0].blob_sha256
        or value.get("passed")
        != (value.get("observed_sha256") == expected_sha256)
        or bool(result.passed) != value.get("passed")
        or result.returncode != (0 if value.get("passed") else 1)
    ):
        raise AriadneCampaignError(
            "frozen evaluator output does not bind the candidate CAS blob"
        )
    return value


def _bounded_failure(exc: BaseException) -> tuple[str, str]:
    """Return bounded, reproducible failure text suitable for retained evidence."""

    error_type = type(exc).__name__[:200] or "Exception"
    message = str(exc)
    if len(message) > 2000:
        message = message[:1997] + "..."
    return error_type, message or error_type


def _inner_effect_binding(
    granted: Any,
    execution: Any,
    attempt: AttemptContract,
    *,
    expected_terminal_state: str,
) -> dict[str, str]:
    """Freeze and verify one attempt lease identity before its terminal commit."""

    if expected_terminal_state not in {"completed", "failed"}:
        raise AriadneCampaignError("inner effect expected terminal state is invalid")
    subject_digest = granted.evidence_records.get("lease_subject")
    execution_digest = granted.evidence_records.get(
        f"lease_execution:{execution.execution_id}"
    )
    digests = {
        "operation_sha256": attempt.digest,
        "lease_sha256": granted.lease.digest,
        "lease_subject_record_sha256": subject_digest,
        "lease_execution_record_sha256": execution_digest,
    }
    if any(
        not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
        for value in digests.values()
    ):
        raise AriadneCampaignError(
            "inner attempt effect evidence was not retained before commit"
        )
    try:
        chain = require_retained_effect_lease_start_records(
            granted.evidence_root,
            subject_record_sha256=subject_digest,
            execution_record_sha256=execution_digest,
            entrypoint_id=ATTEMPT_ENTRYPOINT_ID,
            source_revision=attempt.base_revision,
            attempt_id=attempt.attempt_id,
            operation_sha256=attempt.digest,
            expected_lease_sha256=granted.lease.digest,
            expected_execution_id=execution.execution_id,
            expected_execution_request_sha256=execution.digest,
        )
    except (EffectLeaseError, OSError, TypeError, ValueError) as exc:
        raise AriadneCampaignError(
            "inner attempt effect evidence is unavailable or invalid before commit"
        ) from exc
    request = chain["subject_record"].get("request")
    execution_payload = chain.get("execution")
    if (
        not isinstance(request, dict)
        or request.get("mission_id") != attempt.mission_id
        or not isinstance(execution_payload, dict)
        or tuple(execution_payload.get("writable_paths", ()))
        != tuple(attempt.writable_paths)
        or tuple(execution_payload.get("tools", ())) != ("python",)
    ):
        raise AriadneCampaignError(
            "inner attempt effect evidence differs from its AttemptContract"
        )
    return {
        "schema": _INNER_EFFECT_BINDING_SCHEMA,
        "campaign_id": str(attempt.campaign_id),
        "source_revision": attempt.base_revision,
        "attempt_id": attempt.attempt_id,
        "entrypoint_id": ATTEMPT_ENTRYPOINT_ID,
        **digests,
        "execution_id": execution.execution_id,
        "execution_request_sha256": execution.digest,
        "expected_terminal_state": expected_terminal_state,
    }


def _store_attempt_report(
    store: SourceTreeStore,
    *,
    packet_ref: ArtifactRef,
    observation_ref: ArtifactRef,
    inner_effect: dict[str, str],
) -> ArtifactRef:
    report = {
        "schema": _ATTEMPT_REPORT_SCHEMA,
        "evidence": packet_ref.to_dict(),
        "observation": observation_ref.to_dict(),
        "inner_effect": inner_effect,
    }
    return store.put_bytes(canonical_json(report).encode("ascii"))


def _require_bound_inner_terminal(
    evidence_root: Path,
    binding: dict[str, Any],
    attempt: AttemptContract,
    attempt_receipt: AttemptTerminalReceipt,
) -> None:
    """Verify a report-bound inner subject -> execution -> terminal chain."""

    expected_state = (
        "completed" if attempt_receipt.outcome == "succeeded" else "failed"
    )
    expected_keys = {
        "schema",
        "campaign_id",
        "source_revision",
        "attempt_id",
        "entrypoint_id",
        "operation_sha256",
        "lease_sha256",
        "lease_subject_record_sha256",
        "lease_execution_record_sha256",
        "execution_id",
        "execution_request_sha256",
        "expected_terminal_state",
    }
    if (
        set(binding) != expected_keys
        or binding.get("schema") != _INNER_EFFECT_BINDING_SCHEMA
        or binding.get("campaign_id") != attempt.mission_id
        or binding.get("campaign_id") != attempt.campaign_id
        or binding.get("source_revision") != attempt.base_revision
        or binding.get("attempt_id") != attempt.attempt_id
        or binding.get("entrypoint_id") != ATTEMPT_ENTRYPOINT_ID
        or binding.get("operation_sha256") != attempt.digest
        or binding.get("expected_terminal_state") != expected_state
    ):
        raise AriadneCampaignError(
            "inner attempt effect binding differs from its terminal Attempt receipt"
        )
    try:
        terminal = require_retained_effect_lease_terminal_record(
            evidence_root,
            subject_record_sha256=str(binding["lease_subject_record_sha256"]),
            execution_record_sha256=str(binding["lease_execution_record_sha256"]),
            entrypoint_id=ATTEMPT_ENTRYPOINT_ID,
            source_revision=attempt.base_revision,
            attempt_id=attempt.attempt_id,
            operation_sha256=attempt.digest,
            expected_lease_sha256=str(binding["lease_sha256"]),
            expected_execution_id=str(binding["execution_id"]),
            expected_execution_request_sha256=str(
                binding["execution_request_sha256"]
            ),
            expected_terminal_state=expected_state,
            expected_output_digests=(attempt_receipt.digest,),
        )
    except (EffectLeaseError, OSError, TypeError, ValueError) as exc:
        raise AriadneCampaignError(
            f"inner attempt effect needs reconciliation: {exc}"
        ) from exc
    if (
        terminal.get("lease_sha256") != binding["lease_sha256"]
        or terminal.get("execution_id") != binding["execution_id"]
        or terminal.get("execution_request_sha256")
        != binding["execution_request_sha256"]
    ):
        raise AriadneCampaignError(
            "inner attempt effect needs reconciliation: terminal binding is invalid"
        )


def _frozen_evaluator_of(store: SourceTreeStore, receipt: CampaignReceipt) -> str | None:
    """The evaluator digest the ExperimentSpec froze, read from the spec itself.

    The replay compared the observation's two evaluator fields against ONE value
    taken from the evidence item, which made the comparison unable to fail
    (Odysseus round 1, F1). The spec is a different artifact, so reading it is
    what turns the comparison into a check.
    """

    try:
        # The receipt's `experiment_spec_sha256` is the CONTRACT digest; the
        # blob is addressed by its locator.
        raw = store.read_bytes(receipt.experiment_spec_locator, max_bytes=MAX_CAMPAIGN_FILE_BYTES)
    except Exception:  # noqa: BLE001 - a replay reads what it can; absence refuses below
        return None
    try:
        payload = json.loads(raw.decode("ascii"))
    except (ValueError, UnicodeDecodeError):
        return None
    frozen = payload.get("frozen_components")
    if isinstance(frozen, dict) and isinstance(frozen.get("evaluator"), str):
        return frozen["evaluator"]
    # A spec this replay cannot read is a refusal, not a pass: returning the
    # observation's own value would restore the tautology this exists to break.
    return None


def _require_campaign_inner_effect_terminals(
    store: SourceTreeStore,
    evidence_root: Path,
    receipt: CampaignReceipt,
) -> None:
    """Replay every controlled-repair Attempt and its exact inner lease chain."""

    # Read from the ExperimentSpec, a different artifact than the evidence item:
    # comparing the observation's two evaluator fields against one value made
    # the check unable to fail (Odysseus round 1).
    spec_frozen_evaluator = _frozen_evaluator_of(store, receipt)
    for trial in receipt.trials:
        if trial.receipt_profile != "controlled-repair-v1":
            continue
        if (
            len(trial.attempt_ids) != 1
            or len(trial.attempt_contract_locators) != 1
            or len(trial.attempt_receipt_locators) != 1
        ):
            raise AriadneCampaignError(
                "controlled-repair trial does not retain exactly one Attempt chain"
            )
        try:
            attempt = load_attempt_contract(
                store, trial.attempt_contract_locators[0]
            )
            loaded_receipt = load_attempt_receipt(
                store, trial.attempt_receipt_locators[0]
            )
            if not isinstance(loaded_receipt, AttemptTerminalReceipt):
                raise AriadneCampaignError(
                    "controlled-repair trial uses the wrong Attempt receipt profile"
                )
            packet = load_evidence_packet(store, trial.evidence_packet_locator)
            payload = store.read_bytes(
                loaded_receipt.report, max_bytes=_MAX_ATTEMPT_REPORT_BYTES
            )
            report = json.loads(payload.decode("ascii"))
        except AriadneCampaignError:
            raise
        except (
            CampaignLifecycleError,
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            SourceTreeStoreError,
            TypeError,
            ValueError,
        ) as exc:
            raise AriadneCampaignError(
                "controlled-repair Attempt report is unavailable or invalid"
            ) from exc
        if (
            not isinstance(report, dict)
            or set(report) != {"schema", "evidence", "observation", "inner_effect"}
            or report.get("schema") != _ATTEMPT_REPORT_SCHEMA
            or canonical_json(report).encode("ascii") != payload
        ):
            raise AriadneCampaignError(
                "controlled-repair Attempt report is noncanonical or malformed"
            )
        try:
            evidence_ref = ArtifactRef(**report["evidence"])
            observation_ref = ArtifactRef(**report["observation"])
            observation_payload = store.read_bytes(
                observation_ref, max_bytes=_MAX_ATTEMPT_REPORT_BYTES
            )
            observation = json.loads(observation_payload.decode("ascii"))
        except (
            UnicodeError,
            json.JSONDecodeError,
            SourceTreeStoreError,
            TypeError,
            ValueError,
        ) as exc:
            raise AriadneCampaignError(
                "controlled-repair Attempt observation is unavailable or invalid"
            ) from exc
        if (
            evidence_ref.sha256 != packet.digest
            or evidence_ref.locator != trial.evidence_packet_locator
            or packet.digest != trial.evidence_packet_sha256
            or len(packet.items) != 1
            or packet.items[0].output_sha256 != observation_ref.sha256
            or packet.items[0].evidence_locator != observation_ref.locator
        ):
            raise AriadneCampaignError(
                "controlled-repair Attempt report does not bind its EvidencePacket"
            )
        if (
            not isinstance(observation, dict)
            or canonical_json(observation).encode("ascii") != observation_payload
        ):
            raise AriadneCampaignError(
                "controlled-repair Attempt observation is noncanonical"
            )
        if observation.get("schema") == _EVALUATOR_ERROR_SCHEMA:
            if (
                set(observation)
                != {
                    "schema",
                    "campaign_id",
                    "attempt_id",
                    "variant_id",
                    "seed",
                    "candidate_tree_sha256",
                    "attempt_contract_sha256",
                    "evaluator_sha256",
                    "error_type",
                    "error",
                }
                or observation.get("campaign_id") != receipt.campaign_id
                or observation.get("attempt_id") != attempt.attempt_id
                or observation.get("variant_id") != trial.variant_id
                or observation.get("seed") != trial.seed
                or observation.get("candidate_tree_sha256")
                != trial.candidate_tree_sha256
                or observation.get("attempt_contract_sha256") != attempt.digest
                # `spec_frozen_evaluator` is None when the spec cannot be read,
                # and `None in (..., None)` would have passed anything carrying
                # a null digest (Cerberus round 3, medium 1).
                or observation.get("evaluator_sha256") not in (
                    (EVALUATOR_SHA256,) if spec_frozen_evaluator is None
                    else (EVALUATOR_SHA256, spec_frozen_evaluator))
                or not isinstance(observation.get("error_type"), str)
                or not observation.get("error_type")
                or not isinstance(observation.get("error"), str)
                or not observation.get("error")
                or packet.evaluation_status != "failed"
                or packet.items[0].verdict != "error"
            ):
                raise AriadneCampaignError(
                    "controlled-repair error observation is not bound to its trial"
                )
        elif observation.get("schema") == TEST_EVALUATOR_OBSERVATION_SCHEMA:
            output = observation.get("output")
            passed = observation.get("passed")
            interpreter = observation.get("interpreter")
            details = dict(packet.items[0].details) if packet.items else {}
            # The digest is cross-checked against the evidence item the
            # orchestrator wrote, so a receipt cannot name its own judge.
            declared = details.get("evaluator_sha256")
            checks = (
                ("keys", set(observation) == set(_TEST_OBSERVATION_KEYS)),
                ("variant", observation.get("variant_id") == trial.variant_id),
                ("seed", observation.get("seed") == trial.seed),
                ("declared evaluator", isinstance(declared, str)),
                ("evaluator digest", observation.get("evaluator_sha256") == declared),
                # NOT the same source as `declared`: comparing both fields to
                # one value made this check unable to fail (Odysseus round 1).
                ("command digest", observation.get("command_sha256")
                 == spec_frozen_evaluator),
                ("candidate tree",
                 observation.get("candidate_tree_sha256") == trial.candidate_tree_sha256),
                ("passed flag", type(passed) is bool),
                ("timed_out flag", type(observation.get("timed_out")) is bool),
                ("returncode", isinstance(observation.get("returncode"), int)
                 and not isinstance(observation.get("returncode"), bool)),
                ("passing returncode", (observation.get("returncode") == 0) is bool(passed)),
                ("counts are not negative", all(
                    isinstance(value, int) and value >= 0
                    for value in (observation.get("workspace_files"),
                                  observation.get("workspace_bytes")))),
                ("output text", isinstance(output, str)),
                ("output withheld", output == ""),
                ("output digest", isinstance(observation.get("output_sha256"), str)
                 and len(observation.get("output_sha256", "")) == 64),
                ("report counts", isinstance(observation.get("report"), dict)),
                ("interpreter provenance", isinstance(interpreter, dict)
                 and set(interpreter) == _INTERPRETER_PROVENANCE_KEYS
                 and all(type(interpreter[key]) is str for key in interpreter)
                 and len(interpreter["binary_sha256"]) == 64),
                ("stated reach", observation.get("child_environment") == "inherited-except-denylist"
                 and observation.get("child_network") == "unrestricted"
                 and observation.get("verdict_is_self_reported") is True),
                ("workspace files", isinstance(observation.get("workspace_files"), int)),
                ("workspace bytes", isinstance(observation.get("workspace_bytes"), int)),
                ("verdict", packet.items[0].verdict == ("passed" if passed else "failed")),
            )
            missing = [label for label, ok in checks if not ok]
            if missing:
                raise AriadneCampaignError(
                    "controlled-repair test observation is not bound to its trial: "
                    + ", ".join(missing)
                )
        elif observation.get("schema") in _EVALUATOR_OBSERVATION_SCHEMAS:
            output = observation.get("output")
            passed = observation.get("passed")
            interpreter = observation.get("interpreter")
            expected_keys = set(_EVALUATOR_OBSERVATION_KEYS)
            if observation.get("schema") == _EVALUATOR_OBSERVATION_SCHEMAS[-1]:
                expected_keys.add("interpreter")
                interpreter_bound = (
                    isinstance(interpreter, dict)
                    and set(interpreter) == _INTERPRETER_PROVENANCE_KEYS
                    and all(type(interpreter[key]) is str for key in interpreter)
                    and len(interpreter["binary_sha256"]) == 64
                )
            else:
                interpreter_bound = interpreter is None
            if (
                set(observation) != expected_keys
                or not interpreter_bound
                or observation.get("variant_id") != trial.variant_id
                or observation.get("seed") != trial.seed
                or observation.get("evaluator_sha256") != EVALUATOR_SHA256
                or observation.get("candidate_tree_sha256")
                != trial.candidate_tree_sha256
                or type(passed) is not bool
                or observation.get("returncode") != (0 if passed else 1)
                or not isinstance(output, str)
                or observation.get("output_sha256")
                != hashlib.sha256(output.encode("utf-8")).hexdigest()
                or packet.items[0].verdict != ("passed" if passed else "failed")
            ):
                raise AriadneCampaignError(
                    "controlled-repair evaluator observation is not bound to its trial"
                )
        else:
            raise AriadneCampaignError(
                "controlled-repair Attempt observation schema is not recognized"
            )
        binding = report.get("inner_effect")
        if not isinstance(binding, dict):
            raise AriadneCampaignError(
                "controlled-repair Attempt report lacks a typed inner effect binding"
            )
        _require_bound_inner_terminal(
            evidence_root, binding, attempt, loaded_receipt
        )


def _judge_labels(evaluator: "TestCommandEvaluator | None") -> tuple[str, str]:
    """The evaluator digest and the metric name for THIS campaign's judge.

    The failure and fault paths hardcoded the exact-match evaluator, so a failed
    test-evaluator receipt named a judge that never ran (Cerberus round 1,
    medium 2), and the failure path is where honesty matters most.
    """

    if evaluator is None:
        return EVALUATOR_SHA256, "exact_match"
    return evaluator.digest, "tests_pass"


def _faulted_attempt_trial(
    *,
    evaluator: "TestCommandEvaluator | None" = None,
    store: SourceTreeStore,
    ledger: AttemptLedger,
    attempt_begin: Any,
    attempt: AttemptContract,
    attempt_ref: ArtifactRef,
    inner: Any,
    inner_execution: Any,
    inner_start: Any,
    candidate: StoredSourceTree,
    base: StoredSourceTree,
    campaign_id: str,
    source_revision: str,
    variant: str,
    role: str,
    seed: int,
    budget_sha256: str,
    started_at: str,
    usage: ResourceUsage,
    failure: BaseException,
    evidence_root: Path,
) -> tuple[CampaignTrialReceipt, str | None]:
    """Retain a post-capture failure as a faulted, candidate-bound Attempt."""

    error_type, error_message = _bounded_failure(failure)
    finished_at = _now()
    observation = {
        "schema": _EVALUATOR_ERROR_SCHEMA,
        "campaign_id": campaign_id,
        "attempt_id": attempt.attempt_id,
        "variant_id": variant,
        "seed": seed,
        "candidate_tree_sha256": candidate.ref.sha256,
        "attempt_contract_sha256": attempt.digest,
        # The judge that actually ran. Naming the exact-match evaluator on a
        # failed test-evaluator receipt is a lie told exactly where honesty
        # matters most (Cerberus round 1, medium 2).
        "evaluator_sha256": _judge_labels(evaluator)[0],
        "error_type": error_type,
        "error": error_message,
    }
    observation_ref = store.put_bytes(canonical_json(observation).encode("ascii"))
    item_provenance = _prov(
        "ariadne.frozen-evaluator",
        source_revision,
        finished_at,
        observation_ref.sha256,
        trace=campaign_id,
    )
    item = EvidenceItem(
        evidence_id=f"evidence-{attempt.attempt_id}",
        evaluator="ariadne-frozen-evaluator",
        assurance="independent",
        verdict="error",
        output_sha256=observation_ref.sha256,
        evidence_locator=observation_ref.locator,
        collected_at=finished_at,
        provenance=item_provenance,
        details={
            "configured_budget_sha256": budget_sha256,
            "error_type": error_type,
            "phase": "post-candidate-capture",
        },
    )
    packet = EvidencePacket(
        packet_id=f"packet-{attempt.attempt_id}",
        mission_id=campaign_id,
        attempt_id=attempt.attempt_id,
        source_revision=source_revision,
        attempt_contract_sha256=attempt.digest,
        subject_sha256=candidate.ref.sha256,
        evaluation_status="failed",
        items=(item,),
        policy_decision_sha256=attempt.policy_decision_sha256,
        usage=usage,
        candidate_artifact_sha256=candidate.ref.sha256,
        candidate_artifact_locator=candidate.ref.locator,
        provenance=_prov(
            "ariadne.controlled-repair.error-evidence",
            source_revision,
            finished_at,
            attempt.digest,
            candidate.ref.sha256,
            attempt.policy_decision_sha256,
            observation_ref.sha256,
            trace=campaign_id,
        ),
    )
    packet_ref = store_contract(store, packet)
    binding = _inner_effect_binding(
        inner,
        inner_execution,
        attempt,
        expected_terminal_state="failed",
    )
    report_ref = _store_attempt_report(
        store,
        packet_ref=packet_ref,
        observation_ref=observation_ref,
        inner_effect=binding,
    )
    completion = ledger.complete(
        attempt_begin.start,
        receipt_id=f"terminal-{attempt.attempt_id}",
        outcome="faulted",
        report=report_ref,
        candidate_tree=candidate,
    )
    receipt_ref = store_contract(store, completion.receipt)
    terminal_error: str | None = None
    try:
        inner.authorization.finish_effect(
            inner_start.receipt,
            outcome="FAILED",
            output_digests=(receipt_ref.sha256,),
        )
        terminal_record = inner.retain_terminal_record(inner_execution)
        if terminal_record is None:
            raise AriadneCampaignError(
                "inner attempt effect terminal evidence was not retained"
            )
        _require_bound_inner_terminal(
            evidence_root, binding, attempt, completion.receipt
        )
    except BaseException as exc:
        terminal_type, terminal_message = _bounded_failure(exc)
        terminal_error = f"{terminal_type}: {terminal_message}"[:1000]
    blocker = f"{error_type}: {error_message}"[:1000]
    trial = CampaignTrialReceipt(
        campaign_id=campaign_id,
        seed=seed,
        replay_role="origin",
        stage="complete",
        status="error",
        base_source_tree_sha256=base.ref.sha256,
        base_source_tree_locator=base.ref.locator,
        mission_sha256=None,
        mission_locator=None,
        attempt_ids=(attempt.attempt_id,),
        attempt_contract_sha256s=(attempt.digest,),
        attempt_contract_locators=(attempt_ref.locator,),
        attempt_receipt_sha256s=(completion.receipt.digest,),
        attempt_receipt_locators=(receipt_ref.locator,),
        gate1_receipt_sha256=None,
        gate1_receipt_locator=None,
        candidate_tree_sha256=candidate.ref.sha256,
        candidate_tree_locator=candidate.ref.locator,
        candidate_source_bundle_sha256=None,
        candidate_snapshot_sha256=None,
        candidate_snapshot_locator=None,
        graph_delta_sha256=None,
        evidence_packet_sha256=packet.digest,
        evidence_packet_locator=packet_ref.locator,
        metrics={_judge_labels(evaluator)[1]: 0},
        usage=usage,
        negative_outcomes=("post-capture-error",),
        blockers=(blocker,),
        started_at=started_at,
        finished_at=finished_at,
        variant_id=variant,
        arm_role=role,
        configured_budget_sha256=budget_sha256,
        receipt_profile="controlled-repair-v1",
    )
    return trial, terminal_error


def _complete_failed_campaign_receipt(
    *,
    evaluator: "TestCommandEvaluator | None" = None,
    store: SourceTreeStore,
    ledger: AttemptLedger,
    campaign_begin: Any,
    contract: Any,
    contract_ref: ArtifactRef,
    spec: ExperimentSpec,
    spec_ref: ArtifactRef,
    granted: Any,
    execution: Any,
    trials: list[CampaignTrialReceipt],
    campaign_id: str,
    source_revision: str,
    operation_sha256: str,
    started_at: str,
    blocker: str,
    reproducibility_note: str,
    base_binding_sha256: str,
    additional_negative_outcomes: tuple[str, ...] = (),
) -> tuple[CampaignReceipt, ArtifactRef]:
    """Commit an addressable failed CampaignReceipt instead of STATE_FAILED."""

    outer_binding = _outer_effect_binding(
        granted,
        execution,
        campaign_id=campaign_id,
        source_revision=source_revision,
        operation_sha256=operation_sha256,
    )
    outer_binding_ref = store.put_bytes(canonical_json(outer_binding).encode("ascii"))
    finished_at = _now()
    receipt_inputs = {
        contract.digest,
        spec.digest,
        outer_binding_ref.sha256,
        base_binding_sha256,
        *(
            digest
            for trial in trials
            for digest in (
                trial.base_source_tree_sha256,
                *trial.attempt_contract_sha256s,
                *trial.attempt_receipt_sha256s,
                trial.candidate_tree_sha256,
                trial.evidence_packet_sha256,
            )
            if digest is not None
        ),
    }
    negative_outcomes = {
        f"{trial.variant_id}:{outcome}"
        for trial in trials
        for outcome in trial.negative_outcomes
    }
    negative_outcomes.update(additional_negative_outcomes)
    receipt = CampaignReceipt(
        campaign_id=campaign_id,
        source_revision=source_revision,
        campaign_contract_sha256=contract.digest,
        campaign_contract_locator=contract_ref.locator,
        experiment_spec_sha256=spec.digest,
        experiment_spec_locator=spec_ref.locator,
        metric_names=(_judge_labels(evaluator)[1],),
        trials=tuple(trials),
        execution_order=tuple(trial.seed for trial in trials),
        outcome="failed",
        selected_seed=None,
        candidate_tree_sha256=None,
        candidate_tree_locator=None,
        nomination_receipt_sha256=None,
        nomination_receipt_locator=None,
        usage=ResourceUsage(
            input_tokens=sum(trial.usage.input_tokens for trial in trials),
            output_tokens=sum(trial.usage.output_tokens for trial in trials),
            cost_microusd=sum(trial.usage.cost_microusd for trial in trials),
            wall_time_ms=sum(trial.usage.wall_time_ms for trial in trials),
            est_input_tokens=sum(
                trial.usage.est_input_tokens for trial in trials
            ),
        ),
        overhead_usage=ResourceUsage(),
        negative_outcomes=tuple(sorted(negative_outcomes)),
        reproducibility_note=reproducibility_note,
        blockers=(blocker[:1000],),
        started_at=started_at,
        finished_at=finished_at,
        provenance=_prov(
            "ariadne.controlled-repair.receipt",
            source_revision,
            finished_at,
            *receipt_inputs,
            trace=campaign_id,
        ),
        selection_mode="best-passed-trial",
        selected_variant_id=None,
        budget_equality=None,
    )
    receipt_ref = complete_campaign(ledger.spine, store, campaign_begin, receipt)
    return receipt, receipt_ref


def _settle_committed_outer_effect(
    granted: Any,
    effect_start: Any,
    execution: Any,
    receipt_sha256: str,
) -> bool:
    """Reconcile a post-commit outer effect as COMPLETED, never FAILED.

    Campaign completion in the canonical spine is the scientific commit.  A
    transient terminal-ledger/evidence error after it cannot roll that fact
    back.  Retry the idempotent completion once, retain what can be retained,
    and report whether both terminal state and retained evidence are durable.
    """
    terminalized = False
    for _attempt in range(2):
        try:
            granted.authorization.finish_effect(
                effect_start.receipt,
                outcome="COMPLETED",
                output_digests=(receipt_sha256,),
            )
            terminalized = True
            break
        except BaseException:
            continue
    retained = False
    try:
        retained = granted.retain_terminal_record(execution) is not None
    except BaseException:
        pass
    return terminalized and retained


def _outer_effect_binding(
    granted: Any,
    execution: Any,
    *,
    campaign_id: str,
    source_revision: str,
    operation_sha256: str,
) -> dict[str, str]:
    subject_digest = granted.evidence_records.get("lease_subject")
    execution_digest = granted.evidence_records.get(
        f"lease_execution:{execution.execution_id}"
    )
    digests = {
        "operation_sha256": operation_sha256,
        "lease_sha256": granted.lease.digest,
        "lease_subject_record_sha256": subject_digest,
        "lease_execution_record_sha256": execution_digest,
    }
    if any(
        not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None
        for value in digests.values()
    ):
        raise AriadneCampaignError(
            "outer campaign effect evidence was not retained before commit"
        )
    try:
        require_retained_effect_lease_start_records(
            granted.evidence_root,
            subject_record_sha256=subject_digest,
            execution_record_sha256=execution_digest,
            entrypoint_id=ENTRYPOINT_ID,
            source_revision=source_revision,
            attempt_id=f"{campaign_id}-campaign",
            operation_sha256=operation_sha256,
            expected_lease_sha256=granted.lease.digest,
            expected_execution_id=execution.execution_id,
            expected_execution_request_sha256=execution.digest,
        )
    except (EffectLeaseError, OSError, TypeError, ValueError) as exc:
        raise AriadneCampaignError(
            "outer campaign effect evidence is unavailable or invalid before commit"
        ) from exc
    return {
        "schema": _OUTER_EFFECT_BINDING_SCHEMA,
        "campaign_id": campaign_id,
        "source_revision": source_revision,
        "attempt_id": f"{campaign_id}-campaign",
        "entrypoint_id": ENTRYPOINT_ID,
        **digests,
        "execution_id": execution.execution_id,
        "execution_request_sha256": execution.digest,
        "expected_terminal_state": "completed",
    }


def _require_campaign_outer_effect_terminal(
    store: SourceTreeStore,
    evidence_root: Path,
    receipt: CampaignReceipt,
    *,
    operation_sha256: str,
) -> None:
    """Keep post-commit outer-effect debt visible on every campaign replay."""

    inputs = tuple(receipt.provenance.input_digests)
    if len(inputs) > _MAX_RECEIPT_PROVENANCE_INPUTS:
        raise AriadneCampaignError(
            "campaign outer effect needs reconciliation: provenance input bound exceeded"
        )
    matches: list[dict[str, Any]] = []
    for digest in inputs:
        try:
            payload = store.read_bytes(
                ArtifactRef.from_sha256(digest),
                max_bytes=_MAX_OUTER_EFFECT_BINDING_BYTES,
            )
            value = json.loads(payload.decode("ascii"))
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            SourceTreeStoreError,
            TypeError,
            ValueError,
        ):
            continue
        if (
            isinstance(value, dict)
            and value.get("schema") == _OUTER_EFFECT_BINDING_SCHEMA
        ):
            if canonical_json(value).encode("ascii") != payload:
                raise AriadneCampaignError(
                    "campaign outer effect needs reconciliation: binding is noncanonical"
                )
            matches.append(value)
    if len(matches) != 1:
        raise AriadneCampaignError(
            "campaign outer effect needs reconciliation: binding is missing or ambiguous"
        )
    binding = matches[0]
    expected_keys = {
        "schema",
        "campaign_id",
        "source_revision",
        "attempt_id",
        "entrypoint_id",
        "operation_sha256",
        "lease_sha256",
        "lease_subject_record_sha256",
        "lease_execution_record_sha256",
        "execution_id",
        "execution_request_sha256",
        "expected_terminal_state",
    }
    if (
        set(binding) != expected_keys
        or binding.get("campaign_id") != receipt.campaign_id
        or binding.get("source_revision") != receipt.source_revision
        or binding.get("attempt_id") != f"{receipt.campaign_id}-campaign"
        or binding.get("entrypoint_id") != ENTRYPOINT_ID
        or binding.get("operation_sha256") != operation_sha256
        or binding.get("expected_terminal_state") != "completed"
    ):
        raise AriadneCampaignError(
            "campaign outer effect needs reconciliation: binding is invalid"
        )
    try:
        terminal = require_retained_effect_lease_terminal_record(
            evidence_root,
            subject_record_sha256=str(binding["lease_subject_record_sha256"]),
            execution_record_sha256=str(binding["lease_execution_record_sha256"]),
            entrypoint_id=ENTRYPOINT_ID,
            source_revision=receipt.source_revision,
            attempt_id=f"{receipt.campaign_id}-campaign",
            operation_sha256=operation_sha256,
            expected_lease_sha256=str(binding["lease_sha256"]),
            expected_execution_id=str(binding["execution_id"]),
            expected_execution_request_sha256=str(
                binding["execution_request_sha256"]
            ),
            expected_terminal_state="completed",
            expected_output_digests=(receipt.digest,),
        )
        if (
            terminal.get("lease_sha256") != binding["lease_sha256"]
            or terminal.get("execution_id") != binding["execution_id"]
            or terminal.get("execution_request_sha256")
            != binding["execution_request_sha256"]
        ):
            raise AriadneCampaignError(
                "campaign outer effect needs reconciliation: binding is invalid"
            )
    except (EffectLeaseError, OSError, TypeError, ValueError) as exc:
        raise AriadneCampaignError(
            f"campaign outer effect needs reconciliation: {exc}"
        ) from exc


def run_campaign(
    *,
    repo_root: str | os.PathLike[str],
    source_revision: str,
    campaign_id: str,
    target_path: str,
    before: str,
    after: str,
    timeout_s: int = 30,
    evaluator: TestCommandEvaluator | None = None,
) -> dict[str, Any]:
    """Run baseline, negative control, and repair once under equal budgets.

    ``evaluator`` selects the verdict source. The default is the frozen
    exact-match evaluator, which proves an edit landed and nothing more. A
    :class:`TestCommandEvaluator` instead runs the caller's frozen test command
    against the pinned revision with one file replaced, and then the arms mean
    something different: the baseline must PASS (otherwise the suite was already
    red and nothing can be attributed) and the negative control must FAIL
    (otherwise the suite cannot see this file at all).
    """
    campaign_id = _campaign_id(campaign_id)
    evaluator = None if evaluator is None else _admit_test_evaluator(evaluator)
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, int) or timeout_s <= 0:
        raise AriadneCampaignError("timeout_s must be a positive integer")
    before, before_bytes = _repair_fragment(
        before, label="before", allow_empty=False
    )
    after, after_bytes = _repair_fragment(
        after, label="after", allow_empty=True
    )
    if before == after:
        raise AriadneCampaignError("repair must replace before with a different value")
    _admit_target_path(target_path)  # pure refusals first: no repository observed yet
    if evaluator is not None:
        _refuse_target_inside_test_roots(target_path, evaluator.test_roots)
    if len(source_revision) != 40 or any(c not in "0123456789abcdef" for c in source_revision):
        raise AriadneCampaignError("source_revision must be the exact lowercase 40-hex Git HEAD")
    try:
        root = Path(repo_root).resolve(strict=True)
    except OSError as exc:
        raise AriadneRequestError(f"repo_root is unavailable or unsafe: {exc}") from exc
    # HEAD is observed BEFORE and AFTER the target read (G1-ARIADNE-05): a
    # commit or checkout between the two would bind bytes of revision X to a
    # receipt labelled Y, and nothing else here would notice.
    head_receipt = _verify_head(root, source_revision)
    relative, target_snapshot = _safe_target(root, target_path)
    if _verify_head(root, source_revision).to_dict() != head_receipt.to_dict():
        raise AriadneConflictError(
            "source_revision conflict: repository HEAD changed while the target was read"
        )
    head_receipt_sha = canonical_sha(head_receipt.to_dict())
    try:
        original = target_snapshot.source.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise AriadneCampaignError("target must be strict UTF-8") from exc
    if original.count(before) != 1:
        raise AriadneCampaignError("before text must occur exactly once in the frozen target")
    original_bytes = target_snapshot.source
    expected = original.replace(before, after, 1).encode("utf-8", errors="strict")
    negative_replacement = before + _NEGATIVE_CONTROL_SUFFIX
    if negative_replacement == after:
        # Keep the control deterministically distinct even when the requested
        # repair happens to equal the standard mutant.  One extra suffix is
        # sufficient because one string cannot equal both lengths.
        negative_replacement += _NEGATIVE_CONTROL_SUFFIX
    negative_control = original.replace(
        before, negative_replacement, 1
    ).encode("utf-8", errors="strict")
    if negative_control == expected:
        raise AriadneCampaignError("negative control must differ from the requested repair")
    if len(expected) > MAX_CAMPAIGN_FILE_BYTES:
        raise AriadneCampaignError(
            f"repair output exceeds the {MAX_CAMPAIGN_FILE_BYTES}-byte campaign file ceiling"
        )
    if len(negative_control) > MAX_CAMPAIGN_FILE_BYTES:
        raise AriadneCampaignError(
            "negative-control output exceeds the "
            f"{MAX_CAMPAIGN_FILE_BYTES}-byte campaign file ceiling"
        )
    expected_sha = hashlib.sha256(expected).hexdigest()
    operation_sha = canonical_sha({
        "schema": "daedalus-ariadne-controlled-repair/2",
        "campaign_id": campaign_id,
        "source_revision": source_revision,
        "target_path": relative,
        "base_file_sha256": target_snapshot.source_sha256,
        "before_sha256": hashlib.sha256(before_bytes).hexdigest(),
        "after_sha256": hashlib.sha256(after_bytes).hexdigest(),
        "expected_sha256": expected_sha,
        "negative_control_sha256": hashlib.sha256(negative_control).hexdigest(),
        # The judge is part of the campaign's identity: without this, a replay
        # of the same id and edit returned a receipt written under a DIFFERENT
        # evaluator, and the permissive one's nomination answered the strict
        # one's request (Cerberus round 1, high 1).
        "evaluator_sha256": EVALUATOR_SHA256 if evaluator is None else evaluator.digest,
        "timeout_s": timeout_s,
        "repair_fragment_max_bytes": MAX_REPAIR_FRAGMENT_BYTES,
        "campaign_file_max_bytes": MAX_CAMPAIGN_FILE_BYTES,
        "negative_control_suffix_sha256": hashlib.sha256(
            _NEGATIVE_CONTROL_SUFFIX.encode("ascii")
        ).hexdigest(),
    })
    state = control_root(root) / "ariadne"
    effect_evidence_root = state / "effect-evidence" / campaign_id
    workspace_parent = state / "workspaces"
    switch = KillSwitch(repo_root=root)
    spine_path, error = resolve_spine_db_path(root)
    if error or spine_path is None:
        raise AriadneCampaignError(f"canonical spine unavailable: {error}")
    granted = acquire_effect_lease(
        root,
        entrypoint_id=ENTRYPOINT_ID,
        source_revision=source_revision,
        mission_id=campaign_id,
        attempt_id=f"{campaign_id}-campaign",
        positions=1,
        writable_paths=(relative,),
        tools=("python",),
        max_spend_usd=None,
        # Three arms plus three workspace builds, under the timeout that
        # actually governs an arm. The outer value governed the lease while the
        # evaluator's governed the run, so an 11.4 s campaign completed under a
        # 3 s declared lease and nothing noticed (Odysseus round 1).
        timeout_s=_campaign_lease_timeout_s(timeout_s, evaluator),
        contained=True,
        containment_evidence="each arm is materialized from exact CAS below a checkout-external Attempt workspace",
        write_policy=Policy(write_allow=(relative,)),
        switch=switch,
        trace_id=campaign_id,
        evidence_root=effect_evidence_root,
        subject_root=root,
        worktree_root=workspace_parent,
        operation_sha256=operation_sha,
    )
    if isinstance(granted, WaveLeaseDenied):
        raise AriadneCampaignError("effect lease denied: " + "; ".join(granted.reasons))
    execution = granted.execution_for(
        0, writable_paths=(relative,), tools=("python",), operation_sha256=operation_sha
    )
    # Retention is part of this product boundary, not best-effort telemetry.
    # Refuse before begin_effect, the serial lock, CAS, SQLite, or workspaces
    # can mutate when the exact outer subject/execution chain is unavailable.
    _outer_effect_binding(
        granted,
        execution,
        campaign_id=campaign_id,
        source_revision=source_revision,
        operation_sha256=operation_sha,
    )
    effect_start = granted.authorization.begin_effect(execution)

    lock = ExclusiveFileLock(
        control_root(root) / "candidate-execution.lock", timeout_s=2.0,
        label="shared Genesis/Ariadne candidate execution lock",
    )
    lock_acquired = False
    store: SourceTreeStore | None = None
    ledger: AttemptLedger | None = None
    campaign_begin = None
    campaign_committed = False
    active_attempt_begin = None
    active_inner = None
    active_inner_execution = None
    active_inner_start = None
    try:
        try:
            lock.__enter__()
            lock_acquired = True
        except FileLockUnavailable as exc:
            raise AriadneCampaignError(
                "another Genesis/Ariadne candidate execution is active; retry"
            ) from exc
        # A mode=ro SpineLedger may create SQLite WAL/SHM companions. Replay
        # therefore comes only after the canonical lease/begin boundary and
        # while holding the shared serial slot. A caller that waited for an
        # identical campaign now sees its terminal WAL before creating CAS or
        # Attempt state. The Campaign spine, not an outer lease ID, owns replay.
        try:
            replay = lookup_campaign_read_only(
                str(spine_path), str(state / "source-cas"), campaign_id,
                expected_operation_sha256=operation_sha,
            )
        except CampaignIdentityConflict as exc:
            # Same id, changed frozen material: a conflict with a durable
            # campaign, the same class as a stale HEAD (HTTP 409). Corrupt or
            # malformed retained state below stays a campaign error (400).
            raise AriadneConflictError(str(exc)) from exc
        except CampaignLifecycleError as exc:
            raise AriadneCampaignError(str(exc)) from exc
        if replay is not None:
            replay_store = SourceTreeStore.open_existing(state / "source-cas")
            _require_campaign_inner_effect_terminals(
                replay_store,
                effect_evidence_root,
                replay.receipt,
            )
            _require_campaign_outer_effect_terminal(
                replay_store,
                effect_evidence_root,
                replay.receipt,
                operation_sha256=operation_sha,
            )
            if effect_start.execute:
                settled = _settle_committed_outer_effect(
                    granted, effect_start, execution, replay.receipt.digest
                )
                if not settled:
                    raise AriadneCampaignError(
                        "campaign replay is canonical but its invocation effect needs "
                        "ledger/evidence reconciliation"
                    )
            return replay.receipt.to_dict()
        if not effect_start.execute:
            raise AriadneCampaignError(
                "effect execution is already terminal or pending; inspect "
                "retained campaign state"
            )
        store = SourceTreeStore(state / "source-cas")
        workspace_parent.mkdir(parents=True, exist_ok=True)
        ledger = AttemptLedger(spine_path, store)
        evaluator_ref = store.put_bytes(EVALUATOR_SOURCE.encode("utf-8"))
        if evaluator_ref.sha256 != EVALUATOR_SHA256:
            raise AriadneCampaignError("frozen evaluator CAS identity changed")
        head_ref = store.put_bytes(canonical_json(head_receipt.to_dict()).encode("ascii"))
        if head_ref.sha256 != head_receipt_sha:
            raise AriadneCampaignError("verified HEAD receipt CAS identity changed")
        created = _now()
        base = _store_scoped_tree(
            store, payload=original_bytes, relative=relative,
            tree_id=f"{campaign_id}-base", source_revision=source_revision,
            origin="ariadne.controlled-repair.working-tree-base", created_at=created,
            trace_id=campaign_id,
        )
        base_binding_ref = store.put_bytes(canonical_json(_base_tree_binding(
            campaign_id=campaign_id, source_revision=source_revision,
            relative=relative, base_file_sha256=target_snapshot.source_sha256,
        )).encode("ascii"))
        evaluator_sha = EVALUATOR_SHA256 if evaluator is None else evaluator.digest
        evaluator_wall_s = timeout_s if evaluator is None else evaluator.timeout_s
        budget = ResourceBudget(max_wall_time_s=evaluator_wall_s, max_attempts=1)
        budget_sha = canonical_sha(asdict(budget))
        task_sha = operation_sha
        frozen = {
            "compiler": canonical_sha({"kind": "exact-text-replace-v1"}),
            "evaluator": evaluator_sha,
            "fixture": expected_sha,
            "generator": canonical_sha({"arms": ["no-change", "negative-control", "repair"]}),
            "model": canonical_sha({"kind": "none-deterministic"}),
            "operator": canonical_sha({"kind": "bounded-text-replace-v1"}),
            "head_revision": head_receipt_sha,
        }
        # The spec must not expire while its own arms are still legal to run.
        # The default path keeps the 15 minutes it always had; only a test
        # evaluator, whose arms are genuinely longer, extends it.
        expires = (
            datetime.now(timezone.utc)
            + timedelta(minutes=15)
            + (timedelta(0) if evaluator is None
               else timedelta(seconds=_campaign_lease_timeout_s(timeout_s, evaluator)))
        ).isoformat(timespec="microseconds")
        spec_inputs = (task_sha, base.ref.sha256, head_receipt_sha, *frozen.values())
        spec = ExperimentSpec(
            campaign_id=campaign_id, source_revision=source_revision,
            objective=f"Replace one exact occurrence in {relative}",
            task_sha256s=(task_sha,), baseline_sha256s=(base.ref.sha256,),
            base_source_tree_sha256=base.ref.sha256, base_source_tree_locator=base.ref.locator,
            seeds=(0, 1, 2),
            metrics=("exact_match",) if evaluator is None else ("tests_pass",),
            operator_axis="repair_variant",
            seed_derivation="fixed ordered arms: 0 baseline, 1 negative control, 2 repair",
            selection_policy="best_passed_trial", attempts_per_seed=1,
            metric_acceptance={"exact_match": 1} if evaluator is None else {"tests_pass": 1},
            gate_timeout_s=evaluator_wall_s,
            frozen_components=frozen, writable_paths=(relative,), budget=budget,
            created_at=created, expires_at=expires,
            provenance=_prov("ariadne.controlled-repair.spec", source_revision, created, *spec_inputs, trace=campaign_id),
        )
        spec_ref = store_contract(store, spec)
        contract_at = _now()
        contract_inputs = (spec.digest, task_sha, base.ref.sha256, evaluator_sha, *frozen.values())
        contract = campaign_contract_for_spec(
            spec,
            provenance=_prov("ariadne.controlled-repair.contract", source_revision, contract_at, *contract_inputs, trace=campaign_id),
        )
        contract_ref = store_contract(store, contract)
        campaign_begin = begin_campaign(ledger.spine, store, contract, contract_ref, spec_ref)
        if not campaign_begin.execute:
            assert campaign_begin.receipt is not None
            _require_campaign_inner_effect_terminals(
                store,
                effect_evidence_root,
                campaign_begin.receipt,
            )
            _require_campaign_outer_effect_terminal(
                store,
                effect_evidence_root,
                campaign_begin.receipt,
                operation_sha256=operation_sha,
            )
            settled = _settle_committed_outer_effect(
                granted,
                effect_start,
                execution,
                campaign_begin.receipt.digest,
            )
            if not settled:
                raise AriadneCampaignError(
                    "campaign replay is canonical but its invocation effect needs "
                    "ledger/evidence reconciliation"
                )
            return campaign_begin.receipt.to_dict()
        coordinator = IsolatedAttemptCoordinator(
            primary_checkout=root, workspace_parent=workspace_parent,
            source_store=store, ledger=ledger,
        )
        trials: list[CampaignTrialReceipt] = []
        evidence_by_key: dict[tuple[str, int], EvidencePacket] = {}
        #: How many tests each arm actually EXECUTED, per the report it wrote.
        executed_by_variant: dict[str, int] = {}
        #: WHICH tests each arm ran and what each said. A count cannot tell a
        #: suite that ran from one that was neutered in place (O2-1b).
        identities_by_variant: dict[str, tuple[str, ...]] = {}
        arms = (("baseline", "baseline", 0), ("negative-control", "candidate", 1), ("repair", "candidate", 2))
        # Resolved once per campaign so every arm runs under the same
        # interpreter; the observation records its identity, never its path.
        # The frozen evaluator is a stdlib-only payload and runs on the bare
        # base interpreter. A TEST command needs the environment the suite is
        # written against -- measured 2026-09-10: the base interpreter cannot
        # import pytest. The kernel's own pytest gate makes the same choice
        # (``pytest_gate_argv`` builds from ``sys.executable``). Either way the
        # child is contained with a scrubbed environment, and the observation
        # records which interpreter ran the arm.
        evaluator_interpreter = (
            _evaluator_interpreter() if evaluator is None else sys.executable
        )
        interpreter_provenance = _interpreter_provenance(evaluator_interpreter)
        for variant, role, seed in arms:
            switch.checkpoint()
            started = _now()
            attempt_id = f"{campaign_id}-{variant}"
            task = TaskSpec(
                task_id=attempt_id,
                instruction=f"Ariadne controlled repair arm {variant}",
                base_revision=source_revision,
                target_paths=(relative,),
                gate_argv=(
                    ("python", "-I", "-c", EVALUATOR_SOURCE, relative, expected_sha)
                    if evaluator is None else evaluator.argv
                ),
                gate_timeout_s=evaluator_wall_s,
            )
            attempt_inputs = (task.digest, operation_sha, granted.policy_decision.digest)
            attempt = AttemptContract.from_task_spec(
                task, attempt_id=attempt_id, mission_id=campaign_id,
                runtime_manifest_sha256=operation_sha,
                policy_decision_sha256=granted.policy_decision.digest,
                budget=budget, campaign_id=campaign_id, base_revision=source_revision,
                provenance=_prov("ariadne.controlled-repair.attempt", source_revision, started, *attempt_inputs, trace=campaign_id),
            )
            attempt_ref = store_contract(store, attempt)
            relative_workspace = f"attempts/{attempt.attempt_id}-{attempt.digest[:16]}"
            attempt_begin = ledger.begin(
                attempt, base, start_id=f"start-{attempt_id}",
                workspace_parent_sha256=coordinator.workspace_parent_sha256,
                workspace_relative_path=relative_workspace,
            )
            if not attempt_begin.execute:
                raise AriadneCampaignError(f"attempt {attempt_id} is pending or already terminal")
            active_attempt_begin = attempt_begin
            inner = acquire_attempt_lease(
                root, source_revision=source_revision, mission_id=campaign_id,
                attempt_id=attempt_id, effect_key=f"attempt-lifecycle:{attempt_id}",
                writable_paths=(relative,), write_policy=Policy(write_allow=(relative,)),
                contained=True,
                containment_evidence=(
                    "exact base CAS materialized below the external campaign "
                    "workspace while the shared Genesis/Ariadne slot is held"
                ),
                subject_root=root, worktree_root=workspace_parent,
                intent_ledger_path_resolver=resolve_spine_db_path,
                trace_id=campaign_id, switch=switch,
                evidence_root=effect_evidence_root,
                operation_sha256=attempt.digest,
            )
            if isinstance(inner, WaveLeaseDenied):
                raise AriadneCampaignError("per-attempt lease denied: " + "; ".join(inner.reasons))
            inner_execution = inner.execution_for(
                0,
                writable_paths=(relative,),
                tools=("python",),
                operation_sha256=attempt.digest,
            )
            # As with the outer Campaign lease, missing retained start evidence
            # is a pre-effect refusal. The terminal-state value is immaterial
            # to this start-only validation and is re-bound after evaluation.
            _inner_effect_binding(
                inner,
                inner_execution,
                attempt,
                expected_terminal_state="failed",
            )
            inner_start = inner.authorization.begin_effect(inner_execution)
            if not inner_start.execute:
                raise AriadneCampaignError(f"attempt {attempt_id} effect is pending or terminal")
            active_inner = inner
            active_inner_execution = inner_execution
            active_inner_start = inner_start
            workspace = workspace_parent.joinpath(*relative_workspace.split("/"))
            store.materialize_tree(base.ref, workspace)
            candidate_file = workspace / relative
            if variant == "negative-control":
                candidate_file.write_bytes(negative_control)
            elif variant == "repair":
                candidate_file.write_bytes(expected)
            candidate_at = _now()
            candidate = store.capture_tree(
                workspace, tree_id=f"{attempt_id}-candidate",
                source_revision=source_revision,
                origin="ariadne.controlled-repair.candidate",
                created_at=candidate_at, trace_id=campaign_id,
                max_file_bytes=MAX_CAMPAIGN_FILE_BYTES,
                max_total_bytes=MAX_CAMPAIGN_FILE_BYTES,
            )
            usage = ResourceUsage()
            evaluation_workspace: Path | None = None
            try:
                # NEGATIVE EVIDENCE, retained (Cerberus rounds 3 and 4).
                # Round 3 moved this workspace into %TEMP% so the retained
                # observations would not be a parent directory of the running
                # arm. Round 4 measured that a contained arm finds this
                # campaign's own baseline observation anyway, by walking DOWN
                # from Path.home(): the control root is home-derived and the
                # child needs no path to it. The move bought nothing and cost
                # two true statements -- the arm ran outside the containment
                # root this campaign declares and retains -- plus an unbounded
                # temp leak. The workspace belongs where the lease says it is.
                evaluation_workspace = (
                    workspace_parent
                    / "evaluations"
                    / f"{attempt.attempt_id}-{candidate.ref.sha256[:16]}"
                )
                workspace_files = 0
                workspace_bytes = 0
                if evaluator is None:
                    materialized_candidate = store.materialize_tree(
                        candidate.ref,
                        evaluation_workspace,
                        max_file_bytes=MAX_CAMPAIGN_FILE_BYTES,
                        max_total_bytes=MAX_CAMPAIGN_FILE_BYTES,
                    )
                    if materialized_candidate != candidate.manifest:
                        raise AriadneCampaignError(
                            "fresh evaluator materialization differs from candidate CAS"
                        )
                    gate_argv = (
                        evaluator_interpreter, "-I", "-S", "-c",
                        EVALUATOR_SOURCE, relative, expected_sha,
                    )
                    gate_name = "ariadne-frozen-evaluator"
                    gate_timeout = float(timeout_s)
                else:
                    # Tests are the judge. The workspace is the pinned
                    # REVISION with one file replaced, plus two files the
                    # CAMPAIGN writes: its own JUnit report and its own pytest
                    # config.
                    #
                    # What this does and does not guarantee, precisely, because
                    # the comment here used to claim "the candidate cannot
                    # reach any other byte" and that was false (Cerberus round
                    # 4, high 1). pytest's rootdir discovery walks UPWARD out
                    # of the workspace: an ini file in an ANCESTOR whose
                    # `addopts` re-injects `-p <module>` loads and executes an
                    # arbitrary module inside the judging process, with no
                    # hostile argv at all. The campaign-owned `-c` below pins
                    # rootdir and conftest collection inside the workspace,
                    # which closes that route.
                    #
                    # What still holds it, and is worth stating because it was
                    # got for free rather than designed: this workspace lives
                    # under the control root, not under %TEMP%. A candidate
                    # cannot plant an ancestor config there -- the workspace is
                    # Low-integrity and the ancestors are not, so a Low process
                    # cannot write up. Under %TEMP% any same-user process
                    # could. Round 3 moved it to %TEMP% and round 4 moved it
                    # back for unrelated reasons; do not move it again without
                    # reading this.
                    workspace_files, workspace_bytes = _extract_revision(
                        root, source_revision, evaluation_workspace
                    )
                    arm_bytes = (
                        original_bytes if variant == "baseline"
                        else negative_control if variant == "negative-control"
                        else expected
                    )
                    if hashlib.sha256(arm_bytes).hexdigest() != candidate.manifest.entries[0].blob_sha256:
                        raise AriadneCampaignError(
                            "arm bytes differ from the captured candidate"
                        )
                    overlay = evaluation_workspace.joinpath(*relative.split("/"))
                    if not overlay.is_file():
                        raise AriadneCampaignError(
                            "target is not a file at the pinned revision"
                        )
                    overlay.write_bytes(arm_bytes)
                    # The campaign appends its OWN report flag and its OWN
                    # config, so the caller cannot omit either, the candidate
                    # cannot choose where the counts come from, and pytest
                    # cannot walk up out of the workspace looking for one.
                    #
                    # `--rootdir=.` is not redundant beside `-c`. `PYTEST_ADDOPTS`
                    # is split and PREPENDED before `parse_known_args`, so a
                    # `--rootdir` exported in the operator's shell resolves
                    # before `determine_setup` runs and beats `-c` outright
                    # (Cerberus round 5, high 1, measured). Because the
                    # environment is PREPENDED, this one lands later and wins
                    # it back. It does NOT close `PYTEST_PLUGINS`, or `-p`
                    # arriving through `PYTEST_ADDOPTS` -- see the packet.
                    config = evaluation_workspace / TEST_CONFIG_RELATIVE
                    if config.exists():
                        raise AriadneCampaignError(
                            "the pinned revision already contains "
                            f"{TEST_CONFIG_RELATIVE}, which the campaign must own")
                    config.write_bytes(TEST_CONFIG_BODY)
                    gate_argv = (
                        evaluator_interpreter, *evaluator.argv[1:],
                        "-c", TEST_CONFIG_RELATIVE, "--rootdir=.",
                        f"--junitxml={TEST_REPORT_RELATIVE}",
                    )
                    gate_name = "ariadne-test-evaluator"
                    gate_timeout = float(evaluator.timeout_s)
                result = command_gate(
                    gate_argv,
                    timeout_s=gate_timeout,
                    poll_s=0.05,
                    name=gate_name,
                    executes_candidate=True,
                )(
                    RunnerContext(
                        worktree=evaluation_workspace,
                        branch=f"ariadne/{attempt_id}",
                        base_revision=source_revision,
                        task=task,
                        is_cancelled=switch.should_stop,
                    )
                )
                finished = _now()
                usage = ResourceUsage(
                    wall_time_ms=max(0, int(round(result.duration_s * 1000)))
                )
                workspace_removed = False
                budget_violations = budget.violations(usage)
                trial_passed = bool(result.passed) and not budget_violations
                report_counts: dict[str, int] = {}
                if evaluator is not None:
                    # An exit code cannot tell "the tests passed" from "no test
                    # ran". A candidate that switched the suite off exited zero
                    # (Cerberus round 1, CRITICAL 2), so the counts decide.
                    try:
                        report_counts = _read_test_report(
                            evaluation_workspace / TEST_REPORT_RELATIVE
                        )
                    except AriadneCampaignError:
                        report_counts = {"tests": 0, "failures": 0, "errors": 0,
                                         "skipped": 0, "executed": 0}
                    identities = _read_test_identities(
                        evaluation_workspace / TEST_REPORT_RELATIVE
                    )
                    if identities and len(identities) != report_counts["tests"]:
                        # The counts come from `<testsuite>` attributes and the
                        # identities from `<testcase>` elements. A report whose
                        # two halves disagree is not evidence (medium 1).
                        report_counts = {"tests": 0, "failures": 0, "errors": 0,
                                         "skipped": 0, "executed": 0}
                    trial_passed = (
                        trial_passed
                        and report_counts["executed"] > 0
                        and report_counts["failures"] == 0
                        and report_counts["errors"] == 0
                    )
                    executed_by_variant[variant] = report_counts["executed"]
                    identities_by_variant[variant] = identities
                    # A tree of the pinned revision per arm is ~284 MiB on this
                    # repository; three of them per campaign, retained forever,
                    # is not evidence, it is disk (Cerberus round 1, high 3).
                    # The receipt is the evidence, so the tree goes. The
                    # `finally` below covers the paths this line cannot reach:
                    # a fault between the extraction and here left the whole
                    # revision on disk in every earlier revision of this packet
                    # (Cerberus round 4).
                    workspace_removed = _remove_evaluation_workspace(evaluation_workspace)
                if evaluator is None:
                    evaluator_value = _verify_frozen_evaluator_output(
                        result,
                        candidate,
                        relative=relative,
                        expected_sha256=expected_sha,
                    )
                    observation = {
                        "schema": "daedalus-ariadne-evaluator-observation/2",
                        "variant_id": variant,
                        "seed": seed,
                        "evaluator_sha256": EVALUATOR_SHA256,
                        "passed": result.passed,
                        "returncode": result.returncode,
                        "output": result.output,
                        "output_sha256": result.output_sha256,
                        "candidate_tree_sha256": candidate.ref.sha256,
                        "expected_sha256": evaluator_value["expected_sha256"],
                        "observed_sha256": evaluator_value["observed_sha256"],
                        "containment": (
                            result.containment.summary() if result.containment else None
                        ),
                        "interpreter": interpreter_provenance,
                    }
                else:
                    # The output is producer text and can name host paths, so the
                    # evidence retains NO output at all -- not an excerpt, not a
                    # redaction. A digest and the report counts say what happened
                    # and the text stays in the gate's scratch (Cerberus round 2,
                    # low: this comment described the design it replaced).
                    raw_output = result.output or ""
                    observation = {
                        "schema": TEST_EVALUATOR_OBSERVATION_SCHEMA,
                        "variant_id": variant,
                        "seed": seed,
                        "evaluator_sha256": evaluator_sha,
                        "command_sha256": evaluator.digest,
                        "passed": bool(trial_passed),
                        "returncode": result.returncode,
                        "timed_out": bool(getattr(result, "timed_out", False)),
                        # The output itself is NOT retained: the child inherits
                        # the operator's environment, and a candidate that
                        # printed it put a live API key into CAS (Cerberus round
                        # 1, CRITICAL 1). The digest still ties the receipt to
                        # what the gate saw; the text stays in gate scratch.
                        "output": "",
                        "output_sha256": hashlib.sha256(raw_output.encode("utf-8")).hexdigest(),
                        "report": dict(report_counts),
                        "candidate_tree_sha256": candidate.ref.sha256,
                        "workspace_files": workspace_files,
                        "workspace_bytes": workspace_bytes,
                        "workspace_removed": workspace_removed,
                        # The counts come from a report written by a process
                        # that ran candidate code, in a directory that process
                        # can write. Nothing here is proof against a hostile
                        # generator, and the receipt says so rather than letting
                        # a reader assume otherwise (Cerberus round 2).
                        "verdict_is_self_reported": True,
                        # Stated, not implied: what the contained child could
                        # reach. The gate's environment is a denylist and it has
                        # no network fence, so a reader of this receipt is not
                        # told a fence existed (Cerberus round 1, CRITICAL 1).
                        "child_environment": "inherited-except-denylist",
                        "child_network": "unrestricted",
                        "containment": (
                            result.containment.summary() if result.containment else None
                        ),
                        "interpreter": interpreter_provenance,
                    }
                observation_ref = store.put_bytes(
                    canonical_json(observation).encode("ascii")
                )
                item_prov = _prov(
                    "ariadne.frozen-evaluator" if evaluator is None else "ariadne.test-evaluator",
                    source_revision,
                    finished,
                    observation_ref.sha256,
                    trace=campaign_id,
                )
                item = EvidenceItem(
                    evidence_id=f"evidence-{attempt_id}",
                    evaluator=("ariadne-frozen-evaluator" if evaluator is None
                               else "ariadne-test-command-evaluator"),
                    assurance="independent",
                    verdict="passed" if result.passed else "failed",
                    output_sha256=observation_ref.sha256,
                    evidence_locator=observation_ref.locator,
                    collected_at=finished,
                    provenance=item_prov,
                    details={
                        "evaluator_sha256": evaluator_sha,
                        "configured_budget_sha256": budget_sha,
                    },
                )
                packet_inputs = (
                    attempt.digest,
                    candidate.ref.sha256,
                    granted.policy_decision.digest,
                    observation_ref.sha256,
                )
                packet = EvidencePacket(
                    packet_id=f"packet-{attempt_id}",
                    mission_id=campaign_id,
                    attempt_id=attempt_id,
                    source_revision=source_revision,
                    attempt_contract_sha256=attempt.digest,
                    subject_sha256=candidate.ref.sha256,
                    evaluation_status="passed" if result.passed else "failed",
                    items=(item,),
                    policy_decision_sha256=granted.policy_decision.digest,
                    usage=usage,
                    candidate_artifact_sha256=candidate.ref.sha256,
                    candidate_artifact_locator=candidate.ref.locator,
                    provenance=_prov(
                        "ariadne.controlled-repair.evidence",
                        source_revision,
                        finished,
                        *packet_inputs,
                        trace=campaign_id,
                    ),
                )
                packet_ref = store_contract(store, packet)
                inner_binding = _inner_effect_binding(
                    inner,
                    inner_execution,
                    attempt,
                    expected_terminal_state=(
                        "completed" if trial_passed else "failed"
                    ),
                )
                report_ref = _store_attempt_report(
                    store,
                    packet_ref=packet_ref,
                    observation_ref=observation_ref,
                    inner_effect=inner_binding,
                )
                completion = ledger.complete(
                    attempt_begin.start,
                    receipt_id=f"terminal-{attempt_id}",
                    outcome="succeeded" if trial_passed else "failed",
                    report=report_ref,
                    candidate_tree=candidate,
                )
            except BaseException as arm_failure:
                faulted_trial, terminal_error = _faulted_attempt_trial(
                    evaluator=evaluator,
                    store=store,
                    ledger=ledger,
                    attempt_begin=attempt_begin,
                    attempt=attempt,
                    attempt_ref=attempt_ref,
                    inner=inner,
                    inner_execution=inner_execution,
                    inner_start=inner_start,
                    candidate=candidate,
                    base=base,
                    campaign_id=campaign_id,
                    source_revision=source_revision,
                    variant=variant,
                    role=role,
                    seed=seed,
                    budget_sha256=budget_sha,
                    started_at=started,
                    usage=usage,
                    failure=arm_failure,
                    evidence_root=effect_evidence_root,
                )
                trials.append(faulted_trial)
                failure_type, failure_message = _bounded_failure(arm_failure)
                blocker = f"{variant}:{failure_type}: {failure_message}"
                if terminal_error is not None:
                    blocker = f"{blocker}; inner-terminal: {terminal_error}"
                failed_receipt, failed_receipt_ref = _complete_failed_campaign_receipt(
                    evaluator=evaluator,
                    store=store,
                    ledger=ledger,
                    campaign_begin=campaign_begin,
                    contract=contract,
                    contract_ref=contract_ref,
                    spec=spec,
                    spec_ref=spec_ref,
                    granted=granted,
                    execution=execution,
                    trials=trials,
                    campaign_id=campaign_id,
                    source_revision=source_revision,
                    operation_sha256=operation_sha,
                    started_at=created,
                    base_binding_sha256=base_binding_ref.sha256,
                    blocker=blocker,
                    reproducibility_note=(
                        "The campaign stopped at the first post-capture error; "
                        "the exact candidate, error observation, EvidencePacket, "
                        "faulted Attempt, and frozen trial prefix are retained."
                    ),
                    additional_negative_outcomes=(
                        (f"{variant}:inner-terminal-evidence-unavailable",)
                        if terminal_error is not None
                        else ()
                    ),
                )
                campaign_committed = True
                if terminal_error is None:
                    _require_campaign_inner_effect_terminals(
                        store,
                        effect_evidence_root,
                        failed_receipt,
                    )
                settled = _settle_committed_outer_effect(
                    granted,
                    effect_start,
                    execution,
                    failed_receipt_ref.sha256,
                )
                if not settled:
                    raise AriadneCampaignError(
                        "Campaign failure receipt is canonical but its outer effect "
                        "needs ledger/evidence reconciliation"
                    ) from arm_failure
                if terminal_error is not None:
                    raise AriadneCampaignError(
                        "Campaign failure receipt is canonical but its inner Attempt "
                        f"effect needs reconciliation: {terminal_error}"
                    ) from arm_failure
                if _is_domain_failure(arm_failure):
                    # G1-ARIADNE-04: an evaluator-contract violation is a retained
                    # negative outcome. The failed receipt is canonical, settled and
                    # replayable, so it IS the result of this call, not an error a
                    # caller has to replay for. Foreign crashes and cancellations
                    # still raise: those are faults the operator must see as such.
                    return failed_receipt.to_dict()
                raise
            finally:
                # The ARM's try: a fault between building this workspace and
                # removing it left the entire pinned revision on disk -- about
                # 284 MiB for this repository -- in every earlier revision of
                # this packet (Cerberus round 4). The receipt is the evidence.
                if evaluation_workspace is not None:
                    _remove_evaluation_workspace(evaluation_workspace)
            receipt_ref = store_contract(store, completion.receipt)
            negative_outcomes = []
            blockers = []
            if evaluator is None:
                if not result.passed:
                    negative_outcomes.append("frozen-evaluator-rejected")
                    blockers.append("exact-match-failed")
            elif not trial_passed:
                negative_outcomes.append("test-command-failed")
                if getattr(result, "timed_out", False):
                    blockers.append("test-command-timed-out")
                elif not result.passed:
                    blockers.append("test-command-exit-nonzero")
                elif report_counts.get("executed", 0) <= 0:
                    # The command exited zero and ran nothing. This is the shape
                    # the proven attack produced, so it gets its own name.
                    blockers.append("test-command-executed-no-tests")
                else:
                    blockers.append(
                        f"test-command-reported-failures: {report_counts.get('failures', 0)} "
                        f"failures, {report_counts.get('errors', 0)} errors"
                    )
            if budget_violations:
                negative_outcomes.append("budget-exhausted")
                blockers.extend(f"budget: {item}" for item in budget_violations)
            trial = CampaignTrialReceipt(
                campaign_id=campaign_id, seed=seed, replay_role="origin", stage="complete",
                status="passed" if trial_passed else "failed",
                base_source_tree_sha256=base.ref.sha256, base_source_tree_locator=base.ref.locator,
                mission_sha256=None, mission_locator=None, attempt_ids=(attempt_id,),
                attempt_contract_sha256s=(attempt.digest,), attempt_contract_locators=(attempt_ref.locator,),
                attempt_receipt_sha256s=(completion.receipt.digest,), attempt_receipt_locators=(receipt_ref.locator,),
                gate1_receipt_sha256=None, gate1_receipt_locator=None,
                candidate_tree_sha256=candidate.ref.sha256, candidate_tree_locator=candidate.ref.locator,
                candidate_source_bundle_sha256=None, candidate_snapshot_sha256=None,
                candidate_snapshot_locator=None, graph_delta_sha256=None,
                evidence_packet_sha256=packet.digest, evidence_packet_locator=packet_ref.locator,
                metrics=(
                    {"exact_match": 1 if result.passed else 0} if evaluator is None
                    else {"tests_pass": 1 if result.passed else 0}
                ), usage=usage,
                negative_outcomes=tuple(negative_outcomes),
                blockers=tuple(blockers),
                started_at=started, finished_at=finished, variant_id=variant, arm_role=role,
                configured_budget_sha256=budget_sha, receipt_profile="controlled-repair-v1",
            )
            try:
                inner.authorization.finish_effect(
                    inner_start.receipt,
                    outcome="COMPLETED" if trial_passed else "FAILED",
                    output_digests=(receipt_ref.sha256,),
                )
                terminal_record = inner.retain_terminal_record(inner_execution)
                if terminal_record is None:
                    raise AriadneCampaignError(
                        "inner attempt effect terminal evidence was not retained"
                    )
                _require_bound_inner_terminal(
                    effect_evidence_root,
                    inner_binding,
                    attempt,
                    completion.receipt,
                )
            except BaseException as terminal_failure:
                trials.append(trial)
                terminal_type, terminal_message = _bounded_failure(terminal_failure)
                _failed_receipt, failed_receipt_ref = _complete_failed_campaign_receipt(
                    evaluator=evaluator,
                    store=store,
                    ledger=ledger,
                    campaign_begin=campaign_begin,
                    contract=contract,
                    contract_ref=contract_ref,
                    spec=spec,
                    spec_ref=spec_ref,
                    granted=granted,
                    execution=execution,
                    trials=trials,
                    campaign_id=campaign_id,
                    source_revision=source_revision,
                    operation_sha256=operation_sha,
                    started_at=created,
                    base_binding_sha256=base_binding_ref.sha256,
                    blocker=(
                        f"{variant}:inner-terminal-evidence:{terminal_type}:"
                        f" {terminal_message}"
                    ),
                    reproducibility_note=(
                        "The retained trial and Attempt are canonical, but the "
                        "inner attempt-effect terminal evidence did not verify; "
                        "the campaign stopped before the next frozen arm."
                    ),
                    additional_negative_outcomes=(
                        f"{variant}:inner-terminal-evidence-unavailable",
                    ),
                )
                campaign_committed = True
                settled = _settle_committed_outer_effect(
                    granted,
                    effect_start,
                    execution,
                    failed_receipt_ref.sha256,
                )
                if not settled:
                    raise AriadneCampaignError(
                        "Campaign failure receipt is canonical but its outer effect "
                        "needs ledger/evidence reconciliation"
                    ) from terminal_failure
                raise AriadneCampaignError(
                    "Campaign failure receipt is canonical but its inner Attempt "
                    "effect needs reconciliation"
                ) from terminal_failure
            finally:
                # A fault between the extraction and the removal above left
                # the entire pinned revision on disk -- about 284 MiB for
                # this repository -- in every earlier revision of this
                # packet (Cerberus round 4). The receipt is the evidence;
                # the tree is not.
                if evaluation_workspace is not None:
                    _remove_evaluation_workspace(evaluation_workspace)
            active_attempt_begin = None
            active_inner = None
            active_inner_execution = None
            active_inner_start = None

            trials.append(trial)
            evidence_by_key[(variant, seed)] = packet
            if budget_violations:
                receipt, receipt_ref = _complete_failed_campaign_receipt(
                    evaluator=evaluator,
                    store=store,
                    ledger=ledger,
                    campaign_begin=campaign_begin,
                    contract=contract,
                    contract_ref=contract_ref,
                    spec=spec,
                    spec_ref=spec_ref,
                    granted=granted,
                    execution=execution,
                    trials=trials,
                    campaign_id=campaign_id,
                    source_revision=source_revision,
                    operation_sha256=operation_sha,
                    started_at=created,
                    base_binding_sha256=base_binding_ref.sha256,
                    blocker="; ".join(
                        f"{variant}:{violation}" for violation in budget_violations
                    ),
                    reproducibility_note=(
                        "The frozen campaign stopped before its next seed when "
                        "the retained trial exceeded its equal budget ceiling."
                    ),
                )
                campaign_committed = True
                _require_campaign_inner_effect_terminals(
                    store,
                    effect_evidence_root,
                    receipt,
                )
                settled = _settle_committed_outer_effect(
                    granted, effect_start, execution, receipt_ref.sha256
                )
                if not settled:
                    raise AriadneCampaignError(
                        "Campaign receipt is canonical but its outer effect needs "
                        "ledger/evidence reconciliation"
                    )
                return receipt.to_dict()
        trial_by_variant = {trial.variant_id: trial for trial in trials}
        baseline_trial = trial_by_variant["baseline"]
        negative_trial = trial_by_variant["negative-control"]
        repair_trial = trial_by_variant["repair"]
        if evaluator is None:
            if (
                baseline_trial.status != "failed"
                or negative_trial.status != "failed"
                or repair_trial.status != "passed"
            ):
                raise AriadneCampaignError(
                    "controlled repair requires failed baseline and negative control "
                    "plus a passed repair"
                )
        else:
            # Under a test-running evaluator the arms mean something else, and
            # each failure names WHICH property of the evidence is missing.
            if baseline_trial.status != "passed":
                raise AriadneCampaignError(
                    "the test command already fails on the unmodified revision, so no "
                    "verdict about this change can be attributed to it"
                )
            if negative_trial.status != "failed":
                raise AriadneCampaignError(
                    "the test command passes on the negative control, so the suite "
                    "cannot see this file and a passing repair proves nothing"
                )
            if repair_trial.status != "passed":
                raise AriadneCampaignError(
                    "the repair does not pass the test command"
                )
            # The repair must pass THE SAME suite, not a suite of its own size.
            # `>=` let a forged report inflate the count and win: the reviewer
            # wrote a report claiming 41 tests where the baseline ran 1, and it
            # was nominated (Cerberus round 2). Equality also closes the "more
            # but weaker" class. It does NOT make the count unknowable to a
            # forger: round 3 read the baseline's own retained observation from
            # a parent directory of the arm, and counting the suite directly
            # works too. The rule raises the cost of a forgery; it does not
            # prevent one, and `verdict_is_self_reported` is the field that
            # says so.
            baseline_executed = executed_by_variant.get("baseline", 0)
            repair_executed = executed_by_variant.get("repair", 0)
            if repair_executed != baseline_executed:
                raise AriadneCampaignError(
                    "the repair arm executed a different number of tests than the "
                    f"baseline ({repair_executed} against {baseline_executed}), so it "
                    "did not pass the same suite"
                )
            baseline_ids = identities_by_variant.get("baseline", ())
            repair_ids = identities_by_variant.get("repair", ())
            control_ids = identities_by_variant.get("negative-control", ())
            if not baseline_ids:
                raise AriadneCampaignError(
                    "the baseline arm reported no test identities, so there is nothing "
                    "for the repair to have passed"
                )
            if repair_ids != baseline_ids:
                # Same count, different tests or different outcomes: that is not
                # the same suite passing (O2-1b: the count matched exactly while
                # every assertion had been neutered in place).
                raise AriadneCampaignError(
                    "the repair arm did not report the same tests with the same "
                    "outcomes as the baseline"
                )
            if control_ids == baseline_ids:
                # The control must DISAGREE with the baseline somewhere.
                raise AriadneCampaignError(
                    "the negative control reported the same tests and outcomes as the "
                    "baseline, so the suite does not exercise the changed region and a "
                    "passing repair proves nothing about it"
                )
            # The failing test must be one the BASELINE passed: a flaky rerun
            # that emits both outcomes, or an id present only in the control,
            # otherwise satisfies this (Cerberus round 1, medium 2).
            baseline_passed = {identity[: -len("=passed")]
                               for identity in baseline_ids if identity.endswith("=passed")}
            control_failed = {identity[: -len("=failure")]
                              for identity in control_ids if identity.endswith("=failure")}
            if not (control_failed & baseline_passed):
                # A test that ERRORED did not run: the mangled file failed to
                # import or collect, so the control proved the suite LOADS the
                # file and nothing about whether it exercises the changed region
                # (Odysseus round 2 on the merged packet, O2-1a: a real
                # behaviour change no test reads was nominated on exactly this).
                # A test that FAILED ran and disagreed, which is the evidence
                # this arm exists to produce. Refusing here means many campaigns
                # will not nominate; that is correct, because they prove nothing.
                # Two different situations, and saying the wrong one is a lie
                # the operator will act on (Cerberus round 1, high 2). The
                # campaign's mutation appends an identifier to the target text,
                # which is a SYNTAX error for a numeric literal, a closing quote
                # or a `def` name -- there the module never parses and even a
                # suite that genuinely covers the region errors.
                if any(identity.endswith("=error") for identity in control_ids):
                    raise AriadneCampaignError(
                        "the negative control did not parse or collect, so this campaign "
                        "cannot discriminate: the mutation appends an identifier to the "
                        "target text, which is a syntax error in this position. Choose a "
                        "`before` whose mangled form still parses (an expression or a "
                        "string's contents) or the evidence cannot be produced"
                    )
                raise AriadneCampaignError(
                    "no test that the baseline passed FAILED against the negative control, "
                    "so the suite did not disagree about the changed region and a passing "
                    "repair proves nothing about it"
                )
        selected = repair_trial
        selected_packet = evidence_by_key[(selected.variant_id, selected.seed)]
        nomination_at = _now()
        nomination_inputs = (selected.candidate_tree_sha256, selected_packet.digest, granted.policy_decision.digest)
        nomination = NominationReceipt(
            nomination_id=f"nomination-{campaign_id}", mission_id=campaign_id,
            attempt_id=selected.attempt_ids[0], source_revision=source_revision,
            candidate_artifact_sha256=selected.candidate_tree_sha256,
            candidate_artifact_locator=selected.candidate_tree_locator,
            evidence_packet_sha256=selected_packet.digest,
            evidence_locator=selected.evidence_packet_locator,
            policy_decision_sha256=granted.policy_decision.digest,
            nomination_status="nominated",
            reasons=(
                ("passed frozen exact-match evaluator under equal configured budget",)
                if evaluator is None else
                ("SELF-REPORTED: the project's own test command reported a green baseline, "
                 "a failing negative control and a passing repair executing the same number "
                 "of tests, under equal configured budget. The command ran candidate code, "
                 "so this verdict is the run's own report and not an independent measurement",)
            ),
            provenance=_prov("ariadne.controlled-repair.nomination", source_revision, nomination_at, *nomination_inputs, trace=campaign_id),
        )
        nomination_ref = store_contract(store, nomination)
        usage = ResourceUsage(wall_time_ms=sum(t.usage.wall_time_ms for t in trials))
        budget_equality = CampaignBudgetEqualityEvidence(
            configured_budget_sha256=budget_sha,
            trial_keys=tuple(f"{t.variant_id}:{t.seed}" for t in trials),
            trial_budget_sha256s=tuple(t.configured_budget_sha256 for t in trials),
            realized_usage_sha256s=tuple(canonical_sha(asdict(t.usage)) for t in trials),
            configured_equal=True, realized_usage_recorded=True,
            within_budget=all(not budget.violations(t.usage) for t in trials),
        )
        outer_binding = _outer_effect_binding(
            granted,
            execution,
            campaign_id=campaign_id,
            source_revision=source_revision,
            operation_sha256=operation_sha,
        )
        outer_binding_ref = store.put_bytes(
            canonical_json(outer_binding).encode("ascii")
        )
        finished = _now()
        receipt_inputs = {
            contract.digest, spec.digest, selected.candidate_tree_sha256,
            outer_binding_ref.sha256, base_binding_ref.sha256,
            nomination.digest, *(digest for t in trials for digest in (
                t.base_source_tree_sha256, *t.attempt_contract_sha256s,
                *t.attempt_receipt_sha256s, t.candidate_tree_sha256, t.evidence_packet_sha256,
            ) if digest is not None),
        }
        receipt = CampaignReceipt(
            campaign_id=campaign_id, source_revision=source_revision,
            campaign_contract_sha256=contract.digest, campaign_contract_locator=contract_ref.locator,
            experiment_spec_sha256=spec.digest, experiment_spec_locator=spec_ref.locator,
            metric_names=("exact_match",) if evaluator is None else ("tests_pass",),
            trials=tuple(trials), execution_order=(0, 1, 2),
            outcome="nominated", selected_seed=selected.seed,
            candidate_tree_sha256=selected.candidate_tree_sha256,
            candidate_tree_locator=selected.candidate_tree_locator,
            nomination_receipt_sha256=nomination.digest,
            nomination_receipt_locator=nomination_ref.locator,
            usage=usage, overhead_usage=ResourceUsage(),
            negative_outcomes=tuple(sorted({
                f"{t.variant_id}:{outcome}"
                for t in trials for outcome in t.negative_outcomes
            })),
            reproducibility_note=(
                "The exact working-tree bytes are identified by base_source_tree_sha256; "
                "source_revision is independently verified HEAD provenance. Replay uses "
                "that base CAS, frozen evaluator, ordered arms, and equal ceilings."
            ),
            blockers=(), started_at=created, finished_at=finished,
            provenance=_prov("ariadne.controlled-repair.receipt", source_revision, finished, *receipt_inputs, trace=campaign_id),
            selection_mode="best-passed-trial", selected_variant_id=selected.variant_id,
            budget_equality=budget_equality,
        )
        receipt_ref = complete_campaign(ledger.spine, store, campaign_begin, receipt)
        campaign_committed = True
        _require_campaign_inner_effect_terminals(
            store,
            effect_evidence_root,
            receipt,
        )
        settled = _settle_committed_outer_effect(
            granted, effect_start, execution, receipt_ref.sha256
        )
        if not settled:
            raise AriadneCampaignError(
                "Campaign receipt is canonical but its outer effect needs "
                "ledger/evidence reconciliation"
            )
        return receipt.to_dict()
    except BaseException as exc:
        if campaign_committed:
            # The receipt is already canonical and durable. Never rewrite the
            # outer effect as FAILED. The caller sees explicit reconciliation
            # debt and every replay checks the receipt-bound terminal record.
            raise
        # Terminalise the innermost admitted unit first.  Cleanup failures are
        # deliberately swallowed here so the original campaign failure remains
        # the reported cause; the durable attempt/effect paths retain their own
        # failure evidence whenever they are still writable.
        if active_attempt_begin is not None and ledger is not None and store is not None:
            try:
                failure_report = store.put_bytes(canonical_json({
                    "schema": "daedalus-ariadne-attempt-failure/1",
                    "error_type": type(exc).__name__, "error": str(exc),
                }).encode("ascii"))
                ledger.complete(
                    active_attempt_begin.start,
                    receipt_id=f"terminal-{active_attempt_begin.start.attempt_id}",
                    outcome="faulted", report=failure_report, candidate_tree=None,
                )
            except BaseException:
                pass
        if active_inner is not None and active_inner_start is not None:
            try:
                active_inner.authorization.finish_effect(
                    active_inner_start.receipt, outcome="FAILED", output_digests=()
                )
                if active_inner_execution is not None:
                    active_inner.retain_terminal_record(active_inner_execution)
            except BaseException:
                pass
        if (
            not campaign_committed
            and campaign_begin is not None
            and campaign_begin.execute
            and ledger is not None
        ):
            try:
                fail_campaign(ledger.spine, campaign_begin, f"{type(exc).__name__}: {exc}")
            except BaseException:
                pass
        if effect_start.execute:
            try:
                granted.authorization.finish_effect(
                    effect_start.receipt, outcome="FAILED", output_digests=()
                )
                granted.retain_terminal_record(execution)
            except BaseException:
                pass
        raise
    finally:
        if ledger is not None:
            ledger.spine.close()
        if lock_acquired:
            lock.__exit__(None, None, None)
