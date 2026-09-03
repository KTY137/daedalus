"""The evaluator whose verdict IS the gate must be bounded like the probe was.

WHY THIS FILE EXISTS
--------------------
G1-ISO-01 hardened ``runner._behavior``. An independent adversarial review of
that packet found the sibling evaluator is strictly weaker AND is the one that
decides the attempt: ``checks.pytest_check`` runs the conformance suite over
the candidate with ``env = dict(os.environ)`` and ``capture_output=True``, and
it is called on the candidate at ``gate1.py:464`` (the data/knowledge gate) and
``gate1.py:1080`` (the composed candidate).

TWO DEFECTS, BOTH MEASURED HERE BEFORE THEY WERE FIXED.

1. The candidate's suite is handed every environment variable this process
   holds -- including ``PYTHONPATH``, which two lines of candidate code put
   back on ``sys.path``, and any provider credential.

2. ``capture_output=True`` means PIPEs, and a descendant that inherits one
   keeps the parent inside ``communicate()`` after ``timeout_s`` fired.

The FIRST version of the timeout test here PASSED against the broken code, and
that negative result is kept rather than deleted: an ordinary
``subprocess.Popen`` inside a pytest test inherits pytest's own capture file,
not the evaluator's pipe, so it does not reach the defect. The candidate writes
the test file, so it can simply ask pytest for ``capfd`` and turn capture off:

    declared timeout: 3.0s
    actual wall     : 45.6s
    VERDICT         : DEFEATED - not an upper bound

``SPAWNS_SURVIVOR`` below is that measured version.

THE ALLOWLIST HAS TWO EDGES. A second adversarial review found that dropping
``PATH``, ``TEMP`` or ``TMPDIR`` from ``EVALUATOR_CHILD_ENV_KEYS`` left all 135
ignition tests green -- nothing asserted that the child receives what it NEEDS,
only that it does not receive secrets. Narrowing an allowlist breaks other
people's boxes exactly as silently as widening it leaks. Both edges are pinned
below.

WHAT THESE TESTS DO NOT CLAIM. Closing the *write* capability -- the review
wrote a file into the evaluator's own package from inside this child -- needs
containment or filesystem permissions, not a flag.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from daedalus.ignition import bundle as ignition_bundle
from daedalus.ignition import checks as ignition_checks

#: A conformance test that records the environment it was handed.
RECORDS_ENV = '''\
import json
import os
import pathlib


def test_records_environment():
    pathlib.Path(__file__).resolve().parent.joinpath("env.json").write_text(
        json.dumps(dict(os.environ)), encoding="utf-8")
'''

#: A conformance test that escapes pytest's capture -- which it may, because the
#: CANDIDATE writes this file -- and leaves a descendant holding the evaluator's
#: own stdout handle.
SPAWNS_SURVIVOR = '''\
import subprocess
import sys
import time


def test_hangs_and_leaves_a_descendant(capfd):
    with capfd.disabled():
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(45)"])
        time.sleep(45)
'''

#: Touches the home directory the way ordinary tooling does. With no home
#: variable in the child, win32 ``expanduser`` returns the literal ``~`` and
#: this creates a directory of that name INSIDE the judged tree.
TOUCHES_HOME = '''\
import os
import pathlib


def test_uses_a_home_relative_cache():
    target = pathlib.Path(os.path.expanduser("~/.cache/daedalus-probe"))
    target.mkdir(parents=True, exist_ok=True)
    (target / "state.json").write_text("{}", encoding="utf-8")
'''


def _tree(root: Path, name: str, source: str) -> Path:
    tests = root / "tests"
    tests.mkdir(parents=True)
    (tests / name).write_text(source, encoding="utf-8")
    return root


# --------------------------------------------------------------------------- #
# the allowlist: the ceiling                                                   #
# --------------------------------------------------------------------------- #
def test_pytest_child_does_not_inherit_the_verifier_environment(monkeypatch, tmp_path):
    """A credential in the verifier is not handed to the candidate's suite."""
    monkeypatch.setenv("DAEDALUS_TEST_FAKE_SECRET", "sk-verifier-secret-do-not-leak")
    monkeypatch.setenv("PYTHONPATH", "c:/somewhere/that/holds/the/evaluator")
    root = _tree(tmp_path / "candidate", "test_env.py", RECORDS_ENV)

    report = ignition_checks.pytest_check(root, ["tests/test_env.py"], timeout_s=120.0)

    assert report.passed, report.output[-2000:]
    seen = json.loads((root / "tests" / "env.json").read_text(encoding="utf-8"))
    assert "DAEDALUS_TEST_FAKE_SECRET" not in seen, (
        "the candidate's own conformance suite was handed a credential held by "
        "the process that judges it"
    )
    assert "PYTHONPATH" not in seen, (
        "the inherited PYTHONPATH is the route a candidate uses to reach the "
        "evaluator's own package from inside the evaluator"
    )


