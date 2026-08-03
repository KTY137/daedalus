"""Vendor-neutral runtime conformance harness for Gate 0.

The harness observes an injected runtime adapter session. It does not spawn a
runtime itself, trust manifest prose, or accept an LLM review as evidence.
Concrete subprocess/API fixtures live outside the production package until they
are registered and leased effect boundaries.
"""
from __future__ import annotations

import math
import os
import tempfile
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from daedalus.schemas import (
    ConformanceCheck,
    ContractProvenance,
    ResourceUsage,
    RuntimeConformanceReceipt,
    RuntimeManifest,
    _freeze_json,
    _identifier,
    _locator_sha256,
    _non_empty,
)
from daedalus.spine.envelope import canonical_json


EvidenceWriter = Callable[[bytes], str]
Clock = Callable[[], datetime]


class RuntimeConformanceError(RuntimeError):
    """Base class for conformance harness failures."""


class RuntimeBindingError(RuntimeConformanceError):
    """The adapter, manifest, or expected revision do not describe one runtime."""


class RuntimeEvidenceError(RuntimeConformanceError):
    """The evidence writer did not retain the exact canonical evidence bytes."""


class RuntimeProbeTimeout(RuntimeConformanceError):
    """A probe exceeded its enforced wall-time bound and was terminated."""


@dataclass(frozen=True)
class RuntimeProbeRequest:
    run_id: str
    runtime_id: str
    mode: str
    workspace: Path
    outside_canary: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "run_id", _identifier(self.run_id, "run_id"))
        object.__setattr__(
            self, "runtime_id", _identifier(self.runtime_id, "runtime_id")
        )
        if self.mode not in {"normal", "hang"}:
            raise ValueError("runtime probe mode must be normal or hang")
        workspace = Path(self.workspace).resolve(strict=True)
        outside_canary = Path(self.outside_canary).resolve(strict=True)
        if not workspace.is_dir():
            raise ValueError("runtime probe workspace must be a directory")
        if (
            workspace == outside_canary
            or workspace in outside_canary.parents
            or outside_canary in workspace.parents
        ):
            raise ValueError("outside canary must not be inside the runtime workspace")
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "outside_canary", outside_canary)


@dataclass(frozen=True)
class RuntimeProbeEvent:
    kind: str
    sequence: int
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _identifier(self.kind, "event.kind"))
        if (
            isinstance(self.sequence, bool)
            or not isinstance(self.sequence, int)
            or self.sequence < 0
        ):
            raise ValueError("event.sequence must be a non-negative integer")
        object.__setattr__(
            self,
            "payload",
            _freeze_json(self.payload, "event.payload"),
        )


class RuntimeProbeSession(Protocol):
    """One started runtime instance under adapter-controlled process/API I/O."""

    @property
    def running(self) -> bool: ...

    @property
    def exit_code(self) -> int | None: ...

    @property
    def parse_errors(self) -> tuple[str, ...]: ...

    def events(self) -> tuple[RuntimeProbeEvent, ...]: ...

    def wait(self, timeout_s: float) -> int:
        """Wait or terminate and raise RuntimeProbeTimeout at the hard bound."""
        ...

    def cancel(self, grace_s: float = 1.0) -> int:
        """Stop the runtime and return only after it is no longer running."""
        ...


class RuntimeFixtureAdapter(Protocol):
    """Adapter surface tested by the conformance harness."""

    runtime_id: str

    def start(self, request: RuntimeProbeRequest) -> RuntimeProbeSession: ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("conformance clock must return timezone-aware datetimes")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


def _event_shape(events: Sequence[RuntimeProbeEvent]) -> tuple[str, ...]:
    return tuple(event.kind for event in events)


def _valid_event_order(events: Sequence[RuntimeProbeEvent]) -> bool:
    sequences = [event.sequence for event in events]
    return sequences == list(range(len(sequences)))


def _wait_for_kind(
    session: RuntimeProbeSession,
    kind: str,
    *,
    timeout_s: float,
) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if any(event.kind == kind for event in session.events()):
            return True
        if not session.running:
            return False
        time.sleep(0.01)
    return False


