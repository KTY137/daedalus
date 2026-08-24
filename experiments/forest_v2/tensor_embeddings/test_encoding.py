"""Contract and determinism tests for role/filler encoding."""
from __future__ import annotations

import math
from dataclasses import replace

import pytest

from experiments.forest_v2.s06_cards.node_cards import ProvenanceBook, build_card
from experiments.forest_v2.tensor_embeddings.algebra import (
    cp_separable_contraction,
    flattened_cosine,
    frobenius_norm,
)
from experiments.forest_v2.tensor_embeddings.contracts import (
    ContractError,
    SeparableKernel,
    canonical_json_bytes,
)
from experiments.forest_v2.tensor_embeddings.encoding import (
    EncodedArtifact,
    HashingFillerBackend,
    MAX_SOURCE_EVIDENCE_BYTES,
    PrecomputedFillerBackend,
    RoleFields,
    TensorProductEncoder,
    canonical_source_digest,
    default_spec,
    fields_from_node_card,
    infer_plane,
    validate_source_binding_evidence,
)
from experiments.forest_v2.tensor_embeddings.retrievers import FROZEN_HASH_SEEDS
from experiments.forest_v2.tensor_embeddings.index import (
    IndexContractError,
    IndexDocument,
    TensorIndex,
)


def test_hash_encoding_is_deterministic_normalized_and_budgeted() -> None:
    spec = default_spec(seed=11)
    encoder = TensorProductEncoder(spec)
    kwargs = {
        "source_id": "src/parser.py",
        "source_digest": canonical_source_digest("def parse_value(): pass"),
        "revision": "parent-revision",
        "plane": "code",
    }
    left = encoder.encode(
        RoleFields(
            path="src/parser.py",
            symbol="parse_value",
            content="def parse_value(): return payload",
            neighbor="calls decode_value",
        ),
        **kwargs,
    )
    right = encoder.encode(left.fields, **kwargs)
    assert left == right
    assert left.tensor.canonical_bytes() == right.tensor.canonical_bytes()
    assert frobenius_norm(left.tensor) == pytest.approx(1.0, abs=1e-12)
    assert spec.dense_scalar_count == 512
    assert left.tensor.rank == 4
    assert left.source_binding == "caller_asserted"


def test_verified_binding_cannot_be_minted_or_relabelled_by_generic_callers() -> None:
    encoder = TensorProductEncoder(default_spec())
    checked = encoder.encode_candidate(
        "src/parser.py", "def parser(): pass", blob="git-sha", revision="r1"
    )

    with pytest.raises(ValueError, match="checking adapter"):
        EncodedArtifact(
            source_id=checked.source_id,
            source_digest=checked.source_digest,
            source_binding="visible_content_sha256_verified",
            revision=checked.revision,
            plane=checked.plane,
            backend_id=checked.backend_id,
            tensor=checked.tensor,
            fields=checked.fields,
            source_evidence=checked.fields.content,
        )
    with pytest.raises(ValueError, match="does not address"):
        replace(checked, source_digest="sha256:" + "0" * 64)
    with pytest.raises(ValueError, match="must equal fields.path"):
        replace(checked, source_id="src/other.py")


@pytest.mark.parametrize(
    ("symbol", "neighbor"),
    (
        ("caller_supplied_symbol", ""),
        ("parser", "caller supplied graph edge"),
    ),
)
def test_visible_content_binding_refuses_unbound_role_views(
    symbol: str, neighbor: str
) -> None:
    encoder = TensorProductEncoder(default_spec())
    content = "def parser(): pass"
    fields = RoleFields(
        path="src/parser.py",
        symbol=symbol,
        content=content,
        neighbor=neighbor,
    )

    with pytest.raises(ValueError, match="derived from checked content"):
        encoder.encode_visible_fields(
            fields,
            source_id=fields.path,
            source_digest=canonical_source_digest(content),
            revision="r1",
            plane="code",
        )


def test_hash_filler_coordinates_are_role_independent_for_every_frozen_seed() -> None:
    text = "ParserConfiguration parse_record storage schema"
    for seed in FROZEN_HASH_SEEDS:
        spec = default_spec(seed=seed)
        backend = HashingFillerBackend(seed)
        fillers = tuple(
            backend.embed(text, role=role, spec=spec) for role in spec.roles
        )
        assert all(filler == fillers[0] for filler in fillers[1:])


@pytest.mark.parametrize("seed", (True, -1, 2**63))
def test_hash_backend_refuses_noncanonical_seed_values(seed: object) -> None:
    with pytest.raises(ValueError, match="hash seed"):
        HashingFillerBackend(seed)  # type: ignore[arg-type]


def test_hash_backend_identity_cannot_be_relabeled() -> None:
    with pytest.raises(ValueError, match="backend_id is frozen"):
        HashingFillerBackend(11, backend_id="precomputed-filler:forged")