# --------------------------------------------------------------------------- #
# the allowlist: the floor                                                     #
# --------------------------------------------------------------------------- #
def test_the_child_receives_the_variables_it_cannot_work_without(tmp_path):
    """Narrowing the allowlist must go red, not silently break other boxes.

    MEASURED before this test existed: dropping ``PATH``, or ``TEMP``/``TMP``/
    ``TMPDIR``, from the allowlist left all 135 ignition tests green.
    """
    root = _tree(tmp_path / "candidate", "test_env.py", RECORDS_ENV)

    ignition_checks.pytest_check(root, ["tests/test_env.py"], timeout_s=120.0)

    seen = json.loads((root / "tests" / "env.json").read_text(encoding="utf-8"))
    missing = sorted(
        key for key in ignition_checks.EVALUATOR_CHILD_ENV_REQUIRED
        if key in os.environ and key not in seen
    )
    assert not missing, (
        f"the evaluator child was denied {missing}, which it cannot work "
        "without; a narrowed allowlist breaks boxes other than this one and "
        "nothing else in the suite notices"
    )


def test_a_home_relative_suite_does_not_pollute_the_judged_tree(tmp_path):
    """The silent half of a too-narrow allowlist.

    Without a home variable, win32 ``expanduser("~")`` returns ``~`` rather
    than raising, the suite passes, and a directory named ``~`` appears in the
    candidate worktree -- which
    ``kernel.attempt_execution._post_gate_artifact_stable`` turns into a
    refused GREEN verdict.
    """
    root = _tree(tmp_path / "candidate", "test_home.py", TOUCHES_HOME)

    report = ignition_checks.pytest_check(root, ["tests/test_home.py"], timeout_s=120.0)

    assert report.passed, report.output[-2000:]
    assert not (root / "~").exists(), (
        "a literal '~' directory was created inside the judged tree: the child "
        "has no home variable, so expanduser did not expand"
    )


# --------------------------------------------------------------------------- #
# the wall-time bound                                                          #
# --------------------------------------------------------------------------- #
def test_the_pytest_timeout_is_an_upper_bound(tmp_path):
    """The gate returns at its bound even when a descendant outlives it.

    MEASURED against the pre-fix implementation: 45.6s wall against a declared
    3.0s bound, because the candidate disabled pytest's capture and its
    descendant inherited the evaluator's pipe.
    """
    root = _tree(tmp_path / "candidate", "test_hang.py", SPAWNS_SURVIVOR)

    started = time.monotonic()
    report = ignition_checks.pytest_check(
        root, ["tests/test_hang.py"], timeout_s=3.0)
    elapsed = time.monotonic() - started

    assert report.passed is False
    assert report.detail["returncode"] is None
    assert elapsed < 20.0, (
        f"pytest_check took {elapsed:.1f}s to honour a 3.0s bound; a descendant "
        "is still holding this process inside communicate()"
    )


# --------------------------------------------------------------------------- #
# the transcript contract                                                      #
# --------------------------------------------------------------------------- #
def test_a_normal_suite_still_passes_and_still_reports(tmp_path):
    """The bound and the allowlist did not break the ordinary green path."""
    root = _tree(
        tmp_path / "candidate", "test_ok.py", "def test_ok():\n    assert True\n")

    report = ignition_checks.pytest_check(root, ["tests/test_ok.py"], timeout_s=120.0)

    assert report.passed is True
    assert report.detail["returncode"] == 0
    assert report.evaluator == "ignition-pytest"
    assert "1 passed" in report.output


def test_a_failing_suite_still_reports_its_failure(tmp_path):
    """A scrubbed environment must not turn a red suite into an unreadable one."""
    root = _tree(
        tmp_path / "candidate", "test_bad.py",
        "def test_bad():\n    assert 1 == 2, 'the candidate is wrong'\n")

    report = ignition_checks.pytest_check(root, ["tests/test_bad.py"], timeout_s=120.0)

    assert report.passed is False
    assert report.detail["returncode"] != 0
    assert "the candidate is wrong" in report.output


def test_stderr_reaches_the_transcript(tmp_path):
    """MEASURED gap: dropping ``stderr=STDOUT`` was caught by nothing.

    pytest's own collection errors and interpreter-level failures arrive on
    stderr. A transcript that silently loses them is a receipt that cannot say
    why a candidate was refused.
    """
    root = _tree(
        tmp_path / "candidate", "test_boom.py",
        "import sys\n\n\ndef test_boom():\n"
        "    sys.stderr.write('STDERR MARKER 8817\\n')\n"
        "    sys.stderr.flush()\n"
        "    raise SystemExit(3)\n")

    report = ignition_checks.pytest_check(root, ["tests/test_boom.py"], timeout_s=120.0)

    assert "STDERR MARKER 8817" in report.output


