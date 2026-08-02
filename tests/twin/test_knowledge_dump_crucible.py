"""One end-to-end crucible for knowledge dump ingestion and Fourfold correlation."""
from __future__ import annotations

from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_sha
from daedalus.structcore.forest import ForestEdge, ForestNode, KnowledgeForest
from daedalus.twin.contracts import CrossPlaneBinding, FourfoldSnapshot, PlaneSnapshot
from daedalus.twin.knowledge_correlation import (
    CorrelationPolicy,
    build_context_capsule,
    correlate_knowledge,
)
from daedalus.twin.knowledge_sources import (
    combine_knowledge_corpora,
    ingest_confluence_dump,
    ingest_mediawiki_dump,
    ingest_obsidian_vault,
)


REVISION = "1" * 40
CREATED_AT = "2026-08-02T20:00:00Z"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64


def _twin() -> tuple[KnowledgeForest, FourfoldSnapshot]:
    nodes = (
        ForestNode(
            "code:file:src/events.py",
            "source_file",
            {"path": "src/events.py"},
        ),
        ForestNode(
            "code:symbol:src/acquisition.py#configure_bias",
            "symbol",
            {"path": "src/acquisition.py", "name": "configure_bias"},
        ),
        ForestNode(
            "code:symbol:src/storage.py#write_measurement",
            "symbol",
            {"path": "src/storage.py", "name": "write_measurement"},
        ),
        ForestNode(
            "type:src/events.py#Event",
            "type",
            {"path": "src/events.py", "name": "Event"},
        ),
        ForestNode(
            "type:field:src/events.py#Event.voltage",
            "field",
            {"path": "src/events.py", "type": "Event", "name": "voltage"},
        ),
        ForestNode(
            "type:field:src/device.py#Device.output_voltage",
            "field",
            {"path": "src/device.py", "type": "Device", "name": "output_voltage"},
        ),
        ForestNode(
            "data:schema:schemas/measurement.schema.json",
            "data_schema",
            {"path": "schemas/measurement.schema.json"},
        ),
        ForestNode(
            "data:schema-field:schemas/measurement.schema.json#voltage",
            "data_schema_field",
            {
                "path": "schemas/measurement.schema.json",
                "name": "voltage",
                "required": True,
            },
        ),
        ForestNode(
            "data:schema-field:schemas/device.schema.json#output_voltage",
            "data_schema_field",
            {
                "path": "schemas/device.schema.json",
                "name": "output_voltage",
                "required": True,
            },
        ),
        ForestNode(
            "knowledge:doc:docs/readme.md",
            "document",
            {"path": "docs/readme.md", "name": "Repository README"},
        ),
    )
    edges = (
        ForestEdge(
            "type:src/events.py#Event",
            "type:field:src/events.py#Event.voltage",
            "has_field",
            True,
            evidence=("src/events.py",),
        ),
        ForestEdge(
            "data:schema:schemas/measurement.schema.json",
            "data:schema-field:schemas/measurement.schema.json#voltage",
            "has_property",
            True,
            evidence=("schemas/measurement.schema.json",),
        ),
    )
    forest = KnowledgeForest(
        root=".",
        nodes=nodes,
        edges=edges,
        hyperedges=(),
        provenance={"source_revision": REVISION, "compiler": "knowledge-crucible"},
    )
    planes = (
        PlaneSnapshot(
            "code",
            REVISION,
            "complete",
            (
                "code:file:src/events.py",
                "code:symbol:src/acquisition.py#configure_bias",
                "code:symbol:src/storage.py#write_measurement",
            ),
            (),
            (SHA_A,),
        ),
        PlaneSnapshot(
            "type",
            REVISION,
            "complete",
            (
                "type:src/events.py#Event",
                "type:field:src/events.py#Event.voltage",
                "type:field:src/device.py#Device.output_voltage",
            ),
            (canonical_sha(edges[0].to_dict()),),
            (SHA_B,),
        ),
        PlaneSnapshot(
            "data",
            REVISION,
            "complete",
            (
                "data:schema:schemas/measurement.schema.json",
                "data:schema-field:schemas/measurement.schema.json#voltage",
                "data:schema-field:schemas/device.schema.json#output_voltage",
            ),
            (canonical_sha(edges[1].to_dict()),),
            (SHA_C,),
        ),
        PlaneSnapshot(
            "knowledge",
            REVISION,
            "complete",
            ("knowledge:doc:docs/readme.md",),
            (),
            (SHA_D,),
        ),
    )
    binding = CrossPlaneBinding(
        source_plane="type",
        source_node_id="type:field:src/events.py#Event.voltage",
        target_plane="data",
        target_node_id="data:schema-field:schemas/measurement.schema.json#voltage",
        relation="constrained_by",
        source_revision=REVISION,
        evidence_sha256s=(SHA_A, SHA_C),
    )
    provenance = ContractProvenance(
        origin="tests.knowledge-correlation-crucible",
        source_revision=REVISION,
        created_at=CREATED_AT,
        input_digests=(
            forest.content_sha256,
            *(plane.digest for plane in planes),
            binding.digest,
        ),
        trace_id="knowledge-correlation-crucible",
    )
    return forest, FourfoldSnapshot(
        repository_id="tct-crucible",
        source_revision=REVISION,
        source_forest_sha256=forest.content_sha256,
        planes=planes,
        bindings=(binding,),
        provenance=provenance,
    )


