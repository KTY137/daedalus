"""Persistence, tamper and proposal-authority tests for the tensor index."""
from __future__ import annotations

import copy
import json
from dataclasses import replace

import pytest

from experiments.forest_v2.tensor_embeddings import index as index_module
from experiments.forest_v2.tensor_embeddings.contracts import SeparableKernel
from experiments.forest_v2.tensor_embeddings.encoding import (
    RoleFields,
    TensorProductEncoder,
    canonical_source_digest,
    default_spec,
)
from experiments.forest_v2.tensor_embeddings.index import (
    AUTHORITY,
    IndexContractError,
    IndexDocument,
    TensorIndex,
)
from experiments.forest_v2.tensor_embeddings.stats import SPEC_DIGEST


PLANE_KERNEL = (
    (1.0, 0.5, 0.5, 0.5),
    (0.5, 1.0, 0.25, 0.25),
    (0.5, 0.25, 1.0, 0.5),
    (0.5, 0.25, 0.5, 1.0),
)
ROLE_KERNEL = (
    (1.0, 0.75, 0.25, 0.1),
    (0.75, 1.0, 0.5, 0.25),
    (0.25, 0.5, 1.0, 0.25),
    (0.1, 0.25, 0.25, 1.0),
)


def _fixture():
    spec = default_spec(seed=11)
    encoder = TensorProductEncoder(spec)
    artifacts = [
        encoder.encode_candidate(
            "src/parser.py", "def parse_record(value): return value", blob="b1", revision="r1"
        ),
        encoder.encode_candidate(
            "docs/parser.md", "Parser record format and examples", blob="b2", revision="r1"
        ),
    ]
    query = encoder.encode_query("parse record", query_id="q1", revision="r1")
    kernel = SeparableKernel(spec, PLANE_KERNEL, ROLE_KERNEL)
    return artifacts, query, kernel


@pytest.mark.parametrize("representation", ("cp", "dense", "tt"))
def test_index_roundtrip_is_deterministic_for_every_storage_form(representation: str) -> None:
    artifacts, _, _ = _fixture()
    index = TensorIndex.build(artifacts, representation=representation)
    restored = TensorIndex.from_bytes(index.canonical_bytes())
    assert restored == index
    assert restored.canonical_bytes() == index.canonical_bytes()
    assert restored.index_id == index.index_id
    assert restored.experiment_spec_digest == SPEC_DIGEST
    assert all(document.tensor.spec.dense_scalar_count == 512 for document in index.documents)
    receipt = index.storage_receipt()
    assert receipt["documents"] == len(index.documents)
    assert receipt["dense_equivalent_scalars"] == len(index.documents) * 512
    assert receipt["canonical_bytes"] == len(index.canonical_bytes())


def test_search_returns_ranked_unverified_proposals_with_explanation() -> None:
    artifacts, query, kernel = _fixture()
    index = TensorIndex.build(artifacts)
    hits = index.search(query, mode="structured", kernel=kernel, limit=2)
    assert len(hits) == 2
    assert {hit.source_id for hit in hits} == {item.source_id for item in artifacts}
    assert all(hit.to_dict()["authority"] == AUTHORITY for hit in hits)
    assert all(
        hit.to_dict()["source_binding"] == "visible_content_sha256_verified"
        for hit in hits
    )
    assert all(hit.revision == "r1" for hit in hits)
    assert all(hit.index_id == index.index_id for hit in hits)
    assert all(hit.corpus_digest == index.corpus_digest for hit in hits)
    assert all(hit.spec_id == index.spec.spec_id for hit in hits)
    assert all(hit.backend_id == index.backend_id for hit in hits)
    assert all(hit.kernel_id == index.kernel.kernel_id for hit in hits)
    assert all(hit.query_tensor_id == query.tensor.tensor_id for hit in hits)
    assert hits[0].score >= hits[1].score
    assert hits[0].explanation
    summary = hits[0].to_dict()["explanation_summary"]
    assert summary["shown_terms"] <= summary["total_terms"]
    assert summary["numerator"] is not None
    cosine = index.search(query, mode="cosine", limit=2)
    identity = index.search(query, mode="identity", limit=2)
    assert [(hit.source_id, hit.score) for hit in cosine] == [
        (hit.source_id, hit.score) for hit in identity
    ]


def test_index_identity_mode_executes_the_independent_contraction(monkeypatch) -> None:
    artifacts, query, _ = _fixture()
    index = TensorIndex.build(artifacts)
    expected = [(hit.source_id, hit.score) for hit in index.search(query, mode="identity")]
    monkeypatch.setattr(index_module, "flattened_cosine", lambda *_args: -0.123)
    assert [(hit.source_id, hit.score) for hit in index.search(query, mode="identity")] == expected
    assert all(hit.score == -0.123 for hit in index.search(query, mode="cosine"))


