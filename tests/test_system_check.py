# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The acceptance harness's own contract.

`tools/system_check.py` is the thing that answers "does the system work". It is
therefore exactly the kind of file that must not be allowed to drift into
answering "yes" by construction. Two properties carry this file:

THE EXIT CODE IS THE VERDICT. 0 means every CORE check ran and passed. 1 means
something FAILED. 2 means a CORE property could not be checked, so the run
proves nothing about it. The first version of the harness counted UNAVAILABLE
separately and still exited 0 -- which made its own three-outcome contract a
paragraph rather than a control, and would have reported "15 pass" on a run
where a core safety property was never examined.

EVERY CHECK DECLARES WHAT IT PROVES. A check without a stated property is a
smoke test wearing a verification's clothes.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1] / "tools"
sys.path.insert(0, str(TOOLS))

sc = pytest.importorskip("system_check")


def _res(name, outcome, core=True):
    return sc.Result(name=name, outcome=outcome, core=core)


# --------------------------------------------------------------------------- #
# the exit contract                                                            #
# --------------------------------------------------------------------------- #
def test_all_pass_is_the_only_zero():
    assert sc.verdict([_res("a", sc.PASS), _res("b", sc.PASS)]) == sc.EXIT_OK


def test_any_failure_is_one():
    assert sc.verdict([_res("a", sc.PASS), _res("b", sc.FAIL)]) == sc.EXIT_FAILED


def test_unavailable_on_a_CORE_check_is_incomplete_not_success():
    # The defect this pins: a core property that could not be examined must
    # never leave the run looking green.
    got = sc.verdict([_res("a", sc.PASS), _res("b", sc.UNAVAILABLE, core=True)])
    assert got == sc.EXIT_INCOMPLETE
    assert got != sc.EXIT_OK


def test_unavailable_on_an_OPTIONAL_check_does_not_block():
    assert sc.verdict([_res("a", sc.PASS),
                       _res("b", sc.UNAVAILABLE, core=False)]) == sc.EXIT_OK


def test_failure_outranks_incomplete():
    # If something is broken AND something else could not be checked, the
    # broken thing is the headline.
    assert sc.verdict([_res("a", sc.FAIL),
                       _res("b", sc.UNAVAILABLE, core=True)]) == sc.EXIT_FAILED


def test_the_three_outcomes_are_distinct():
    assert len({sc.PASS, sc.FAIL, sc.UNAVAILABLE}) == 3
    assert len({sc.EXIT_OK, sc.EXIT_FAILED, sc.EXIT_INCOMPLETE}) == 3


# --------------------------------------------------------------------------- #
# the checks themselves                                                        #
# --------------------------------------------------------------------------- #
def test_every_check_declares_what_it_proves():
    naked = [c["name"] for c in sc.CHECKS if not str(c.get("proves") or "").strip()]
    assert not naked, f"checks with no stated property: {naked}"


def test_every_check_declares_a_stage_and_core_flag():
    bad = [c["name"] for c in sc.CHECKS
           if not str(c.get("stage") or "").strip() or not isinstance(c.get("core"), bool)]
    assert not bad, bad


def test_check_names_are_unique():
    names = [c["name"] for c in sc.CHECKS]
    assert len(names) == len(set(names)), "duplicate check names"


def test_the_spine_and_safety_properties_are_all_covered():
    """The list a reader would expect from "does the system work".

    Named explicitly so that deleting a check is a visible decision rather than
    a quiet reduction in what the run claims.
    """
    names = {c["name"] for c in sc.CHECKS}
    for required in (
        "spine.intent_is_recorded_BEFORE_the_effect",
        "spine.attempt_leaves_the_primary_untouched",
        "spine.circle_closes",
        "safety.remote_ollama_is_refused",
        "safety.picker_cannot_apply",
        "safety.room_prompt_gates_by_speaker",
        "safety.bus_chain_detects_a_break",
        "map.drift_gate_is_green",
        "picker.ranks_with_evidence",
    ):
        assert required in names, f"acceptance check disappeared: {required}"


def test_a_check_that_raises_is_a_FAIL_not_a_skip():
    """A crashing check must never be counted as 'could not look'."""
    marker = "acceptance.deliberate_boom"
    sc.CHECKS.append({"name": marker, "stage": "test", "proves": "nothing",
                      "core": True,
                      "fn": lambda sb: (_ for _ in ()).throw(RuntimeError("boom"))})
    try:
        results = sc.acceptance_run(only=marker, sandbox=object())
    finally:
        sc.CHECKS[:] = [c for c in sc.CHECKS if c["name"] != marker]
    assert len(results) == 1
    assert results[0].outcome == sc.FAIL
    assert "boom" in results[0].detail


# --------------------------------------------------------------------------- #
# the self-test is real, not a promise                                         #
# --------------------------------------------------------------------------- #
def test_the_self_test_exists_and_seeds_defects_for_the_sharpest_checks():
    st = pytest.importorskip("self_test")
    covered = {name for name, _fn, _what in st.MUTATIONS}
    for required in ("spine.attempt_leaves_the_primary_untouched",
                     "spine.circle_closes",
                     "safety.remote_ollama_is_refused",
                     "safety.room_prompt_gates_by_speaker",
                     "safety.bus_chain_detects_a_break"):
        assert required in covered, (
            f"{required} has no seeded defect, so nothing proves it can go red")


def test_every_seeded_defect_names_a_real_check():
    st = pytest.importorskip("self_test")
    names = {c["name"] for c in sc.CHECKS}
    unknown = sorted({n for n, _f, _w in st.MUTATIONS} - names)
    assert not unknown, f"mutations point at checks that do not exist: {unknown}"


def test_the_self_test_is_offered_by_the_cli():
    # The docstring promises --self-test. The first version promised it and the
    # parser did not offer it -- prose without a control, in the file whose
    # entire job is to replace prose with controls.
    import argparse

    parser = None
    for obj in vars(sc).values():
        if isinstance(obj, argparse.ArgumentParser):
            parser = obj
    # main() builds its parser locally, so assert on the source instead.
    src = (TOOLS / "system_check.py").read_text(encoding="utf-8")
    assert '"--self-test"' in src or "'--self-test'" in src