def test_external_knowledge_dump_correlation_crucible() -> None:
    forest, snapshot = _twin()

    confluence_payload = {
        "schema": "daedalus-confluence-dump/1",
        "pages": [
            {
                "page_id": "18439177",
                "version": 23,
                "title": "Sensor Bias Storage",
                "space_key": "E4",
                "labels": ["sensor bias", "bias voltage"],
                "authority": "accepted_architecture",
                "body_storage": """
                    <h1>Sensor bias</h1>
                    <p>Each measurement stores the configured <code>Event.voltage</code>
                    sensor bias. The field is required.</p>
                    <p>The <code>CalibrationService</code> publishes gain corrections.</p>
                """,
            }
        ],
    }
    obsidian_files = {
        "old-plan.md": """---
title: Old TCT Plan
aliases: [sensor bias]
---
# Sensor bias
`Event.voltage` may be omitted.
""",
        "hardware.md": """# Output voltage
`Device.output_voltage` controls the oscilloscope output voltage.
""",
    }
    mediawiki_payload = {
        "schema": "daedalus-mediawiki-dump/1",
        "pages": [
            {
                "page_id": "42",
                "revision_id": "9001",
                "title": "Bias voltage",
                "categories": ["Detector physics"],
                "wikitext": """
== Bias voltage ==
Bias voltage is an operating voltage applied to a detector.
""",
            }
        ],
    }

    confluence = ingest_confluence_dump(
        confluence_payload,
        instance_id="institute-confluence",
        imported_at=CREATED_AT,
    )
    obsidian = ingest_obsidian_vault(
        obsidian_files,
        vault_id="research-notes",
        source_revision="vault-rev-7",
        imported_at=CREATED_AT,
    )
    mediawiki = ingest_mediawiki_dump(
        mediawiki_payload,
        instance_id="wikipedia-en",
        imported_at=CREATED_AT,
    )
    corpus = combine_knowledge_corpora(
        "tct-knowledge-dump-v1",
        confluence,
        obsidian,
        mediawiki,
    )
    reordered = combine_knowledge_corpora(
        "tct-knowledge-dump-v1",
        mediawiki,
        obsidian,
        confluence,
    )
    assert corpus.digest == reordered.digest

    policy = CorrelationPolicy(
        min_proposal_score=0.58,
        max_proposals_per_claim=10,
        max_context_bundles=16,
    )
    result = correlate_knowledge(
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
        policy=policy,
    )
    replay = correlate_knowledge(
        snapshot=snapshot,
        forest=forest,
        corpus=reordered,
        policy=policy,
    )
    assert result.digest == replay.digest
    assert result.snapshot_sha256 == snapshot.digest
    assert result.forest_sha256 == forest.content_sha256
    assert all(proposal.state in {"proposed", "source_supported"} for proposal in result.proposals)
    assert not any(proposal.to_dict().get("assurance") == "trusted" for proposal in result.proposals)

    confluence_bundles = [
        bundle
        for bundle in result.bundles
        if bundle.source_authority == "accepted_architecture"
    ]
    event_claim = next(
        bundle for bundle in confluence_bundles if "Event.voltage" in bundle.claim.text
    )
    event_targets = {proposal.target_node_id: proposal for proposal in event_claim.proposals}
    assert "type:field:src/events.py#Event.voltage" in event_targets
    assert "data:schema-field:schemas/measurement.schema.json#voltage" in event_targets
    assert event_targets["type:field:src/events.py#Event.voltage"].eligible_for_verification
    assert event_targets[
        "data:schema-field:schemas/measurement.schema.json#voltage"
    ].eligible_for_verification
    assert any(
        signal.kind == "verified-neighbor"
        for signal in event_targets[
            "data:schema-field:schemas/measurement.schema.json#voltage"
        ].signals
    )

    unresolved_claim = next(
        bundle for bundle in confluence_bundles if "CalibrationService" in bundle.claim.text
    )
    assert [item.mention for item in unresolved_claim.unresolved] == ["CalibrationService"]

    old_note = next(
        bundle
        for bundle in result.bundles
        if bundle.source_authority == "personal_note"
        and "may be omitted" in bundle.claim.text
    )
    assert any(
        proposal.target_node_id == "type:field:src/events.py#Event.voltage"
        for proposal in old_note.proposals
    )
    assert not any(proposal.eligible_for_verification for proposal in old_note.proposals)
    assert any(
        contradiction.kind == "requiredness-conflict"
        and contradiction.target_node_id
        == "data:schema-field:schemas/measurement.schema.json#voltage"
        for contradiction in old_note.contradictions
    )

    output_claim = next(
        bundle
        for bundle in result.bundles
        if "Device.output_voltage" in bundle.claim.text
    )
    output_targets = {proposal.target_node_id for proposal in output_claim.proposals}
    assert "type:field:src/device.py#Device.output_voltage" in output_targets
    assert "type:field:src/events.py#Event.voltage" not in output_targets
    assert "data:schema-field:schemas/measurement.schema.json#voltage" not in output_targets

    external = [
        bundle
        for bundle in result.bundles
        if bundle.source_authority == "external_reference"
    ]
    assert external
    assert not any(
        proposal.eligible_for_verification
        for bundle in external
        for proposal in bundle.proposals
    )

    capsule = build_context_capsule(
        result,
        snapshot=snapshot,
        objective="Rename Event.voltage to Event.bias_voltage without touching output_voltage.",
        anchor_node_ids=("type:field:src/events.py#Event.voltage",),
        policy=policy,
    )
    assert capsule.digest == build_context_capsule(
        replay,
        snapshot=snapshot,
        objective="Rename Event.voltage to Event.bias_voltage without touching output_voltage.",
        anchor_node_ids=("type:field:src/events.py#Event.voltage",),
        policy=policy,
    ).digest
    capsule_text = str(capsule.to_dict())
    assert "Event.voltage" in capsule_text
    assert "requiredness-conflict" in capsule_text
    assert "Device.output_voltage" not in capsule_text
    assert capsule.source_revision == REVISION
    assert capsule.snapshot_sha256 == snapshot.digest
    assert capsule.corpus_sha256 == corpus.digest
