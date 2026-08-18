"""The result-record contract the kill evaluator reads.

Deliberately a *data* contract, not a Python one.  A measuring harness
(slice s09 and its successors) writes JSON; this evaluator reads JSON.  No
import edge exists in either direction, so neither side can quietly reach
into the other's internals, and a result set stays gradeable after the
harness that produced it has moved on.

Three properties are enforced here rather than trusted:

1. **One pre-declared primary metric.**  ``primary_metric`` is named in the
   file.  The evaluator reads that metric and no other, so nobody can shop
   for the cutoff that happens to look best after seeing the numbers.
2. **Paired case sets.**  Every arm must score exactly the declared cases.
   The section-14 tests are paired; an arm that silently skipped its hard
   cases would otherwise win by attrition.
3. **Declared roles.**  An arm says what it *is* (``full``, ``bm25``,
   ``ablate:type`` ...).  The evaluator matches on role, never on a
   hopeful substring of a name, and reports the roles it needed but did
   not find instead of guessing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

SCHEMA_ID = "forest_v2.s10.kill-input/1"

#: Roles the section-14 predicates know how to ask for.  ``ablate:<plane>``
#: is parameterised and validated separately.
KNOWN_ROLES: Tuple[str, ...] = (
    "full",             # the full four-plane representation under test
    "fusion",           # cross-plane fusion (may be the same system as full)
    "code_only",        # code/AST plane alone
    "bm25",             # lexical retrieval baseline
    "rewired",          # degree-preserving randomised cross-plane edges
    "separate_indices",  # four independent per-plane indices, no fusion
    "graph_priority",   # graph-conditioned prioritisation
    "random_priority",  # random selection control
    "evaluator_only",   # evaluator-driven selection control
    "token_matched",    # baseline handed the same extra token budget
)

PLANES: Tuple[str, ...] = ("code", "type", "data", "knowledge")


class SchemaError(ValueError):
    """The input is not a result set this evaluator will grade."""


@dataclass(frozen=True)
class Arm:
    """One measured system, on one query variant, over the whole case set."""

    arm_id: str
    role: str
    variant: str
    scores: Mapping[str, float]
    budget_tokens: Optional[float] = None
    cost_units: Optional[float] = None
    notes: str = ""

    @property
    def ablated_plane(self) -> Optional[str]:
        if self.role.startswith("ablate:"):
            return self.role.split(":", 1)[1]
        return None


@dataclass(frozen=True)
class ResultSet:
    """A frozen measurement run: cases, arms, and the metric to judge on."""

    run_id: str
    primary_metric: str
    cases: Tuple[str, ...]
    arms: Tuple[Arm, ...]
    case_groups: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)
    source: str = ""
    seeds: int = 1

    # -- lookup ---------------------------------------------------------
    def find(self, role: str, variant: Optional[str] = None) -> Optional[Arm]:
        """The single arm with this role (and variant), or ``None``.

        Ambiguity is an error, not a coin flip: two arms claiming the same
        role and variant means the run cannot say what it measured.
        """
        hits = [
            a for a in self.arms
            if a.role == role and (variant is None or a.variant == variant)
        ]
        if len(hits) > 1:
            raise SchemaError(
                f"run {self.run_id!r} has {len(hits)} arms with role {role!r}"
                + (f" and variant {variant!r}" if variant else "")
            )
        return hits[0] if hits else None

    def ablation_arms(self, variant: Optional[str] = None) -> Tuple[Arm, ...]:
        return tuple(
            a for a in self.arms
            if a.ablated_plane is not None
            and (variant is None or a.variant == variant)
        )

    def variants(self) -> Tuple[str, ...]:
        seen: List[str] = []
        for arm in self.arms:
            if arm.variant not in seen:
                seen.append(arm.variant)
        return tuple(seen)

    @property
    def default_variant(self) -> str:
        """The variant the un-scrubbed criteria judge on.

        ``raw`` when present (the harness convention), otherwise whichever
        variant the file listed first.  Never silently mixes two.
        """
        variants = self.variants()
        if not variants:
            raise SchemaError(f"run {self.run_id!r} has no arms")
        return "raw" if "raw" in variants else variants[0]

    def group(self, name: str) -> Optional[Tuple[str, ...]]:
        got = self.case_groups.get(name)
        return tuple(got) if got else None

    # -- io -------------------------------------------------------------
    @staticmethod
    def from_obj(obj: Mapping[str, object]) -> "ResultSet":
        return _parse(obj)

    @staticmethod
    def load(path: str | Path) -> "ResultSet":
        text = Path(path).read_text(encoding="utf-8")
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SchemaError(f"{path}: not valid JSON: {exc}") from exc
        if not isinstance(obj, dict):
            raise SchemaError(f"{path}: top level must be an object")
        return _parse(obj)


def _require(obj: Mapping[str, object], key: str, kind: type, where: str):
    if key not in obj:
        raise SchemaError(f"{where}: missing required field {key!r}")
    val = obj[key]
    if not isinstance(val, kind):
        raise SchemaError(
            f"{where}: field {key!r} must be {kind.__name__}, got {type(val).__name__}"
        )
    return val


def _parse(obj: Mapping[str, object]) -> ResultSet:
    schema = obj.get("schema")
    if schema != SCHEMA_ID:
        raise SchemaError(
            f"unsupported schema {schema!r}; this evaluator reads {SCHEMA_ID!r}"
        )
    run_id = _require(obj, "run_id", str, "result set")
    where = f"run {run_id!r}"
    primary_metric = _require(obj, "primary_metric", str, where)
    raw_cases = _require(obj, "cases", list, where)
    cases: Tuple[str, ...] = tuple(str(c) for c in raw_cases)
    if not cases:
        raise SchemaError(f"{where}: case list is empty")
    if len(set(cases)) != len(cases):
        raise SchemaError(f"{where}: duplicate case ids")

    groups: Dict[str, Tuple[str, ...]] = {}
    raw_groups = obj.get("case_groups") or {}
    if not isinstance(raw_groups, dict):
        raise SchemaError(f"{where}: case_groups must be an object")
    known = set(cases)
    for name, members in raw_groups.items():
        if not isinstance(members, list):
            raise SchemaError(f"{where}: case group {name!r} must be a list")
        member_ids = tuple(str(m) for m in members)
        stray = [m for m in member_ids if m not in known]
        if stray:
            raise SchemaError(
                f"{where}: case group {name!r} names cases outside the run: {stray[:3]}"
            )
        groups[str(name)] = member_ids

    raw_arms = _require(obj, "arms", list, where)
    if not raw_arms:
        raise SchemaError(f"{where}: no arms")
    arms: List[Arm] = []
    seen_ids = set()
    for idx, raw in enumerate(raw_arms):
        arms.append(_parse_arm(raw, idx, cases, primary_metric, where, seen_ids))

    return ResultSet(
        run_id=run_id,
        primary_metric=primary_metric,
        cases=cases,
        arms=tuple(arms),
        case_groups=groups,
        source=str(obj.get("source", "")),
        seeds=int(obj.get("seeds", 1) or 1),
    )


def _parse_arm(
    raw: object,
    idx: int,
    cases: Sequence[str],
    primary_metric: str,
    where: str,
    seen_ids: set,
) -> Arm:
    if not isinstance(raw, dict):
        raise SchemaError(f"{where}: arm #{idx} must be an object")
    arm_id = _require(raw, "arm_id", str, f"{where} arm #{idx}")
    if arm_id in seen_ids:
        raise SchemaError(f"{where}: duplicate arm_id {arm_id!r}")
    seen_ids.add(arm_id)
    spot = f"{where} arm {arm_id!r}"
    role = _require(raw, "role", str, spot)
    if role not in KNOWN_ROLES and not role.startswith("ablate:"):
        raise SchemaError(
            f"{spot}: unknown role {role!r}; expected one of {KNOWN_ROLES} "
            f"or 'ablate:<plane>'"
        )
    plane = role.split(":", 1)[1] if role.startswith("ablate:") else None
    if plane is not None and plane not in PLANES:
        raise SchemaError(f"{spot}: ablated plane {plane!r} is not one of {PLANES}")

    variant = str(raw.get("variant", "raw"))
    all_scores = _require(raw, "scores", dict, spot)
    if primary_metric not in all_scores:
        raise SchemaError(
            f"{spot}: no scores for the declared primary metric {primary_metric!r} "
            f"(has {sorted(all_scores)})"
        )
    per_case = all_scores[primary_metric]
    if not isinstance(per_case, dict):
        raise SchemaError(f"{spot}: scores[{primary_metric!r}] must be an object")

    missing = [c for c in cases if c not in per_case]
    extra = [c for c in per_case if c not in set(cases)]
    if missing:
        raise SchemaError(
            f"{spot}: unpaired -- missing {len(missing)} of {len(cases)} cases "
            f"(e.g. {missing[:3]})"
        )
    if extra:
        raise SchemaError(
            f"{spot}: scores name {len(extra)} cases outside the run (e.g. {extra[:3]})"
        )
    scores: Dict[str, float] = {}
    for case in cases:
        val = per_case[case]
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise SchemaError(f"{spot}: score for case {case!r} is not a number")
        scores[case] = float(val)

    return Arm(
        arm_id=arm_id,
        role=role,
        variant=variant,
        scores=scores,
        budget_tokens=_opt_number(raw.get("budget_tokens"), spot, "budget_tokens"),
        cost_units=_opt_number(raw.get("cost_units"), spot, "cost_units"),
        notes=str(raw.get("notes", "")),
    )


def _opt_number(val: object, spot: str, field_name: str) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise SchemaError(f"{spot}: {field_name} must be a number if present")
    return float(val)


def roles_present(rs: ResultSet, variant: Optional[str] = None) -> List[str]:
    return sorted({a.role for a in rs.arms if variant is None or a.variant == variant})


def dump(rs: ResultSet) -> Dict[str, object]:
    """Round-trip a result set back to the wire form (used by the self-test)."""
    return {
        "schema": SCHEMA_ID,
        "run_id": rs.run_id,
        "source": rs.source,
        "seeds": rs.seeds,
        "primary_metric": rs.primary_metric,
        "cases": list(rs.cases),
        "case_groups": {k: list(v) for k, v in rs.case_groups.items()},
        "arms": [
            {
                "arm_id": a.arm_id,
                "role": a.role,
                "variant": a.variant,
                "budget_tokens": a.budget_tokens,
                "cost_units": a.cost_units,
                "notes": a.notes,
                "scores": {rs.primary_metric: dict(a.scores)},
            }
            for a in rs.arms
        ],
    }


def iter_paired(a: Arm, b: Arm, cases: Iterable[str]) -> List[Tuple[float, float]]:
    """Per-case ``(treatment, baseline)`` pairs, in the run's case order."""
    return [(a.scores[c], b.scores[c]) for c in cases]
