"""Deterministic semantic super-sampling over a :class:`KnowledgeForest`.

``DSS`` borrows the *coarse-to-fine* idea from multigrid and temporal
reconstruction, not any graphics implementation.  Version zero deliberately
contains no learned interpolation, hidden-state transport, differentiable
program space, or diffeomorphic claim:

* source files form leaves in a deterministic repository/directory hierarchy;
* seed relevance is restricted upwards and prolonged through a bounded number
  of high-scoring branches;
* each evidence relation diffuses in its own channel;
* previous scores may be carried by exact IDs or explicit rename evidence;
* the fused ranking is packed into a token budget; and
* every input and decision is represented by a content-addressed receipt.

The module is dependency-free and read-only.  It selects context; it never
changes source code and never treats a relevance score as a fitness signal.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping

from .forest import KnowledgeForest


DSS_SCHEMA_VERSION = "daedalus-dss/0"
HIERARCHY_SCHEMA_VERSION = "daedalus-dss-hierarchy/0"
RECEIPT_SCHEMA_VERSION = "daedalus-dss-receipt/0"
REPOSITORY_NODE_ID = "repo:."

# Forest node kinds that are FILES for selection purposes: a leaf of the
# repository hierarchy, a legal seed, and a candidate for the token budget.
#
# ONE definition, because there were three copies of this set (the hierarchy
# builder, the temporal carry and the packer) and they have to agree by
# construction: a kind accepted as a seed but rejected as a hierarchy leaf
# raises ``KeyError: unknown Forest file ID`` from ``semantic_super_sample``,
# which is precisely what a partially-added node kind produces.
#
# ``document`` is here because the defect this feature exists to fix is a
# SELECTION defect: a task specified entirely in a 3592-line markdown
# architecture document got a context plan of three TypeScript files, because
# the specification was not a node the selector could see. A document that is
# indexed but unselectable fixes nothing.
#
# ``type`` and ``field`` are DELIBERATELY ABSENT, and adding them is not a
# completion of this set, it is a defect. A document has bytes on disk; a type
# node is a derived assertion about a region of a file that is already a node.
# Admit it here and it becomes a hierarchy leaf, a legal seed and a budget
# candidate -- at which point ``_estimated_tokens`` falls through to its
# ``loc * 8`` fallback and invents a token cost for something no reader can
# read, while the file that actually holds the declaration may be dropped for
# lack of budget. Type evidence RE-SCORES file nodes; it is never itself the
# thing shipped to a model. ``forest.py``'s module docstring carries the full
# argument, including the measured 2-hop blow-up that keeps these relations out
# of diffusion as well (see ``_relation_adjacencies``).
FILE_NODE_KINDS = frozenset({"source_file", "file", "document"})


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


def _finite_non_negative(value: Any, *, name: str) -> float:
    score = float(value)
    if not math.isfinite(score) or score < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return score


def _score_rows(scores: Mapping[str, float]) -> tuple[tuple[str, float], ...]:
    return tuple(
        (node_id, float(score))
        for node_id, score in sorted(scores.items())
        if score > 0
    )


def _score_dict(rows: Iterable[tuple[str, float]]) -> dict[str, float]:
    return {node_id: score for node_id, score in rows}


def _normalise_max(scores: Mapping[str, float]) -> dict[str, float]:
    if not scores:
        return {}
    maximum = max(scores.values(), default=0.0)
    if maximum <= 0:
        return {}
    return {
        node_id: score / maximum
        for node_id, score in sorted(scores.items())
        if score > 0
    }


def _canonical_file_path(node_id: str) -> str:
    """Return a safe, relative POSIX hierarchy path for a Forest file ID."""
    raw = str(node_id).replace("\\", "/")
    path = PurePosixPath(raw)
    if not raw or path.is_absolute() or ".." in path.parts:
        raise ValueError(
            f"Forest file ID {node_id!r} is not a safe relative path"
        )
    parts = tuple(part for part in path.parts if part not in {"", "."})
    if not parts:
        raise ValueError(f"Forest file ID {node_id!r} has no path components")
    return PurePosixPath(*parts).as_posix()


@dataclass(frozen=True)
class HierarchyNode:
    """A repository, directory, or source-file node in the DSS hierarchy."""

    id: str
    kind: str
    path: str
    parent_id: str | None
    forest_node_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "path": self.path,
            "parent_id": self.parent_id,
            "forest_node_id": self.forest_node_id,
        }


@dataclass(frozen=True)
class ForestHierarchy:
    """A deterministic hierarchy derived from file paths, not inferred."""

    nodes: tuple[HierarchyNode, ...]
    schema: str = HIERARCHY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "nodes": [node.to_dict() for node in self.nodes],
        }

    @property
    def content_sha256(self) -> str:
        return _digest(self.to_dict())

    @property
    def root(self) -> HierarchyNode:
        return next(node for node in self.nodes if node.id == REPOSITORY_NODE_ID)

    def node_map(self) -> dict[str, HierarchyNode]:
        return {node.id: node for node in self.nodes}

    def file_node_map(self) -> dict[str, HierarchyNode]:
        return {
            node.forest_node_id: node
            for node in self.nodes
            if node.kind == "file" and node.forest_node_id is not None
        }

    def children_map(self) -> dict[str, tuple[HierarchyNode, ...]]:
        children: dict[str, list[HierarchyNode]] = {}
        for node in self.nodes:
            if node.parent_id is not None:
                children.setdefault(node.parent_id, []).append(node)
        return {
            parent_id: tuple(sorted(rows, key=lambda row: row.id))
            for parent_id, rows in children.items()
        }


def build_forest_hierarchy(forest: KnowledgeForest) -> ForestHierarchy:
    """Build the repository/directory/file hierarchy for file-kind nodes
    (``FILE_NODE_KINDS``: source files and documents)."""
    directories: set[str] = set()
    files: list[tuple[str, str]] = []
    canonical_paths: dict[str, str] = {}

    for node in forest.nodes:
        if node.kind not in FILE_NODE_KINDS:
            continue
        path = _canonical_file_path(node.id)
        prior = canonical_paths.get(path)
        if prior is not None and prior != node.id:
            raise ValueError(
                f"Forest IDs {prior!r} and {node.id!r} map to the same path"
            )
        canonical_paths[path] = node.id
        files.append((path, node.id))
        parent = PurePosixPath(path).parent
        while parent.as_posix() not in {"", "."}:
            directories.add(parent.as_posix())
            parent = parent.parent

    nodes: list[HierarchyNode] = [
        HierarchyNode(REPOSITORY_NODE_ID, "repository", ".", None)
    ]
    for path in sorted(directories, key=lambda item: (item.count("/"), item)):
        parent_path = PurePosixPath(path).parent.as_posix()
        parent_id = (
            REPOSITORY_NODE_ID
            if parent_path in {"", "."}
            else f"dir:{parent_path}"
        )
        nodes.append(HierarchyNode(
            id=f"dir:{path}",
            kind="directory",
            path=path,
            parent_id=parent_id,
        ))
    for path, forest_node_id in sorted(files):
        parent_path = PurePosixPath(path).parent.as_posix()
        parent_id = (
            REPOSITORY_NODE_ID
            if parent_path in {"", "."}
            else f"dir:{parent_path}"
        )
        nodes.append(HierarchyNode(
            id=f"file:{path}",
            kind="file",
            path=path,
            parent_id=parent_id,
            forest_node_id=forest_node_id,
        ))
    return ForestHierarchy(tuple(nodes))


def restrict_scores(
    hierarchy: ForestHierarchy,
    file_scores: Mapping[str, float],
) -> dict[str, float]:
    """Restrict file relevance to all ancestors by deterministic summation.

    Input keys are authoritative Forest node IDs.  Output keys are hierarchy
    IDs.  Unknown source IDs are rejected so a typo cannot silently alter the
    branch selection.
    """
    files = hierarchy.file_node_map()
    nodes = hierarchy.node_map()
    restricted: dict[str, float] = {}
    for forest_node_id, raw_score in sorted(file_scores.items()):
        score = _finite_non_negative(
            raw_score, name=f"score for {forest_node_id!r}"
        )
        if score == 0:
            continue
        leaf = files.get(forest_node_id)
        if leaf is None:
            raise KeyError(f"unknown Forest file ID: {forest_node_id!r}")
        current: HierarchyNode | None = leaf
        while current is not None:
            restricted[current.id] = restricted.get(current.id, 0.0) + score
            current = (
                nodes.get(current.parent_id)
                if current.parent_id is not None
                else None
            )
    return dict(sorted(restricted.items()))


@dataclass(frozen=True)
class Prolongation:
    """Bounded coarse-to-fine traversal and the relevance mass it preserves."""

    file_scores: tuple[tuple[str, float], ...]
    selected_hierarchy_nodes: tuple[str, ...]
    pruned_hierarchy_nodes: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_scores": [
                {"node_id": node_id, "score": score}
                for node_id, score in self.file_scores
            ],
            "selected_hierarchy_nodes": list(self.selected_hierarchy_nodes),
            "pruned_hierarchy_nodes": list(self.pruned_hierarchy_nodes),
        }


def prolongate_scores(
    hierarchy: ForestHierarchy,
    restricted_scores: Mapping[str, float],
    *,
    branch_limit: int,
) -> Prolongation:
    """Project restricted relevance down through at most N children per branch.

    The restriction sum makes a child/parent ratio a deterministic share of
    incoming relevance.  Pruned mass is not renormalised onto other branches;
    doing so would make a surviving low-score file appear more relevant merely
    because its sibling was removed.
    """
    if branch_limit < 1:
        raise ValueError("branch_limit must be at least 1")
    if not restricted_scores.get(REPOSITORY_NODE_ID, 0.0):
        return Prolongation((), (), ())

    children = hierarchy.children_map()
    selected: list[str] = [REPOSITORY_NODE_ID]
    pruned: list[str] = []
    files: dict[str, float] = {}
    queue: list[tuple[str, float]] = [(REPOSITORY_NODE_ID, 1.0)]

    while queue:
        parent_id, incoming = queue.pop(0)
        parent_score = float(restricted_scores.get(parent_id, 0.0))
        if parent_score <= 0:
            continue
        ranked = sorted(
            (
                child for child in children.get(parent_id, ())
                if restricted_scores.get(child.id, 0.0) > 0
            ),
            key=lambda child: (
                -float(restricted_scores[child.id]),
                child.id,
            ),
        )
        chosen = ranked[:branch_limit]
        pruned.extend(child.id for child in ranked[branch_limit:])
        for child in chosen:
            selected.append(child.id)
            share = float(restricted_scores[child.id]) / parent_score
            child_score = incoming * share
            if child.kind == "file" and child.forest_node_id is not None:
                files[child.forest_node_id] = child_score
            else:
                queue.append((child.id, child_score))

    return Prolongation(
        file_scores=_score_rows(files),
        selected_hierarchy_nodes=tuple(selected),
        pruned_hierarchy_nodes=tuple(sorted(pruned)),
    )


@dataclass(frozen=True)
class TemporalEvidence:
    previous_id: str
    current_id: str
    kind: str
    confidence: float
    previous_score: float
    carried_score: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "previous_id": self.previous_id,
            "current_id": self.current_id,
            "kind": self.kind,
            "confidence": self.confidence,
            "previous_score": self.previous_score,
            "carried_score": self.carried_score,
        }


@dataclass(frozen=True)
class TemporalCarry:
    scores: tuple[tuple[str, float], ...]
    evidence: tuple[TemporalEvidence, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scores": [
                {"node_id": node_id, "score": score}
                for node_id, score in self.scores
            ],
            "evidence": [row.to_dict() for row in self.evidence],
        }


def carry_temporal_scores(
    forest: KnowledgeForest,
    previous_scores: Mapping[str, float] | None = None,
    *,
    rename_map: Mapping[str, str] | None = None,
    rename_confidence: Mapping[str, float] | None = None,
) -> TemporalCarry:
    """Carry old relevance through exact IDs and explicit rename evidence.

    Exact IDs have confidence 1.  A rename mapping is considered only when the
    old ID no longer exists.  Confidence is keyed by the old ID and defaults to
    1 for a caller-asserted rename.  Multiple pieces of evidence targeting one
    file use ``max`` rather than summation to avoid artificial score inflation.
    """
    previous_scores = previous_scores or {}
    rename_map = rename_map or {}
    rename_confidence = rename_confidence or {}
    current_ids = {
        node.id for node in forest.nodes
        if node.kind in FILE_NODE_KINDS
    }
    carried: dict[str, float] = {}
    evidence: list[TemporalEvidence] = []

    for previous_id, raw_score in sorted(previous_scores.items()):
        previous_score = _finite_non_negative(
            raw_score, name=f"previous score for {previous_id!r}"
        )
        if previous_score == 0:
            continue
        if previous_id in current_ids:
            current_id, kind, confidence = previous_id, "exact_id", 1.0
        else:
            current_id = rename_map.get(previous_id, "")
            if not current_id or current_id not in current_ids:
                continue
            kind = "rename"
            confidence = _finite_non_negative(
                rename_confidence.get(previous_id, 1.0),
                name=f"rename confidence for {previous_id!r}",
            )
            if confidence > 1:
                raise ValueError("rename confidence must be at most 1")
        score = previous_score * confidence
        if score == 0:
            continue
        carried[current_id] = max(carried.get(current_id, 0.0), score)
        evidence.append(TemporalEvidence(
            previous_id=previous_id,
            current_id=current_id,
            kind=kind,
            confidence=confidence,
            previous_score=previous_score,
            carried_score=score,
        ))
    return TemporalCarry(
        scores=_score_rows(carried),
        evidence=tuple(evidence),
    )


@dataclass(frozen=True)
class RelationChannel:
    """Scores propagated through one semantically named Forest relation."""

    relation: str
    scores: tuple[tuple[str, float], ...]
    directed: bool | None
    source_kind: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation": self.relation,
            "scores": [
                {"node_id": node_id, "score": score}
                for node_id, score in self.scores
            ],
            "directed": self.directed,
            "source_kind": self.source_kind,
        }


def _relation_adjacencies(
    forest: KnowledgeForest,
) -> dict[str, tuple[dict[str, dict[str, float]], bool | None, str]]:
    """Build per-relation transitions without merging evidence semantics.

    DIFFUSION IS FILE-TO-FILE ONLY, BY CONSTRUCTION. This function is where a
    relation layer becomes a channel, and it used to accept whatever endpoints
    it found -- which was harmless while every layer was file-to-file, and stops
    being harmless the moment the forest carries ``type``/``field`` nodes.

    The reason is measured, not feared. On this repository, 2182 functions
    mention 227 distinct nominal types; if a type node may carry a diffusion
    step, then "two functions that mention the same type" are two hops apart and
    1,276,024 of the 2,379,471 possible function pairs become adjacent -- 53.6%
    of the complete graph, of which ``str`` alone contributes 939,135. A channel
    that connects half the repository to itself does not rank anything; it
    normalises everything to the same score and the packer then falls back to
    node id order. So the type layers ship as a LENS: published for consumers
    that ask for them by name, never mixed into the score that decides what is
    read. Turning them into a channel is a separate, gated lane whose
    precondition is the hub cap in ``index["types"]["coverage"]``.

    Filtering by node KIND rather than by relation NAME is deliberate: a name
    list would have to be edited every time a relation is added, and the edit
    that is forgotten is the one that reopens this.
    """
    raw: dict[str, dict[str, dict[str, float]]] = {}
    direction: dict[str, bool | None] = {}
    source_kind: dict[str, str] = {}
    file_ids = {
        node.id for node in forest.nodes if node.kind in FILE_NODE_KINDS
    }

    def add(relation: str, source: str, target: str, weight: float) -> None:
        if source == target or weight <= 0:
            return
        targets = raw.setdefault(relation, {}).setdefault(source, {})
        targets[target] = targets.get(target, 0.0) + weight

    for edge in forest.edges:
        weight = _finite_non_negative(
            edge.weight, name=f"weight for relation {edge.relation!r}"
        )
        if edge.source not in file_ids or edge.target not in file_ids:
            # Validated first and skipped second, so a malformed weight still
            # fails closed on every edge in the forest, not only on the ones
            # that happen to be diffusible.
            continue
        direction.setdefault(edge.relation, edge.directed)
        if direction[edge.relation] != edge.directed:
            direction[edge.relation] = None
        source_kind[edge.relation] = "edge"
        add(edge.relation, edge.source, edge.target, weight)
        if not edge.directed:
            add(edge.relation, edge.target, edge.source, weight)

    for hyperedge in forest.hyperedges:
        weight = _finite_non_negative(
            hyperedge.weight,
            name=f"weight for hyperedge relation {hyperedge.relation!r}",
        )
        direction[hyperedge.relation] = False
        source_kind[hyperedge.relation] = "hyperedge"
        members = tuple(
            member for member in dict.fromkeys(hyperedge.members)
            if member in file_ids
        )
        if len(members) < 2:
            continue
        share = weight / (len(members) - 1)
        for source in members:
            for target in members:
                if target != source:
                    add(hyperedge.relation, source, target, share)

    result = {}
    for relation in sorted(raw):
        normalised: dict[str, dict[str, float]] = {}
        for source, targets in sorted(raw[relation].items()):
            total = sum(targets.values())
            if total <= 0:
                continue
            normalised[source] = {
                target: weight / total
                for target, weight in sorted(targets.items())
            }
        result[relation] = (
            normalised,
            direction.get(relation),
            source_kind[relation],
        )
    return result


def diffuse_relation_scores(
    forest: KnowledgeForest,
    source_scores: Mapping[str, float],
    *,
    steps: int,
    decay: float,
) -> tuple[RelationChannel, ...]:
    """Diffuse scores independently along every edge and hyperedge relation.

    Directed edges propagate only source-to-target.  Hyperedges use explicit
    member-to-group-to-member message passing, represented here by an
    equivalent normalised transition for computation; the Forest itself is
    never rewritten as a clique.
    """
    if steps < 0:
        raise ValueError("steps must be non-negative")
    decay = _finite_non_negative(decay, name="diffusion decay")
    if decay > 1:
        raise ValueError("diffusion decay must be at most 1")
    frontier_seed: dict[str, float] = {}
    for node_id, raw_score in sorted(source_scores.items()):
        score = _finite_non_negative(
            raw_score, name=f"score for {node_id!r}"
        )
        if score > 0:
            frontier_seed[node_id] = score
    channels: list[RelationChannel] = []
    for relation, (adjacency, directed, kind) in _relation_adjacencies(
        forest
    ).items():
        frontier = dict(frontier_seed)
        accumulated: dict[str, float] = {}
        for hop in range(1, steps + 1):
            next_frontier: dict[str, float] = {}
            for source, score in sorted(frontier.items()):
                for target, probability in adjacency.get(source, {}).items():
                    next_frontier[target] = (
                        next_frontier.get(target, 0.0) + score * probability
                    )
            factor = decay ** hop
            for target, score in next_frontier.items():
                accumulated[target] = (
                    accumulated.get(target, 0.0) + factor * score
                )
            frontier = next_frontier
            if not frontier:
                break
        channels.append(RelationChannel(
            relation=relation,
            scores=_score_rows(accumulated),
            directed=directed,
            source_kind=kind,
        ))
    return tuple(channels)


DEFAULT_RELATION_WEIGHTS: tuple[tuple[str, float], ...] = (
    ("imports", 0.70),
    ("co_change", 0.55),
    ("clone_exact", 0.45),
    ("clone_renamed", 0.40),
    ("clone_near", 0.30),
    ("clone_window", 0.25),
)


@dataclass(frozen=True)
class DSSConfig:
    branch_limit: int = 4
    diffusion_steps: int = 2
    diffusion_decay: float = 0.5
    temporal_weight: float = 0.6
    relation_weights: tuple[tuple[str, float], ...] = (
        DEFAULT_RELATION_WEIGHTS
    )
    unknown_relation_weight: float = 0.0

    def __post_init__(self) -> None:
        if self.branch_limit < 1:
            raise ValueError("branch_limit must be at least 1")
        if self.diffusion_steps < 0:
            raise ValueError("diffusion_steps must be non-negative")
        for name, value in (
            ("diffusion_decay", self.diffusion_decay),
            ("temporal_weight", self.temporal_weight),
            ("unknown_relation_weight", self.unknown_relation_weight),
        ):
            _finite_non_negative(value, name=name)
        if self.diffusion_decay > 1:
            raise ValueError("diffusion_decay must be at most 1")
        names: set[str] = set()
        for relation, weight in self.relation_weights:
            if relation in names:
                raise ValueError(f"duplicate relation weight: {relation!r}")
            names.add(relation)
            _finite_non_negative(weight, name=f"weight for {relation!r}")

    def weights(self) -> dict[str, float]:
        return dict(self.relation_weights)

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch_limit": self.branch_limit,
            "diffusion_steps": self.diffusion_steps,
            "diffusion_decay": self.diffusion_decay,
            "temporal_weight": self.temporal_weight,
            "relation_weights": {
                relation: weight
                for relation, weight in sorted(self.relation_weights)
            },
            "unknown_relation_weight": self.unknown_relation_weight,
        }


@dataclass(frozen=True)
class ContextItem:
    node_id: str
    score: float
    estimated_tokens: int
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "score": self.score,
            "estimated_tokens": self.estimated_tokens,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class ContextPlan:
    token_budget: int
    tokens_used: int
    selected: tuple[ContextItem, ...]
    omitted: tuple[ContextItem, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "token_budget": self.token_budget,
            "tokens_used": self.tokens_used,
            "selected": [item.to_dict() for item in self.selected],
            "omitted": [item.to_dict() for item in self.omitted],
        }


def _estimated_tokens(
    forest: KnowledgeForest,
    node_id: str,
    explicit: Mapping[str, int],
) -> int:
    if node_id in explicit:
        value = int(explicit[node_id])
        if value < 1:
            raise ValueError(f"token cost for {node_id!r} must be positive")
        return value
    node = next(node for node in forest.nodes if node.id == node_id)
    for key in ("n_tokens", "token_count", "tokens", "estimated_tokens"):
        if key in node.attributes:
            value = int(node.attributes[key])
            if value > 0:
                return value
    # A deterministic documented fallback; callers should pass measured costs
    # when context budgeting must correspond to a specific tokenizer.
    #
    # It is also the reason ``build_context_plan`` refuses non-file node kinds
    # BEFORE calling this: this fallback cannot fail, so for a node with no
    # bytes on disk it does not report a gap, it reports 8 tokens. The guard
    # upstream is what keeps that number honest -- do not relax it here.
    loc = max(1, int(node.attributes.get("loc", 1) or 1))
    return loc * 8


def build_context_plan(
    forest: KnowledgeForest,
    ranked_scores: Mapping[str, float],
    *,
    token_budget: int,
    token_costs: Mapping[str, int] | None = None,
    reasons: Mapping[str, Iterable[str]] | None = None,
) -> ContextPlan:
    """Greedily pack the score-ranked whole-file candidates into a budget.

    "Whole-file" is enforced, not assumed. Membership in the forest is not
    enough to be packable: only ``FILE_NODE_KINDS`` name something with bytes on
    disk, and a plan is a list of things to READ. A ``type``/``field`` node is
    valid evidence and an invalid candidate, and the two failures are reported
    separately -- an unknown id is a typo, a known id of the wrong kind is a
    category error -- because collapsing them would send the author of either
    one looking for the other's bug.

    Refusing loudly rather than skipping quietly is the same posture
    ``restrict_scores`` and ``semantic_super_sample`` already take on their own
    inputs. Nothing inside this module can trigger it: ``_relation_adjacencies``
    keeps diffusion file-to-file, so a type node has no path into ``fused``.
    That makes this the SECOND lock on the door, and the one that turns a
    regression in the first into a stack trace instead of a fabricated cost.
    """
    if token_budget < 0:
        raise ValueError("token_budget must be non-negative")
    token_costs = token_costs or {}
    reasons = reasons or {}
    kinds = {node.id: node.kind for node in forest.nodes}
    candidates: list[ContextItem] = []
    for node_id, raw_score in ranked_scores.items():
        if node_id not in kinds:
            raise KeyError(f"unknown Forest node ID: {node_id!r}")
        if kinds[node_id] not in FILE_NODE_KINDS:
            raise KeyError(
                f"Forest node ID {node_id!r} is not a packable node kind: "
                f"{kinds[node_id]!r} is not one of "
                f"{sorted(FILE_NODE_KINDS)}"
            )
        score = _finite_non_negative(
            raw_score, name=f"ranked score for {node_id!r}"
        )
        if score <= 0:
            continue
        candidates.append(ContextItem(
            node_id=node_id,
            score=score,
            estimated_tokens=_estimated_tokens(
                forest, node_id, token_costs
            ),
            reasons=tuple(sorted(set(reasons.get(node_id, ())))),
        ))
    candidates.sort(key=lambda item: (-item.score, item.node_id))

    used = 0
    selected: list[ContextItem] = []
    omitted: list[ContextItem] = []
    for item in candidates:
        if used + item.estimated_tokens <= token_budget:
            selected.append(item)
            used += item.estimated_tokens
        else:
            omitted.append(item)
    return ContextPlan(
        token_budget=token_budget,
        tokens_used=used,
        selected=tuple(selected),
        omitted=tuple(omitted),
    )


@dataclass(frozen=True)
class DSSReceipt:
    """Content-addressed provenance for a deterministic DSS result."""

    forest_sha256: str
    hierarchy_sha256: str
    config: Mapping[str, Any]
    input_sha256: Mapping[str, str]
    branch_selection: Mapping[str, Any]
    relation_channels: Mapping[str, str]
    context_plan: Mapping[str, Any]
    schema: str = RECEIPT_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "forest_sha256": self.forest_sha256,
            "hierarchy_sha256": self.hierarchy_sha256,
            "config": dict(self.config),
            "input_sha256": dict(sorted(self.input_sha256.items())),
            "branch_selection": dict(self.branch_selection),
            "relation_channels": dict(sorted(self.relation_channels.items())),
            "context_plan": dict(self.context_plan),
        }

    @property
    def content_sha256(self) -> str:
        return _digest(self.to_dict())

    def envelope(self) -> dict[str, Any]:
        return {
            "receipt_sha256": self.content_sha256,
            **self.to_dict(),
        }


@dataclass(frozen=True)
class DSSResult:
    hierarchy: ForestHierarchy
    restricted_scores: tuple[tuple[str, float], ...]
    prolongation: Prolongation
    temporal: TemporalCarry
    relation_channels: tuple[RelationChannel, ...]
    final_scores: tuple[tuple[str, float], ...]
    context_plan: ContextPlan
    receipt: DSSReceipt
    schema: str = DSS_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "hierarchy_sha256": self.hierarchy.content_sha256,
            "restricted_scores": [
                {"node_id": node_id, "score": score}
                for node_id, score in self.restricted_scores
            ],
            "prolongation": self.prolongation.to_dict(),
            "temporal": self.temporal.to_dict(),
            "relation_channels": [
                channel.to_dict() for channel in self.relation_channels
            ],
            "final_scores": [
                {"node_id": node_id, "score": score}
                for node_id, score in self.final_scores
            ],
            "context_plan": self.context_plan.to_dict(),
            "receipt": self.receipt.envelope(),
        }


def semantic_super_sample(
    forest: KnowledgeForest,
    seed_scores: Mapping[str, float],
    *,
    token_budget: int,
    token_costs: Mapping[str, int] | None = None,
    previous_scores: Mapping[str, float] | None = None,
    rename_map: Mapping[str, str] | None = None,
    rename_confidence: Mapping[str, float] | None = None,
    config: DSSConfig | None = None,
) -> DSSResult:
    """Run the deterministic DSS v0 context-selection pipeline."""
    config = config or DSSConfig()
    token_costs = token_costs or {}
    previous_scores = previous_scores or {}
    rename_map = rename_map or {}
    rename_confidence = rename_confidence or {}

    file_ids = {
        node.id for node in forest.nodes
        if node.kind in FILE_NODE_KINDS
    }
    seeds: dict[str, float] = {}
    for node_id, raw_score in sorted(seed_scores.items()):
        if node_id not in file_ids:
            raise KeyError(f"unknown Forest file ID: {node_id!r}")
        score = _finite_non_negative(
            raw_score, name=f"seed score for {node_id!r}"
        )
        if score > 0:
            seeds[node_id] = score

    hierarchy = build_forest_hierarchy(forest)
    temporal = carry_temporal_scores(
        forest,
        previous_scores,
        rename_map=rename_map,
        rename_confidence=rename_confidence,
    )
    temporal_scores = _score_dict(temporal.scores)
    coarse_input = dict(seeds)
    for node_id, score in temporal_scores.items():
        coarse_input[node_id] = (
            coarse_input.get(node_id, 0.0) + config.temporal_weight * score
        )
    restricted = restrict_scores(hierarchy, coarse_input)
    prolongation = prolongate_scores(
        hierarchy,
        restricted,
        branch_limit=config.branch_limit,
    )
    base_scores = _score_dict(prolongation.file_scores)
    channels = diffuse_relation_scores(
        forest,
        base_scores,
        steps=config.diffusion_steps,
        decay=config.diffusion_decay,
    )

    fused = dict(base_scores)
    relation_weights = config.weights()
    reasons: dict[str, set[str]] = {}
    for node_id in seeds:
        if node_id in base_scores:
            reasons.setdefault(node_id, set()).add("seed")
    for node_id in temporal_scores:
        if node_id in base_scores:
            reasons.setdefault(node_id, set()).add("temporal")
    for channel in channels:
        weight = relation_weights.get(
            channel.relation, config.unknown_relation_weight
        )
        if weight <= 0:
            continue
        for node_id, score in channel.scores:
            fused[node_id] = fused.get(node_id, 0.0) + weight * score
            if score > 0:
                reasons.setdefault(node_id, set()).add(
                    f"relation:{channel.relation}"
                )
    final_scores = _normalise_max(fused)
    context_plan = build_context_plan(
        forest,
        final_scores,
        token_budget=token_budget,
        token_costs=token_costs,
        reasons=reasons,
    )

    input_values = {
        "seed_scores": sorted(seeds.items()),
        "previous_scores": sorted(previous_scores.items()),
        "rename_map": sorted(rename_map.items()),
        "rename_confidence": sorted(rename_confidence.items()),
        "token_costs": sorted(token_costs.items()),
    }
    receipt = DSSReceipt(
        forest_sha256=forest.content_sha256,
        hierarchy_sha256=hierarchy.content_sha256,
        config=config.to_dict(),
        input_sha256={
            key: _digest(value) for key, value in input_values.items()
        },
        branch_selection={
            "selected": list(prolongation.selected_hierarchy_nodes),
            "pruned": list(prolongation.pruned_hierarchy_nodes),
        },
        relation_channels={
            channel.relation: _digest(channel.to_dict())
            for channel in channels
        },
        context_plan=context_plan.to_dict(),
    )
    return DSSResult(
        hierarchy=hierarchy,
        restricted_scores=_score_rows(restricted),
        prolongation=prolongation,
        temporal=temporal,
        relation_channels=channels,
        final_scores=_score_rows(final_scores),
        context_plan=context_plan,
        receipt=receipt,
    )