def test_any_mutated_source_factor_spec_or_digest_refuses() -> None:
    artifacts, _, _ = _fixture()
    index = TensorIndex.build(artifacts)
    mutations = []
    source = copy.deepcopy(index.to_dict())
    source["documents"][0]["source_digest"] = "sha256:" + "0" * 64
    mutations.append(source)
    source_evidence = copy.deepcopy(index.to_dict())
    source_evidence["documents"][0]["source_evidence"] = "forged content"
    mutations.append(source_evidence)
    factor = copy.deepcopy(index.to_dict())
    factor["documents"][0]["tensor"]["terms"][0]["weight"] += 0.1
    mutations.append(factor)
    spec = copy.deepcopy(index.to_dict())
    spec["spec"]["seed"] = 23
    mutations.append(spec)
    digest = copy.deepcopy(index.to_dict())
    digest["index_id"] = "index:tampered"
    mutations.append(digest)
    experiment_spec = copy.deepcopy(index.to_dict())
    experiment_spec["experiment_spec_digest"] = "sha256:" + "0" * 64
    mutations.append(experiment_spec)
    kernel = copy.deepcopy(index.to_dict())
    kernel["kernel"]["plane_matrix"][0][0] = 0.125
    mutations.append(kernel)
    kernel_id = copy.deepcopy(index.to_dict())
    kernel_id["kernel_id"] = "kernel:tampered"
    mutations.append(kernel_id)
    for payload in mutations:
        with pytest.raises(ValueError):
            TensorIndex.from_dict(payload)


def test_resigned_source_claim_cannot_launder_an_unrelated_tensor() -> None:
    artifacts, _, _ = _fixture()
    index = TensorIndex.build(artifacts)
    document = copy.deepcopy(index.to_dict()["documents"][0])
    document["source_evidence"] = "forged source bytes"
    document["source_digest"] = canonical_source_digest("forged source bytes")
    document["fields"]["content"] = "forged source bytes"
    with pytest.raises(IndexContractError, match="does not match its replayed"):
        IndexDocument.from_dict(document, index.spec)


def test_original_evidence_cannot_be_reused_for_coordinated_fields_and_tensor() -> None:
    artifacts, _, _ = _fixture()
    index = TensorIndex.build(artifacts)
    document = copy.deepcopy(index.to_dict()["documents"][0])
    forged_fields = RoleFields(
        path=document["fields"]["path"],
        symbol="malicious_symbol",
        content="malicious substituted tensor bytes",
        neighbor="malicious_neighbor",
    )
    forged_tensor = TensorProductEncoder(index.spec).encode(
        forged_fields,
        source_id=document["source_id"],
        source_digest=document["source_digest"],
        revision=document["revision"],
        plane=document["plane"],
    ).tensor
    document["fields"] = forged_fields.as_mapping()
    document["tensor"] = forged_tensor.to_dict()

    with pytest.raises(IndexContractError, match="evidence differs from fields.content"):
        IndexDocument.from_dict(document, index.spec)


@pytest.mark.parametrize("role", ("symbol", "neighbor"))
def test_verified_index_refuses_recomputed_unbound_role_view(role: str) -> None:
    artifacts, _, _ = _fixture()
    index = TensorIndex.build(artifacts)
    document = copy.deepcopy(index.to_dict()["documents"][0])
    fields_values = dict(document["fields"])
    fields_values[role] = "caller supplied unverified role bytes"
    forged_fields = RoleFields(**fields_values)
    forged_tensor = TensorProductEncoder(index.spec).encode(
        forged_fields,
        source_id=document["source_id"],
        source_digest=document["source_digest"],
        revision=document["revision"],
        plane=document["plane"],
    ).tensor
    document["fields"] = forged_fields.as_mapping()
    document["tensor"] = forged_tensor.to_dict()

    with pytest.raises(IndexContractError, match="derived from checked content"):
        IndexDocument.from_dict(document, index.spec)


@pytest.mark.parametrize("bad_index_id", (None, "", False, 0, "index:tampered"))
def test_loader_rejects_missing_empty_or_wrong_index_id(bad_index_id) -> None:
    artifacts, _, _ = _fixture()
    payload = copy.deepcopy(TensorIndex.build(artifacts).to_dict())
    payload["index_id"] = bad_index_id
    with pytest.raises(IndexContractError, match="index_id"):
        TensorIndex.from_dict(payload)


