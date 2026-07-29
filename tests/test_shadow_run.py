"""The shadow run: it may collect candidates, it may not confer trust.

The rule this file enforces came out of an adversarial review of the bootstrap
plan, and it is worth stating in full because every test below is a corollary:

    With 0/3, the gate is a hard block on PROMOTION, not on candidate
    GENERATION. Let the run collect, but call it a shadow run; no candidate
    gets less human review because it came back green.

    The smallest trustworthy property is demonstrated discrimination: a frozen
    gate must separate good patches from representative bad ones, including a
    defect corpus held back until evaluation. Critical defect classes must be
    killed completely; a global mutation score must not average them away.

So the tests are about what the module REFUSES to conclude. The dangerous
failure here is not a crash -- it is a run that comes back green and is read as
"this patch is good", which is a sentence nothing in this repo can currently
support.
"""
from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from daedalus.spine import bootstrap as B


def _receipt(tmp_path: Path, **doc) -> Path:
    p = tmp_path / B.DISCRIMINATION_REL_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


HEAD = "a" * 40


# --------------------------------------------------------------------------- #
# whether a green gate means anything                                          #
# --------------------------------------------------------------------------- #
def test_no_receipt_means_unproven_not_fine(tmp_path):
    """Absent evidence is the state the whole repo keeps getting wrong.

    Nothing has measured this gate, so "green" carries no information about
    correctness. Reporting that as acceptable is how three green suites came to
    sit over three live escapes in one day.
    """
    got = B.gate_discrimination(tmp_path, head=HEAD)
    assert got.proven is False
    assert "pytest ran" in got.reason


def test_a_receipt_from_another_revision_does_not_count(tmp_path):
    """Same doctrine the map and inventory sources follow: a measurement of a
    tree that no longer exists is not a measurement of this one."""
    _receipt(tmp_path, head="b" * 12, measured_at="2026-07-29", planted=50,
             killed=50, surviving_classes=[])
    got = B.gate_discrimination(tmp_path, head=HEAD)
    assert got.proven is False
    assert "but HEAD is" in got.reason


def test_a_surviving_CRITICAL_class_beats_a_perfect_looking_score(tmp_path):
    """The averaging failure, stated as a test.

    98% sounds like a working gate. It is not, if the 2% that survived is the
    class "deletes outside the worktree" -- which is a thing that has actually
    happened in this repo. A single number hides exactly the blind spot that
    matters, so the class check runs BEFORE the rate check and overrides it.
    """
    _receipt(tmp_path, head=HEAD[:12], measured_at="2026-07-29", planted=100,
             killed=98, surviving_classes=["deletes-outside-the-worktree"])
    got = B.gate_discrimination(tmp_path, head=HEAD)
    assert got.proven is False
    assert "critical defect class" in got.reason
    assert got.kill_rate == pytest.approx(0.98)


def test_a_low_kill_rate_is_unproven_even_with_no_critical_survivors(tmp_path):
    _receipt(tmp_path, head=HEAD[:12], measured_at="2026-07-29", planted=100,
             killed=50, surviving_classes=["cosmetic"])
    got = B.gate_discrimination(tmp_path, head=HEAD)
    assert got.proven is False
    assert "below the" in got.reason


def test_a_corrupt_receipt_is_unproven_not_a_crash(tmp_path):
    p = tmp_path / B.DISCRIMINATION_REL_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{not json", encoding="utf-8")
    assert B.gate_discrimination(tmp_path, head=HEAD).proven is False


def test_a_GOOD_receipt_does_prove_it(tmp_path):
    """The allow side. Without this, a function that returned False forever
    would pass every test above while making the gate permanently worthless.
    """
    _receipt(tmp_path, head=HEAD[:12], measured_at="2026-07-29", planted=100,
             killed=92, surviving_classes=["cosmetic"])
    got = B.gate_discrimination(tmp_path, head=HEAD)
    assert got.proven is True
    assert got.kill_rate == pytest.approx(0.92)


# --------------------------------------------------------------------------- #
# promotion                                                                    #
# --------------------------------------------------------------------------- #
def test_promotion_is_refused_while_discrimination_is_unproven():
    res = B.ShadowResult(state="gated",
                         discrimination=B.GateDiscrimination(False, "nothing measured"))
    assert res.promotion_allowed is False


def _code_without_prose(obj) -> str:
    """The source of `obj` with docstrings removed.

    Written because the first version of the test below matched the word
    "override" inside the docstring that EXPLAINS there is no override, and so
    it failed while the code was correct. The same mistake in the other
    direction is the dangerous one: a guard-text assertion that matches a
    comment stays green after the guard itself is deleted, which happened four
    times in one evening on the room mirror test. Assert on code, never on
    prose that happens to sit next to it.
    """
    import ast
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(obj)))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef, ast.Module)) and ast.get_docstring(node):
            node.body = node.body[1:]
    return ast.unparse(tree)


