from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus.schemas import ContractProvenance
from daedalus.twin import (
    CrossPlaneBinding,
    FourfoldSnapshot,
    PlaneSnapshot,
    ReferenceCompileError,
    compile_reference_project,
)

REVISION = "b" * 40
NOW = "2026-08-01T17:30:00Z"
FIXTURE = Path(__file__).resolve().parents[2] / "examples" / "fourfold_wiki_app"


def _copy_fixture(tmp_path: Path) -> Path:
    target = tmp_path / "wiki_app"
    shutil.copytree(FIXTURE, target)
    return target


def _compile(root: Path):
    return compile_reference_project(
        root,
        source_revision=REVISION,
        created_at=NOW,
        trace_id="tr-wiki-reference",
    )


def test_reference_application_runs_real_list_show_and_search_commands() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(FIXTURE / "src")
    data = str(FIXTURE / "data" / "articles.csv")

    listed = subprocess.run(
        [sys.executable, "-m", "knowledge_hub.app", "--data", data, "--list"],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "fourfold-overview\tFourfold Overview" in listed.stdout
    assert "draft-research" not in listed.stdout

    shown = subprocess.run(
        [
            sys.executable,
            "-m",
            "knowledge_hub.app",
            "--data",
            data,
            "--show",
            "revision-atomicity",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert "Every plane and binding is tied to one exact source revision." in shown.stdout

    searched = subprocess.run(
        [
            sys.executable,
            "-m",
            "knowledge_hub.app",
            "--data",
            data,
            "--search",
            "evidence",
        ],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    assert searched.stdout.strip().splitlines() == [
        "evidence-boundaries\tEvidence Boundaries",
        "fourfold-overview\tFourfold Overview",
    ]


def test_compiler_builds_complete_atomic_fourfold_snapshot() -> None:
    result = _compile(FIXTURE)
    snapshot = result.snapshot

    assert tuple(snapshot.plane_map) == ("code", "type", "data", "knowledge")
    assert all(plane.status == "complete" for plane in snapshot.planes)
    assert all(plane.node_ids for plane in snapshot.planes)
    assert all(plane.evidence_sha256s for plane in snapshot.planes)
    assert snapshot.source_forest_sha256 == result.forest.content_sha256
    assert len(snapshot.bindings) == 31
    assert {binding.relation for binding in snapshot.bindings} == {
        "constrained_by",
        "declares_type",
        "documents",
        "materializes_as",
    }
    assert len(result.forest.nodes) >= 30
    assert len(snapshot.plane_map["knowledge"].node_ids) == 10


def test_compilation_is_deterministic_under_manifest_reordering(tmp_path: Path) -> None:
    first_root = _copy_fixture(tmp_path / "first")
    second_root = _copy_fixture(tmp_path / "second")
    manifest_path = second_root / "fourfold.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["code_files"].reverse()
    manifest["data_files"].reverse()
    manifest["knowledge_files"].reverse()
    manifest["claims"].reverse()
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    first = _compile(first_root)
    second = _compile(second_root)

    # The manifest itself is evidence, so its bytes legitimately change. The
    # semantic memberships and bindings must still canonicalize identically.
    assert first.snapshot.planes == second.snapshot.planes
    assert first.snapshot.bindings == second.snapshot.bindings
    assert first.forest.nodes == second.forest.nodes
    assert first.forest.edges == second.forest.edges


def test_broken_local_wiki_link_refuses_compilation(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    home = root / "wiki" / "Home.md"
    home.write_text(home.read_text(encoding="utf-8") + "\n[Broken](Missing.md)\n", encoding="utf-8")

    with pytest.raises(ReferenceCompileError, match="broken local Markdown link"):
        _compile(root)


def test_csv_or_schema_drift_refuses_claim_promotion(tmp_path: Path) -> None:
    csv_root = _copy_fixture(tmp_path / "csv")
    csv_path = csv_root / "data" / "articles.csv"
    csv_path.write_text(
        csv_path.read_text(encoding="utf-8").replace("id,slug,title,body,status,tag", "id,slug,title,body,status"),
        encoding="utf-8",
    )
    with pytest.raises(ReferenceCompileError, match="CSV field does not exist"):
        _compile(csv_root)

    schema_root = _copy_fixture(tmp_path / "schema")
    schema_path = schema_root / "schemas" / "article.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["properties"].pop("tag")
    schema_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ReferenceCompileError, match="schema field does not exist"):
        _compile(schema_root)


def test_manifest_path_traversal_missing_file_and_duplicate_claim_refuse(tmp_path: Path) -> None:
    traversal_root = _copy_fixture(tmp_path / "traversal")
    manifest_path = traversal_root / "fourfold.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["code_files"][0] = "../outside.py"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ReferenceCompileError, match="stay inside"):
        _compile(traversal_root)

    missing_root = _copy_fixture(tmp_path / "missing")
    (missing_root / "src" / "knowledge_hub" / "search.py").unlink()
    with pytest.raises(ReferenceCompileError, match="declared file is missing"):
        _compile(missing_root)

    duplicate_root = _copy_fixture(tmp_path / "duplicate")
    manifest_path = duplicate_root / "fourfold.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["claims"].append(copy.deepcopy(manifest["claims"][0]))
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ReferenceCompileError, match="duplicate semantic claim"):
        _compile(duplicate_root)


def test_source_mutation_changes_forest_and_snapshot_identity(tmp_path: Path) -> None:
    root = _copy_fixture(tmp_path)
    before = _compile(root)
    search_path = root / "src" / "knowledge_hub" / "search.py"
    search_path.write_text(
        search_path.read_text(encoding="utf-8") + "\n# evidence-bearing mutation\n",
        encoding="utf-8",
    )
    after = _compile(root)

    assert before.forest.content_sha256 != after.forest.content_sha256
    assert before.snapshot.digest != after.snapshot.digest


def test_contract_hardening_refuses_empty_complete_plane_duplicate_nodes_and_repacked_claims() -> None:
    with pytest.raises(ValueError, match="complete plane must contain"):
        PlaneSnapshot(
            plane="code",
            source_revision=REVISION,
            status="complete",
            evidence_sha256s=("1" * 64,),
        )

    result = _compile(FIXTURE)
    snapshot = result.snapshot
    planes = list(snapshot.planes)
    repeated = snapshot.plane_map["code"].node_ids[0]
    type_plane = snapshot.plane_map["type"]
    planes[1] = PlaneSnapshot(
        plane="type",
        source_revision=REVISION,
        status="complete",
        node_ids=(*type_plane.node_ids, repeated),
        relation_sha256s=type_plane.relation_sha256s,
        evidence_sha256s=type_plane.evidence_sha256s,
    )
    with pytest.raises(ValueError, match="exactly one plane"):
        FourfoldSnapshot(
            repository_id=snapshot.repository_id,
            source_revision=REVISION,
            source_forest_sha256=snapshot.source_forest_sha256,
            planes=tuple(planes),
            bindings=(),
            provenance=snapshot.provenance,
        )

    original = snapshot.bindings[0]
    repacked = CrossPlaneBinding(
        source_plane=original.source_plane,
        source_node_id=original.source_node_id,
        target_plane=original.target_plane,
        target_node_id=original.target_node_id,
        relation=original.relation,
        source_revision=REVISION,
        evidence_sha256s=("f" * 64,),
    )
    provenance = ContractProvenance(
        origin="test.repacked",
        source_revision=REVISION,
        created_at=NOW,
        input_digests=(
            snapshot.source_forest_sha256,
            *(plane.digest for plane in snapshot.planes),
            original.digest,
            repacked.digest,
        ),
    )
    with pytest.raises(ValueError, match="same semantic claim"):
        FourfoldSnapshot(
            repository_id=snapshot.repository_id,
            source_revision=REVISION,
            source_forest_sha256=snapshot.source_forest_sha256,
            planes=snapshot.planes,
            bindings=(original, repacked),
            provenance=provenance,
        )
