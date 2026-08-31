"""Canonical Gate-0 contracts owned by :mod:`daedalus.kernel.contracts`.

These records give the event spine, runtime adapters, and artifact store one
strict wire language. They deliberately do not schedule work, persist another
ledger, enforce effects, verify evidence, or apply promotion decisions.
"""

from __future__ import annotations

import math
import re
from dataclasses import MISSING, asdict, dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, ClassVar, Mapping, Sequence
from urllib.parse import urlsplit

from daedalus.kernel.policy.limits import ExecutionLimitPolicy
from daedalus.spine.envelope import canonical_json, canonical_sha


KERNEL_CONTRACT_VERSION = "1.0.0"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_ARTIFACT_LOCATOR_RE = re.compile(r"^artifact-locator:sha256:([0-9a-f]{64})$")

RUNTIME_CONFORMANCE_CHECKS = frozenset(
    {
        "start",
        "stream",
        "tool-events",
        "structured-output",
        "timeout",
        "cancellation",
        "workspace-isolation",
        "cost",
    }
)


def _non_empty(value: Any, name: str, *, max_length: int = 4000) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    text = value
    if not text.strip():
        raise ValueError(f"{name} must be non-empty")
    if len(text) > max_length:
        raise ValueError(f"{name} must be no longer than {max_length} characters")
    return text


def _identifier(value: Any, name: str) -> str:
    text = _non_empty(value, name, max_length=200)
    if not _ID_RE.fullmatch(text):
        raise ValueError(
            f"{name} must start with an alphanumeric character and contain only "
            "letters, digits, '.', '_', ':', '/', or '-'"
        )
    return text


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    text = value
    if not _SHA256_RE.fullmatch(text):
        raise ValueError(f"{name} must be a lowercase 64-character sha256 digest")
    return text


def _revision(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    text = value
    if not _REVISION_RE.fullmatch(text):
        raise ValueError(
            f"{name} must be an exact lowercase 40- or 64-character source revision"
        )
    return text


def _artifact_locator(value: Any, name: str) -> str:
    text = _non_empty(value, name, max_length=1000)
    if not _ARTIFACT_LOCATOR_RE.fullmatch(text):
        raise ValueError(
            f"{name} must be a content-addressed artifact-locator:sha256 URI"
        )
    return text


def _locator_sha256(locator: str) -> str:
    match = _ARTIFACT_LOCATOR_RE.fullmatch(locator)
    if match is None:  # callers validate first; retain a fail-closed assertion
        raise ValueError("invalid artifact locator")
    return match.group(1)


def _egress_endpoint(value: Any, name: str) -> str:
    text = _non_empty(value, name, max_length=1000)
    if "*" in text:
        raise ValueError(f"{name} must not contain a wildcard")
    parsed = urlsplit(text)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"{name} must be an explicit http(s) endpoint")
    if parsed.username or parsed.password:
        raise ValueError(f"{name} must not embed credentials")
    return text.rstrip("/")


def _utc_timestamp(value: Any, name: str) -> str:
    text = _non_empty(value, name, max_length=64)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _repo_path(value: Any, name: str) -> str:
    raw = _non_empty(value, name, max_length=500).replace("\\", "/")
    if "\x00" in raw:
        raise ValueError(f"{name} contains a NUL byte")
    path = PurePosixPath(raw)
    if path.is_absolute() or any(part == ".." for part in path.parts):
        raise ValueError(f"{name} must stay inside the declared workspace")
    if path.parts and ":" in path.parts[0]:
        raise ValueError(f"{name} must be repository-relative, not drive-qualified")
    normalized = path.as_posix()
    if normalized in {"", "."}:
        return "."
    return normalized


def _sorted_strings(
    values: Sequence[Any],
    name: str,
    *,
    identifiers: bool = False,
    paths: bool = False,
    digests: bool = False,
) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{name} must be a sequence, not a string")
    converted: list[str] = []
    for index, value in enumerate(values):
        item_name = f"{name}[{index}]"
        if identifiers:
            converted.append(_identifier(value, item_name))
        elif paths:
            converted.append(_repo_path(value, item_name))
        elif digests:
            converted.append(_sha256(value, item_name))
        else:
            converted.append(_non_empty(value, item_name, max_length=1000))
    if len(set(converted)) != len(converted):
        raise ValueError(f"{name} must not contain duplicates")
    return tuple(sorted(converted))


def _freeze_json(value: Any, name: str = "value") -> Any:
    """Take an immutable JSON snapshot.

    Contract digests must not change because a caller mutates a dictionary
    after construction. Mapping proxies and tuples make that property
    structural rather than a convention.
    """

    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ValueError(f"{name} contains a non-string object key")
            frozen[key] = _freeze_json(nested, f"{name}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, f"{name}[]") for item in value)
    raise ValueError(f"{name} contains non-JSON value {type(value).__name__}")


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(value[key]) for key in sorted(value)}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: _json_value(getattr(value, f.name)) for f in fields(value)}
    return value


