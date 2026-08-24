"""Checks for the s09 -> s10 adapter.

One test here deliberately breaks ``to_s10.py``'s own "no import of
``s10_kill``" discipline: ``test_emitted_document_validates_against_the_real_
schema`` imports ``experiments.forest_v2.s10_kill.schema`` to prove the
adapter's output is accepted by the *real* evaluator contract, not by a
hand-copied re-implementation of it that could quietly drift from the real
one. This is the same trade slice s06 made for its s01 coupling (README,
slice s06, "Honest caveats"): a disclosed, one-place, test-only import beats
trusting a duplicated schema never to rot. ``to_s10.py`` itself, and every
other test in this file, stays free of that import -- see its module
docstring for why the production code keeps the boundary s10_kill's own
``__init__.py`` and ``test_s10_boundary.py`` document for the harness side.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Same convention every other test file in this package uses (see
# test_gitio.py, test_harness.py, ...): put experiments/forest_v2/ on
# sys.path and import siblings as top-level packages. s10_kill is reachable
# the identical way, which is what the one disclosed cross-import below
# relies on -- see this file's module docstring.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from s09_eval import to_s10  # noqa: E402


def _raw(per_case, retrievers=None):
    names = retrievers if retrievers is not None else sorted({r["retriever"] for r in per_case})
    return {
        "schema": "forest_v2.s09.results/1",
        "taskset_digest": "sha256:test",
        "taskset_anchor": "deadbeef",
        "cases": len({r["case_id"] for r in per_case}),
        "retrievers": names,
        "per_case": per_case,
    }


def _row(case_id, retriever, variant, rr):
    return {
        "case_id": case_id,
        "retriever": retriever,
        "variant": variant,
        "gold_total": 1,
        "hits_at": {"1": 1 if rr == 1.0 else 0},
        "first_hit_rank": (round(1 / rr) if rr else None),
        "reciprocal_rank": rr,
        "universe_size": 100,
        "returned": 20,
    }


# --------------------------------------------------------------- build_arm


def test_build_arm_reads_scores_from_per_case_only():
    raw = _raw([
        _row("c0", "bm25", "raw", 1.0),
        _row("c1", "bm25", "raw", 0.5),
        _row("c0", "random_uniform", "raw", 0.0),
        _row("c1", "random_uniform", "raw", 0.0),
    ])
    arm = to_s10.build_arm(raw, "bm25", "raw", "bm25", "lexical")
    assert arm["scores"][to_s10.PRIMARY_METRIC] == {"c0": 1.0, "c1": 0.5}
    assert arm["role"] == "bm25"
    assert arm["retriever"]["mechanism"] == "lexical"
    assert arm["returns_planes"] == list(to_s10.RETURNS_PLANES)
    assert arm["returned_plane_counts"] is None


def test_build_arm_raises_on_a_retriever_variant_absent_from_the_run():
    raw = _raw([_row("c0", "bm25", "raw", 1.0)])
    with pytest.raises(to_s10.AdapterError):
        to_s10.build_arm(raw, "bm25", "scrubbed", "bm25", "lexical")


# --------------------------------------------------------- build_kill_input


def _five_baseline_raw(cases=("c0", "c1", "c2")):
    rows = []
    for i, case in enumerate(cases):
        for retriever in (
            "random_uniform", "path_lexical", "bm25", "bm25_content_only", "recency_prior",
        ):
            rows.append(_row(case, retriever, "raw", 0.0 if i % 2 else 1.0))
            rows.append(_row(case, retriever, "scrubbed", 0.0))
    return _raw(rows)


def test_only_arms_with_honest_roles_are_included():
    raw = _five_baseline_raw()
    doc = to_s10.build_kill_input(raw, run_id="t", source="test")
    arm_ids = sorted(a["arm_id"] for a in doc["arms"])
    assert arm_ids == [
        "bm25/raw", "bm25/scrubbed", "random_uniform/raw", "random_uniform/scrubbed",
    ]
    roles = {a["role"] for a in doc["arms"]}
    assert roles == {"bm25", "random_priority"}


def test_excluded_retrievers_are_named_not_silently_dropped():
    assert set(to_s10.EXCLUDED_ARMS) == {"recency_prior", "path_lexical", "bm25_content_only"}
    for retriever, reason in to_s10.EXCLUDED_ARMS.items():
        assert retriever not in to_s10.INCLUDED_ARMS
        assert len(reason) > 20  # a real sentence, not a stub


def test_no_arm_is_labelled_full_or_fusion():
    """Guard against silently promoting a baseline into the one role this
    whole slice exists to refuse fabricating. Verified by disabling: adding
    a ``"recency_prior": ("full", "single_index")`` entry to ``INCLUDED_ARMS``
    and re-running this test turns it red (checked by hand while writing
    this file; not re-mutated on every run to keep the suite fast)."""
    for role, _mechanism in to_s10.INCLUDED_ARMS.values():
        assert role not in ("full", "fusion")


def test_missing_included_retriever_is_silently_skipped_not_fabricated():
    raw = _raw([
        _row("c0", "random_uniform", "raw", 0.0),
        _row("c1", "random_uniform", "raw", 1.0),
    ])
    doc = to_s10.build_kill_input(raw, run_id="t", source="test")
    roles = {a["role"] for a in doc["arms"]}
    assert roles == {"random_priority"}


def test_no_included_retrievers_present_raises():
    raw = _raw([_row("c0", "recency_prior", "raw", 1.0)], retrievers=["recency_prior"])
    with pytest.raises(to_s10.AdapterError):
        to_s10.build_kill_input(raw, run_id="t", source="test")


def test_wrong_schema_is_rejected():
    raw = _five_baseline_raw()
    raw["schema"] = "some.other.schema/1"
    with pytest.raises(to_s10.AdapterError):
        to_s10.build_kill_input(raw, run_id="t", source="test")


def test_case_order_is_stable_first_seen_not_resorted():
    raw = _raw([
        _row("c2", "bm25", "raw", 1.0),
        _row("c0", "bm25", "raw", 0.0),
        _row("c1", "bm25", "raw", 0.0),
        _row("c2", "random_uniform", "raw", 0.0),
        _row("c0", "random_uniform", "raw", 0.0),
        _row("c1", "random_uniform", "raw", 0.0),
    ])
    doc = to_s10.build_kill_input(raw, run_id="t", source="test")
    assert doc["cases"] == ["c2", "c0", "c1"]


def test_document_carries_no_single_corpus_census():
    """s09 has no one fixed corpus (every case has its own pre-image tree);
    the adapter must not invent one."""
    doc = to_s10.build_kill_input(_five_baseline_raw(), run_id="t", source="test")
    assert doc["corpus"] is None


# ------------------------------------------------------------ gold_planes


def test_gold_planes_only_declared_for_single_plane_cases():
    gold_by_case = {
        "single_code": ("daedalus/core.py",),
        "single_knowledge": ("docs/README.md",),
        "cross_plane": ("daedalus/core.py", "docs/README.md"),
        "no_twin_plane": ("index.html",),  # presentation only, not a Twin plane
    }
    out = to_s10.gold_planes_for_cases(gold_by_case)
    assert out == {"single_code": "code", "single_knowledge": "knowledge"}
    assert "cross_plane" not in out
    assert "no_twin_plane" not in out


# ------------------------------------------------------------- end to end


def test_end_to_end_document_validates_against_the_real_s10_schema():
    """Disclosed, deliberate boundary crossing -- see this file's docstring."""
    from s10_kill.schema import ResultSet  # noqa: E402 (path already on sys.path)

    raw = _five_baseline_raw(cases=("c0", "c1", "c2", "c3", "c4"))
    gold_planes = to_s10.gold_planes_for_cases({
        "c0": ("daedalus/core.py",),
        "c1": ("docs/README.md",),
        "c2": ("daedalus/core.py", "docs/README.md"),  # cross-plane, left undeclared
        "c3": ("configs/x.json",),
        "c4": ("daedalus/core.py",),
    })
    doc = to_s10.build_kill_input(
        raw, run_id="t-end-to-end", source="synthetic fixture, not a real harness run",
        gold_planes=gold_planes,
    )
    rs = ResultSet.from_obj(doc)  # raises SchemaError if the contract is violated
    assert sorted(a.role for a in rs.arms) == ["bm25", "bm25", "random_priority", "random_priority"]
    assert rs.gold_planes == {"c0": "code", "c1": "knowledge", "c3": "data", "c4": "code"}
    assert "c2" not in rs.gold_planes


