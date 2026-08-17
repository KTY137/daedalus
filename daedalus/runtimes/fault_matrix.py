"""Canonical runtime-fault requirements, observations, and verification.

The catalog defines required Gate-0 questions. It does not claim that any fault
was executed. Observations are immutable, content-addressed records, but they
are not self-authenticating: a candidate-authored ``status='passed'`` record is
accepted only when its complete record digest appears in a trust set obtained by
an external exact-head collector.

A passing observation also records the actual terminal outcome. Verification
compares it with the catalog's expected outcome, so a trusted harness cannot
collapse "the test process exited zero" and "the system reached the required
state" into the same undifferentiated bit.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_sha

_SCHEMA = "daedalus-runtime-fault-matrix/1"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_AUTHORITIES = frozenset({"deterministic-fixture", "linux-host", "live-runtime"})
_STATUSES = frozenset({"passed", "failed", "blocked"})
_OUTCOMES = frozenset(
    {
        "refused-before-start",
        "failed",
        "cancelled",
        "completed-before-quarantine",
        "unknown-reconciled",
    }
)
_BOUNDARIES = frozenset(
    {
        "broker",
        "effect-ledger",
        "runtime-trust",
        "provider-process",
        "sandbox",
        "egress",
        "secrets",
    }
)


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase stable identifier")
    return value


def _non_empty(value: Any, name: str, *, maximum: int = 2000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    text = value.strip()
    if len(text) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
    return text


def _choice(value: Any, name: str, allowed: frozenset[str]) -> str:
    text = _non_empty(value, name, maximum=100)
    if text not in allowed:
        raise ValueError(f"{name} must be one of {sorted(allowed)}")
    return text


def _sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be lowercase SHA-256")
    return value


def _revision(value: Any, name: str = "source_revision") -> str:
    if not isinstance(value, str) or _REVISION_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a full lowercase Git/SHA revision")
    return value


def _timestamp(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a timezone-aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{name} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _sequence(value: Any, name: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be an array")
    return tuple(value)


def _strict_record(
    payload: Mapping[str, Any], expected: set[str], name: str
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{name} must be an object")
    keys = set(payload)
    missing = sorted(expected - keys)
    extra = sorted(keys - expected)
    if missing or extra:
        raise ValueError(f"{name} fields mismatch; missing={missing}, extra={extra}")
    return dict(payload)


def _record_dict(value: object) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in fields(value):
        nested = getattr(value, item.name)
        if isinstance(nested, tuple):
            result[item.name] = [
                row.to_dict() if hasattr(row, "to_dict") else row for row in nested
            ]
        elif isinstance(nested, ContractProvenance):
            result[item.name] = nested.to_dict()
        else:
            result[item.name] = nested
    return result


def _trusted_digests(values: Sequence[str]) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise ValueError("trusted observation digests must be an array")
    rows = tuple(
        sorted(
            _sha256(value, f"trusted_observation_digests[{index}]")
            for index, value in enumerate(values)
        )
    )
    if len(rows) != len(set(rows)):
        raise ValueError("trusted observation digests must be unique")
    return rows


@dataclass(frozen=True)
class RuntimeFaultScenario:
    scenario_id: str
    boundary: str
    authority: str
    injection: str
    expected_outcome: str
    invariant: str
    executor: str
    required_for_gate0: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "scenario_id", _identifier(self.scenario_id, "scenario_id"))
        object.__setattr__(self, "boundary", _choice(self.boundary, "boundary", _BOUNDARIES))
        object.__setattr__(self, "authority", _choice(self.authority, "authority", _AUTHORITIES))
        object.__setattr__(self, "injection", _non_empty(self.injection, "injection"))
        object.__setattr__(
            self,
            "expected_outcome",
            _choice(self.expected_outcome, "expected_outcome", _OUTCOMES),
        )
        object.__setattr__(self, "invariant", _non_empty(self.invariant, "invariant"))
        object.__setattr__(self, "executor", _non_empty(self.executor, "executor"))
        if not isinstance(self.required_for_gate0, bool):
            raise ValueError("required_for_gate0 must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return _record_dict(self)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeFaultScenario":
        return cls(
            **_strict_record(
                payload,
                {item.name for item in fields(cls)},
                "runtime fault scenario",
            )
        )


@dataclass(frozen=True)
class RuntimeFaultCatalog:
    catalog_id: str
    scenarios: tuple[RuntimeFaultScenario, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "catalog_id", _identifier(self.catalog_id, "catalog_id"))
        rows = tuple(sorted(self.scenarios, key=lambda row: row.scenario_id))
        if not rows:
            raise ValueError("runtime fault catalog must not be empty")
        ids = tuple(row.scenario_id for row in rows)
        if len(ids) != len(set(ids)):
            raise ValueError("runtime fault catalog contains duplicate scenario ids")
        object.__setattr__(self, "scenarios", rows)

    @property
    def scenario_map(self) -> Mapping[str, RuntimeFaultScenario]:
        return {row.scenario_id: row for row in self.scenarios}

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog_id": self.catalog_id,
            "scenarios": [row.to_dict() for row in self.scenarios],
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeFaultCatalog":
        body = _strict_record(payload, {"catalog_id", "scenarios"}, "runtime fault catalog")
        body["scenarios"] = tuple(
            RuntimeFaultScenario.from_dict(row)
            for row in _sequence(body["scenarios"], "scenarios")
        )
        return cls(**body)


@dataclass(frozen=True)
class RuntimeFaultObservation:
    observation_id: str
    scenario_id: str
    scenario_sha256: str
    source_revision: str
    authority: str
    status: str
    observed_outcome: str | None
    observed_at: str
    evidence_sha256: str
    detail_code: str | None
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "observation_id", _identifier(self.observation_id, "observation_id"))
        object.__setattr__(self, "scenario_id", _identifier(self.scenario_id, "scenario_id"))
        object.__setattr__(self, "scenario_sha256", _sha256(self.scenario_sha256, "scenario_sha256"))
        object.__setattr__(self, "source_revision", _revision(self.source_revision))
        object.__setattr__(self, "authority", _choice(self.authority, "authority", _AUTHORITIES))
        object.__setattr__(self, "status", _choice(self.status, "status", _STATUSES))
        if self.observed_outcome is not None:
            object.__setattr__(
                self,
                "observed_outcome",
                _choice(self.observed_outcome, "observed_outcome", _OUTCOMES),
            )
        if self.status == "passed":
            if self.observed_outcome is None:
                raise ValueError("passed observations require observed_outcome")
            if self.detail_code is not None:
                raise ValueError("passed observations must not carry detail_code")
        elif self.status == "blocked":
            if self.observed_outcome is not None:
                raise ValueError("blocked observations must not invent observed_outcome")
            object.__setattr__(self, "detail_code", _identifier(self.detail_code, "detail_code"))
        else:
            object.__setattr__(self, "detail_code", _identifier(self.detail_code, "detail_code"))
        object.__setattr__(self, "observed_at", _timestamp(self.observed_at, "observed_at"))
        object.__setattr__(self, "evidence_sha256", _sha256(self.evidence_sha256, "evidence_sha256"))
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("observation source revision contradicts provenance")
        if _timestamp(self.provenance.created_at, "provenance.created_at") != self.observed_at:
            raise ValueError("observation timestamp contradicts provenance")
        expected_inputs = tuple(sorted((self.scenario_sha256, self.evidence_sha256)))
        if tuple(self.provenance.input_digests) != expected_inputs:
            raise ValueError(
                "observation provenance must bind exact scenario and evidence digests"
            )

    def to_dict(self) -> dict[str, Any]:
        return _record_dict(self)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeFaultObservation":
        body = _strict_record(
            payload,
            {item.name for item in fields(cls)},
            "runtime fault observation",
        )
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class RuntimeFaultMatrix:
    matrix_id: str
    schema: str
    source_revision: str
    catalog_sha256: str
    observations: tuple[RuntimeFaultObservation, ...]
    generated_at: str
    provenance: ContractProvenance

    def __post_init__(self) -> None:
        object.__setattr__(self, "matrix_id", _identifier(self.matrix_id, "matrix_id"))
        if self.schema != _SCHEMA:
            raise ValueError(f"schema must be {_SCHEMA}")
        object.__setattr__(self, "source_revision", _revision(self.source_revision))
        object.__setattr__(self, "catalog_sha256", _sha256(self.catalog_sha256, "catalog_sha256"))
        rows = tuple(sorted(self.observations, key=lambda row: row.scenario_id))
        scenario_ids = tuple(row.scenario_id for row in rows)
        observation_ids = tuple(row.observation_id for row in rows)
        if len(scenario_ids) != len(set(scenario_ids)):
            raise ValueError("runtime fault matrix contains duplicate scenario observations")
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("runtime fault matrix contains duplicate observation ids")
        if any(row.source_revision != self.source_revision for row in rows):
            raise ValueError("matrix observations must share the exact source revision")
        object.__setattr__(self, "observations", rows)
        object.__setattr__(self, "generated_at", _timestamp(self.generated_at, "generated_at"))
        if self.provenance.source_revision != self.source_revision:
            raise ValueError("matrix source revision contradicts provenance")
        if _timestamp(self.provenance.created_at, "provenance.created_at") != self.generated_at:
            raise ValueError("matrix timestamp contradicts provenance")
        expected_inputs = tuple(sorted((self.catalog_sha256, *(row.digest for row in rows))))
        if tuple(self.provenance.input_digests) != expected_inputs:
            raise ValueError("matrix provenance must bind the exact catalog and observations")

    def to_dict(self) -> dict[str, Any]:
        return _record_dict(self)

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeFaultMatrix":
        body = _strict_record(
            payload,
            {item.name for item in fields(cls)},
            "runtime fault matrix",
        )
        body["observations"] = tuple(
            RuntimeFaultObservation.from_dict(row)
            for row in _sequence(body["observations"], "observations")
        )
        body["provenance"] = ContractProvenance.from_dict(body["provenance"])
        return cls(**body)


@dataclass(frozen=True)
class RuntimeFaultVerification:
    matrix_sha256: str
    catalog_sha256: str
    source_revision: str
    trusted_observation_sha256s: tuple[str, ...]
    blockers: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "matrix_sha256", _sha256(self.matrix_sha256, "matrix_sha256"))
        object.__setattr__(self, "catalog_sha256", _sha256(self.catalog_sha256, "catalog_sha256"))
        object.__setattr__(self, "source_revision", _revision(self.source_revision))
        object.__setattr__(
            self,
            "trusted_observation_sha256s",
            _trusted_digests(self.trusted_observation_sha256s),
        )
        blockers = tuple(sorted(_non_empty(row, "blocker") for row in self.blockers))
        if len(blockers) != len(set(blockers)):
            raise ValueError("verification blockers must be unique")
        object.__setattr__(self, "blockers", blockers)

    @property
    def closed(self) -> bool:
        return not self.blockers

    def to_dict(self) -> dict[str, Any]:
        return {
            "matrix_sha256": self.matrix_sha256,
            "catalog_sha256": self.catalog_sha256,
            "source_revision": self.source_revision,
            "trusted_observation_sha256s": list(self.trusted_observation_sha256s),
            "blockers": list(self.blockers),
            "closed": self.closed,
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def build_runtime_fault_matrix(
    *,
    matrix_id: str,
    source_revision: str,
    observations: Sequence[RuntimeFaultObservation],
    generated_at: str,
    catalog: RuntimeFaultCatalog,
    provenance_origin: str = "daedalus.runtimes.faults",
) -> RuntimeFaultMatrix:
    revision = _revision(source_revision)
    timestamp = _timestamp(generated_at, "generated_at")
    rows = tuple(observations)
    provenance = ContractProvenance(
        origin=provenance_origin,
        source_revision=revision,
        created_at=timestamp,
        input_digests=tuple(sorted((catalog.digest, *(row.digest for row in rows)))),
    )
    return RuntimeFaultMatrix(
        matrix_id=matrix_id,
        schema=_SCHEMA,
        source_revision=revision,
        catalog_sha256=catalog.digest,
        observations=rows,
        generated_at=timestamp,
        provenance=provenance,
    )


def verify_runtime_fault_matrix(
    matrix: RuntimeFaultMatrix,
    *,
    catalog: RuntimeFaultCatalog,
    expected_source_revision: str,
    trusted_observation_digests: Sequence[str],
) -> RuntimeFaultVerification:
    revision = _revision(expected_source_revision, "expected_source_revision")
    trusted = _trusted_digests(trusted_observation_digests)
    trusted_set = frozenset(trusted)
    blockers: set[str] = set()
    if matrix.catalog_sha256 != catalog.digest:
        blockers.add("fault.catalog-mismatch")
    if matrix.source_revision != revision:
        blockers.add("fault.matrix-stale-revision")

    observations = {row.scenario_id: row for row in matrix.observations}
    scenarios = catalog.scenario_map
    for scenario_id in sorted(observations.keys() - scenarios.keys()):
        blockers.add(f"fault.foreign-scenario:{scenario_id}")

    for scenario in catalog.scenarios:
        if not scenario.required_for_gate0:
            continue
        observation = observations.get(scenario.scenario_id)
        if observation is None:
            blockers.add(f"fault.missing:{scenario.scenario_id}")
            continue
        if observation.digest not in trusted_set:
            blockers.add(f"fault.untrusted-observation:{scenario.scenario_id}")
        if observation.source_revision != revision:
            blockers.add(f"fault.stale-revision:{scenario.scenario_id}")
        if observation.scenario_sha256 != scenario.digest:
            blockers.add(f"fault.scenario-drift:{scenario.scenario_id}")
        if observation.authority != scenario.authority:
            blockers.add(f"fault.authority-mismatch:{scenario.scenario_id}")
        if observation.status == "failed":
            blockers.add(f"fault.failed:{scenario.scenario_id}")
        elif observation.status == "blocked":
            blockers.add(f"fault.blocked:{scenario.scenario_id}")
        elif observation.observed_outcome != scenario.expected_outcome:
            blockers.add(f"fault.outcome-mismatch:{scenario.scenario_id}")

    return RuntimeFaultVerification(
        matrix_sha256=matrix.digest,
        catalog_sha256=catalog.digest,
        source_revision=revision,
        trusted_observation_sha256s=trusted,
        blockers=tuple(blockers),
    )


_SCENARIOS: tuple[tuple[str, str, str, str, str, str, str], ...] = (
    ("runtime.broker.exact-replay-inert", "broker", "deterministic-fixture", "reuse the exact execution identity and idempotency key", "refused-before-start", "provider and output-evidence callbacks are not invoked twice", "pytest:tests/runtimes/test_runtime_provider_broker.py::test_exact_replay_is_inert_and_reuses_retained_binding"),
    ("runtime.broker.foreign-authority", "broker", "deterministic-fixture", "substitute the registry-bound runtime identity under an otherwise exact authority", "refused-before-start", "no grant, start, or provider effect occurs under foreign authority", "pytest:tests/runtimes/test_runtime_provider_broker.py::test_foreign_noncentral_or_malformed_binding_refuses_before_effect[runtime]"),
    ("runtime.broker.provider-exception", "broker", "deterministic-fixture", "raise an ordinary exception from the provider callback", "failed", "a FAILED terminal is durable before the exception escapes", "pytest:tests/runtimes/test_runtime_provider_broker.py::test_provider_exception_is_terminalized_before_escape[error0-FAILED]"),
    ("runtime.broker.cancellation", "broker", "deterministic-fixture", "raise KeyboardInterrupt from the provider callback", "cancelled", "a CANCELLED terminal is durable before cancellation escapes", "pytest:tests/runtimes/test_runtime_provider_broker.py::test_keyboard_interrupt_is_cancelled_before_it_escapes"),
    ("runtime.broker.trust-loss-after-invoke", "runtime-trust", "deterministic-fixture", "quarantine runtime immediately after provider return", "cancelled", "output evidence is not extracted or released", "pytest:tests/runtimes/test_runtime_provider_broker.py::test_runtime_trust_loss_after_provider_withholds_evidence_and_cancels"),
    ("runtime.broker.trust-loss-after-evidence", "runtime-trust", "deterministic-fixture", "rotate runtime evidence after output materialization", "cancelled", "COMPLETED is not persisted for stale runtime evidence", "pytest:tests/runtimes/test_runtime_provider_broker.py::test_runtime_trust_loss_after_evidence_blocks_completion"),
    ("runtime.fence.quarantine-wins", "runtime-trust", "deterministic-fixture", "commit quarantine after the last ordinary verify but before fence acquisition", "cancelled", "the terminal fence withholds output and records CANCELLED", "pytest:tests/runtimes/test_runtime_terminal_fence.py::test_trust_change_after_last_plain_verify_is_caught_by_terminal_fence[quarantine]"),
    ("runtime.fence.record-rotation-wins", "runtime-trust", "deterministic-fixture", "replace trust-record identity before terminal fence acquisition", "cancelled", "a foreign record cannot receive COMPLETED", "pytest:tests/runtimes/test_runtime_terminal_fence.py::test_trust_change_after_last_plain_verify_is_caught_by_terminal_fence[replace-record]"),
    ("runtime.fence.completion-wins", "runtime-trust", "deterministic-fixture", "race quarantine against a completion already holding the trust writer lock", "completed-before-quarantine", "quarantine cannot interleave before the terminal receipt is durable", "pytest:tests/runtimes/test_runtime_terminal_fence.py::test_quarantine_waits_until_completed_receipt_is_durable"),
    ("runtime.fence.shared-ledger", "effect-ledger", "deterministic-fixture", "configure trust and effect authorities on the same SQLite path", "refused-before-start", "a self-deadlocking configuration is refused before grant", "pytest:tests/runtimes/test_runtime_terminal_fence.py::test_runtime_trust_and_effect_ledgers_must_be_distinct"),
    ("runtime.fence.readonly-commit-failure", "runtime-trust", "deterministic-fixture", "reject COMMIT after the separate effect terminal is durable", "completed-before-quarantine", "the read-only fence rolls back and does not lose a valid result", "pytest:tests/runtimes/test_runtime_terminal_fence_release.py::test_read_only_trust_fence_does_not_commit_after_effect_completion"),
    ("runtime.broker.malformed-output-evidence", "broker", "deterministic-fixture", "return missing, malformed, or duplicate output digests", "failed", "successful output cannot escape without content-addressed evidence", "pytest:tests/runtimes/test_runtime_provider_broker.py::test_missing_or_malformed_output_evidence_marks_execution_failed"),
    ("runtime.effect-terminal.disk-full", "effect-ledger", "deterministic-fixture", "fail terminal receipt persistence with an I/O error", "failed", "the broker raises an explicit state error and never reports success", "pytest:tests/runtimes/test_runtime_provider_broker.py::test_terminal_persistence_failure_is_a_broker_state_error"),
    ("runtime.trust-ledger.lock-contention", "runtime-trust", "linux-host", "hold the trust writer lock past the configured busy timeout", "cancelled", "provider output is withheld and lock failure is retained explicitly", "host-fixture:runtime-trust-lock-contention"),
    ("runtime.effect-ledger.lock-contention", "effect-ledger", "linux-host", "hold the effect writer lock past the configured busy timeout", "refused-before-start", "no provider effect begins without a durable start receipt", "host-fixture:runtime-effect-lock-contention"),
    ("runtime.live-envelope.expiry", "runtime-trust", "live-runtime", "allow the externally signed runtime envelope to expire", "refused-before-start", "expired live evidence cannot authorize a production lease", "live-probe:runtime-envelope-expiry"),
    ("runtime.live-envelope.binary-drift", "runtime-trust", "live-runtime", "change provider binary or image identity after conformance", "refused-before-start", "runtime drift quarantines the exact envelope without fallback", "live-probe:runtime-binary-drift"),
    ("runtime.process.timeout", "provider-process", "linux-host", "run a provider process beyond its declared timeout", "cancelled", "the complete process tree is terminated and no output is accepted", "host-fixture:runtime-process-timeout"),
    ("runtime.process.ignored-sigterm", "provider-process", "linux-host", "make parent and child ignore SIGTERM", "cancelled", "escalated kill removes the entire process tree without orphans", "host-fixture:runtime-process-tree-kill"),
    ("runtime.process.oom", "sandbox", "linux-host", "exceed the runtime memory limit", "failed", "OOM is explicit and cannot fall back to an unsandboxed execution", "host-fixture:runtime-container-oom"),
    ("runtime.sandbox.daemon-unavailable", "sandbox", "linux-host", "make the required container runtime unavailable", "refused-before-start", "sandbox unavailability fails closed with no host-process fallback", "host-fixture:runtime-sandbox-unavailable"),
    ("runtime.egress.unauthorized-endpoint", "egress", "linux-host", "attempt egress outside the leased endpoint set", "failed", "undeclared network destinations are unreachable and evidenced", "host-fixture:runtime-unauthorized-egress"),
    ("runtime.secrets.undeclared-access", "secrets", "linux-host", "enumerate or read a secret not named by the lease", "failed", "undeclared secrets are absent and no secret value enters evidence", "host-fixture:runtime-secret-isolation"),
    ("runtime.effect.unknown-outcome-replay", "effect-ledger", "linux-host", "crash after external acknowledgement but before terminal persistence", "unknown-reconciled", "recovery reconciles the external idempotency key without a second effect", "host-fixture:runtime-unknown-outcome-reconciliation"),
)

RUNTIME_FAULT_CATALOG = RuntimeFaultCatalog(
    catalog_id="gate0-runtime-faults-v1",
    scenarios=tuple(RuntimeFaultScenario(*row) for row in _SCENARIOS),
)

__all__ = [
    "RUNTIME_FAULT_CATALOG",
    "RuntimeFaultCatalog",
    "RuntimeFaultMatrix",
    "RuntimeFaultObservation",
    "RuntimeFaultScenario",
    "RuntimeFaultVerification",
    "build_runtime_fault_matrix",
    "verify_runtime_fault_matrix",
]
