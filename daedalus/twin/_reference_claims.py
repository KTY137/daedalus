"""Deterministic verification of declared cross-plane reference claims."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from ..schemas import _identifier
from ..spine.envelope import canonical_sha
from ..structcore.forest import ForestEdge
from ._reference_common import CLAIM_KEYS, REFERENCE_SCHEMA, ReferenceCompileError, safe_relpath, strict_object
from ._reference_inventory import Inventory, normalized_link
from .contracts import CrossPlaneBinding


def _binding(*, source_plane: str, source: str, target_plane: str, target: str,
             relation: str, revision: str, proof: Mapping[str, Any], digests) -> CrossPlaneBinding:
    evidence = tuple(sorted({*digests, canonical_sha(proof)}))
    return CrossPlaneBinding(
        source_plane=source_plane, source_node_id=source,
        target_plane=target_plane, target_node_id=target,
        relation=relation, source_revision=revision, evidence_sha256s=evidence,
    )


def verify_claims(
    claims_value: Any,
    *,
    inventory: Inventory,
    code_files: tuple[str, ...],
    knowledge_files: tuple[str, ...],
    file_sha: Mapping[str, str],
    revision: str,
) -> tuple[list[CrossPlaneBinding], list[ForestEdge], list[dict[str, Any]]]:
    if isinstance(claims_value, (str, bytes)) or not isinstance(claims_value, Sequence):
        raise ReferenceCompileError("claims must be a sequence")
    if not claims_value:
        raise ReferenceCompileError("claims must not be empty")
    bindings: list[CrossPlaneBinding] = []
    edges: list[ForestEdge] = []
    canonical: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()

    for index, raw in enumerate(claims_value):
        if not isinstance(raw, Mapping):
            raise ReferenceCompileError(f"claims[{index}] must be an object")
        kind = raw.get("kind")
        if kind not in CLAIM_KEYS:
            raise ReferenceCompileError(f"claims[{index}].kind is unsupported: {kind!r}")
        claim = strict_object(raw, allowed=CLAIM_KEYS[kind], label=f"claims[{index}]")
        proof = {"schema": REFERENCE_SCHEMA, **claim}
        canonical.append(proof)

        if kind == "code_declares_type":
            code_file = safe_relpath(claim["code_file"], "claim.code_file")
            type_file = safe_relpath(claim["type_file"], "claim.type_file")
            name = _identifier(claim["type_name"], "claim.type_name")
            if code_file not in code_files or type_file not in code_files:
                raise ReferenceCompileError("code_declares_type files must be declared code files")
            source, target = f"code:file:{code_file}", f"type:{type_file}#{name}"
            if target not in inventory.plane_nodes["type"]:
                raise ReferenceCompileError(f"declared type does not exist: {target}")
            key = (kind, source, target)
            binding = _binding(source_plane="code", source=source, target_plane="type", target=target,
                               relation="declares_type", revision=revision, proof=proof,
                               digests=(file_sha[code_file], file_sha[type_file]))
        elif kind in {"type_matches_csv_field", "type_matches_schema_field"}:
            type_file = safe_relpath(claim["type_file"], "claim.type_file")
            type_name = _identifier(claim["type_name"], "claim.type_name")
            type_field = _identifier(claim["type_field"], "claim.type_field")
            if (type_name, type_field) not in inventory.dataclass_fields.get(type_file, set()):
                raise ReferenceCompileError(f"dataclass field does not exist: {type_file}#{type_name}.{type_field}")
            source = f"type:field:{type_file}#{type_name}.{type_field}"
            if kind == "type_matches_csv_field":
                data_file = safe_relpath(claim["csv_file"], "claim.csv_file")
                data_field = _identifier(claim["csv_field"], "claim.csv_field")
                if data_field not in inventory.csv_fields.get(data_file, set()):
                    raise ReferenceCompileError(f"CSV field does not exist: {data_file}#{data_field}")
                target = f"data:field:{data_file}#{data_field}"
                relation = "materializes_as"
            else:
                data_file = safe_relpath(claim["schema_file"], "claim.schema_file")
                data_field = _identifier(claim["schema_field"], "claim.schema_field")
                if data_field not in inventory.schema_fields.get(data_file, set()):
                    raise ReferenceCompileError(f"schema field does not exist: {data_file}#{data_field}")
                target = f"data:schema-field:{data_file}#{data_field}"
                relation = "constrained_by"
            key = (kind, source, target)
            binding = _binding(source_plane="type", source=source, target_plane="data", target=target,
                               relation=relation, revision=revision, proof=proof,
                               digests=(file_sha[type_file], file_sha[data_file]))
        else:
            wiki = safe_relpath(claim["wiki_file"], "claim.wiki_file")
            link = claim["link_target"]
            if not isinstance(link, str) or not link:
                raise ReferenceCompileError("claim.link_target must be non-empty")
            plane = claim["target_plane"]
            target = claim["target_node_id"]
            if plane not in {"code", "type", "data"}:
                raise ReferenceCompileError("wiki_documents_node target_plane must be code, type, or data")
            if not isinstance(target, str) or not target:
                raise ReferenceCompileError("claim.target_node_id must be non-empty")
            if wiki not in knowledge_files:
                raise ReferenceCompileError("wiki_documents_node wiki_file must be declared knowledge")
            target_path = normalized_link(wiki, link)
            if target_path not in inventory.wiki_links.get(wiki, set()):
                raise ReferenceCompileError(f"wiki page does not contain declared link: {wiki} -> {link}")
            if target not in inventory.plane_nodes[plane]:
                raise ReferenceCompileError(f"wiki target node does not exist: {target}")
            if target_path not in file_sha:
                raise ReferenceCompileError(f"wiki claim target is not a declared evidence file: {target_path}")
            source = f"knowledge:doc:{wiki}"
            key = (kind, source, plane, target)
            binding = _binding(source_plane="knowledge", source=source, target_plane=plane, target=target,
                               relation="documents", revision=revision, proof=proof,
                               digests=(file_sha[wiki], file_sha[target_path]))

        if key in seen:
            raise ReferenceCompileError(f"duplicate semantic claim in manifest: {key}")
        seen.add(key)
        bindings.append(binding)
        edges.append(ForestEdge(binding.source_node_id, binding.target_node_id, binding.relation,
                                True, evidence=binding.evidence_sha256s))
    return bindings, edges, canonical
