"""Fail-closed execution records for ``live-runtime`` runtime fault rows.

This is the third collector column, sibling to
:mod:`daedalus.runtimes.host_fault_runner` (``linux-host``) and
:mod:`daedalus.runtimes.fixture_fault_collector` (``deterministic-fixture``).
Same shape, same fail-closed discipline, different authority. It does not make
an observation trusted; the separate attestation boundary
(:mod:`daedalus.runtimes.live_fault_attestation_issuer`) must still authenticate
the complete observation before it can enter the trusted digest set.

What makes this column different is what it is allowed to observe.

**A live row needs live evidence.** The two catalog rows carried by this
authority (``runtime.live-envelope.expiry`` and
``runtime.live-envelope.binary-drift``) are refusals *of a production runtime
lease*. A lease is only ever authorized by a ``live-runtime``
:class:`~daedalus.runtimes.profiles.RuntimeConformanceEnvelope`: a probe identity
measured from a really installed provider plus a conformance receipt assembled
from live observations of every check. No such envelope can be manufactured by
this collector, and an ``offline-fixture`` envelope is not a substitute. When no
live envelope is supplied the row is ``blocked`` with a named reason and the
facts that *were* measured are retained. It is never quietly skipped and never
upgraded to a pass.

**A refusal alone proves nothing.** Both rows expect ``refused-before-start``,
and the trivial way to produce a refusal is to hand the boundary something it
would have rejected anyway. Therefore every driver in this column must first
demonstrate a *positive control* -- the unmodified bundle is accepted at the
lease boundary -- and only then inject its fault and observe the refusal. A
driver that cannot establish its control reports ``blocked``; a driver whose
control is accepted but whose fault is *also* accepted reports ``failed``. That
discipline lives in :mod:`daedalus.runtimes.live_probe_drivers`; this module is
the seam that records whatever the driver honestly produced.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from daedalus.runtimes.fault_matrix import (
    RuntimeFaultCatalog,
    RuntimeFaultObservation,
    RuntimeFaultScenario,
)
from daedalus.runtimes.host_fault_runner import HostFaultFact
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_json, canonical_sha

_SCHEMA = "daedalus-live-runtime-fault-evidence/1"
_AUTHORITY = "live-runtime"
_EXECUTOR_PREFIX = "live-probe:"
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
        "started-unreconciled",
    }
)
_MAX_RAW_EVIDENCE_BYTES = 1024 * 1024
_MAX_FACTS = 64
_MAX_WIRE_BYTES = 2 * 1024 * 1024


class LiveFaultCollectorError(RuntimeError):
    """Base class for collector-side live-runtime fault failures."""


class LiveFaultBindingMismatch(LiveFaultCollectorError):
    """The selected catalog scenario, revision, or executor does not match."""


class LiveFaultClockError(LiveFaultCollectorError):
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
        raise LiveFaultClockError(f"{name} must be timezone-aware")
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


def _object_pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant is not allowed: {value}")


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


def _facts(values: Sequence[HostFaultFact], name: str) -> tuple[HostFaultFact, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise ValueError(f"{name} must be an array")
    rows = tuple(values)
    if any(not isinstance(row, HostFaultFact) for row in rows):
        raise ValueError(f"{name} must contain HostFaultFact records")
    rows = tuple(sorted(rows, key=lambda row: row.name))
    if len(rows) > _MAX_FACTS:
        raise ValueError(f"{name} exceeds {_MAX_FACTS} facts")
    names = tuple(row.name for row in rows)
    if len(names) != len(set(names)):
        raise ValueError(f"{name} contains duplicate fact names")
    return rows


@dataclass(frozen=True)
class LiveProbeResult:
    """Bounded live-probe output before collector evidence is materialized."""

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
                raise ValueError("passed live probe results require observed_outcome")
            if self.detail_code is not None:
                raise ValueError("passed live probe results must not carry detail_code")
        elif self.status == "blocked":
            if self.observed_outcome is not None:
                raise ValueError("blocked live probe results must not invent observed_outcome")
            object.__setattr__(
                self, "detail_code", _identifier(self.detail_code, "detail_code")
            )
        else:
            object.__setattr__(
                self, "detail_code", _identifier(self.detail_code, "detail_code")
            )
        object.__setattr__(self, "raw_evidence", _raw_evidence(self.raw_evidence))
        object.__setattr__(self, "facts", _facts(self.facts, "live probe result facts"))


LiveProbeExecutor = Callable[[RuntimeFaultScenario], LiveProbeResult]


@dataclass(frozen=True)
class LiveProbeExecutorBinding:
    """Exact logical locator and implementation identity for one live probe."""

    locator: str
    implementation_sha256: str
    execute: LiveProbeExecutor = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "locator", _non_empty(self.locator, "executor.locator", maximum=1000)
        )
        if not self.locator.startswith(_EXECUTOR_PREFIX):
            raise ValueError(f"live probe locator must start with {_EXECUTOR_PREFIX!r}")
        object.__setattr__(
            self,
            "implementation_sha256",
            _sha256(self.implementation_sha256, "executor.implementation_sha256"),
        )
        if not callable(self.execute):
            raise ValueError("executor.execute must be callable")


@dataclass(frozen=True)
class LiveFaultEvidence:
    """Canonical collector artifact for one exact live-runtime scenario."""

    schema: str
    scenario_id: str
    scenario_sha256: str
    source_revision: str
    executor: str
    executor_sha256: str
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
        if not self.executor.startswith(_EXECUTOR_PREFIX):
            raise ValueError(f"live fault executor must start with {_EXECUTOR_PREFIX!r}")
        object.__setattr__(
            self, "executor_sha256", _sha256(self.executor_sha256, "executor_sha256")
        )
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
                raise ValueError("passed live fault evidence requires observed_outcome")
            if self.detail_code is not None:
                raise ValueError("passed live fault evidence must not carry detail_code")
        elif self.status == "blocked":
            if self.observed_outcome is not None:
                raise ValueError("blocked live fault evidence must not invent observed_outcome")
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
        object.__setattr__(self, "facts", _facts(self.facts, "live fault evidence facts"))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "scenario_id": self.scenario_id,
            "scenario_sha256": self.scenario_sha256,
            "source_revision": self.source_revision,
            "executor": self.executor,
            "executor_sha256": self.executor_sha256,
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
    def from_dict(cls, payload: Mapping[str, Any]) -> "LiveFaultEvidence":
        body = _strict_payload(payload, cls, "live fault evidence")
        body["facts"] = tuple(
            HostFaultFact.from_dict(row) for row in _sequence(body["facts"], "facts")
        )
        return cls(**body)


def load_live_fault_evidence_json(text: str) -> LiveFaultEvidence:
    """Parse one untrusted evidence document without JSON ambiguity."""

    if not isinstance(text, str):
        raise ValueError("live fault evidence JSON must be text")
    if len(text.encode("utf-8")) > _MAX_WIRE_BYTES:
        raise ValueError("live fault evidence JSON exceeds two MiB")
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_object_pairs_no_duplicates,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as exc:
        raise ValueError("live fault evidence JSON is malformed") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("live fault evidence JSON root must be an object")
    return LiveFaultEvidence.from_dict(payload)


@dataclass(frozen=True)
class LiveFaultRun:
    """One evidence artifact, retained raw bytes, and exact observation."""

    evidence: LiveFaultEvidence
    observation: RuntimeFaultObservation
    raw_evidence: bytes = field(repr=False)

    def __post_init__(self) -> None:
        retained = _raw_evidence(self.raw_evidence)
        if hashlib.sha256(retained).hexdigest() != self.evidence.raw_evidence_sha256:
            raise LiveFaultBindingMismatch(
                "retained raw evidence does not match the collector artifact"
            )
        object.__setattr__(self, "raw_evidence", retained)
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
            "authority": (self.observation.authority, _AUTHORITY),
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
            raise LiveFaultBindingMismatch(
                "live fault run binding mismatch: " + ", ".join(mismatches)
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence": self.evidence.to_dict(),
            "observation": self.observation.to_dict(),
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def _internal_result(
    scenario: RuntimeFaultScenario,
    *,
    status: str,
    observed_outcome: str | None,
    detail_code: str,
    facts: Mapping[str, str],
) -> LiveProbeResult:
    payload = {
        "schema": _SCHEMA,
        "scenario_id": scenario.scenario_id,
        "scenario_sha256": scenario.digest,
        "status": status,
        "observed_outcome": observed_outcome,
        "detail_code": detail_code,
        "facts": dict(sorted(facts.items())),
    }
    return LiveProbeResult(
        status=status,
        observed_outcome=observed_outcome,
        detail_code=detail_code,
        raw_evidence=canonical_json(payload).encode("utf-8"),
        facts=tuple(HostFaultFact(name, value) for name, value in sorted(facts.items())),
    )


def _normalize_executor_result(
    scenario: RuntimeFaultScenario,
    executor: LiveProbeExecutorBinding | None,
) -> LiveProbeResult:
    if executor is None:
        return _internal_result(
            scenario,
            status="blocked",
            observed_outcome=None,
            detail_code="live-probe-unavailable",
            facts={
                "executor-state": "missing",
                "required-executor": scenario.executor,
            },
        )
    if executor.locator != scenario.executor:
        raise LiveFaultBindingMismatch(
            "executor binding locator does not match the catalog scenario"
        )
    try:
        result = executor.execute(scenario)
    except Exception as exc:
        return _internal_result(
            scenario,
            status="failed",
            observed_outcome="failed",
            detail_code="live-probe-error",
            facts={"exception-type": type(exc).__name__},
        )
    if not isinstance(result, LiveProbeResult):
        return _internal_result(
            scenario,
            status="failed",
            observed_outcome="failed",
            detail_code="live-probe-contract",
            facts={"result-type": type(result).__name__},
        )
    if result.status == "passed" and result.observed_outcome != scenario.expected_outcome:
        merged = {row.name: row.value for row in result.facts}
        merged["collector-expected-outcome"] = scenario.expected_outcome
        merged["collector-reported-outcome"] = str(result.observed_outcome)
        facts = tuple(HostFaultFact(name, value) for name, value in sorted(merged.items()))
        return LiveProbeResult(
            status="failed",
            observed_outcome=result.observed_outcome,
            detail_code="outcome-mismatch",
            raw_evidence=result.raw_evidence,
            facts=facts,
        )
    return result


def run_live_fault(
    scenario: RuntimeFaultScenario,
    *,
    source_revision: str,
    executor: LiveProbeExecutorBinding | None,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> LiveFaultRun:
    """Execute or explicitly block one exact live-runtime catalog scenario."""

    revision = _revision(source_revision)
    if scenario.authority != _AUTHORITY:
        raise LiveFaultBindingMismatch(
            f"scenario {scenario.scenario_id} is not a {_AUTHORITY} scenario"
        )
    started = _clock_value(clock, "started_at")
    result = _normalize_executor_result(scenario, executor)
    finished = _clock_value(clock, "finished_at")
    if finished < started:
        raise LiveFaultClockError("collector clock moved backwards")

    evidence = LiveFaultEvidence(
        schema=_SCHEMA,
        scenario_id=scenario.scenario_id,
        scenario_sha256=scenario.digest,
        source_revision=revision,
        executor=scenario.executor,
        executor_sha256=(
            executor.implementation_sha256
            if executor is not None
            else hashlib.sha256(
                ("missing-live-probe\0" + scenario.executor).encode("utf-8")
            ).hexdigest()
        ),
        started_at=started.isoformat(timespec="microseconds"),
        finished_at=finished.isoformat(timespec="microseconds"),
        status=result.status,
        observed_outcome=result.observed_outcome,
        detail_code=result.detail_code,
        raw_evidence_sha256=hashlib.sha256(result.raw_evidence).hexdigest(),
        facts=result.facts,
    )
    provenance = ContractProvenance(
        origin="daedalus.runtimes.live_fault_collector",
        source_revision=revision,
        created_at=evidence.finished_at,
        input_digests=tuple(sorted((scenario.digest, evidence.digest))),
        trace_id=scenario.scenario_id,
    )
    observation = RuntimeFaultObservation(
        observation_id="live-" + evidence.digest[:24],
        scenario_id=scenario.scenario_id,
        scenario_sha256=scenario.digest,
        source_revision=revision,
        authority=_AUTHORITY,
        status=evidence.status,
        observed_outcome=evidence.observed_outcome,
        observed_at=evidence.finished_at,
        evidence_sha256=evidence.digest,
        detail_code=evidence.detail_code,
        provenance=provenance,
    )
    return LiveFaultRun(
        evidence=evidence,
        observation=observation,
        raw_evidence=result.raw_evidence,
    )


def run_live_fault_catalog(
    *,
    catalog: RuntimeFaultCatalog,
    source_revision: str,
    executors: Mapping[str, LiveProbeExecutorBinding],
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> tuple[LiveFaultRun, ...]:
    """Run every live-runtime row while making unsupported rows explicit blockers."""

    if not isinstance(executors, Mapping):
        raise ValueError("executors must be a mapping")
    scenarios = tuple(row for row in catalog.scenarios if row.authority == _AUTHORITY)
    if not scenarios:
        raise LiveFaultBindingMismatch(
            f"runtime fault catalog contains no {_AUTHORITY} scenarios"
        )
    registered: list[str] = []
    for locator, binding in executors.items():
        if not isinstance(locator, str):
            raise ValueError("executor registry locators must be strings")
        if not isinstance(binding, LiveProbeExecutorBinding):
            raise ValueError(
                "executor registry values must be LiveProbeExecutorBinding records"
            )
        if binding.locator != locator:
            raise LiveFaultBindingMismatch(
                "executor registry key does not match its binding locator"
            )
        registered.append(locator)
    expected_locators = frozenset(row.executor for row in scenarios)
    foreign = sorted(set(registered) - expected_locators)
    if foreign:
        raise LiveFaultBindingMismatch(
            "executor registry contains foreign locators: " + ", ".join(foreign)
        )
    return tuple(
        run_live_fault(
            scenario,
            source_revision=source_revision,
            executor=executors.get(scenario.executor),
            clock=clock,
        )
        for scenario in scenarios
    )


def retain_live_fault_run(directory: Path, run: LiveFaultRun) -> None:
    """Write one artifact triple in the layout the live issuer expects."""

    base = Path(directory)
    base.mkdir(parents=True, exist_ok=True)
    scenario_id = run.observation.scenario_id
    (base / f"{scenario_id}.evidence.json").write_text(
        canonical_json(run.evidence.to_dict()) + "\n", encoding="utf-8"
    )
    (base / f"{scenario_id}.observation.json").write_text(
        canonical_json(run.observation.to_dict()) + "\n", encoding="utf-8"
    )
    (base / f"{scenario_id}.raw").write_bytes(run.raw_evidence)


def main(argv: Sequence[str] | None = None) -> int:
    """Collect the live-runtime column and retain its evidence.

    This entrypoint produces evidence and nothing else. It holds no signing key
    and cannot place an observation into a trust set; that is the separate
    ``live-fault-attestation`` operator step.

    Without ``--live-envelope-dir`` the collector has no live evidence to work
    from and both rows are retained as ``blocked`` with a named reason. That is
    the honest state of a host that cannot mint a production runtime lease, and
    it is deliberately not the same thing as a skipped row.
    """

    import argparse
    import sys

    from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG

    # ``python -m daedalus.runtimes.live_fault_collector`` loads this file as
    # ``__main__`` while the drivers import it under its package name, so the two
    # copies would hold *different* LiveProbeExecutorBinding classes and every
    # binding would fail its isinstance check. Delegate to the canonical module
    # instead of type-checking across a duplicated import.
    from daedalus.runtimes import live_fault_collector as canonical

    if canonical is not sys.modules[__name__]:
        return canonical.main(argv)

    from daedalus.runtimes.live_probe_drivers import build_live_probe_executors

    parser = argparse.ArgumentParser(
        description=(
            "Run every live-runtime runtime fault row against a supplied live "
            "conformance envelope and retain bounded, content-addressed "
            "evidence. Produces no signatures and grants no trust."
        )
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument(
        "--live-envelope-dir",
        type=Path,
        default=None,
        help=(
            "directory holding one live-runtime bundle: <name>-envelope.json, "
            "-probe-identity.json, -manifest.json and -receipt.json. Omit it on a "
            "host that cannot produce live evidence; every row is then blocked "
            "with a named reason instead of silently passing."
        ),
    )
    parser.add_argument(
        "--provider-binary",
        type=Path,
        default=None,
        help=(
            "path to the really installed provider executable, re-measured by the "
            "binary-drift probe. Required for that row to run at all."
        ),
    )
    args = parser.parse_args(argv)

    # Canonical Gate-0 effect start, placed after the canonical-module
    # delegation above so it fires exactly once per run, and after argument
    # parsing so a usage error stays fail-open. What this decision really does
    # is install the in-process spend net; it is an honest interposition for
    # the run, and it is deliberately NOT a claim that the evidence write was
    # inspected -- this row declares filesystem_write only, and no fs-write
    # contract exists in GUARD_CONTRACT_IMPLEMENTED to make a stronger one.
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "runtimes.live_fault_collector",
        REGISTRY_BY_ID["runtimes.live_fault_collector"].effects,
        (process_guard_boundary_decision(),),
    )

    executors = build_live_probe_executors(
        live_envelope_dir=args.live_envelope_dir,
        provider_binary=args.provider_binary,
    )
    runs = run_live_fault_catalog(
        catalog=RUNTIME_FAULT_CATALOG,
        source_revision=args.source_revision,
        executors=executors,
    )
    for run in runs:
        retain_live_fault_run(args.run_dir, run)
    summary = {
        "collected": len(runs),
        "passed": sum(1 for row in runs if row.observation.status == "passed"),
        "failed": sum(1 for row in runs if row.observation.status == "failed"),
        "blocked": sum(1 for row in runs if row.observation.status == "blocked"),
        "rows": [
            {
                "scenario_id": row.observation.scenario_id,
                "status": row.observation.status,
                "observed_outcome": row.observation.observed_outcome,
                "detail_code": row.observation.detail_code,
                "facts": {fact.name: fact.value for fact in row.evidence.facts},
            }
            for row in runs
        ],
    }
    print(canonical_json(summary))
    # Exit non-zero when anything did not cleanly pass. Retaining the evidence
    # is still the point, so the artifacts are written either way.
    return 0 if summary["passed"] == summary["collected"] else 1


__all__ = [
    "LiveFaultBindingMismatch",
    "LiveFaultClockError",
    "LiveFaultCollectorError",
    "LiveFaultEvidence",
    "LiveFaultRun",
    "LiveProbeExecutor",
    "LiveProbeExecutorBinding",
    "LiveProbeResult",
    "load_live_fault_evidence_json",
    "main",
    "retain_live_fault_run",
    "run_live_fault",
    "run_live_fault_catalog",
]


if __name__ == "__main__":
    raise SystemExit(main())
