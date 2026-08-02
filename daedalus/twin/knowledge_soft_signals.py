"""Deterministic soft-signal providers for autonomous knowledge correlation.

BM25 is intentionally the first provider: it is cheap, inspectable and a strong
retrieval baseline. Optional alias groups let a project declare terminology such
as ``sensor bias`` ↔ ``bias voltage`` ↔ ``voltage`` without granting authority.
The provider only returns scores and a manifest digest. The correlation engine
caps soft evidence and cannot promote it to ``source_supported`` on its own.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
import math
import re
from types import MappingProxyType
from typing import Any, ClassVar, Mapping, Sequence

from ..spine.envelope import canonical_sha
from .knowledge_correlation import (
    GraphNodeCard,
    KnowledgeCorrelationError,
)
from .knowledge_sources import KnowledgeClaim, KnowledgeDocument


_CAMEL_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokens(value: str) -> tuple[str, ...]:
    expanded = _CAMEL_RE.sub(" ", value).replace("_", " ").replace(".", " ")
    return tuple(
        token.casefold()
        for token in _TOKEN_RE.findall(expanded)
        if len(token) > 1
    )


def _phrase(value: str) -> str:
    return " ".join(_tokens(value))


@dataclass(frozen=True)
class AliasGroup:
    concept_id: str
    terms: tuple[str, ...]

    def __post_init__(self) -> None:
        concept = _phrase(self.concept_id)
        if not concept:
            raise KnowledgeCorrelationError("alias concept_id must not be empty")
        terms = tuple(
            sorted({_phrase(value) for value in self.terms if _phrase(value)})
        )
        if len(terms) < 2:
            raise KnowledgeCorrelationError(
                "alias group requires at least two terms"
            )
        object.__setattr__(self, "concept_id", concept)
        object.__setattr__(self, "terms", terms)

    def to_dict(self) -> dict[str, Any]:
        return {"concept_id": self.concept_id, "terms": list(self.terms)}

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class KnowledgeAliasLexicon:
    groups: tuple[AliasGroup, ...]

    SCHEMA: ClassVar[str] = "daedalus-knowledge-alias-lexicon/1"

    def __post_init__(self) -> None:
        groups = tuple(sorted(self.groups, key=lambda item: item.concept_id))
        if len({group.concept_id for group in groups}) != len(groups):
            raise KnowledgeCorrelationError("alias concept ids must be unique")
        term_owners: dict[str, str] = {}
        for group in groups:
            for term in group.terms:
                previous = term_owners.setdefault(term, group.concept_id)
                if previous != group.concept_id:
                    raise KnowledgeCorrelationError(
                        f"alias term {term!r} belongs to multiple concepts"
                    )
        object.__setattr__(self, "groups", groups)

    @property
    def term_map(self) -> Mapping[str, AliasGroup]:
        return MappingProxyType(
            {
                term: group
                for group in self.groups
                for term in group.terms
            }
        )

    def expand(self, text: str) -> tuple[str, ...]:
        normalized = _phrase(text)
        padded = f" {normalized} "
        result = list(_tokens(text))
        matched: set[str] = set()
        for term, group in self.term_map.items():
            if f" {term} " in padded:
                matched.add(group.concept_id)
                for equivalent in group.terms:
                    result.extend(_tokens(equivalent))
        result.extend(
            token
            for concept in sorted(matched)
            for token in _tokens(concept)
        )
        return tuple(result)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "groups": [group.to_dict() for group in self.groups],
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


EMPTY_ALIAS_LEXICON = KnowledgeAliasLexicon(groups=())


@dataclass(frozen=True)
class BM25SoftSignalProvider:
    """BM25 over a precomputed immutable index of Fourfold node cards."""

    cards: tuple[GraphNodeCard, ...]
    lexicon: KnowledgeAliasLexicon = EMPTY_ALIAS_LEXICON
    k1: float = 1.2
    b: float = 0.75
    score_scale: float = 4.0
    _card_token_map: Mapping[str, tuple[str, ...]] = field(
        init=False, repr=False, compare=False
    )
    _document_frequencies: Mapping[str, int] = field(
        init=False, repr=False, compare=False
    )
    _average_document_length: float = field(
        init=False, repr=False, compare=False
    )
    _card_ids: frozenset[str] = field(init=False, repr=False, compare=False)

    SCHEMA: ClassVar[str] = "daedalus-bm25-node-card-soft-signal/1"

    def __post_init__(self) -> None:
        cards = tuple(sorted(self.cards, key=lambda item: item.node_id))
        if not cards:
            raise KnowledgeCorrelationError("BM25 provider requires node cards")
        if len({card.node_id for card in cards}) != len(cards):
            raise KnowledgeCorrelationError(
                "BM25 provider card ids must be unique"
            )
        for name in ("k1", "score_scale"):
            value = float(getattr(self, name))
            if not math.isfinite(value) or value <= 0:
                raise KnowledgeCorrelationError(
                    f"BM25 {name} must be positive"
                )
            object.__setattr__(self, name, value)
        b = float(self.b)
        if not math.isfinite(b) or not 0.0 <= b <= 1.0:
            raise KnowledgeCorrelationError("BM25 b must be in [0, 1]")
        object.__setattr__(self, "b", b)
        object.__setattr__(self, "cards", cards)

        card_token_map = {
            card.node_id: self._tokenize_card(card) for card in cards
        }
        frequencies: Counter[str] = Counter()
        for tokens in card_token_map.values():
            frequencies.update(set(tokens))
        average_length = sum(map(len, card_token_map.values())) / len(cards)
        object.__setattr__(
            self,
            "_card_token_map",
            MappingProxyType(card_token_map),
        )
        object.__setattr__(
            self,
            "_document_frequencies",
            MappingProxyType(dict(frequencies)),
        )
        object.__setattr__(
            self,
            "_average_document_length",
            average_length,
        )
        object.__setattr__(
            self,
            "_card_ids",
            frozenset(card_token_map),
        )

    def _tokenize_card(self, card: GraphNodeCard) -> tuple[str, ...]:
        text = " ".join(
            (
                card.node_id,
                card.plane,
                card.kind,
                card.label,
                card.path,
                *card.aliases,
                *(f"{key} {value}" for key, value in card.attributes),
            )
        )
        return self.lexicon.expand(text)

    @property
    def document_frequencies(self) -> Mapping[str, int]:
        return self._document_frequencies

    @property
    def average_document_length(self) -> float:
        return self._average_document_length

    def _raw_score(
        self,
        query_tokens: Sequence[str],
        card: GraphNodeCard,
    ) -> float:
        document = self._card_token_map[card.node_id]
        if not query_tokens or not document:
            return 0.0
        counts = Counter(document)
        n_documents = len(self.cards)
        average_length = self._average_document_length or 1.0
        length_normalizer = (
            1.0 - self.b + self.b * len(document) / average_length
        )
        score = 0.0
        for token in query_tokens:
            frequency = counts[token]
            if frequency == 0:
                continue
            df = self._document_frequencies.get(token, 0)
            idf = math.log(
                1.0 + (n_documents - df + 0.5) / (df + 0.5)
            )
            numerator = frequency * (self.k1 + 1.0)
            denominator = frequency + self.k1 * length_normalizer
            score += idf * numerator / denominator
        return score

    def score(
        self,
        *,
        claim: KnowledgeClaim,
        document: KnowledgeDocument,
        card: GraphNodeCard,
    ) -> tuple[float, str] | None:
        if card.node_id not in self._card_ids:
            raise KnowledgeCorrelationError(
                "BM25 score requested for an unknown card"
            )
        query = self.lexicon.expand(
            " ".join(
                (
                    document.title,
                    " ".join(document.aliases),
                    claim.text,
                    " ".join(claim.identifiers),
                )
            )
        )
        raw = self._raw_score(query, card)
        if raw <= 0:
            return None
        normalized = 1.0 - math.exp(-raw / self.score_scale)
        return min(1.0, normalized), self.manifest_sha256

    def manifest_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "card_sha256s": [card.digest for card in self.cards],
            "lexicon_sha256": self.lexicon.digest,
            "k1": self.k1,
            "b": self.b,
            "score_scale": self.score_scale,
            "authority_granted": False,
        }

    @property
    def manifest_sha256(self) -> str:
        return canonical_sha(self.manifest_dict())


__all__ = [
    "AliasGroup",
    "BM25SoftSignalProvider",
    "EMPTY_ALIAS_LEXICON",
    "KnowledgeAliasLexicon",
]