def test_there_is_NO_flag_that_allows_promotion_anyway():
    """The containment module lost its handle-inheritance bypass to exactly one
    keyword argument. This asserts the same mistake is not available here."""
    # STRUCTURAL, not a word list: a word list either misses the escape hatch
    # or trips over the property's own name. The property must be exactly one
    # return statement -- no branch, no env lookup, no attribute a caller could
    # set. Anything else is a place a bypass can live.
    import ast
    import textwrap

    fn = ast.parse(textwrap.dedent(
        inspect.getsource(B.ShadowResult.promotion_allowed.fget))).body[0]
    body = [n for n in fn.body if not isinstance(n, ast.Expr)]
    assert len(body) == 1 and isinstance(body[0], ast.Return), (
        "the promotion predicate is no longer a single unconditional return; "
        "a bypass can hide in a branch")
    names = {n.attr for n in ast.walk(body[0]) if isinstance(n, ast.Attribute)}
    assert names <= {"discrimination", "proven"}, (
        f"the promotion predicate consults {names - {'discrimination', 'proven'}} "
        f"-- promotion must depend on measured discrimination and nothing else")
    for name in ("force", "override", "allow_promotion", "promote", "apply"):
        assert name not in inspect.signature(B.shadow_run).parameters, (
            f"shadow_run exposes {name!r}; promotion must stay a human act")
    module_code = _code_without_prose(B)
    assert "def apply" not in module_code
    assert "--apply" not in module_code


def test_the_verdict_never_calls_a_green_gate_good():
    """The sentence a tired human reads at 3am is the actual interface."""
    res = B.ShadowResult(state="gated",
                         discrimination=B.GateDiscrimination(False, "nothing measured"))
    v = res.verdict()
    assert "NOT evidence" in v
    assert "as if it were unreviewed" in v


def test_a_proven_gate_still_does_not_promote_by_itself():
    res = B.ShadowResult(state="gated",
                         discrimination=B.GateDiscrimination(True, "kill rate 92%"))
    assert res.promotion_allowed is True
    assert "human act" in res.verdict()


# --------------------------------------------------------------------------- #
# step zero: refreshing the sources                                            #
# --------------------------------------------------------------------------- #
def test_a_generator_that_exits_0_without_stamping_is_NOT_success(tmp_path):
    """Exit 0 is not the criterion; the artefact being checkable is.

    Today's `daedalus map` returns 0 and writes no repo_state, so its consumer
    still refuses the snapshot. Calling that a successful refresh would report
    a working circle while the circle cannot start.
    """
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "architecture-state.json").write_text(
        json.dumps({"schema": 3}), encoding="utf-8")
    got = B.refresh_sources(tmp_path, runner=lambda argv, root: (0, "wrote map"))
    assert got[0].attempted is True
    assert got[0].succeeded is False
    assert "still records no repo_state.head" in got[0].detail


def test_a_generator_that_DOES_stamp_counts_as_success(tmp_path):
    (tmp_path / "docs").mkdir()
    snap = tmp_path / "docs" / "architecture-state.json"

    def gen(argv, root):
        snap.write_text(json.dumps({"schema": 3, "repo_state": {"head": HEAD}}),
                        encoding="utf-8")
        return (0, "ok")

    snap.write_text(json.dumps({"schema": 3}), encoding="utf-8")
    got = B.refresh_sources(tmp_path, runner=gen)
    assert got[0].succeeded is True
    assert got[0].before_head is None and got[0].after_head == HEAD


def test_a_generator_that_raises_is_reported_not_swallowed(tmp_path):
    (tmp_path / "docs").mkdir()

    def boom(argv, root):
        raise OSError("generator missing")

    got = B.refresh_sources(tmp_path, runner=boom)
    assert got[0].succeeded is False
    assert "OSError" in got[0].detail


# --------------------------------------------------------------------------- #
# the two silences that must stay distinguishable                              #
# --------------------------------------------------------------------------- #
class _Queue:
    def __init__(self, candidates=(), degraded=(), notes=()):
        self.candidates = list(candidates)
        self.degraded_sources = tuple(degraded)
        self.notes = tuple(notes)
        self.sources = {}


def test_no_work_and_could_not_look_are_different_states(monkeypatch, tmp_path):
    """A source that failed must never render as "there is nothing to do".

    This distinction is the difference between "the repo is in good shape" and
    "the loop is blind", and they look identical in an empty queue.
    """
    import daedalus.spine.picker as picker

    monkeypatch.setattr(picker, "build_queue", lambda **k: _Queue())
    empty = B.shadow_run(tmp_path, runner=lambda ctx: None, refresh=False)
    assert empty.state == "no_candidate"

    monkeypatch.setattr(picker, "build_queue",
                        lambda **k: _Queue(degraded=("inventory",)))
    blind = B.shadow_run(tmp_path, runner=lambda ctx: None, refresh=False)
    assert blind.state == "sources_unavailable"
    assert blind.degraded_sources == ("inventory",)
    assert B.EXIT_SOURCES_UNAVAILABLE != B.EXIT_NO_CANDIDATE


def test_a_runner_is_required_and_has_no_implicit_default(tmp_path):
    """Mirrors TaskAttempt: no run may quietly reach a model because a caller
    forgot an argument."""
    with pytest.raises((ValueError, TypeError)):
        B.shadow_run(tmp_path, runner=None, refresh=False)


def test_the_module_does_not_write_the_primary_checkout():
    """Structural, not promised. If an apply path is ever added here it will
    be added deliberately, over this test."""
    src = inspect.getsource(B)
    for forbidden in ("git apply", "git am", "checkout --", "reset --hard"):
        assert forbidden not in src, f"{forbidden!r} appeared in the shadow runner"
