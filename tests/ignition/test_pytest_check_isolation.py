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
that negative result is kept in this docstring rather than deleted: an ordinary
``subprocess.Popen`` inside a pytest test inherits pytest's own capture file,
not the evaluator's pipe, so it does not reach the defect. The candidate writes
the test file, so it can simply ask pytest for ``capfd`` and turn capture off:

    declared timeout: 3.0s
    actual wall     : 45.6s
    VERDICT         : DEFEATED - not an upper bound

``SPAWNS_SURVIVOR`` below is that measured version.

WHAT THESE TESTS DO NOT CLAIM. Closing the *write* capability -- the review
wrote a file into the evaluator's own package from inside this child -- needs
containment or filesystem permissions, not a flag. It stays open, and
``test_the_evaluator_bundle_notices_a_changed_evaluator`` pins the tripwire
that catches it after the fact instead.
"""
from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

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


def _tree(root: Path, name: str, source: str) -> Path:
    tests = root / "tests"
    tests.mkdir(parents=True)
    (tests / name).write_text(source, encoding="utf-8")
    return root


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


def test_a_timed_out_suite_still_carries_its_output(tmp_path):
    """A refusal that says nothing is a refusal nobody can act on."""
    root = _tree(
        tmp_path / "candidate", "test_slow.py",
        "import time\n\n\ndef test_slow():\n    print('CANDIDATE SPOKE')\n"
        "    time.sleep(45)\n")

    report = ignition_checks.pytest_check(
        root, ["tests/test_slow.py"], timeout_s=3.0)

    assert report.passed is False
    assert report.detail["returncode"] is None
    assert "timed out" in report.output


def test_the_evaluator_bundle_notices_a_changed_evaluator(tmp_path):
    """The tripwire that catches what isolation does not prevent.

    ``gate1`` re-reads the bundle after the run and turns a difference into a
    blocker ("this receipt cannot say what judged"). That is detection, not
    prevention -- and it only covers the modules
    :data:`daedalus.ignition.bundle.EVALUATOR_MODULES` names explicitly, not
    everything they import. This pins the half that exists.
    """
    real_root = Path(ignition_bundle.__file__).resolve().parents[2]
    fake_root = tmp_path / "repo"
    for rel in ignition_bundle.EVALUATOR_MODULES:
        target = fake_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(real_root / rel, target)

    before = ignition_bundle.evaluator_bundle(
        fake_root,
        criterion_path=ignition_checks.CONFORMANCE_TEST_PATH,
        criterion_source=ignition_checks.CONFORMANCE_TEST_SOURCE,
        node_ids={"code-type": ignition_checks.CODE_TYPE_NODE_IDS},
        fixture_root=fake_root,
    )["digest"]

    target = fake_root / "daedalus/ignition/checks.py"
    target.write_text(
        target.read_text(encoding="utf-8") + "\n# candidate was here\n",
        encoding="utf-8")

    after = ignition_bundle.evaluator_bundle(
        fake_root,
        criterion_path=ignition_checks.CONFORMANCE_TEST_PATH,
        criterion_source=ignition_checks.CONFORMANCE_TEST_SOURCE,
        node_ids={"code-type": ignition_checks.CODE_TYPE_NODE_IDS},
        fixture_root=fake_root,
    )["digest"]

    assert before != after, (
        "an evaluator module changed and the bundle digest did not move; the "
        "receipt's 'an evaluator changed while the slice was running' blocker "
        "would never fire"
    )


def test_the_bundle_does_not_cover_what_the_evaluators_import():
    """The tripwire's honest limit, pinned so it cannot be forgotten.

    ``EVALUATOR_MODULES`` is an explicit six-file list. Those six import many
    others -- ``daedalus/spine/envelope.py`` supplies ``canonical_sha`` to both
    ``checks`` and ``runner`` -- and a change there moves no bundle digest.
    This test EXPECTS the gap; it exists so that closing it is a deliberate
    decision with a failing test, not a silent one.
    """
    assert "daedalus/spine/envelope.py" not in ignition_bundle.EVALUATOR_MODULES
    assert len(ignition_bundle.EVALUATOR_MODULES) == 6
