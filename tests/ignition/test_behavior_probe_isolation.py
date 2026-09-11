"""The behavior probe must not execute candidate code in the verifier process,
and must not accept an answer the candidate wrote.

WHY THIS FILE EXISTS
--------------------
``docs/work-packets/G1_ACTIVATION_CHECKLIST.md`` §2.3 named the first half on
2026-08-17 and it was never closed: the probe ``importlib.import_module``d the
candidate package INTO the process that holds the EffectLease, assembles the
EvidencePacket and writes the receipt. Master plan invariant 3 says candidate
execution "cannot modify its evaluator, policy, evidence, budget ledger, or
promotion mechanism", and ``AGENTS.md`` lists "candidate access to its
evaluator" as a release-blocking defect.

THE SECOND HALF came from the adversarial review of `3b531d44`, which moved the
process boundary but left the TRUST boundary where it was: the result travelled
on the candidate's own stdout, so a candidate with no ``parse_event`` and no
``Event`` class could print the expected JSON, call ``os._exit(0)``, and have
its forged verdict enter the EvidencePacket as ``assurance="deterministic"``.
That review also found three mutations no test caught -- dropping ``-I``,
dropping the shape guard, dropping ``timeout=`` -- and each has a test here now.

THE DISCRIMINATING TEST for the process boundary is
``test_candidate_import_does_not_run_in_this_process``: the synthetic candidate
records ``os.getpid()`` at import, and the verifier asserts the recorded pid is
not its own. There is no way to satisfy it without leaving this interpreter.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from daedalus.ignition import runner
from daedalus.ignition.runner import IgnitionError, candidate_behavior

#: Records the importing process at import time, then supplies the tiny API the
#: probe calls. The pid file is written beside the module so the test needs no
#: environment variable to find it.
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

#: THE FORGERY THE STDOUT PROTOCOL ALLOWED. No Event class, no parse_event --
#: it prints the answer and ends the process before the probe can disagree.
CANDIDATE_FORGES_ON_STDOUT = '''\
import json, os, sys

json.dump({
    "type": "Event",
    "id": "1",
    "bias_voltage": 125.0,
    "has_old_voltage_attribute": False,
}, sys.stdout)
sys.stdout.flush()
os._exit(0)
'''

#: The same forgery aimed at the result FILE, whose path the candidate can read
#: out of ``sys.argv``. What it cannot read is the nonce.
CANDIDATE_FORGES_RESULT_FILE = '''\
import json, os, sys

with open(sys.argv[2], "w", encoding="utf-8") as handle:
    json.dump({"nonce": "forged", "result": {
        "type": "Event",
        "id": "1",
        "bias_voltage": 125.0,
        "has_old_voltage_attribute": False,
    }}, handle)
os._exit(0)
'''

#: Records the environment the child was handed, then answers normally.
CANDIDATE_RECORDS_ENV = '''\
import json
import os
import pathlib

pathlib.Path(__file__).resolve().parent.joinpath("env.json").write_text(
    json.dumps(dict(os.environ)), encoding="utf-8")


class Event:
    def __init__(self, id, bias_voltage):
        self.id = id
        self.bias_voltage = bias_voltage


def parse_event(row):
    return Event(id=row["id"], bias_voltage=float(row["bias_voltage"]))
'''

#: Spawns a descendant that outlives the probe, then hangs itself. Under the
#: stdout-PIPE protocol the grandchild kept the PARENT inside communicate()
#: long past the declared timeout (measured 25.1s against a 2.0s bound).
CANDIDATE_SPAWNS_SURVIVOR = '''\
import subprocess, sys, time

subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
time.sleep(60)
'''


def _candidate(root: Path, source: str = CANDIDATE_INIT) -> Path:
    package = root / "src" / "ignition_app"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(source, encoding="utf-8")
    return root


# --------------------------------------------------------------------------- #
# the process boundary                                                         #
# --------------------------------------------------------------------------- #
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

    A child interpreter at the operator's own privilege level is process
    isolation, NOT the capability-bounded containment
    ``daedalus.spine.containment.spawn_contained`` provides (win32-only, no
    stdio). Recording the mode keeps the receipt honest about which one ran.
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


# --------------------------------------------------------------------------- #
# the trust boundary: the candidate does not author the answer                 #
# --------------------------------------------------------------------------- #
def test_a_candidate_cannot_forge_the_verdict_on_stdout(tmp_path):
    """Printing the expected JSON and exiting 0 is a refusal, not a pass.

    This candidate has no ``Event`` class and no ``parse_event``. Under the
    pre-review protocol it produced ``behavior_ok is True``.
    """
    root = _candidate(tmp_path / "candidate", CANDIDATE_FORGES_ON_STDOUT)

    with pytest.raises(IgnitionError) as excinfo:
        candidate_behavior(root)

    assert "without writing a result" in str(excinfo.value)


def test_a_candidate_cannot_forge_the_result_file(tmp_path):
    """The result file is reachable from ``sys.argv``; the nonce is not."""
    root = _candidate(tmp_path / "candidate", CANDIDATE_FORGES_RESULT_FILE)

    with pytest.raises(IgnitionError) as excinfo:
        candidate_behavior(root)

    assert "nonce" in str(excinfo.value)


def test_the_probe_child_does_not_inherit_the_verifier_environment(monkeypatch, tmp_path):
    """A credential in this process is not handed to the candidate.

    ``-I`` makes the INTERPRETER ignore ``PYTHON*``; it does not scrub
    ``os.environ`` for the candidate, and two lines of candidate code used to
    put the inherited ``PYTHONPATH`` back on ``sys.path``.
    """
    monkeypatch.setenv("DAEDALUS_TEST_FAKE_SECRET", "sk-verifier-secret-do-not-leak")
    monkeypatch.setenv("PYTHONPATH", "c:/somewhere/that/holds/the/evaluator")
    root = _candidate(tmp_path / "candidate", CANDIDATE_RECORDS_ENV)

    candidate_behavior(root)

    seen = json.loads(
        (root / "src" / "ignition_app" / "env.json").read_text(encoding="utf-8"))
    assert "DAEDALUS_TEST_FAKE_SECRET" not in seen
    assert "PYTHONPATH" not in seen


# --------------------------------------------------------------------------- #
# refusals                                                                     #
# --------------------------------------------------------------------------- #
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


@pytest.mark.parametrize("payload, expected", [
    ("not an object at all", "not an object"),
    (["a", "list"], "not an object"),
    (42, "not an object"),
])
def test_a_non_object_result_is_a_refusal(payload, expected):
    """Mutation M4: removing this guard was caught by nothing."""
    with pytest.raises(IgnitionError) as excinfo:
        runner._validated_behavior(payload, nonce="n")

    assert expected in str(excinfo.value)


def _wrap(result: dict) -> dict:
    return {"nonce": "n", "result": result}


GOOD_RESULT = {
    "type": "Event",
    "id": "1",
    "bias_voltage": 125.0,
    "has_old_voltage_attribute": False,
}


@pytest.mark.parametrize("mutate, expected", [
    (lambda r: r.pop("has_old_voltage_attribute"), "missing"),
    (lambda r: r.pop("bias_voltage"), "missing"),
    (lambda r: r.update(bias_voltage="125.0"), "bias_voltage"),
    (lambda r: r.update(bias_voltage=True), "bool"),
    (lambda r: r.update(has_old_voltage_attribute="no"), "has_old_voltage_attribute"),
    (lambda r: r.update(type=None), "type"),
])
def test_a_malformed_result_shape_is_a_refusal(mutate, expected):
    """An empty object used to escape as a bare KeyError, not an IgnitionError.

    ``run_voltage_ignition`` indexes these keys directly, so a shape the probe
    accepted but the caller could not use was a refusal-contract hole.
    """
    result = dict(GOOD_RESULT)
    mutate(result)

    with pytest.raises(IgnitionError) as excinfo:
        runner._validated_behavior(_wrap(result), nonce="n")

    assert expected in str(excinfo.value)


def test_a_result_without_the_nonce_is_a_refusal():
    with pytest.raises(IgnitionError) as excinfo:
        runner._validated_behavior({"result": dict(GOOD_RESULT)}, nonce="n")

    assert "nonce" in str(excinfo.value)


def test_a_well_formed_result_is_accepted():
    """The refusals above are not simply refusing everything."""
    assert runner._validated_behavior(
        _wrap(dict(GOOD_RESULT)), nonce="n") == GOOD_RESULT


# --------------------------------------------------------------------------- #
# the spawn contract itself                                                    #
# --------------------------------------------------------------------------- #
@pytest.fixture()
def spawn_calls(monkeypatch):
    """Record how the probe spawns, while still really spawning."""
    calls: list[tuple[list, dict]] = []
    real = subprocess.run

    def recording(*args, **kwargs):
        calls.append((list(args[0]), dict(kwargs)))
        return real(*args, **kwargs)

    monkeypatch.setattr(runner.subprocess, "run", recording)
    return calls


def test_probe_argv_carries_the_isolated_flag(spawn_calls, tmp_path):
    """Mutation M2: dropping ``-I`` was caught by nothing in the repository.

    ``-I`` is the whole capability-bounding story the docstring tells about
    ``sys.path``; a silent removal must not stay silent.
    """
    candidate_behavior(_candidate(tmp_path / "candidate"))

    argv, _ = spawn_calls[0]
    assert "-I" in argv, f"the probe spawned without isolated mode: {argv}"
    assert argv[0] == runner.sys.executable


def test_probe_call_is_bounded_by_a_timeout(spawn_calls, tmp_path):
    """Mutation M7: removing ``timeout=`` was caught by nothing."""
    candidate_behavior(_candidate(tmp_path / "candidate"))

    _, kwargs = spawn_calls[0]
    assert kwargs.get("timeout") == runner.BEHAVIOR_PROBE_TIMEOUT_S


def test_probe_does_not_pipe_the_child_output(spawn_calls, tmp_path):
    """A descendant holding a PIPE is what broke the timeout bound.

    stdout is discarded and stderr goes to a real file, so nothing this process
    must drain is inherited by a grandchild.
    """
    candidate_behavior(_candidate(tmp_path / "candidate"))

    _, kwargs = spawn_calls[0]
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is not subprocess.PIPE
    assert "capture_output" not in kwargs


def test_the_declared_timeout_is_an_upper_bound(monkeypatch, tmp_path):
    """The probe returns at its bound even when a descendant outlives it.

    MEASURED against the stdout-PIPE protocol: a grandchild held the parent
    25.1s against a declared 2.0s bound, while the refusal still said "within
    2s". The grandchild here sleeps 60s; a parent that waits for it fails.
    """
    monkeypatch.setattr(runner, "BEHAVIOR_PROBE_TIMEOUT_S", 3.0)
    root = _candidate(tmp_path / "candidate", CANDIDATE_SPAWNS_SURVIVOR)

    started = time.monotonic()
    with pytest.raises(IgnitionError) as excinfo:
        candidate_behavior(root)
    elapsed = time.monotonic() - started

    assert "did not answer within" in str(excinfo.value)
    assert elapsed < 20.0, (
        f"the probe took {elapsed:.1f}s to honour a 3.0s bound; a descendant "
        "is still holding this process"
    )
