"""Fail-closed execution records for deterministic-fixture runtime fault rows.

This module is the collector-side seam between the pytest nodes named by the
canonical catalog and the contracts in :mod:`daedalus.runtimes.fault_matrix`.
It is the sibling of :mod:`daedalus.runtimes.host_fault_runner`: same shape,
same fail-closed discipline, different column. It does not make an observation
trusted; the separate attestation boundary must still authenticate the complete
observation before it can enter the trusted digest set.

Two properties of this column drive the whole design.

**A green exit code is not an outcome.** The catalog demands that a passing
observation report the terminal outcome that was actually reached, so that
:func:`~daedalus.runtimes.fault_matrix.verify_runtime_fault_matrix` can compare
it against the expected outcome. If this collector derived the outcome from the
catalog it would be comparing the catalog with itself. Therefore the pytest node
must *report* the outcome it observed, via
``record_property("runtime_fault_observed_outcome", ...)``, exactly as a
Linux-host executor reports :class:`~daedalus.runtimes.host_fault_runner.HostFaultResult.observed_outcome`.
A node that passes without reporting is ``blocked`` with ``outcome-unreported``:
honest ignorance, never an assumed pass.

**A broken harness is not a red test.** An import error, a syntax error, a
missing or ambiguous node, a timeout, or a crashed runner says nothing about the
invariant under test. Those become ``blocked`` with a named ``detail_code``.
Only a node that actually ran and actually failed its assertions becomes
``failed``. Both are matrix blockers, but they are different findings and the
evidence keeps them apart.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import re
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence
from xml.etree import ElementTree

from daedalus.runtimes.fault_matrix import (
    RuntimeFaultCatalog,
    RuntimeFaultObservation,
    RuntimeFaultScenario,
)
from daedalus.runtimes.host_fault_runner import HostFaultFact
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_json, canonical_sha

_SCHEMA = "daedalus-fixture-fault-evidence/1"
_AUTHORITY = "deterministic-fixture"
_EXECUTOR_PREFIX = "pytest:"
_OUTCOME_PROPERTY = "runtime_fault_observed_outcome"
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
_MAX_JUNIT_BYTES = 4 * 1024 * 1024
_MAX_WIRE_BYTES = 2 * 1024 * 1024
_MAX_STDOUT_CHARS = 8000
_DEFAULT_TIMEOUT_SECONDS = 600


class FixtureFaultCollectorError(RuntimeError):
    """Base class for collector-side deterministic-fixture failures."""


class FixtureFaultBindingMismatch(FixtureFaultCollectorError):
    """The selected catalog scenario, revision, or executor does not match."""


class FixtureFaultClockError(FixtureFaultCollectorError):
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
        raise FixtureFaultClockError(f"{name} must be timezone-aware")
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


def scenario_node_id(scenario: RuntimeFaultScenario) -> str:
    """Return the exact pytest node id a deterministic-fixture row declares."""

    if scenario.authority != _AUTHORITY:
        raise FixtureFaultBindingMismatch(
            f"scenario {scenario.scenario_id} is not a {_AUTHORITY} scenario"
        )
    if not scenario.executor.startswith(_EXECUTOR_PREFIX):
        raise FixtureFaultBindingMismatch(
            f"scenario {scenario.scenario_id} does not declare a pytest executor"
        )
    node = scenario.executor[len(_EXECUTOR_PREFIX) :].strip()
    if not node or "::" not in node:
        raise FixtureFaultBindingMismatch(
            f"scenario {scenario.scenario_id} declares a malformed pytest node id"
        )
    return node


def derive_terminal_outcome(
    *,
    terminal_outcome: str | None,
    execution_state: str | None = None,
) -> str:
    """Translate a durable broker terminal into the catalog's outcome vocabulary.

    This exists so that a fixture node never writes an outcome literal. The node
    passes the terminal state it just asserted on, and this shared rule names it.
    Anything unmappable raises, which surfaces as a red or errored node rather
    than as a quietly wrong pass.

    A durable ``COMPLETED`` terminal inside a fault scenario means the effect
    became durable before the competing quarantine could interleave; the catalog
    calls that ``completed-before-quarantine``. There is deliberately no plain
    "completed" outcome: an uncontested success is not a fault observation.
    """

    state = None if execution_state is None else str(execution_state).strip().lower()
    if terminal_outcome is None:
        if state is not None:
            raise ValueError(
                "a durable execution state without a terminal is not a clean refusal: "
                f"{execution_state!r}"
            )
        return "refused-before-start"
    terminal = str(terminal_outcome).strip().lower()
    if state is not None and state != terminal:
        raise ValueError(
            f"terminal {terminal!r} contradicts execution state {state!r}"
        )
    mapping = {
        "completed": "completed-before-quarantine",
        "cancelled": "cancelled",
        "failed": "failed",
    }
    if terminal not in mapping:
        raise ValueError(f"unmappable terminal outcome: {terminal_outcome!r}")
    return mapping[terminal]


def report_runtime_fault_outcome(
    record_property: Callable[[str, str], Any],
    *,
    terminal_outcome: str | None,
    execution_state: str | None = None,
) -> str:
    """Record the derived outcome so the collector can read it out of JUnit XML.

    The pytest node is the executor of the deterministic-fixture column. Like a
    Linux-host executor, it reports what it observed; the collector cross-checks
    that report against the catalog instead of assuming it.
    """

    outcome = derive_terminal_outcome(
        terminal_outcome=terminal_outcome, execution_state=execution_state
    )
    record_property(_OUTCOME_PROPERTY, outcome)
    return outcome


@dataclass(frozen=True)
class PytestInvocation:
    """Bounded, untrusted result of running exactly one pytest node id."""

    exit_code: int
    stdout: str
    junit_xml: str = ""
    timed_out: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.exit_code, int) or isinstance(self.exit_code, bool):
            raise ValueError("exit_code must be an integer")
        if not isinstance(self.stdout, str):
            raise ValueError("stdout must be text")
        if not isinstance(self.junit_xml, str):
            raise ValueError("junit_xml must be text")
        if not isinstance(self.timed_out, bool):
            raise ValueError("timed_out must be boolean")
        if len(self.junit_xml.encode("utf-8")) > _MAX_JUNIT_BYTES:
            raise ValueError("junit_xml exceeds four MiB")
        object.__setattr__(self, "stdout", self.stdout[-_MAX_STDOUT_CHARS:])


@dataclass(frozen=True)
class PytestNodeReport:
    """One ``<testcase>`` element, reduced to what the collector may rely on."""

    name: str
    verdict: str
    properties: Mapping[str, str]

    @property
    def reported_outcome(self) -> str | None:
        return self.properties.get(_OUTCOME_PROPERTY)


FixturePytestRunner = Callable[[str], PytestInvocation]


def parse_pytest_junit(xml_text: str) -> tuple[PytestNodeReport, ...]:
    """Reduce a JUnit document to per-testcase verdicts and properties.

    The document is produced by this collector's own subprocess into a private
    temporary file, but it is still parsed defensively: oversized input is
    rejected and any structural surprise raises rather than being guessed at.
    """

    if not isinstance(xml_text, str):
        raise ValueError("junit xml must be text")
    if len(xml_text.encode("utf-8")) > _MAX_JUNIT_BYTES:
        raise ValueError("junit xml exceeds four MiB")
    if not xml_text.strip():
        return ()
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise ValueError(f"junit xml is malformed: {exc}") from exc

    reports: list[PytestNodeReport] = []
    for case in root.iter("testcase"):
        verdict = "passed"
        if case.find("error") is not None:
            verdict = "error"
        elif case.find("failure") is not None:
            verdict = "failed"
        elif case.find("skipped") is not None:
            verdict = "skipped"
        properties: dict[str, str] = {}
        for prop in case.iter("property"):
            name = prop.get("name")
            value = prop.get("value")
            if isinstance(name, str) and isinstance(value, str):
                properties[name] = value
        reports.append(
            PytestNodeReport(
                name=case.get("name") or "",
                verdict=verdict,
                properties=properties,
            )
        )
    return tuple(reports)


@dataclass(frozen=True)
class FixtureFaultResult:
    """Bounded classification of one pytest run before evidence is materialized."""

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
                raise ValueError("passed fixture fault results require observed_outcome")
            if self.detail_code is not None:
                raise ValueError("passed fixture fault results must not carry detail_code")
        elif self.status == "blocked":
            if self.observed_outcome is not None:
                raise ValueError(
                    "blocked fixture fault results must not invent observed_outcome"
                )
            object.__setattr__(
                self, "detail_code", _identifier(self.detail_code, "detail_code")
            )
        else:
            object.__setattr__(
                self, "detail_code", _identifier(self.detail_code, "detail_code")
            )
        object.__setattr__(self, "raw_evidence", _raw_evidence(self.raw_evidence))
        object.__setattr__(self, "facts", _facts(self.facts, "fixture fault result facts"))


@dataclass(frozen=True)
class FixtureFaultEvidence:
    """Canonical collector artifact for one exact deterministic-fixture scenario."""

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
                raise ValueError("passed fixture fault evidence requires observed_outcome")
            if self.detail_code is not None:
                raise ValueError("passed fixture fault evidence must not carry detail_code")
        elif self.status == "blocked":
            if self.observed_outcome is not None:
                raise ValueError(
                    "blocked fixture fault evidence must not invent observed_outcome"
                )
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
        object.__setattr__(self, "facts", _facts(self.facts, "fixture fault evidence facts"))

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
    def from_dict(cls, payload: Mapping[str, Any]) -> "FixtureFaultEvidence":
        body = _strict_payload(payload, cls, "fixture fault evidence")
        body["facts"] = tuple(
            HostFaultFact.from_dict(row) for row in _sequence(body["facts"], "facts")
        )
        return cls(**body)


def load_fixture_fault_evidence_json(text: str) -> FixtureFaultEvidence:
    """Parse one untrusted evidence document without JSON ambiguity."""

    if not isinstance(text, str):
        raise ValueError("fixture fault evidence JSON must be text")
    if len(text.encode("utf-8")) > _MAX_WIRE_BYTES:
        raise ValueError("fixture fault evidence JSON exceeds two MiB")
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_object_pairs_no_duplicates,
            parse_constant=_reject_json_constant,
        )
    except json.JSONDecodeError as exc:
        raise ValueError("fixture fault evidence JSON is malformed") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("fixture fault evidence JSON root must be an object")
    return FixtureFaultEvidence.from_dict(payload)


@dataclass(frozen=True)
class FixtureFaultRun:
    """One evidence artifact, retained raw bytes, and exact observation."""

    evidence: FixtureFaultEvidence
    observation: RuntimeFaultObservation
    raw_evidence: bytes = field(repr=False)

    def __post_init__(self) -> None:
        retained = _raw_evidence(self.raw_evidence)
        if hashlib.sha256(retained).hexdigest() != self.evidence.raw_evidence_sha256:
            raise FixtureFaultBindingMismatch(
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
            raise FixtureFaultBindingMismatch(
                "fixture fault run binding mismatch: " + ", ".join(mismatches)
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence": self.evidence.to_dict(),
            "observation": self.observation.to_dict(),
        }

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


def _result(
    scenario: RuntimeFaultScenario,
    node_id: str,
    invocation: PytestInvocation | None,
    *,
    status: str,
    observed_outcome: str | None,
    detail_code: str | None,
    facts: Mapping[str, str],
) -> FixtureFaultResult:
    payload: dict[str, Any] = {
        "schema": _SCHEMA,
        "scenario_id": scenario.scenario_id,
        "scenario_sha256": scenario.digest,
        "node_id": node_id,
        "status": status,
        "observed_outcome": observed_outcome,
        "detail_code": detail_code,
        "facts": dict(sorted(facts.items())),
    }
    if invocation is not None:
        payload["pytest"] = {
            "exit_code": invocation.exit_code,
            "timed_out": invocation.timed_out,
            "stdout_tail": invocation.stdout,
        }
    return FixtureFaultResult(
        status=status,
        observed_outcome=observed_outcome,
        detail_code=detail_code,
        raw_evidence=canonical_json(payload).encode("utf-8"),
        facts=tuple(HostFaultFact(name, value) for name, value in sorted(facts.items())),
    )


def classify_pytest_invocation(
    scenario: RuntimeFaultScenario,
    node_id: str,
    invocation: PytestInvocation,
) -> FixtureFaultResult:
    """Map one bounded pytest run onto a fail-closed fixture fault result.

    ``passed`` requires all of: the process exited zero, exactly one matching
    testcase ran, it did not fail/error/skip, it reported an outcome, and that
    reported outcome equals the outcome the catalog requires. Everything the
    harness could not actually determine becomes ``blocked``; only a genuine
    assertion failure becomes ``failed``.
    """

    if not isinstance(invocation, PytestInvocation):
        return _result(
            scenario,
            node_id,
            None,
            status="blocked",
            observed_outcome=None,
            detail_code="runner-contract",
            facts={"result-type": type(invocation).__name__},
        )
    if invocation.timed_out:
        return _result(
            scenario,
            node_id,
            invocation,
            status="blocked",
            observed_outcome=None,
            detail_code="execution-timeout",
            facts={"pytest-exit-code": str(invocation.exit_code)},
        )

    try:
        reports = parse_pytest_junit(invocation.junit_xml)
    except ValueError as exc:
        return _result(
            scenario,
            node_id,
            invocation,
            status="blocked",
            observed_outcome=None,
            detail_code="junit-unreadable",
            facts={"parse-error": type(exc).__name__},
        )

    if invocation.exit_code == 5 or not reports:
        # No test was collected at all. The declared node id does not resolve at
        # this revision; that is a stale catalog locator, not a red invariant.
        return _result(
            scenario,
            node_id,
            invocation,
            status="blocked",
            observed_outcome=None,
            detail_code="node-missing",
            facts={
                "pytest-exit-code": str(invocation.exit_code),
                "collected-testcases": "0",
            },
        )
    if len(reports) > 1:
        return _result(
            scenario,
            node_id,
            invocation,
            status="blocked",
            observed_outcome=None,
            detail_code="node-ambiguous",
            facts={"collected-testcases": str(len(reports))},
        )

    report = reports[0]
    if report.verdict == "error":
        # Import errors, syntax errors and fixture errors. The invariant was
        # never exercised, so this is explicitly not a failing test.
        return _result(
            scenario,
            node_id,
            invocation,
            status="blocked",
            observed_outcome=None,
            detail_code="collection-error",
            facts={
                "pytest-exit-code": str(invocation.exit_code),
                "testcase-verdict": report.verdict,
            },
        )
    if report.verdict == "skipped":
        return _result(
            scenario,
            node_id,
            invocation,
            status="blocked",
            observed_outcome=None,
            detail_code="test-skipped",
            facts={"pytest-exit-code": str(invocation.exit_code)},
        )
    if report.verdict == "failed":
        # A node that ran and failed its assertions. The outcome is genuinely
        # unknown, so none is claimed.
        return _result(
            scenario,
            node_id,
            invocation,
            status="failed",
            observed_outcome=None,
            detail_code="assertion-failed",
            facts={"pytest-exit-code": str(invocation.exit_code)},
        )
    if invocation.exit_code != 0:
        # A green testcase inside a non-zero session: teardown errors, internal
        # errors, or a session-level abort. Fail closed rather than pick one.
        return _result(
            scenario,
            node_id,
            invocation,
            status="blocked",
            observed_outcome=None,
            detail_code="session-not-clean",
            facts={"pytest-exit-code": str(invocation.exit_code)},
        )

    reported = report.reported_outcome
    if reported is None:
        return _result(
            scenario,
            node_id,
            invocation,
            status="blocked",
            observed_outcome=None,
            detail_code="outcome-unreported",
            facts={"expected-outcome-property": _OUTCOME_PROPERTY},
        )
    if reported not in _OUTCOMES:
        return _result(
            scenario,
            node_id,
            invocation,
            status="blocked",
            observed_outcome=None,
            detail_code="outcome-uninterpretable",
            facts={"reported-outcome": reported[:200]},
        )
    if reported != scenario.expected_outcome:
        return _result(
            scenario,
            node_id,
            invocation,
            status="failed",
            observed_outcome=reported,
            detail_code="outcome-mismatch",
            facts={
                "collector-expected-outcome": scenario.expected_outcome,
                "collector-reported-outcome": reported,
            },
        )
    return _result(
        scenario,
        node_id,
        invocation,
        status="passed",
        observed_outcome=reported,
        detail_code=None,
        facts={"collector-reported-outcome": reported},
    )


def _executor_sha256(node_id: str, repo_root: Path) -> str:
    """Bind evidence to the exact test source that produced it."""

    relative = node_id.split("::", 1)[0]
    candidate = Path(repo_root) / relative
    try:
        if candidate.is_file() and not candidate.is_symlink():
            return hashlib.sha256(candidate.read_bytes()).hexdigest()
    except OSError:
        pass
    return hashlib.sha256(("missing-executor\0" + node_id).encode("utf-8")).hexdigest()


def subprocess_pytest_runner(
    *,
    repo_root: Path,
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
) -> FixturePytestRunner:
    """Return a runner that executes one node id in its own pytest process.

    Each node runs alone so that one row's crash cannot contaminate another
    row's verdict, and so that a session-level abort is attributable.
    """

    root = Path(repo_root)
    if not root.is_dir():
        raise FixtureFaultCollectorError(f"repo root must be a directory: {root}")
    if not isinstance(timeout_seconds, int) or timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be a positive integer")

    def run(node_id: str) -> PytestInvocation:
        with tempfile.TemporaryDirectory(prefix="daedalus-fixture-fault-") as scratch:
            report = Path(scratch) / "report.xml"
            environment = dict(os.environ)
            environment["PYTHONUTF8"] = "1"
            environment["PYTHONIOENCODING"] = "utf-8"
            command = [
                sys.executable,
                "-m",
                "pytest",
                node_id,
                "-q",
                "-p",
                "no:randomly",
                "--junit-xml",
                str(report),
                "-o",
                "junit_family=xunit1",
            ]
            try:
                completed = subprocess.run(
                    command,
                    cwd=str(root),
                    env=environment,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return PytestInvocation(
                    exit_code=-1,
                    stdout=f"pytest exceeded {timeout_seconds}s for {node_id}",
                    junit_xml="",
                    timed_out=True,
                )
            xml_text = ""
            if report.is_file():
                raw = report.read_bytes()
                if len(raw) <= _MAX_JUNIT_BYTES:
                    xml_text = raw.decode("utf-8", errors="replace")
            return PytestInvocation(
                exit_code=completed.returncode,
                stdout=(completed.stdout or "") + (completed.stderr or ""),
                junit_xml=xml_text,
                timed_out=False,
            )

    return run


def run_fixture_fault(
    scenario: RuntimeFaultScenario,
    *,
    source_revision: str,
    runner: FixturePytestRunner,
    repo_root: Path,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> FixtureFaultRun:
    """Execute or explicitly block one exact deterministic-fixture catalog row."""

    revision = _revision(source_revision)
    node_id = scenario_node_id(scenario)
    if not callable(runner):
        raise FixtureFaultBindingMismatch("runner must be callable")

    started = _clock_value(clock, "started_at")
    try:
        invocation = runner(node_id)
    except Exception as exc:  # the runner itself broke, not the invariant
        result = _result(
            scenario,
            node_id,
            None,
            status="blocked",
            observed_outcome=None,
            detail_code="runner-error",
            facts={"exception-type": type(exc).__name__},
        )
    else:
        result = classify_pytest_invocation(scenario, node_id, invocation)
    finished = _clock_value(clock, "finished_at")
    if finished < started:
        raise FixtureFaultClockError("collector clock moved backwards")

    evidence = FixtureFaultEvidence(
        schema=_SCHEMA,
        scenario_id=scenario.scenario_id,
        scenario_sha256=scenario.digest,
        source_revision=revision,
        executor=scenario.executor,
        executor_sha256=_executor_sha256(node_id, repo_root),
        started_at=started.isoformat(timespec="microseconds"),
        finished_at=finished.isoformat(timespec="microseconds"),
        status=result.status,
        observed_outcome=result.observed_outcome,
        detail_code=result.detail_code,
        raw_evidence_sha256=hashlib.sha256(result.raw_evidence).hexdigest(),
        facts=result.facts,
    )
    provenance = ContractProvenance(
        origin="daedalus.runtimes.fixture_fault_collector",
        source_revision=revision,
        created_at=evidence.finished_at,
        input_digests=tuple(sorted((scenario.digest, evidence.digest))),
        trace_id=scenario.scenario_id,
    )
    observation = RuntimeFaultObservation(
        observation_id="fixture-" + evidence.digest[:24],
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
    return FixtureFaultRun(
        evidence=evidence, observation=observation, raw_evidence=result.raw_evidence
    )


def run_fixture_fault_catalog(
    *,
    catalog: RuntimeFaultCatalog,
    source_revision: str,
    runner: FixturePytestRunner,
    repo_root: Path,
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
) -> tuple[FixtureFaultRun, ...]:
    """Run every deterministic-fixture row, one isolated pytest process each."""

    scenarios = tuple(row for row in catalog.scenarios if row.authority == _AUTHORITY)
    if not scenarios:
        raise FixtureFaultBindingMismatch(
            f"runtime fault catalog contains no {_AUTHORITY} scenarios"
        )
    return tuple(
        run_fixture_fault(
            scenario,
            source_revision=source_revision,
            runner=runner,
            repo_root=repo_root,
            clock=clock,
        )
        for scenario in scenarios
    )


def retain_fixture_fault_run(directory: Path, run: FixtureFaultRun) -> None:
    """Write one artifact triple in the layout the issuer expects."""

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
    """Collect the deterministic-fixture column and retain its evidence.

    This entrypoint produces evidence and nothing else. It holds no signing key
    and cannot place an observation into a trust set; that is the separate
    ``fixture-fault-attestation`` operator step. Keeping the two apart is what
    makes "a candidate can write evidence" different from "a candidate can
    write trust".
    """

    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Run every deterministic-fixture runtime fault row in its own pytest "
            "process and retain bounded, content-addressed evidence. Produces no "
            "signatures and grants no trust."
        )
    )
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--timeout-seconds", type=int, default=_DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args(argv)

    from daedalus.runtimes.fault_matrix import RUNTIME_FAULT_CATALOG

    runs = run_fixture_fault_catalog(
        catalog=RUNTIME_FAULT_CATALOG,
        source_revision=args.source_revision,
        runner=subprocess_pytest_runner(
            repo_root=args.repo_root, timeout_seconds=args.timeout_seconds
        ),
        repo_root=args.repo_root,
    )
    for run in runs:
        retain_fixture_fault_run(args.run_dir, run)
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
            }
            for row in runs
        ],
    }
    print(canonical_json(summary))
    # Exit non-zero when anything did not cleanly pass. Retaining the evidence
    # is still the point, so the artifacts are written either way.
    return 0 if summary["passed"] == summary["collected"] else 1


__all__ = [
    "FixtureFaultBindingMismatch",
    "FixtureFaultClockError",
    "FixtureFaultCollectorError",
    "FixtureFaultEvidence",
    "FixtureFaultResult",
    "FixtureFaultRun",
    "FixturePytestRunner",
    "PytestInvocation",
    "PytestNodeReport",
    "classify_pytest_invocation",
    "derive_terminal_outcome",
    "load_fixture_fault_evidence_json",
    "main",
    "parse_pytest_junit",
    "retain_fixture_fault_run",
    "report_runtime_fault_outcome",
    "run_fixture_fault",
    "run_fixture_fault_catalog",
    "scenario_node_id",
    "subprocess_pytest_runner",
]


if __name__ == "__main__":
    raise SystemExit(main())
