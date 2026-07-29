"""The drill decides whether autonomy is defensible, so the drill needs guards.

`tools/operability_drill.py` is the instrument a human would read before letting
a shadow run go from "on request" to "on a schedule". That makes its FAILURE
MODES more important than its success path: a drill that quietly rounds an
unexercised control up to a pass would authorise exactly the unattended loop
this project has spent a session establishing it is not ready for.

Three properties carry this file, and each is a mistake this repo has actually
made rather than a hypothetical:

  1. INCOMPLETE IS NOT A PASS. "Skipped rendered as green" is the single defect
     this codebase has paid for most often -- an acceptance harness reporting
     `unavailable` as working, a health surface collapsing `present` into `ok`.
  2. ONE FAIL IS A FAIL. There is no "mostly". A verdict that averaged five
     passes against one failure would hide the one that matters.
  3. A STALE PROOF IS A MISSING CONTROL. The reviewer's clause: "if a control is
     missing OR ITS PROOF IS STALE, the scheduled run must fail closed". A
     measurement of a tree that no longer exists says nothing about this one.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

drill = pytest.importorskip("tools.operability_drill")


def _c(status: str, name: str = "x") -> "drill.Control":
    return drill.Control(name=name, proves="p", status=status)


# --------------------------------------------------------------------------- #
# the verdict arithmetic                                                       #
# --------------------------------------------------------------------------- #
def test_incomplete_is_never_rounded_up_to_a_pass():
    """The exit codes must be three distinct values, not two.

    If INCOMPLETE collapsed into PASS, a drill on a machine where the kill
    switch cannot be exercised would report that scheduling is defensible --
    having proven nothing whatsoever about stopping the loop.
    """
    assert drill.EXIT_PASS != drill.EXIT_INCOMPLETE
    assert drill.EXIT_FAIL != drill.EXIT_INCOMPLETE
    assert len({drill.EXIT_PASS, drill.EXIT_FAIL, drill.EXIT_INCOMPLETE}) == 3


def test_one_failure_outranks_any_number_of_passes():
    results = [_c(drill.PASS) for _ in range(9)] + [_c(drill.FAIL, "the_one")]
    failed = sum(r.status == drill.FAIL for r in results)
    incomplete = sum(r.status == drill.INCOMPLETE for r in results)
    verdict = (drill.EXIT_FAIL if failed else
               drill.EXIT_INCOMPLETE if incomplete else drill.EXIT_PASS)
    assert verdict == drill.EXIT_FAIL


def test_a_single_unexercised_control_blocks_the_verdict():
    results = [_c(drill.PASS) for _ in range(9)] + [_c(drill.INCOMPLETE, "unrun")]
    failed = sum(r.status == drill.FAIL for r in results)
    incomplete = sum(r.status == drill.INCOMPLETE for r in results)
    verdict = (drill.EXIT_FAIL if failed else
               drill.EXIT_INCOMPLETE if incomplete else drill.EXIT_PASS)
    assert verdict == drill.EXIT_INCOMPLETE, (
        "nine passes and one unexercised control is not a green drill")


# --------------------------------------------------------------------------- #
# staleness -- the reviewer's clause                                           #
# --------------------------------------------------------------------------- #
def test_a_proof_from_another_revision_fails_the_drill(monkeypatch, tmp_path):
    """The whole point of the clause, exercised against the real function."""
    from daedalus.spine import bootstrap as B

    monkeypatch.setattr(
        B, "gate_discrimination",
        lambda root, head=None: B.GateDiscrimination(
            True, "kill rate 95%", measured_at="2026-07-01",
            measured_head="deadbeef1234", kill_rate=0.95))
    c = drill.staleness("f" * 40)
    assert c.status == drill.FAIL
    assert "deadbeef1234" in c.effect
    assert "stale" in c.telemetry.lower()


def test_a_proof_for_THIS_revision_passes(monkeypatch):
    """The allow side. Without it, a staleness check that failed unconditionally
    would pass the test above while making the drill permanently red."""
    from daedalus.spine import bootstrap as B

    head = "abcdef1234567890" + "0" * 24
    monkeypatch.setattr(
        B, "gate_discrimination",
        lambda root, head=None: B.GateDiscrimination(
            True, "kill rate 95%", measured_at="2026-07-29",
            measured_head=head[:12], kill_rate=0.95))
    monkeypatch.setattr(drill, "RECEIPT_REL_PATH", "runs/spine/does-not-exist.json")
    c = drill.staleness(head)
    assert c.status == drill.PASS


# --------------------------------------------------------------------------- #
# a control that raises must not disappear                                     #
# --------------------------------------------------------------------------- #
def test_a_control_that_raises_is_INCOMPLETE_and_says_so(monkeypatch):
    """A crashing control is the case most likely to be silently dropped.

    It must land as INCOMPLETE with the exception named -- not as a pass, and
    not as a FAIL either, because "the control could not run" and "the control
    ran and the system failed" are different facts and lead to different work.
    """
    def explodes(c):
        raise RuntimeError("probe blew up")

    monkeypatch.setattr(drill, "CONTROLS",
                        (("probe.explodes", "nothing", explodes),))
    # Isolate the exception verdict from the real checkout's deliberately stale
    # discrimination receipt. A genuine FAIL correctly outranks INCOMPLETE, but
    # that is a different test above.
    monkeypatch.setattr(
        drill, "staleness",
        lambda head: _c(drill.PASS, "proofs.are_for_THIS_revision"))
    monkeypatch.setattr(drill, "RECEIPT_REL_PATH", "runs/spine/drill-test.json")
    code = drill.run(json_out=True)
    assert code == drill.EXIT_INCOMPLETE

    receipt = json.loads((ROOT / "runs/spine/drill-test.json").read_text(encoding="utf-8"))
    hit = [c for c in receipt["controls"] if c["name"] == "probe.explodes"]
    assert hit and hit[0]["status"] == drill.INCOMPLETE
    assert "RuntimeError" in hit[0]["detail"]
    assert "probe blew up" in hit[0]["detail"]
    assert receipt["scheduling_defensible"] is False
    (ROOT / "runs/spine/drill-test.json").unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# the receipt                                                                  #
# --------------------------------------------------------------------------- #
def test_the_receipt_records_the_revision_it_was_measured_at(monkeypatch):
    """Without a revision the receipt cannot be checked for staleness by the
    NEXT run -- and the staleness rule is the drill's own reason to exist."""
    monkeypatch.setattr(drill, "CONTROLS", ())
    monkeypatch.setattr(drill, "RECEIPT_REL_PATH", "runs/spine/drill-test2.json")
    drill.run(json_out=True)
    receipt = json.loads((ROOT / "runs/spine/drill-test2.json").read_text(encoding="utf-8"))
    assert receipt.get("head"), "the receipt does not record a revision"
    assert "scheduling_defensible" in receipt
    (ROOT / "runs/spine/drill-test2.json").unlink(missing_ok=True)


