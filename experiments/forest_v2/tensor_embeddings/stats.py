"""Deterministic metrics, paired uncertainty, and report validation.

This module is deliberately effect-free.  It neither opens paths nor invokes
network or subprocess APIs; callers own transport and persistence.  The
report validator is a diagnostic evidence boundary: incomplete or non-finite
measurements refuse.  This experiment currently has no scientific Decision
API; ``ADVANCE``/``KILL`` could be considered only after an owner-recorded
plan/Work-Packet amendment and an externally controlled trust chain.  The
separate sealed-ranking module validates structure and never executes
retriever code, but it is not such a decision authority.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .arm_census import REQUIRED_ARM_NAMES, REQUIRED_COMPARISON_KEYS


REPORT_SCHEMA = "forest-v2.tensor-embedding-report/1"
PACKET_ID = "EXPERIMENT-TENSOR-EMBEDDINGS-001"

# SHA-256 of EXPERIMENT_SPEC.json after canonical JSON serialization (sorted
# keys, compact separators, UTF-8, and non-finite numbers forbidden).  It is
# embedded so validation remains pure and cannot silently follow a changed
# file on disk.
SPEC_DIGEST = "sha256:fda353879ff59c6dbc64b1fb426711cac8bac6d1a17923db6b4cbefe4490b684"
FROZEN_SEEDS = (11, 23, 47, 89, 131)
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20260824

METRIC_NAMES = (
    "reciprocal_rank",
    "recall_at_1",
    "recall_at_5",
    "recall_at_10",
    "recall_at_20",
    "first_hit_coverage",
)
VALID_STATUSES = frozenset({"VALID", "INVALID", "BLOCKED"})
DIAGNOSTIC_CONCLUSION = "INCONCLUSIVE"
NO_SCIENTIFIC_VERDICT = "NO_SCIENTIFIC_VERDICT"

_REPORT_KEYS = frozenset(
    {
        "schema",
        "packet_id",
        "spec_digest",
        "corpus_digest",
        "status",
        "required_arms",
        "seeds",
        "case_ids",
        "arms",
        "failures",
        "comparisons",
        "conclusion",
    }
)
_FAILURE_KEYS = frozenset({"arm", "seed", "case_id", "category", "message"})
_COMPARISON_KEYS = frozenset(
    {
        "left_arm",
        "right_arm",
        "metric",
        "case_count",
        "resamples",
        "seed",
        "delta",
        "ci_low",
        "ci_high",
        "superiority_claim",
    }
)
_SHA256_PREFIXED_LENGTH = len("sha256:") + 64


class ReportValidationError(ValueError):
    """A report is not complete, frozen, or valid as diagnostic evidence."""


@dataclass(frozen=True)
class BootstrapDifference:
    """Percentile-bootstrap interval for the mean paired case difference."""

    delta: float
    ci_low: float
    ci_high: float
    case_count: int
    resamples: int
    seed: int

    @property
    def superiority_claim_allowed(self) -> bool:
        """Whether the interval is positive; reports still reject such claims."""

        return self.ci_low > 0.0

    def as_dict(self) -> dict[str, float | int]:
        return {
            "delta": self.delta,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "case_count": self.case_count,
            "resamples": self.resamples,
            "seed": self.seed,
        }


def _sequence(value: Sequence[Any], name: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes, bytearray)):
        raise TypeError(f"{name} must be a sequence of ranked items, not text")
    return value


def _gold_set(gold: Sequence[Any]) -> set[Any]:
    return set(_sequence(gold, "gold"))


def reciprocal_rank(ranking: Sequence[Any], gold: Sequence[Any]) -> float:
    """Return reciprocal rank of the first gold item, or ``0.0`` on a miss."""

    ranked = _sequence(ranking, "ranking")
    wanted = _gold_set(gold)
    if not wanted:
        return 0.0
    for index, item in enumerate(ranked, start=1):
        if item in wanted:
            return 1.0 / index
    return 0.0


def recall_at_k(ranking: Sequence[Any], gold: Sequence[Any], k: int) -> float:
    """Return unique-gold recall in the first ``k`` ranked positions."""

    if isinstance(k, bool) or not isinstance(k, int) or k <= 0:
        raise ValueError("k must be a positive integer")
    ranked = _sequence(ranking, "ranking")
    wanted = _gold_set(gold)
    if not wanted:
        return 0.0
    hits = wanted.intersection(ranked[:k])
    return len(hits) / len(wanted)


def first_hit_coverage(ranking: Sequence[Any], gold: Sequence[Any]) -> float:
    """Return ``1.0`` iff the supplied ranking contains at least one gold."""

    return 1.0 if reciprocal_rank(ranking, gold) > 0.0 else 0.0


def _finite_number(value: Any, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{path} must be a real number")
    try:
        converted = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise ValueError(f"{path} cannot be represented as float64") from exc
    if not math.isfinite(converted):
        raise ValueError(f"{path} must be finite")
    return converted


def _report_number(value: Any, path: str) -> float:
    try:
        return _finite_number(value, path)
    except ValueError as exc:
        raise ReportValidationError(str(exc)) from exc


def _paired_values(
    left_by_case: Mapping[str, float], right_by_case: Mapping[str, float]
) -> tuple[float, ...]:
    if not isinstance(left_by_case, Mapping) or not isinstance(right_by_case, Mapping):
        raise TypeError("paired bootstrap inputs must be mappings keyed by case ID")
    left_keys = set(left_by_case)
    right_keys = set(right_by_case)
    if not left_keys:
        raise ValueError("paired bootstrap needs at least one case")
    if left_keys != right_keys:
        missing_left = sorted(right_keys - left_keys, key=str)
        missing_right = sorted(left_keys - right_keys, key=str)
        raise ValueError(
            "paired bootstrap needs identical case IDs "
            f"(missing_left={missing_left!r}, missing_right={missing_right!r})"
        )
    if any(not isinstance(case_id, str) or not case_id for case_id in left_keys):
        raise ValueError("paired bootstrap case IDs must be non-empty strings")
    return tuple(
        _finite_number(left_by_case[case_id], f"left[{case_id!r}]")
        - _finite_number(right_by_case[case_id], f"right[{case_id!r}]")
        for case_id in sorted(left_keys)
    )


def _percentile(sorted_values: Sequence[float], probability: float) -> float:
    """Nearest-index percentile, matching the existing Forest v2 convention."""

    index = round(probability * (len(sorted_values) - 1))
    return sorted_values[index]


def paired_bootstrap_difference(
    left_by_case: Mapping[str, float],
    right_by_case: Mapping[str, float],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> BootstrapDifference:
    """Bootstrap mean ``left - right`` using one shared case draw per pair.

    Case IDs, rather than mapping insertion order, determine the input order.
    Each resample draws case indices once and applies those paired differences;
    the two arms are never resampled independently.
    """

    if isinstance(resamples, bool) or not isinstance(resamples, int) or resamples <= 0:
        raise ValueError("resamples must be a positive integer")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed must be an integer")
    differences = _paired_values(left_by_case, right_by_case)
    case_count = len(differences)
    point = sum(differences) / case_count

    if all(value == differences[0] for value in differences):
        low = high = differences[0]
    else:
        rng = random.Random(seed)
        means = []
        for _ in range(resamples):
            total = 0.0
            for _ in range(case_count):
                total += differences[rng.randrange(case_count)]
            means.append(total / case_count)
        means.sort()
        low = _percentile(means, 0.025)
        high = _percentile(means, 0.975)

    return BootstrapDifference(
        delta=point,
        ci_low=low,
        ci_high=high,
        case_count=case_count,
        resamples=resamples,
        seed=seed,
    )


def _json_safe(value: Any) -> None:
    """Reject non-JSON values, cycles, excessive nesting, and NaN/Infinity."""

    stack: list[tuple[str, Any, int]] = [("report", value, 0)]
    active: set[int] = set()
    while stack:
        path, current, depth = stack.pop()
        if depth > 64:
            raise ReportValidationError(f"{path} exceeds maximum JSON depth")
        if current is None or type(current) is bool:
            continue
        if type(current) is str:
            try:
                current.encode("utf-8", "strict")
            except UnicodeEncodeError as exc:
                raise ReportValidationError(
                    f"{path} contains an invalid Unicode surrogate"
                ) from exc
            continue
        if type(current) is int:
            if abs(current) > (1 << 63) - 1:
                raise ReportValidationError(
                    f"{path} exceeds the signed 64-bit JSON integer boundary"
                )
            continue
        if type(current) is float:
            if not math.isfinite(current):
                raise ReportValidationError(f"{path} contains a non-finite number")
            continue
        if type(current) is list:
            identity = id(current)
            if identity in active:
                raise ReportValidationError(f"{path} contains a cycle")
            active.add(identity)
            stack.append((path, _ContainerEnd(identity), depth))
            stack.extend(
                (f"{path}[{index}]", item, depth + 1)
                for index, item in reversed(tuple(enumerate(current)))
            )
            continue
        if type(current) is dict:
            identity = id(current)
            if identity in active:
                raise ReportValidationError(f"{path} contains a cycle")
            if any(type(key) is not str for key in current):
                raise ReportValidationError(f"{path} has a non-string JSON key")
            for key in current:
                try:
                    key.encode("utf-8", "strict")
                except UnicodeEncodeError as exc:
                    raise ReportValidationError(
                        f"{path} has an invalid Unicode-surrogate key"
                    ) from exc
            active.add(identity)
            stack.append((path, _ContainerEnd(identity), depth))
            stack.extend(
                (f"{path}.{key}", item, depth + 1)
                for key, item in reversed(tuple(current.items()))
            )
            continue
        if isinstance(current, _ContainerEnd):
            active.remove(current.identity)
            continue
        raise ReportValidationError(
            f"{path} has non-JSON type {type(current).__name__}"
        )


@dataclass(frozen=True)
class _ContainerEnd:
    identity: int


def _exact_dict(value: Any, keys: frozenset[str], path: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise ReportValidationError(f"{path} must be an object")
    actual = set(value)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        raise ReportValidationError(
            f"{path} keys differ (missing={missing!r}, unknown={unknown!r})"
        )
    return value


def _digest(value: Any, path: str) -> str:
    if (
        type(value) is not str
        or len(value) != _SHA256_PREFIXED_LENGTH
        or not value.startswith("sha256:")
    ):
        raise ReportValidationError(f"{path} must be a lowercase sha256 content ID")
    hex_digest = value[len("sha256:") :]
    if any(ch not in "0123456789abcdef" for ch in hex_digest):
        raise ReportValidationError(f"{path} must be a lowercase sha256 content ID")
    return value


def _unique_strings(value: Any, path: str) -> tuple[str, ...]:
    if type(value) is not list or not value:
        raise ReportValidationError(f"{path} must be a non-empty list")
    if any(type(item) is not str or not item for item in value):
        raise ReportValidationError(f"{path} must contain non-empty strings")
    if len(set(value)) != len(value):
        raise ReportValidationError(f"{path} must not contain duplicates")
    return tuple(value)


def _validate_metric_map(value: Any, path: str) -> None:
    metrics = _exact_dict(value, frozenset(METRIC_NAMES), path)
    numbers = {
        name: _report_number(metrics[name], f"{path}.{name}") for name in METRIC_NAMES
    }
    for name, number in numbers.items():
        if not 0.0 <= number <= 1.0:
            raise ReportValidationError(f"{path}.{name} must be in [0, 1]")
    recalls = [numbers[f"recall_at_{cutoff}"] for cutoff in (1, 5, 10, 20)]
    if recalls != sorted(recalls):
        raise ReportValidationError(f"{path} recall must be monotone in k")
    coverage = numbers["first_hit_coverage"]
    if coverage not in (0.0, 1.0):
        raise ReportValidationError(f"{path}.first_hit_coverage must be binary")
    has_hit = numbers["reciprocal_rank"] > 0.0 or numbers["recall_at_20"] > 0.0
    if has_hit != (coverage == 1.0):
        raise ReportValidationError(f"{path} has inconsistent first-hit metrics")


def _validate_failures(
    value: Any,
    arms: tuple[str, ...],
    seeds: tuple[int, ...],
    cases: tuple[str, ...],
) -> tuple[tuple[str | None, int | None, str | None, str], ...]:
    if type(value) is not list:
        raise ReportValidationError("report.failures must be a list, even when empty")
    failures = []
    for index, item in enumerate(value):
        path = f"report.failures[{index}]"
        failure = _exact_dict(item, _FAILURE_KEYS, path)
        arm = failure["arm"]
        seed = failure["seed"]
        case_id = failure["case_id"]
        category = failure["category"]
        message = failure["message"]
        if arm is not None and (type(arm) is not str or arm not in arms):
            raise ReportValidationError(f"{path}.arm is not a declared arm or null")
        if seed is not None and (
            isinstance(seed, bool) or not isinstance(seed, int) or seed not in seeds
        ):
            raise ReportValidationError(f"{path}.seed is not a frozen seed or null")
        if case_id is not None and (
            type(case_id) is not str or case_id not in cases
        ):
            raise ReportValidationError(f"{path}.case_id is not declared or null")
        if type(category) is not str or not category.strip():
            raise ReportValidationError(f"{path}.category must be non-empty text")
        if type(message) is not str or not message.strip():
            raise ReportValidationError(f"{path}.message must be non-empty text")
        failures.append((arm, seed, case_id, category.strip().lower()))
    return tuple(failures)


def _failure_covers(
    failures: Sequence[tuple[str | None, int | None, str | None, str]],
    arm: str,
    seed: int,
    case_id: str,
) -> bool:
    return any(
        (failure_arm is None or failure_arm == arm)
        and (failure_seed is None or failure_seed == seed)
        and (failure_case is None or failure_case == case_id)
        for failure_arm, failure_seed, failure_case, _ in failures
    )


def _validate_arms(
    value: Any,
    required_arms: tuple[str, ...],
    seeds: tuple[int, ...],
    cases: tuple[str, ...],
    status: str,
    failures: Sequence[tuple[str | None, int | None, str | None, str]],
) -> None:
    arms = _exact_dict(value, frozenset(required_arms), "report.arms")
    expected_seed_keys = {str(seed) for seed in seeds}
    for arm in required_arms:
        arm_runs = arms[arm]
        if type(arm_runs) is not dict:
            raise ReportValidationError(f"report.arms[{arm!r}] must be an object")
        actual_seed_keys = set(arm_runs)
        if any(type(key) is not str for key in arm_runs):
            raise ReportValidationError(f"report.arms[{arm!r}] has a non-string seed key")
        if not actual_seed_keys <= expected_seed_keys:
            raise ReportValidationError(f"report.arms[{arm!r}] has an undeclared seed")
        if status == "VALID" and actual_seed_keys != expected_seed_keys:
            raise ReportValidationError(f"report.arms[{arm!r}] is missing a frozen seed")

        for seed_key, run in arm_runs.items():
            seed = int(seed_key)
            run_path = f"report.arms[{arm!r}][{seed_key!r}]"
            run_obj = _exact_dict(run, frozenset({"per_case"}), run_path)
            per_case = run_obj["per_case"]
            if type(per_case) is not dict:
                raise ReportValidationError(f"{run_path}.per_case must be an object")
            actual_cases = set(per_case)
            if any(type(key) is not str for key in per_case):
                raise ReportValidationError(f"{run_path}.per_case has a non-string key")
            if not actual_cases <= set(cases):
                raise ReportValidationError(f"{run_path}.per_case has an undeclared case")
            if status == "VALID" and actual_cases != set(cases):
                raise ReportValidationError(f"{run_path}.per_case is incomplete")
            for case_id, metrics in per_case.items():
                _validate_metric_map(metrics, f"{run_path}.per_case[{case_id!r}]")

        if status != "VALID":
            for seed in seeds:
                run = arm_runs.get(str(seed))
                present_cases = set(run["per_case"]) if run is not None else set()
                for case_id in cases:
                    if case_id not in present_cases and not _failure_covers(
                        failures, arm, seed, case_id
                    ):
                        raise ReportValidationError(
                            "missing invalid/blocked result has no retained failure: "
                            f"arm={arm!r}, seed={seed}, case={case_id!r}"
                        )


def _validate_comparisons(
    value: Any,
    arms: Mapping[str, Any],
    required_arms: tuple[str, ...],
    seeds: tuple[int, ...],
    cases: tuple[str, ...],
    case_count: int,
    status: str,
) -> bool:
    if type(value) is not list:
        raise ReportValidationError("report.comparisons must be a list")
    if status == "VALID" and not value:
        raise ReportValidationError("a VALID report must retain at least one comparison")
    seen: set[tuple[str, str, str]] = set()
    observed_keys: list[tuple[str, str, str]] = []
    any_superiority = False
    for index, item in enumerate(value):
        path = f"report.comparisons[{index}]"
        comparison = _exact_dict(item, _COMPARISON_KEYS, path)
        left = comparison["left_arm"]
        right = comparison["right_arm"]
        metric = comparison["metric"]
        if type(left) is not str or left not in required_arms:
            raise ReportValidationError(f"{path}.left_arm is not declared")
        if type(right) is not str or right not in required_arms or right == left:
            raise ReportValidationError(f"{path}.right_arm is invalid")
        if type(metric) is not str or metric not in METRIC_NAMES:
            raise ReportValidationError(f"{path}.metric is not a frozen metric")
        key = (left, right, metric)
        if key in seen:
            raise ReportValidationError(f"{path} duplicates a comparison")
        seen.add(key)
        observed_keys.append(key)
        if (
            isinstance(comparison["case_count"], bool)
            or comparison["case_count"] != case_count
        ):
            raise ReportValidationError(f"{path}.case_count does not match case_ids")
        if comparison["resamples"] != BOOTSTRAP_RESAMPLES:
            raise ReportValidationError(f"{path}.resamples is not frozen")
        if comparison["seed"] != BOOTSTRAP_SEED:
            raise ReportValidationError(f"{path}.seed is not frozen")
        delta = _report_number(comparison["delta"], f"{path}.delta")
        low = _report_number(comparison["ci_low"], f"{path}.ci_low")
        high = _report_number(comparison["ci_high"], f"{path}.ci_high")
        if any(not -1.0 <= number <= 1.0 for number in (delta, low, high)):
            raise ReportValidationError(f"{path} metric differences must be in [-1, 1]")
        if low > high:
            raise ReportValidationError(f"{path} has an inverted interval")
        claim = comparison["superiority_claim"]
        if type(claim) is not bool:
            raise ReportValidationError(f"{path}.superiority_claim must be boolean")
        if claim and low <= 0.0:
            raise ReportValidationError(
                f"{path} claims superiority although its CI crosses or touches zero"
            )
        if claim and status != "VALID":
            raise ReportValidationError(
                f"{path} cannot claim superiority from an {status} report"
            )
        if status == "VALID":
            left_by_case = {
                case_id: sum(
                    arms[left][str(frozen_seed)]["per_case"][case_id][metric]
                    for frozen_seed in seeds
                )
                / len(seeds)
                for case_id in cases
            }
            right_by_case = {
                case_id: sum(
                    arms[right][str(frozen_seed)]["per_case"][case_id][metric]
                    for frozen_seed in seeds
                )
                / len(seeds)
                for case_id in cases
            }
            calculated = paired_bootstrap_difference(
                left_by_case,
                right_by_case,
                resamples=BOOTSTRAP_RESAMPLES,
                seed=BOOTSTRAP_SEED,
            )
            observed = (delta, low, high)
            expected = (calculated.delta, calculated.ci_low, calculated.ci_high)
            if any(
                not math.isclose(actual, wanted, rel_tol=1e-12, abs_tol=1e-12)
                for actual, wanted in zip(observed, expected)
            ):
                raise ReportValidationError(
                    f"{path} does not match the paired per-case bootstrap"
                )
        any_superiority = any_superiority or claim
    if status == "VALID" and tuple(observed_keys) != REQUIRED_COMPARISON_KEYS:
        raise ReportValidationError(
            "a VALID report must retain the complete frozen comparison census"
        )
    return any_superiority


def validate_report(
    report: Mapping[str, Any],
    *,
    expected_corpus_digest: str | None = None,
    expected_case_ids: Sequence[str] | None = None,
) -> None:
    """Validate the complete experiment report or raise ``ReportValidationError``.

    ``expected_corpus_digest`` and ``expected_case_ids`` bind a report to the
    caller's independently frozen inputs.  Without them the report must still
    carry a syntactically valid content digest and a non-empty unique case
    census; a validator cannot infer a corpus identity from scores alone.

    A ``VALID`` report must contain the full declared arm x seed x case
    Cartesian product and an exactly empty failure list. It is still
    diagnostic: it must use ``INCONCLUSIVE`` and cannot retain a superiority
    claim. ``INVALID``/``BLOCKED`` reports may retain partial measurements,
    but every missing cell must be covered by an explicit failure record and
    their conclusion is always ``NO_SCIENTIFIC_VERDICT``. There is no Decision
    API in this experiment.
    """

    _json_safe(report)
    body = _exact_dict(report, _REPORT_KEYS, "report")
    if body["schema"] != REPORT_SCHEMA:
        raise ReportValidationError("report.schema does not match the frozen schema")
    if body["packet_id"] != PACKET_ID:
        raise ReportValidationError("report.packet_id does not match the Work Packet")
    if body["spec_digest"] != SPEC_DIGEST:
        raise ReportValidationError("report.spec_digest does not match the frozen spec")
    corpus_digest = _digest(body["corpus_digest"], "report.corpus_digest")
    if expected_corpus_digest is not None:
        expected = _digest(expected_corpus_digest, "expected_corpus_digest")
        if corpus_digest != expected:
            raise ReportValidationError("report.corpus_digest does not match input")

    status = body["status"]
    if type(status) is not str or status not in VALID_STATUSES:
        raise ReportValidationError("report.status must be VALID, INVALID, or BLOCKED")
    required_arms = _unique_strings(body["required_arms"], "report.required_arms")
    if required_arms != REQUIRED_ARM_NAMES:
        raise ReportValidationError(
            "report.required_arms is not the complete frozen arm census"
        )

    seeds_value = body["seeds"]
    if type(seeds_value) is not list or any(
        isinstance(seed, bool) or not isinstance(seed, int) for seed in seeds_value
    ):
        raise ReportValidationError("report.seeds must be an integer list")
    if len(set(seeds_value)) != len(seeds_value):
        raise ReportValidationError("report.seeds must not contain duplicates")
    seeds = tuple(seeds_value)
    if seeds != FROZEN_SEEDS:
        raise ReportValidationError("report.seeds do not match the frozen seed policy")

    cases = _unique_strings(body["case_ids"], "report.case_ids")
    if expected_case_ids is not None:
        expected_cases = tuple(expected_case_ids)
        if cases != expected_cases:
            raise ReportValidationError("report.case_ids do not match frozen inputs")

    failures = _validate_failures(body["failures"], required_arms, seeds, cases)
    invalidating_failure = any(
        any(marker in category for marker in ("isolation", "budget", "input"))
        for _, _, _, category in failures
    )
    if status == "VALID" and invalidating_failure:
        raise ReportValidationError(
            "isolation, budget, or input failures make a report INVALID/BLOCKED"
        )
    if status == "VALID" and failures:
        raise ReportValidationError(
            "a VALID report requires report.failures to be exactly empty"
        )
    if status != "VALID" and not failures:
        raise ReportValidationError(f"an {status} report must retain its failures")

    _validate_arms(body["arms"], required_arms, seeds, cases, status, failures)
    any_superiority = _validate_comparisons(
        body["comparisons"], body["arms"], required_arms, seeds, cases, len(cases), status
    )

    conclusion = body["conclusion"]
    if status == "VALID":
        if conclusion != DIAGNOSTIC_CONCLUSION:
            raise ReportValidationError(
                "a VALID diagnostic report must be INCONCLUSIVE; "
                "this experiment has no ADVANCE/KILL Decision API"
            )
        if any_superiority:
            raise ReportValidationError(
                "a diagnostic report cannot retain a superiority claim"
            )
    elif conclusion != NO_SCIENTIFIC_VERDICT:
        raise ReportValidationError(
            "INVALID/BLOCKED reports must use NO_SCIENTIFIC_VERDICT; "
            "this experiment has no ADVANCE/KILL Decision API"
        )


def report_from_bytes(
    raw: bytes | str,
    *,
    expected_corpus_digest: str | None = None,
    expected_case_ids: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Strictly decode and validate one serialized experiment report.

    Duplicate object keys and non-finite JSON constants are rejected while
    parsing, before ordinary ``dict`` construction could hide them.  Bytes
    must be strict UTF-8; accepting text as well keeps this symmetric with the
    other experiment contract loaders.
    """

    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise ReportValidationError("serialized report is not UTF-8") from exc
    elif type(raw) is str:
        text = raw
    else:
        raise ReportValidationError("serialized report must be bytes or str")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ReportValidationError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ReportValidationError(
            f"non-finite JSON number is forbidden: {value}"
        )

    try:
        decoded = json.loads(
            text,
            object_pairs_hook=pairs,
            parse_constant=reject_constant,
        )
    except ReportValidationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ReportValidationError(f"invalid serialized report: {exc}") from exc
    if type(decoded) is not dict:
        raise ReportValidationError("serialized report must be an object")
    validate_report(
        decoded,
        expected_corpus_digest=expected_corpus_digest,
        expected_case_ids=expected_case_ids,
    )
    return decoded


