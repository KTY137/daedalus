"""Compile one bounded wiki application into an evidence-bound Fourfold Twin.

The manifest declares a finite source set and semantic claims. Claims are not
trusted: Python AST, CSV, JSON Schema, and Markdown evidence must reproduce each
claim before it becomes a verified cross-plane binding.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from ..schemas import ContractProvenance, _identifier, _revision
from ..spine.envelope import canonical_sha
from ..structcore.forest import KnowledgeForest
from ._reference_claims import verify_claims
from ._reference_common import (
    MANIFEST_KEYS, REFERENCE_SCHEMA, ReferenceCompileError, decode_text,
    read_file, safe_relpath, sha256_bytes, strict_object, strict_path_list,
)
from ._reference_inventory import build_inventory
from .contracts import FOURFOLD_PLANES, FourfoldSnapshot, PlaneSnapshot


@dataclass(frozen=True)
class ReferenceCompileResult:
    forest: KnowledgeForest
    snapshot: FourfoldSnapshot
    manifest_sha256: str
    file_sha256s: tuple[tuple[str, str], ...]

    @property
    def file_digest_map(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self.file_sha256s))


def compile_reference_project(
    root: str | Path,
    *,
    source_revision: str,
    created_at: str,
    manifest_name: str = "fourfold.json",
    trace_id: str | None = None,
) -> ReferenceCompileResult:
    revision = _revision(source_revision, "source_revision")
    project_root = Path(root).resolve()
    manifest_rel = safe_relpath(manifest_name, "manifest_name")
    manifest_bytes = read_file(project_root, manifest_rel)
    try:
        raw = json.loads(decode_text(manifest_bytes, manifest_rel))
    except json.JSONDecodeError as exc:
        raise ReferenceCompileError(f"manifest JSON is invalid: {exc}") from exc
    manifest = strict_object(raw, allowed=MANIFEST_KEYS, label="reference manifest")
    if manifest["schema"] != REFERENCE_SCHEMA:
        raise ReferenceCompileError(f"manifest schema must be {REFERENCE_SCHEMA!r}")
    repository_id = _identifier(manifest["repository_id"], "repository_id")
    code_files = strict_path_list(manifest["code_files"], "code_files")
    data_files = strict_path_list(manifest["data_files"], "data_files")
    knowledge_files = strict_path_list(manifest["knowledge_files"], "knowledge_files")
    classified = code_files + data_files + knowledge_files
    if len(set(classified)) != len(classified):
        raise ReferenceCompileError("a declared file may belong to only one semantic plane")
    if any(not p.endswith(".py") for p in code_files):
        raise ReferenceCompileError("code_files must contain only .py files")
    if any(not p.endswith((".csv", ".json")) for p in data_files):
        raise ReferenceCompileError("data_files must contain only .csv or .json files")
    if any(not p.endswith(".md") for p in knowledge_files):
        raise ReferenceCompileError("knowledge_files must contain only .md files")

    file_bytes = {path: read_file(project_root, path) for path in classified}
    file_sha = {path: sha256_bytes(data) for path, data in file_bytes.items()}
    inv = build_inventory(
        project_root, code_files=code_files, data_files=data_files,
        knowledge_files=knowledge_files, file_bytes=file_bytes,
    )
    bindings, claim_edges, canonical_claims = verify_claims(
        manifest["claims"], inventory=inv, code_files=code_files,
        knowledge_files=knowledge_files, file_sha=file_sha, revision=revision,
    )
    inv.edges.extend(claim_edges)
    manifest_sha = canonical_sha({
        "schema": REFERENCE_SCHEMA,
        "repository_id": repository_id,
        "code_files": list(code_files),
        "data_files": list(data_files),
        "knowledge_files": list(knowledge_files),
        "claims": sorted(canonical_claims, key=canonical_sha),
    })
    forest = KnowledgeForest(
        root=".",
        nodes=tuple(sorted(inv.nodes, key=lambda n: n.id)),
        edges=tuple(sorted(inv.edges, key=lambda e: (e.source, e.target, e.relation, canonical_sha(e.to_dict())))),
        hyperedges=(),
        provenance={
            "compiler": "daedalus.twin.reference_compiler",
            "manifest_sha256": manifest_sha,
            "source_revision": revision,
        },
    )
    forest_digest = forest.content_sha256
    node_plane = {node: plane for plane, nodes in inv.plane_nodes.items() for node in nodes}
    relation_digests = {plane: [] for plane in FOURFOLD_PLANES}
    for edge in forest.edges:
        source_plane, target_plane = node_plane[edge.source], node_plane[edge.target]
        if source_plane == target_plane:
            relation_digests[source_plane].append(canonical_sha(edge.to_dict()))
    plane_files = {
        "code": code_files, "type": code_files,
        "data": data_files, "knowledge": knowledge_files,
    }
    planes = tuple(
        PlaneSnapshot(
            plane=plane, source_revision=revision, status="complete",
            node_ids=tuple(inv.plane_nodes[plane]),
            relation_sha256s=tuple(relation_digests[plane]),
            evidence_sha256s=tuple({manifest_sha, *(file_sha[p] for p in plane_files[plane])}),
        )
        for plane in FOURFOLD_PLANES
    )
    provenance = ContractProvenance(
        origin="daedalus.twin.reference-compiler",
        source_revision=revision,
        created_at=created_at,
        input_digests=tuple({
            manifest_sha, forest_digest, *file_sha.values(),
            *(p.digest for p in planes), *(b.digest for b in bindings),
        }),
        trace_id=trace_id,
    )
    snapshot = FourfoldSnapshot(
        repository_id=repository_id, source_revision=revision,
        source_forest_sha256=forest_digest, planes=planes,
        bindings=tuple(bindings), provenance=provenance,
    )
    return ReferenceCompileResult(
        forest=forest, snapshot=snapshot, manifest_sha256=manifest_sha,
        file_sha256s=tuple(sorted(file_sha.items())),
    )


__all__ = [
    "REFERENCE_SCHEMA", "ReferenceCompileError", "ReferenceCompileResult",
    "compile_reference_project",
]