def test_loader_rejects_empty_document_array() -> None:
    artifacts, _, _ = _fixture()
    payload = copy.deepcopy(TensorIndex.build(artifacts).to_dict())
    payload["documents"] = []
    payload["corpus_digest"] = TensorIndex.compute_corpus_digest(())
    with pytest.raises(IndexContractError, match="must not be empty"):
        TensorIndex.from_dict(payload)


def test_builder_rejects_more_than_the_frozen_document_cap() -> None:
    artifacts, _, _ = _fixture()
    with pytest.raises(IndexContractError, match="document cap"):
        TensorIndex.build([artifacts[0]] * 65_537)


def test_conflicting_duplicate_source_and_mixed_revision_refuse() -> None:
    artifacts, _, _ = _fixture()
    same = TensorIndex.build([artifacts[0], artifacts[0]])
    assert len(same.documents) == 1
    encoder = TensorProductEncoder(artifacts[0].tensor.spec)
    conflict = encoder.encode_candidate(
        artifacts[0].source_id, "changed content", blob="other", revision="r1"
    )
    with pytest.raises(IndexContractError, match="conflicting content"):
        TensorIndex.build([artifacts[0], conflict])
    other_revision = encoder.encode_candidate(
        "src/other.py", "def other(): pass", blob="b3", revision="r2"
    )
    with pytest.raises(IndexContractError, match="revision"):
        TensorIndex.build([artifacts[0], other_revision])


def test_query_artifacts_cannot_be_laundered_into_document_index() -> None:
    _, query, _ = _fixture()
    with pytest.raises(IndexContractError, match="one-hot plane"):
        TensorIndex.build([query])


def test_loader_rejects_unknown_duplicate_keys_and_nonfinite_json() -> None:
    artifacts, _, _ = _fixture()
    index = TensorIndex.build(artifacts)
    payload = index.to_dict()
    payload["unknown"] = True
    with pytest.raises(IndexContractError, match="key mismatch"):
        TensorIndex.from_dict(payload)
    with pytest.raises(IndexContractError, match="duplicate JSON key"):
        TensorIndex.from_bytes('{"schema":"a","schema":"b"}')
    raw = index.canonical_bytes().decode().replace('"seed":11', '"seed":NaN')
    with pytest.raises(IndexContractError, match="non-finite"):
        TensorIndex.from_bytes(raw)


def test_query_revision_backend_and_mode_boundaries_refuse() -> None:
    artifacts, query, kernel = _fixture()
    index = TensorIndex.build(artifacts)
    encoder = TensorProductEncoder(query.tensor.spec)
    stale = encoder.encode_query("parse", query_id="q", revision="r0")
    with pytest.raises(IndexContractError, match="revision"):
        index.search(stale, mode="cosine")
    with pytest.raises(IndexContractError, match="unsupported search mode"):
        index.search(query, mode="magic")
    with pytest.raises(IndexContractError, match="index-bound kernel"):
        index.search(query, mode="structured")
    with pytest.raises(IndexContractError, match="does not accept a kernel"):
        index.search(query, mode="cosine", kernel=kernel)
    alternate = SeparableKernel.identity(index.spec)
    with pytest.raises(IndexContractError, match="index-bound kernel"):
        index.search(query, mode="structured", kernel=alternate)
    with pytest.raises(IndexContractError, match="plane-unspecified"):
        index.search(artifacts[0], mode="cosine")
    forged_tensor = TensorProductEncoder(query.tensor.spec).encode_query(
        "different query", query_id=query.source_id, revision=query.revision
    ).tensor
    with pytest.raises(IndexContractError, match="does not match its replayed evidence"):
        index.search(replace(query, tensor=forged_tensor), mode="cosine")


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("source_id", ""),
        ("source_digest", "not-a-digest"),
        ("source_binding", "bogus"),
        ("revision", ""),
        ("tensor_id", ""),
        ("mode", "bogus"),
    ),
)
def test_search_hit_contract_refuses_malformed_identity(field: str, value: str) -> None:
    artifacts, query, _ = _fixture()
    hit = TensorIndex.build(artifacts).search(query, mode="cosine", limit=1)[0]
    with pytest.raises(IndexContractError):
        replace(hit, **{field: value})


def test_index_bytes_are_json_and_module_owns_no_writer() -> None:
    artifacts, _, _ = _fixture()
    index = TensorIndex.build(artifacts)
    assert json.loads(index.canonical_bytes())["index_id"] == index.index_id
    assert not hasattr(index, "save")
    assert not hasattr(TensorIndex, "write")