# ------------------------------------------------- the committed real runs


RESULTS_DIR = Path(__file__).resolve().parent / "results" / "s10_adapter_runs"


@pytest.mark.parametrize("name", [
    "kill_input_taskset20_2026-08-24.json",
    "kill_input_xplane88_2026-08-24.json",
])
def test_the_committed_real_adapter_outputs_still_validate(name):
    """Pins the two real, executed adapter runs committed alongside this
    file (see the README continuation for what produced them) -- a silent
    edit to either JSON, or a schema drift in either package, turns this
    red the same way test_published_numbers.py pins slice s09's own table."""
    path = RESULTS_DIR / name
    if not path.exists():  # pragma: no cover - only true before the runs are committed
        pytest.skip(f"{path} not present in this checkout")
    import json
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["schema"] == to_s10.SCHEMA_ID

    from s10_kill.schema import ResultSet

    rs = ResultSet.from_obj(doc)
    assert sorted({a.role for a in rs.arms}) == ["bm25", "random_priority"]
    # every excluded retriever is named in the run's own source note, not
    # silently absent with no explanation
    for retriever in to_s10.EXCLUDED_ARMS:
        assert retriever in doc["source"]


# ------------------------------------------------- s11 fusion arms (build_fusion_arm)


def _fusion_raw(cases=("c0", "c1", "c2")):
    rows = []
    plane_counts = {
        "fusion_rrf": {"raw": {"code": 3, "data": 2, "knowledge": 1}},
        "separate_indices_bm25": {"raw": {"code": 6, "data": 0, "knowledge": 0}},
    }
    for i, case in enumerate(cases):
        for retriever in (
            "random_uniform", "path_lexical", "bm25", "bm25_content_only", "recency_prior",
            "fusion_rrf", "code_only_bm25", "separate_indices_bm25",
        ):
            rows.append(_row(case, retriever, "raw", 0.0 if i % 2 else 1.0))
    raw = _raw(rows)
    raw["returned_plane_counts"] = plane_counts
    return raw