def run_runtime_conformance(
    manifest: RuntimeManifest,
    adapter: RuntimeFixtureAdapter,
    *,
    evidence_writer: EvidenceWriter,
    receipt_id: str,
    expected_source_revision: str,
    workspace_parent: str | os.PathLike[str] | None = None,
    clock: Clock = _utc_now,
    normal_timeout_s: float = 3.0,
    timeout_probe_s: float = 0.1,
    cancellation_grace_s: float = 1.0,
) -> RuntimeConformanceReceipt:
    """Run the exact Gate-0 fixture matrix and emit a canonical receipt.

    The caller supplies a content-addressed evidence writer. The harness verifies
    that every returned locator addresses the exact bytes it supplied. Adapter
    sessions, not this module, own subprocess/API effects and must already be
    routed through the applicable effect boundary in production.
    """

    normalized_receipt_id = _identifier(receipt_id, "receipt_id")
    if manifest.runtime_id != adapter.runtime_id:
        raise RuntimeBindingError("runtime manifest does not match adapter runtime_id")
    if manifest.source_revision != expected_source_revision:
        raise RuntimeBindingError("runtime manifest is stale for the expected revision")
    for name, value in (
        ("normal_timeout_s", normal_timeout_s),
        ("timeout_probe_s", timeout_probe_s),
        ("cancellation_grace_s", cancellation_grace_s),
    ):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value <= 0
        ):
            raise ValueError(f"{name} must be a finite positive number")

    parent = Path(workspace_parent) if workspace_parent is not None else None
    if parent is not None:
        parent = parent.resolve(strict=True)
        if not parent.is_dir():
            raise ValueError("workspace_parent must be an existing directory")

    started_at = clock()
    started_at_text = _iso(started_at)
    checks: list[ConformanceCheck] = []

    def retain(
        name: str,
        passed: bool,
        detail: str,
        observations: Mapping[str, Any],
    ) -> None:
        normalized_detail = _non_empty(detail, f"{name}.detail", max_length=2000)
        evidence = {
            "schema": "daedalus-runtime-conformance-evidence/1",
            "runtime_manifest_sha256": manifest.digest,
            "runtime_id": manifest.runtime_id,
            "source_revision": manifest.source_revision,
            "check": name,
            "passed": bool(passed),
            "observations": observations,
        }
        payload = canonical_json(evidence).encode("utf-8")
        digest = sha256(payload).hexdigest()
        locator = evidence_writer(payload)
        try:
            addressed = _locator_sha256(locator)
        except ValueError as exc:
            raise RuntimeEvidenceError(
                f"evidence writer returned an invalid locator for {name}"
            ) from exc
        if addressed != digest:
            raise RuntimeEvidenceError(
                f"evidence writer returned the wrong content address for {name}"
            )
        checks.append(
            ConformanceCheck(
                name=name,
                passed=bool(passed),
                evidence_sha256=digest,
                evidence_locator=locator,
                detail=normalized_detail,
            )
        )

    with tempfile.TemporaryDirectory(prefix="daedalus-runtime-", dir=parent) as root_text:
        root = Path(root_text)
        workspace = root / "workspace"
        workspace.mkdir()
        canary = root / "outside-canary.txt"
        canary.write_text("unchanged\n", encoding="utf-8")
        canary_before = canary.read_bytes()

        normal_events: tuple[RuntimeProbeEvent, ...] = ()
        normal_exit: int | None = None
        normal_errors: tuple[str, ...] = ()
        normal_exception = ""
        normal_session: RuntimeProbeSession | None = None
        try:
            normal_session = adapter.start(
                RuntimeProbeRequest(
                    run_id=f"{normalized_receipt_id}-normal",
                    runtime_id=manifest.runtime_id,
                    mode="normal",
                    workspace=workspace,
                    outside_canary=canary,
                )
            )
            normal_exit = normal_session.wait(normal_timeout_s)
            normal_events = normal_session.events()
            normal_errors = normal_session.parse_errors
        except Exception as exc:
            normal_exception = type(exc).__name__
            if normal_session is not None and normal_session.running:
                normal_session.cancel()

        event_order_ok = _valid_event_order(normal_events)
        shapes = _event_shape(normal_events)
        started_events = [event for event in normal_events if event.kind == "started"]
        finished_events = [event for event in normal_events if event.kind == "finished"]
        lifecycle_ok = (
            len(started_events) == 1
            and normal_events
            and normal_events[0].kind == "started"
            and len(finished_events) == 1
            and normal_events[-1].kind == "finished"
            and finished_events[0].payload.get("status") == "passed"
        )
        retain(
            "start",
            lifecycle_ok and normal_exit == 0 and event_order_ok and not normal_errors,
            "runtime starts once, emits a contiguous parseable lifecycle, and exits successfully",
            {
                "lifecycle_ok": lifecycle_ok,
                "started_count": len(started_events),
                "finished_count": len(finished_events),
                "exit_code": normal_exit,
                "event_order_ok": event_order_ok,
                "parse_error_count": len(normal_errors),
                "exception": normal_exception,
                "event_shape": shapes,
            },
        )

        stream_events = [event for event in normal_events if event.kind == "stream.delta"]
        stream_text = stream_events[0].payload.get("text") if stream_events else None
        retain(
            "stream",
            manifest.capabilities.streaming
            and len(stream_events) == 1
            and stream_text == "fixture",
            "declared streaming produces the expected provider-neutral delta",
            {
                "declared": manifest.capabilities.streaming,
                "count": len(stream_events),
                "text": stream_text,
            },
        )

        tool_started = [event for event in normal_events if event.kind == "tool.started"]
        tool_finished = [event for event in normal_events if event.kind == "tool.finished"]
        started_tool = tool_started[0].payload.get("tool") if tool_started else None
        finished_tool = tool_finished[0].payload.get("tool") if tool_finished else None
        paired = (
            len(tool_started) == 1
            and len(tool_finished) == 1
            and tool_started[0].sequence < tool_finished[0].sequence
            and tool_started[0].payload.get("call_id")
            == tool_finished[0].payload.get("call_id")
            and started_tool == finished_tool
            and started_tool in manifest.declared_tools
            and tool_finished[0].payload.get("status") == "ok"
        )
        retain(
            "tool-events",
            manifest.capabilities.tool_events and paired,
            "declared tools expose ordered, paired provider-neutral start/finish events",
            {
                "declared": manifest.capabilities.tool_events,
                "started_count": len(tool_started),
                "finished_count": len(tool_finished),
                "tool_declared": started_tool in manifest.declared_tools,
                "paired": paired,
            },
        )

        structured = [
            event for event in normal_events if event.kind == "structured-output"
        ]
        structured_value = structured[0].payload.get("value") if structured else None
        retain(
            "structured-output",
            manifest.capabilities.structured_output
            and len(structured) == 1
            and structured_value == {"ok": True, "value": "fixture"},
            "declared structured output is parsed as the exact expected object",
            {
                "declared": manifest.capabilities.structured_output,
                "count": len(structured),
                "value": structured_value,
            },
        )

        usage_events = [event for event in normal_events if event.kind == "usage"]
        usage = ResourceUsage()
        usage_valid = False
        if len(usage_events) == 1:
            try:
                usage = ResourceUsage.from_dict(dict(usage_events[0].payload))
                usage_valid = True
            except (TypeError, ValueError):
                usage_valid = False
        retain(
            "cost",
            manifest.capabilities.cost_reporting and usage_valid,
            "declared cost reporting emits validated integer resource usage",
            {
                "declared": manifest.capabilities.cost_reporting,
                "count": len(usage_events),
                "valid": usage_valid,
                "cost_microusd": usage.cost_microusd if usage_valid else None,
            },
        )

        timeout_passed = False
        timeout_dead = False
        timeout_error = ""
        timeout_session: RuntimeProbeSession | None = None
        try:
            timeout_session = adapter.start(
                RuntimeProbeRequest(
                    run_id=f"{normalized_receipt_id}-timeout",
                    runtime_id=manifest.runtime_id,
                    mode="hang",
                    workspace=workspace,
                    outside_canary=canary,
                )
            )
            try:
                timeout_session.wait(timeout_probe_s)
            except RuntimeProbeTimeout:
                timeout_passed = True
            timeout_dead = not timeout_session.running
        except Exception as exc:
            timeout_error = type(exc).__name__
            if timeout_session is not None and timeout_session.running:
                timeout_session.cancel()
        retain(
            "timeout",
            manifest.capabilities.timeout and timeout_passed and timeout_dead,
            "declared timeout terminates a hung runtime within the outer bound",
            {
                "declared": manifest.capabilities.timeout,
                "timeout_raised": timeout_passed,
                "process_dead": timeout_dead,
                "exception": timeout_error,
            },
        )

        cancellation_started = False
        cancellation_dead = False
        cancellation_error = ""
        cancellation_session: RuntimeProbeSession | None = None
        try:
            cancellation_session = adapter.start(
                RuntimeProbeRequest(
                    run_id=f"{normalized_receipt_id}-cancel",
                    runtime_id=manifest.runtime_id,
                    mode="hang",
                    workspace=workspace,
                    outside_canary=canary,
                )
            )
            cancellation_started = _wait_for_kind(
                cancellation_session, "started", timeout_s=1.0
            )
            cancellation_session.cancel(cancellation_grace_s)
            cancellation_dead = not cancellation_session.running
        except Exception as exc:
            cancellation_error = type(exc).__name__
            if cancellation_session is not None and cancellation_session.running:
                cancellation_session.cancel()
        retain(
            "cancellation",
            manifest.capabilities.cancellation
            and cancellation_started
            and cancellation_dead,
            "declared cancellation stops an already-started runtime process",
            {
                "declared": manifest.capabilities.cancellation,
                "started": cancellation_started,
                "process_dead": cancellation_dead,
                "exception": cancellation_error,
            },
        )

        output = workspace / "fixture-output.txt"
        outside_unchanged = canary.is_file() and canary.read_bytes() == canary_before
        retain(
            "workspace-isolation",
            manifest.capabilities.workspace_isolation
            and manifest.capabilities.workspace_write
            and "isolated-worktree" in manifest.workspace_modes
            and output.is_file()
            and output.read_text(encoding="utf-8") == "fixture\n"
            and outside_unchanged,
            "all fixture phases remain in the declared workspace and preserve an outside canary",
            {
                "declared_isolation": manifest.capabilities.workspace_isolation,
                "declared_write": manifest.capabilities.workspace_write,
                "inside_output": output.is_file(),
                "outside_canary_unchanged": outside_unchanged,
            },
        )

    finished_at = clock()
    finished_at_text = _iso(finished_at)
    status = "passed" if all(check.passed for check in checks) else "failed"
    evidence_digests = tuple(check.evidence_sha256 for check in checks)
    provenance = ContractProvenance(
        origin="runtime-conformance-harness",
        source_revision=manifest.source_revision,
        created_at=finished_at_text,
        input_digests=tuple(sorted({manifest.digest, *evidence_digests})),
        trace_id=normalized_receipt_id,
    )
    return RuntimeConformanceReceipt(
        receipt_id=normalized_receipt_id,
        runtime_manifest_sha256=manifest.digest,
        source_revision=manifest.source_revision,
        status=status,
        checks=tuple(checks),
        started_at=started_at_text,
        finished_at=finished_at_text,
        usage=usage,
        provenance=provenance,
    )


__all__ = [
    "EvidenceWriter",
    "RuntimeBindingError",
    "RuntimeConformanceError",
    "RuntimeEvidenceError",
    "RuntimeFixtureAdapter",
    "RuntimeProbeEvent",
    "RuntimeProbeRequest",
    "RuntimeProbeSession",
    "RuntimeProbeTimeout",
    "run_runtime_conformance",
]
