from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[2]
TWIN = ROOT / "daedalus" / "twin"
EXPERIMENT = ROOT / "experiments" / "fourfold_hybrid_retrieval"
CANONICAL_WORKFLOW = ROOT / ".github" / "workflows" / "fourfold-v2.yml"
PACKAGED_DUPLICATE_WORKFLOW = (
    ROOT / ".github" / "workflows" / "fourfold-hybrid-retrieval-evidence.yml"
)
EXPERIMENT_WORKFLOW = ROOT / ".github" / "workflows" / "fourfold-hybrid-retrieval.yml"
ORIGINAL_PACKET = (
    ROOT
    / "docs"
    / "work-packets"
    / "G1-EXP-FOURFOLD-HYBRID-RETRIEVAL-01.json"
)
EXPERIMENT_HEAD = "f02b5e140308000676febf919bc92fd461d92716"
MERGE_COMMIT = "521f95702e82265486f8a7a342092c0bc9276e82"
RETIRED_BLOBS = {
    "__init__.py": "2bf6f03fa2b1fc5e9c8f750fc85246e6e3711e09",
    "planner.py": "3bf58f112011bc05e652ff4962d91b0b37dc4bca",
    "relations.py": "cc08a2f9624e5904155c7b7ac9ea67cdc8b2e36a",
    "retrieval.py": "c0ec989166c29a466ffca809c2d4b9fee1e013ac",
}


def test_packaged_hybrid_duplicate_surface_stays_pruned() -> None:
    for name in ("contractions.py", "hybrid_retrieval.py", "relation_compiler.py"):
        assert not (TWIN / name).exists(), name


def test_superseded_hybrid_experiment_is_evidence_not_live_code() -> None:
    for name in RETIRED_BLOBS:
        assert not (EXPERIMENT / name).exists(), name
    assert (EXPERIMENT / "README.md").is_file()
    assert ORIGINAL_PACKET.is_file()


def test_hybrid_tombstone_pins_recoverable_pr_commit_and_blobs() -> None:
    tombstone = (EXPERIMENT / "README.md").read_text(encoding="utf-8")
    assert "#311" in tombstone
    assert EXPERIMENT_HEAD in tombstone
    assert MERGE_COMMIT in tombstone
    for name, blob in RETIRED_BLOBS.items():
        assert f"`{name}`" in tombstone
        assert blob in tombstone


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


def test_retired_hybrid_workflows_do_not_remain_active() -> None:
    workflow = CANONICAL_WORKFLOW.read_text(encoding="utf-8")
    assert "daedalus.twin.hybrid_retrieval" not in workflow
    assert "daedalus.twin.relation_compiler" not in workflow
    assert "daedalus.twin.contractions" not in workflow
    assert not PACKAGED_DUPLICATE_WORKFLOW.exists()
    assert not EXPERIMENT_WORKFLOW.exists()