def test_build_fusion_arm_reads_measured_plane_counts():
    raw = _fusion_raw()
    arm = to_s10.build_fusion_arm(raw, "fusion_rrf", "raw", "full")
    assert arm["role"] == "full"
    assert arm["arm_id"] == "fusion_rrf/raw#full"
    assert arm["retriever"]["mechanism"] == to_s10.FUSION_MECHANISM
    assert arm["retriever"]["combines_planes"] == ["code", "data", "knowledge"]
    assert arm["returns_planes"] == ["code", "data", "knowledge"]
    assert arm["returned_plane_counts"] == {"code": 3, "data": 2, "knowledge": 1}


def test_build_fusion_arm_declares_absence_when_the_run_never_captured_it():
    raw = _fusion_raw()
    del raw["returned_plane_counts"]["fusion_rrf"]
    arm = to_s10.build_fusion_arm(raw, "fusion_rrf", "raw", "fusion")
    assert arm["returned_plane_counts"] is None


def test_build_fusion_arm_rejects_an_unknown_retriever():
    raw = _fusion_raw()
    with pytest.raises(to_s10.AdapterError):
        to_s10.build_fusion_arm(raw, "some_other_retriever", "raw", "full")


def test_code_only_arm_scopes_to_the_code_plane_alone():
    raw = _fusion_raw()
    arm = to_s10.build_fusion_arm(raw, "code_only_bm25", "raw", "code_only")
    assert arm["returns_planes"] == ["code"]
    assert arm["retriever"]["combines_planes"] == []
    assert arm["retriever"]["mechanism"] == "single_plane"


