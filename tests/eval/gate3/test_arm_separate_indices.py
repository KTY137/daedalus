"""tests for daedalus.eval.gate3.arms.separate_indices (packet G3-BASE-01, C8).

The whole point of this arm is that it must NOT reproduce slice s08
(docs/GATE2_FOREST_V2_TRIAGE.md:109-131): a shared retrieval budget split
round-robin across four per-plane indices, measured against a task set whose
gold labels lived in exactly one plane, and reported as "four separate
indices are strictly inferior to fusion" -- an artifact of the split, not a
finding. Every test below is aimed at one way that defect could reappear.
"""
from __future__ import annotations

import pytest

from daedalus.eval import harness
from daedalus.eval.gate3.arms.separate_indices import (
    SeparateIndicesArm,
    classify_plane,
    cross_plane_verdict,
    plane_documents,
)
from daedalus.eval.gate3.contracts import ArmBudget, FreezeError, FrozenTaskSet, PLANES
from daedalus.eval.gate3.protocols import SealedEvaluator, Task, run_trial


def _needle_evaluator(needle: str = "NEEDLE") -> SealedEvaluator:
    return SealedEvaluator(
        "needle-contains",
        lambda candidate, task: 1.0 if needle in candidate else 0.0,
    )


def _write_repo(tmp_path, *, code=True, knowledge=True, data=False, type_=False,
                 code_body: str = "def alpha():\n    return 1\n") -> str:
    root = tmp_path / "repo"
    root.mkdir()
    if code:
        (root / "alpha.py").write_text(code_body, encoding="utf-8")
    if knowledge:
        (root / "README.md").write_text(
            "# Docs\n\nSome knowledge-plane prose about the project.\n",
            encoding="utf-8",
        )
    if data:
        (root / "fixture.json").write_text('{"a": 1, "b": 2}\n', encoding="utf-8")
    if type_:
        (root / "shapes.proto").write_text(
            "message Shape {\n  string kind = 1;\n}\n", encoding="utf-8"
        )
    return str(root)


def _task(repo_root: str, *, label_plane: str = "code", target: str = "alpha") -> Task:
    return Task(
        task_id="t-separate-indices",
        repo_root=repo_root,
        question="alpha",
        target=target,
        label_plane=label_plane,
    )


# --------------------------------------------------------------------------- #
# C8 -- each index gets the FULL budget, never a share of it                  #
# --------------------------------------------------------------------------- #
def test_arm_separate_indices_each_full_budget(tmp_path, monkeypatch):
    """The exact s08 defect, made mechanical: assert every present plane's
    index was queried with the FULL declared budget, never budget/4, and that
    ``ArmBudget.split`` is never invoked by this arm."""
    root = _write_repo(tmp_path, code=True, knowledge=True, data=False, type_=False,
                        code_body="def alpha():\n    return 'NEEDLE alpha content here'\n")

    seen_budget_tokens: list[float] = []
    original_bm25_context = harness._bm25_context

    def _spy_bm25_context(chunks, query, budget_tokens):
        seen_budget_tokens.append(budget_tokens)
        return original_bm25_context(chunks, query, budget_tokens=budget_tokens)

    monkeypatch.setattr(harness, "_bm25_context", _spy_bm25_context)

    def _forbidden_split(self, n):
        raise AssertionError(
            f"ArmBudget.split({n}) was called -- R1 forbids dividing an arm's "
            "budget across its internal indices (this is the s08 defect)."
        )

    monkeypatch.setattr(ArmBudget, "split", _forbidden_split)

    budget = ArmBudget(max_tokens=500)
    arm = SeparateIndicesArm()
    task = _task(root, label_plane="code", target="alpha")
    outcome = arm.run(task, budget, _needle_evaluator(), seed=0)

    assert outcome.error is None, outcome.error
    # Exactly two planes are present in this fixture (code, knowledge); each
    # must have been queried with the SAME full budget, not a divided share.
    assert len(seen_budget_tokens) == 2
    assert seen_budget_tokens == [500, 500], (
        f"expected each of the 2 present indices to receive the full budget "
        f"(500), got {seen_budget_tokens} -- a value like [125, 125] would be "
        "the exact s08 defect (budget split 4 ways)."
    )
    assert outcome.notes["budget_arrangement"]  # declared, see test below too
    assert "500" in outcome.notes["budget_arrangement"]