def test_the_child_cannot_block_on_inherited_stdin(tmp_path):
    """MEASURED gap: dropping ``stdin=DEVNULL`` was caught by nothing.

    A candidate reading stdin must get EOF, not the operator's terminal.
    """
    root = _tree(
        tmp_path / "candidate", "test_stdin.py",
        "import os\n\n\ndef test_stdin(capfd):\n"
        "    with capfd.disabled():\n"
        "        assert os.read(0, 16) == b''\n")

    started = time.monotonic()
    report = ignition_checks.pytest_check(
        root, ["tests/test_stdin.py"], timeout_s=20.0)
    elapsed = time.monotonic() - started

    assert report.passed, report.output[-2000:]
    assert elapsed < 15.0


def test_a_timed_out_suite_names_its_bound(tmp_path):
    """What a killed run CAN promise, which is less than it first claimed.

    An earlier version of this test was called
    ``test_a_timed_out_suite_still_carries_its_output`` and asserted only
    ``"timed out" in report.output`` -- which it would have passed with the
    transcript dropped entirely. MEASURED: pytest buffers test output in its
    own capture and writes it at report time, so a killed run has flushed
    nothing and 'CANDIDATE SPOKE' does NOT survive. Output written outside
    pytest's capture does survive; that half is asserted here.
    """
    root = _tree(
        tmp_path / "candidate", "test_slow.py",
        "import sys\nimport time\n\n\ndef test_slow(capfd):\n"
        "    with capfd.disabled():\n"
        "        sys.stdout.write('UNCAPTURED MARKER 4471\\n')\n"
        "        sys.stdout.flush()\n"
        "        time.sleep(45)\n")

    report = ignition_checks.pytest_check(
        root, ["tests/test_slow.py"], timeout_s=3.0)

    assert report.passed is False
    assert report.detail["returncode"] is None
    assert "timed out" in report.output
    assert "UNCAPTURED MARKER 4471" in report.output, (
        "output the suite had already flushed was lost with the transcript"
    )
    assert report.detail["argv"], "the refusal must still name what it ran"


# --------------------------------------------------------------------------- #
# the tripwire that catches what isolation does not prevent                    #
# --------------------------------------------------------------------------- #
def _bundle_digest(root: Path) -> str:
    return ignition_bundle.evaluator_bundle(
        root,
        criterion_path=ignition_checks.CONFORMANCE_TEST_PATH,
        criterion_source=ignition_checks.CONFORMANCE_TEST_SOURCE,
        node_ids={"code-type": ignition_checks.CODE_TYPE_NODE_IDS},
        fixture_root=root,
    )["digest"]


@pytest.fixture()
def evaluator_tree(tmp_path):
    """A copy of every module the bundle actually hashes."""
    real_root = Path(ignition_bundle.__file__).resolve().parents[2]
    fake_root = tmp_path / "repo"
    for rel in ignition_bundle.import_closure(
            real_root, ignition_bundle.EVALUATOR_MODULES):
        target = fake_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(real_root / rel, target)
    return fake_root


@pytest.mark.parametrize("rel", [
    "daedalus/ignition/checks.py",       # a declared evaluator root
    "daedalus/spine/envelope.py",        # reached only through the closure
    "daedalus/twin/reference_compiler.py",
])
def test_the_bundle_digest_moves_when_any_judging_module_changes(evaluator_tree, rel):
    """The tripwire covers the import CLOSURE, not just the six roots.

    THIS TEST REPLACES A FALSE ONE. Its predecessor,
    ``test_the_bundle_does_not_cover_what_the_evaluators_import``, asserted
    ``"daedalus/spine/envelope.py" not in EVALUATOR_MODULES`` and
    ``len(EVALUATOR_MODULES) == 6`` -- both true, and neither of them the
    proposition its name, docstring and work packet claimed. It documented a
    gap that does not exist: ``bundle.import_closure`` walks every in-repo
    module reachable from the six roots (MEASURED: 198 of them, including
    ``envelope.py``) and ``bundle_digest_from_body`` folds that digest into the
    identity. A green test asserting a false fact is what ``AGENTS.md`` calls
    an unverifiable claim.
    """
    before = _bundle_digest(evaluator_tree)

    target = evaluator_tree / rel
    target.write_text(
        target.read_text(encoding="utf-8") + "\n# candidate was here\n",
        encoding="utf-8")

    assert _bundle_digest(evaluator_tree) != before, (
        f"{rel} changed and the bundle digest did not move; the receipt's "
        "'an evaluator changed while the slice was running' blocker would "
        "never fire for it"
    )


def test_the_closure_reaches_past_the_declared_roots():
    """The closure is the identity, and it is much larger than the root list."""
    real_root = Path(ignition_bundle.__file__).resolve().parents[2]
    closure = ignition_bundle.import_closure(
        real_root, ignition_bundle.EVALUATOR_MODULES)

    assert len(ignition_bundle.EVALUATOR_MODULES) == 6
    assert len(closure) > 100, len(closure)
    assert "daedalus/spine/envelope.py" in closure
    for rel in ignition_bundle.EVALUATOR_MODULES:
        assert rel in closure
