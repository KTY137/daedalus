"""Hybrid, evidence-bearing context planning over the Daedalus Knowledge Forest.

The planner turns a natural-language objective into file-level seed evidence,
then delegates coarse-to-fine propagation and token packing to deterministic
DSS.  The current baseline deliberately keeps the sources distinct:

* ``lexical`` is BM25 over file-path and indexed symbol-name terms;
* ``latent_memory`` is an optional search over versioned agent-event
  projections, mapped back to files only when the event contains explicit path
  evidence;
* relation propagation is performed by DSS in named graph channels.

This is a hybrid retriever, not a claim that code, prose, and agent hidden
states share one universal coordinate system.  The raw StructCore index and
append-only event journal remain authoritative.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..memory import VECTOR_DB_PATH
from ..memory.embeddings import (
    EMBED_MODEL,
    EmbeddingBackend,
    EventVectorStore,
    ProjectionFilter,
)
from ..providers.ollama import DEFAULT_HOST
from ..structcore.dss import DSSConfig, DSSResult, semantic_super_sample
from ..structcore.forest import KnowledgeForest, build_knowledge_forest
from ..structcore.index import cached_index, resolution_context


CONTEXT_PLAN_SCHEMA = "daedalus-context-plan/0"
LEXICAL_PROJECTOR_VERSION = "path-symbol-bm25-v1"
LATENT_MAPPER_VERSION = "explicit-event-path-v1"

# Latent seed statuses.  ``disabled`` means the source was never asked;
# ``ready`` means it answered (possibly with nothing).  Every other code is a
# reason the source was asked but could not answer, and must survive into the
# receipt: a silent zero is indistinguishable from a considered zero otherwise.
LATENT_STATUS_DISABLED = "disabled"
LATENT_STATUS_READY = "ready"
LATENT_STATUS_ERROR = "error"

_WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ0-9]+")
_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_STOP = {
    "a", "an", "and", "auf", "aus", "bei", "bitte", "can", "code", "das",
    "dem", "den", "der", "die", "ein", "eine", "einer", "eines", "for",
    "from", "für", "how", "ich", "in", "ist", "it", "kann", "mit", "of",
    "oder", "please", "the", "to", "und", "von", "was", "wie", "wir", "with",
}


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _terms(text: str) -> list[str]:
    expanded = _CAMEL.sub(" ", str(text)).replace("_", " ").replace("-", " ")
    return [
        token.lower()
        for token in _WORD.findall(expanded)
        if len(token) > 1 and token.lower() not in _STOP
    ]


def _normalise_max(scores: Mapping[str, float]) -> dict[str, float]:
    maximum = max(scores.values(), default=0.0)
    if maximum <= 0:
        return {}
    return {
        node_id: score / maximum
        for node_id, score in sorted(scores.items())
        if score > 0
    }


def _symbol_names(idx: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    resolver = resolution_context(
        idx.get("root", ""),
        key=idx.get("scope_key"),
    )
    if resolver is None:
        return {}
    return {
        rel: tuple(sorted(definitions))
        for rel, definitions in resolver.defs_by_file.items()
    }


@dataclass(frozen=True)
class LexicalSeedResult:
    scores: Mapping[str, float]
    query_terms: tuple[str, ...]
    matched_terms: Mapping[str, tuple[str, ...]]
    projector_version: str = LEXICAL_PROJECTOR_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "projector_version": self.projector_version,
            "query_terms": list(self.query_terms),
            "scores": dict(sorted(self.scores.items())),
            "matched_terms": {
                node_id: list(terms)
                for node_id, terms in sorted(self.matched_terms.items())
            },
        }


def lexical_seed_scores(
    idx: Mapping[str, Any],
    objective: str,
    *,
    limit: int = 128,
) -> LexicalSeedResult:
    """BM25 baseline over derived path and symbol-name evidence.

    Paths receive two copies of their terms because they encode module
    ownership and are available with equal precision in every supported
    language.  Symbol names come from StructCore's cached parser output.  Source
    bodies are intentionally not rescanned on every request.
    """
    if limit < 1:
        raise ValueError("lexical seed limit must be positive")
    query_terms = tuple(dict.fromkeys(_terms(objective)))
    if not query_terms:
        return LexicalSeedResult({}, (), {})

    symbols = _symbol_names(idx)
    documents: dict[str, list[str]] = {}
    for node_id, attributes in sorted((idx.get("modules") or {}).items()):
        path_terms = _terms(node_id)
        symbol_terms: list[str] = []
        for name in symbols.get(node_id, ()):
            symbol_terms.extend(_terms(name))
        language_terms = _terms(str(attributes.get("language", "")))
        documents[str(node_id)] = [
            *path_terms,
            *path_terms,
            *symbol_terms,
            *language_terms,
        ]

    n_documents = len(documents)
    if n_documents == 0:
        return LexicalSeedResult({}, query_terms, {})
    average_length = (
        sum(max(1, len(document)) for document in documents.values())
        / n_documents
    )
    document_frequency = {
        term: sum(term in set(document) for document in documents.values())
        for term in query_terms
    }

    k1, b = 1.2, 0.75
    raw_scores: dict[str, float] = {}
    matched: dict[str, tuple[str, ...]] = {}
    for node_id, document in documents.items():
        frequencies = Counter(document)
        length = max(1, len(document))
        score = 0.0
        hits: list[str] = []
        for term in query_terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            hits.append(term)
            df = document_frequency[term]
            inverse_document_frequency = math.log(
                1.0 + (n_documents - df + 0.5) / (df + 0.5)
            )
            denominator = frequency + k1 * (
                1.0 - b + b * length / average_length
            )
            score += inverse_document_frequency * (
                frequency * (k1 + 1.0) / denominator
            )
        if score > 0:
            raw_scores[node_id] = score
            matched[node_id] = tuple(hits)

    ranked = sorted(raw_scores, key=lambda key: (-raw_scores[key], key))[:limit]
    normalised = _normalise_max({key: raw_scores[key] for key in ranked})
    return LexicalSeedResult(
        scores=normalised,
        query_terms=query_terms,
        matched_terms={key: matched[key] for key in ranked},
    )


def _metadata_strings(value: Any, *, depth: int = 0) -> Iterable[str]:
    """Yield bounded strings from event metadata without interpreting schemas."""
    if depth > 3:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key in sorted(value, key=str):
            yield from _metadata_strings(value[key], depth=depth + 1)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in list(value)[:100]:
            yield from _metadata_strings(item, depth=depth + 1)


def _contains_explicit_path(text: str, path: str) -> bool:
    """Match a path as a token, not as the suffix of another filename."""
    start = 0
    token_chars = set(
        "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
    )
    while True:
        index = text.find(path, start)
        if index < 0:
            return False
        before = text[index - 1] if index else ""
        end = index + len(path)
        after = text[end] if end < len(text) else ""
        if (not before or before not in token_chars) and (
            not after or after not in token_chars
        ):
            return True
        start = index + 1


@dataclass(frozen=True)
class LatentSeedResult:
    """What the latent source was asked, and what it actually gave back.

    ``requested``/``consulted``/``answered`` are carried separately on purpose.
    "nobody asked", "asked but the index was not reachable" and "asked, answered,
    found nothing" all produce an empty ``scores`` map, and a reader who only
    sees the empty map cannot tell them apart.
    """

    status: str
    message: str
    scores: Mapping[str, float]
    mapped_events: tuple[Mapping[str, Any], ...]
    index_id: str | None = None
    mapper_version: str = LATENT_MAPPER_VERSION
    requested: bool = False
    consulted: bool = False
    candidates: int = 0

    @property
    def answered(self) -> bool:
        """True when the index served a query, even if it matched nothing."""
        return self.status == LATENT_STATUS_READY

    def to_dict(self) -> dict[str, Any]:
        return {
            "mapper_version": self.mapper_version,
            "status": self.status,
            "message": self.message,
            "requested": self.requested,
            "consulted": self.consulted,
            "answered": self.answered,
            "index_id": self.index_id,
            "candidates": self.candidates,
            "mapped_event_count": len(self.mapped_events),
            "seed_file_count": len(self.scores),
            "scores": dict(sorted(self.scores.items())),
            "mapped_events": [dict(row) for row in self.mapped_events],
        }


def latent_not_requested() -> LatentSeedResult:
    """The sentinel used when the caller did not opt in to latent seeds."""
    return LatentSeedResult(
        LATENT_STATUS_DISABLED,
        "latent memory seeds not requested (use_latent=False)",
        {},
        (),
        requested=False,
        consulted=False,
    )


def latent_memory_seed_scores(
    forest: KnowledgeForest,
    objective: str,
    *,
    db_path: str | Path = VECTOR_DB_PATH,
    host: str = DEFAULT_HOST,
    model: str = EMBED_MODEL,
    project: str | None = None,
    limit: int = 20,
    backend: EmbeddingBackend | None = None,
) -> LatentSeedResult:
    """Search versioned event projections and require explicit file evidence."""
    if limit < 1:
        raise ValueError("latent seed limit must be positive")
    path = Path(db_path) if str(db_path) != ":memory:" else None
    if path is not None and not path.exists():
        return LatentSeedResult(
            "not_configured",
            f"vector index does not exist: {path}",
            {},
            (),
            requested=True,
            consulted=False,
        )

    consulted = False
    try:
        store = EventVectorStore(db_path, backend=backend)
        try:
            if not store.list_indexes():
                return LatentSeedResult(
                    "index_unavailable",
                    "no versioned projections are available",
                    {},
                    (),
                    requested=True,
                    consulted=False,
                )
            consulted = True
            report = store.search_report(
                objective,
                limit=limit,
                host=host,
                model=model,
                filters=ProjectionFilter(project=project) if project else None,
            )
        finally:
            store.close()
    except Exception as exc:  # noqa: BLE001
        # The latent half is an optional enrichment.  A corrupt or locked index
        # must not take down the plan the caller actually asked for -- but it
        # must be named in the receipt rather than read as "found nothing".
        return LatentSeedResult(
            LATENT_STATUS_ERROR,
            f"latent seed lookup failed: {type(exc).__name__}: {exc}",
            {},
            (),
            requested=True,
            consulted=consulted,
        )

    if not report.status.available:
        return LatentSeedResult(
            report.status.code,
            report.status.message,
            {},
            (),
            report.status.index_id,
            requested=True,
            consulted=True,
        )

    file_ids = sorted(
        (
            node.id
            for node in forest.nodes
            if node.kind in {"source_file", "file"}
        ),
        key=lambda value: (-len(value), value),
    )
    scores: dict[str, float] = {}
    mapped: list[Mapping[str, Any]] = []
    for event, raw_similarity in report.matches:
        similarity = max(0.0, min(1.0, float(raw_similarity)))
        if similarity <= 0:
            continue
        evidence_text = "\n".join(
            [
                event.content,
                *_metadata_strings(event.metadata),
            ]
        ).replace("\\", "/").lower()
        event_paths = [
            node_id for node_id in file_ids
            if _contains_explicit_path(evidence_text, node_id.lower())
        ]
        if not event_paths:
            continue
        for node_id in event_paths:
            scores[node_id] = max(scores.get(node_id, 0.0), similarity)
        mapped.append({
            "event_id": event.event_id,
            "score": similarity,
            "paths": event_paths,
        })

    return LatentSeedResult(
        LATENT_STATUS_READY,
        (
            f"mapped {len(mapped)} of {len(report.matches)} event hits "
            "through explicit file paths"
        ),
        _normalise_max(scores),
        tuple(mapped),
        report.status.index_id,
        requested=True,
        consulted=True,
        candidates=len(report.matches),
    )


@dataclass(frozen=True)
class HybridSeedResult:
    lexical: LexicalSeedResult
    latent: LatentSeedResult
    scores: Mapping[str, float]
    lexical_weight: float
    latent_weight: float
    latent_influenced: tuple[str, ...] = ()

    @property
    def latent_applied(self) -> bool:
        """True only when latent evidence actually carried mass into the fusion."""
        return bool(self.latent_influenced) and self.latent_weight > 0

    @property
    def effective_latent_weight(self) -> float:
        """The weight that was really in play, not the one merely configured.

        ``latent_weight`` is a setting.  When the latent side contributed no
        seeds, nothing was weighted by it, and a reader who sees only the
        configured 0.35 would credit the plan to a source that said nothing.
        """
        return self.latent_weight if self.latent_applied else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "lexical_weight": self.lexical_weight,
            "latent_weight": self.latent_weight,
            "latent_applied": self.latent_applied,
            "effective_latent_weight": self.effective_latent_weight,
            "latent_influenced": list(self.latent_influenced),
            "scores": dict(sorted(self.scores.items())),
            "lexical": self.lexical.to_dict(),
            "latent": self.latent.to_dict(),
        }


def fuse_seed_scores(
    lexical: LexicalSeedResult,
    latent: LatentSeedResult,
    *,
    lexical_weight: float = 1.0,
    latent_weight: float = 0.35,
) -> HybridSeedResult:
    for name, value in (
        ("lexical_weight", lexical_weight),
        ("latent_weight", latent_weight),
    ):
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"{name} must be finite and non-negative")
    fused: dict[str, float] = {}
    for node_id, score in lexical.scores.items():
        fused[node_id] = fused.get(node_id, 0.0) + lexical_weight * score
    latent_mass: set[str] = set()
    for node_id, score in latent.scores.items():
        fused[node_id] = fused.get(node_id, 0.0) + latent_weight * score
        if score > 0 and latent_weight > 0:
            latent_mass.add(node_id)
    scores = _normalise_max(fused)
    return HybridSeedResult(
        lexical=lexical,
        latent=latent,
        scores=scores,
        lexical_weight=lexical_weight,
        latent_weight=latent_weight,
        latent_influenced=tuple(sorted(latent_mass & set(scores))),
    )


@dataclass(frozen=True)
class ContextPlanningResult:
    objective: str
    project: str | None
    seed_result: HybridSeedResult
    dss: DSSResult
    scope_key: str | None
    schema: str = CONTEXT_PLAN_SCHEMA

    def _latent_source(self) -> dict[str, Any]:
        """State the latent half's contribution in terms a reader can check.

        Answers, without reading the seed block: was it consulted, did it
        answer, how much did it contribute, and -- if it contributed nothing --
        why.  ``effective_weight`` is 0.0 whenever nothing was weighted, so a
        configured weight can never imply an influence that did not happen.
        """
        latent = self.seed_result.latent
        return {
            "requested": latent.requested,
            "consulted": latent.consulted,
            "answered": latent.answered,
            "status": latent.status,
            "reason": latent.message,
            "mapper_version": latent.mapper_version,
            "index_id": latent.index_id,
            "candidates": latent.candidates,
            "mapped_events": len(latent.mapped_events),
            "seed_files": len(latent.scores),
            "influenced_files": len(self.seed_result.latent_influenced),
            "declared_weight": self.seed_result.latent_weight,
            "effective_weight": self.seed_result.effective_latent_weight,
        }

    def _receipt_body(self) -> dict[str, Any]:
        seeds = self.seed_result.to_dict()
        return {
            "schema": self.schema,
            "objective_sha256": hashlib.sha256(
                self.objective.encode("utf-8")
            ).hexdigest(),
            "project": self.project,
            "scope_key": self.scope_key,
            "seed_evidence_sha256": _digest(seeds),
            "seed_projectors": {
                "lexical": self.seed_result.lexical.projector_version,
                "latent": self.seed_result.latent.mapper_version,
                "latent_index_id": self.seed_result.latent.index_id,
            },
            "latent_source": self._latent_source(),
            "dss_receipt_sha256": self.dss.receipt.content_sha256,
        }

    @property
    def receipt_sha256(self) -> str:
        return _digest(self._receipt_body())

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "objective": self.objective,
            "project": self.project,
            "seeds": self.seed_result.to_dict(),
            "dss": self.dss.to_dict(),
            "receipt": {
                "receipt_sha256": self.receipt_sha256,
                **self._receipt_body(),
            },
        }


def plan_context(
    repo_root: str | Path,
    objective: str,
    *,
    idx: Mapping[str, Any] | None = None,
    project: str | None = None,
    token_budget: int = 8_000,
    use_latent: bool = False,
    vector_db: str | Path = VECTOR_DB_PATH,
    embedding_host: str = DEFAULT_HOST,
    embedding_model: str = EMBED_MODEL,
    embedding_backend: EmbeddingBackend | None = None,
    lexical_limit: int = 128,
    config: DSSConfig | None = None,
    temporal_pairs: Iterable[Mapping[str, Any]] = (),
    previous_scores: Mapping[str, float] | None = None,
    rename_map: Mapping[str, str] | None = None,
    rename_confidence: Mapping[str, float] | None = None,
) -> ContextPlanningResult:
    """Build a hybrid DSS plan.  No source material is emitted or rewritten."""
    objective = objective.strip()
    if not objective:
        raise ValueError("objective must not be empty")
    if token_budget < 1:
        raise ValueError("token_budget must be positive")
    resolved = Path(repo_root).resolve()
    index = dict(idx) if idx is not None else cached_index(resolved)
    forest = build_knowledge_forest(index, temporal_pairs=temporal_pairs)
    lexical = lexical_seed_scores(index, objective, limit=lexical_limit)
    latent = (
        latent_memory_seed_scores(
            forest,
            objective,
            db_path=vector_db,
            host=embedding_host,
            model=embedding_model,
            project=project,
            backend=embedding_backend,
        )
        if use_latent
        else latent_not_requested()
    )
    hybrid = fuse_seed_scores(lexical, latent)
    token_costs = {
        node.id: int(node.attributes["n_tokens"])
        for node in forest.nodes
        if node.attributes.get("n_tokens")
    }
    dss = semantic_super_sample(
        forest,
        hybrid.scores,
        token_budget=token_budget,
        token_costs=token_costs,
        previous_scores=previous_scores,
        rename_map=rename_map,
        rename_confidence=rename_confidence,
        config=config,
    )
    return ContextPlanningResult(
        objective=objective,
        project=project,
        seed_result=hybrid,
        dss=dss,
        scope_key=index.get("scope_key"),
    )