def test_arm_separate_indices_full_budget_prevents_truncation(tmp_path):
    """Concretely falsify a reintroduced split: content that fits under the
    FULL budget but would be truncated under budget/4 must come back
    untruncated for every present plane."""
    # ~40 whitespace-tokens of body text per plane: fits under 200 (full
    # budget) but would very likely be truncated under 200/4 = 50 once the
    # "# ===== label =====" wrapper and any second chunk are accounted for --
    # so this is a real, not incidental, falsification of a 4-way split.
    body = " ".join(f"word{i}" for i in range(40))
    root = _write_repo(
        tmp_path, code=True, knowledge=True,
        code_body=f"def alpha():\n    # {body}\n    return 1\n",
    )
    from pathlib import Path
    Path(root, "README.md").write_text(f"# Docs\n\n{body}\n", encoding="utf-8")

    budget = ArmBudget(max_tokens=200)
    arm = SeparateIndicesArm()
    task = _task(root, label_plane="code", target="alpha")
    outcome = arm.run(task, budget, _needle_evaluator(), seed=0)

    assert outcome.error is None, outcome.error
    for plane in ("code", "knowledge"):
        info = outcome.notes["per_plane"][plane]
        assert info["present"] is True
        assert info["truncated"] is False, (
            f"plane {plane!r} was truncated under the FULL budget -- this is "
            "consistent with a reintroduced budget split"
        )


# --------------------------------------------------------------------------- #
# B2 -- composite arm declares its internal budget arrangement                #
# --------------------------------------------------------------------------- #
def test_arm_declares_per_index_budget_arrangement_in_notes(tmp_path):
    root = _write_repo(tmp_path, code=True, knowledge=True)
    budget = ArmBudget(max_tokens=300)
    arm = SeparateIndicesArm()
    task = _task(root, label_plane="code")
    outcome = arm.run(task, budget, _needle_evaluator(), seed=0)

    assert outcome.error is None, outcome.error
    assert isinstance(outcome.notes["budget_arrangement"], str)
    assert "full" in outcome.notes["budget_arrangement"].lower()
    assert outcome.notes["fusion"] == (
        "none -- each plane's retrieval is scored independently; "
        "no cross-plane rank merge or blend occurs in this arm"
    )
    # all four planes are represented in the declared arrangement, present or not
    assert set(outcome.notes["per_plane"]) == set(PLANES)


# --------------------------------------------------------------------------- #
# absent planes are reported, never dropped                                   #
# --------------------------------------------------------------------------- #
def test_absent_planes_are_reported_not_dropped(tmp_path):
    root = _write_repo(tmp_path, code=True, knowledge=True, data=False, type_=False)
    budget = ArmBudget(max_tokens=300)
    arm = SeparateIndicesArm()
    task = _task(root, label_plane="code")
    outcome = arm.run(task, budget, _needle_evaluator(), seed=0)

    assert outcome.error is None, outcome.error
    per_plane = outcome.notes["per_plane"]
    assert len(per_plane) == 4  # denominator is not shrunk to "planes that exist"
    assert per_plane["data"] == {"present": False, "n_documents": 0}
    assert per_plane["type"] == {"present": False, "n_documents": 0}
    assert per_plane["code"]["present"] is True
    assert per_plane["knowledge"]["present"] is True


def test_plane_documents_reports_all_four_plane_keys_even_when_empty(tmp_path):
    root = _write_repo(tmp_path, code=True, knowledge=False)
    docs = plane_documents(root)
    assert set(docs) == set(PLANES)
    assert docs["knowledge"] == []
    assert docs["data"] == []
    assert docs["type"] == []
    assert len(docs["code"]) == 1


def test_classify_plane_does_not_double_claim_code_files():
    # A file named like a "type" file but written in Python is still code:
    # spec_for's claim wins, so the type/data proxies never re-claim it.
    assert classify_plane("pkg/types.py") == "code"
    assert classify_plane("pkg/schema.json") == "data"
    assert classify_plane("pkg/shape.proto") == "type"
    assert classify_plane("pkg/notes.md") == "knowledge"
    assert classify_plane("pkg/binary.exe") is None


# --------------------------------------------------------------------------- #
# honest miss when the label plane has no documents                           #
# --------------------------------------------------------------------------- #
def test_arm_reports_honest_miss_when_label_plane_absent(tmp_path):
    root = _write_repo(tmp_path, code=True, knowledge=True, data=False, type_=False)
    budget = ArmBudget(max_tokens=300)
    arm = SeparateIndicesArm()
    # This task claims its answer lives in "data", but the fixture has no data
    # documents -- the arm must not silently borrow content from another plane.
    task = _task(root, label_plane="data")
    outcome = arm.run(task, budget, _needle_evaluator(), seed=0)

    assert outcome.error is None
    assert outcome.success is False
    assert outcome.score == 0.0
    assert outcome.candidate == ""
    assert outcome.notes["per_plane"]["data"]["present"] is False


