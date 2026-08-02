"""Gold-bound quality report for the knowledge correlation crucible."""
from __future__ import annotations

import runpy

from daedalus.twin.knowledge_correlation import CorrelationPolicy, correlate_knowledge
from daedalus.twin.knowledge_evaluation import (
    CorrelationGoldCase,
    evaluate_knowledge_correlation,
)
from daedalus.twin.knowledge_sources import (
    combine_knowledge_corpora,
    ingest_confluence_dump,
    ingest_obsidian_vault,
)


_FIXTURE = runpy.run_path("tests/twin/test_knowledge_dump_crucible.py")
_twin = _FIXTURE["_twin"]
CREATED_AT = _FIXTURE["CREATED_AT"]


def _evaluated_fixture():
    forest, snapshot = _twin()
    confluence = ingest_confluence_dump(
        {
            "schema": "daedalus-confluence-dump/1",
            "pages": [
                {
                    "page_id": "1",
                    "version": 3,
                    "title": "Sensor Bias",
                    "space_key": "E4",
                    "authority": "accepted_architecture",
                    "body_storage": (
                        "<p><code>Event.voltage</code> is required and persisted.</p>"
                        "<p><code>CalibrationService</code> publishes gain corrections.</p>"
                    ),
                }
            ],
        },
        instance_id="confluence",
        imported_at=CREATED_AT,
    )
    obsidian = ingest_obsidian_vault(
        {
            "old.md": "# Sensor bias\n`Event.voltage` may be omitted.\n",
            "hardware.md": "# Hardware\n`Device.output_voltage` controls output voltage.\n",
        },
        vault_id="notes",
        source_revision="7",
        imported_at=CREATED_AT,
    )
    corpus = combine_knowledge_corpora("evaluation-crucible", confluence, obsidian)
    result = correlate_knowledge(
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
        policy=CorrelationPolicy(min_proposal_score=0.58),
    )
    bundle_by_text = {bundle.claim.text: bundle for bundle in result.bundles}
    event = next(bundle for text, bundle in bundle_by_text.items() if "required and persisted" in text)
    calibration = next(bundle for text, bundle in bundle_by_text.items() if "CalibrationService" in text)
    stale = next(bundle for text, bundle in bundle_by_text.items() if "may be omitted" in text)
    output = next(bundle for text, bundle in bundle_by_text.items() if "Device.output_voltage" in text)
    cases = (
        CorrelationGoldCase(
            case_id="accepted-event-contract",
            claim_sha256=event.claim.digest,
            required_node_ids=(
                "type:field:src/events.py#Event.voltage",
                "data:schema-field:schemas/measurement.schema.json#voltage",
            ),
            forbidden_node_ids=("type:field:src/device.py#Device.output_voltage",),
            allow_extra_node_ids=True,
        ),
        CorrelationGoldCase(
            case_id="unresolved-calibration-service",
            claim_sha256=calibration.claim.digest,
            required_unresolved_mentions=("CalibrationService",),
            allow_extra_node_ids=True,
        ),
        CorrelationGoldCase(
            case_id="stale-optional-claim",
            claim_sha256=stale.claim.digest,
            required_node_ids=(
                "type:field:src/events.py#Event.voltage",
                "data:schema-field:schemas/measurement.schema.json#voltage",
            ),
            forbidden_node_ids=("type:field:src/device.py#Device.output_voltage",),
            required_contradiction_kinds=("requiredness-conflict",),
            allow_extra_node_ids=True,
        ),
        CorrelationGoldCase(
            case_id="unrelated-output-voltage",
            claim_sha256=output.claim.digest,
            required_node_ids=("type:field:src/device.py#Device.output_voltage",),
            forbidden_node_ids=(
                "type:field:src/events.py#Event.voltage",
                "data:schema-field:schemas/measurement.schema.json#voltage",
            ),
            allow_extra_node_ids=False,
        ),
    )
    return result, cases


def test_correlation_crucible_closes_only_against_positive_and_negative_gold() -> None:
    result, cases = _evaluated_fixture()
    report = evaluate_knowledge_correlation(result, cases)

    assert report.closed is True
    assert report.blockers == ()
    assert report.precision == 1.0
    assert report.recall == 1.0
    assert report.contradiction_recall == 1.0
    assert report.unresolved_recall == 1.0
    assert report.forbidden_hits == 0
    assert report.authority_escalations == 0
    assert report.to_dict()["gate_closure_claimed"] is False
    assert report.digest == evaluate_knowledge_correlation(result, tuple(reversed(cases))).digest

    wrong = (
        *cases,
        CorrelationGoldCase(
            case_id="deliberately-impossible",
            claim_sha256="f" * 64,
            required_node_ids=("type:missing#Impossible",),
        ),
    )
    failed = evaluate_knowledge_correlation(result, wrong)
    assert failed.closed is False
    assert failed.false_negatives >= 1
    assert any("claim missing" in blocker for blocker in failed.blockers)
