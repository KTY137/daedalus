"""Deterministic role/filler encoding for the tensor-embedding experiment.

This module deliberately contains no model client.  A filler backend maps one
declared role text to one fixed-width vector; the reference backend below uses
signed feature hashing so the complete experiment is replayable offline.  A
future semantic backend may implement :class:`FillerBackend`, but it must obey
the same dimension, source-digest and scalar budgets.

The output is a CP representation of ``T[plane, role, feature]``.  It is only
a retrieval proposal representation; source identity and revision stay on the
enclosing :class:`EncodedArtifact`.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Protocol, Sequence, runtime_checkable

from .contracts import CPTensor, CPTerm, TensorSpec


_ALNUM = re.compile(r"[A-Za-z0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_SYMBOL = re.compile(
    r"(?m)^\s*(?:async\s+def|def|class|function|interface|type|enum)\s+"
    r"([A-Za-z_$][A-Za-z0-9_$]*)"
)
_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")

DEFAULT_PLANES = ("code", "type", "data", "knowledge")
DEFAULT_ROLES = ("path", "symbol", "content", "neighbor")
ROLE_WEIGHTS = {
    "path": 1.0,
    "symbol": 1.0,
    "content": 1.0,
    "neighbor": 1.0,
}
HASH_FEATURE_FAMILY = "shared-word-plus-prefix4-suffix4/2"
HASH_BACKEND_ID = "signed-subword-hash-shared-word-p4-s4/2"
MAX_ROLE_FIELD_BYTES = 65_536
MAX_SOURCE_EVIDENCE_BYTES = 262_144
SOURCE_BINDINGS = frozenset(
    {
        "caller_asserted",
        "visible_content_sha256_verified",
        "query_content_sha256_verified",
        "node_card_provenance_verified",
    }
)
_VERIFIED_BINDING_CAPABILITY = object()


def canonical_source_digest(value: str | bytes) -> str:
    if isinstance(value, str):
        try:
            raw = value.encode("utf-8", "strict")
        except UnicodeEncodeError as exc:
            raise ValueError("source text contains an invalid Unicode surrogate") from exc
    else:
        raw = bytes(value)
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _iter_word_tokens(text: str) -> Iterable[str]:
    for match in _ALNUM.finditer(text):
        chunk = match.group(0)
        for piece in _CAMEL.split(chunk):
            lowered = piece.lower()
            if len(lowered) > 1:
                yield lowered


def word_tokens(text: str) -> tuple[str, ...]:
    """Stable tokenizer matching the s09 lexical boundary rules."""

    return tuple(_iter_word_tokens(text))


def _hashed_coordinate(seed: int, feature: str, dimension: int) -> tuple[int, float]:
    """Map one feature without retaining cross-run lexical state."""

    seed_bytes = int(seed).to_bytes(8, "big", signed=True)
    # Fillers must inhabit one shared coordinate space.  Salting by role would
    # turn every off-diagonal role-kernel comparison into hash-collision noise
    # instead of comparing the same lexical/subword feature across roles.
    payload = feature.encode("utf-8")
    digest = hashlib.blake2b(payload, key=seed_bytes, digest_size=16).digest()
    bucket = int.from_bytes(digest[:8], "big") % dimension
    return bucket, (1.0 if digest[8] & 1 else -1.0)


@runtime_checkable
class FillerBackend(Protocol):
    """The narrow seam for a budget-matched filler-vector implementation."""

    backend_id: str

    def embed(self, text: str, *, role: str, spec: TensorSpec) -> Sequence[float]:
        ...


@dataclass(frozen=True)
class HashingFillerBackend:
    """Offline signed hashing with no learned state and no hidden vocabulary."""

    seed: int
    backend_id: str = HASH_BACKEND_ID

    def __post_init__(self) -> None:
        if isinstance(self.seed, bool) or type(self.seed) is not int:
            raise ValueError("hash seed must be an integer")
        if not 0 <= self.seed <= (2**63 - 1):
            raise ValueError("hash seed must fit an unsigned 63-bit integer")
        if self.backend_id != HASH_BACKEND_ID:
            raise ValueError("hashing backend_id is frozen and cannot be relabeled")

    def embed(self, text: str, *, role: str, spec: TensorSpec) -> tuple[float, ...]:
        if role not in spec.roles:
            raise ValueError(f"unknown role {role!r}")
        values = [0.0] * spec.feature_dimension
        # Expand only unique tokens.  Expanding every occurrence first made a
        # 64 KiB source file pay for the same prefix/suffix hundreds of times.
        # ``findall`` performs the byte scan in the regex engine.  CamelCase
        # morphology is still present through boundary prefixes/suffixes; the
        # public lexical tokenizer remains aligned with s09 for query roles.
        token_counts = Counter(
            token.lower() for token in _ALNUM.findall(text) if len(token) > 1
        )
        for token, count in token_counts.items():
            # One full-token feature plus the frozen four-character boundary
            # subwords.  This keeps lexical morphology while bounding work at
            # three projections per unique token.
            features = ["w:" + token]
            if len(token) >= 4:
                features.append("p4:" + token[:4])
                features.append("s4:" + token[-4:])
            for feature in features:
                bucket, sign = _hashed_coordinate(
                    self.seed, feature, spec.feature_dimension
                )
                values[bucket] += sign * count
        norm = math.sqrt(sum(value * value for value in values))
        if norm:
            values = [value / norm for value in values]
        return tuple(values)


@dataclass(frozen=True)
class PrecomputedFillerBackend:
    """Explicit semantic-vector fixture/backend with content-addressed keys.

    Keys are ``sha256(role + NUL + text)``.  Missing inputs refuse instead of
    silently falling back to a different representation.
    """

    vectors: Mapping[str, Sequence[float]]
    backend_id: str = ""

    def __post_init__(self) -> None:
        normalized: dict[str, tuple[float, ...]] = {}
        for key, raw_vector in self.vectors.items():
            if type(key) is not str or not _SHA256.fullmatch(key):
                raise ValueError("precomputed filler keys must be sha256 content addresses")
            if any(
                isinstance(value, bool) or not isinstance(value, (int, float))
                for value in raw_vector
            ):
                raise ValueError("precomputed filler vectors must contain real numbers")
            vector = tuple(float(value) for value in raw_vector)
            if not vector or not all(math.isfinite(value) for value in vector):
                raise ValueError("precomputed filler vectors must be non-empty and finite")
            normalized[key] = vector
        if not normalized:
            raise ValueError("precomputed filler backend must contain at least one vector")
        payload = {
            key: list(normalized[key]) for key in sorted(normalized)
        }
        raw = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        expected = "precomputed-filler:" + hashlib.sha256(raw).hexdigest()
        if self.backend_id and self.backend_id != expected:
            raise ValueError("precomputed filler backend_id does not address its vectors")
        object.__setattr__(self, "vectors", MappingProxyType(normalized))
        object.__setattr__(self, "backend_id", expected)

    @staticmethod
    def key(text: str, role: str) -> str:
        return canonical_source_digest(role + "\x00" + text)

    def embed(self, text: str, *, role: str, spec: TensorSpec) -> tuple[float, ...]:
        key = self.key(text, role)
        if key not in self.vectors:
            raise KeyError(f"no precomputed filler for {key}")
        vector = tuple(self.vectors[key])
        if len(vector) != spec.feature_dimension:
            raise ValueError(
                f"precomputed filler has {len(vector)} values; "
                f"expected {spec.feature_dimension}"
            )
        if not all(math.isfinite(value) for value in vector):
            raise ValueError("precomputed filler contains a non-finite value")
        return vector


@dataclass(frozen=True)
class RoleFields:
    path: str = ""
    symbol: str = ""
    content: str = ""
    neighbor: str = ""

    def __post_init__(self) -> None:
        for role, text in self.as_mapping().items():
            if type(text) is not str:
                raise TypeError(f"role field {role} must be text")
            try:
                raw = text.encode("utf-8", "strict")
            except UnicodeEncodeError as exc:
                raise ValueError(
                    f"role field {role} contains an invalid Unicode surrogate"
                ) from exc
            if len(raw) > MAX_ROLE_FIELD_BYTES:
                raise ValueError(
                    f"role field {role} exceeds the frozen 65536-byte cap"
                )

    def as_mapping(self) -> dict[str, str]:
        return {
            "path": self.path,
            "symbol": self.symbol,
            "content": self.content,
            "neighbor": self.neighbor,
        }


@dataclass(frozen=True)
class EncodedArtifact:
    """Revision/source-bound wrapper around a regenerable tensor projection."""

    source_id: str
    source_digest: str
    source_binding: str
    revision: str
    plane: str | None
    backend_id: str
    tensor: CPTensor
    fields: RoleFields
    source_evidence: str = ""
    _binding_capability: object | None = field(
        default=None, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        if type(self.source_id) is not str or not self.source_id:
            raise ValueError("source_id must not be empty")
        try:
            self.source_id.encode("utf-8", "strict")
        except UnicodeEncodeError as exc:
            raise ValueError("source_id contains an invalid Unicode surrogate") from exc
        if type(self.source_digest) is not str or not _SHA256.fullmatch(self.source_digest):
            raise ValueError("source_digest must be a sha256 content address")
        if self.source_binding not in SOURCE_BINDINGS:
            raise ValueError("source_binding must declare how the digest was verified")
        if not isinstance(self.fields, RoleFields):
            raise TypeError("encoded fields must be RoleFields")
        if not isinstance(self.tensor, CPTensor):
            raise TypeError("encoded tensor must be a CPTensor")
        if type(self.source_evidence) is not str:
            raise TypeError("source_evidence must be canonical text")
        try:
            source_evidence_bytes = self.source_evidence.encode("utf-8", "strict")
        except UnicodeEncodeError as exc:
            raise ValueError(
                "source_evidence contains an invalid Unicode surrogate"
            ) from exc
        if len(source_evidence_bytes) > MAX_SOURCE_EVIDENCE_BYTES:
            raise ValueError("source_evidence exceeds the frozen byte cap")
        if type(self.revision) is not str or not self.revision:
            raise ValueError("revision must not be empty")
        try:
            self.revision.encode("utf-8", "strict")
        except UnicodeEncodeError as exc:
            raise ValueError("revision contains an invalid Unicode surrogate") from exc
        if type(self.backend_id) is not str or not self.backend_id:
            raise ValueError("backend_id must not be empty")
        try:
            self.backend_id.encode("utf-8", "strict")
        except UnicodeEncodeError as exc:
            raise ValueError("backend_id contains an invalid Unicode surrogate") from exc
        if self.plane is not None and self.plane not in self.tensor.spec.planes:
            raise ValueError(f"unknown plane {self.plane!r}")
        if self.source_binding == "caller_asserted":
            if self._binding_capability is not None:
                raise ValueError("caller-asserted artifacts cannot carry a verified capability")
            if self.source_evidence:
                raise ValueError("caller-asserted artifacts cannot carry verified evidence")
            return
        if self._binding_capability is not _VERIFIED_BINDING_CAPABILITY:
            raise ValueError(
                "verified source bindings can only be minted by a checking adapter"
            )
        if self.source_binding == "visible_content_sha256_verified":
            if self.source_evidence != self.fields.content:
                raise ValueError("visible-content evidence differs from fields.content")
            if self.source_id != self.fields.path:
                raise ValueError("visible-content source_id must equal fields.path")
            if self.source_digest != canonical_source_digest(self.fields.content):
                raise ValueError("visible-content digest does not address fields.content")
            if self.plane is None or self.plane != infer_plane(self.fields.path):
                raise ValueError("visible-content document plane must match its path")
            if self.fields != fields_from_candidate(
                self.source_id, self.source_evidence
            ):
                raise ValueError(
                    "visible-content role fields must be derived from checked content"
                )
        elif self.source_binding == "query_content_sha256_verified":
            if self.source_evidence != self.fields.content:
                raise ValueError("query evidence differs from fields.content")
            if self.source_digest != canonical_source_digest(self.fields.content):
                raise ValueError("query digest does not address fields.content")
            if self.plane is not None:
                raise ValueError("query binding requires a uniform plane")
            if self.fields != fields_from_query(self.fields.content):
                raise ValueError("query role fields do not match the checked query text")
        elif self.source_binding == "node_card_provenance_verified":
            if self.source_digest != self.source_id:
                raise ValueError("Node Card digest must equal its content-addressed card_id")
            if self.plane is None:
                raise ValueError("Node Card documents require a declared plane")
            _validate_node_card_evidence(
                self.source_evidence,
                source_id=self.source_id,
                revision=self.revision,
                plane=self.plane,
                fields=self.fields,
            )


def default_spec(seed: int = 11, feature_dimension: int = 32) -> TensorSpec:
    return TensorSpec(
        planes=DEFAULT_PLANES,
        roles=DEFAULT_ROLES,
        feature_dimension=feature_dimension,
        seed=seed,
        normalization="global_l2",
    )


def infer_plane(path: str) -> str:
    """Map every eligible text artifact into exactly one Project-Twin plane."""

    normal = path.replace("\\", "/").lower()
    name = PurePosixPath(normal).name
    suffix = PurePosixPath(normal).suffix
    if suffix in {".pyi", ".proto", ".graphql", ".gql"} or any(
        marker in name for marker in ("schema", "types", "typing")
    ):
        return "type"
    if suffix in {".json", ".yaml", ".yml", ".toml", ".csv", ".sql", ".ini", ".cfg"}:
        return "data"
    if suffix in {".md", ".rst", ".txt", ".adoc"}:
        return "knowledge"
    # HTML/CSS and unknown eligible source formats are executable/product
    # implementation evidence here; no fifth "presentation" plane is minted.
    return "code"


def extract_symbols(text: str) -> str:
    return " ".join(match.group(1) for match in _SYMBOL.finditer(text))


def fields_from_candidate(path: str, content: str) -> RoleFields:
    return RoleFields(path=path, symbol=extract_symbols(content), content=content)


def fields_from_query(text: str) -> RoleFields:
    # Queries have no privileged graph neighborhood.  Identifier-like terms
    # are copied to symbol as a declared role view, not inferred from gold.
    identifiers = [token for token in word_tokens(text) if "_" in token or token.isidentifier()]
    return RoleFields(symbol=" ".join(identifiers), content=text)


def fields_from_node_card(
    card: Mapping[str, Any], *, provenance_book: object
) -> RoleFields:
    """Extract declared Node-Card fields with resolvable provenance.

    A syntactically valid provenance reference is not enough for a measured
    input. The caller must supply the matching s06 ``ProvenanceBook`` so the
    reference is resolved and content-address checked before encoding.
    """

    # Import remains experiment-to-experiment and is lazy so this package has
    # no production dependency or import-time side effect.
    from experiments.forest_v2.s06_cards.node_cards import (
        ProvenanceBook,
        validate_card,
    )

    if not isinstance(provenance_book, ProvenanceBook):
        raise TypeError("provenance_book must be an s06 ProvenanceBook")
    problems = validate_card(dict(card), provenance_book)
    if problems:
        raise ValueError("invalid Node Card: " + "; ".join(problems))
    content = card["content"]
    edges = card["neighborhood"]["edges"]
    neighbor_text = " ".join(
        " ".join(
            str(edge.get(key, ""))
            for key in ("relation", "direction", "kind", "name", "node_id")
        )
        for edge in edges
    )
    return RoleFields(
        path=str(card["locator"]["path"]),
        symbol=" ".join(
            str(content.get(key, ""))
            for key in ("name", "qualname", "signature")
        ),
        content=" ".join(
            str(content.get(key, "")) for key in ("text", "doc")
        ),
        neighbor=neighbor_text,
    )


def _canonical_evidence(value: object) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("source evidence must be canonicalizable JSON") from exc


def _strict_evidence_loads(raw: str) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in items:
            if key in value:
                raise ValueError(f"duplicate source-evidence key {key!r}")
            value[key] = item
        return value

    def reject(value: str) -> object:
        raise ValueError(f"non-finite source-evidence number {value} is forbidden")

    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=reject)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("source_evidence is not strict JSON") from exc
    if _canonical_evidence(value) != raw:
        raise ValueError("source_evidence must use canonical JSON bytes")
    return value


def node_card_source_evidence(
    card: Mapping[str, Any], *, provenance_book: object
) -> str:
    """Carry the exact card and resolved provenance needed for index replay."""

    from experiments.forest_v2.s06_cards.node_cards import ProvenanceBook

    if not isinstance(provenance_book, ProvenanceBook):
        raise TypeError("provenance_book must be an s06 ProvenanceBook")
    ref = card.get("provenance")
    block = provenance_book.get(ref) if isinstance(ref, str) else None
    if block is None:
        raise ValueError("Node Card provenance ref does not resolve")
    evidence = _canonical_evidence({"card": dict(card), "provenance_block": block})
    if len(evidence.encode("utf-8")) > MAX_SOURCE_EVIDENCE_BYTES:
        raise ValueError("Node Card source evidence exceeds the frozen byte cap")
    return evidence


def _validate_node_card_evidence(
    evidence: str,
    *,
    source_id: str,
    revision: str,
    plane: str,
    fields: RoleFields | None,
) -> None:
    from experiments.forest_v2.s06_cards.node_cards import ProvenanceBook, validate_card

    value = _strict_evidence_loads(evidence)
    if not isinstance(value, Mapping) or set(value) != {"card", "provenance_block"}:
        raise ValueError("Node Card evidence must contain card and provenance_block")
    card = value["card"]
    block = value["provenance_block"]
    if not isinstance(card, Mapping) or not isinstance(block, Mapping):
        raise ValueError("Node Card evidence entries must be objects")
    ref = card.get("provenance")
    if type(ref) is not str:
        raise ValueError("Node Card evidence has no provenance ref")
    book = ProvenanceBook({ref: dict(block)})
    problems = validate_card(dict(card), book)
    if problems:
        raise ValueError("invalid Node Card source evidence: " + "; ".join(problems))
    # validate_card already checks the native card identity algorithm.
    if card.get("card_id") != source_id:
        raise ValueError("Node Card evidence identifies another card")
    if card.get("revision") != revision or card.get("plane") != plane:
        raise ValueError("Node Card evidence revision or plane differs")
    if fields is not None:
        checked_fields = fields_from_node_card(card, provenance_book=book)
        if checked_fields != fields:
            raise ValueError("Node Card evidence yields different role fields")


def validate_source_binding_evidence(
    *,
    source_id: str,
    source_digest: str,
    source_binding: str,
    source_evidence: str,
    revision: str,
    plane: str | None,
    fields: RoleFields | None = None,
) -> None:
    """Replay the transportable part of a source-binding claim.

    This establishes internal consistency only. It does not authenticate that
    the carried bytes came from an authoritative repository or issuer.
    """

    if type(source_evidence) is not str:
        raise TypeError("source_evidence must be text")
    if len(source_evidence.encode("utf-8")) > MAX_SOURCE_EVIDENCE_BYTES:
        raise ValueError("source_evidence exceeds the frozen byte cap")
    if fields is not None and not isinstance(fields, RoleFields):
        raise TypeError("fields must be RoleFields when supplied")
    if source_binding == "caller_asserted":
        if source_evidence:
            raise ValueError("caller-asserted source must not carry verified evidence")
        return
    if source_binding == "visible_content_sha256_verified":
        if not source_evidence:
            raise ValueError("visible-content binding requires the checked bytes")
        if source_digest != canonical_source_digest(source_evidence):
            raise ValueError("visible-content digest does not address its evidence")
        if plane is None or plane != infer_plane(source_id):
            raise ValueError("visible-content document plane must match its source path")
        if fields is not None:
            if source_evidence != fields.content:
                raise ValueError("visible-content evidence differs from fields.content")
            if source_id != fields.path:
                raise ValueError("visible-content source_id must equal fields.path")
            if plane != infer_plane(fields.path):
                raise ValueError("visible-content plane differs from fields.path")
            if fields != fields_from_candidate(source_id, source_evidence):
                raise ValueError(
                    "visible-content role fields must be derived from checked content"
                )
        return
    if source_binding == "query_content_sha256_verified":
        if source_digest != canonical_source_digest(source_evidence):
            raise ValueError("query digest does not address its evidence")
        if plane is not None:
            raise ValueError("query binding requires a uniform plane")
        if fields is not None and fields != fields_from_query(source_evidence):
            raise ValueError("query evidence yields different role fields")
        return
    if source_binding == "node_card_provenance_verified":
        if plane is None:
            raise ValueError("Node Card binding requires a declared plane")
        _validate_node_card_evidence(
            source_evidence,
            source_id=source_id,
            revision=revision,
            plane=plane,
            fields=fields,
        )
        return
    raise ValueError("unknown source binding")


class TensorProductEncoder:
    """Bind plane, role and filler factors, then globally L2-normalize."""

    def __init__(
        self,
        spec: TensorSpec | None = None,
        backend: FillerBackend | None = None,
    ) -> None:
        self.spec = spec or default_spec()
        self.backend = backend or HashingFillerBackend(self.spec.seed)
        if not isinstance(self.backend, FillerBackend):
            raise TypeError("backend does not satisfy FillerBackend")
        if type(self.backend.backend_id) is not str or not self.backend.backend_id:
            raise ValueError("backend_id must be a non-empty string")
        if (
            isinstance(self.backend, HashingFillerBackend)
            and self.backend.seed != self.spec.seed
        ):
            raise ValueError("hashing backend seed must match TensorSpec.seed")

    def _encode_bound(
        self,
        fields: RoleFields,
        *,
        source_id: str,
        source_digest: str,
        revision: str,
        plane: str | None,
        source_binding: str,
        source_evidence: str,
        binding_capability: object | None,
    ) -> EncodedArtifact:
        if not isinstance(fields, RoleFields):
            raise TypeError("fields must be RoleFields")
        oversized = [
            role
            for role, text in fields.as_mapping().items()
            if len(text.encode("utf-8")) > MAX_ROLE_FIELD_BYTES
        ]
        if oversized:
            raise ValueError(
                "role fields exceed the frozen 65536-byte cap: "
                + ", ".join(oversized)
            )
        if plane is not None and plane not in self.spec.planes:
            raise ValueError(f"unknown plane {plane!r}")
        if plane is None:
            scale = 1.0 / math.sqrt(len(self.spec.planes))
            plane_factor = tuple(scale for _ in self.spec.planes)
        else:
            plane_factor = tuple(1.0 if item == plane else 0.0 for item in self.spec.planes)

        terms: list[CPTerm] = []
        field_map = fields.as_mapping()
        for role_index, role in enumerate(self.spec.roles):
            text = field_map[role]
            if not text or next(iter(_iter_word_tokens(text)), None) is None:
                continue
            filler = tuple(self.backend.embed(text, role=role, spec=self.spec))
            if len(filler) != self.spec.feature_dimension:
                raise ValueError(f"backend returned wrong dimension for role {role!r}")
            if not any(filler):
                continue
            filler_norm = math.sqrt(math.fsum(value * value for value in filler))
            if filler_norm <= 0.0 or not math.isfinite(filler_norm):
                raise ValueError(f"backend returned an invalid vector for role {role!r}")
            filler = tuple(value / filler_norm for value in filler)
            role_factor = tuple(
                1.0 if index == role_index else 0.0
                for index in range(len(self.spec.roles))
            )
            terms.append(
                CPTerm(
                    weight=ROLE_WEIGHTS[role],
                    plane=plane_factor,
                    role=role_factor,
                    feature=filler,
                )
            )
        if not terms:
            raise ValueError("cannot encode an artifact with no token-bearing role")

        # Terms occupy distinct one-hot role fibers; plane, role and filler
        # factors are unit vectors.  Cross-role products are exactly zero, so
        # this is the exact Frobenius norm without materializing 512 entries.
        norm = math.sqrt(math.fsum(term.weight * term.weight for term in terms))
        if norm <= 0.0 or not math.isfinite(norm):
            raise ValueError("encoded tensor has invalid norm")
        normalized = CPTensor(
            spec=self.spec,
            terms=tuple(
                CPTerm(
                    weight=term.weight / norm,
                    plane=term.plane,
                    role=term.role,
                    feature=term.feature,
                )
                for term in terms
            ),
        )
        return EncodedArtifact(
            source_id=source_id,
            source_digest=source_digest,
            source_binding=source_binding,
            revision=revision,
            plane=plane,
            backend_id=self.backend.backend_id,
            tensor=normalized,
            fields=fields,
            source_evidence=source_evidence,
            _binding_capability=binding_capability,
        )

    def encode(
        self,
        fields: RoleFields,
        *,
        source_id: str,
        source_digest: str,
        revision: str,
        plane: str | None,
    ) -> EncodedArtifact:
        """Encode caller-described fields without upgrading their provenance."""

        return self._encode_bound(
            fields,
            source_id=source_id,
            source_digest=source_digest,
            revision=revision,
            plane=plane,
            source_binding="caller_asserted",
            source_evidence="",
            binding_capability=None,
        )

    def encode_visible_fields(
        self,
        fields: RoleFields,
        *,
        source_id: str,
        source_digest: str,
        revision: str,
        plane: str,
    ) -> EncodedArtifact:
        """Encode document fields after checking the visible content binding."""

        if not isinstance(fields, RoleFields):
            raise TypeError("fields must be RoleFields")
        if source_id != fields.path:
            raise ValueError("visible-content source_id must equal fields.path")
        if source_digest != canonical_source_digest(fields.content):
            raise ValueError("source_digest does not address fields.content")
        if plane != infer_plane(fields.path):
            raise ValueError("visible-content plane must match the source path")
        return self._encode_bound(
            fields,
            source_id=source_id,
            source_digest=source_digest,
            revision=revision,
            plane=plane,
            source_binding="visible_content_sha256_verified",
            source_evidence=fields.content,
            binding_capability=_VERIFIED_BINDING_CAPABILITY,
        )

    def encode_candidate(
        self, path: str, content: str, *, blob: str, revision: str
    ) -> EncodedArtifact:
        # ``Candidate.text()`` may be budget-truncated, and a Git/blob label is
        # not independently resolvable inside this pure adapter. Bind exactly
        # the bytes encoded; keep the caller's blob identity in score receipts.
        digest = canonical_source_digest(content)
        return self.encode_visible_fields(
            fields_from_candidate(path, content),
            source_id=path,
            source_digest=digest,
            revision=revision,
            plane=infer_plane(path),
        )

    def encode_query(self, text: str, *, query_id: str, revision: str) -> EncodedArtifact:
        return self._encode_bound(
            fields_from_query(text),
            source_id=query_id,
            source_digest=canonical_source_digest(text),
            revision=revision,
            plane=None,
            source_binding="query_content_sha256_verified",
            source_evidence=text,
            binding_capability=_VERIFIED_BINDING_CAPABILITY,
        )

    def encode_node_card(
        self, card: Mapping[str, Any], *, provenance_book: object
    ) -> EncodedArtifact:
        fields = fields_from_node_card(card, provenance_book=provenance_book)
        evidence = node_card_source_evidence(card, provenance_book=provenance_book)
        return self._encode_bound(
            fields,
            source_id=str(card["card_id"]),
            source_digest=str(card["card_id"]),
            revision=str(card["revision"]),
            plane=str(card["plane"]),
            source_binding="node_card_provenance_verified",
            source_evidence=evidence,
            binding_capability=_VERIFIED_BINDING_CAPABILITY,
        )


__all__ = [
    "DEFAULT_PLANES",
    "DEFAULT_ROLES",
    "EncodedArtifact",
    "FillerBackend",
    "HashingFillerBackend",
    "HASH_BACKEND_ID",
    "HASH_FEATURE_FAMILY",
    "MAX_ROLE_FIELD_BYTES",
    "MAX_SOURCE_EVIDENCE_BYTES",
    "PrecomputedFillerBackend",
    "RoleFields",
    "SOURCE_BINDINGS",
    "TensorProductEncoder",
    "canonical_source_digest",
    "default_spec",
    "extract_symbols",
    "fields_from_candidate",
    "fields_from_node_card",
    "fields_from_query",
    "infer_plane",
    "node_card_source_evidence",
    "validate_source_binding_evidence",
    "word_tokens",
]
