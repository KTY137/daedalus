"""Logical contraction plans compiled onto typed relation-block indices."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Mapping, Sequence

from daedalus.spine.envelope import canonical_sha

from .relations import (
    RelationBlockCatalog,
    RelationSignature,
    TypedRelationBlock,
)

MAX_PLAN_PATHS = 32
MAX_PLAN_STEPS = 16
MAX_EXECUTION_STATES = 100_000
MAX_DERIVATIONS_PER_TARGET = 128

_DIRECTIONS = frozenset({"forward", "reverse"})
_COMBINERS = frozenset({"union", "intersection"})


@dataclass(frozen=True)
class RelationStep:
    signature: RelationSignature
    direction: str = "forward"

    def __post_init__(self) -> None:
        if not isinstance(self.signature, RelationSignature):
            raise ValueError("step.signature must be RelationSignature")
        if self.direction not in _DIRECTIONS:
            raise ValueError("step.direction must be forward or reverse")

    @property
    def input_plane(self) -> str:
        return (
            self.signature.source_plane
            if self.direction == "forward"
            else self.signature.target_plane
        )

    @property
    def output_plane(self) -> str:
        return (
            self.signature.target_plane
            if self.direction == "forward"
            else self.signature.source_plane
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "signature": self.signature.to_dict(),
            "direction": self.direction,
        }


@dataclass(frozen=True)
class PathExpression:
    name: str
    steps: tuple[RelationStep, ...]

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name or len(self.name) > 200:
            raise ValueError("path.name must be bounded non-empty text")
        if not isinstance(self.steps, Sequence) or isinstance(
            self.steps, (str, bytes, Mapping)
        ):
            raise ValueError("path.steps must be a bounded sequence")
        if not 1 <= len(self.steps) <= MAX_PLAN_STEPS:
            raise ValueError(f"path.steps must contain 1..{MAX_PLAN_STEPS} steps")
        steps = tuple(self.steps)
        if any(not isinstance(step, RelationStep) for step in steps):
            raise ValueError("path.steps must contain RelationStep records")
        for left, right in zip(steps, steps[1:]):
            if left.output_plane != right.input_plane:
                raise ValueError(
                    "path steps are not plane-compatible: "
                    f"{left.output_plane!r} != {right.input_plane!r}"
                )
        object.__setattr__(self, "steps", steps)

    @property
    def start_plane(self) -> str:
        return self.steps[0].input_plane

    @property
    def end_plane(self) -> str:
        return self.steps[-1].output_plane

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass(frozen=True)
class ContractionPlan:
    """One or more typed paths combined by union or intersection."""

    name: str
    paths: tuple[PathExpression, ...]
    combine: str = "union"

    def __post_init__(self) -> None:
        if type(self.name) is not str or not self.name or len(self.name) > 200:
            raise ValueError("plan.name must be bounded non-empty text")
        if not isinstance(self.paths, Sequence) or isinstance(
            self.paths, (str, bytes, Mapping)
        ):
            raise ValueError("plan.paths must be a bounded sequence")
        if not 1 <= len(self.paths) <= MAX_PLAN_PATHS:
            raise ValueError(f"plan.paths must contain 1..{MAX_PLAN_PATHS} paths")
        paths = tuple(self.paths)
        if any(not isinstance(path, PathExpression) for path in paths):
            raise ValueError("plan.paths must contain PathExpression records")
        if len({path.name for path in paths}) != len(paths):
            raise ValueError("plan path names must be unique")
        starts = {path.start_plane for path in paths}
        ends = {path.end_plane for path in paths}
        if len(starts) != 1 or len(ends) != 1:
            raise ValueError("all plan paths must share one start plane and end plane")
        if self.combine not in _COMBINERS:
            raise ValueError("plan.combine must be union or intersection")
        object.__setattr__(self, "paths", paths)

    @property
    def start_plane(self) -> str:
        return self.paths[0].start_plane

    @property
    def end_plane(self) -> str:
        return self.paths[0].end_plane

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "combine": self.combine,
            "paths": [path.to_dict() for path in self.paths],
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


@dataclass(frozen=True)
class IndexedHop:
    node_id: str
    evidence_sha256s: tuple[str, ...]
    weight: float


@dataclass(frozen=True)
class PhysicalRelationIndex:
    """Forward and reverse hash indices over one canonical relation block."""

    block: TypedRelationBlock
    forward: Mapping[str, tuple[IndexedHop, ...]]
    reverse: Mapping[str, tuple[IndexedHop, ...]]

    @classmethod
    def build(cls, block: TypedRelationBlock) -> "PhysicalRelationIndex":
        if not isinstance(block, TypedRelationBlock):
            raise ValueError("physical index requires a TypedRelationBlock")
        forward: dict[str, list[IndexedHop]] = defaultdict(list)
        reverse: dict[str, list[IndexedHop]] = defaultdict(list)
        for cell in block.cells:
            forward[cell.source_node_id].append(
                IndexedHop(
                    node_id=cell.target_node_id,
                    evidence_sha256s=cell.evidence_sha256s,
                    weight=cell.weight,
                )
            )
            reverse[cell.target_node_id].append(
                IndexedHop(
                    node_id=cell.source_node_id,
                    evidence_sha256s=cell.evidence_sha256s,
                    weight=cell.weight,
                )
            )

        def freeze(values: Mapping[str, list[IndexedHop]]) -> Mapping[str, tuple[IndexedHop, ...]]:
            return MappingProxyType(
                {
                    key: tuple(
                        sorted(
                            hops,
                            key=lambda hop: (
                                hop.node_id,
                                hop.evidence_sha256s,
                                hop.weight,
                            ),
                        )
                    )
                    for key, hops in sorted(values.items())
                }
            )

        return cls(block=block, forward=freeze(forward), reverse=freeze(reverse))

    def neighbors(self, node_id: str, direction: str) -> tuple[IndexedHop, ...]:
        if direction == "forward":
            return self.forward.get(node_id, ())
        if direction == "reverse":
            return self.reverse.get(node_id, ())
        raise ValueError("direction must be forward or reverse")


@dataclass(frozen=True)
class CompiledStep:
    logical: RelationStep
    index: PhysicalRelationIndex


@dataclass(frozen=True)
class CompiledPath:
    name: str
    steps: tuple[CompiledStep, ...]


@dataclass(frozen=True)
class PhysicalContractionPlan:
    logical: ContractionPlan
    catalog_digest: str
    paths: tuple[CompiledPath, ...]
    strategies: tuple[str, ...]


class PhysicalPlanner:
    """Compile logical Fourfold paths onto reusable adjacency/hash indices."""

    def compile(
        self,
        plan: ContractionPlan,
        catalog: RelationBlockCatalog,
    ) -> PhysicalContractionPlan:
        if not isinstance(plan, ContractionPlan):
            raise ValueError("plan must be ContractionPlan")
        if not isinstance(catalog, RelationBlockCatalog):
            raise ValueError("catalog must be RelationBlockCatalog")

        indices: dict[RelationSignature, PhysicalRelationIndex] = {}
        compiled_paths: list[CompiledPath] = []
        for path in plan.paths:
            compiled_steps: list[CompiledStep] = []
            for step in path.steps:
                index = indices.get(step.signature)
                if index is None:
                    index = PhysicalRelationIndex.build(catalog.require(step.signature))
                    indices[step.signature] = index
                compiled_steps.append(CompiledStep(logical=step, index=index))
            compiled_paths.append(
                CompiledPath(name=path.name, steps=tuple(compiled_steps))
            )

        strategies = ["adjacency_lookup"]
        if any(len(path.steps) > 1 for path in plan.paths):
            strategies.append("sparse_hash_join")
        strategies.append(
            "set_intersection" if plan.combine == "intersection" else "set_union"
        )
        return PhysicalContractionPlan(
            logical=plan,
            catalog_digest=catalog.digest,
            paths=tuple(compiled_paths),
            strategies=tuple(strategies),
        )


@dataclass(frozen=True)
class EvidenceDerivation:
    path_name: str
    seed_node_id: str
    nodes: tuple[str, ...]
    evidence_sha256s: tuple[str, ...]
    weight: float

    def __post_init__(self) -> None:
        if len(self.nodes) < 2:
            raise ValueError("a derivation must include its seed and at least one result")
        if self.nodes[0] != self.seed_node_id:
            raise ValueError("derivation nodes must begin with seed_node_id")
        if not self.evidence_sha256s:
            raise ValueError("a derivation must retain evidence")
        if not math.isfinite(self.weight) or self.weight <= 0.0:
            raise ValueError("derivation weight must be positive and finite")

    @property
    def target_node_id(self) -> str:
        return self.nodes[-1]

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_name": self.path_name,
            "seed_node_id": self.seed_node_id,
            "nodes": list(self.nodes),
            "evidence_sha256s": list(self.evidence_sha256s),
            "weight": self.weight,
        }


@dataclass(frozen=True)
class ContractionHit:
    node_id: str
    branch_names: tuple[str, ...]
    branch_coverage: float
    derivation_count: int
    max_weight: float
    evidence_sha256s: tuple[str, ...]
    derivations: tuple[EvidenceDerivation, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "branch_names": list(self.branch_names),
            "branch_coverage": self.branch_coverage,
            "derivation_count": self.derivation_count,
            "max_weight": self.max_weight,
            "evidence_sha256s": list(self.evidence_sha256s),
            "derivations": [item.to_dict() for item in self.derivations],
        }


@dataclass(frozen=True)
class ContractionResult:
    plan_digest: str
    catalog_digest: str
    seeds: tuple[str, ...]
    strategies: tuple[str, ...]
    hits: tuple[ContractionHit, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_digest": self.plan_digest,
            "catalog_digest": self.catalog_digest,
            "seeds": list(self.seeds),
            "strategies": list(self.strategies),
            "hits": [hit.to_dict() for hit in self.hits],
        }


@dataclass(frozen=True)
class _State:
    seed_node_id: str
    nodes: tuple[str, ...]
    evidence_sha256s: tuple[str, ...]
    weight: float


class ReferenceContractionExecutor:
    """Deterministic reference executor for the compiled physical plan."""

    def execute(
        self,
        plan: PhysicalContractionPlan,
        catalog: RelationBlockCatalog,
        *,
        seeds: Sequence[str],
        max_states: int = MAX_EXECUTION_STATES,
        max_derivations_per_target: int = MAX_DERIVATIONS_PER_TARGET,
    ) -> ContractionResult:
        if not isinstance(plan, PhysicalContractionPlan):
            raise ValueError("plan must be PhysicalContractionPlan")
        if not isinstance(catalog, RelationBlockCatalog):
            raise ValueError("catalog must be RelationBlockCatalog")
        if plan.catalog_digest != catalog.digest:
            raise ValueError("physical plan was compiled for another relation catalog")
        if isinstance(seeds, (str, bytes, Mapping)) or not isinstance(seeds, Sequence):
            raise ValueError("seeds must be a bounded sequence")
        if type(max_states) is not int or not 1 <= max_states <= MAX_EXECUTION_STATES:
            raise ValueError(f"max_states must be in [1, {MAX_EXECUTION_STATES}]")
        if (
            type(max_derivations_per_target) is not int
            or not 1 <= max_derivations_per_target <= MAX_DERIVATIONS_PER_TARGET
        ):
            raise ValueError(
                "max_derivations_per_target must be in "
                f"[1, {MAX_DERIVATIONS_PER_TARGET}]"
            )

        normalized_seeds = tuple(sorted(set(seeds)))
        for seed in normalized_seeds:
            if catalog.plane_of(seed) != plan.logical.start_plane:
                raise ValueError(
                    f"seed {seed!r} is not in plan start plane "
                    f"{plan.logical.start_plane!r}"
                )

        path_results: dict[
            str,
            dict[str, tuple[EvidenceDerivation, ...]],
        ] = {}
        for path in plan.paths:
            states = tuple(
                _State(
                    seed_node_id=seed,
                    nodes=(seed,),
                    evidence_sha256s=(),
                    weight=1.0,
                )
                for seed in normalized_seeds
            )
            for step in path.steps:
                expanded: dict[
                    tuple[str, str, tuple[str, ...], tuple[str, ...]],
                    _State,
                ] = {}
                for state in states:
                    for hop in step.index.neighbors(
                        state.nodes[-1],
                        step.logical.direction,
                    ):
                        evidence = tuple(
                            sorted(
                                set(state.evidence_sha256s).union(
                                    hop.evidence_sha256s
                                )
                            )
                        )
                        next_state = _State(
                            seed_node_id=state.seed_node_id,
                            nodes=state.nodes + (hop.node_id,),
                            evidence_sha256s=evidence,
                            weight=state.weight * hop.weight,
                        )
                        if not math.isfinite(next_state.weight) or next_state.weight <= 0.0:
                            raise ValueError(
                                "contraction produced a non-positive or non-finite weight"
                            )
                        key = (
                            next_state.seed_node_id,
                            next_state.nodes[-1],
                            next_state.nodes,
                            next_state.evidence_sha256s,
                        )
                        prior = expanded.get(key)
                        if prior is None or next_state.weight > prior.weight:
                            expanded[key] = next_state
                        if len(expanded) > max_states:
                            raise ValueError(
                                "contraction exceeded its bounded intermediate-state budget"
                            )
                states = tuple(
                    expanded[key]
                    for key in sorted(
                        expanded,
                        key=lambda item: (
                            item[1],
                            item[0],
                            item[2],
                            item[3],
                        ),
                    )
                )

            grouped: dict[str, list[EvidenceDerivation]] = defaultdict(list)
            for state in states:
                grouped[state.nodes[-1]].append(
                    EvidenceDerivation(
                        path_name=path.name,
                        seed_node_id=state.seed_node_id,
                        nodes=state.nodes,
                        evidence_sha256s=state.evidence_sha256s,
                        weight=state.weight,
                    )
                )
            path_results[path.name] = {
                target: tuple(
                    sorted(
                        derivations,
                        key=lambda item: (
                            -item.weight,
                            item.seed_node_id,
                            item.nodes,
                            item.evidence_sha256s,
                        ),
                    )[:max_derivations_per_target]
                )
                for target, derivations in sorted(grouped.items())
            }

        target_sets = [set(values) for values in path_results.values()]
        if not target_sets:
            targets: set[str] = set()
        elif plan.logical.combine == "intersection":
            targets = set.intersection(*target_sets)
        else:
            targets = set.union(*target_sets)

        hits: list[ContractionHit] = []
        total_paths = len(plan.logical.paths)
        for target in sorted(targets):
            branches = tuple(
                path.name
                for path in plan.logical.paths
                if target in path_results[path.name]
            )
            derivations = tuple(
                item
                for branch in branches
                for item in path_results[branch][target]
            )
            evidence = tuple(
                sorted(
                    {
                        digest
                        for derivation in derivations
                        for digest in derivation.evidence_sha256s
                    }
                )
            )
            hits.append(
                ContractionHit(
                    node_id=target,
                    branch_names=branches,
                    branch_coverage=len(branches) / total_paths,
                    derivation_count=len(derivations),
                    max_weight=max(item.weight for item in derivations),
                    evidence_sha256s=evidence,
                    derivations=derivations,
                )
            )
        hits.sort(
            key=lambda item: (
                -item.branch_coverage,
                -item.derivation_count,
                -item.max_weight,
                item.node_id,
            )
        )
        return ContractionResult(
            plan_digest=plan.logical.digest,
            catalog_digest=catalog.digest,
            seeds=normalized_seeds,
            strategies=plan.strategies,
            hits=tuple(hits),
        )


__all__ = [
    "MAX_DERIVATIONS_PER_TARGET",
    "MAX_EXECUTION_STATES",
    "MAX_PLAN_PATHS",
    "MAX_PLAN_STEPS",
    "ContractionHit",
    "ContractionPlan",
    "ContractionResult",
    "EvidenceDerivation",
    "PathExpression",
    "PhysicalContractionPlan",
    "PhysicalPlanner",
    "ReferenceContractionExecutor",
    "RelationStep",
]