def canonical_report_bytes(
    report: Mapping[str, Any],
    *,
    expected_corpus_digest: str | None = None,
    expected_case_ids: Sequence[str] | None = None,
) -> bytes:
    """Return validated canonical UTF-8 JSON bytes, with no trailing newline."""

    validate_report(
        report,
        expected_corpus_digest=expected_corpus_digest,
        expected_case_ids=expected_case_ids,
    )
    try:
        return json.dumps(
            report,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8", "strict")
    except (TypeError, ValueError, UnicodeEncodeError) as exc:
        raise ReportValidationError(
            "validated report could not be canonically encoded"
        ) from exc


def report_digest(
    report: Mapping[str, Any],
    *,
    expected_corpus_digest: str | None = None,
    expected_case_ids: Sequence[str] | None = None,
) -> str:
    """Return the prefixed SHA-256 of :func:`canonical_report_bytes`."""

    payload = canonical_report_bytes(
        report,
        expected_corpus_digest=expected_corpus_digest,
        expected_case_ids=expected_case_ids,
    )
    return "sha256:" + hashlib.sha256(payload).hexdigest()


__all__ = [
    "BOOTSTRAP_RESAMPLES",
    "BOOTSTRAP_SEED",
    "BootstrapDifference",
    "DIAGNOSTIC_CONCLUSION",
    "FROZEN_SEEDS",
    "METRIC_NAMES",
    "NO_SCIENTIFIC_VERDICT",
    "PACKET_ID",
    "REPORT_SCHEMA",
    "REQUIRED_ARM_NAMES",
    "REQUIRED_COMPARISON_KEYS",
    "ReportValidationError",
    "SPEC_DIGEST",
    "canonical_report_bytes",
    "first_hit_coverage",
    "paired_bootstrap_difference",
    "recall_at_k",
    "reciprocal_rank",
    "report_from_bytes",
    "report_digest",
    "validate_report",
]
