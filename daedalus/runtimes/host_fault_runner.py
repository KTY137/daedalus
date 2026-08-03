"""Fail-closed execution records for Linux-host runtime fault scenarios.

This module is the collector-side seam between a concrete host fault executor
and the canonical :mod:`daedalus.runtimes.fault_matrix` contracts. It does not
make an observation trusted. A run records bounded, content-addressed evidence
and produces a :class:`RuntimeFaultObservation`; the separate attestation
boundary must still authenticate that complete observation before it can enter
the trusted digest set.

Executors are selected by the exact locator declared in the canonical catalog.
Missing executors become explicit ``blocked`` observations. Exceptions,
malformed results, and outcome mismatches become ``failed`` observations rather
than disappearing or being upgraded to a pass.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, fields
from datetime import datetime, timezone
from typing import Any, Callable, Mapping, Sequence

from daedalus.runtimes.fault_matrix import (
    RuntimeFaultCatalog,
    RuntimeFaultObservation,
    RuntimeFaultScenario,
)
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_json, canonical_sha

_SCHEMA = "daedalus-linux-host-fault-evidence/1"
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVISION_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
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
_MAX_RAW_EVIDENCE_BYTES = 1024 * 1024
_MAX_FACTS = 64


class LinuxHostFaultRunnerError(RuntimeError):
    """Base class for collector-side host fault failures."""


class LinuxHostFaultBindingMismatch(LinuxHostFaultRunnerError):
    """The selected catalog scenario, revision, or executor does not match."""


class LinuxHostFaultClockError(LinuxHostFaultRunnerError):
    """The collector clock is malformed or moves backwards."""


def _identifier(value: Any, name: str) -> str:
    if not isinstance(value, str) or _ID_RE.fullmatch(value) is None:
        raise ValueError(f"{name} must be a lowercase stable identifier")
    return value


def _non_empty(value: Any, name: str, *, maximum: int = 500) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    text = value.strip()
    if len(text) > maximum:
        raise ValueError(f"{name} exceeds {maximum} characters")
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


def _clock_value(clock: Callable[[], datetime], name: str) -> datetime:
    value = clock()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise LinuxHostFaultClockError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _strict_payload(payload: Mapping[str, Any], cls: type, name: str) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{name} must be an object")
    expected = {item.name for item in fields(cls)}
    missing = sorted(expected - set(payload))
    extra = sorted(set(payload) - expected)
    if missing or extra:
        raise ValueError(f"{name} fields mismatch; missing={missing}, extra={extra}")
    return dict(payload)


def _sequence(value: Any, name: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ValueError(f"{name} must be an array")
    return tuple(value)


def _raw_evidence(value: Any) -> bytes:
    if not isinstance(value, bytes):
        raise ValueError("raw_evidence must be bytes")
    if not value:
        raise ValueError("raw_evidence must not be empty")
    if len(value) > _MAX_RAW_EVIDENCE_BYTES:
        raise ValueError("raw_evidence exceeds one MiB")
    return value


@dataclass(frozen=True)
class HostFaultFact:
    name: str
    value: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _identifier(self.name, "fact.name"))
        object.__setattr__(self, "value", _non_empty(self.value, "fact.value"))

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "value": self.value}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "HostFaultFact":
        return cls(**_strict_payload(payload, cls, "host fault fact"))


@dataclass(frozen=True)
class HostFaultResult:
    """Bounded executor output before collector evidence is materialized."""

    status: str
    observed_outcome: str | None
    detail_code: str | None
    raw_evidence: bytes
    facts: tuple[HostFaultFact, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in _STATUSES:
            raise ValueError(f"status must be one of {sorted(_STATUSES)}")
        if self.observed_outcome is not None and self.observed_outcome not in _OUTCOMES:
            raise ValueError(f"observed_outcome must be one of {sorted(_OUTCOMES)}")
        if self.status == "passed":
            if self.observed_outcome is None:
                raise ValueError("passed host fault results require observed_outcome")
            if self.detail_code is not None:
                raise ValueError("passed host fault results must not carry detail_code")
        elif self.status == "blocked":
            if self.observed_outcome is not None:
                raise ValueError("blocked host fault results must not invent observed_outcome")
            object.__setattr__(
                self, "detail_code", _identifier(self.detail_code, "detail_code")
            )
        else:
            object.__setattr__(
                self, "detail_code", _identifier(self.detail_code, "detail_code")
            )
        object.__setattr__(self, "raw_evidence", _raw_evidence(self.raw_evidence))
        rows = tuple(sorted(self.facts, key=lambda row: row.name))
        if len(rows) > _MAX_FACTS:
            raise ValueError(f"host fault result exceeds {_MAX_FACTS} facts")
        names = tuple(row.name for row in rows)
        if len(names) != len(set(names)):
            raise ValueError("host fault result contains duplicate fact names")
        object.__setattr__(self, "facts", rows)


@dataclass(frozen=True)
class LinuxHostFaultEvidence:
    """Canonical collector artifact for one exact Linux-host scenario."""

    schema: str
    scenario_id: str
    scenario_sha256: str
    source_revision: str
    executor: str
    started_at: str
    finished_at: str
    status: str
    observed_outcome: str | None
    detail_code: str | None
    raw_evidence_sha256: str
    facts: tuple[HostFaultFact, ...]

    def __post_init__(self) -> None:
        if self.schema != _SCHEMA:
            raise ValueError(f"schema must be {_SCHEMA}")
        object.__setattr__(self, "scenario_id", _identifier(self.scenario_id, "scenario_id"))
        object.__setattr__(
            self, "scenario_sha256", _sha256(self.scenario_sha256, "scenario_sha256")
        )
        object.__setattr__(self, "source_revision", _revision(self.source_revision))
        object.__setattr__(self, "executor", _non_empty(self.executor, "executor", maximum=1000))
        object.__setattr__(self, "started_at", _timestamp(self.started_at, "started_at"))
        object.__setattr__(self, "finished_at", _timestamp(self.finished_at, "finished_at"))
        if datetime.fromisoformat(self.finished_at) < datetime.fromisoformat(self.started_at):
            raise ValueError("finished_at must not precede started_at")
        if self.status not in _STATUSES:
            raise ValueError(f"status must be one of {sorted(_STATUSES)}")
        if self.observed_outcome is not None and self.observed_outcome not in _OUTCOMES:
            raise ValueError(f"observed_outcome must be one of {sorted(_OUTCOMES)}")
        if self.status == "passed":
            if self.observed_outcome is None:
                raise ValueError("passed host fault evidence requires observed_outcome")
            if self.detail_code is not None:
                raise ValueError("passed host fault evidence must not carry detail_code")
        elif self.status == "blocked":
            if self.observed_outcome is not None:
                raise ValueError("blocked host fault evidence must not invent observed_outcome")
            object.__setattr__(
                self, "detail_code", _identifier(self.detail_code, "detail_code")
            )
        else:
            object.__setattr__(
                self, "detail_code", _identifier(self.detail_code, "detail_code")
            )
        object.__setattr__(
            self,
            "raw_evidence_sha256",
            _sha256(self.raw_evidence_sha256, "raw_evidence_sha256"),
        )
        rows = tuple(sorted(self.facts, key=lambda row: row.name))
        if len(rows) > _MAX_FACTS:
            raise ValueError(f"host fault evidence exceeds {_MAX_FACTS} facts")
        names = tuple(row.name for row in rows)
        if len(names) != len(set(names)):
            raise ValueError("host fault evidence contains duplicate fact names")
        object.__setattr__(self, "facts", rows)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "scenario_id": self.scenario_id,
            "scenario_sha256": self.scenario_sha256,
            "source_revision": self.source_revision,
            "executor": self.executor,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "observed_outcome": self.observed_outcome,
            "detail_code": self.detail_code,
            "raw_evidence_sha256": self.raw_evidence_sha256,
            "facts": [row.to_dict() for row in self.facts],
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "LinuxHostFaultEvidence":
        body = _strict_payload(payload, cls, "linux host fault evidence")
        body["facts"] = tuple(
            HostFaultFact.from_dict(row) for row in _sequence(body["facts"], "facts")
        )
        return cls(**body)


@dataclass(frozen=True)
class LinuxHostFaultRun:
    """One evidence artifact and its exact canonical fault observation."""

    evidence: LinuxHostFaultEvidence
    observation: RuntimeFaultObservation

    def __post_init__(self) -> None:
        expected = {
            "scenario_id": (self.observation.scenario_id, self.evidence.scenario_id),
            "scenario_sha256": (
                self.observation.scenario_sha256,
                self.evidence.scenario_sha256,
            ),
            "source_revision": (
                self.observation.source_revision,
                self.evidence.source_revision,
            ),
            "authority": (self.observation.authority, "linux-host"),
            "status": (self.observation.status, self.evidence.status),
            "observed_outcome": (
                self.observation.observed_outcome,
                self.evidence.observed_outcome,
            ),
            "detail_code": (self.observation.detail_code, self.evidence.detail_code),
            "observed_at": (self.observation.observed_at, self.evidence.finished_at),
            "evidence_sha256": (self.observation.evidence_sha256, self.evidence.digest),
        }
        mismatches = sorted(
            name for name, (actual, wanted) in expected.items() if actual != wanted
        )
        if mismatches:
            raise LinuxHostFaultBindingMismatch(
                "host fault run binding mismatch: " + ", ".join(mismatches)
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence": self.evidence.to_dict(),
            "observation": self.observation.to_dict(),
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


LinuxHostExecutor = Callable[[RuntimeFaultScenario], HostFaultResult]


def _internal_result(
    scenario: RuntimeFaultScenario,
    *,
    status: str,
    observed_outcome: str | None,
    detail_code: str,
    fact_name: str,
    fact_value: str,
) -> HostFaultResult:
    payload = {
        "schema": _SCHEMA,
        "scenario_id": scenario.scenario_id,
        "scenario_sha256": scenario.digest,
        "status": status,
        "observed_outcome": observed_outcome,
        "detail_code": detail_code,
        fact_name: fact_value,
    }
    return HostFaultResult(
        status=status,
        observed_outcome=observed_outcome,
        detail_code=detail_code,
        raw_evidence=canonical_json(payload).encode("utf-8"),
        facts=(HostFaultFact(fact_name, fact_value),),
    )


def _normalize_executor_result(
    scenario: RuntimeFaultScenario,
    executor: LinuxHostExecutor | None,
) -> HostFaultResult:
    if executor is None:
        return _internal_result(
            scenario,
            status="blocked",
            observed_outcome=None,
            detail_code="executor-unavailable",
            fact_name="executor-state",
            fact_value="missing",
        )
    try:
        result = executor(scenario)
    except Exception as exc:
        return _internal_result(
            scenario,
            status="failed",
            observed_outcome="failed",
            detail_code="executor-error",
            fact_name="exception-type",
            fact_value=type(exc).__name__,
        )
    if not isinstance(result, HostFaultResult):
        return _internal_result(
            scenario,
            status="failed",
            observed_outcome="failed",
            detail_code="executor-contract",
            fact_name="result-type",
            fact_value=type(result).__name__,
        )
    if result.status == "passed" and result.observed_outcome != scenario.expected_outcome:
        facts = tuple(result.facts) + (
            HostFaultFact("expected-outcome", scenario.expected_outcome),
            HostFaultFact("reported-outcome", str(result.observed_outcome)),
        )
        return HostFaultResult(
            status="failed",
            observed_outcome=result.observed_outcome,
            detail_code="outcome-mismatch",
            raw_evidence=result.raw_evidence,
            facts=facts,
        )
    return result


def run_linux_host_fault(
    scenario: RuntimeFaultScenario,
    *,
    source_revision: str,
    executor: LinuxHostExecutor | None,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> LinuxHostFaultRun:
    """Execute or explicitly block one exact Linux-host catalog scenario."""

    revision = _revision(source_revision)
    if scenario.authority != "linux-host":
        raise LinuxHostFaultBindingMismatch(
            f"scenario {scenario.scenario_id} is not a linux-host scenario"
        )
    started = _clock_value(clock, "started_at")
    result = _normalize_executor_result(scenario, executor)
    finished = _clock_value(clock, "finished_at")
    if finished < started:
        raise LinuxHostFaultClockError("collector clock moved backwards")

    evidence = LinuxHostFaultEvidence(
        schema=_SCHEMA,
        scenario_id=scenario.scenario_id,
        scenario_sha256=scenario.digest,
        source_revision=revision,
        executor=scenario.executor,
        started_at=started.isoformat(timespec="microseconds"),
        finished_at=finished.isoformat(timespec="microseconds"),
        status=result.status,
        observed_outcome=result.observed_outcome,
        detail_code=result.detail_code,
        raw_evidence_sha256=hashlib.sha256(result.raw_evidence).hexdigest(),
        facts=result.facts,
    )
    provenance = ContractProvenance(
        origin="daedalus.runtimes.host_fault_runner",
        source_revision=revision,
        created_at=evidence.finished_at,
        input_digests=tuple(sorted((scenario.digest, evidence.digest))),
        trace_id=scenario.scenario_id,
    )
    observation = RuntimeFaultObservation(
        observation_id="host-" + evidence.digest[:24],
        scenario_id=scenario.scenario_id,
        scenario_sha256=scenario.digest,
        source_revision=revision,
        authority="linux-host",
        status=evidence.status,
        observed_outcome=evidence.observed_outcome,
        observed_at=evidence.finished_at,
        evidence_sha256=evidence.digest,
        detail_code=evidence.detail_code,
        provenance=provenance,
    )
    return LinuxHostFaultRun(evidence=evidence, observation=observation)


def run_linux_host_fault_catalog(
    *,
    catalog: RuntimeFaultCatalog,
    source_revision: str,
    executors: Mapping[str, LinuxHostExecutor],
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> tuple[LinuxHostFaultRun, ...]:
    """Run every Linux-host row while making unsupported rows explicit blockers."""

    if not isinstance(executors, Mapping):
        raise ValueError("executors must be a mapping")
    scenarios = tuple(row for row in catalog.scenarios if row.authority == "linux-host")
    expected_locators = frozenset(row.executor for row in scenarios)
    foreign = sorted(set(executors) - expected_locators)
    if foreign:
        raise LinuxHostFaultBindingMismatch(
            "executor registry contains foreign locators: " + ", ".join(foreign)
        )
    return tuple(
        run_linux_host_fault(
            scenario,
            source_revision=source_revision,
            executor=executors.get(scenario.executor),
            clock=clock,
        )
        for scenario in scenarios
    )


__all__ = [
    "HostFaultFact",
    "HostFaultResult",
    "LinuxHostExecutor",
    "LinuxHostFaultBindingMismatch",
    "LinuxHostFaultClockError",
    "LinuxHostFaultEvidence",
    "LinuxHostFaultRun",
    "LinuxHostFaultRunnerError",
    "run_linux_host_fault",
    "run_linux_host_fault_catalog",
]
