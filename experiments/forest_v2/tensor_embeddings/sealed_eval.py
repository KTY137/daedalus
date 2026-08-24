"""Gold-separated descriptive evaluation over sealed ranking manifests.

This module is a data boundary, not a ranking harness.  It imports no
retriever or benchmark implementation and accepts no callback.  Ranking code
runs elsewhere without gold; this evaluator receives only content-addressed
JSON values after ranking has finished, validates the frozen census and
budgets, and then joins rankings to a separately sealed gold manifest.

Content addresses prove byte integrity, not provenance, execution order, or
isolation.  Consequently, even a structurally complete set is reported only
as ``STRUCTURALLY_VALID_UNANCHORED`` with ``NO_SCIENTIFIC_VERDICT``.  A caller
cannot turn this module into a decision API by setting Boolean receipt fields.
Malformed or incomplete inputs are ``BLOCKED``.  Every output remains an
experiment report and grants no promotion authority.

A future decision API is intentionally absent.  It would require all of the
following *before* measured results are read:

* an externally verified signature or append-only-ledger trust chain over the
  exact owner-frozen input/taskset/gold/implementation identities, a pre-gold
  ranking commitment, and an independently issued isolation receipt;
* an owner-reviewed Work-Packet/spec amendment freezing the complete case and
  repository census, minimum sample policy, decision truth table, null and
  equivalence margins, and seed/repository resampling policy;
* independent A4 per-candidate score evidence proving identity contraction
  equals flattened cosine within ``1e-10``;
* measured, artifact-bound scalar, canonical-storage-byte, query-cost and
  baseline-index receipts rather than caller-declared integers;
* evidence for kill criteria 4--7: collision/context/tuning attribution,
  CP/TT quality-cost frontier, transfer to a second revision-pinned repository,
  and replayable source/input/filler/failure evidence.

Until those prerequisites exist, descriptive intervals are useful diagnostics
only.  All ``superiority_claim`` fields are forced to ``false``.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .stats import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    FROZEN_SEEDS,
    NO_SCIENTIFIC_VERDICT,
    PACKET_ID,
    SPEC_DIGEST,
    first_hit_coverage,
    paired_bootstrap_difference,
    recall_at_k,
    reciprocal_rank,
)


INPUT_MANIFEST_SCHEMA = "forest-v2.tensor-sealed-input/1"
RANKINGS_MANIFEST_SCHEMA = "forest-v2.tensor-sealed-rankings/1"
GOLD_MANIFEST_SCHEMA = "forest-v2.tensor-sealed-gold/1"
ISOLATION_RECEIPT_SCHEMA = "forest-v2.tensor-sealed-isolation/1"
SEALED_REPORT_SCHEMA = "forest-v2.tensor-sealed-descriptive-report/2"
STRUCTURALLY_VALID_UNANCHORED = "STRUCTURALLY_VALID_UNANCHORED"
_SEALED_REPORT_ID_DOMAIN = "tensor-sealed-report-self-address/1"
_MAX_JSON_INTEGER = (1 << 63) - 1

QUERY_VARIANTS = ("raw", "scrubbed")
DENSE_SCALAR_BUDGET = 512
DENSE_EQUIVALENT_FLOAT64_BYTES = 512 * 8
CANDIDATE_CONTENT_BUDGET_BYTES = 65_536
MAX_CANDIDATES_PER_CASE = 65_536
MAX_FILE_BYTES = 200_000
MAX_RANK = 20

MISSING_DECISION_PREREQUISITES = (
    "externally verified signed or ledger-anchored campaign, input, pre-gold ranking, isolation, and gold trust chain",
    "owner-reviewed Work-Packet/spec amendment freezing case/repository census, sample policy, margins, truth table, and resampling",
    "independent A4 per-candidate identity-vs-cosine score equality receipt within 1e-10",
    "independent tensor-contraction-vs-flattened-bilinear equality receipt within 1e-10",
    "artifact-bound actual storage, scalar, baseline-index, and query-cost receipts",
    "kill-criteria 4-7 evidence for collision/context/tuning attribution, CP/TT frontier, second-repository transfer, and replay",
)

REQUIRED_ARMS = (
    "flattened_cosine_same_scalars",
    "identity_contraction",
    "structured_contraction",
    "flattened_bilinear_same_kernel",
    "tensor_late_interaction",
    "plane_label_permutation",
    "role_label_permutation",
    "uniform_kernel",
    "bm25",
    "random_uniform",
    "path_lexical",
    "recency_prior",
    "fusion_rrf",
)
TENSOR_ARMS = frozenset(REQUIRED_ARMS[:8])
PRIMARY_ARM = "structured_contraction"
REFERENCE_ARM = "flattened_cosine_same_scalars"

_SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_REVISION = re.compile(r"^[0-9a-f]{40}$")
_CONTENT_ID = re.compile(r"^(?:sha256:[0-9a-f]{64}|git-sha1:[0-9a-f]{40})$")


class SealedEvaluationError(ValueError):
    """One sealed input is not eligible for scientific evaluation."""


def _ensure_json(value: object, path: str = "value", depth: int = 0, active: set[int] | None = None) -> None:
    """Accept only finite, acyclic, ordinary JSON values.

    Requiring exact ``dict``/``list`` values also prevents a caller from
    smuggling an executable mapping, iterator, or callback across the sealed
    boundary.
    """

    if depth > 64:
        raise SealedEvaluationError(f"{path} exceeds the maximum JSON depth")
    if type(value) is str:
        try:
            value.encode("utf-8", "strict")
        except UnicodeEncodeError as exc:
            raise SealedEvaluationError(
                f"{path} contains an invalid Unicode surrogate"
            ) from exc
        return
    if value is None or type(value) is bool:
        return
    if type(value) is int:
        if abs(value) > _MAX_JSON_INTEGER:
            raise SealedEvaluationError(
                f"{path} exceeds the signed 64-bit JSON integer boundary"
            )
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise SealedEvaluationError(f"{path} contains a non-finite number")
        return
    if type(value) not in (dict, list):
        raise SealedEvaluationError(f"{path} must contain ordinary JSON values only")

    active = set() if active is None else active
    identity = id(value)
    if identity in active:
        raise SealedEvaluationError(f"{path} contains a cycle")
    active.add(identity)
    try:
        if type(value) is dict:
            for key, item in value.items():
                if type(key) is not str:
                    raise SealedEvaluationError(f"{path} has a non-string object key")
                try:
                    key.encode("utf-8", "strict")
                except UnicodeEncodeError as exc:
                    raise SealedEvaluationError(
                        f"{path} has an invalid Unicode-surrogate key"
                    ) from exc
                _ensure_json(item, f"{path}.{key}", depth + 1, active)
        else:
            for index, item in enumerate(value):
                _ensure_json(item, f"{path}[{index}]", depth + 1, active)
    finally:
        active.remove(identity)


def _canonical_json_bytes(value: object) -> bytes:
    _ensure_json(value)
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _content_digest(value: object, *, domain: str) -> str:
    payload = domain.encode("utf-8") + b"\x00" + _canonical_json_bytes(value)
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _manifest_digest(schema: str, payload: Mapping[str, Any]) -> str:
    return _content_digest(
        {"schema": schema, "payload": dict(payload)}, domain="tensor-sealed-manifest/1"
    )


def seal_manifest(schema: str, payload: Mapping[str, Any]) -> dict[str, object]:
    """Return a canonical content-addressed manifest envelope.

    This helper does not attest that the payload is true; it only gives the
    exact bytes an independent producer/isolation boundary must bind.  The
    schema-specific checks happen in :func:`evaluate_sealed_rankings`.
    """

    if type(schema) is not str or not schema:
        raise SealedEvaluationError("manifest schema must be non-empty text")
    if type(payload) is not dict:
        raise SealedEvaluationError("manifest payload must be an ordinary object")
    _ensure_json(payload, "manifest.payload")
    body = dict(payload)
    return {"schema": schema, "payload": body, "digest": _manifest_digest(schema, body)}


def manifest_from_bytes(raw: bytes | str) -> dict[str, object]:
    """Decode one manifest without allowing duplicate keys or JSON constants."""

    if isinstance(raw, bytes):
        try:
            text = raw.decode("utf-8", "strict")
        except UnicodeDecodeError as exc:
            raise SealedEvaluationError("manifest bytes are not UTF-8") from exc
    elif type(raw) is str:
        text = raw
    else:
        raise SealedEvaluationError("serialized manifest must be bytes or text")

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise SealedEvaluationError(f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    def constant(value: str) -> object:
        raise SealedEvaluationError(f"non-finite JSON constant {value!r}")

    try:
        value = json.loads(text, object_pairs_hook=pairs, parse_constant=constant)
    except SealedEvaluationError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise SealedEvaluationError("manifest is not strict JSON") from exc
    _ensure_json(value, "manifest")
    if type(value) is not dict:
        raise SealedEvaluationError("manifest must be a JSON object")
    return value


def _exact(value: object, keys: frozenset[str], path: str) -> dict[str, Any]:
    if type(value) is not dict:
        raise SealedEvaluationError(f"{path} must be an object")
    actual = set(value)
    if actual != keys:
        raise SealedEvaluationError(
            f"{path} key mismatch; unknown={sorted(actual - keys)!r}, "
            f"missing={sorted(keys - actual)!r}"
        )
    return value


def _array(value: object, path: str, *, nonempty: bool = True) -> list[Any]:
    if type(value) is not list or (nonempty and not value):
        suffix = "non-empty " if nonempty else ""
        raise SealedEvaluationError(f"{path} must be a {suffix}array")
    return value


def _text(value: object, path: str) -> str:
    if type(value) is not str or not value or value.strip() != value:
        raise SealedEvaluationError(f"{path} must be non-empty trimmed text")
    return value


def _bounded_text(value: object, path: str, *, max_bytes: int) -> str:
    text = _text(value, path)
    if len(text.encode("utf-8")) > max_bytes:
        raise SealedEvaluationError(f"{path} exceeds the frozen {max_bytes}-byte cap")
    return text


def _frozen_seed(value: object, path: str) -> int:
    if isinstance(value, bool) or type(value) is not int or value not in FROZEN_SEEDS:
        raise SealedEvaluationError(f"{path} is outside the frozen seed policy")
    return value


def _digest(value: object, path: str) -> str:
    text = _text(value, path)
    if not _SHA256.fullmatch(text):
        raise SealedEvaluationError(f"{path} must be a sha256 content address")
    return text


def _revision(value: object, path: str) -> str:
    text = _text(value, path)
    if not _GIT_REVISION.fullmatch(text):
        raise SealedEvaluationError(f"{path} must be a full lowercase Git revision")
    return text


def _positive_int(value: object, path: str, *, maximum: int | None = None) -> int:
    if isinstance(value, bool) or type(value) is not int or value <= 0:
        raise SealedEvaluationError(f"{path} must be a positive integer")
    if maximum is not None and value > maximum:
        raise SealedEvaluationError(f"{path} exceeds the frozen maximum {maximum}")
    return value


def _open_manifest(
    value: object, expected_schema: str, path: str
) -> tuple[dict[str, Any], str]:
    _ensure_json(value, path)
    body = _exact(value, frozenset({"schema", "payload", "digest"}), path)
    if body["schema"] != expected_schema:
        raise SealedEvaluationError(f"{path}.schema is not {expected_schema!r}")
    payload = body["payload"]
    if type(payload) is not dict:
        raise SealedEvaluationError(f"{path}.payload must be an object")
    digest = _digest(body["digest"], f"{path}.digest")
    expected = _manifest_digest(expected_schema, payload)
    if digest != expected:
        raise SealedEvaluationError(f"{path}.digest does not address its payload")
    return payload, digest


def candidate_manifest_digest(candidates: Sequence[Mapping[str, Any]]) -> str:
    """Content address one ordered, revision-bound candidate census."""

    if type(candidates) is not list:
        candidates = list(candidates)
    return _content_digest(candidates, domain="tensor-sealed-candidates/1")


def source_manifest_digest(
    *,
    repository_id: str,
    source_revision: str,
    preimage_revision: str,
    candidate_digest: str,
) -> str:
    """Bind the candidate census to one repository and atomic pre-image."""

    return _content_digest(
        {
            "repository_id": repository_id,
            "source_revision": source_revision,
            "preimage_revision": preimage_revision,
            "candidate_manifest_digest": candidate_digest,
        },
        domain="tensor-sealed-source-manifest/1",
    )


@dataclass(frozen=True)
class _Case:
    case_id: str
    repository_id: str
    revision: str
    source_manifest_digest: str
    candidate_manifest_digest: str
    candidate_ids: tuple[str, ...]
    candidate_input_bytes: int
    query_digests: Mapping[str, str]
    query_bytes: Mapping[str, int]


@dataclass(frozen=True)
class _Input:
    digest: str
    taskset_digest: str
    implementation_revision: str
    cases: tuple[_Case, ...]

    @property
    def census(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (case.case_id, variant) for case in self.cases for variant in QUERY_VARIANTS
        )


_INPUT_KEYS = frozenset(
    {
        "packet_id",
        "spec_digest",
        "implementation_revision",
        "taskset_digest",
        "tuning_data_digest",
        "evaluation_split",
        "query_variants",
        "seeds",
        "required_arms",
        "dense_scalar_budget",
        "dense_equivalent_float64_bytes",
        "candidate_content_budget_bytes",
        "max_file_bytes",
        "cases",
    }
)
_CASE_KEYS = frozenset(
    {
        "case_id",
        "repository_id",
        "source_revision",
        "preimage_revision",
        "source_manifest_digest",
        "candidate_manifest_digest",
        "candidates",
        "queries",
    }
)
_CANDIDATE_KEYS = frozenset(
    {
        "candidate_id",
        "source_locator",
        "source_revision",
        "source_digest",
        "blob_id",
        "size_bytes",
        "visible_bytes",
        "visible_digest",
    }
)
_QUERY_KEYS = frozenset({"query_digest", "query_bytes"})


def _validate_input(manifest: object) -> _Input:
    payload, manifest_digest = _open_manifest(
        manifest, INPUT_MANIFEST_SCHEMA, "input_manifest"
    )
    body = _exact(payload, _INPUT_KEYS, "input_manifest.payload")
    if body["packet_id"] != PACKET_ID:
        raise SealedEvaluationError("input packet_id does not match the frozen Work Packet")
    if body["spec_digest"] != SPEC_DIGEST:
        raise SealedEvaluationError("input spec_digest does not match the frozen spec")
    implementation_revision = _revision(
        body["implementation_revision"], "input.implementation_revision"
    )
    taskset_digest = _digest(body["taskset_digest"], "input.taskset_digest")
    tuning_digest = _digest(body["tuning_data_digest"], "input.tuning_data_digest")
    if tuning_digest == taskset_digest:
        raise SealedEvaluationError("held-out taskset must differ from tuning data")
    if body["evaluation_split"] != "held-out":
        raise SealedEvaluationError("scientific evaluation requires the held-out split")
    if body["query_variants"] != list(QUERY_VARIANTS):
        raise SealedEvaluationError("input must freeze raw and scrubbed variants in order")
    if body["seeds"] != list(FROZEN_SEEDS):
        raise SealedEvaluationError("input seeds do not match the frozen five-seed policy")
    if body["required_arms"] != list(REQUIRED_ARMS):
        raise SealedEvaluationError("input required_arms is not the complete frozen arm set")
    if body["dense_scalar_budget"] != DENSE_SCALAR_BUDGET:
        raise SealedEvaluationError("input dense scalar budget must be exactly 512")
    if body["dense_equivalent_float64_bytes"] != DENSE_EQUIVALENT_FLOAT64_BYTES:
        raise SealedEvaluationError(
            "input dense-equivalent float64 size must be exactly 4096 bytes; "
            "this is not a measured storage receipt"
        )
    if body["candidate_content_budget_bytes"] != CANDIDATE_CONTENT_BUDGET_BYTES:
        raise SealedEvaluationError("candidate content budget must be exactly 65536 bytes")
    if body["max_file_bytes"] != MAX_FILE_BYTES:
        raise SealedEvaluationError("max file budget must match the frozen s09 budget")

    raw_cases = _array(body["cases"], "input.cases")
    cases: list[_Case] = []
    for case_index, value in enumerate(raw_cases):
        path = f"input.cases[{case_index}]"
        case = _exact(value, _CASE_KEYS, path)
        case_id = _text(case["case_id"], f"{path}.case_id")
        if "::" in case_id:
            raise SealedEvaluationError(f"{path}.case_id contains the reserved '::' separator")
        repository_id = _digest(case["repository_id"], f"{path}.repository_id")
        source_revision = _revision(case["source_revision"], f"{path}.source_revision")
        preimage_revision = _revision(case["preimage_revision"], f"{path}.preimage_revision")
        if source_revision != preimage_revision:
            raise SealedEvaluationError(
                f"{path} is a partial revision: source and pre-image revisions differ"
            )

        raw_candidates = _array(case["candidates"], f"{path}.candidates")
        if len(raw_candidates) > MAX_CANDIDATES_PER_CASE:
            raise SealedEvaluationError(
                f"{path}.candidate count exceeds the frozen maximum "
                f"{MAX_CANDIDATES_PER_CASE}"
            )
        candidate_ids: list[str] = []
        visible_total = 0
        for candidate_index, candidate_value in enumerate(raw_candidates):
            candidate_path = f"{path}.candidates[{candidate_index}]"
            candidate = _exact(candidate_value, _CANDIDATE_KEYS, candidate_path)
            candidate_id = _bounded_text(
                candidate["candidate_id"],
                f"{candidate_path}.candidate_id",
                max_bytes=CANDIDATE_CONTENT_BUDGET_BYTES,
            )
            locator = _bounded_text(
                candidate["source_locator"],
                f"{candidate_path}.source_locator",
                max_bytes=CANDIDATE_CONTENT_BUDGET_BYTES,
            )
            if candidate_id != locator:
                raise SealedEvaluationError(
                    f"{candidate_path} candidate_id must equal the ranked source locator"
                )
            if _revision(candidate["source_revision"], f"{candidate_path}.source_revision") != source_revision:
                raise SealedEvaluationError(f"{candidate_path} is bound to a different revision")
            _digest(candidate["source_digest"], f"{candidate_path}.source_digest")
            blob_id = _text(candidate["blob_id"], f"{candidate_path}.blob_id")
            if not _CONTENT_ID.fullmatch(blob_id):
                raise SealedEvaluationError(
                    f"{candidate_path}.blob_id must be prefixed git-sha1 or sha256"
                )
            size_bytes = _positive_int(
                candidate["size_bytes"], f"{candidate_path}.size_bytes", maximum=MAX_FILE_BYTES
            )
            visible_bytes = _positive_int(
                candidate["visible_bytes"],
                f"{candidate_path}.visible_bytes",
                maximum=CANDIDATE_CONTENT_BUDGET_BYTES,
            )
            if visible_bytes != min(size_bytes, CANDIDATE_CONTENT_BUDGET_BYTES):
                raise SealedEvaluationError(
                    f"{candidate_path}.visible_bytes does not equal the frozen byte cap"
                )
            _digest(candidate["visible_digest"], f"{candidate_path}.visible_digest")
            candidate_ids.append(candidate_id)
            visible_total += visible_bytes

        if candidate_ids != sorted(candidate_ids) or len(set(candidate_ids)) != len(candidate_ids):
            raise SealedEvaluationError(
                f"{path}.candidates must be uniquely sorted by candidate_id"
            )
        expected_candidate_digest = candidate_manifest_digest(raw_candidates)
        candidate_digest = _digest(
            case["candidate_manifest_digest"], f"{path}.candidate_manifest_digest"
        )
        if candidate_digest != expected_candidate_digest:
            raise SealedEvaluationError(
                f"{path}.candidate_manifest_digest does not address the candidate census"
            )
        expected_source_digest = source_manifest_digest(
            repository_id=repository_id,
            source_revision=source_revision,
            preimage_revision=preimage_revision,
            candidate_digest=candidate_digest,
        )
        source_digest = _digest(
            case["source_manifest_digest"], f"{path}.source_manifest_digest"
        )
        if source_digest != expected_source_digest:
            raise SealedEvaluationError(
                f"{path}.source_manifest_digest does not bind revision and candidates"
            )

        queries = _exact(case["queries"], frozenset(QUERY_VARIANTS), f"{path}.queries")
        query_digests: dict[str, str] = {}
        query_bytes: dict[str, int] = {}
        for variant in QUERY_VARIANTS:
            query = _exact(queries[variant], _QUERY_KEYS, f"{path}.queries.{variant}")
            query_digests[variant] = _digest(
                query["query_digest"], f"{path}.queries.{variant}.query_digest"
            )
            query_bytes[variant] = _positive_int(
                query["query_bytes"], f"{path}.queries.{variant}.query_bytes"
            )
            if query_bytes[variant] > CANDIDATE_CONTENT_BUDGET_BYTES:
                raise SealedEvaluationError(
                    f"{path}.queries.{variant}.query_bytes exceeds the frozen "
                    f"{CANDIDATE_CONTENT_BUDGET_BYTES}-byte cap"
                )
        cases.append(
            _Case(
                case_id=case_id,
                repository_id=repository_id,
                revision=preimage_revision,
                source_manifest_digest=source_digest,
                candidate_manifest_digest=candidate_digest,
                candidate_ids=tuple(candidate_ids),
                candidate_input_bytes=visible_total,
                query_digests=query_digests,
                query_bytes=query_bytes,
            )
        )

    case_ids = [case.case_id for case in cases]
    if case_ids != sorted(case_ids) or len(set(case_ids)) != len(case_ids):
        raise SealedEvaluationError("input cases must be uniquely sorted by case_id")
    return _Input(
        digest=manifest_digest,
        taskset_digest=taskset_digest,
        implementation_revision=implementation_revision,
        cases=tuple(cases),
    )


_RANKINGS_KEYS = frozenset(
    {"packet_id", "spec_digest", "input_manifest_digest", "implementation_revision", "rows", "failures"}
)
_RANKING_KEYS = frozenset(
    {
        "arm",
        "seed",
        "case_id",
        "variant",
        "preimage_revision",
        "source_manifest_digest",
        "candidate_manifest_digest",
        "query_digest",
        "budget",
        "ranking",
    }
)
_BUDGET_KEYS = frozenset(
    {
        "tensor_dense_scalars",
        "tensor_dense_equivalent_float64_bytes",
        "candidate_content_budget_bytes",
        "candidate_input_bytes",
        "query_input_bytes",
    }
)
_RANKING_FAILURE_KEYS = frozenset(
    {"arm", "seed", "case_id", "variant", "category", "message"}
)


def _validate_rankings(
    manifest: object, inputs: _Input
) -> tuple[str, dict[tuple[str, int, str, str], tuple[str, ...]]]:
    payload, digest = _open_manifest(
        manifest, RANKINGS_MANIFEST_SCHEMA, "rankings_manifest"
    )
    body = _exact(payload, _RANKINGS_KEYS, "rankings_manifest.payload")
    if body["packet_id"] != PACKET_ID or body["spec_digest"] != SPEC_DIGEST:
        raise SealedEvaluationError("rankings packet/spec identity is stale")
    if body["input_manifest_digest"] != inputs.digest:
        raise SealedEvaluationError("rankings are not bound to the sealed input manifest")
    if body["implementation_revision"] != inputs.implementation_revision:
        raise SealedEvaluationError("rankings implementation revision differs from input")

    failures = _array(body["failures"], "rankings.failures", nonempty=False)
    for index, value in enumerate(failures):
        failure = _exact(value, _RANKING_FAILURE_KEYS, f"rankings.failures[{index}]")
        if failure["arm"] not in REQUIRED_ARMS:
            raise SealedEvaluationError(f"rankings.failures[{index}].arm is unknown")
        _frozen_seed(failure["seed"], f"rankings.failures[{index}].seed")
        _text(failure["case_id"], f"rankings.failures[{index}].case_id")
        if failure["variant"] not in QUERY_VARIANTS:
            raise SealedEvaluationError(f"rankings.failures[{index}].variant is unknown")
        _text(failure["category"], f"rankings.failures[{index}].category")
        _text(failure["message"], f"rankings.failures[{index}].message")
    if failures:
        raise SealedEvaluationError(
            f"ranking campaign retained {len(failures)} failed arm/seed/case runs"
        )

    rows = _array(body["rows"], "rankings.rows")
    expected_keys = [
        (arm, seed, case.case_id, variant)
        for arm in REQUIRED_ARMS
        for seed in FROZEN_SEEDS
        for case in inputs.cases
        for variant in QUERY_VARIANTS
    ]
    actual_keys: list[tuple[str, int, str, str]] = []
    rankings: dict[tuple[str, int, str, str], tuple[str, ...]] = {}
    case_by_id = {case.case_id: case for case in inputs.cases}
    for index, value in enumerate(rows):
        path = f"rankings.rows[{index}]"
        row = _exact(value, _RANKING_KEYS, path)
        arm = _text(row["arm"], f"{path}.arm")
        seed = _frozen_seed(row["seed"], f"{path}.seed")
        case_id = _text(row["case_id"], f"{path}.case_id")
        variant = _text(row["variant"], f"{path}.variant")
        key = (arm, seed, case_id, variant)
        actual_keys.append(key)
        if arm not in REQUIRED_ARMS or variant not in QUERY_VARIANTS:
            raise SealedEvaluationError(f"{path} is outside the frozen arm/seed/variant census")
        case = case_by_id.get(case_id)
        if case is None:
            raise SealedEvaluationError(f"{path}.case_id is outside the frozen census")
        if row["preimage_revision"] != case.revision:
            raise SealedEvaluationError(f"{path}.preimage_revision differs from input")
        if row["source_manifest_digest"] != case.source_manifest_digest:
            raise SealedEvaluationError(f"{path}.source_manifest_digest differs from input")
        if row["candidate_manifest_digest"] != case.candidate_manifest_digest:
            raise SealedEvaluationError(f"{path}.candidate_manifest_digest differs from input")
        if row["query_digest"] != case.query_digests[variant]:
            raise SealedEvaluationError(f"{path}.query_digest differs from input")

        budget = _exact(row["budget"], _BUDGET_KEYS, f"{path}.budget")
        tensor_scalars = DENSE_SCALAR_BUDGET if arm in TENSOR_ARMS else 0
        tensor_equivalent_bytes = (
            DENSE_EQUIVALENT_FLOAT64_BYTES if arm in TENSOR_ARMS else 0
        )
        expected_budget = {
            "tensor_dense_scalars": tensor_scalars,
            "tensor_dense_equivalent_float64_bytes": tensor_equivalent_bytes,
            "candidate_content_budget_bytes": CANDIDATE_CONTENT_BUDGET_BYTES,
            "candidate_input_bytes": case.candidate_input_bytes,
            "query_input_bytes": case.query_bytes[variant],
        }
        if budget != expected_budget:
            raise SealedEvaluationError(f"{path}.budget is unequal or outside the frozen budget")

        raw_ranking = _array(row["ranking"], f"{path}.ranking")
        if any(type(candidate_id) is not str or not candidate_id for candidate_id in raw_ranking):
            raise SealedEvaluationError(f"{path}.ranking must contain candidate IDs")
        expected_length = min(MAX_RANK, len(case.candidate_ids))
        if len(raw_ranking) != expected_length:
            raise SealedEvaluationError(
                f"{path}.ranking must retain exactly top-{expected_length}"
            )
        if len(set(raw_ranking)) != len(raw_ranking):
            raise SealedEvaluationError(f"{path}.ranking contains duplicates")
        outside = set(raw_ranking) - set(case.candidate_ids)
        if outside:
            raise SealedEvaluationError(f"{path}.ranking contains candidates outside the pre-image")
        rankings[key] = tuple(raw_ranking)

    if actual_keys != expected_keys:
        raise SealedEvaluationError(
            "rankings must contain the exact arm x seed x (case_id, variant) Cartesian product in frozen order"
        )
    return digest, rankings


_ISOLATION_KEYS = frozenset(
    {
        "packet_id",
        "input_manifest_digest",
        "rankings_manifest_digest",
        "implementation_revision",
        "taskset_digest",
        "isolator_id",
        "preimage_only",
        "future_objects_absent",
        "gold_unavailable_during_ranking",
        "network_disabled",
        "writes_disabled",
        "automatic_promotions",
        "cases",
    }
)
_ISOLATION_CASE_KEYS = frozenset(
    {"case_id", "preimage_revision", "source_manifest_digest", "isolated_repository_digest"}
)


def _validate_isolation(
    manifest: object, inputs: _Input, rankings_digest: str
) -> str:
    payload, digest = _open_manifest(
        manifest, ISOLATION_RECEIPT_SCHEMA, "isolation_receipt"
    )
    body = _exact(payload, _ISOLATION_KEYS, "isolation_receipt.payload")
    if body["packet_id"] != PACKET_ID:
        raise SealedEvaluationError("isolation receipt packet_id is stale")
    if body["input_manifest_digest"] != inputs.digest:
        raise SealedEvaluationError("isolation receipt is not bound to sealed inputs")
    if body["rankings_manifest_digest"] != rankings_digest:
        raise SealedEvaluationError("isolation receipt is not bound to sealed rankings")
    if body["implementation_revision"] != inputs.implementation_revision:
        raise SealedEvaluationError("isolation receipt implementation revision differs")
    if body["taskset_digest"] != inputs.taskset_digest:
        raise SealedEvaluationError("isolation receipt taskset differs")
    if body["isolator_id"] != "s09-preimage-bare-clone/1":
        raise SealedEvaluationError("isolation receipt names an unapproved isolator")
    required_flags = (
        "preimage_only",
        "future_objects_absent",
        "gold_unavailable_during_ranking",
        "network_disabled",
        "writes_disabled",
    )
    if any(body[name] is not True for name in required_flags):
        raise SealedEvaluationError("isolation receipt does not close every leakage/effect boundary")
    if body["automatic_promotions"] != 0:
        raise SealedEvaluationError("isolation receipt must record automatic promotions: 0")
    rows = _array(body["cases"], "isolation.cases")
    if len(rows) != len(inputs.cases):
        raise SealedEvaluationError("isolation receipt must cover every base case")
    for index, (value, expected_case) in enumerate(zip(rows, inputs.cases)):
        path = f"isolation.cases[{index}]"
        row = _exact(value, _ISOLATION_CASE_KEYS, path)
        if row["case_id"] != expected_case.case_id:
            raise SealedEvaluationError(f"{path}.case_id is out of frozen order")
        if row["preimage_revision"] != expected_case.revision:
            raise SealedEvaluationError(f"{path}.preimage_revision differs from input")
        if row["source_manifest_digest"] != expected_case.source_manifest_digest:
            raise SealedEvaluationError(f"{path}.source_manifest_digest differs from input")
        _digest(row["isolated_repository_digest"], f"{path}.isolated_repository_digest")
    return digest


_GOLD_KEYS = frozenset(
    {"packet_id", "input_manifest_digest", "taskset_digest", "label_source_digest", "cases"}
)
_GOLD_CASE_KEYS = frozenset(
    {"case_id", "variant", "preimage_revision", "gold_candidate_ids"}
)


def _validate_gold(
    manifest: object, inputs: _Input
) -> tuple[str, dict[tuple[str, str], tuple[str, ...]]]:
    payload, digest = _open_manifest(manifest, GOLD_MANIFEST_SCHEMA, "gold_manifest")
    body = _exact(payload, _GOLD_KEYS, "gold_manifest.payload")
    if body["packet_id"] != PACKET_ID:
        raise SealedEvaluationError("gold packet_id is stale")
    if body["input_manifest_digest"] != inputs.digest:
        raise SealedEvaluationError("gold is not bound to the sealed input manifest")
    if body["taskset_digest"] != inputs.taskset_digest:
        raise SealedEvaluationError("gold taskset differs from input")
    if body["label_source_digest"] != inputs.taskset_digest:
        raise SealedEvaluationError("gold label source must be the frozen taskset")

    rows = _array(body["cases"], "gold.cases")
    expected = list(inputs.census)
    actual: list[tuple[str, str]] = []
    gold: dict[tuple[str, str], tuple[str, ...]] = {}
    case_by_id = {case.case_id: case for case in inputs.cases}
    for index, value in enumerate(rows):
        path = f"gold.cases[{index}]"
        row = _exact(value, _GOLD_CASE_KEYS, path)
        case_id = _text(row["case_id"], f"{path}.case_id")
        variant = _text(row["variant"], f"{path}.variant")
        key = (case_id, variant)
        actual.append(key)
        case = case_by_id.get(case_id)
        if case is None or variant not in QUERY_VARIANTS:
            raise SealedEvaluationError(f"{path} lies outside the frozen census")
        if row["preimage_revision"] != case.revision:
            raise SealedEvaluationError(f"{path}.preimage_revision differs from input")
        ids = _array(row["gold_candidate_ids"], f"{path}.gold_candidate_ids")
        if any(type(candidate_id) is not str or not candidate_id for candidate_id in ids):
            raise SealedEvaluationError(f"{path}.gold_candidate_ids must contain IDs")
        if len(set(ids)) != len(ids):
            raise SealedEvaluationError(f"{path}.gold_candidate_ids contains duplicates")
        if set(ids) - set(case.candidate_ids):
            raise SealedEvaluationError(f"{path}.gold_candidate_ids lies outside candidates")
        gold[key] = tuple(ids)
    if actual != expected:
        raise SealedEvaluationError("gold must contain the exact (case_id, variant) census")
    for case in inputs.cases:
        if gold[(case.case_id, "raw")] != gold[(case.case_id, "scrubbed")]:
            raise SealedEvaluationError("raw and scrubbed variants must share evaluator gold")
    return digest, gold


def _metrics(ranking: Sequence[str], gold: Sequence[str]) -> dict[str, float]:
    return {
        "reciprocal_rank": reciprocal_rank(ranking, gold),
        "recall_at_1": recall_at_k(ranking, gold, 1),
        "recall_at_5": recall_at_k(ranking, gold, 5),
        "recall_at_10": recall_at_k(ranking, gold, 10),
        "recall_at_20": recall_at_k(ranking, gold, 20),
        "first_hit_coverage": first_hit_coverage(ranking, gold),
    }


def _case_token(case_id: str, variant: str) -> str:
    return case_id + "::" + variant


def _comparison(
    mean_scores: Mapping[str, Mapping[tuple[str, str], float]],
    right_arm: str,
    variant: str,
) -> dict[str, object]:
    pairs = list(next(iter(mean_scores.values())))
    if variant == "all":
        # Raw and scrubbed are repeated views of one underlying task, not two
        # independent samples.  Average variants within each case first, then
        # let the paired bootstrap resample base cases.
        case_ids = sorted({case_id for case_id, _ in pairs})
        left = {
            case_id: math.fsum(
                mean_scores[PRIMARY_ARM][(case_id, item)] for item in QUERY_VARIANTS
            )
            / len(QUERY_VARIANTS)
            for case_id in case_ids
        }
        right = {
            case_id: math.fsum(
                mean_scores[right_arm][(case_id, item)] for item in QUERY_VARIANTS
            )
            / len(QUERY_VARIANTS)
            for case_id in case_ids
        }
    else:
        selected = [pair for pair in pairs if pair[1] == variant]
        left = {_case_token(*pair): mean_scores[PRIMARY_ARM][pair] for pair in selected}
        right = {_case_token(*pair): mean_scores[right_arm][pair] for pair in selected}
    interval = paired_bootstrap_difference(left, right)
    return {
        "left_arm": PRIMARY_ARM,
        "right_arm": right_arm,
        "variant": variant,
        "metric": "reciprocal_rank",
        **interval.as_dict(),
        # Hash-addressed manifests have no authenticity/isolation trust anchor.
        # The interval remains descriptive, but this module can never claim
        # superiority from it.
        "superiority_claim": False,
    }


def _claimed_digest(value: object) -> str | None:
    if type(value) is dict:
        candidate = value.get("digest")
        if type(candidate) is str and _SHA256.fullmatch(candidate):
            return candidate
    return None


_METRIC_NAMES = (
    "reciprocal_rank",
    "recall_at_1",
    "recall_at_5",
    "recall_at_10",
    "recall_at_20",
    "first_hit_coverage",
)
_MEASUREMENT_KEYS = frozenset({"arm", "seed", "per_case"})
_MEASUREMENT_CASE_KEYS = frozenset({"case_id", "variant", *_METRIC_NAMES})
_COMPARISON_KEYS = frozenset(
    {
        "left_arm",
        "right_arm",
        "variant",
        "metric",
        "delta",
        "ci_low",
        "ci_high",
        "case_count",
        "resamples",
        "seed",
        "superiority_claim",
    }
)
_MANIFEST_DIGEST_KEYS = frozenset({"input", "rankings", "gold", "isolation"})
_BUDGET_REPORT_KEYS = frozenset(
    {
        "dense_scalar_budget",
        "dense_equivalent_float64_bytes",
        "candidate_content_budget_bytes",
        "max_file_bytes",
    }
)


_REPORT_BODY_KEYS = frozenset(
    {
        "schema",
        "packet_id",
        "spec_digest",
        "status",
        "eligibility",
        "conclusion",
        "automatic_promotions",
        "manifest_digests",
        "taskset_digest",
        "implementation_revision",
        "required_arms",
        "seeds",
        "case_census",
        "budgets",
        "measurements",
        "comparisons",
        "missing_decision_prerequisites",
        "failures",
    }
)
_REPORT_KEYS = _REPORT_BODY_KEYS | {"report_id"}


def _report_id(report: Mapping[str, Any]) -> str:
    body = {key: report[key] for key in _REPORT_BODY_KEYS}
    return _content_digest(body, domain=_SEALED_REPORT_ID_DOMAIN)


def _attach_report_id(report: dict[str, object]) -> dict[str, object]:
    if set(report) != _REPORT_BODY_KEYS:
        raise SealedEvaluationError("sealed report body is incomplete before sealing")
    report["report_id"] = _report_id(report)
    validate_sealed_report(report)
    return report


def _metric_number(value: object, path: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SealedEvaluationError(f"{path} must be numeric")
    try:
        converted = float(value)
    except (OverflowError, TypeError, ValueError) as exc:
        raise SealedEvaluationError(f"{path} cannot be represented as float64") from exc
    if not math.isfinite(converted) or not 0.0 <= converted <= 1.0:
        raise SealedEvaluationError(f"{path} must be finite in [0,1]")
    return converted


def _validate_metric_relations(row: Mapping[str, Any], path: str) -> dict[str, float]:
    """Check every relation derivable without reopening gold/rankings.

    Recall magnitudes depend on the gold-set cardinality, so standalone report
    validation cannot prove them.  :func:`validate_sealed_report_bundle`
    performs that stronger recomputation.  These relations still reject
    impossible detached rows and make the limitation explicit.
    """

    values = {
        metric: _metric_number(row[metric], f"{path}.{metric}")
        for metric in _METRIC_NAMES
    }
    reciprocal = values["reciprocal_rank"]
    rank = 0
    if reciprocal != 0.0:
        for candidate_rank in range(1, MAX_RANK + 1):
            if reciprocal == 1.0 / candidate_rank:
                rank = candidate_rank
                break
        if rank == 0:
            raise SealedEvaluationError(
                f"{path}.reciprocal_rank is not zero or 1/r for r <= {MAX_RANK}"
            )

    expected_coverage = 1.0 if rank else 0.0
    if values["first_hit_coverage"] != expected_coverage:
        raise SealedEvaluationError(
            f"{path}.first_hit_coverage disagrees with reciprocal_rank"
        )

    cutoffs = (1, 5, 10, 20)
    recalls = tuple(values[f"recall_at_{cutoff}"] for cutoff in cutoffs)
    if any(left > right for left, right in zip(recalls, recalls[1:])):
        raise SealedEvaluationError(f"{path} recall values are not monotone")
    for cutoff, recall in zip(cutoffs, recalls):
        expected_hit = bool(rank and rank <= cutoff)
        if (recall > 0.0) != expected_hit:
            raise SealedEvaluationError(
                f"{path}.recall_at_{cutoff} disagrees with reciprocal_rank"
            )
    return values


def validate_sealed_report(report: Mapping[str, Any]) -> None:
    """Validate evaluator output before canonical transport or persistence."""

    _ensure_json(report, "sealed_report")
    body = _exact(report, _REPORT_KEYS, "sealed_report")
    if body["schema"] != SEALED_REPORT_SCHEMA:
        raise SealedEvaluationError("sealed report schema is stale")
    if body["packet_id"] != PACKET_ID or body["spec_digest"] != SPEC_DIGEST:
        raise SealedEvaluationError("sealed report packet/spec identity is stale")
    if body["automatic_promotions"] != 0:
        raise SealedEvaluationError("sealed report may never authorize promotion")
    if body["required_arms"] != list(REQUIRED_ARMS) or body["seeds"] != list(FROZEN_SEEDS):
        raise SealedEvaluationError("sealed report census policy is stale")
    manifest_digests = _exact(
        body["manifest_digests"], _MANIFEST_DIGEST_KEYS, "sealed_report.manifest_digests"
    )
    for name, value in manifest_digests.items():
        if value is not None:
            _digest(value, f"sealed_report.manifest_digests.{name}")
    status = body["status"]
    conclusion = body["conclusion"]
    if status == "BLOCKED":
        if body["eligibility"] != "INELIGIBLE" or conclusion != NO_SCIENTIFIC_VERDICT:
            raise SealedEvaluationError("blocked report must carry no scientific verdict")
        if type(body["failures"]) is not list or not body["failures"]:
            raise SealedEvaluationError("blocked report must retain a failure")
        if (
            body["taskset_digest"] is not None
            or body["implementation_revision"] is not None
            or body["case_census"] != []
            or body["budgets"] is not None
            or body["measurements"] != []
            or body["comparisons"] != []
            or body["missing_decision_prerequisites"] != []
        ):
            raise SealedEvaluationError("blocked report must not retain scientific measurements")
    elif status == STRUCTURALLY_VALID_UNANCHORED:
        if (
            body["eligibility"] != STRUCTURALLY_VALID_UNANCHORED
            or conclusion != NO_SCIENTIFIC_VERDICT
        ):
            raise SealedEvaluationError(
                "unanchored structural report must carry NO_SCIENTIFIC_VERDICT"
            )
        if body["failures"] != []:
            raise SealedEvaluationError("structurally valid report cannot contain failures")
        if body["missing_decision_prerequisites"] != list(MISSING_DECISION_PREREQUISITES):
            raise SealedEvaluationError(
                "unanchored report must retain every missing decision prerequisite"
            )

        _digest(body["taskset_digest"], "sealed_report.taskset_digest")
        _revision(body["implementation_revision"], "sealed_report.implementation_revision")
        if any(value is None for value in manifest_digests.values()):
            raise SealedEvaluationError("structural report must bind every sealed manifest")

        raw_census = _array(body["case_census"], "sealed_report.case_census")
        census: list[tuple[str, str]] = []
        for index, value in enumerate(raw_census):
            row = _exact(
                value,
                frozenset({"case_id", "variant"}),
                f"sealed_report.case_census[{index}]",
            )
            census.append(
                (
                    _text(row["case_id"], f"sealed_report.case_census[{index}].case_id"),
                    _text(row["variant"], f"sealed_report.case_census[{index}].variant"),
                )
            )
        if any("::" in case_id for case_id, _ in census):
            raise SealedEvaluationError("sealed report case_id uses the reserved separator")
        if len(census) % len(QUERY_VARIANTS):
            raise SealedEvaluationError("sealed report census does not contain variant pairs")
        base_ids: list[str] = []
        for index in range(0, len(census), len(QUERY_VARIANTS)):
            pair = census[index : index + len(QUERY_VARIANTS)]
            if (
                tuple(item[1] for item in pair) != QUERY_VARIANTS
                or len({item[0] for item in pair}) != 1
            ):
                raise SealedEvaluationError("sealed report must pair raw and scrubbed per case")
            base_ids.append(pair[0][0])
        if base_ids != sorted(base_ids) or len(set(base_ids)) != len(base_ids):
            raise SealedEvaluationError("sealed report cases must be uniquely sorted")

        budgets = _exact(body["budgets"], _BUDGET_REPORT_KEYS, "sealed_report.budgets")
        if budgets != {
            "dense_scalar_budget": DENSE_SCALAR_BUDGET,
            "dense_equivalent_float64_bytes": DENSE_EQUIVALENT_FLOAT64_BYTES,
            "candidate_content_budget_bytes": CANDIDATE_CONTENT_BUDGET_BYTES,
            "max_file_bytes": MAX_FILE_BYTES,
        }:
            raise SealedEvaluationError("sealed report budgets differ from the frozen policy")

        measurements = _array(body["measurements"], "sealed_report.measurements")
        expected_runs = [(arm, seed) for arm in REQUIRED_ARMS for seed in FROZEN_SEEDS]
        actual_runs: list[tuple[str, int]] = []
        reciprocal: dict[tuple[str, int, str, str], float] = {}
        for index, value in enumerate(measurements):
            path = f"sealed_report.measurements[{index}]"
            row = _exact(value, _MEASUREMENT_KEYS, path)
            arm = _text(row["arm"], f"{path}.arm")
            seed = _frozen_seed(row["seed"], f"{path}.seed")
            actual_runs.append((arm, seed))
            per_case = _array(row["per_case"], f"{path}.per_case")
            seen_pairs: list[tuple[str, str]] = []
            for case_index, case_value in enumerate(per_case):
                case_path = f"{path}.per_case[{case_index}]"
                case_row = _exact(case_value, _MEASUREMENT_CASE_KEYS, case_path)
                pair = (
                    _text(case_row["case_id"], f"{case_path}.case_id"),
                    _text(case_row["variant"], f"{case_path}.variant"),
                )
                seen_pairs.append(pair)
                metric_values = _validate_metric_relations(case_row, case_path)
                reciprocal[(arm, seed, *pair)] = metric_values["reciprocal_rank"]
            if seen_pairs != census:
                raise SealedEvaluationError(f"{path}.per_case differs from the frozen census")
        if actual_runs != expected_runs:
            raise SealedEvaluationError("sealed report measurements lack the exact arm x seed grid")

        mean_scores: dict[str, dict[tuple[str, str], float]] = {}
        for arm in REQUIRED_ARMS:
            mean_scores[arm] = {
                pair: math.fsum(
                    reciprocal[(arm, seed, pair[0], pair[1])] for seed in FROZEN_SEEDS
                )
                / len(FROZEN_SEEDS)
                for pair in census
            }
        expected_comparisons = [
            _comparison(mean_scores, right_arm, variant)
            for right_arm in REQUIRED_ARMS
            if right_arm != PRIMARY_ARM
            for variant in ("all", *QUERY_VARIANTS)
        ]
        raw_comparisons = _array(body["comparisons"], "sealed_report.comparisons")
        for index, value in enumerate(raw_comparisons):
            _exact(value, _COMPARISON_KEYS, f"sealed_report.comparisons[{index}]")
        if raw_comparisons != expected_comparisons:
            raise SealedEvaluationError(
                "sealed report comparisons do not recompute from retained per-case measurements"
            )
    else:
        raise SealedEvaluationError(
            "sealed report status must be STRUCTURALLY_VALID_UNANCHORED or BLOCKED"
        )
    if type(body["comparisons"]) is not list:
        raise SealedEvaluationError("sealed report comparisons must be an array")
    for index, comparison in enumerate(body["comparisons"]):
        if type(comparison) is not dict:
            raise SealedEvaluationError(f"sealed_report.comparisons[{index}] must be an object")
        claim = comparison.get("superiority_claim")
        low = comparison.get("ci_low")
        if type(claim) is not bool or isinstance(low, bool) or not isinstance(low, (int, float)):
            raise SealedEvaluationError(f"sealed_report.comparisons[{index}] is malformed")
        if claim:
            raise SealedEvaluationError(
                "unanchored descriptive reports can never claim superiority"
            )
    report_id = _digest(body["report_id"], "sealed_report.report_id")
    if report_id != _report_id(body):
        raise SealedEvaluationError("sealed_report.report_id does not address its body")


def _blocked_report(error: SealedEvaluationError, manifests: Sequence[object]) -> dict[str, object]:
    report: dict[str, object] = {
        "schema": SEALED_REPORT_SCHEMA,
        "packet_id": PACKET_ID,
        "spec_digest": SPEC_DIGEST,
        "status": "BLOCKED",
        "eligibility": "INELIGIBLE",
        "conclusion": NO_SCIENTIFIC_VERDICT,
        "automatic_promotions": 0,
        "manifest_digests": {
            "input": _claimed_digest(manifests[0]),
            "rankings": _claimed_digest(manifests[1]),
            "gold": _claimed_digest(manifests[2]),
            "isolation": _claimed_digest(manifests[3]),
        },
        "taskset_digest": None,
        "implementation_revision": None,
        "required_arms": list(REQUIRED_ARMS),
        "seeds": list(FROZEN_SEEDS),
        "case_census": [],
        "budgets": None,
        "measurements": [],
        "comparisons": [],
        "missing_decision_prerequisites": [],
        "failures": [{"category": "sealed_input_ineligible", "message": str(error)}],
    }
    return _attach_report_id(report)


def evaluate_sealed_rankings(
    input_manifest: Mapping[str, Any],
    rankings_manifest: Mapping[str, Any],
    gold_manifest: Mapping[str, Any],
    isolation_receipt: Mapping[str, Any],
) -> dict[str, object]:
    """Validate and describe external rankings without issuing a science verdict.

    The argument order deliberately keeps gold separate from rankings.  No
    object supplied here is invoked.  Invalid evidence returns a BLOCKED
    report.  Structurally complete evidence remains explicitly unanchored and
    therefore also carries ``NO_SCIENTIFIC_VERDICT``.
    """

    manifests: tuple[object, ...] = (
        input_manifest,
        rankings_manifest,
        gold_manifest,
        isolation_receipt,
    )
    try:
        inputs = _validate_input(input_manifest)
        rankings_digest, rankings = _validate_rankings(rankings_manifest, inputs)
        isolation_digest = _validate_isolation(isolation_receipt, inputs, rankings_digest)
        gold_digest, gold = _validate_gold(gold_manifest, inputs)
    except SealedEvaluationError as exc:
        return _blocked_report(exc, manifests)

    metric_grid: dict[tuple[str, int, str, str], dict[str, float]] = {}
    measurements: list[dict[str, object]] = []
    for arm in REQUIRED_ARMS:
        for seed in FROZEN_SEEDS:
            per_case: list[dict[str, object]] = []
            for case_id, variant in inputs.census:
                key = (arm, seed, case_id, variant)
                values = _metrics(rankings[key], gold[(case_id, variant)])
                metric_grid[key] = values
                per_case.append({"case_id": case_id, "variant": variant, **values})
            measurements.append({"arm": arm, "seed": seed, "per_case": per_case})

    mean_scores: dict[str, dict[tuple[str, str], float]] = {}
    for arm in REQUIRED_ARMS:
        mean_scores[arm] = {}
        for case_id, variant in inputs.census:
            mean_scores[arm][(case_id, variant)] = math.fsum(
                metric_grid[(arm, seed, case_id, variant)]["reciprocal_rank"]
                for seed in FROZEN_SEEDS
            ) / len(FROZEN_SEEDS)

    comparisons = [
        _comparison(mean_scores, right_arm, variant)
        for right_arm in REQUIRED_ARMS
        if right_arm != PRIMARY_ARM
        for variant in ("all", *QUERY_VARIANTS)
    ]

    report: dict[str, object] = {
        "schema": SEALED_REPORT_SCHEMA,
        "packet_id": PACKET_ID,
        "spec_digest": SPEC_DIGEST,
        "status": STRUCTURALLY_VALID_UNANCHORED,
        "eligibility": STRUCTURALLY_VALID_UNANCHORED,
        "conclusion": NO_SCIENTIFIC_VERDICT,
        "automatic_promotions": 0,
        "manifest_digests": {
            "input": inputs.digest,
            "rankings": rankings_digest,
            "gold": gold_digest,
            "isolation": isolation_digest,
        },
        "taskset_digest": inputs.taskset_digest,
        "implementation_revision": inputs.implementation_revision,
        "required_arms": list(REQUIRED_ARMS),
        "seeds": list(FROZEN_SEEDS),
        "case_census": [
            {"case_id": case_id, "variant": variant}
            for case_id, variant in inputs.census
        ],
        "budgets": {
            "dense_scalar_budget": DENSE_SCALAR_BUDGET,
            "dense_equivalent_float64_bytes": DENSE_EQUIVALENT_FLOAT64_BYTES,
            "candidate_content_budget_bytes": CANDIDATE_CONTENT_BUDGET_BYTES,
            "max_file_bytes": MAX_FILE_BYTES,
        },
        "measurements": measurements,
        "comparisons": comparisons,
        "missing_decision_prerequisites": list(MISSING_DECISION_PREREQUISITES),
        "failures": [],
    }
    return _attach_report_id(report)


def validate_sealed_report_bundle(
    report: Mapping[str, Any],
    input_manifest: Mapping[str, Any],
    rankings_manifest: Mapping[str, Any],
    gold_manifest: Mapping[str, Any],
    isolation_receipt: Mapping[str, Any],
) -> None:
    """Recompute and verify every report metric from its four bound manifests.

    A detached report can prove its own byte integrity but cannot derive recall
    magnitudes without gold and rankings.  This is the semantic verification
    boundary: the supplied report must byte-match a fresh evaluator result.
    """

    validate_sealed_report(report)
    expected = evaluate_sealed_rankings(
        input_manifest,
        rankings_manifest,
        gold_manifest,
        isolation_receipt,
    )
    if _canonical_json_bytes(report) != _canonical_json_bytes(expected):
        raise SealedEvaluationError(
            "sealed report does not match recomputation from its bound manifests"
        )


def sealed_report_from_bytes(raw: bytes | str) -> dict[str, object]:
    """Strictly decode and validate a self-addressed sealed report."""

    report = manifest_from_bytes(raw)
    validate_sealed_report(report)
    return report


def canonical_sealed_report_bytes(report: Mapping[str, Any]) -> bytes:
    """Return validated deterministic report bytes without a trailing newline."""

    validate_sealed_report(report)
    return _canonical_json_bytes(report)


def sealed_report_digest(report: Mapping[str, Any]) -> str:
    """Return the content address of validated sealed-evaluator output."""

    validate_sealed_report(report)
    return _content_digest(report, domain=SEALED_REPORT_SCHEMA)


__all__ = [
    "CANDIDATE_CONTENT_BUDGET_BYTES",
    "DENSE_SCALAR_BUDGET",
    "DENSE_EQUIVALENT_FLOAT64_BYTES",
    "GOLD_MANIFEST_SCHEMA",
    "INPUT_MANIFEST_SCHEMA",
    "ISOLATION_RECEIPT_SCHEMA",
    "MAX_CANDIDATES_PER_CASE",
    "MAX_FILE_BYTES",
    "MAX_RANK",
    "MISSING_DECISION_PREREQUISITES",
    "QUERY_VARIANTS",
    "RANKINGS_MANIFEST_SCHEMA",
    "REQUIRED_ARMS",
    "SEALED_REPORT_SCHEMA",
    "STRUCTURALLY_VALID_UNANCHORED",
    "SealedEvaluationError",
    "TENSOR_ARMS",
    "candidate_manifest_digest",
    "canonical_sealed_report_bytes",
    "evaluate_sealed_rankings",
    "manifest_from_bytes",
    "seal_manifest",
    "sealed_report_digest",
    "sealed_report_from_bytes",
    "source_manifest_digest",
    "validate_sealed_report",
    "validate_sealed_report_bundle",
]