def test_separate_indices_arm_never_claims_the_fusion_mechanism():
    raw = _fusion_raw()
    arm = to_s10.build_fusion_arm(raw, "separate_indices_bm25", "raw", "separate_indices")
    assert arm["retriever"]["mechanism"] != to_s10.FUSION_MECHANISM
    assert arm["retriever"]["mechanism"] == "per_plane_topk_concat"
    assert arm["retriever"]["combines_planes"] == []


def test_build_kill_input_emits_full_and_fusion_from_the_same_retriever():
    """s10_kill/schema.py's own KNOWN_ROLES docstring: 'fusion (may be the
    same system as full)'. One retriever, two roles, identical scores --
    disclosed, not hidden."""
    raw = _fusion_raw()
    doc = to_s10.build_kill_input(raw, run_id="t", source="test")
    roles = sorted(a["role"] for a in doc["arms"])
    assert roles == [
        "bm25", "code_only", "full", "fusion", "random_priority", "separate_indices",
    ]
    full_arm = next(a for a in doc["arms"] if a["role"] == "full")
    fusion_arm = next(a for a in doc["arms"] if a["role"] == "fusion")
    assert full_arm["scores"] == fusion_arm["scores"]
    assert full_arm["arm_id"] != fusion_arm["arm_id"]


def test_stale_no_fusion_claim_was_corrected_not_just_renamed():
    """The pre-s11 constant said 'no cross-plane fusion retriever exists
    anywhere in this program'. That sentence is no longer true and must not
    appear verbatim in the corrected text -- see the constant's own comment
    for why it was restated rather than silently edited in place."""
    assert "anywhere in this program" not in to_s10.NO_FUSION_ARM_NATIVE_TO_S07_S08_S09
    assert to_s10.NO_FUSION_ARM_ANYWHERE == to_s10.NO_FUSION_ARM_NATIVE_TO_S07_S08_S09
    assert "s11_fusion" in to_s10.NO_FUSION_ARM_NATIVE_TO_S07_S08_S09


# --------------------------------------------- the committed real fusion runs


@pytest.mark.parametrize("name", [
    "kill_input_taskset20_fusion_2026-08-24.json",
    "kill_input_xplane88_fusion_2026-08-24.json",
])
def test_the_committed_real_fusion_adapter_outputs_still_validate(name):
    """Same pin as test_the_committed_real_adapter_outputs_still_validate,
    for the s11 continuation's two runs: full/fusion/code_only/
    separate_indices now sit alongside bm25/random_priority in one document,
    and the fusion arm's returned_plane_counts must show real multi-plane
    coverage or fusion_arm() in plane_range.py would refuse it."""
    path = RESULTS_DIR / name
    if not path.exists():  # pragma: no cover - only true before the runs are committed
        pytest.skip(f"{path} not present in this checkout")
    import json
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["schema"] == to_s10.SCHEMA_ID

    from s10_kill.schema import ResultSet

    rs = ResultSet.from_obj(doc)
    assert sorted({a.role for a in rs.arms}) == [
        "bm25", "code_only", "full", "fusion", "random_priority", "separate_indices",
    ]
    fusion_arm = rs.find("fusion", "raw")
    assert fusion_arm is not None
    assert fusion_arm.retriever.mechanism == to_s10.FUSION_MECHANISM
    assert fusion_arm.returned_plane_counts is not None
    reached = [p for p, n in fusion_arm.returned_plane_counts.items() if n > 0]
    assert len(reached) >= 2, "a fusion arm that never returns a second plane is not fusion"
    for retriever in to_s10.EXCLUDED_ARMS:
        assert retriever in doc["source"]