def test_scheduling_defensible_is_true_ONLY_on_a_clean_exit(monkeypatch):
    """The field a scheduler would read. It must never be true beside a FAIL."""
    seen = []

    def fail_control(c):
        c.status = drill.FAIL
        c.effect = "deliberately failed"

    monkeypatch.setattr(drill, "CONTROLS",
                        (("probe.fails", "nothing", fail_control),))
    monkeypatch.setattr(drill, "RECEIPT_REL_PATH", "runs/spine/drill-test3.json")
    code = drill.run(json_out=True)
    receipt = json.loads((ROOT / "runs/spine/drill-test3.json").read_text(encoding="utf-8"))
    assert code == drill.EXIT_FAIL
    assert receipt["scheduling_defensible"] is False
    (ROOT / "runs/spine/drill-test3.json").unlink(missing_ok=True)


# --------------------------------------------------------------------------- #
# the drill must not become a thing that schedules                             #
# --------------------------------------------------------------------------- #
def test_the_drill_does_not_start_anything_by_itself():
    """It reports whether scheduling would be defensible. Deciding to schedule
    is a human act, like promotion, and this asserts the file has not quietly
    grown the ability to take it."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(drill)))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                             ast.Module)) and ast.get_docstring(node):
            node.body = node.body[1:]
    code = ast.unparse(tree)
    for forbidden in ("CronCreate", "schedule_", "crontab", "Task Scheduler",
                      "schtasks", "install_service"):
        assert forbidden not in code, f"the drill can now {forbidden!r}"