def test_encoder_cross_role_contraction_uses_shared_filler_semantics() -> None:
    spec = default_spec(seed=11)
    encoder = TensorProductEncoder(spec)
    text = "parse record schema"
    digest = canonical_source_digest(text)
    path_bound = encoder.encode(
        RoleFields(path=text),
        source_id="path-view",
        source_digest=digest,
        revision="r1",
        plane="code",
    )
    symbol_bound = encoder.encode(
        RoleFields(symbol=text),
        source_id="symbol-view",
        source_digest=digest,
        revision="r1",
        plane="code",
    )
    identity_plane = tuple(
        tuple(1.0 if row == column else 0.0 for column in range(len(spec.planes)))
        for row in range(len(spec.planes))
    )
    role_matrix = tuple(
        tuple(
            0.75
            if (row, column) == (spec.roles.index("path"), spec.roles.index("symbol"))
            else (1.0 if row == column else 0.0)
            for column in range(len(spec.roles))
        )
        for row in range(len(spec.roles))
    )
    kernel = SeparableKernel(spec, identity_plane, role_matrix)

    # One-hot role binding makes flattened cosine orthogonal, while the
    # declared cross-role operator sees a feature dot of exactly one.  A
    # role-salted hash would turn this 0.75 into accidental collision noise.
    assert flattened_cosine(path_bound.tensor, symbol_bound.tensor) == 0.0
    assert cp_separable_contraction(
        path_bound.tensor, symbol_bound.tensor, kernel
    ) == pytest.approx(0.75, abs=1e-12, rel=1e-12)


def test_query_plane_is_uniform_unit_and_document_is_one_hot() -> None:
    encoder = TensorProductEncoder(default_spec())
    query = encoder.encode_query("update parser schema", query_id="q", revision="r")
    document = encoder.encode_candidate(
        "src/parser.py", "def parser(): pass", blob="git-sha", revision="r"
    )
    expected = (0.5, 0.5, 0.5, 0.5)
    assert all(term.plane == expected for term in query.tensor.terms)
    assert all(term.plane == (1.0, 0.0, 0.0, 0.0) for term in document.tensor.terms)
    assert query.source_binding == "query_content_sha256_verified"
    assert document.source_binding == "visible_content_sha256_verified"
    assert document.source_digest == canonical_source_digest("def parser(): pass")


def test_candidate_never_treats_an_unresolved_sha_label_as_verified_source() -> None:
    encoder = TensorProductEncoder(default_spec())
    content = "def actual_source(): pass"
    artifact = encoder.encode_candidate(
        "src/a.py", content, blob="sha256:" + "0" * 64, revision="r1"
    )
    assert artifact.source_digest == canonical_source_digest(content)
    assert artifact.source_binding == "visible_content_sha256_verified"


@pytest.mark.parametrize(
    ("path", "plane"),
    (
        ("pkg/api.pyi", "type"),
        ("schemas/user.schema.json", "type"),
        ("fixtures/users.json", "data"),
        ("docs/design.md", "knowledge"),
        ("web/component.tsx", "code"),
        ("web/theme.css", "code"),
    ),
)
def test_plane_mapping_mints_no_fifth_plane(path: str, plane: str) -> None:
    assert infer_plane(path) == plane


def test_precomputed_backend_is_strict_about_key_dimension_and_finiteness() -> None:
    spec = default_spec()
    text = "parser"
    key = PrecomputedFillerBackend.key(text, "content")
    backend = PrecomputedFillerBackend({key: [1.0] * spec.feature_dimension})
    assert len(backend.embed(text, role="content", spec=spec)) == 32
    assert backend.backend_id.startswith("precomputed-filler:")
    assert backend.backend_id == PrecomputedFillerBackend(
        {key: [1.0] * spec.feature_dimension}
    ).backend_id
    with pytest.raises(KeyError):
        backend.embed("missing", role="content", spec=spec)
    short = PrecomputedFillerBackend({key: [1.0]})
    with pytest.raises(ValueError, match="expected 32"):
        short.embed(text, role="content", spec=spec)
    with pytest.raises(ValueError, match="finite"):
        PrecomputedFillerBackend({key: [math.nan] * spec.feature_dimension})


def test_precomputed_backend_identity_binds_frozen_vector_contents() -> None:
    spec = default_spec()
    key = PrecomputedFillerBackend.key("value", "content")
    source = {key: [1.0] * spec.feature_dimension}
    backend = PrecomputedFillerBackend(source)
    source[key][0] = 99.0
    assert backend.embed("value", role="content", spec=spec)[0] == 1.0
    changed = PrecomputedFillerBackend({key: [2.0] * spec.feature_dimension})
    assert changed.backend_id != backend.backend_id
    with pytest.raises(ValueError, match="does not address"):
        PrecomputedFillerBackend(
            {key: [1.0] * spec.feature_dimension}, backend_id=changed.backend_id
        )


