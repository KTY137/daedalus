"""The behavior probe must not execute candidate code in the verifier process.

WHY THIS FILE EXISTS
--------------------
``docs/work-packets/G1_ACTIVATION_CHECKLIST.md`` §2.3 named this on 2026-08-17
and it was never closed: the probe ``importlib.import_module``d the candidate
package INTO the process that holds the EffectLease, assembles the
EvidencePacket and writes the receipt. Master plan invariant 3 (Isolation) says
candidate execution "cannot modify its evaluator, policy, evidence, budget
ledger, or promotion mechanism", and ``AGENTS.md`` lists "candidate access to
its evaluator" as a release-blocking defect.

THE DISCRIMINATING TEST is ``test_candidate_import_does_not_run_in_this_process``:
the synthetic candidate records ``os.getpid()`` at import time, and the verifier
asserts that the recorded pid is not its own. Against the pre-2026-09-03
in-process implementation the two pids are equal and it fails; there is no way
to satisfy it without actually leaving this interpreter.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from daedalus.ignition.runner import IgnitionError, candidate_behavior

#: Records the importing process at import time, then supplies the tiny API the
#: probe calls. The pid file is written beside the module so the test needs no
#: environment variable to find it -- ``-I``/``-E`` on the child would strip a
#: ``PYTHON*`` one, and a plain one would still be an extra moving part.
CANDIDATE_INIT = '''\
import os
import pathlib

pathlib.Path(__file__).resolve().parent.joinpath("import_pid.txt").write_text(
    str(os.getpid()), encoding="utf-8")


class Event:
    def __init__(self, id, bias_voltage):
        self.id = id
        self.bias_voltage = bias_voltage


def parse_event(row):
    return Event(id=row["id"], bias_voltage=float(row["bias_voltage"]))
'''

#: A candidate whose import blows up. The probe must surface this as a refusal,
#: never as an absent or defaulted measurement.
CANDIDATE_RAISES = '''\
raise RuntimeError("candidate exploded at import")
'''


def _candidate(root: Path, source: str = CANDIDATE_INIT) -> Path:
    package = root / "src" / "ignition_app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(source, encoding="utf-8")
    return root


def test_candidate_import_does_not_run_in_this_process(tmp_path):
    """The pid that imported the candidate is NOT the verifier's pid."""
    root = _candidate(tmp_path / "candidate")

    candidate_behavior(root)

    recorded = (root / "src" / "ignition_app" / "import_pid.txt").read_text(
        encoding="utf-8").strip()
    assert recorded, "the candidate package was never imported at all"
    assert int(recorded) != os.getpid(), (
        "candidate code executed inside the verifier process: the module that "
        "produces the behavior evidence is the same process that holds the "
        "lease and writes the receipt (master plan invariant 3)"
    )


def test_probe_still_reports_the_rename_contract(tmp_path):
    """The measurement the receipt depends on is unchanged."""
    root = _candidate(tmp_path / "candidate")

    observed = dict(candidate_behavior(root))

    assert observed["type"] == "Event"
    assert observed["id"] == "1"
    assert observed["bias_voltage"] == 125.0
    assert observed["has_old_voltage_attribute"] is False


def test_probe_declares_how_it_isolated(tmp_path):
    """The evidence names the isolation it actually got, so it cannot overstate.

    A plain child interpreter is process isolation, NOT the capability-bounded
    containment ``daedalus.spine.containment.spawn_contained`` provides (which
    is win32-only and gives the child no stdio). Recording the mode keeps the
    receipt honest about which one ran.
    """
    root = _candidate(tmp_path / "candidate")

    observed = dict(candidate_behavior(root))

    assert observed["isolation"] == "subprocess"


def test_probe_output_is_stable_across_runs(tmp_path):
    """No pid, no timing, no path in the measurement -- replay depends on it.

    ``gate1`` digests this mapping into the ``ignition-behavior`` evidence item
    and the receipt compares two runs' check reports. A field that moves per
    run would make every Gate-1 run report itself as a failed replay.
    """
    root = _candidate(tmp_path / "candidate")

    first = json.dumps(dict(candidate_behavior(root)), sort_keys=True)
    second = json.dumps(dict(candidate_behavior(root)), sort_keys=True)

    assert first == second


def test_a_candidate_that_raises_is_a_refusal(tmp_path):
    """A broken candidate refuses loudly and carries its cause."""
    root = _candidate(tmp_path / "candidate", CANDIDATE_RAISES)

    with pytest.raises(IgnitionError) as excinfo:
        candidate_behavior(root)

    assert "candidate exploded at import" in str(excinfo.value)


def test_a_missing_candidate_package_is_a_refusal(tmp_path):
    """No silent fall-back to an in-process import when the child cannot run."""
    root = tmp_path / "candidate"
    (root / "src").mkdir(parents=True)

    with pytest.raises(IgnitionError):
        candidate_behavior(root)
