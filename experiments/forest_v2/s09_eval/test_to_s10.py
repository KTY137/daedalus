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
