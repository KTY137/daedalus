"""Access-control regression for prompt-bound knowledge correlation output."""
from __future__ import annotations

import runpy

import pytest

from daedalus.twin.knowledge_access import (
    KnowledgeAccessPolicy,
    build_access_scoped_context,
)
from daedalus.twin.knowledge_correlation import (
    CorrelationPolicy,
    KnowledgeCorrelationError,
    correlate_knowledge,
)
from daedalus.twin.knowledge_sources import (
    combine_knowledge_corpora,
    ingest_confluence_dump,
    ingest_obsidian_vault,
)


_FIXTURE = runpy.run_path("tests/twin/test_knowledge_dump_crucible.py")
_twin = _FIXTURE["_twin"]
CREATED_AT = _FIXTURE["CREATED_AT"]


def _correlated():
    forest, snapshot = _twin()
    confluence = ingest_confluence_dump(
        {
            "schema": "daedalus-confluence-dump/1",
            "pages": [
                {
                    "page_id": "11",
                    "version": 4,
                    "title": "Sensor Bias Contract",
                    "space_key": "E4",
                    "authority": "accepted_architecture",
                    "access_class": "internal",
                    "body_storage": (
                        "<h1>Sensor bias</h1>"
                        "<p><code>Event.voltage</code> is required for every measurement.</p>"
                    ),
                }
            ],
        },
        instance_id="institute-confluence",
        imported_at=CREATED_AT,
    )
    obsidian = ingest_obsidian_vault(
        {
            "private-note.md": (
                "# Sensor bias\n"
                "`Event.voltage` may be omitted while debugging.\n"
            )
        },
        vault_id="private-research",
        source_revision="vault-9",
        imported_at=CREATED_AT,
        authority="personal_note",
        access_class="private",
    )
    corpus = combine_knowledge_corpora(
        "access-crucible",
        confluence,
        obsidian,
    )
    result = correlate_knowledge(
        snapshot=snapshot,
        forest=forest,
        corpus=corpus,
        policy=CorrelationPolicy(min_proposal_score=0.58),
    )
    return snapshot, corpus, result


def test_default_agent_context_withholds_private_obsidian_claims() -> None:
    snapshot, corpus, result = _correlated()
    context = build_access_scoped_context(
        result,
        snapshot=snapshot,
        corpus=corpus,
        objective="Rename Event.voltage without exposing private notes.",
        anchor_node_ids=("type:field:src/events.py#Event.voltage",),
    )

    body = str(context.to_dict())
    assert "is required for every measurement" in body
    assert "may be omitted while debugging" not in body
    assert context.policy.allowed_access_classes == ("internal", "public")
    assert any(source_id.startswith("obsidian:") for source_id in context.withheld_source_ids)
    assert context.withheld_claim_sha256s
    assert not set(context.included_source_ids).intersection(context.withheld_source_ids)


def test_private_claim_requires_explicit_access_scope_and_remains_non_authoritative() -> None:
    snapshot, corpus, result = _correlated()
    context = build_access_scoped_context(
        result,
        snapshot=snapshot,
        corpus=corpus,
        objective="Audit all bias knowledge including private notes.",
        anchor_node_ids=("type:field:src/events.py#Event.voltage",),
        access_policy=KnowledgeAccessPolicy(
            allowed_access_classes=("public", "internal", "private"),
        ),
    )

    body = str(context.to_dict())
    assert "may be omitted while debugging" in body
    private_bundles = [
        bundle
        for bundle in context.capsule.bundles
        if bundle.source_authority == "personal_note"
    ]
    assert private_bundles
    assert not any(
        proposal.eligible_for_verification
        for bundle in private_bundles
        for proposal in bundle.proposals
    )


def test_access_boundary_refuses_corpus_substitution() -> None:
    snapshot, corpus, result = _correlated()
    foreign = ingest_obsidian_vault(
        {"other.md": "# Other\n`Event.voltage` is discussed here.\n"},
        vault_id="other",
        source_revision="1",
        imported_at=CREATED_AT,
    )
    with pytest.raises(KnowledgeCorrelationError, match="does not bind"):
        build_access_scoped_context(
            result,
            snapshot=snapshot,
            corpus=foreign,
            objective="Attempt corpus substitution.",
            anchor_node_ids=("type:field:src/events.py#Event.voltage",),
        )

    assert result.corpus_sha256 == corpus.digest


def test_access_policy_is_canonical_and_fail_closed() -> None:
    assert KnowledgeAccessPolicy(
        allowed_access_classes=("internal", "public", "internal")
    ).allowed_access_classes == ("internal", "public")
    with pytest.raises(KnowledgeCorrelationError, match="at least one"):
        KnowledgeAccessPolicy(allowed_access_classes=())
    with pytest.raises(KnowledgeCorrelationError, match="unknown"):
        KnowledgeAccessPolicy(allowed_access_classes=("secret",))