def _record_payload(cls: type, payload: Mapping[str, Any], label: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{label} must be an object")
    declared = {f.name: f for f in fields(cls)}
    unknown = set(payload) - set(declared)
    if unknown:
        raise ValueError(f"{label} contains unknown field(s): {sorted(unknown)}")
    missing = {
        name
        for name, f in declared.items()
        if f.init and f.default is MISSING and f.default_factory is MISSING and name not in payload
    }
    if missing:
        raise ValueError(f"{label} is missing field(s): {sorted(missing)}")
    return dict(payload)


class CanonicalContract:
    """Mixin for the one deterministic wire representation of kernel records.

    This is a schema and digest boundary, not an effect boundary. Constructing
    a policy decision or receipt does not enforce, verify, sign, or promote
    anything.
    """

    CONTRACT_TYPE: ClassVar[str]
    CONTRACT_VERSION: ClassVar[str] = KERNEL_CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        body = {
            f.name: _json_value(getattr(self, f.name))
            for f in fields(self)
            if not (
                f.metadata.get("canonical_omit_if_none", False)
                and getattr(self, f.name) is None
            )
        }
        return {
            "contract_type": self.CONTRACT_TYPE,
            "contract_version": self.CONTRACT_VERSION,
            **body,
        }

    def to_json(self) -> str:
        return canonical_json(self.to_dict())

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def _contract_payload(cls, payload: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ValueError(f"{cls.CONTRACT_TYPE} must be an object")
        contract_type = payload.get("contract_type")
        version = payload.get("contract_version")
        if contract_type != cls.CONTRACT_TYPE:
            raise ValueError(
                f"contract_type must be {cls.CONTRACT_TYPE!r}, got {contract_type!r}"
            )
        if version != cls.CONTRACT_VERSION:
            raise ValueError(
                f"contract_version must be {cls.CONTRACT_VERSION!r}, got {version!r}"
            )
        body = dict(payload)
        body.pop("contract_type", None)
        body.pop("contract_version", None)
        return _record_payload(cls, body, cls.CONTRACT_TYPE)


@dataclass(frozen=True)
class ContractProvenance:
    """Origin and source binding shared by every canonical kernel contract."""

    origin: str
    source_revision: str
    created_at: str
    input_digests: tuple[str, ...] = ()
    trace_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "origin", _identifier(self.origin, "provenance.origin"))
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "provenance.source_revision"),
        )
        object.__setattr__(
            self, "created_at", _utc_timestamp(self.created_at, "provenance.created_at")
        )
        object.__setattr__(
            self,
            "input_digests",
            _sorted_strings(
                self.input_digests, "provenance.input_digests", digests=True
            ),
        )
        if self.trace_id is not None:
            object.__setattr__(
                self, "trace_id", _identifier(self.trace_id, "provenance.trace_id")
            )

    def to_dict(self) -> dict[str, Any]:
        return {f.name: _json_value(getattr(self, f.name)) for f in fields(self)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ContractProvenance":
        return cls(**_record_payload(cls, payload, "provenance"))


def _require_provenance_inputs(
    provenance: ContractProvenance,
    required: Sequence[str],
    label: str,
) -> None:
    missing = sorted(set(required) - set(provenance.input_digests))
    if missing:
        raise ValueError(
            f"{label} provenance does not bind referenced input digest(s): {missing}"
        )


def _snapshot_execution_limit_policy(
    policy: ExecutionLimitPolicy | None,
    fingerprint_sha256: str | None,
    provenance: ContractProvenance,
    label: str,
) -> tuple[ExecutionLimitPolicy | None, str | None]:
    """Validate and freeze an optional Revision-10 policy/evidence pair.

    ``None``/``None`` is the legacy wire shape and means bounded execution.
    Newly admitted work supplies both values.  Keeping the fields optional and
    omitting them from the canonical JSON when absent preserves the digest of
    records written before Revision 10; a half-present or unbound pair is
    refused rather than guessed.
    """

    if policy is None and fingerprint_sha256 is None:
        return None, None
    if policy is None or fingerprint_sha256 is None:
        raise ValueError(
            f"{label} must carry execution_limit_policy and "
            "execution_limit_policy_sha256 together"
        )
    if type(policy) is not ExecutionLimitPolicy:
        raise ValueError(
            f"{label}.execution_limit_policy must be an exact "
            "ExecutionLimitPolicy"
        )
    snapshot = ExecutionLimitPolicy.from_dict(policy.as_dict())
    fingerprint = _sha256(
        fingerprint_sha256, f"{label}.execution_limit_policy_sha256"
    )
    if fingerprint != snapshot.fingerprint_sha256:
        raise ValueError(
            f"{label}.execution_limit_policy_sha256 does not match the "
            "captured policy"
        )
    _require_provenance_inputs(provenance, (fingerprint,), label)
    return snapshot, fingerprint


@dataclass(frozen=True)
class ResourceBudget:
    """Frozen upper bounds. Money is integer micro-USD, never a float."""

    max_tokens: int | None = None
    max_cost_microusd: int | None = None
    max_wall_time_s: int | None = None
    max_attempts: int | None = None

    def __post_init__(self) -> None:
        for name in (
            "max_tokens",
            "max_cost_microusd",
            "max_wall_time_s",
            "max_attempts",
        ):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
                raise ValueError(f"budget.{name} must be a non-negative integer or null")

    @property
    def is_bounded(self) -> bool:
        return any(
            value is not None
            for value in (
                self.max_tokens,
                self.max_cost_microusd,
                self.max_wall_time_s,
                self.max_attempts,
            )
        )

    @property
    def has_execution_bound(self) -> bool:
        """Whether one attempt has a spend, token, or time ceiling."""

        return any(
            value is not None
            for value in (
                self.max_tokens,
                self.max_cost_microusd,
                self.max_wall_time_s,
            )
        )

    def effective(
        self,
        execution_limit_policy: ExecutionLimitPolicy | None = None,
    ) -> "ResourceBudget":
        """Return effective limits without erasing configured fallbacks.

        The receiver remains the frozen configured budget embedded in the
        contract.  ``None`` is the legacy bounded policy; explicit disabled
        axes become nullable effective values as required by Revision 10.
        """

        if execution_limit_policy is None:
            return self
        if type(execution_limit_policy) is not ExecutionLimitPolicy:
            raise ValueError(
                "execution_limit_policy must be an exact ExecutionLimitPolicy"
            )
        return ResourceBudget(
            max_tokens=(
                self.max_tokens
                if execution_limit_policy.enforces("tokens")
                else None
            ),
            max_cost_microusd=(
                self.max_cost_microusd
                if execution_limit_policy.enforces("mission_spend")
                else None
            ),
            max_wall_time_s=(
                self.max_wall_time_s
                if execution_limit_policy.enforces("wall_time")
                else None
            ),
            max_attempts=(
                self.max_attempts
                if execution_limit_policy.enforces("attempts")
                else None
            ),
        )

    def violations(
        self,
        usage: "ResourceUsage",
        *,
        execution_limit_policy: ExecutionLimitPolicy | None = None,
    ) -> tuple[str, ...]:
        effective = self.effective(execution_limit_policy)
        violations: list[str] = []
        # THE LARGER OF THE TWO INPUT NUMBERS, never their sum. They describe
        # the SAME prompt -- a server-reported count and a local pre-send
        # estimate of it -- so adding them would charge one prompt twice.
        # Taking the max rather than only the measured count keeps a token
        # ceiling from going blind on the local lane, which reports an estimate
        # and no measurement: a bound that ignores the only number anyone has
        # is not a bound. It stays conservative by construction, because the
        # estimator over-counts.
        used_tokens = max(usage.input_tokens, usage.est_input_tokens) + usage.output_tokens
        if effective.max_tokens is not None and used_tokens > effective.max_tokens:
            violations.append(
                f"tokens {used_tokens} exceed max_tokens {effective.max_tokens}"
            )
        if (
            effective.max_cost_microusd is not None
            and usage.cost_microusd > effective.max_cost_microusd
        ):
            violations.append(
                f"cost {usage.cost_microusd} exceeds "
                f"max_cost_microusd {effective.max_cost_microusd}"
            )
        if (
            effective.max_wall_time_s is not None
            and usage.wall_time_ms > effective.max_wall_time_s * 1000
        ):
            violations.append(
                f"wall time {usage.wall_time_ms}ms exceeds "
                f"max_wall_time_s {effective.max_wall_time_s}"
            )
        return tuple(violations)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ResourceBudget":
        return cls(**_record_payload(cls, payload, "budget"))


@dataclass(frozen=True)
class ResourceUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_microusd: int = 0
    wall_time_ms: int = 0
    #: A LOCALLY ESTIMATED input-token count, kept in its own field so it can
    #: never be read as a measurement. ``input_tokens`` means "the serving side
    #: counted this many"; an over-count produced by running cl100k over the
    #: prompt text before it was sent is a different quantity with different
    #: error, and writing it into ``input_tokens`` would make a contract assert
    #: a server-reported number nobody reported (Invariant 9). Appended at the
    #: END of the dataclass so no positional construction site re-binds, and
    #: defaulted to 0 so every existing record round-trips unchanged: a payload
    #: written before this field existed reads back with the default rather
    #: than failing ``_record_payload``.
    est_input_tokens: int = 0

    def __post_init__(self) -> None:
        for name in ("input_tokens", "output_tokens", "cost_microusd",
                     "wall_time_ms", "est_input_tokens"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"usage.{name} must be a non-negative integer")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ResourceUsage":
        return cls(**_record_payload(cls, payload, "usage"))


@dataclass(frozen=True)
class EffectScope:
    """Effective bounds granted by a policy decision, not model capabilities."""

    read_only: bool = True
    writable_paths: tuple[str, ...] = ()
    egress_endpoints: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    secret_refs: tuple[str, ...] = ()
    max_cost_microusd: int | None = None
    max_concurrency: int | None = 1
    timeout_s: int | None = None
    kill_switch_ref: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.read_only, bool):
            raise ValueError("effect_scope.read_only must be boolean")
        object.__setattr__(
            self,
            "writable_paths",
            _sorted_strings(self.writable_paths, "effect_scope.writable_paths", paths=True),
        )
        if isinstance(self.egress_endpoints, (str, bytes)):
            raise ValueError("effect_scope.egress_endpoints must be a sequence")
        endpoints = [
            _egress_endpoint(value, f"effect_scope.egress_endpoints[{index}]")
            for index, value in enumerate(self.egress_endpoints)
        ]
        if len(set(endpoints)) != len(endpoints):
            raise ValueError("effect_scope.egress_endpoints must not contain duplicates")
        object.__setattr__(self, "egress_endpoints", tuple(sorted(endpoints)))
        object.__setattr__(
            self, "tools", _sorted_strings(self.tools, "effect_scope.tools", identifiers=True)
        )
        object.__setattr__(
            self,
            "secret_refs",
            _sorted_strings(self.secret_refs, "effect_scope.secret_refs", identifiers=True),
        )
        if self.read_only and self.writable_paths:
            raise ValueError("read-only effect scope cannot grant writable paths")
        if not self.read_only and not self.writable_paths:
            raise ValueError(
                "write-capable effect scope must declare bounded writable paths"
            )
        if (
            self.max_cost_microusd is not None
            and (
                isinstance(self.max_cost_microusd, bool)
                or not isinstance(self.max_cost_microusd, int)
                or self.max_cost_microusd < 0
            )
        ):
            raise ValueError("effect_scope.max_cost_microusd must be non-negative or null")
        if self.max_concurrency is not None and (
            isinstance(self.max_concurrency, bool)
            or not isinstance(self.max_concurrency, int)
            or self.max_concurrency < 1
        ):
            raise ValueError(
                "effect_scope.max_concurrency must be a positive integer or null"
            )
        if self.timeout_s is not None and (
            isinstance(self.timeout_s, bool)
            or not isinstance(self.timeout_s, int)
            or self.timeout_s < 1
        ):
            raise ValueError("effect_scope.timeout_s must be a positive integer or null")
        if self.kill_switch_ref:
            object.__setattr__(
                self,
                "kill_switch_ref",
                _identifier(self.kill_switch_ref, "effect_scope.kill_switch_ref"),
            )

    @property
    def has_effects(self) -> bool:
        return bool(
            self.writable_paths
            or self.egress_endpoints
            or self.tools
            or self.secret_refs
            or not self.read_only
            # A resource-unbounded spend/process-only scope can otherwise have
            # no non-empty collection above. The kill-switch binding is the
            # invariant marker that this is still an effect grant; the default
            # deny scope carries no such binding.
            or self.kill_switch_ref
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EffectScope":
        return cls(**_record_payload(cls, payload, "effect_scope"))


@dataclass(frozen=True)
class RuntimeCapabilities:
    """What an adapter can express; this never grants mission authorization."""

    streaming: bool = False
    tool_events: bool = False
    structured_output: bool = False
    timeout: bool = False
    cancellation: bool = False
    workspace_isolation: bool = False
    cost_reporting: bool = False
    workspace_write: bool = False

    def __post_init__(self) -> None:
        for f in fields(self):
            if not isinstance(getattr(self, f.name), bool):
                raise ValueError(f"runtime capabilities.{f.name} must be boolean")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeCapabilities":
        return cls(**_record_payload(cls, payload, "runtime capabilities"))


@dataclass(frozen=True)
class MissionContract(CanonicalContract):
    CONTRACT_TYPE: ClassVar[str] = "daedalus.mission"

    mission_id: str
    objective: str
    source_revision: str
    work_item_ids: tuple[str, ...]
    success_criteria: tuple[str, ...]
    policy_sha256: str
    budget: ResourceBudget
    provenance: ContractProvenance
    execution_limit_policy: ExecutionLimitPolicy | None = field(
        default=None, metadata={"canonical_omit_if_none": True}
    )
    execution_limit_policy_sha256: str | None = field(
        default=None, metadata={"canonical_omit_if_none": True}
    )

    def __post_init__(self) -> None:
        object.__setattr__(self, "mission_id", _identifier(self.mission_id, "mission_id"))
        object.__setattr__(
            self, "objective", _non_empty(self.objective, "objective", max_length=8000)
        )
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "source_revision"),
        )
        object.__setattr__(
            self,
            "work_item_ids",
            _sorted_strings(self.work_item_ids, "work_item_ids", identifiers=True),
        )
        object.__setattr__(
            self,
            "success_criteria",
            _sorted_strings(self.success_criteria, "success_criteria"),
        )
        object.__setattr__(
            self, "policy_sha256", _sha256(self.policy_sha256, "policy_sha256")
        )
        if not self.work_item_ids:
            raise ValueError("mission must name at least one work item")
        if not self.success_criteria:
            raise ValueError("mission must name at least one success criterion")
        policy, policy_fingerprint = _snapshot_execution_limit_policy(
            self.execution_limit_policy,
            self.execution_limit_policy_sha256,
            self.provenance,
            "mission",
        )
        object.__setattr__(self, "execution_limit_policy", policy)
        object.__setattr__(
            self, "execution_limit_policy_sha256", policy_fingerprint
        )
        if not self.budget.effective(policy).has_execution_bound and (
            policy is None
            or any(
                policy.enforces(axis)
                for axis in ("tokens", "mission_spend", "wall_time")
            )
        ):
            raise ValueError(
                "mission budget must bound tokens, cost, or wall time; "
                "max_attempts alone does not bound one attempt"
            )
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("mission source_revision must match provenance.source_revision")
        _require_provenance_inputs(
            self.provenance, (self.policy_sha256,), "mission"
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "MissionContract":
        body = cls._contract_payload(payload)
        body["budget"] = ResourceBudget.from_dict(body["budget"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        if body.get("execution_limit_policy") is not None:
            body["execution_limit_policy"] = ExecutionLimitPolicy.from_dict(
                body["execution_limit_policy"]
            )
        return cls(**body)


def derive_work_item_id(
    mission_id: str,
    *,
    ordinal: int,
    identity: Sequence[Any] = (),
) -> str:
    """The deterministic id of ONE work item under ``mission_id``.

    THERE IS NO ``WorkItem`` CLASS AND THIS FUNCTION IS WHY. Plan §7's chain
    names WorkItems between the mission and its attempts, and
    :class:`MissionContract` already owns that layer as
    ``work_item_ids: tuple[str, ...]`` -- a work item IS an id under a mission.
    A second dataclass would have been a second contract for the thing the
    mission already names (Invariant 1). What was actually missing is the
    *derivation*, and it lives here, beside the validator that will reject a
    malformed result, so producer and validator cannot drift.

    ``ordinal`` must be unique within the mission and is what makes the id
    unique: two planned items with byte-identical text still get distinct ids.
    (A collision would not pass silently either -- ``work_item_ids`` rejects
    duplicates -- but a producer that relies on a downstream refusal for
    uniqueness is a producer that fails late.)

    ``identity`` is the content the id is BOUND to (objective, owner, declared
    paths -- whatever the caller considers the item's substance). It is hashed,
    not stored, so a receipt naming ``wi-002-<digest>`` proves which text was
    worked without the id becoming a copy of it (Invariant 7). A re-plan that
    changes the substance changes the id; that is the point, not a defect.

    The ordinal is zero-padded to three digits so the SORTED
    ``work_item_ids`` tuple reads back in plan order for the first thousand
    items. That is a readability nicety and nothing depends on it: ordering is
    owned by whatever batches the items (a wave index, a queue position), never
    by the mission, whose tuple is sorted by construction.
    """

    digest = work_item_identity_sha256(
        mission_id, ordinal=ordinal, identity=identity
    )
    return _identifier(f"wi-{ordinal:03d}-{digest[:12]}", "work_item_id")


def work_item_identity_sha256(
    mission_id: str,
    *,
    ordinal: int,
    identity: Sequence[Any] = (),
) -> str:
    """The FULL digest :func:`derive_work_item_id` truncates into an id.

    Extracted so a binder can freeze the substance it bound and later compare
    against it: the id carries only twelve hex characters of this, which is
    enough to make two plans collide-resistantly distinct but not enough for a
    mismatch report to name what actually moved. Pure, additive, and the single
    place the canonical identity body is spelled -- deriving the id and freezing
    its substance cannot drift into two different bodies.
    """

    mission = _identifier(mission_id, "mission_id")
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
        raise ValueError("work item ordinal must be a non-negative integer")
    if isinstance(identity, (str, bytes)):
        raise ValueError("work item identity must be a sequence, not a string")
    return canonical_sha(
        {
            "mission_id": mission,
            "ordinal": ordinal,
            "identity": [str(part) for part in identity],
        }
    )


@dataclass(frozen=True)
class AttemptContract(CanonicalContract):
    CONTRACT_TYPE: ClassVar[str] = "daedalus.attempt"

    attempt_id: str
    mission_id: str
    task_id: str
    instruction: str
    base_revision: str
    task_sha256: str
    runtime_manifest_sha256: str
    policy_decision_sha256: str
    budget: ResourceBudget
    provenance: ContractProvenance
    writable_paths: tuple[str, ...] = ()
    gate_names: tuple[str, ...] = ()
    campaign_id: str | None = None
    read_only: bool = False
    execution_limit_policy: ExecutionLimitPolicy | None = field(
        default=None, metadata={"canonical_omit_if_none": True}
    )
    execution_limit_policy_sha256: str | None = field(
        default=None, metadata={"canonical_omit_if_none": True}
    )

    def __post_init__(self) -> None:
        for name in ("attempt_id", "mission_id", "task_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        if self.campaign_id is not None:
            object.__setattr__(
                self, "campaign_id", _identifier(self.campaign_id, "campaign_id")
            )
        object.__setattr__(
            self, "instruction", _non_empty(self.instruction, "instruction", max_length=16000)
        )
        object.__setattr__(
            self,
            "base_revision",
            _revision(self.base_revision, "base_revision"),
        )
        for name in (
            "task_sha256",
            "runtime_manifest_sha256",
            "policy_decision_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self,
            "writable_paths",
            _sorted_strings(self.writable_paths, "writable_paths", paths=True),
        )
        object.__setattr__(
            self,
            "gate_names",
            _sorted_strings(self.gate_names, "gate_names", identifiers=True),
        )
        if not isinstance(self.read_only, bool):
            raise ValueError("read_only must be boolean")
        if self.read_only and self.writable_paths:
            raise ValueError("read-only attempt cannot declare writable paths")
        if not self.read_only and not self.writable_paths:
            raise ValueError("write-capable attempt must declare bounded writable paths")
        if not self.gate_names:
            raise ValueError("attempt must declare at least one evidence gate")
        policy, policy_fingerprint = _snapshot_execution_limit_policy(
            self.execution_limit_policy,
            self.execution_limit_policy_sha256,
            self.provenance,
            "attempt",
        )
        object.__setattr__(self, "execution_limit_policy", policy)
        object.__setattr__(
            self, "execution_limit_policy_sha256", policy_fingerprint
        )
        if not self.budget.effective(policy).has_execution_bound and (
            policy is None
            or any(
                policy.enforces(axis)
                for axis in ("tokens", "mission_spend", "wall_time")
            )
        ):
            raise ValueError(
                "attempt budget must bound tokens, cost, or wall time; "
                "max_attempts alone does not bound one attempt"
            )
        if self.provenance.source_revision != self.base_revision:
            raise ValueError("attempt base_revision must match provenance.source_revision")
        _require_provenance_inputs(
            self.provenance,
            (
                self.task_sha256,
                self.runtime_manifest_sha256,
                self.policy_decision_sha256,
            ),
            "attempt",
        )

    @classmethod
    def from_task_spec(
        cls,
        task: Any,
        *,
        attempt_id: str,
        mission_id: str,
        runtime_manifest_sha256: str,
        policy_decision_sha256: str,
        budget: ResourceBudget,
        provenance: ContractProvenance,
        campaign_id: str | None = None,
        read_only: bool = False,
        base_revision: str | None = None,
        execution_limit_policy: ExecutionLimitPolicy | None = None,
        execution_limit_policy_sha256: str | None = None,
    ) -> "AttemptContract":
        """Adapt the existing spine TaskSpec without inventing a second task.

        A legacy write task with an empty target scope is deliberately refused:
        it may still run through the old harness, but it cannot masquerade as a
        bounded Gate-0 contract.

        ``base_revision`` overrides ``task.base_revision`` and exists because
        the live spine RESOLVES the task's request (``None``, ``"HEAD"``, a
        branch name) into one exact revision at run time, and the resolved
        value -- not the request -- is what the candidate was actually built
        on. Taking the request here would bind the contract to a moving
        reference, which is the opposite of an atomic revision.
        """

        required = ("task_id", "instruction", "base_revision", "digest")
        missing = [name for name in required if not hasattr(task, name)]
        if missing:
            raise ValueError(f"task spec is missing adapter field(s): {missing}")
        if base_revision is None:
            base_revision = getattr(task, "base_revision")
        if not base_revision:
            raise ValueError("canonical attempt requires a frozen base_revision")
        paths = tuple(getattr(task, "target_paths", ()) or ())
        if read_only:
            paths = ()
        elif not paths:
            raise ValueError(
                "legacy TaskSpec has no target_paths; refusing an unbounded canonical attempt"
            )
        gate_argv = tuple(getattr(task, "gate_argv", ()) or ())
        if gate_argv:
            gate_names = ("command",)
        elif getattr(task, "fail_to_pass", ()) or getattr(task, "pass_to_pass", ()):
            gate_names = ("correctness",)
        else:
            gate_names = ("pytest",)
        return cls(
            attempt_id=attempt_id,
            mission_id=mission_id,
            task_id=task.task_id,
            instruction=task.instruction,
            base_revision=base_revision,
            task_sha256=task.digest,
            runtime_manifest_sha256=runtime_manifest_sha256,
            policy_decision_sha256=policy_decision_sha256,
            budget=budget,
            provenance=provenance,
            writable_paths=paths,
            gate_names=gate_names,
            campaign_id=campaign_id,
            read_only=read_only,
            execution_limit_policy=execution_limit_policy,
            execution_limit_policy_sha256=execution_limit_policy_sha256,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AttemptContract":
        body = cls._contract_payload(payload)
        body["budget"] = ResourceBudget.from_dict(body["budget"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        if body.get("execution_limit_policy") is not None:
            body["execution_limit_policy"] = ExecutionLimitPolicy.from_dict(
                body["execution_limit_policy"]
            )
        return cls(**body)


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    evaluator: str
    assurance: str
    verdict: str
    output_sha256: str
    evidence_locator: str
    collected_at: str
    provenance: ContractProvenance
    details: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evidence_id", _identifier(self.evidence_id, "evidence_id")
        )
        object.__setattr__(self, "evaluator", _identifier(self.evaluator, "evaluator"))
        if self.assurance not in {"deterministic", "independent", "unverified"}:
            raise ValueError(
                "evidence assurance must be deterministic, independent, or unverified"
            )
        if self.verdict not in {"passed", "failed", "error", "cancelled"}:
            raise ValueError("evidence verdict must be passed, failed, error, or cancelled")
        object.__setattr__(
            self, "output_sha256", _sha256(self.output_sha256, "output_sha256")
        )
        object.__setattr__(
            self,
            "evidence_locator",
            _artifact_locator(self.evidence_locator, "evidence_locator"),
        )
        object.__setattr__(
            self, "collected_at", _utc_timestamp(self.collected_at, "collected_at")
        )
        object.__setattr__(self, "details", _freeze_json(self.details, "evidence.details"))
        _require_provenance_inputs(
            self.provenance,
            (self.output_sha256, _locator_sha256(self.evidence_locator)),
            "evidence item",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvidenceItem":
        body = _record_payload(cls, payload, "evidence item")
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


def _attempt_evidence_projection(
    result: Any, attempt: "AttemptContract"
) -> dict[str, Any]:
    """The ONE reading of a legacy AttemptResult used to build evidence.

    Extracted from :meth:`EvidencePacket.from_attempt_result` so that a live
    producer can compute the input digests its provenance must bind WITHOUT
    re-deriving this projection in a second place and drifting from it. The
    duplicate would not fail loudly: it would fail as a provenance that binds
    the wrong gate output, which is exactly the class of silent lie this
    contract exists to prevent.

    It decides nothing. No verdict is promoted, no evaluation status is chosen
    and no artifact is persisted here; this is a pure read of an already
    finished attempt.
    """

    if str(getattr(result, "task_id", "")) != attempt.task_id:
        raise ValueError("attempt result task_id does not match attempt contract")
    result_base = getattr(result, "base_revision", None)
    if result_base and str(result_base) != attempt.base_revision:
        raise ValueError("attempt result base_revision does not match attempt contract")
    gate = getattr(result, "gates", None)
    artifact = getattr(result, "artifact", None)
    locator = getattr(result, "artifact_locator", None)
    persist_error = getattr(result, "persist_error", None)
    state = str(getattr(result, "state", ""))
    if gate is not None:
        if bool(getattr(gate, "cancelled", False)):
            verdict = "cancelled"
        elif bool(getattr(gate, "passed", False)):
            verdict = "passed"
        else:
            verdict = "failed"
        evidence_sha = str(getattr(gate, "output_sha256"))
        evaluator = str(getattr(gate, "name", "") or "gate")
        details = gate.summary()
    else:
        verdict = "cancelled" if state == "cancelled" else "error"
        details = {
            "state": state,
            "error": getattr(result, "error", None),
            "ledger_error": getattr(result, "ledger_error", None),
        }
        evidence_sha = canonical_sha(_json_value(details))
        evaluator = "attempt-state"
    candidate_sha = (
        str(getattr(artifact, "diff_sha256"))
        if artifact is not None and not artifact.is_empty
        else None
    )
    candidate_locator: str | None = None
    locator_matches = False
    if isinstance(locator, Mapping) and candidate_sha is not None:
        locator_uri = str(locator.get("locator_uri") or "")
        artifact_uri = str(locator.get("uri") or "")
        try:
            candidate_locator = _artifact_locator(
                locator_uri, "attempt result artifact_locator.locator_uri"
            )
        except ValueError:
            candidate_locator = None
        locator_matches = (
            candidate_locator is not None
            and artifact_uri == f"sha256:{candidate_sha}"
        )
    return {
        "state": state,
        "verdict": verdict,
        "evaluator": evaluator,
        "evidence_sha256": evidence_sha,
        "details": details,
        "candidate_sha256": candidate_sha,
        "candidate_locator": candidate_locator,
        "locator_matches": locator_matches,
        "persist_error": persist_error,
        "has_artifact": artifact is not None,
    }


@dataclass(frozen=True)
class EvidencePacket(CanonicalContract):
    CONTRACT_TYPE: ClassVar[str] = "daedalus.evidence"

    packet_id: str
    mission_id: str
    attempt_id: str
    source_revision: str
    attempt_contract_sha256: str
    subject_sha256: str
    evaluation_status: str
    items: tuple[EvidenceItem, ...]
    policy_decision_sha256: str
    usage: ResourceUsage
    provenance: ContractProvenance
    candidate_artifact_sha256: str | None = None
    candidate_artifact_locator: str | None = None
    execution_limit_policy: ExecutionLimitPolicy | None = field(
        default=None, metadata={"canonical_omit_if_none": True}
    )
    execution_limit_policy_sha256: str | None = field(
        default=None, metadata={"canonical_omit_if_none": True}
    )

    def __post_init__(self) -> None:
        for name in ("packet_id", "mission_id", "attempt_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "source_revision"),
        )
        object.__setattr__(
            self,
            "attempt_contract_sha256",
            _sha256(self.attempt_contract_sha256, "attempt_contract_sha256"),
        )
        object.__setattr__(
            self, "subject_sha256", _sha256(self.subject_sha256, "subject_sha256")
        )
        object.__setattr__(
            self,
            "policy_decision_sha256",
            _sha256(self.policy_decision_sha256, "policy_decision_sha256"),
        )
        if self.candidate_artifact_sha256 is not None:
            object.__setattr__(
                self,
                "candidate_artifact_sha256",
                _sha256(self.candidate_artifact_sha256, "candidate_artifact_sha256"),
            )
        if self.candidate_artifact_locator is not None:
            object.__setattr__(
                self,
                "candidate_artifact_locator",
                _artifact_locator(
                    self.candidate_artifact_locator, "candidate_artifact_locator"
                ),
            )
        if (
            self.candidate_artifact_locator is not None
            and self.candidate_artifact_sha256 is None
        ):
            raise ValueError(
                "candidate artifact locator requires its artifact digest"
            )
        if self.evaluation_status not in {"passed", "failed", "inconclusive"}:
            raise ValueError(
                "evaluation_status must be passed, failed, or inconclusive"
            )
        if not self.items:
            raise ValueError("evidence packet must retain at least one evidence item")
        item_ids = [item.evidence_id for item in self.items]
        if len(set(item_ids)) != len(item_ids):
            raise ValueError("evidence item ids must be unique")
        object.__setattr__(self, "items", tuple(sorted(self.items, key=lambda item: item.evidence_id)))
        verdicts = {item.verdict for item in self.items}
        if self.evaluation_status == "passed" and verdicts != {"passed"}:
            raise ValueError("passed packet cannot contain failed or inconclusive evidence")
        if self.evaluation_status == "failed" and not (
            {"failed", "error"} & verdicts
        ):
            raise ValueError(
                "failed packet requires an explicit failed/error evidence item"
            )
        if self.evaluation_status in {"passed", "failed"} and any(
            item.assurance == "unverified" for item in self.items
        ):
            raise ValueError(
                "conclusive packet cannot rely on unverified evidence"
            )
        if self.evaluation_status == "passed" and self.candidate_artifact_locator is None:
            raise ValueError(
                "passed packet requires a durable content-addressed candidate locator"
            )
        policy, policy_fingerprint = _snapshot_execution_limit_policy(
            self.execution_limit_policy,
            self.execution_limit_policy_sha256,
            self.provenance,
            "evidence packet",
        )
        object.__setattr__(self, "execution_limit_policy", policy)
        object.__setattr__(
            self, "execution_limit_policy_sha256", policy_fingerprint
        )
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("evidence source_revision must match provenance.source_revision")
        if any(
            item.provenance.source_revision != self.source_revision
            for item in self.items
        ):
            raise ValueError(
                "each evidence item must bind the packet source_revision"
            )
        required_inputs = [
            self.attempt_contract_sha256,
            self.subject_sha256,
            self.policy_decision_sha256,
            *(item.output_sha256 for item in self.items),
        ]
        if self.candidate_artifact_sha256 is not None:
            required_inputs.append(self.candidate_artifact_sha256)
        if self.candidate_artifact_locator is not None:
            required_inputs.append(
                _locator_sha256(str(self.candidate_artifact_locator))
            )
        _require_provenance_inputs(
            self.provenance, required_inputs, "evidence packet"
        )

    @classmethod
    def attempt_provenance(
        cls,
        result: Any,
        *,
        attempt: AttemptContract,
        evidence_locator: str,
        origin: str,
        created_at: str,
        trace_id: str | None = None,
        extra_digests: Sequence[str] = (),
    ) -> ContractProvenance:
        """Build the provenance :meth:`from_attempt_result` will demand.

        Every digest this packet and its single evidence item reference has to
        appear in ``provenance.input_digests`` or construction fails closed.
        Working that set out by hand at the call site is how a producer ends up
        binding a stale gate output, so the schema computes it from the same
        projection the packet itself uses.
        """

        projection = _attempt_evidence_projection(result, attempt)
        locator = _artifact_locator(evidence_locator, "evidence_locator")
        candidate_sha = projection["candidate_sha256"]
        digests: list[str] = [
            attempt.digest,
            attempt.policy_decision_sha256,
            str(projection["evidence_sha256"]),
            _locator_sha256(locator),
            # subject_sha256, exactly as from_attempt_result derives it.
            str(candidate_sha or attempt.digest),
        ]
        if candidate_sha is not None:
            digests.append(str(candidate_sha))
        if projection["locator_matches"] and projection["candidate_locator"]:
            digests.append(_locator_sha256(str(projection["candidate_locator"])))
        if attempt.execution_limit_policy_sha256 is not None:
            digests.append(attempt.execution_limit_policy_sha256)
        digests.extend(str(value) for value in extra_digests)
        return ContractProvenance(
            origin=origin,
            source_revision=attempt.base_revision,
            created_at=created_at,
            input_digests=tuple(sorted(set(digests))),
            trace_id=trace_id,
        )

    @classmethod
    def from_attempt_result(
        cls,
        result: Any,
        *,
        attempt: AttemptContract,
        packet_id: str,
        usage: ResourceUsage,
        provenance: ContractProvenance,
        evidence_locator: str,
        evaluator_assurance: str,
    ) -> "EvidencePacket":
        """Project an AttemptResult into evidence without turning green into promotion."""

        projection = _attempt_evidence_projection(result, attempt)
        artifact = getattr(result, "artifact", None)
        persist_error = projection["persist_error"]
        state = projection["state"]
        verdict = projection["verdict"]
        evidence_sha = projection["evidence_sha256"]
        evaluator = projection["evaluator"]
        details = projection["details"]
        candidate_sha = projection["candidate_sha256"]
        candidate_locator = projection["candidate_locator"]
        locator_matches = projection["locator_matches"]
        budget_violations = attempt.budget.violations(
            usage,
            execution_limit_policy=attempt.execution_limit_policy,
        )
        details = {
            **details,
            "candidate_locator_bound": locator_matches,
            "persist_error": persist_error,
            "budget_violations": list(budget_violations),
        }
        if attempt.execution_limit_policy is not None:
            details = {
                **details,
                "execution_limit_policy": attempt.execution_limit_policy.as_dict(),
                "execution_limit_policy_sha256": (
                    attempt.execution_limit_policy_sha256
                ),
            }
        conclusive = (
            evaluator_assurance in {"deterministic", "independent"}
            and not persist_error
            and locator_matches
            and not budget_violations
        )
        if (
            state == "clean"
            and verdict == "passed"
            and artifact is not None
            and conclusive
        ):
            evaluation_status = "passed"
        elif verdict in {"failed", "error"} and conclusive:
            evaluation_status = "failed"
        else:
            evaluation_status = "inconclusive"
        subject_sha = candidate_sha or attempt.digest
        item = EvidenceItem(
            evidence_id=f"{attempt.attempt_id}:gate",
            evaluator=evaluator,
            assurance=evaluator_assurance,
            verdict=verdict,
            output_sha256=evidence_sha,
            evidence_locator=evidence_locator,
            collected_at=str(getattr(result, "finished_ts")),
            provenance=provenance,
            details=details,
        )
        if evidence_sha not in provenance.input_digests:
            raise ValueError(
                "evidence provenance must include the retained gate output digest"
            )
        return cls(
            packet_id=packet_id,
            mission_id=attempt.mission_id,
            attempt_id=attempt.attempt_id,
            source_revision=attempt.base_revision,
            attempt_contract_sha256=attempt.digest,
            subject_sha256=subject_sha,
            evaluation_status=evaluation_status,
            items=(item,),
            policy_decision_sha256=attempt.policy_decision_sha256,
            usage=usage,
            provenance=provenance,
            candidate_artifact_sha256=candidate_sha,
            candidate_artifact_locator=candidate_locator if locator_matches else None,
            execution_limit_policy=attempt.execution_limit_policy,
            execution_limit_policy_sha256=attempt.execution_limit_policy_sha256,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "EvidencePacket":
        body = cls._contract_payload(payload)
        body["items"] = tuple(EvidenceItem.from_dict(item) for item in body["items"])
        body["usage"] = ResourceUsage.from_dict(body["usage"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        if body.get("execution_limit_policy") is not None:
            body["execution_limit_policy"] = ExecutionLimitPolicy.from_dict(
                body["execution_limit_policy"]
            )
        return cls(**body)


@dataclass(frozen=True)
class ExperimentSpec(CanonicalContract):
    """A pre-registered campaign definition, frozen before any trial runs."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.experiment-spec"

    campaign_id: str
    source_revision: str
    objective: str
    task_sha256s: tuple[str, ...]
    baseline_sha256s: tuple[str, ...]
    base_source_tree_sha256: str
    base_source_tree_locator: str
    seeds: tuple[int, ...]
    metrics: tuple[str, ...]
    operator_axis: str
    seed_derivation: str
    selection_policy: str
    attempts_per_seed: int
    metric_acceptance: Mapping[str, int | float]
    gate_timeout_s: int
    frozen_components: Mapping[str, str]
    writable_paths: tuple[str, ...]
    budget: ResourceBudget
    created_at: str
    expires_at: str
    provenance: ContractProvenance
    execution_limit_policy: ExecutionLimitPolicy | None = field(
        default=None, metadata={"canonical_omit_if_none": True}
    )
    execution_limit_policy_sha256: str | None = field(
        default=None, metadata={"canonical_omit_if_none": True}
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "campaign_id", _identifier(self.campaign_id, "campaign_id")
        )
        revision = _revision(self.source_revision, "source_revision")
        object.__setattr__(self, "source_revision", revision)
        object.__setattr__(
            self, "objective", _non_empty(self.objective, "objective", max_length=4000)
        )
        object.__setattr__(
            self,
            "task_sha256s",
            _sorted_strings(self.task_sha256s, "task_sha256s", digests=True),
        )
        object.__setattr__(
            self,
            "baseline_sha256s",
            _sorted_strings(self.baseline_sha256s, "baseline_sha256s", digests=True),
        )
        if not self.task_sha256s or not self.baseline_sha256s:
            raise ValueError("experiment must freeze tasks and at least one baseline")
        base_tree_sha = _sha256(
            self.base_source_tree_sha256, "base_source_tree_sha256"
        )
        base_tree_locator = _artifact_locator(
            self.base_source_tree_locator, "base_source_tree_locator"
        )
        if _locator_sha256(base_tree_locator) != base_tree_sha:
            raise ValueError("base source tree locator does not resolve to its digest")
        if base_tree_sha not in self.baseline_sha256s:
            raise ValueError("baseline_sha256s must include the base source tree")
        object.__setattr__(self, "base_source_tree_sha256", base_tree_sha)
        object.__setattr__(self, "base_source_tree_locator", base_tree_locator)
        if isinstance(self.seeds, (str, bytes)):
            raise ValueError("seeds must be a sequence of integers")
        seeds = tuple(self.seeds)
        if any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            for seed in seeds
        ):
            raise ValueError("seeds must be non-negative integers")
        if not seeds or len(set(seeds)) != len(seeds):
            raise ValueError("experiment seeds must be non-empty and unique")
        object.__setattr__(self, "seeds", tuple(sorted(seeds)))
        object.__setattr__(
            self, "metrics", _sorted_strings(self.metrics, "metrics", identifiers=True)
        )
        if not self.metrics:
            raise ValueError("experiment must freeze at least one metric")
        object.__setattr__(
            self, "operator_axis", _identifier(self.operator_axis, "operator_axis")
        )
        object.__setattr__(
            self,
            "seed_derivation",
            _non_empty(self.seed_derivation, "seed_derivation", max_length=1000),
        )
        object.__setattr__(
            self,
            "selection_policy",
            _identifier(self.selection_policy, "selection_policy"),
        )
        if (
            isinstance(self.attempts_per_seed, bool)
            or not isinstance(self.attempts_per_seed, int)
            or self.attempts_per_seed <= 0
        ):
            raise ValueError("attempts_per_seed must be a positive integer")
        if (
            isinstance(self.gate_timeout_s, bool)
            or not isinstance(self.gate_timeout_s, int)
            or self.gate_timeout_s <= 0
        ):
            raise ValueError("gate_timeout_s must be a positive integer")
        acceptance: dict[str, int | float] = {}
        for name, value in self.metric_acceptance.items():
            key = _identifier(name, "metric_acceptance key")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"metric acceptance {key} must be numeric")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"metric acceptance {key} must be finite")
            acceptance[key] = value
        if set(acceptance) != set(self.metrics):
            raise ValueError(
                "metric_acceptance keys must exactly match experiment metrics"
            )
        object.__setattr__(
            self,
            "metric_acceptance",
            MappingProxyType(dict(sorted(acceptance.items()))),
        )
        frozen: dict[str, str] = {}
        for name, digest in self.frozen_components.items():
            frozen[_identifier(name, "frozen_components key")] = _sha256(
                digest, f"frozen_components.{name}"
            )
        missing = sorted(
            {"compiler", "evaluator", "fixture", "generator", "model", "operator"}
            - set(frozen)
        )
        if missing:
            raise ValueError(f"experiment frozen_components is missing {missing}")
        object.__setattr__(
            self, "frozen_components", MappingProxyType(dict(sorted(frozen.items())))
        )
        object.__setattr__(
            self,
            "writable_paths",
            _sorted_strings(self.writable_paths, "writable_paths", paths=True),
        )
        if not self.writable_paths:
            raise ValueError("experiment must declare a bounded writable scope")
        if not isinstance(self.budget, ResourceBudget):
            raise ValueError("experiment budget must be ResourceBudget")
        policy, policy_fingerprint = _snapshot_execution_limit_policy(
            self.execution_limit_policy,
            self.execution_limit_policy_sha256,
            self.provenance,
            "experiment",
        )
        object.__setattr__(self, "execution_limit_policy", policy)
        object.__setattr__(
            self, "execution_limit_policy_sha256", policy_fingerprint
        )
        if not self.budget.effective(policy).has_execution_bound and (
            policy is None
            or any(
                policy.enforces(axis)
                for axis in ("tokens", "mission_spend", "wall_time")
            )
        ):
            raise ValueError(
                "experiment budget must bound tokens, cost, or wall time; "
                "max_attempts alone does not bound one attempt"
            )
        object.__setattr__(self, "created_at", _utc_timestamp(self.created_at, "created_at"))
        object.__setattr__(self, "expires_at", _utc_timestamp(self.expires_at, "expires_at"))
        if self.expires_at <= self.created_at:
            raise ValueError("experiment expires_at must be after created_at")
        if self.provenance.source_revision != revision:
            raise ValueError("experiment source_revision must match provenance")
        if self.provenance.created_at != self.created_at:
            raise ValueError("experiment created_at must match provenance.created_at")
        _require_provenance_inputs(
            self.provenance,
            (
                *self.task_sha256s,
                *self.baseline_sha256s,
                _locator_sha256(self.base_source_tree_locator),
                *self.frozen_components.values(),
            ),
            "experiment",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ExperimentSpec":
        body = cls._contract_payload(payload)
        body["budget"] = ResourceBudget.from_dict(body["budget"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        if body.get("execution_limit_policy") is not None:
            body["execution_limit_policy"] = ExecutionLimitPolicy.from_dict(
                body["execution_limit_policy"]
            )
        return cls(**body)


@dataclass(frozen=True)
class CampaignContract(CanonicalContract):
    CONTRACT_TYPE: ClassVar[str] = "daedalus.campaign"

    campaign_id: str
    source_revision: str
    experiment_spec_sha256: str
    evaluator_sha256: str
    task_sha256s: tuple[str, ...]
    baseline_sha256s: tuple[str, ...]
    seeds: tuple[int, ...]
    metrics: tuple[str, ...]
    operator_axis: str
    frozen_components: Mapping[str, str]
    writable_paths: tuple[str, ...]
    budget: ResourceBudget
    expires_at: str
    provenance: ContractProvenance
    execution_limit_policy: ExecutionLimitPolicy | None = field(
        default=None, metadata={"canonical_omit_if_none": True}
    )
    execution_limit_policy_sha256: str | None = field(
        default=None, metadata={"canonical_omit_if_none": True}
    )
    base_source_tree_sha256: str | None = field(
        default=None, metadata={"canonical_omit_if_none": True}
    )
    base_source_tree_locator: str | None = field(
        default=None, metadata={"canonical_omit_if_none": True}
    )
    seed_derivation: str | None = field(
        default=None, metadata={"canonical_omit_if_none": True}
    )
    selection_policy: str | None = field(
        default=None, metadata={"canonical_omit_if_none": True}
    )
    attempts_per_seed: int | None = field(
        default=None, metadata={"canonical_omit_if_none": True}
    )
    metric_acceptance: Mapping[str, int | float] | None = field(
        default=None, metadata={"canonical_omit_if_none": True}
    )
    gate_timeout_s: int | None = field(
        default=None, metadata={"canonical_omit_if_none": True}
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "campaign_id", _identifier(self.campaign_id, "campaign_id")
        )
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "source_revision"),
        )
        for name in ("experiment_spec_sha256", "evaluator_sha256"):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self,
            "task_sha256s",
            _sorted_strings(self.task_sha256s, "task_sha256s", digests=True),
        )
        object.__setattr__(
            self,
            "baseline_sha256s",
            _sorted_strings(self.baseline_sha256s, "baseline_sha256s", digests=True),
        )
        if not self.task_sha256s or not self.baseline_sha256s:
            raise ValueError("campaign must freeze tasks and at least one baseline")
        if isinstance(self.seeds, (str, bytes)):
            raise ValueError("seeds must be a sequence of integers")
        if any(isinstance(seed, bool) or not isinstance(seed, int) or seed < 0 for seed in self.seeds):
            raise ValueError("seeds must be non-negative integers")
        if len(set(self.seeds)) != len(self.seeds) or not self.seeds:
            raise ValueError("campaign seeds must be non-empty and unique")
        object.__setattr__(self, "seeds", tuple(sorted(self.seeds)))
        object.__setattr__(
            self, "metrics", _sorted_strings(self.metrics, "metrics", identifiers=True)
        )
        if not self.metrics:
            raise ValueError("campaign must freeze at least one metric")
        object.__setattr__(
            self, "operator_axis", _identifier(self.operator_axis, "operator_axis")
        )
        if (self.base_source_tree_sha256 is None) != (
            self.base_source_tree_locator is None
        ):
            raise ValueError(
                "campaign base source-tree digest and locator must appear together"
            )
        if self.base_source_tree_sha256 is not None:
            base_sha = _sha256(
                self.base_source_tree_sha256, "base_source_tree_sha256"
            )
            base_locator = _artifact_locator(
                self.base_source_tree_locator, "base_source_tree_locator"
            )
            if _locator_sha256(base_locator) != base_sha:
                raise ValueError(
                    "campaign base source-tree locator does not resolve to its digest"
                )
            if base_sha not in self.baseline_sha256s:
                raise ValueError(
                    "campaign baseline_sha256s must include the base source tree"
                )
            object.__setattr__(self, "base_source_tree_sha256", base_sha)
            object.__setattr__(self, "base_source_tree_locator", base_locator)
        if self.seed_derivation is not None:
            object.__setattr__(
                self,
                "seed_derivation",
                _non_empty(self.seed_derivation, "seed_derivation", max_length=1000),
            )
        if self.selection_policy is not None:
            object.__setattr__(
                self,
                "selection_policy",
                _identifier(self.selection_policy, "selection_policy"),
            )
        if self.attempts_per_seed is not None and (
            isinstance(self.attempts_per_seed, bool)
            or not isinstance(self.attempts_per_seed, int)
            or self.attempts_per_seed <= 0
        ):
            raise ValueError("campaign attempts_per_seed must be positive or null")
        if self.gate_timeout_s is not None and (
            isinstance(self.gate_timeout_s, bool)
            or not isinstance(self.gate_timeout_s, int)
            or self.gate_timeout_s <= 0
        ):
            raise ValueError("campaign gate_timeout_s must be positive or null")
        if self.metric_acceptance is not None:
            acceptance: dict[str, int | float] = {}
            for name, value in self.metric_acceptance.items():
                key = _identifier(name, "metric_acceptance key")
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    raise ValueError(f"metric acceptance {key} must be numeric")
                if isinstance(value, float) and not math.isfinite(value):
                    raise ValueError(f"metric acceptance {key} must be finite")
                acceptance[key] = value
            if set(acceptance) != set(self.metrics):
                raise ValueError(
                    "campaign metric_acceptance keys must exactly match metrics"
                )
            object.__setattr__(
                self,
                "metric_acceptance",
                MappingProxyType(dict(sorted(acceptance.items()))),
            )
        frozen: dict[str, str] = {}
        for name, digest in self.frozen_components.items():
            frozen[_identifier(name, "frozen_components key")] = _sha256(
                digest, f"frozen_components.{name}"
            )
        if not frozen:
            raise ValueError("campaign must pin its frozen components")
        required_components = {"generator", "model", "evaluator"}
        missing_components = sorted(required_components - set(frozen))
        if missing_components:
            raise ValueError(
                f"campaign frozen_components is missing {missing_components}"
            )
        if frozen["evaluator"] != self.evaluator_sha256:
            raise ValueError(
                "campaign evaluator_sha256 contradicts frozen_components.evaluator"
            )
        object.__setattr__(
            self, "frozen_components", MappingProxyType(dict(sorted(frozen.items())))
        )
        object.__setattr__(
            self,
            "writable_paths",
            _sorted_strings(self.writable_paths, "writable_paths", paths=True),
        )
        if not self.writable_paths:
            raise ValueError("campaign must declare a bounded writable scope")
        policy, policy_fingerprint = _snapshot_execution_limit_policy(
            self.execution_limit_policy,
            self.execution_limit_policy_sha256,
            self.provenance,
            "campaign",
        )
        object.__setattr__(self, "execution_limit_policy", policy)
        object.__setattr__(
            self, "execution_limit_policy_sha256", policy_fingerprint
        )
        if not self.budget.effective(policy).has_execution_bound and (
            policy is None
            or any(
                policy.enforces(axis)
                for axis in ("tokens", "mission_spend", "wall_time")
            )
        ):
            raise ValueError(
                "campaign budget must bound tokens, cost, or wall time; "
                "max_attempts alone does not bound one attempt"
            )
        object.__setattr__(self, "expires_at", _utc_timestamp(self.expires_at, "expires_at"))
        if self.expires_at <= self.provenance.created_at:
            raise ValueError("campaign expires_at must be after provenance.created_at")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("campaign source_revision must match provenance.source_revision")
        _require_provenance_inputs(
            self.provenance,
            (
                self.experiment_spec_sha256,
                self.evaluator_sha256,
                *self.task_sha256s,
                *self.baseline_sha256s,
                *self.frozen_components.values(),
                *(
                    (
                        self.base_source_tree_sha256,
                        _locator_sha256(self.base_source_tree_locator),
                    )
                    if self.base_source_tree_sha256 is not None
                    else ()
                ),
            ),
            "campaign",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CampaignContract":
        body = cls._contract_payload(payload)
        body["budget"] = ResourceBudget.from_dict(body["budget"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        if body.get("execution_limit_policy") is not None:
            body["execution_limit_policy"] = ExecutionLimitPolicy.from_dict(
                body["execution_limit_policy"]
            )
        return cls(**body)


@dataclass(frozen=True)
class CampaignTrialReceipt:
    """One retained seed outcome inside a canonical CampaignReceipt."""

    campaign_id: str
    seed: int
    replay_role: str
    stage: str
    status: str
    base_source_tree_sha256: str
    base_source_tree_locator: str
    mission_sha256: str | None
    mission_locator: str | None
    attempt_ids: tuple[str, ...]
    attempt_contract_sha256s: tuple[str, ...]
    attempt_contract_locators: tuple[str, ...]
    attempt_receipt_sha256s: tuple[str, ...]
    attempt_receipt_locators: tuple[str, ...]
    gate1_receipt_sha256: str | None
    gate1_receipt_locator: str | None
    candidate_tree_sha256: str | None
    candidate_tree_locator: str | None
    candidate_source_bundle_sha256: str | None
    candidate_snapshot_sha256: str | None
    candidate_snapshot_locator: str | None
    graph_delta_sha256: str | None
    evidence_packet_sha256: str | None
    evidence_packet_locator: str | None
    metrics: Mapping[str, int | float]
    usage: ResourceUsage
    negative_outcomes: tuple[str, ...]
    blockers: tuple[str, ...]
    started_at: str
    finished_at: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "campaign_id", _identifier(self.campaign_id, "campaign_id")
        )
        if isinstance(self.seed, bool) or not isinstance(self.seed, int) or self.seed < 0:
            raise ValueError("campaign trial seed must be a non-negative integer")
        if self.replay_role not in {"origin", "replay"}:
            raise ValueError("campaign trial replay_role must be origin or replay")
        if self.stage not in {
            "admitted",
            "mission",
            "attempts",
            "candidate",
            "evidence",
            "complete",
        }:
            raise ValueError("campaign trial stage is not recognized")
        if self.status not in {
            "passed", "failed", "cancelled", "inconclusive", "error"
        }:
            raise ValueError(
                "campaign trial status must be passed, failed, cancelled, "
                "inconclusive, or error"
            )
        base_sha = _sha256(
            self.base_source_tree_sha256, "base_source_tree_sha256"
        )
        base_locator = _artifact_locator(
            self.base_source_tree_locator, "base_source_tree_locator"
        )
        if _locator_sha256(base_locator) != base_sha:
            raise ValueError(
                "campaign trial base source-tree locator does not resolve to its digest"
            )
        object.__setattr__(self, "base_source_tree_sha256", base_sha)
        object.__setattr__(self, "base_source_tree_locator", base_locator)
        for digest_name, locator_name, label in (
            ("mission_sha256", "mission_locator", "mission"),
            ("gate1_receipt_sha256", "gate1_receipt_locator", "Gate-1 receipt"),
        ):
            digest = getattr(self, digest_name)
            locator = getattr(self, locator_name)
            if (digest is None) != (locator is None):
                raise ValueError(f"{label} digest and locator must appear together")
            if digest is not None:
                checked_digest = _sha256(digest, digest_name)
                checked_locator = _artifact_locator(locator, locator_name)
                if _locator_sha256(checked_locator) != checked_digest:
                    raise ValueError(f"{label} locator does not resolve to its digest")
                object.__setattr__(self, digest_name, checked_digest)
                object.__setattr__(self, locator_name, checked_locator)
        attempts = tuple(
            _identifier(value, f"attempt_ids[{index}]")
            for index, value in enumerate(self.attempt_ids)
        )
        if len(set(attempts)) != len(attempts):
            raise ValueError("campaign trial attempt_ids must be unique")
        object.__setattr__(self, "attempt_ids", attempts)
        for field_name, locator_field in (
            ("attempt_contract_sha256s", "attempt_contract_locators"),
            ("attempt_receipt_sha256s", "attempt_receipt_locators"),
        ):
            values = tuple(
                _sha256(value, f"{field_name}[{index}]")
                for index, value in enumerate(getattr(self, field_name))
            )
            if len(values) != len(attempts):
                raise ValueError(
                    f"{field_name} must have one digest per retained attempt"
                )
            locators = tuple(
                _artifact_locator(value, f"{locator_field}[{index}]")
                for index, value in enumerate(getattr(self, locator_field))
            )
            if len(locators) != len(values):
                raise ValueError(
                    f"{locator_field} must have one locator per retained attempt"
                )
            for digest, locator in zip(values, locators):
                if _locator_sha256(locator) != digest:
                    raise ValueError(
                        f"{locator_field} does not resolve to {field_name}"
                    )
            object.__setattr__(self, field_name, values)
            object.__setattr__(self, locator_field, locators)
        for digest_name, locator_name, label in (
            ("candidate_tree_sha256", "candidate_tree_locator", "candidate tree"),
            (
                "candidate_snapshot_sha256",
                "candidate_snapshot_locator",
                "candidate snapshot",
            ),
            ("evidence_packet_sha256", "evidence_packet_locator", "evidence packet"),
        ):
            digest = getattr(self, digest_name)
            locator = getattr(self, locator_name)
            if (digest is None) != (locator is None):
                raise ValueError(f"{label} digest and locator must appear together")
            if digest is not None:
                checked_digest = _sha256(digest, digest_name)
                checked_locator = _artifact_locator(locator, locator_name)
                if _locator_sha256(checked_locator) != checked_digest:
                    raise ValueError(f"{label} locator does not resolve to its digest")
                object.__setattr__(self, digest_name, checked_digest)
                object.__setattr__(self, locator_name, checked_locator)
        for name in ("candidate_source_bundle_sha256", "graph_delta_sha256"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, _sha256(value, name))
        metric_values: dict[str, int | float] = {}
        for name, value in self.metrics.items():
            key = _identifier(name, "trial metric name")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"trial metric {key} must be numeric")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"trial metric {key} must be finite")
            metric_values[key] = value
        if self.status == "passed" and not metric_values:
            raise ValueError("passed campaign trial must retain metrics")
        object.__setattr__(
            self, "metrics", MappingProxyType(dict(sorted(metric_values.items())))
        )
        if not isinstance(self.usage, ResourceUsage):
            raise ValueError("campaign trial usage must be ResourceUsage")
        object.__setattr__(
            self,
            "negative_outcomes",
            _sorted_strings(self.negative_outcomes, "negative_outcomes"),
        )
        object.__setattr__(self, "blockers", _sorted_strings(self.blockers, "blockers"))
        object.__setattr__(
            self, "started_at", _utc_timestamp(self.started_at, "started_at")
        )
        object.__setattr__(
            self, "finished_at", _utc_timestamp(self.finished_at, "finished_at")
        )
        if self.finished_at < self.started_at:
            raise ValueError("campaign trial finished_at cannot precede started_at")
        if self.status == "passed":
            if self.blockers:
                raise ValueError("passed campaign trial cannot retain blockers")
            if (
                self.stage != "complete"
                or self.mission_sha256 is None
                or not self.attempt_ids
                or self.gate1_receipt_sha256 is None
                or self.candidate_tree_sha256 is None
                or self.candidate_source_bundle_sha256 is None
                or self.candidate_snapshot_sha256 is None
                or self.graph_delta_sha256 is None
                or self.evidence_packet_sha256 is None
            ):
                raise ValueError(
                    "passed campaign trial requires its complete retained evidence chain"
                )
        elif not self.blockers:
            raise ValueError("non-passed campaign trial must retain at least one blocker")

    def to_dict(self) -> dict[str, Any]:
        return {f.name: _json_value(getattr(self, f.name)) for f in fields(self)}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CampaignTrialReceipt":
        body = _record_payload(cls, payload, "campaign trial receipt")
        body["usage"] = ResourceUsage.from_dict(body["usage"])
        return cls(**body)


@dataclass(frozen=True)
class CampaignReceipt(CanonicalContract):
    """Terminal campaign result. A nomination is never promotion authority."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.campaign-receipt"

    campaign_id: str
    source_revision: str
    campaign_contract_sha256: str
    campaign_contract_locator: str
    experiment_spec_sha256: str
    experiment_spec_locator: str
    metric_names: tuple[str, ...]
    trials: tuple[CampaignTrialReceipt, ...]
    execution_order: tuple[int, ...]
    outcome: str
    selected_seed: int | None
    candidate_tree_sha256: str | None
    candidate_tree_locator: str | None
    nomination_receipt_sha256: str | None
    nomination_receipt_locator: str | None
    usage: ResourceUsage
    overhead_usage: ResourceUsage
    negative_outcomes: tuple[str, ...]
    reproducibility_note: str
    blockers: tuple[str, ...]
    started_at: str
    finished_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "campaign_id", _identifier(self.campaign_id, "campaign_id")
        )
        revision = _revision(self.source_revision, "source_revision")
        object.__setattr__(self, "source_revision", revision)
        for digest_name, locator_name in (
            ("campaign_contract_sha256", "campaign_contract_locator"),
            ("experiment_spec_sha256", "experiment_spec_locator"),
        ):
            digest = _sha256(getattr(self, digest_name), digest_name)
            locator = _artifact_locator(getattr(self, locator_name), locator_name)
            if _locator_sha256(locator) != digest:
                raise ValueError(f"{locator_name} does not resolve to {digest_name}")
            object.__setattr__(self, digest_name, digest)
            object.__setattr__(self, locator_name, locator)
        metric_names = _sorted_strings(
            self.metric_names, "metric_names", identifiers=True
        )
        if not metric_names:
            raise ValueError("campaign receipt must name its metrics")
        object.__setattr__(self, "metric_names", metric_names)
        trials = tuple(self.trials)
        if not all(isinstance(item, CampaignTrialReceipt) for item in trials):
            raise ValueError("campaign receipt trials must be typed trial receipts")
        if len({item.seed for item in trials}) != len(trials):
            raise ValueError("campaign receipt trial seeds must be unique")
        for trial in trials:
            if trial.campaign_id != self.campaign_id:
                raise ValueError("campaign trial belongs to another campaign")
            if trial.status == "passed" and tuple(trial.metrics) != metric_names:
                raise ValueError("campaign trial metrics contradict metric_names")
        object.__setattr__(self, "trials", trials)
        execution_order = tuple(self.execution_order)
        if any(
            isinstance(seed, bool) or not isinstance(seed, int) or seed < 0
            for seed in execution_order
        ):
            raise ValueError("campaign execution_order must contain non-negative seeds")
        if execution_order != tuple(item.seed for item in self.trials):
            raise ValueError(
                "campaign execution_order must exactly name the retained trial order"
            )
        object.__setattr__(self, "execution_order", execution_order)
        if self.outcome not in {"nominated", "rejected", "failed", "cancelled"}:
            raise ValueError(
                "campaign outcome must be nominated, rejected, failed, or cancelled"
            )
        if self.selected_seed is not None and (
            isinstance(self.selected_seed, bool)
            or not isinstance(self.selected_seed, int)
            or self.selected_seed < 0
        ):
            raise ValueError("selected_seed must be a non-negative integer or null")
        for digest_name, locator_name, label in (
            ("candidate_tree_sha256", "candidate_tree_locator", "candidate tree"),
            (
                "nomination_receipt_sha256",
                "nomination_receipt_locator",
                "nomination receipt",
            ),
        ):
            digest = getattr(self, digest_name)
            locator = getattr(self, locator_name)
            if (digest is None) != (locator is None):
                raise ValueError(f"{label} digest and locator must appear together")
            if digest is not None:
                checked_digest = _sha256(digest, digest_name)
                checked_locator = _artifact_locator(locator, locator_name)
                if _locator_sha256(checked_locator) != checked_digest:
                    raise ValueError(f"{label} locator does not resolve to its digest")
                object.__setattr__(self, digest_name, checked_digest)
                object.__setattr__(self, locator_name, checked_locator)
        if not isinstance(self.usage, ResourceUsage):
            raise ValueError("campaign receipt usage must be ResourceUsage")
        if not isinstance(self.overhead_usage, ResourceUsage):
            raise ValueError("campaign receipt overhead_usage must be ResourceUsage")
        object.__setattr__(
            self,
            "negative_outcomes",
            _sorted_strings(self.negative_outcomes, "negative_outcomes"),
        )
        object.__setattr__(self, "blockers", _sorted_strings(self.blockers, "blockers"))
        object.__setattr__(
            self,
            "reproducibility_note",
            _non_empty(
                self.reproducibility_note,
                "reproducibility_note",
                max_length=2000,
            ),
        )
        object.__setattr__(self, "started_at", _utc_timestamp(self.started_at, "started_at"))
        object.__setattr__(self, "finished_at", _utc_timestamp(self.finished_at, "finished_at"))
        if self.finished_at < self.started_at:
            raise ValueError("campaign finished_at cannot precede started_at")
        if self.outcome == "nominated":
            if not trials:
                raise ValueError("nominated campaign requires retained trials")
            if self.blockers:
                raise ValueError("nominated campaign cannot retain blockers")
            if any(trial.status != "passed" for trial in trials):
                raise ValueError("nominated campaign requires every trial to pass")
            identities = {trial.candidate_tree_sha256 for trial in trials}
            if None in identities or len(identities) != 1:
                raise ValueError("nominated campaign requires one stable candidate identity")
            if self.candidate_tree_sha256 != next(iter(identities)):
                raise ValueError("campaign candidate contradicts its trial candidates")
            if self.nomination_receipt_sha256 is None:
                raise ValueError("nominated campaign requires a nomination receipt")
            if self.selected_seed not in {trial.seed for trial in trials}:
                raise ValueError("nominated campaign must select one retained seed")
        else:
            if self.selected_seed is not None:
                raise ValueError("non-nominated campaign cannot select a seed")
            if self.nomination_receipt_sha256 is not None:
                raise ValueError("non-nominated campaign cannot carry a nomination")
            if not self.blockers:
                raise ValueError("non-nominated campaign must retain blockers")
        if self.provenance.source_revision != revision:
            raise ValueError("campaign receipt revision must match provenance")
        if self.provenance.created_at != self.finished_at:
            raise ValueError("campaign receipt provenance must be created at finish")
        required = {
            self.campaign_contract_sha256,
            _locator_sha256(self.campaign_contract_locator),
            self.experiment_spec_sha256,
            _locator_sha256(self.experiment_spec_locator),
            *(
                (self.candidate_tree_sha256, _locator_sha256(self.candidate_tree_locator))
                if self.candidate_tree_sha256 is not None
                else ()
            ),
            *(
                (
                    self.nomination_receipt_sha256,
                    _locator_sha256(self.nomination_receipt_locator),
                )
                if self.nomination_receipt_sha256 is not None
                else ()
            ),
        }
        for trial in trials:
            required.update(
                {
                    trial.base_source_tree_sha256,
                    _locator_sha256(trial.base_source_tree_locator),
                    *(
                        (trial.mission_sha256, _locator_sha256(trial.mission_locator))
                        if trial.mission_sha256 is not None
                        else ()
                    ),
                    *trial.attempt_contract_sha256s,
                    *(
                        _locator_sha256(locator)
                        for locator in trial.attempt_contract_locators
                    ),
                    *trial.attempt_receipt_sha256s,
                    *(
                        _locator_sha256(locator)
                        for locator in trial.attempt_receipt_locators
                    ),
                    *(
                        (trial.candidate_source_bundle_sha256,)
                        if trial.candidate_source_bundle_sha256 is not None
                        else ()
                    ),
                    *(
                        (trial.graph_delta_sha256,)
                        if trial.graph_delta_sha256 is not None
                        else ()
                    ),
                    *(
                        (
                            trial.gate1_receipt_sha256,
                            _locator_sha256(trial.gate1_receipt_locator),
                        )
                        if trial.gate1_receipt_sha256 is not None
                        else ()
                    ),
                    *(
                        (
                            trial.candidate_tree_sha256,
                            _locator_sha256(trial.candidate_tree_locator),
                        )
                        if trial.candidate_tree_sha256 is not None
                        else ()
                    ),
                    *(
                        (
                            trial.candidate_snapshot_sha256,
                            _locator_sha256(trial.candidate_snapshot_locator),
                        )
                        if trial.candidate_snapshot_sha256 is not None
                        else ()
                    ),
                    *(
                        (
                            trial.evidence_packet_sha256,
                            _locator_sha256(trial.evidence_packet_locator),
                        )
                        if trial.evidence_packet_sha256 is not None
                        else ()
                    ),
                }
            )
        _require_provenance_inputs(self.provenance, tuple(required), "campaign receipt")

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CampaignReceipt":
        body = cls._contract_payload(payload)
        body["trials"] = tuple(
            CampaignTrialReceipt.from_dict(item) for item in body["trials"]
        )
        body["usage"] = ResourceUsage.from_dict(body["usage"])
        body["overhead_usage"] = ResourceUsage.from_dict(body["overhead_usage"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class PolicyDecision(CanonicalContract):
    CONTRACT_TYPE: ClassVar[str] = "daedalus.policy-decision"

    decision_id: str
    subject_id: str
    subject_sha256: str
    policy_version: str
    policy_sha256: str
    verdict: str
    reasons: tuple[str, ...]
    effect_scope: EffectScope
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("decision_id", "subject_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self, "subject_sha256", _sha256(self.subject_sha256, "subject_sha256")
        )
        object.__setattr__(
            self,
            "policy_version",
            _non_empty(self.policy_version, "policy_version", max_length=100),
        )
        object.__setattr__(
            self, "policy_sha256", _sha256(self.policy_sha256, "policy_sha256")
        )
        if self.verdict not in {"allow", "deny"}:
            raise ValueError("policy verdict must be allow or deny")
        object.__setattr__(self, "reasons", _sorted_strings(self.reasons, "reasons"))
        if not self.reasons:
            raise ValueError("policy decision must retain at least one reason")
        if self.verdict == "deny" and self.effect_scope.has_effects:
            raise ValueError("deny decision cannot carry effect grants")
        if self.verdict == "allow" and self.effect_scope.has_effects:
            if not self.effect_scope.kill_switch_ref:
                raise ValueError("effectful allow decision requires a kill_switch_ref")
            # Resource nulls are explicit unbounded-axis decisions captured by
            # the execution-limit policy. Authorization remains bounded by the
            # kill switch and the effect-specific scope checks in the lease
            # issuer; PolicyDecision must not reinterpret null as no authority.
        _require_provenance_inputs(
            self.provenance,
            (self.subject_sha256, self.policy_sha256),
            "policy decision",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PolicyDecision":
        body = cls._contract_payload(payload)
        body["effect_scope"] = EffectScope.from_dict(body["effect_scope"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class RuntimeManifest(CanonicalContract):
    CONTRACT_TYPE: ClassVar[str] = "daedalus.runtime-manifest"

    runtime_id: str
    runtime_version: str
    adapter_id: str
    adapter_version: str
    source_revision: str
    assurance: str
    capabilities: RuntimeCapabilities
    declared_tools: tuple[str, ...]
    egress_transports: tuple[str, ...]
    workspace_modes: tuple[str, ...]
    cost_model: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("runtime_id", "adapter_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        for name in ("runtime_version", "adapter_version", "cost_model"):
            object.__setattr__(
                self, name, _non_empty(getattr(self, name), name, max_length=200)
            )
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        if self.assurance != "declared":
            raise ValueError(
                "runtime manifest assurance is always declared; observations belong "
                "in RuntimeConformanceReceipt"
            )
        object.__setattr__(
            self,
            "declared_tools",
            _sorted_strings(self.declared_tools, "declared_tools", identifiers=True),
        )
        object.__setattr__(
            self,
            "egress_transports",
            _sorted_strings(self.egress_transports, "egress_transports", identifiers=True),
        )
        forbidden_egress = {"any", "unrestricted", "wildcard"}
        if forbidden_egress & set(self.egress_transports):
            raise ValueError("runtime egress transports must be explicitly bounded")
        object.__setattr__(
            self,
            "workspace_modes",
            _sorted_strings(self.workspace_modes, "workspace_modes", identifiers=True),
        )
        allowed_modes = {"read-only", "workspace-write", "isolated-worktree"}
        if not self.workspace_modes or set(self.workspace_modes) - allowed_modes:
            raise ValueError(
                "workspace_modes must contain supported read-only, workspace-write, "
                "or isolated-worktree modes"
            )
        if self.capabilities.workspace_write and not (
            {"workspace-write", "isolated-worktree"} & set(self.workspace_modes)
        ):
            raise ValueError("workspace-write capability requires a writable workspace mode")
        if not self.capabilities.workspace_write and (
            {"workspace-write", "isolated-worktree"} & set(self.workspace_modes)
        ):
            raise ValueError("read-only runtime cannot advertise a writable workspace mode")
        if self.capabilities.workspace_isolation != (
            "isolated-worktree" in self.workspace_modes
        ):
            raise ValueError(
                "workspace_isolation capability must match isolated-worktree mode"
            )
        if self.declared_tools and not self.capabilities.tool_events:
            raise ValueError(
                "a runtime with declared tools must expose provider-neutral tool events"
            )
        if self.capabilities.cost_reporting and self.cost_model == "unknown":
            raise ValueError("cost-reporting runtime must declare a cost_model")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("runtime source_revision must match provenance.source_revision")

    @classmethod
    def from_runtime_spec(
        cls,
        spec: Any,
        *,
        runtime_version: str,
        adapter_id: str,
        adapter_version: str,
        source_revision: str,
        provenance: ContractProvenance,
        capabilities: RuntimeCapabilities | None = None,
        declared_tools: Sequence[str] = (),
        egress_transports: Sequence[str] = (),
        cost_model: str = "unknown",
    ) -> "RuntimeManifest":
        """Conservative adapter for runtime_registry.RuntimeSpec declarations.

        Registry booleans are declarations, not conformance evidence. Unknown
        features remain false until a conformance receipt measures them.
        """

        if not hasattr(spec, "id") or not hasattr(spec, "can_write"):
            raise ValueError("runtime spec lacks id/can_write adapter fields")
        caps = capabilities or RuntimeCapabilities(
            workspace_write=bool(spec.can_write)
        )
        if caps.workspace_isolation:
            modes = ("isolated-worktree", "read-only")
        elif caps.workspace_write:
            modes = ("read-only", "workspace-write")
        else:
            modes = ("read-only",)
        return cls(
            runtime_id=str(spec.id),
            runtime_version=runtime_version,
            adapter_id=adapter_id,
            adapter_version=adapter_version,
            source_revision=source_revision,
            assurance="declared",
            capabilities=caps,
            declared_tools=tuple(declared_tools),
            egress_transports=tuple(egress_transports),
            workspace_modes=modes,
            cost_model=cost_model,
            provenance=provenance,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeManifest":
        body = cls._contract_payload(payload)
        body["capabilities"] = RuntimeCapabilities.from_dict(body["capabilities"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class AttemptReceipt(CanonicalContract):
    CONTRACT_TYPE: ClassVar[str] = "daedalus.attempt-receipt"

    receipt_id: str
    mission_id: str
    attempt_id: str
    source_revision: str
    attempt_contract_sha256: str
    runtime_manifest_sha256: str
    policy_decision_sha256: str
    evidence_packet_sha256: str
    outcome: str
    usage: ResourceUsage
    started_at: str
    finished_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("receipt_id", "mission_id", "attempt_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "source_revision"),
        )
        for name in (
            "attempt_contract_sha256",
            "runtime_manifest_sha256",
            "policy_decision_sha256",
            "evidence_packet_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        if self.outcome not in {
            "passed",
            "failed",
            "cancelled",
            "no-change",
            "error",
            # ADDITIVE. The legacy attempt state ``clean`` means only "the gate
            # returned green"; it does not mean the evidence is conclusive. A
            # green gate whose evaluator assurance is ``unverified`` -- pytest
            # run over the candidate's own worktree, where the candidate could
            # have edited the tests that judge it -- yields an INCONCLUSIVE
            # EvidencePacket by the packet's own rules. Without this outcome the
            # receipt for that attempt could not be built at all, and the live
            # path would have had to choose between minting no receipt and
            # claiming a "passed" the evidence refuses to support. Neither is
            # acceptable, so the honest verdict gets a name.
            "inconclusive",
        }:
            raise ValueError(
                "receipt outcome must be passed, failed, cancelled, no-change, "
                "inconclusive, or error"
            )
        object.__setattr__(self, "started_at", _utc_timestamp(self.started_at, "started_at"))
        object.__setattr__(
            self, "finished_at", _utc_timestamp(self.finished_at, "finished_at")
        )
        if self.finished_at < self.started_at:
            raise ValueError("receipt finished_at cannot precede started_at")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("receipt source_revision must match provenance.source_revision")
        _require_provenance_inputs(
            self.provenance,
            (
                self.attempt_contract_sha256,
                self.runtime_manifest_sha256,
                self.policy_decision_sha256,
                self.evidence_packet_sha256,
            ),
            "attempt receipt",
        )

    @classmethod
    def from_attempt_result(
        cls,
        result: Any,
        *,
        attempt: AttemptContract,
        evidence: EvidencePacket,
        receipt_id: str,
        usage: ResourceUsage,
        provenance: ContractProvenance,
    ) -> "AttemptReceipt":
        """Map legacy execution states into receipt outcomes explicitly.

        The mapping stops at execution/evaluation. It cannot nominate or
        promote a candidate; those are separate contracts.
        """

        state_to_outcome = {
            "clean": "passed",
            "gates_failed": "failed",
            "cancelled": "cancelled",
            "no_change": "no-change",
            "runner_failed": "error",
            "worktree_failed": "error",
            "storage_unavailable": "error",
        }
        state = str(getattr(result, "state", ""))
        try:
            outcome = state_to_outcome[state]
        except KeyError as exc:
            raise ValueError(f"unknown legacy attempt state {state!r}") from exc
        # THE EVIDENCE OUTRANKS THE LEGACY STATE. ``clean`` is a statement about
        # the gate's exit code; ``evaluation_status`` is a statement about
        # whether that verdict can be relied on. When the packet says
        # inconclusive -- unverified evaluator, unbound candidate locator, a
        # persist error, or a budget violation -- the receipt says inconclusive
        # too, rather than laundering a green exit code into a "passed" the
        # evidence boundary explicitly declined to certify.
        if outcome in {"passed", "failed"} and (
            evidence.evaluation_status == "inconclusive"
        ):
            outcome = "inconclusive"
        if str(getattr(result, "task_id", "")) != attempt.task_id:
            raise ValueError("attempt result task_id does not match attempt contract")
        if evidence.mission_id != attempt.mission_id or evidence.attempt_id != attempt.attempt_id:
            raise ValueError("evidence packet does not belong to the attempt contract")
        if evidence.attempt_contract_sha256 != attempt.digest:
            raise ValueError("evidence packet is bound to a different attempt contract")
        if evidence.policy_decision_sha256 != attempt.policy_decision_sha256:
            raise ValueError("evidence packet is bound to a different policy decision")
        if evidence.source_revision != attempt.base_revision:
            raise ValueError("evidence packet is bound to a different source revision")
        if usage != evidence.usage:
            raise ValueError("receipt usage must match the evidence packet usage")
        if outcome == "passed" and evidence.evaluation_status != "passed":
            raise ValueError("passed receipt requires a passed evidence packet")
        if outcome == "failed" and evidence.evaluation_status == "passed":
            raise ValueError("failed receipt contradicts a passed evidence packet")
        return cls(
            receipt_id=receipt_id,
            mission_id=attempt.mission_id,
            attempt_id=attempt.attempt_id,
            source_revision=attempt.base_revision,
            attempt_contract_sha256=attempt.digest,
            runtime_manifest_sha256=attempt.runtime_manifest_sha256,
            policy_decision_sha256=attempt.policy_decision_sha256,
            evidence_packet_sha256=evidence.digest,
            outcome=outcome,
            usage=usage,
            started_at=str(getattr(result, "started_ts")),
            finished_at=str(getattr(result, "finished_ts")),
            provenance=provenance,
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "AttemptReceipt":
        body = cls._contract_payload(payload)
        body["usage"] = ResourceUsage.from_dict(body["usage"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class NominationReceipt(CanonicalContract):
    """A candidate recommendation, deliberately not a promotion decision."""

    CONTRACT_TYPE: ClassVar[str] = "daedalus.nomination"

    nomination_id: str
    mission_id: str
    attempt_id: str
    source_revision: str
    candidate_artifact_sha256: str
    candidate_artifact_locator: str
    evidence_packet_sha256: str
    evidence_locator: str
    policy_decision_sha256: str
    nomination_status: str
    reasons: tuple[str, ...]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        for name in ("nomination_id", "mission_id", "attempt_id"):
            object.__setattr__(self, name, _identifier(getattr(self, name), name))
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "source_revision"),
        )
        for name in (
            "candidate_artifact_sha256",
            "evidence_packet_sha256",
            "policy_decision_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self,
            "candidate_artifact_locator",
            _artifact_locator(
                self.candidate_artifact_locator, "candidate_artifact_locator"
            ),
        )
        object.__setattr__(
            self,
            "evidence_locator",
            _artifact_locator(self.evidence_locator, "evidence_locator"),
        )
        if self.nomination_status not in {"nominated", "rejected"}:
            raise ValueError("nomination_status must be nominated or rejected")
        object.__setattr__(self, "reasons", _sorted_strings(self.reasons, "reasons"))
        if not self.reasons:
            raise ValueError("nomination receipt must retain at least one reason")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError(
                "nomination source_revision must match provenance.source_revision"
            )
        _require_provenance_inputs(
            self.provenance,
            (
                self.candidate_artifact_sha256,
                _locator_sha256(self.candidate_artifact_locator),
                self.evidence_packet_sha256,
                _locator_sha256(self.evidence_locator),
                self.policy_decision_sha256,
            ),
            "nomination",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "NominationReceipt":
        body = cls._contract_payload(payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class PromotionReceipt(CanonicalContract):
    """Claimed owner-controlled decision; it never applies the candidate.

    `promotion_status` is intentionally independent of evaluation and
    nomination. Even an approved receipt is only an authorization claim. This
    schema does not authenticate the owner; the guarded promotion boundary must
    resolve and authenticate the approval locator before any merge/deploy.
    """

    CONTRACT_TYPE: ClassVar[str] = "daedalus.promotion"

    promotion_id: str
    nomination_receipt_sha256: str
    candidate_artifact_sha256: str
    candidate_artifact_locator: str
    evidence_packet_sha256: str
    evidence_locator: str
    source_revision: str
    target_revision: str
    promotion_status: str
    owner_approval_ref: str | None
    approval_assurance: str
    reasons: tuple[str, ...]
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "promotion_id", _identifier(self.promotion_id, "promotion_id")
        )
        for name in (
            "nomination_receipt_sha256",
            "candidate_artifact_sha256",
            "evidence_packet_sha256",
        ):
            object.__setattr__(self, name, _sha256(getattr(self, name), name))
        object.__setattr__(
            self,
            "candidate_artifact_locator",
            _artifact_locator(
                self.candidate_artifact_locator, "candidate_artifact_locator"
            ),
        )
        object.__setattr__(
            self,
            "evidence_locator",
            _artifact_locator(self.evidence_locator, "evidence_locator"),
        )
        object.__setattr__(
            self, "source_revision", _revision(self.source_revision, "source_revision")
        )
        object.__setattr__(
            self,
            "target_revision",
            _non_empty(self.target_revision, "target_revision", max_length=200),
        )
        if self.promotion_status not in {"pending-owner", "approved", "rejected"}:
            raise ValueError(
                "promotion_status must be pending-owner, approved, or rejected"
            )
        if self.approval_assurance not in {"not-applicable", "authenticated"}:
            raise ValueError(
                "approval_assurance must be not-applicable or authenticated"
            )
        object.__setattr__(self, "reasons", _sorted_strings(self.reasons, "reasons"))
        if not self.reasons:
            raise ValueError("promotion receipt must retain at least one reason")
        if self.promotion_status == "approved":
            if self.owner_approval_ref is None:
                raise ValueError("approved promotion requires owner_approval_ref")
            object.__setattr__(
                self,
                "owner_approval_ref",
                _artifact_locator(self.owner_approval_ref, "owner_approval_ref"),
            )
            if self.approval_assurance != "authenticated":
                raise ValueError(
                    "approved promotion requires authenticated approval_assurance"
                )
        elif self.owner_approval_ref is not None:
            raise ValueError(
                "owner_approval_ref is valid only for an approved promotion"
            )
        elif self.approval_assurance != "not-applicable":
            raise ValueError(
                "non-approved promotion must use not-applicable approval_assurance"
            )
        if self.provenance.source_revision != self.source_revision:
            raise ValueError(
                "promotion source_revision must match provenance.source_revision"
            )
        _require_provenance_inputs(
            self.provenance,
            (
                self.nomination_receipt_sha256,
                self.candidate_artifact_sha256,
                _locator_sha256(self.candidate_artifact_locator),
                self.evidence_packet_sha256,
                _locator_sha256(self.evidence_locator),
                *(
                    (_locator_sha256(self.owner_approval_ref),)
                    if self.owner_approval_ref is not None
                    else ()
                ),
            ),
            "promotion",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "PromotionReceipt":
        body = cls._contract_payload(payload)
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class ConformanceCheck:
    name: str
    passed: bool
    evidence_sha256: str
    evidence_locator: str
    detail: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _identifier(self.name, "conformance check.name"))
        if not isinstance(self.passed, bool):
            raise ValueError("conformance check.passed must be boolean")
        object.__setattr__(
            self,
            "evidence_sha256",
            _sha256(self.evidence_sha256, "conformance check.evidence_sha256"),
        )
        object.__setattr__(
            self,
            "evidence_locator",
            _artifact_locator(
                self.evidence_locator, "conformance check.evidence_locator"
            ),
        )
        if self.detail:
            object.__setattr__(
                self,
                "detail",
                _non_empty(self.detail, "conformance check.detail", max_length=2000),
            )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ConformanceCheck":
        return cls(**_record_payload(cls, payload, "conformance check"))


@dataclass(frozen=True)
class RuntimeConformanceReceipt(CanonicalContract):
    CONTRACT_TYPE: ClassVar[str] = "daedalus.runtime-conformance"

    receipt_id: str
    runtime_manifest_sha256: str
    source_revision: str
    status: str
    checks: tuple[ConformanceCheck, ...]
    started_at: str
    finished_at: str
    usage: ResourceUsage
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "receipt_id", _identifier(self.receipt_id, "receipt_id"))
        object.__setattr__(
            self,
            "runtime_manifest_sha256",
            _sha256(self.runtime_manifest_sha256, "runtime_manifest_sha256"),
        )
        object.__setattr__(
            self,
            "source_revision",
            _revision(self.source_revision, "source_revision"),
        )
        if self.status not in {"passed", "failed"}:
            raise ValueError("conformance status must be passed or failed")
        if not self.checks:
            raise ValueError("conformance receipt must retain at least one check")
        check_names = [check.name for check in self.checks]
        if len(set(check_names)) != len(check_names):
            raise ValueError("conformance check names must be unique")
        object.__setattr__(self, "checks", tuple(sorted(self.checks, key=lambda check: check.name)))
        missing_checks = sorted(RUNTIME_CONFORMANCE_CHECKS - set(check_names))
        extra_checks = sorted(set(check_names) - RUNTIME_CONFORMANCE_CHECKS)
        if missing_checks or extra_checks:
            raise ValueError(
                "conformance checks must exactly cover the vendor-neutral fixture "
                f"matrix (missing={missing_checks}, extra={extra_checks})"
            )
        actual_status = "passed" if all(check.passed for check in self.checks) else "failed"
        if self.status != actual_status:
            raise ValueError(
                f"conformance status {self.status!r} contradicts retained check evidence"
            )
        object.__setattr__(self, "started_at", _utc_timestamp(self.started_at, "started_at"))
        object.__setattr__(
            self, "finished_at", _utc_timestamp(self.finished_at, "finished_at")
        )
        if self.finished_at < self.started_at:
            raise ValueError("conformance finished_at cannot precede started_at")
        if self.provenance.source_revision != self.source_revision:
            raise ValueError(
                "conformance source_revision must match provenance.source_revision"
            )
        _require_provenance_inputs(
            self.provenance,
            (
                self.runtime_manifest_sha256,
                *(check.evidence_sha256 for check in self.checks),
                *(_locator_sha256(check.evidence_locator) for check in self.checks),
            ),
            "runtime conformance",
        )

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeConformanceReceipt":
        body = cls._contract_payload(payload)
        body["checks"] = tuple(ConformanceCheck.from_dict(item) for item in body["checks"])
        body["usage"] = ResourceUsage.from_dict(body["usage"])
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


KERNEL_CONTRACT_TYPES: Mapping[str, type[CanonicalContract]] = MappingProxyType(
    {
        cls.CONTRACT_TYPE: cls
        for cls in (
            MissionContract,
            AttemptContract,
            EvidencePacket,
            ExperimentSpec,
            CampaignContract,
            CampaignReceipt,
            PolicyDecision,
            RuntimeManifest,
            AttemptReceipt,
            NominationReceipt,
            PromotionReceipt,
            RuntimeConformanceReceipt,
        )
    }
)


def parse_kernel_contract(payload: Mapping[str, Any]) -> CanonicalContract:
    """Strictly parse one canonical contract; unknown versions/types fail closed."""

    if not isinstance(payload, Mapping):
        raise ValueError("kernel contract must be an object")
    contract_type = payload.get("contract_type")
    cls = KERNEL_CONTRACT_TYPES.get(str(contract_type))
    if cls is None:
        raise ValueError(f"unknown kernel contract_type {contract_type!r}")
    return cls.from_dict(payload)