# --------------------------------------------------------------------------- #
# determinism                                                                  #
# --------------------------------------------------------------------------- #
def test_arm_separate_indices_is_deterministic(tmp_path):
    root = _write_repo(tmp_path, code=True, knowledge=True,
                        code_body="def alpha():\n    return 'NEEDLE'\n")
    budget = ArmBudget(max_tokens=300)
    arm = SeparateIndicesArm()
    assert arm.stochastic is False
    task = _task(root, label_plane="code")

    outcome_a = arm.run(task, budget, _needle_evaluator(), seed=0)
    outcome_b = arm.run(task, budget, _needle_evaluator(), seed=1)

    assert outcome_a.candidate == outcome_b.candidate
    assert outcome_a.score == outcome_b.score
    assert outcome_a.success == outcome_b.success
    assert outcome_a.tokens_used == outcome_b.tokens_used
    assert outcome_a.notes == outcome_b.notes


def test_arm_separate_indices_deterministic_via_run_trial(tmp_path):
    """Same check through the shared ``run_trial`` runner used by every arm,
    so the arm is proven deterministic under the actual harness call path."""
    root = _write_repo(tmp_path, code=True, knowledge=True,
                        code_body="def alpha():\n    return 'NEEDLE'\n")
    budget = ArmBudget(max_tokens=300)
    arm = SeparateIndicesArm()
    task = _task(root, label_plane="code")

    r1 = run_trial(arm, task, budget, _needle_evaluator(), seed=0)
    r2 = run_trial(arm, task, budget, _needle_evaluator(), seed=0)

    assert r1.success == r2.success
    assert r1.score == r2.score
    assert r1.tokens_used == r2.tokens_used
    assert r1.notes == r2.notes


# --------------------------------------------------------------------------- #
# R3 regression -- the s08 shape must never yield a "fusion loses" verdict    #
# --------------------------------------------------------------------------- #
def test_cross_plane_verdict_refuses_single_plane_taskset():
    """Reproduces the s08 shape: gold labels 100% in one plane. The honest
    outcome is a refusal, never a comparative verdict string."""
    single_plane_set = FrozenTaskSet(
        name="s08-shape",
        task_ids=tuple(f"q{i}" for i in range(600)),
        counting_rule="hit@10 over 600 code-only queries",
        label_plane_census={"code": 600, "type": 0, "data": 0, "knowledge": 0},
    )

    with pytest.raises(FreezeError):
        single_plane_set.require_cross_plane()

    with pytest.raises(FreezeError):
        # Must raise BEFORE producing a "432 vs 491, separate_indices loses"
        # style string -- there is no code path in cross_plane_verdict that
        # returns such a string for a single-plane task set.
        cross_plane_verdict(single_plane_set, separate_score=432.0, fusion_score=491.0)


def test_cross_plane_verdict_permits_genuine_cross_plane_taskset():
    """Sanity check that the refusal is targeted, not universal: a task set
    with labels in more than one plane gets a real verdict."""
    cross_plane_set = FrozenTaskSet(
        name="genuinely-cross-plane",
        task_ids=("q1", "q2", "q3", "q4"),
        counting_rule="hit@10 over 4 mixed-plane queries",
        label_plane_census={"code": 2, "type": 0, "data": 1, "knowledge": 1},
    )
    verdict = cross_plane_verdict(cross_plane_set, separate_score=491.0, fusion_score=480.0)
    assert "beats" in verdict


def test_arm_never_emits_a_fused_cross_plane_score(tmp_path):
    """Even when the underlying repo is genuinely multi-plane, one arm.run()
    call must never fuse planes into a single blended score -- notes always
    say 'fusion: none', and the reported candidate is exactly the label
    plane's own retrieval, not a concatenation of several planes'."""
    root = _write_repo(tmp_path, code=True, knowledge=True, data=True, type_=True,
                        code_body="def alpha():\n    return 'NEEDLE'\n")
    budget = ArmBudget(max_tokens=1000)
    arm = SeparateIndicesArm()
    task = _task(root, label_plane="code")
    outcome = arm.run(task, budget, _needle_evaluator(), seed=0)

    assert outcome.error is None, outcome.error
    assert outcome.notes["fusion"].startswith("none")
    # the candidate must come only from the code plane's retrieval text
    assert "message Shape" not in outcome.candidate  # type-plane content
    assert '"a": 1' not in outcome.candidate  # data-plane content
