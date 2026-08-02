"""Evidence-preserving correlation between external knowledge and Fourfold nodes.

The engine is deliberately conservative:

* imported prose remains an external, provenance-bearing overlay;
* exact identifiers, explicit node links and repository paths are hard signals;
* learned aliases and lexical similarity only create proposals;
* verified Fourfold bindings may expand a hard anchor across planes;
* no output of this module is a :class:`CrossPlaneBinding` or trusted fact.

This is the first practical bridge from Confluence/Obsidian/MediaWiki dumps to
LLM context.  Embedding and learned rerankers can be added later behind the
``SoftSignalProvider`` protocol without changing the authority model.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, ClassVar, Iterable, Mapping, Protocol, Sequence

from ..spine.envelope import canonical_sha
from ..structcore.forest import ForestNode, KnowledgeForest
from .contracts import FOURFOLD_PLANES, FourfoldSnapshot
from .knowledge_sources import (
    KnowledgeClaim,
    KnowledgeCorpus,
    KnowledgeDocument,
    PROJECT_AUTHORITY_CLASSES,
)

_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_OPTIONAL_RE = re.compile(
    r"\b(optional|may be omitted|can be omitted|not required|nullable)\b",
    re.IGNORECASE,
)
_REQUIRED_RE = re.compile(
    r"\b(required|must be present|must contain|cannot be omitted|non-null)\b",
    re.IGNORECASE,
)
_DEPRECATED_RE = re.compile(r"\b(deprecated|obsolete|legacy|no longer used)\b", re.IGNORECASE)
_NEGATION_RE = re.compile(r"\b(does not exist|is absent|is removed|was deleted)\b", re.IGNORECASE)

_GENERIC_ALIAS_STOPLIST = frozenset(
    {
        "architecture",
        "overview",
        "introduction",
        "notes",
        "documentation",
        "reference",
        "design",
        "data",
        "code",
        "type",
        "knowledge",
        "system",
        "service",
    }
)
_RELATION_BY_PLANE = {
    "code": "documents",
    "type": "documents",
    "data": "describes_schema",
    "knowledge": "correlates_with",
}
_HARD_SIGNAL_KINDS = frozenset(
    {"explicit-node-link", "exact-identifier", "repository-path", "verified-neighbor"}
)


class KnowledgeCorrelationError(ValueError):
    """Raised when correlation inputs violate an authority or identity boundary."""


def _nonempty(value: Any, name: str, *, max_length: int = 5000) -> str:
    if not isinstance(value, str):
        raise KnowledgeCorrelationError(f"{name} must be a string")
    result = value.strip()
    if not result:
        raise KnowledgeCorrelationError(f"{name} must not be empty")
    if "\x00" in result or len(result) > max_length:
        raise KnowledgeCorrelationError(f"{name} is invalid")
    return result


def _digest(value: Any, name: str) -> str:
    result = _nonempty(value, name, max_length=64).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", result):
        raise KnowledgeCorrelationError(f"{name} must be lowercase sha256")
    return result


def _tokens(value: str) -> frozenset[str]:
    return frozenset(token.casefold() for token in _TOKEN_RE.findall(value) if len(token) > 1)


def _normalized_phrase(value: str) -> str:
    return " ".join(token.casefold() for token in _TOKEN_RE.findall(value))


def _tail_aliases(node_id: str) -> set[str]:
    aliases = {node_id}
    tail = node_id.rsplit(":", 1)[-1]
    aliases.add(tail)
    if "#" in tail:
        path, fragment = tail.split("#", 1)
        aliases.add(fragment)
        aliases.add(path.rsplit("/", 1)[-1])
    if "." in tail:
        aliases.add(tail.rsplit(".", 1)[-1])
    if "/" in tail:
        aliases.add(tail.rsplit("/", 1)[-1])
    return {alias for alias in aliases if alias}


def _attribute_scalar(attributes: Mapping[str, Any], key: str) -> str:
    value = attributes.get(key)
    return str(value).strip() if isinstance(value, (str, int, float, bool)) else ""


def _node_aliases(node: ForestNode) -> tuple[str, ...]:
    aliases = _tail_aliases(node.id)
    for key in ("name", "qualified_name", "symbol", "path", "type", "column", "property"):
        value = _attribute_scalar(node.attributes, key)
        if value:
            aliases.add(value)
    type_name = _attribute_scalar(node.attributes, "type")
    field_name = _attribute_scalar(node.attributes, "name")
    if type_name and field_name:
        aliases.add(f"{type_name}.{field_name}")
    return tuple(sorted(aliases, key=str.casefold))


def _path_from_node(node: ForestNode) -> str:
    value = node.attributes.get("path")
    return str(value).replace("\\", "/") if isinstance(value, str) else ""


def _boolean_attribute(attributes: Mapping[str, Any], key: str) -> bool | None:
    value = attributes.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.casefold().strip()
        if lowered in {"true", "yes", "required"}:
            return True
        if lowered in {"false", "no", "optional"}:
            return False
    return None


@dataclass(frozen=True)
class GraphNodeCard:
    """A deterministic, prompt-safe summary of one Fourfold node."""

    node_id: str
    plane: str
    kind: str
    label: str
    path: str
    aliases: tuple[str, ...]
    attributes: tuple[tuple[str, str], ...]
    evidence_sha256s: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "node_id", _nonempty(self.node_id, "node_id"))
        if self.plane not in FOURFOLD_PLANES:
            raise KnowledgeCorrelationError("card plane is not Fourfold")
        object.__setattr__(self, "kind", _nonempty(self.kind, "kind", max_length=300))
        object.__setattr__(self, "label", _nonempty(self.label, "label", max_length=1000))
        object.__setattr__(self, "path", self.path.replace("\\", "/"))
        object.__setattr__(
            self,
            "aliases",
            tuple(sorted({_nonempty(item, "alias", max_length=1500) for item in self.aliases}, key=str.casefold)),
        )
        attrs = tuple(sorted((str(key), str(value)) for key, value in self.attributes))
        if len({key for key, _ in attrs}) != len(attrs):
            raise KnowledgeCorrelationError("card attribute keys must be unique")
        object.__setattr__(self, "attributes", attrs)
        object.__setattr__(
            self,
            "evidence_sha256s",
            tuple(sorted({_digest(item, "evidence_sha256") for item in self.evidence_sha256s})),
        )

    @property
    def attribute_map(self) -> Mapping[str, str]:
        return dict(self.attributes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "plane": self.plane,
            "kind": self.kind,
            "label": self.label,
            "path": self.path,
            "aliases": list(self.aliases),
            "attributes": [{"key": key, "value": value} for key, value in self.attributes],
            "evidence_sha256s": list(self.evidence_sha256s),
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class CorrelationSignal:
    kind: str
    weight: float
    detail: str
    evidence_sha256s: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _nonempty(self.kind, "signal.kind", max_length=200))
        if not 0.0 <= float(self.weight) <= 1.0:
            raise KnowledgeCorrelationError("signal weight must be in [0, 1]")
        object.__setattr__(self, "weight", float(self.weight))
        object.__setattr__(self, "detail", _nonempty(self.detail, "signal.detail", max_length=3000))
        object.__setattr__(
            self,
            "evidence_sha256s",
            tuple(sorted({_digest(item, "signal evidence") for item in self.evidence_sha256s})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "weight": self.weight,
            "detail": self.detail,
            "evidence_sha256s": list(self.evidence_sha256s),
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class KnowledgeCorrelationProposal:
    """One non-authoritative claim-to-node candidate."""

    claim_sha256: str
    document_id: str
    source_authority: str
    target_node_id: str
    target_plane: str
    relation: str
    state: str
    score: float
    signals: tuple[CorrelationSignal, ...]
    evidence_sha256s: tuple[str, ...]

    SCHEMA: ClassVar[str] = "daedalus-knowledge-correlation-proposal/1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_sha256", _digest(self.claim_sha256, "claim_sha256"))
        for name in ("document_id", "target_node_id", "relation"):
            object.__setattr__(self, name, _nonempty(getattr(self, name), name))
        if self.target_plane not in FOURFOLD_PLANES:
            raise KnowledgeCorrelationError("proposal target plane is invalid")
        if self.state not in {"proposed", "source_supported"}:
            raise KnowledgeCorrelationError("proposal state must be proposed or source_supported")
        if not 0.0 <= float(self.score) <= 1.0:
            raise KnowledgeCorrelationError("proposal score must be in [0, 1]")
        object.__setattr__(self, "score", round(float(self.score), 6))
        signals = tuple(sorted(self.signals, key=lambda item: (item.kind, item.detail, item.digest)))
        if not signals:
            raise KnowledgeCorrelationError("proposal requires at least one signal")
        object.__setattr__(self, "signals", signals)
        object.__setattr__(
            self,
            "evidence_sha256s",
            tuple(sorted({_digest(item, "proposal evidence") for item in self.evidence_sha256s})),
        )
        if self.state == "source_supported":
            if not any(signal.kind in _HARD_SIGNAL_KINDS for signal in signals):
                raise KnowledgeCorrelationError("source_supported proposal requires a hard signal")
            if not self.evidence_sha256s:
                raise KnowledgeCorrelationError("source_supported proposal requires evidence")

    @property
    def project_authority(self) -> bool:
        return self.source_authority in PROJECT_AUTHORITY_CLASSES

    @property
    def eligible_for_verification(self) -> bool:
        return self.project_authority and self.state == "source_supported"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "claim_sha256": self.claim_sha256,
            "document_id": self.document_id,
            "source_authority": self.source_authority,
            "target_node_id": self.target_node_id,
            "target_plane": self.target_plane,
            "relation": self.relation,
            "state": self.state,
            "score": self.score,
            "signals": [signal.to_dict() for signal in self.signals],
            "evidence_sha256s": list(self.evidence_sha256s),
            "eligible_for_verification": self.eligible_for_verification,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class KnowledgeContradiction:
    claim_sha256: str
    target_node_id: str
    kind: str
    detail: str
    evidence_sha256s: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_sha256", _digest(self.claim_sha256, "claim_sha256"))
        for name in ("target_node_id", "kind", "detail"):
            object.__setattr__(self, name, _nonempty(getattr(self, name), name))
        object.__setattr__(
            self,
            "evidence_sha256s",
            tuple(sorted({_digest(item, "contradiction evidence") for item in self.evidence_sha256s})),
        )
        if not self.evidence_sha256s:
            raise KnowledgeCorrelationError("contradiction requires evidence")

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_sha256": self.claim_sha256,
            "target_node_id": self.target_node_id,
            "kind": self.kind,
            "detail": self.detail,
            "evidence_sha256s": list(self.evidence_sha256s),
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class UnresolvedKnowledgeAnchor:
    claim_sha256: str
    document_id: str
    mention: str
    reason: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_sha256", _digest(self.claim_sha256, "claim_sha256"))
        for name in ("document_id", "mention", "reason"):
            object.__setattr__(self, name, _nonempty(getattr(self, name), name))

    def to_dict(self) -> dict[str, str]:
        return {
            "claim_sha256": self.claim_sha256,
            "document_id": self.document_id,
            "mention": self.mention,
            "reason": self.reason,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class KnowledgeCorrelationBundle:
    claim: KnowledgeClaim
    document_title: str
    source_authority: str
    proposals: tuple[KnowledgeCorrelationProposal, ...]
    contradictions: tuple[KnowledgeContradiction, ...]
    unresolved: tuple[UnresolvedKnowledgeAnchor, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.claim, KnowledgeClaim):
            raise KnowledgeCorrelationError("bundle claim must be KnowledgeClaim")
        object.__setattr__(self, "document_title", _nonempty(self.document_title, "document_title"))
        object.__setattr__(self, "source_authority", _nonempty(self.source_authority, "source_authority"))
        object.__setattr__(
            self, "proposals", tuple(sorted(self.proposals, key=lambda item: (-item.score, item.target_node_id)))
        )
        object.__setattr__(
            self, "contradictions", tuple(sorted(self.contradictions, key=lambda item: item.digest))
        )
        object.__setattr__(
            self, "unresolved", tuple(sorted(self.unresolved, key=lambda item: item.digest))
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim": self.claim.to_dict(),
            "document_title": self.document_title,
            "source_authority": self.source_authority,
            "proposals": [proposal.to_dict() for proposal in self.proposals],
            "contradictions": [item.to_dict() for item in self.contradictions],
            "unresolved": [item.to_dict() for item in self.unresolved],
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class KnowledgeCorrelationResult:
    snapshot_sha256: str
    forest_sha256: str
    corpus_sha256: str
    cards: tuple[GraphNodeCard, ...]
    bundles: tuple[KnowledgeCorrelationBundle, ...]

    SCHEMA: ClassVar[str] = "daedalus-knowledge-correlation-result/1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_sha256", _digest(self.snapshot_sha256, "snapshot_sha256"))
        object.__setattr__(self, "forest_sha256", _digest(self.forest_sha256, "forest_sha256"))
        object.__setattr__(self, "corpus_sha256", _digest(self.corpus_sha256, "corpus_sha256"))
        object.__setattr__(self, "cards", tuple(sorted(self.cards, key=lambda item: item.node_id)))
        object.__setattr__(self, "bundles", tuple(sorted(self.bundles, key=lambda item: item.claim.digest)))

    @property
    def proposals(self) -> tuple[KnowledgeCorrelationProposal, ...]:
        return tuple(proposal for bundle in self.bundles for proposal in bundle.proposals)

    @property
    def contradictions(self) -> tuple[KnowledgeContradiction, ...]:
        return tuple(item for bundle in self.bundles for item in bundle.contradictions)

    @property
    def unresolved(self) -> tuple[UnresolvedKnowledgeAnchor, ...]:
        return tuple(item for bundle in self.bundles for item in bundle.unresolved)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "snapshot_sha256": self.snapshot_sha256,
            "forest_sha256": self.forest_sha256,
            "corpus_sha256": self.corpus_sha256,
            "cards": [card.to_dict() for card in self.cards],
            "bundles": [bundle.to_dict() for bundle in self.bundles],
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class KnowledgeContextCapsule:
    """Deterministic LLM context assembled from correlation bundles."""

    source_revision: str
    snapshot_sha256: str
    corpus_sha256: str
    objective: str
    anchor_node_ids: tuple[str, ...]
    bundles: tuple[KnowledgeCorrelationBundle, ...]
    withheld_claim_sha256s: tuple[str, ...] = ()

    SCHEMA: ClassVar[str] = "daedalus-knowledge-context-capsule/1"

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_revision", _nonempty(self.source_revision, "source_revision"))
        object.__setattr__(self, "snapshot_sha256", _digest(self.snapshot_sha256, "snapshot_sha256"))
        object.__setattr__(self, "corpus_sha256", _digest(self.corpus_sha256, "corpus_sha256"))
        object.__setattr__(self, "objective", _nonempty(self.objective, "objective"))
        object.__setattr__(
            self, "anchor_node_ids", tuple(sorted({_nonempty(item, "anchor_node_id") for item in self.anchor_node_ids}))
        )
        object.__setattr__(self, "bundles", tuple(sorted(self.bundles, key=lambda item: item.claim.digest)))
        object.__setattr__(
            self,
            "withheld_claim_sha256s",
            tuple(sorted({_digest(item, "withheld claim") for item in self.withheld_claim_sha256s})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "source_revision": self.source_revision,
            "snapshot_sha256": self.snapshot_sha256,
            "corpus_sha256": self.corpus_sha256,
            "objective": self.objective,
            "anchor_node_ids": list(self.anchor_node_ids),
            "bundles": [bundle.to_dict() for bundle in self.bundles],
            "withheld_claim_sha256s": list(self.withheld_claim_sha256s),
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


class SoftSignalProvider(Protocol):
    """Optional non-authoritative similarity provider.

    Implementations may use embeddings, BM25, a graph model or an LLM. Scores
    never change proposal authority and must be reproducible through the
    provider's own evidence digest.
    """

    def score(
        self,
        *,
        claim: KnowledgeClaim,
        document: KnowledgeDocument,
        card: GraphNodeCard,
    ) -> tuple[float, str] | None:
        """Return ``(score, evidence_sha256)`` or ``None``."""


@dataclass(frozen=True)
class CorrelationPolicy:
    min_proposal_score: float = 0.58
    max_proposals_per_claim: int = 12
    max_context_bundles: int = 24
    external_background_in_context: bool = True

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_proposal_score <= 1.0:
            raise KnowledgeCorrelationError("min_proposal_score must be in [0, 1]")
        if self.max_proposals_per_claim < 1 or self.max_context_bundles < 1:
            raise KnowledgeCorrelationError("correlation limits must be positive")


def build_node_cards(
    snapshot: FourfoldSnapshot,
    forest: KnowledgeForest,
) -> tuple[GraphNodeCard, ...]:
    """Build one card for every node present in the exact Fourfold snapshot."""

    if forest.content_sha256 != snapshot.source_forest_sha256:
        raise KnowledgeCorrelationError("forest digest does not match FourfoldSnapshot")
    node_by_id = {node.id: node for node in forest.nodes}
    if len(node_by_id) != len(forest.nodes):
        raise KnowledgeCorrelationError("forest node ids are not unique")
    cards: list[GraphNodeCard] = []
    for plane in snapshot.planes:
        for node_id in plane.node_ids:
            node = node_by_id.get(node_id)
            if node is None:
                raise KnowledgeCorrelationError(f"snapshot node missing from forest: {node_id}")
            attrs = tuple(
                sorted(
                    (str(key), str(value))
                    for key, value in node.attributes.items()
                    if isinstance(value, (str, int, float, bool))
                )
            )
            aliases = _node_aliases(node)
            label = (
                _attribute_scalar(node.attributes, "qualified_name")
                or _attribute_scalar(node.attributes, "name")
                or next((alias for alias in aliases if alias != node_id), node_id)
            )
            cards.append(
                GraphNodeCard(
                    node_id=node_id,
                    plane=plane.plane,
                    kind=node.kind,
                    label=label,
                    path=_path_from_node(node),
                    aliases=aliases,
                    attributes=attrs,
                    evidence_sha256s=plane.evidence_sha256s,
                )
            )
    return tuple(sorted(cards, key=lambda item: item.node_id))


def _document_aliases(document: KnowledgeDocument, claim: KnowledgeClaim) -> tuple[str, ...]:
    section = next(section for section in document.sections if section.section_id == claim.section_id)
    candidates = set(document.aliases)
    candidates.add(document.title)
    candidates.update(section.heading_path)
    normalized: set[str] = set()
    for candidate in candidates:
        phrase = _normalized_phrase(candidate)
        if (
            phrase
            and phrase not in _GENERIC_ALIAS_STOPLIST
            and (len(phrase) >= 8 or len(phrase.split()) >= 2)
        ):
            normalized.add(phrase)
    return tuple(sorted(normalized))


def _exact_card_matches(identifier: str, cards: Sequence[GraphNodeCard]) -> tuple[GraphNodeCard, ...]:
    folded = identifier.casefold()
    matches = [
        card
        for card in cards
        if folded == card.node_id.casefold()
        or any(folded == alias.casefold() for alias in card.aliases)
    ]
    return tuple(sorted(matches, key=lambda item: item.node_id))


def _path_card_matches(link: str, cards: Sequence[GraphNodeCard]) -> tuple[GraphNodeCard, ...]:
    if link.startswith("daedalus://node/"):
        target = link[len("daedalus://node/") :]
        return tuple(card for card in cards if card.node_id == target)
    cleaned = link.split("#", 1)[0].split("?", 1)[0].replace("\\", "/").strip("<>")
    if not cleaned or "://" in cleaned or cleaned.startswith("mediawiki:"):
        return ()
    matches = [
        card
        for card in cards
        if card.path and (card.path == cleaned or card.path.endswith("/" + cleaned))
    ]
    return tuple(sorted(matches, key=lambda item: item.node_id))


def _lexical_score(claim: KnowledgeClaim, card: GraphNodeCard) -> float:
    claim_tokens = _tokens(claim.text)
    card_tokens = _tokens(" ".join(card.aliases))
    if not claim_tokens or not card_tokens:
        return 0.0
    overlap = len(claim_tokens & card_tokens)
    union = len(claim_tokens | card_tokens)
    return overlap / union if union else 0.0


def _proposal_score(signals: Iterable[CorrelationSignal]) -> float:
    remaining = 1.0
    for signal in sorted(signals, key=lambda item: item.weight, reverse=True):
        remaining *= 1.0 - signal.weight
    return min(1.0, 1.0 - remaining)


def _snapshot_neighbors(snapshot: FourfoldSnapshot) -> Mapping[str, tuple[tuple[str, str], ...]]:
    rows: dict[str, list[tuple[str, str]]] = {}
    for binding in snapshot.bindings:
        rows.setdefault(binding.source_node_id, []).append(
            (binding.target_node_id, binding.digest)
        )
        rows.setdefault(binding.target_node_id, []).append(
            (binding.source_node_id, binding.digest)
        )
    return {
        node_id: tuple(sorted(values))
        for node_id, values in rows.items()
    }


def _required_contradictions(
    *,
    claim: KnowledgeClaim,
    card: GraphNodeCard,
    evidence_sha256s: tuple[str, ...],
) -> tuple[KnowledgeContradiction, ...]:
    attributes = card.attribute_map
    required = _boolean_attribute(attributes, "required")
    results: list[KnowledgeContradiction] = []
    if required is True and _OPTIONAL_RE.search(claim.text):
        results.append(
            KnowledgeContradiction(
                claim_sha256=claim.digest,
                target_node_id=card.node_id,
                kind="requiredness-conflict",
                detail="knowledge says optional while source evidence says required",
                evidence_sha256s=evidence_sha256s,
            )
        )
    if required is False and _REQUIRED_RE.search(claim.text):
        results.append(
            KnowledgeContradiction(
                claim_sha256=claim.digest,
                target_node_id=card.node_id,
                kind="requiredness-conflict",
                detail="knowledge says required while source evidence says optional",
                evidence_sha256s=evidence_sha256s,
            )
        )
    deprecated = _boolean_attribute(attributes, "deprecated")
    if deprecated is False and _DEPRECATED_RE.search(claim.text):
        results.append(
            KnowledgeContradiction(
                claim_sha256=claim.digest,
                target_node_id=card.node_id,
                kind="lifecycle-conflict",
                detail="knowledge marks an active source node as deprecated",
                evidence_sha256s=evidence_sha256s,
            )
        )
    if _NEGATION_RE.search(claim.text):
        results.append(
            KnowledgeContradiction(
                claim_sha256=claim.digest,
                target_node_id=card.node_id,
                kind="existence-conflict",
                detail="knowledge denies a node that exists in the bound snapshot",
                evidence_sha256s=evidence_sha256s,
            )
        )
    return tuple(results)


def correlate_knowledge(
    *,
    snapshot: FourfoldSnapshot,
    forest: KnowledgeForest,
    corpus: KnowledgeCorpus,
    policy: CorrelationPolicy = CorrelationPolicy(),
    soft_signal_provider: SoftSignalProvider | None = None,
) -> KnowledgeCorrelationResult:
    """Correlate external claims with exact Fourfold nodes in two deterministic passes."""

    cards = build_node_cards(snapshot, forest)
    cards_by_id = {card.node_id: card for card in cards}
    neighbors = _snapshot_neighbors(snapshot)

    hard_matches: dict[str, dict[str, list[CorrelationSignal]]] = {}
    learned_aliases: dict[str, set[str]] = {}

    for document in corpus.documents:
        for claim in document.claims:
            matches: dict[str, list[CorrelationSignal]] = {}
            for identifier in claim.identifiers:
                exact = _exact_card_matches(identifier, cards)
                for card in exact:
                    matches.setdefault(card.node_id, []).append(
                        CorrelationSignal(
                            kind="exact-identifier",
                            weight=0.96,
                            detail=f"claim names exact node alias {identifier!r}",
                            evidence_sha256s=(claim.source_sha256, card.digest),
                        )
                    )
            for link in claim.links:
                for card in _path_card_matches(link, cards):
                    kind = "explicit-node-link" if link.startswith("daedalus://node/") else "repository-path"
                    matches.setdefault(card.node_id, []).append(
                        CorrelationSignal(
                            kind=kind,
                            weight=0.99 if kind == "explicit-node-link" else 0.9,
                            detail=f"claim links to {link!r}",
                            evidence_sha256s=(claim.source_sha256, card.digest),
                        )
                    )
            hard_matches[claim.digest] = matches
            if matches and document.source.project_authoritative:
                for phrase in _document_aliases(document, claim):
                    learned_aliases.setdefault(phrase, set()).update(matches)

    bundles: list[KnowledgeCorrelationBundle] = []
    for document in corpus.documents:
        for claim in document.claims:
            signals_by_node: dict[str, list[CorrelationSignal]] = {
                node_id: list(signals)
                for node_id, signals in hard_matches[claim.digest].items()
            }
            normalized_claim = _normalized_phrase(claim.text)

            for phrase, node_ids in learned_aliases.items():
                if phrase and phrase in normalized_claim:
                    for node_id in node_ids:
                        card = cards_by_id[node_id]
                        signals_by_node.setdefault(node_id, []).append(
                            CorrelationSignal(
                                kind="learned-authoritative-alias",
                                weight=0.68,
                                detail=f"claim contains alias {phrase!r} learned from a hard project anchor",
                                evidence_sha256s=(claim.source_sha256, card.digest),
                            )
                        )

            for card in cards:
                lexical = _lexical_score(claim, card)
                if lexical >= 0.14:
                    signals_by_node.setdefault(card.node_id, []).append(
                        CorrelationSignal(
                            kind="lexical-overlap",
                            weight=min(0.42, lexical),
                            detail=f"token Jaccard={lexical:.6f}",
                            evidence_sha256s=(claim.source_sha256, card.digest),
                        )
                    )
                if soft_signal_provider is not None:
                    result = soft_signal_provider.score(
                        claim=claim,
                        document=document,
                        card=card,
                    )
                    if result is not None:
                        score, evidence = result
                        if not 0.0 <= score <= 1.0:
                            raise KnowledgeCorrelationError("soft signal score must be in [0, 1]")
                        signals_by_node.setdefault(card.node_id, []).append(
                            CorrelationSignal(
                                kind="soft-provider",
                                weight=min(0.5, float(score) * 0.5),
                                detail=f"external soft provider score={float(score):.6f}",
                                evidence_sha256s=(evidence,),
                            )
                        )

            initial_hard = {
                node_id
                for node_id, signals in signals_by_node.items()
                if any(signal.kind in {"explicit-node-link", "exact-identifier", "repository-path"} for signal in signals)
            }
            for anchor_id in sorted(initial_hard):
                for neighbor_id, binding_digest in neighbors.get(anchor_id, ()):
                    card = cards_by_id[neighbor_id]
                    signals_by_node.setdefault(neighbor_id, []).append(
                        CorrelationSignal(
                            kind="verified-neighbor",
                            weight=0.82,
                            detail=f"verified Fourfold binding expands hard anchor {anchor_id}",
                            evidence_sha256s=(claim.source_sha256, binding_digest, card.digest),
                        )
                    )

            proposals: list[KnowledgeCorrelationProposal] = []
            contradictions: list[KnowledgeContradiction] = []
            for node_id, signals in signals_by_node.items():
                score = _proposal_score(signals)
                if score < policy.min_proposal_score:
                    continue
                hard = any(signal.kind in _HARD_SIGNAL_KINDS for signal in signals)
                card = cards_by_id[node_id]
                evidence = tuple(
                    sorted(
                        {
                            digest
                            for signal in signals
                            for digest in signal.evidence_sha256s
                        }
                    )
                )
                proposal = KnowledgeCorrelationProposal(
                    claim_sha256=claim.digest,
                    document_id=document.document_id,
                    source_authority=document.source.authority,
                    target_node_id=node_id,
                    target_plane=card.plane,
                    relation=_RELATION_BY_PLANE[card.plane],
                    state="source_supported" if hard else "proposed",
                    score=score,
                    signals=tuple(signals),
                    evidence_sha256s=evidence if hard else (),
                )
                proposals.append(proposal)
                if hard:
                    contradictions.extend(
                        _required_contradictions(
                            claim=claim,
                            card=card,
                            evidence_sha256s=evidence,
                        )
                    )
            proposals.sort(key=lambda item: (-item.score, item.target_node_id))
            proposals = proposals[: policy.max_proposals_per_claim]

            matched_aliases = {
                alias.casefold()
                for proposal in proposals
                for alias in cards_by_id[proposal.target_node_id].aliases
            }
            unresolved: list[UnresolvedKnowledgeAnchor] = []
            for identifier in claim.identifiers:
                if identifier.casefold() not in matched_aliases and not _exact_card_matches(identifier, cards):
                    unresolved.append(
                        UnresolvedKnowledgeAnchor(
                            claim_sha256=claim.digest,
                            document_id=document.document_id,
                            mention=identifier,
                            reason="identifier has no node in the bound Fourfold snapshot",
                        )
                    )
            bundles.append(
                KnowledgeCorrelationBundle(
                    claim=claim,
                    document_title=document.title,
                    source_authority=document.source.authority,
                    proposals=tuple(proposals),
                    contradictions=tuple({item.digest: item for item in contradictions}.values()),
                    unresolved=tuple(unresolved),
                )
            )

    return KnowledgeCorrelationResult(
        snapshot_sha256=snapshot.digest,
        forest_sha256=forest.content_sha256,
        corpus_sha256=corpus.digest,
        cards=cards,
        bundles=tuple(bundles),
    )


def build_context_capsule(
    result: KnowledgeCorrelationResult,
    *,
    snapshot: FourfoldSnapshot,
    objective: str,
    anchor_node_ids: Sequence[str],
    policy: CorrelationPolicy = CorrelationPolicy(),
) -> KnowledgeContextCapsule:
    """Select deterministic, authority-labelled bundles for one coding attempt."""

    anchors = tuple(sorted(set(anchor_node_ids)))
    card_ids = {card.node_id for card in result.cards}
    missing = sorted(set(anchors) - card_ids)
    if missing:
        raise KnowledgeCorrelationError(f"context anchors are outside the snapshot: {missing}")
    selected: list[KnowledgeCorrelationBundle] = []
    withheld: list[str] = []
    for bundle in result.bundles:
        target_ids = {proposal.target_node_id for proposal in bundle.proposals}
        relevant = bool(target_ids.intersection(anchors))
        if not relevant:
            continue
        if (
            bundle.source_authority == "external_reference"
            and not policy.external_background_in_context
        ):
            withheld.append(bundle.claim.digest)
            continue
        selected.append(bundle)
    selected.sort(
        key=lambda bundle: (
            0 if bundle.source_authority in PROJECT_AUTHORITY_CLASSES else 1,
            0 if bundle.contradictions else 1,
            bundle.claim.digest,
        )
    )
    selected = selected[: policy.max_context_bundles]
    selected_ids = {bundle.claim.digest for bundle in selected}
    withheld.extend(
        bundle.claim.digest
        for bundle in result.bundles
        if any(proposal.target_node_id in anchors for proposal in bundle.proposals)
        and bundle.claim.digest not in selected_ids
    )
    return KnowledgeContextCapsule(
        source_revision=snapshot.source_revision,
        snapshot_sha256=result.snapshot_sha256,
        corpus_sha256=result.corpus_sha256,
        objective=objective,
        anchor_node_ids=anchors,
        bundles=tuple(selected),
        withheld_claim_sha256s=tuple(sorted(set(withheld))),
    )


__all__ = [
    "CorrelationPolicy",
    "CorrelationSignal",
    "GraphNodeCard",
    "KnowledgeContextCapsule",
    "KnowledgeContradiction",
    "KnowledgeCorrelationBundle",
    "KnowledgeCorrelationError",
    "KnowledgeCorrelationProposal",
    "KnowledgeCorrelationResult",
    "SoftSignalProvider",
    "UnresolvedKnowledgeAnchor",
    "build_context_capsule",
    "build_node_cards",
    "correlate_knowledge",
]