def test_empty_and_invalid_inputs_refuse() -> None:
    encoder = TensorProductEncoder(default_spec(), HashingFillerBackend(11))
    digest = canonical_source_digest("")
    with pytest.raises(ValueError, match="no token-bearing role"):
        encoder.encode(
            RoleFields(),
            source_id="empty",
            source_digest=digest,
            revision="r",
            plane="code",
        )
    with pytest.raises(ValueError, match="unknown plane"):
        encoder.encode(
            RoleFields(content="value"),
            source_id="x",
            source_digest=canonical_source_digest("value"),
            revision="r",
            plane="presentation",
        )
    with pytest.raises(ValueError, match="must match TensorSpec"):
        TensorProductEncoder(default_spec(seed=11), HashingFillerBackend(23))
    with pytest.raises(ValueError, match="65536-byte cap"):
        encoder.encode_candidate(
            "src/large.py", "x" * 65_537, blob="large", revision="r"
        )


def test_invalid_unicode_surrogates_fail_at_contract_boundaries() -> None:
    with pytest.raises(ContractError, match="Unicode surrogate"):
        canonical_json_bytes({"source_id": "\ud800"})
    with pytest.raises(ValueError, match="Unicode surrogate"):
        RoleFields(path="\ud800")

    encoder = TensorProductEncoder(default_spec())
    ordinary = encoder.encode(
        RoleFields(content="value"),
        source_id="source",
        source_digest=canonical_source_digest("value"),
        revision="r1",
        plane="code",
    )
    with pytest.raises(ValueError, match="source_id.*Unicode surrogate"):
        replace(ordinary, source_id="\ud800")
    with pytest.raises(ValueError, match="revision.*Unicode surrogate"):
        replace(ordinary, revision="\ud800")


def test_node_card_adapter_uses_declared_roles_and_preserves_identity() -> None:
    record = {
        "plane": "code",
        "kind": "function",
        "path": "src/math.py",
        "qualname": "add",
        "start_line": 1,
        "end_line": 2,
        "text": "def add(left, right): return left + right",
        "signature": "(left, right)",
        "doc": "Add two values.",
        "neighbors": [
            {
                "relation": "calls",
                "direction": "out",
                "node_id": "code://src/math.py#function:coerce",
                "kind": "function",
                "name": "coerce",
            }
        ],
    }
    book = ProvenanceBook()
    provenance = {"source": "fixture"}
    provenance_id = book.add(provenance)
    card = build_card(record, revision="abc123", provenance=provenance_id)
    fields = fields_from_node_card(card, provenance_book=book)
    assert fields.path == "src/math.py"
    assert "add" in fields.symbol
    assert "calls" in fields.neighbor
    encoded = TensorProductEncoder(default_spec()).encode_node_card(
        card, provenance_book=book
    )
    assert encoded.source_id == card["card_id"]
    assert encoded.source_digest == card["card_id"]
    assert encoded.source_binding == "node_card_provenance_verified"
    assert encoded.revision == "abc123"
    restored = TensorIndex.from_bytes(TensorIndex.build([encoded]).canonical_bytes())
    assert restored.documents[0].source_binding == "node_card_provenance_verified"

    payload = restored.documents[0].to_dict()
    forged_fields = RoleFields(
        path="src/other.py",
        symbol="forged",
        content="forged bytes",
        neighbor="",
    )
    forged_tensor = TensorProductEncoder(encoded.tensor.spec).encode(
        forged_fields,
        source_id=encoded.source_id,
        source_digest=encoded.source_digest,
        revision=encoded.revision,
        plane=encoded.plane,
    ).tensor
    payload["fields"] = forged_fields.as_mapping()
    payload["tensor"] = forged_tensor.to_dict()
    with pytest.raises(IndexContractError, match="yields different role fields"):
        IndexDocument.from_dict(payload, encoded.tensor.spec)

    with pytest.raises(ValueError, match="does not resolve"):
        fields_from_node_card(card, provenance_book=ProvenanceBook())


def test_transport_source_evidence_enforces_the_frozen_byte_cap() -> None:
    evidence = "x" * (MAX_SOURCE_EVIDENCE_BYTES + 1)
    with pytest.raises(ValueError, match="byte cap"):
        validate_source_binding_evidence(
            source_id="src/large.py",
            source_digest=canonical_source_digest(evidence),
            source_binding="visible_content_sha256_verified",
            source_evidence=evidence,
            revision="r",
            plane="code",
            fields=RoleFields(path="src/large.py", content=evidence),
        )
