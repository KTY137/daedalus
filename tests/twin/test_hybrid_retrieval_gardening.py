from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[2]
TWIN = ROOT / "daedalus" / "twin"
EXPERIMENT = ROOT / "experiments" / "fourfold_hybrid_retrieval"
CANONICAL_WORKFLOW = ROOT / ".github" / "workflows" / "fourfold-v2.yml"
DUPLICATE_WORKFLOW = (
    ROOT / ".github" / "workflows" / "fourfold-hybrid-retrieval-evidence.yml"
)


def test_packaged_hybrid_duplicate_surface_stays_pruned() -> None:
    for name in ("contractions.py", "hybrid_retrieval.py", "relation_compiler.py"):
        assert not (TWIN / name).exists(), name


def test_contained_hybrid_experiment_remains_as_evidence() -> None:
    for name in ("planner.py", "relations.py", "retrieval.py", "README.md"):
        assert (EXPERIMENT / name).is_file(), name


def test_twin_package_does_not_reimport_retired_hybrid_surface() -> None:
    forbidden = (
        ".contractions",
        ".hybrid_retrieval",
        ".relation_compiler",
        "daedalus.twin.contractions",
        "daedalus.twin.hybrid_retrieval",
        "daedalus.twin.relation_compiler",
    )
    offenders: list[str] = []
    for path in TWIN.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(needle in text for needle in forbidden):
            offenders.append(path.name)
    assert offenders == []


def test_canonical_workflow_stops_importing_retired_modules() -> None:
    workflow = CANONICAL_WORKFLOW.read_text(encoding="utf-8")
    assert "daedalus.twin.hybrid_retrieval" not in workflow
    assert "daedalus.twin.relation_compiler" not in workflow
    assert "daedalus.twin.contractions" not in workflow
    assert not DUPLICATE_WORKFLOW.exists()
