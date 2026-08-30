"""Admitted, bounded execution receipts for local EDA commands.

Dry-run planning is effect free. Every live command consumes a caller-issued
``NonRuntimeEffectAuthorization`` and one exact ``EffectExecutionRequest``;
this module never issues a lease or invents a policy decision. The durable
effect start precedes executable discovery and ``ManagedProcess`` construction,
exact replay is inert, and known process outcomes receive exactly one terminal
receipt.

Console captures, declared native outputs, and the pre-terminal execution
receipt are retained in the existing content-addressed ``ArtifactStore``. If a
process has run but that evidence cannot be made durable, the execution stays
``STARTED`` for reconciliation. ``KeyboardInterrupt`` and ``SystemExit`` also
stay pending: the managed context reaps the tree, but an interrupted caller
cannot prove how far the EDA tool progressed.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import stat
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Callable, Mapping, Sequence

from daedalus.kernel.authorization import NonRuntimeEffectAuthorization
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
)
from daedalus.schemas import ContractProvenance
from daedalus.spine.cancel import ManagedProcess
from daedalus.spine.effect_boundary import Effect
from daedalus.spine.envelope import canonical_json, canonical_sha, current_trace_id
from daedalus.storage import ArtifactLocator, ArtifactStore

from .execution_plan import (
    EdaExecutionPlan,
    sanitized_eda_environment,
    trusted_windows_command_interpreter,
)
from .manifest import (
    VivadoProjectManifest,
    build_vivado_project_manifest,
    canonical_path_identity,
)
from .toolchains import (
    is_trusted_vendor_tool_path,
    trusted_launcher_sha256,
)
from .vivado_tcl import (
    build_vivado_flow_argv,
    expected_vivado_output_paths,
    trusted_vivado_tcl,
)


_MAX_CAPTURE_CHARS = 128_000
_TRUNCATION_MARKER = "\n\n... [Daedalus truncated EDA output] ...\n\n"
_ENTRYPOINT_ID = "cli.daedalus_chip"
_REQUIRED_EFFECTS = frozenset(
    {
        Effect.FILESYSTEM_WRITE.value,
        Effect.PROCESS_CONTROL.value,
        Effect.PROCESS_SPAWN.value,
    }
)
_RECEIPT_SCHEMA = "daedalus.eda-execution-receipt/2"
_POLL_INTERVAL_S = 0.05
_UNKNOWN_ABORTS = (KeyboardInterrupt, SystemExit)
_TERMINAL_EXECUTION_STATES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
_CMD_META = frozenset('"%!^&|<>()\r\n')
_RECEIPT_FIELDS = frozenset(
    {
        "schema",
        "execution_id",
        "execution_request_sha256",
        "operation_sha256",
        "execution_plan",
        "effect_start_receipt",
        "argv",
        "cwd",
        "status",
        "returncode",
        "duration_s",
        "process_spawned",
        "intended_effect_terminal_outcome",
        "stdout_sha256",
        "stdout_locator",
        "stderr_sha256",
        "stderr_locator",
        "artifacts",
        "missing_artifact_paths",
        "pre_workspace_manifest_sha256",
        "pre_workspace_source_identity_sha256",
        "pre_workspace_manifest_locator",
        "pre_authoritative_manifest_sha256",
        "pre_authoritative_source_identity_sha256",
        "pre_authoritative_manifest_locator",
        "trusted_tcl_sha256",
        "trusted_tcl_locator",
        "post_workspace_manifest_sha256",
        "post_source_identity_sha256",
        "post_workspace_manifest_locator",
        "post_authoritative_manifest_sha256",
        "post_authoritative_source_identity_sha256",
        "post_authoritative_manifest_locator",
        "observed_at",
        "security_boundary_claimed",
    }
)


class EdaExecutionError(RuntimeError):
    """Base class for the admitted local EDA boundary."""


class EdaExecutionAdmissionError(EdaExecutionError):
    """The caller did not supply the exact authority required for a live run."""


class EdaExecutionReconciliationRequired(EdaExecutionError):
    """A started execution needs authenticated operator reconciliation.

    The exception deliberately carries both durable lifecycle identities and,
    when available, the already-retained CAS evidence.  A caller can therefore
    locate the exact ledger row without guessing from console text, while a
    failed terminal write never masquerades as a known ``FAILED`` execution.
    """

    def __init__(
        self,
        *,
        start_receipt: LeasedEffectStartReceipt,
        phase: str,
        cause_sha256: str,
        execution_id: str | None = None,
        execution_request_sha256: str | None = None,
        effect_ledger_path: str | None = None,
        evidence_locators: Sequence[str] = (),
    ) -> None:
        super().__init__(
            "EDA execution has no confirmed terminal receipt; authenticated "
            "reconciliation is required"
        )
        self.start_receipt = start_receipt
        self.phase = phase
        self.cause_sha256 = cause_sha256
        self.execution_id = execution_id or start_receipt.execution_id
        self.execution_request_sha256 = (
            execution_request_sha256 or start_receipt.execution_request_sha256
        )
        self.effect_ledger_path = effect_ledger_path
        self.start_receipt_locator = (
            f"effect-start:sha256:{start_receipt.receipt_sha256}"
        )
        if effect_ledger_path:
            self.execution_locator = (
                f"effect-ledger:{effect_ledger_path}#execution_id={self.execution_id}"
            )
        else:
            self.execution_locator = f"effect-execution:{self.execution_id}"
        self.evidence_locators = tuple(str(value) for value in evidence_locators)


class EdaExecutionStateError(EdaExecutionError):
    """The known process outcome could not receive its terminal receipt."""


@dataclass(frozen=True)
class ExecutionArtifact:
    """Portable identity of one declared native output retained in the CAS."""

    path: str
    sha256: str
    locator: str
    byte_length: int


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    argv: tuple[str, ...]
    cwd: str
    returncode: int | None
    duration_s: float
    stdout: str
    stderr: str
    truncated: bool = False
    executed: bool = False
    start_receipt: LeasedEffectStartReceipt | None = None
    terminal_receipt: EffectTerminalReceipt | None = None
    stdout_sha256: str | None = None
    stderr_sha256: str | None = None
    receipt_sha256: str | None = None
    stdout_locator: str | None = None
    stderr_locator: str | None = None
    receipt_locator: str | None = None
    pre_workspace_manifest_locator: str | None = None
    pre_authoritative_manifest_locator: str | None = None
    trusted_tcl_locator: str | None = None
    post_workspace_manifest_sha256: str | None = None
    post_source_identity_sha256: str | None = None
    post_workspace_manifest_locator: str | None = None
    post_authoritative_manifest_sha256: str | None = None
    post_authoritative_source_identity_sha256: str | None = None
    post_authoritative_manifest_locator: str | None = None
    artifacts: tuple[ExecutionArtifact, ...] = ()
    missing_artifact_paths: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    def artifact_for(self, relative_path: str | Path) -> ExecutionArtifact:
        """Return the retained CAS identity for one declared native output.

        Report parsers that still read a live workspace can compare their own
        input SHA-256 to this value.  The executor intentionally does not claim
        that a later live read is the same byte sequence merely because the
        path is the same.
        """

        key = Path(relative_path).as_posix()
        matches = tuple(artifact for artifact in self.artifacts if artifact.path == key)
        if len(matches) != 1:
            raise KeyError(f"no unique retained EDA artifact for {key!r}")
        return matches[0]


@dataclass(frozen=True)
class RetainedExecutionObservation:
    """Authenticated CAS reconstruction of one terminal EDA execution."""

    result: ExecutionResult
    plan: EdaExecutionPlan
    receipt_body: Mapping[str, Any]
    receipt_payload: bytes


@dataclass(frozen=True)
class _ProcessObservation:
    status: str
    returncode: int | None
    duration_s: float
    stdout: bytes
    stderr: bytes
    terminal_outcome: str
    process_spawned: bool


@dataclass(frozen=True)
class _NativeArtifactBytes:
    path: str
    payload: bytes
    sha256: str


@dataclass(frozen=True)
class _StoredObservation:
    stdout: ArtifactLocator
    stderr: ArtifactLocator
    receipt: ArtifactLocator
    artifacts: tuple[ExecutionArtifact, ...]
    pre_workspace_manifest: ArtifactLocator
    pre_authoritative_manifest: ArtifactLocator
    trusted_tcl: ArtifactLocator
    post_workspace_manifest: ArtifactLocator | None
    post_authoritative_manifest: ArtifactLocator | None


class _PostSpawnStateUnknown(RuntimeError):
    """Internal signal: containment started, but observation is incomplete."""

    def __init__(self, phase: str, cause: BaseException) -> None:
        super().__init__(f"post-spawn EDA state is unknown during {phase}")
        self.phase = phase
        self.cause = cause


def _bounded(text: str | bytes) -> tuple[str, bool]:
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    if len(text) <= _MAX_CAPTURE_CHARS:
        return text, False

    payload_chars = _MAX_CAPTURE_CHARS - len(_TRUNCATION_MARKER)
    if payload_chars < 0:  # defensive if the constants are changed later
        return _TRUNCATION_MARKER[:_MAX_CAPTURE_CHARS], True
    head_chars = payload_chars // 2
    tail_chars = payload_chars - head_chars
    tail = text[-tail_chars:] if tail_chars else ""
    return text[:head_chars] + _TRUNCATION_MARKER + tail, True


def _strict_canonical_json_object(payload: bytes, *, label: str) -> dict[str, Any]:
    """Decode one exact canonical JSON object, rejecting ambiguous JSON."""

    if not isinstance(payload, bytes):
        raise TypeError(f"{label} must be bytes")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"{label} contains duplicate key {key!r}")
            result[key] = value
        return result

    def nonfinite(value: str) -> None:
        raise ValueError(f"{label} contains non-finite number {value}")

    try:
        decoded = payload.decode("ascii")
        value = json.loads(
            decoded,
            object_pairs_hook=unique_object,
            parse_constant=nonfinite,
        )
    except (UnicodeError, json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"{label} is not canonical JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    if canonical_json(value).encode("ascii") != payload:
        raise ValueError(f"{label} is not canonical JSON")
    return value


def _sha256_value(value: object, *, label: str) -> str:
    text = value if isinstance(value, str) else ""
    if len(text) != 64 or any(character not in "0123456789abcdef" for character in text):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")
    return text


def _retained_locator(
    store: ArtifactStore,
    uri: object,
    expected_sha256: object,
    *,
    label: str,
) -> ArtifactLocator:
    prefix = "artifact-locator:sha256:"
    if not isinstance(uri, str) or not uri.startswith(prefix):
        raise ValueError(f"{label} has no canonical artifact locator")
    locator_digest = _sha256_value(uri[len(prefix) :], label=f"{label} locator")
    expected = _sha256_value(expected_sha256, label=f"{label} artifact")
    locator = store.verify(store.load_locator(locator_digest))
    if locator.artifact_sha256 != expected:
        raise ValueError(f"{label} locator does not bind its declared artifact")
    return locator


def _locator_for_execution_receipt(
    store: ArtifactStore,
    *,
    execution_id: str,
    receipt_sha256: str,
) -> ArtifactLocator:
    """Find the unique immutable locator for a terminal-bound raw receipt."""

    locator_root = store.root / "locators" / "sha256"
    matches: list[ArtifactLocator] = []
    if locator_root.is_dir():
        for path in sorted(locator_root.glob("*/*.json"), key=lambda item: item.as_posix()):
            if path.is_symlink() or not path.is_file():
                raise EdaExecutionError("artifact locator inventory contains a non-regular file")
            digest = path.parent.name + path.stem
            try:
                locator = store.verify(store.load_locator(digest))
            except (OSError, TypeError, ValueError) as exc:
                raise EdaExecutionError(
                    "artifact locator inventory cannot be authenticated"
                ) from exc
            metadata = locator.metadata
            if (
                locator.artifact_sha256 == receipt_sha256
                and metadata.get("kind") == "eda_execution_receipt"
                and metadata.get("execution_id") == execution_id
            ):
                matches.append(locator)
    if len(matches) != 1:
        raise EdaExecutionError(
            "terminal EDA execution has no unique raw-receipt locator"
        )
    return matches[0]


def recover_retained_execution(
    *,
    artifact_store: ArtifactStore,
    execution: EffectExecutionRequest,
    start_receipt: LeasedEffectStartReceipt,
    terminal_receipt: EffectTerminalReceipt,
) -> RetainedExecutionObservation:
    """Rebuild a terminal result solely from authenticated ledger/CAS facts."""

    if type(execution) is not EffectExecutionRequest:
        raise TypeError("retained EDA recovery requires an exact execution request")
    if type(start_receipt) is not LeasedEffectStartReceipt:
        raise TypeError("retained EDA recovery requires an exact start receipt")
    if type(terminal_receipt) is not EffectTerminalReceipt:
        raise TypeError("retained EDA recovery requires an exact terminal receipt")
    if (
        start_receipt.execution_id != execution.execution_id
        or start_receipt.execution_request_sha256 != execution.digest
        or terminal_receipt.execution_id != execution.execution_id
        or terminal_receipt.start_receipt_sha256 != start_receipt.receipt_sha256
    ):
        raise EdaExecutionError("retained EDA lifecycle identities disagree")

    terminal_payloads = {
        digest: artifact_store.get_bytes(digest)
        for digest in terminal_receipt.output_digests
    }
    candidates: list[tuple[str, bytes, dict[str, Any]]] = []
    for digest, payload in terminal_payloads.items():
        try:
            body = _strict_canonical_json_object(
                payload,
                label="retained EDA execution receipt",
            )
        except (TypeError, ValueError):
            continue
        if body.get("schema") == _RECEIPT_SCHEMA:
            candidates.append((digest, payload, body))
    if len(candidates) != 1:
        raise EdaExecutionError(
            "terminal outputs contain no unique canonical EDA execution receipt"
        )
    receipt_sha256, receipt_payload, body = candidates[0]
    if set(body) != _RECEIPT_FIELDS:
        raise EdaExecutionError("retained EDA execution receipt has unexpected fields")
    if body["security_boundary_claimed"] is not False:
        raise EdaExecutionError("retained EDA receipt makes an unsupported sandbox claim")

    plan = EdaExecutionPlan.from_dict(body["execution_plan"])
    comparisons = {
        "execution_id": (body["execution_id"], execution.execution_id),
        "execution_request_sha256": (
            body["execution_request_sha256"],
            execution.digest,
        ),
        "operation_sha256": (body["operation_sha256"], execution.operation_sha256),
        "execution_plan_sha256": (plan.digest, execution.operation_sha256),
        "effect_start_receipt": (
            body["effect_start_receipt"],
            start_receipt.to_dict(),
        ),
        "argv": (body["argv"], list(plan.argv)),
        "cwd": (body["cwd"], plan.cwd),
        "terminal_outcome": (
            body["intended_effect_terminal_outcome"],
            terminal_receipt.outcome,
        ),
    }
    mismatches = sorted(
        name for name, (actual, expected) in comparisons.items() if actual != expected
    )
    if mismatches:
        raise EdaExecutionError(
            "retained EDA receipt contradicts its lifecycle or plan: "
            + ", ".join(mismatches)
        )

    status = body["status"]
    expected_outcomes = {
        "ok": "COMPLETED",
        "failed": "FAILED",
        "timeout": "CANCELLED",
        "missing": "FAILED",
        "error": "FAILED",
    }
    if not isinstance(status, str) or expected_outcomes.get(status) != terminal_receipt.outcome:
        raise EdaExecutionError("retained EDA status contradicts its terminal outcome")
    returncode = body["returncode"]
    if returncode is not None and (
        isinstance(returncode, bool) or not isinstance(returncode, int)
    ):
        raise EdaExecutionError("retained EDA returncode is invalid")
    duration = body["duration_s"]
    if (
        isinstance(duration, bool)
        or not isinstance(duration, (int, float))
        or not math.isfinite(float(duration))
        or float(duration) < 0
    ):
        raise EdaExecutionError("retained EDA duration is invalid")
    process_spawned = body["process_spawned"]
    if not isinstance(process_spawned, bool):
        raise EdaExecutionError("retained EDA process-spawned flag is invalid")

    stdout_locator = _retained_locator(
        artifact_store,
        body["stdout_locator"],
        body["stdout_sha256"],
        label="retained EDA stdout",
    )
    stderr_locator = _retained_locator(
        artifact_store,
        body["stderr_locator"],
        body["stderr_sha256"],
        label="retained EDA stderr",
    )
    stdout_payload = artifact_store.get_bytes(stdout_locator.artifact_sha256)
    stderr_payload = artifact_store.get_bytes(stderr_locator.artifact_sha256)

    artifacts_raw = body["artifacts"]
    missing_raw = body["missing_artifact_paths"]
    if not isinstance(artifacts_raw, list) or not isinstance(missing_raw, list):
        raise EdaExecutionError("retained EDA output partition is malformed")
    if not all(isinstance(path, str) for path in missing_raw):
        raise EdaExecutionError("retained EDA missing-output paths are malformed")
    retained_artifacts: list[ExecutionArtifact] = []
    for index, row in enumerate(artifacts_raw):
        if not isinstance(row, Mapping) or set(row) != {
            "path",
            "sha256",
            "locator",
            "byte_length",
        }:
            raise EdaExecutionError(
                f"retained EDA artifact {index} has unexpected fields"
            )
        path = row["path"]
        byte_length = row["byte_length"]
        if not isinstance(path, str) or (
            isinstance(byte_length, bool)
            or not isinstance(byte_length, int)
            or byte_length < 0
        ):
            raise EdaExecutionError(f"retained EDA artifact {index} is malformed")
        locator = _retained_locator(
            artifact_store,
            row["locator"],
            row["sha256"],
            label=f"retained EDA artifact {index}",
        )
        if locator.byte_length != byte_length:
            raise EdaExecutionError(
                f"retained EDA artifact {index} byte length disagrees with its locator"
            )
        retained_artifacts.append(
            ExecutionArtifact(
                path=path,
                sha256=locator.artifact_sha256,
                locator=locator.locator_uri,
                byte_length=locator.byte_length,
            )
        )

    retained_paths = tuple(artifact.path for artifact in retained_artifacts)
    missing_paths = tuple(missing_raw)
    if len(set(retained_paths + missing_paths)) != len(plan.artifact_paths):
        raise EdaExecutionError("retained EDA outputs are duplicated or incomplete")
    if set(retained_paths) | set(missing_paths) != set(plan.artifact_paths):
        raise EdaExecutionError("retained EDA outputs do not partition the execution plan")
    if retained_paths != tuple(
        path for path in plan.artifact_paths if path not in set(missing_paths)
    ) or missing_paths != tuple(
        path for path in plan.artifact_paths if path not in set(retained_paths)
    ):
        raise EdaExecutionError("retained EDA output partition is not in plan order")

    expected_terminal_outputs = {
        receipt_sha256,
        stdout_locator.artifact_sha256,
        stderr_locator.artifact_sha256,
        *(artifact.sha256 for artifact in retained_artifacts),
    }
    if expected_terminal_outputs != set(terminal_receipt.output_digests):
        raise EdaExecutionError("retained EDA outputs do not match the terminal receipt")

    pre_workspace_locator = _retained_locator(
        artifact_store,
        body["pre_workspace_manifest_locator"],
        body["pre_workspace_manifest_sha256"],
        label="retained pre-workspace manifest",
    )
    pre_authoritative_locator = _retained_locator(
        artifact_store,
        body["pre_authoritative_manifest_locator"],
        body["pre_authoritative_manifest_sha256"],
        label="retained pre-authoritative manifest",
    )
    trusted_tcl_locator = _retained_locator(
        artifact_store,
        body["trusted_tcl_locator"],
        body["trusted_tcl_sha256"],
        label="retained trusted Tcl",
    )
    if (
        pre_workspace_locator.artifact_sha256 != plan.workspace_manifest_sha256
        or pre_authoritative_locator.artifact_sha256 != plan.source_manifest_sha256
        or trusted_tcl_locator.artifact_sha256 != plan.trusted_tcl_sha256
        or body["pre_workspace_source_identity_sha256"]
        != plan.source_identity_sha256
        or body["pre_authoritative_source_identity_sha256"]
        != plan.source_identity_sha256
    ):
        raise EdaExecutionError("retained EDA immutable inputs contradict the plan")

    def optional_manifest(prefix: str) -> tuple[str | None, str | None, str | None]:
        digest = body[f"post_{prefix}_manifest_sha256"]
        identity_key = (
            "post_source_identity_sha256"
            if prefix == "workspace"
            else "post_authoritative_source_identity_sha256"
        )
        identity = body[identity_key]
        uri = body[f"post_{prefix}_manifest_locator"]
        if digest is None and identity is None and uri is None:
            return None, None, None
        if digest is None or identity is None or uri is None:
            raise EdaExecutionError(f"retained post-{prefix} manifest is partial")
        locator = _retained_locator(
            artifact_store,
            uri,
            digest,
            label=f"retained post-{prefix} manifest",
        )
        return (
            locator.artifact_sha256,
            _sha256_value(identity, label=f"post-{prefix} source identity"),
            locator.locator_uri,
        )

    post_workspace_sha, post_workspace_identity, post_workspace_uri = optional_manifest(
        "workspace"
    )
    post_authoritative_sha, post_authoritative_identity, post_authoritative_uri = (
        optional_manifest("authoritative")
    )
    if status == "ok" and (
        post_workspace_sha is None or post_authoritative_sha is None
    ):
        raise EdaExecutionError(
            "successful retained EDA execution lacks post-execution manifests"
        )

    observed_at = body["observed_at"]
    try:
        observed = datetime.fromisoformat(str(observed_at).replace("Z", "+00:00"))
        started = datetime.fromisoformat(start_receipt.started_at.replace("Z", "+00:00"))
        finished = datetime.fromisoformat(
            terminal_receipt.finished_at.replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise EdaExecutionError("retained EDA timestamps are malformed") from exc
    if (
        observed.tzinfo is None
        or started.tzinfo is None
        or finished.tzinfo is None
        or not started <= observed <= finished
    ):
        raise EdaExecutionError("retained EDA timestamps are inconsistent")

    receipt_locator = _locator_for_execution_receipt(
        artifact_store,
        execution_id=execution.execution_id,
        receipt_sha256=receipt_sha256,
    )
    stdout, stdout_truncated = _bounded(stdout_payload)
    stderr, stderr_truncated = _bounded(stderr_payload)
    result = ExecutionResult(
        status=status,
        argv=plan.argv,
        cwd=plan.cwd,
        returncode=returncode,
        duration_s=float(duration),
        stdout=stdout,
        stderr=stderr,
        truncated=stdout_truncated or stderr_truncated,
        executed=process_spawned,
        start_receipt=start_receipt,
        terminal_receipt=terminal_receipt,
        stdout_sha256=stdout_locator.artifact_sha256,
        stderr_sha256=stderr_locator.artifact_sha256,
        receipt_sha256=receipt_sha256,
        stdout_locator=stdout_locator.locator_uri,
        stderr_locator=stderr_locator.locator_uri,
        receipt_locator=receipt_locator.locator_uri,
        pre_workspace_manifest_locator=pre_workspace_locator.locator_uri,
        pre_authoritative_manifest_locator=pre_authoritative_locator.locator_uri,
        trusted_tcl_locator=trusted_tcl_locator.locator_uri,
        post_workspace_manifest_sha256=post_workspace_sha,
        post_source_identity_sha256=post_workspace_identity,
        post_workspace_manifest_locator=post_workspace_uri,
        post_authoritative_manifest_sha256=post_authoritative_sha,
        post_authoritative_source_identity_sha256=post_authoritative_identity,
        post_authoritative_manifest_locator=post_authoritative_uri,
        artifacts=tuple(retained_artifacts),
        missing_artifact_paths=missing_paths,
    )
    return RetainedExecutionObservation(
        result=result,
        plan=plan,
        receipt_body=dict(body),
        receipt_payload=receipt_payload,
    )


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _exception_detail(phase: str, exc: BaseException) -> str:
    """Hash exception class, not host-specific or potentially secret text."""

    return canonical_sha(
        {
            "phase": phase,
            "exception_module": type(exc).__module__,
            "exception_type": type(exc).__qualname__,
        }
    )


def _effect_ledger_path(
    authorization: NonRuntimeEffectAuthorization,
) -> str | None:
    """Best-effort diagnostic locator for an already-started execution."""

    try:
        raw = authorization.effect_ledger.path
    except AttributeError:
        return None
    try:
        return str(Path(raw).resolve(strict=False))
    except (OSError, TypeError, ValueError):
        return str(raw) if raw is not None else None


def _reconciliation_error(
    *,
    authorization: NonRuntimeEffectAuthorization,
    execution: EffectExecutionRequest,
    start_receipt: LeasedEffectStartReceipt,
    phase: str,
    cause: BaseException | None = None,
    cause_sha256: str | None = None,
    stored: _StoredObservation | None = None,
) -> EdaExecutionReconciliationRequired:
    if cause_sha256 is None:
        if cause is None:  # pragma: no cover - internal contract
            raise ValueError("reconciliation requires a cause or cause_sha256")
        cause_sha256 = _exception_detail(phase, cause)
    evidence_locators: tuple[str, ...] = ()
    if stored is not None:
        evidence_locators = (
            stored.stdout.locator_uri,
            stored.stderr.locator_uri,
            stored.receipt.locator_uri,
            stored.pre_workspace_manifest.locator_uri,
            stored.pre_authoritative_manifest.locator_uri,
            stored.trusted_tcl.locator_uri,
            *(artifact.locator for artifact in stored.artifacts),
        )
    return EdaExecutionReconciliationRequired(
        start_receipt=start_receipt,
        phase=phase,
        cause_sha256=cause_sha256,
        execution_id=execution.execution_id,
        execution_request_sha256=execution.digest,
        effect_ledger_path=_effect_ledger_path(authorization),
        evidence_locators=evidence_locators,
    )


def _cancel_and_known_returncode(process: ManagedProcess, *, phase: str) -> int:
    """Cancel a managed tree and prove that its root process has terminated."""

    try:
        cancellation = process.cancel()
    except BaseException as exc:
        raise _PostSpawnStateUnknown(phase, exc) from exc

    returncode = getattr(cancellation, "returncode", None)
    if returncode is None:
        try:
            returncode = process.poll()
        except BaseException as exc:
            raise _PostSpawnStateUnknown(f"{phase}-poll", exc) from exc
    if isinstance(returncode, bool) or not isinstance(returncode, int):
        raise _PostSpawnStateUnknown(
            phase,
            RuntimeError("managed cancellation did not prove process termination"),
        )
    return returncode


def _tool_aliases(command: str) -> frozenset[str]:
    """Return stable command spellings admitted by a canonical tool name."""

    leaf = command.replace("\\", "/").rsplit("/", 1)[-1]
    stem = Path(leaf).stem
    return frozenset(value for value in (command, leaf, stem) if value)


def _validate_canonical_vivado_argv(
    clean_argv: tuple[str, ...],
    *,
    root: Path,
    plan: EdaExecutionPlan,
) -> None:
    """Refuse any live Vivado invocation outside the package-owned flow.

    Binding a digest is not enough when the caller can choose what was
    digested. Reconstructing the one supported argv here prevents an otherwise
    valid chip lease from being reused for arbitrary ``vivado -source`` Tcl.
    """

    if (
        len(clean_argv) != 19
        or clean_argv[1:7]
        != ("-mode", "batch", "-nojournal", "-nolog", "-notrace", "-source")
        or clean_argv[8] != "-tclargs"
    ):
        raise EdaExecutionAdmissionError(
            "chip EDA execution requires the exact package-owned Vivado argv shape"
        )

    if clean_argv[0].casefold().endswith(".bat"):
        for index, value in enumerate(clean_argv):
            if any(character in value for character in _CMD_META):
                raise EdaExecutionAdmissionError(
                    "Windows Vivado batch argv contains a cmd.exe metacharacter "
                    f"at index {index}"
                )

    trusted = trusted_vivado_tcl()
    if plan.trusted_tcl_sha256 != trusted.sha256:
        raise EdaExecutionAdmissionError(
            "EDA execution plan does not bind the current package-owned Vivado Tcl"
        )
    if clean_argv[9] != plan.phase:
        raise EdaExecutionAdmissionError(
            "EDA execution plan phase does not match the Vivado Tcl phase"
        )
    argv_root = Path(clean_argv[10]).expanduser().resolve(strict=False)
    if os.path.normcase(str(argv_root)) != os.path.normcase(str(root)):
        raise EdaExecutionAdmissionError(
            "Vivado Tcl project root must equal the admitted working directory"
        )
    try:
        jobs = int(clean_argv[18])
        rebuilt = tuple(
            build_vivado_flow_argv(
                clean_argv[9],
                clean_argv[11],
                project_root=clean_argv[10],
                output_dir=clean_argv[12],
                expected_part=clean_argv[13],
                expected_board_part=clean_argv[14],
                expected_top=clean_argv[15],
                synth_run=clean_argv[16],
                impl_run=clean_argv[17],
                jobs=jobs,
                command=clean_argv[0],
            )
        )
    except (OSError, ValueError) as exc:
        raise EdaExecutionAdmissionError(
            f"invalid package-owned Vivado argv: {exc}"
        ) from exc
    if rebuilt != clean_argv or clean_argv[7] != trusted.path:
        raise EdaExecutionAdmissionError(
            "live Vivado argv differs from the package-owned trusted flow"
        )


def _validate_workspace_binding(
    clean_argv: tuple[str, ...],
    *,
    root: Path,
    plan: EdaExecutionPlan,
    declared_artifacts: tuple[tuple[str, Path], ...],
) -> VivadoProjectManifest:
    """Recompute active workspace bytes and the phase-exact output contract."""

    try:
        current = build_vivado_project_manifest(
            clean_argv[11], project_root=root
        )
    except (OSError, ValueError) as exc:
        raise EdaExecutionAdmissionError(
            f"cannot recompute the admitted Vivado workspace manifest: {exc}"
        ) from exc
    if not current.complete:
        raise EdaExecutionAdmissionError(
            "admitted Vivado workspace manifest is incomplete"
        )
    if current.sha256 != plan.workspace_manifest_sha256:
        raise EdaExecutionAdmissionError(
            "Vivado workspace bytes changed after the execution plan was built"
        )
    if current.source_identity_sha256 != plan.source_identity_sha256:
        raise EdaExecutionAdmissionError(
            "Vivado workspace source identity differs from the execution plan"
        )
    try:
        expected = tuple(
            sorted(
                expected_vivado_output_paths(
                    root, clean_argv[12], plan.phase
                )
            )
        )
    except (OSError, ValueError) as exc:
        raise EdaExecutionAdmissionError(
            f"cannot derive phase-exact Vivado outputs: {exc}"
        ) from exc
    actual = tuple(relative for relative, _path in declared_artifacts)
    if actual != expected or plan.artifact_paths != expected:
        raise EdaExecutionAdmissionError(
            "declared artifacts are not the exact output set for the Vivado phase"
        )
    return current


def _validate_post_execution_workspace(
    clean_argv: tuple[str, ...],
    *,
    root: Path,
    plan: EdaExecutionPlan,
) -> VivadoProjectManifest:
    """Fail evidence closed if authored inputs drifted during the tool run."""

    try:
        current = build_vivado_project_manifest(
            clean_argv[11],
            project_root=root,
        )
    except (OSError, ValueError) as exc:
        raise EdaExecutionAdmissionError(
            f"cannot recompute the post-execution Vivado workspace manifest: {exc}"
        ) from exc
    if not current.complete:
        raise EdaExecutionAdmissionError(
            "post-execution Vivado workspace manifest is incomplete"
        )
    if current.source_identity_sha256 != plan.source_identity_sha256:
        raise EdaExecutionAdmissionError(
            "authored Vivado source identity drifted during execution"
        )
    return current


def _validate_authoritative_source(plan: EdaExecutionPlan) -> VivadoProjectManifest:
    """Rebuild the disjoint source manifest without trusting a stale CLI object."""

    try:
        current = build_vivado_project_manifest(
            plan.source_project,
            project_root=plan.source_root,
        )
    except (OSError, ValueError) as exc:
        raise EdaExecutionAdmissionError(
            f"cannot recompute the authoritative Vivado source manifest: {exc}"
        ) from exc
    if not current.complete:
        raise EdaExecutionAdmissionError(
            "authoritative Vivado source manifest is incomplete"
        )
    if current.sha256 != plan.source_manifest_sha256:
        raise EdaExecutionAdmissionError(
            "authoritative Vivado source bytes changed after plan construction"
        )
    if current.source_identity_sha256 != plan.source_identity_sha256:
        raise EdaExecutionAdmissionError(
            "authoritative Vivado source identity differs from the execution plan"
        )
    return current


def _validate_post_execution_source(
    plan: EdaExecutionPlan,
) -> VivadoProjectManifest:
    current = _validate_authoritative_source(plan)
    if current.sha256 != plan.source_manifest_sha256:
        raise EdaExecutionAdmissionError(
            "authoritative Vivado source changed during execution"
        )
    return current


def _trusted_tcl_payload(plan: EdaExecutionPlan) -> bytes:
    """Read the package Tcl once with stable file identity for CAS retention."""

    path = Path(plan.argv[7])
    if path.is_symlink() or not path.is_file():
        raise EdaExecutionAdmissionError(
            "package-owned Vivado Tcl is not a regular non-symlink file"
        )
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        payload = handle.read()
        after = os.fstat(handle.fileno())
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    digest = hashlib.sha256(payload).hexdigest()
    if (
        identity_before != identity_after
        or len(payload) != after.st_size
        or digest != plan.trusted_tcl_sha256
    ):
        raise EdaExecutionAdmissionError(
            "package-owned Vivado Tcl changed while retained for execution"
        )
    return payload


def _validate_authority_artifact_store(
    authorization: NonRuntimeEffectAuthorization,
    artifact_store: ArtifactStore,
) -> None:
    """Bind CAS writes to the specialized lease's checkout-external root."""

    try:
        raw_ledger = Path(authorization.effect_ledger.path)
        source_revision = authorization.request.provenance.source_revision
    except AttributeError as exc:
        raise EdaExecutionAdmissionError("EDA authorization is malformed") from exc
    # Production ledgers are absolute.  Relative paths are retained only for
    # narrow in-memory test doubles; they are never accepted by the real
    # EffectLeaseLedger composition root.
    if not raw_ledger.is_absolute():
        return
    expected = (
        raw_ledger.resolve(strict=False).parent
        / "write-evidence"
        / str(source_revision)
        / "artifacts"
    ).resolve(strict=False)
    actual = Path(artifact_store.root).resolve(strict=False)
    if canonical_path_identity(expected) != canonical_path_identity(actual):
        raise EdaExecutionAdmissionError(
            "artifact store is not dominated by the lease authority evidence root"
        )


def _validate_startup_surface(
    launcher: str | Path,
    *,
    root: Path,
    environment: Mapping[str, str],
    plan: EdaExecutionPlan,
) -> None:
    """Refuse ambient startup Tcl and require a fresh isolated user profile."""

    path = Path(launcher).expanduser().resolve(strict=False)
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise EdaExecutionAdmissionError(
            "live Vivado launcher must be an absolute regular non-symlink file"
        )
    if not is_trusted_vendor_tool_path("vivado", path):
        raise EdaExecutionAdmissionError(
            "Vivado launcher is outside package-known AMD installation roots"
        )
    try:
        digest = trusted_launcher_sha256(path)
    except (OSError, ValueError) as exc:
        raise EdaExecutionAdmissionError(
            f"cannot bind the Vivado launcher bytes: {exc}"
        ) from exc
    if digest != plan.launcher_sha256:
        raise EdaExecutionAdmissionError(
            "Vivado launcher bytes differ from the signed execution plan"
        )

    if path.suffix.casefold() in {".bat", ".cmd"}:
        try:
            interpreter_path, interpreter_sha256 = (
                trusted_windows_command_interpreter()
            )
        except (OSError, ValueError) as exc:
            raise EdaExecutionAdmissionError(
                f"cannot bind the OS command interpreter: {exc}"
            ) from exc
        if not interpreter_path or not interpreter_sha256:
            raise EdaExecutionAdmissionError(
                "a Windows batch launcher requires an OS command interpreter identity"
            )
        if (
            canonical_path_identity(interpreter_path)
            != canonical_path_identity(plan.command_interpreter_path)
            or interpreter_sha256 != plan.command_interpreter_sha256
        ):
            raise EdaExecutionAdmissionError(
                "Windows command interpreter differs from the signed execution plan"
            )
        if canonical_path_identity(environment.get("COMSPEC", "")) != (
            canonical_path_identity(interpreter_path)
        ):
            raise EdaExecutionAdmissionError(
                "sanitized COMSPEC differs from the OS command interpreter"
            )
        if _inside(root, Path(interpreter_path)):
            raise EdaExecutionAdmissionError(
                "Windows command interpreter must not come from workspace content"
            )

    profile_values = {
        str(environment.get(name, ""))
        for name in ("APPDATA", "HOME", "USERPROFILE")
    }
    if len(profile_values) != 1 or "" in profile_values:
        raise EdaExecutionAdmissionError(
            "Vivado user profile roots are not pinned to one isolated path"
        )
    profile = Path(next(iter(profile_values))).resolve(strict=False)
    if not _inside(root, profile) or profile == root:
        raise EdaExecutionAdmissionError(
            "Vivado user profile must be a proper workspace descendant"
        )
    if profile.exists():
        raise EdaExecutionAdmissionError(
            "isolated Vivado user profile already exists; startup-script absence "
            "is no longer provable"
        )

    install_root = path.parent.parent
    startup_candidates = (
        install_root / "scripts" / "Vivado_init.tcl",
        install_root / "scripts" / "init.tcl",
    )
    existing = [str(candidate) for candidate in startup_candidates if candidate.exists()]
    if existing:
        raise EdaExecutionAdmissionError(
            "ambient Vivado installation startup Tcl is refused: " + ", ".join(existing)
        )


def _inside(root: Path, candidate: Path) -> bool:
    try:
        common = os.path.commonpath((str(root), str(candidate)))
        return os.path.normcase(common) == os.path.normcase(str(root))
    except ValueError:
        return False


def _validated_resolved_vivado_launcher(
    command: str,
    resolved: str,
    *,
    root: Path,
    environment: Mapping[str, str],
    plan: EdaExecutionPlan,
) -> str:
    """Recheck post-start discovery before the managed process is constructed."""

    launcher = Path(resolved).expanduser().resolve(strict=False)
    if launcher.name.casefold() not in {"vivado", "vivado.exe", "vivado.bat"}:
        raise EdaExecutionAdmissionError(
            "resolved executable is not the AMD Vivado launcher"
        )
    if _inside(root, launcher):
        raise EdaExecutionAdmissionError(
            "resolved Vivado launcher must not come from workspace content"
        )
    selected = Path(command).expanduser()
    if selected.is_absolute():
        expected = selected.resolve(strict=False)
        if os.path.normcase(str(expected)) != os.path.normcase(str(launcher)):
            raise EdaExecutionAdmissionError(
                "resolved Vivado launcher differs from the bound absolute command"
            )
    _validate_startup_surface(
        launcher,
        root=root,
        environment=environment,
        plan=plan,
    )
    return str(launcher)


def _normalise_artifact_paths(
    root: Path,
    artifact_paths: Sequence[str | Path],
) -> tuple[tuple[str, Path], ...]:
    if isinstance(artifact_paths, (str, bytes, Path)):
        raise TypeError("artifact_paths must be a sequence of relative paths")
    declared: list[tuple[str, Path]] = []
    for index, value in enumerate(artifact_paths):
        raw = Path(value)
        if raw.is_absolute() or ".." in raw.parts:
            raise EdaExecutionAdmissionError(
                f"artifact_paths[{index}] must stay inside cwd"
            )
        candidate = (root / raw).resolve(strict=False)
        if not _inside(root, candidate):
            raise EdaExecutionAdmissionError(
                f"artifact_paths[{index}] resolves outside cwd"
            )
        relative = candidate.relative_to(root).as_posix()
        if relative in {"", "."}:
            raise EdaExecutionAdmissionError(
                f"artifact_paths[{index}] must name a file"
            )
        declared.append((relative, candidate))
    if len({relative for relative, _ in declared}) != len(declared):
        raise EdaExecutionAdmissionError("artifact_paths must not contain duplicates")
    return tuple(sorted(declared, key=lambda item: item[0]))


def _normalise_live_inputs(
    argv: Sequence[str],
    *,
    cwd: str | Path,
    timeout_s: float,
    poll_s: float,
    env_overrides: Mapping[str, str] | None,
    artifact_paths: Sequence[str | Path],
) -> tuple[
    tuple[str, ...],
    Path,
    float,
    float,
    dict[str, str],
    tuple[tuple[str, Path], ...],
]:
    if not argv or not str(argv[0]).strip():
        raise ValueError("argv must contain a command")
    clean_argv = tuple(str(value) for value in argv)
    if any("\x00" in value for value in clean_argv):
        raise ValueError("argv must not contain NUL bytes")

    root = Path(cwd).resolve()
    if not root.is_dir():
        raise ValueError(f"cwd is not a directory: {root}")

    try:
        timeout = float(timeout_s)
        poll = float(poll_s)
    except (TypeError, ValueError) as exc:
        raise ValueError("timeout_s and poll_s must be finite positive numbers") from exc
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout_s must be a finite positive number")
    if not math.isfinite(poll) or poll <= 0:
        raise ValueError("poll_s must be a finite positive number")

    overrides: dict[str, str] = {}
    if env_overrides is not None:
        if not isinstance(env_overrides, Mapping):
            raise TypeError("env_overrides must be a mapping")
        for raw_name, raw_value in env_overrides.items():
            name = str(raw_name)
            value = str(raw_value)
            if not name or "=" in name or "\x00" in name or "\x00" in value:
                raise ValueError("environment overrides contain an invalid name or value")
            overrides[name] = value
    declared = _normalise_artifact_paths(root, artifact_paths)
    return clean_argv, root, timeout, poll, overrides, declared


def _validate_admission(
    clean_argv: tuple[str, ...],
    *,
    root: Path,
    timeout_s: float,
    environment: Mapping[str, str],
    declared_artifacts: tuple[tuple[str, Path], ...],
    authorization: NonRuntimeEffectAuthorization,
    execution: EffectExecutionRequest,
    artifact_store: ArtifactStore,
    plan: EdaExecutionPlan | None,
    env_overrides: Mapping[str, str],
) -> tuple[VivadoProjectManifest, VivadoProjectManifest]:
    # Exact types are deliberate. A duck-typed or subclassed capability could
    # override grant/start/terminal persistence and turn this into a callback.
    if type(authorization) is not NonRuntimeEffectAuthorization:
        raise EdaExecutionAdmissionError(
            "live EDA execution requires an exact NonRuntimeEffectAuthorization"
        )
    if type(execution) is not EffectExecutionRequest:
        raise EdaExecutionAdmissionError(
            "live EDA execution requires an exact EffectExecutionRequest"
        )
    if type(artifact_store) is not ArtifactStore:
        raise EdaExecutionAdmissionError(
            "live EDA execution requires the canonical ArtifactStore"
        )
    if type(plan) is not EdaExecutionPlan:
        raise EdaExecutionAdmissionError(
            "live EDA execution requires an exact EdaExecutionPlan"
        )
    if env_overrides:
        raise EdaExecutionAdmissionError(
            "live EDA execution forbids caller environment overrides; the "
            "no-secret environment projection is fixed by the executor"
        )

    _validate_canonical_vivado_argv(clean_argv, root=root, plan=plan)
    authoritative_manifest = _validate_authoritative_source(plan)
    workspace_manifest = _validate_workspace_binding(
        clean_argv,
        root=root,
        plan=plan,
        declared_artifacts=declared_artifacts,
    )
    _validate_authority_artifact_store(authorization, artifact_store)
    _validate_startup_surface(
        clean_argv[0],
        root=root,
        environment=environment,
        plan=plan,
    )

    rebound = EdaExecutionPlan.build(
        phase=plan.phase,
        argv=clean_argv,
        source_root=plan.source_root,
        source_project=plan.source_project,
        cwd=root,
        artifact_paths=tuple(relative for relative, _ in declared_artifacts),
        artifact_store_root=artifact_store.root,
        timeout_s=timeout_s,
        environment=environment,
        source_manifest_sha256=plan.source_manifest_sha256,
        workspace_manifest_sha256=plan.workspace_manifest_sha256,
        source_identity_sha256=plan.source_identity_sha256,
        trusted_tcl_sha256=plan.trusted_tcl_sha256,
        launcher_sha256=plan.launcher_sha256,
        command_interpreter_path=plan.command_interpreter_path,
        command_interpreter_sha256=plan.command_interpreter_sha256,
    )
    if rebound.digest != plan.digest:
        raise EdaExecutionAdmissionError(
            "EDA execution plan does not match normalized argv, cwd, outputs, "
            "environment, timeout, or artifact store"
        )
    if execution.operation_sha256 is None:
        raise EdaExecutionAdmissionError(
            "chip EDA execution request must bind an operation_sha256"
        )
    if execution.operation_sha256 != plan.digest:
        raise EdaExecutionAdmissionError(
            "effect execution request is bound to a different EDA execution plan"
        )

    request_operation = getattr(authorization.request, "operation_sha256", None)
    if request_operation is None:
        raise EdaExecutionAdmissionError(
            "signed chip lease request must bind an operation_sha256"
        )
    if request_operation != plan.digest:
        raise EdaExecutionAdmissionError(
            "signed chip lease request is bound to a different EDA operation"
        )

    try:
        request_entrypoint = authorization.request.entrypoint_id
        lease_entrypoint = authorization.lease.entrypoint_id
        timeout_limit = authorization.request.effect_scope.timeout_s
    except AttributeError as exc:
        raise EdaExecutionAdmissionError("EDA authorization is malformed") from exc
    if request_entrypoint != _ENTRYPOINT_ID or lease_entrypoint != _ENTRYPOINT_ID:
        raise EdaExecutionAdmissionError(
            "EDA authorization targets a different effectful entrypoint"
        )
    if set(execution.requested_effects) != _REQUIRED_EFFECTS:
        raise EdaExecutionAdmissionError(
            "EDA execution must request exactly filesystem write, process spawn, "
            "and process control"
        )
    if execution.egress_endpoints or execution.secret_refs or execution.max_cost_microusd:
        raise EdaExecutionAdmissionError(
            "EDA execution cannot request network, secret, or spend capability"
        )
    if execution.writable_paths != (".",) or execution.tools != ("vivado",):
        raise EdaExecutionAdmissionError(
            "chip EDA execution must retain the pinned whole-workspace write "
            "scope and exact Vivado tool scope"
        )
    if Path(clean_argv[0].replace("\\", "/")).stem.casefold() != "vivado":
        raise EdaExecutionAdmissionError(
            "chip EDA execution may launch only the registered Vivado executable"
        )
    if not set(execution.tools).intersection(_tool_aliases(clean_argv[0])):
        raise EdaExecutionAdmissionError(
            "EDA argv executable is absent from the exact requested tool scope"
        )
    if timeout_limit is None or timeout_s > float(timeout_limit):
        raise EdaExecutionAdmissionError(
            "EDA timeout exceeds the caller-issued effect scope"
        )
    return authoritative_manifest, workspace_manifest


def _error_observation(exc: Exception) -> _ProcessObservation:
    return _ProcessObservation(
        status="error",
        returncode=None,
        duration_s=0.0,
        stdout=b"",
        stderr=str(exc).encode("utf-8", errors="replace"),
        terminal_outcome="FAILED",
        process_spawned=False,
    )


def _run_managed_process(
    run_argv: tuple[str, ...],
    *,
    cwd: Path,
    env: Mapping[str, str],
    stdout_file: BinaryIO,
    stderr_file: BinaryIO,
    timeout_s: float,
    poll_s: float,
    authority_check: Callable[[], None],
    pre_spawn_check: Callable[[], None],
) -> _ProcessObservation:
    """Run one killable process and continuously recheck live authority.

    Once ``ManagedProcess`` has returned successfully, no observation failure
    is converted into a synthetic pre-spawn ``FAILED`` result.  The caller
    receives :class:`_PostSpawnStateUnknown` and leaves the durable execution
    ``STARTED`` for reconciliation.
    """

    started = time.monotonic()
    spawned = False
    phase = "process-construction"
    # The admitted caller opens both captures only after its durable effect
    # start. This helper owns their close so a close failure after spawn keeps
    # the execution STARTED for reconciliation instead of inventing a result.
    try:
        with stdout_file, stderr_file:
            phase = "process-construction"
            # A failed authority or input check here proves that
            # ManagedProcess was never called.  Keep these checks outside the
            # constructor guard: only a constructor failure is ambiguous
            # because it may already have crossed the Popen boundary.
            try:
                authority_check()
            except _UNKNOWN_ABORTS:
                raise
            except BaseException as exc:
                detail = _exception_detail("pre-spawn-authority", exc)
                return _ProcessObservation(
                    status="cancelled",
                    returncode=None,
                    duration_s=round(time.monotonic() - started, 3),
                    stdout=b"",
                    stderr=(
                        "live EDA authority changed or became unreadable before "
                        f"spawn (cause_sha256={detail})"
                    ).encode("ascii"),
                    terminal_outcome="CANCELLED",
                    process_spawned=False,
                )

            # Close the manifest / launcher / startup-surface race after the
            # durable STARTED receipt and immediately before any child exists.
            pre_spawn_check()
            try:
                authority_check()
            except _UNKNOWN_ABORTS:
                raise
            except BaseException as exc:
                detail = _exception_detail("immediate-pre-spawn-authority", exc)
                return _ProcessObservation(
                    status="cancelled",
                    returncode=None,
                    duration_s=round(time.monotonic() - started, 3),
                    stdout=b"",
                    stderr=(
                        "live EDA authority changed or became unreadable during "
                        f"pre-spawn input closure (cause_sha256={detail})"
                    ).encode("ascii"),
                    terminal_outcome="CANCELLED",
                    process_spawned=False,
                )
            try:
                process = ManagedProcess(
                    run_argv,
                    cwd=cwd,
                    env=env,
                    stdout=stdout_file,
                    stderr=stderr_file,
                )
            except _UNKNOWN_ABORTS:
                raise
            except Exception as exc:
                # ManagedProcess may have crossed Popen before containment's
                # constructor reports failure.  Its best-effort kill/wait is
                # not proof that no descendant wrote; keep STARTED for
                # authenticated reconciliation.
                raise _PostSpawnStateUnknown("process-construction", exc) from exc

            spawned = True
            timed_out = False
            authority_cancelled = False
            authority_detail_sha256: str | None = None
            returncode: int | None = None
            body_error: BaseException | None = None
            body_phase = "process-context-enter"
            entered = False
            try:
                phase = body_phase = "process-context-enter"
                process.__enter__()
                entered = True
                deadline = started + timeout_s
                while True:
                    phase = body_phase = "kill-switch-verification"
                    try:
                        authority_check()
                    except _UNKNOWN_ABORTS:
                        raise
                    except BaseException as exc:
                        authority_detail_sha256 = _exception_detail(
                            "kill-switch-verification", exc
                        )
                        phase = body_phase = "kill-switch-cancellation"
                        returncode = _cancel_and_known_returncode(
                            process, phase=body_phase
                        )
                        authority_cancelled = True
                        break

                    phase = body_phase = "process-poll"
                    returncode = process.poll()
                    if returncode is not None:
                        if isinstance(returncode, bool) or not isinstance(
                            returncode, int
                        ):
                            raise RuntimeError(
                                "managed process returned an invalid return code"
                            )
                        break

                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        phase = body_phase = "timeout-cancellation"
                        _cancel_and_known_returncode(process, phase=body_phase)
                        timed_out = True
                        break
                    phase = body_phase = "process-poll-wait"
                    time.sleep(min(poll_s, remaining))
            except BaseException as exc:
                body_error = exc
                if not entered:
                    try:
                        _cancel_and_known_returncode(
                            process, phase="process-context-enter-cancellation"
                        )
                    except _PostSpawnStateUnknown as cancel_error:
                        body_error = cancel_error
                        body_phase = cancel_error.phase
            finally:
                if entered:
                    try:
                        phase = "process-context-exit"
                        process.__exit__(
                            None if body_error is None else type(body_error),
                            body_error,
                            None if body_error is None else body_error.__traceback__,
                        )
                    except BaseException as exc:
                        body_error = exc
                        body_phase = phase

            if body_error is not None:
                if isinstance(body_error, _PostSpawnStateUnknown):
                    raise body_error
                raise _PostSpawnStateUnknown(body_phase, body_error) from body_error

            phase = "capture-flush"
            stdout_file.flush()
            stderr_file.flush()
            phase = "capture-seek"
            stdout_file.seek(0)
            stderr_file.seek(0)
            phase = "capture-read"
            stdout = stdout_file.read()
            stderr = stderr_file.read()
            elapsed = round(time.monotonic() - started, 3)
            phase = "capture-close"
    except _PostSpawnStateUnknown:
        raise
    except BaseException as exc:
        if spawned:
            raise _PostSpawnStateUnknown(phase, exc) from exc
        raise

    if authority_cancelled:
        suffix = (
            "live EDA authority changed or became unreadable; managed tree "
            f"cancelled (cause_sha256={authority_detail_sha256})"
        ).encode("ascii")
        separator = b"\n" if stderr else b""
        return _ProcessObservation(
            status="cancelled",
            returncode=returncode,
            duration_s=elapsed,
            stdout=stdout,
            stderr=stderr + separator + suffix,
            terminal_outcome="CANCELLED",
            process_spawned=True,
        )

    if timed_out:
        return _ProcessObservation(
            status="timeout",
            returncode=None,
            duration_s=elapsed,
            stdout=stdout,
            stderr=stderr,
            terminal_outcome="CANCELLED",
            process_spawned=True,
        )
    return _ProcessObservation(
        status="ok" if returncode == 0 else "failed",
        returncode=returncode,
        duration_s=elapsed,
        stdout=stdout,
        stderr=stderr,
        terminal_outcome="COMPLETED" if returncode == 0 else "FAILED",
        process_spawned=True,
    )


def _missing_tool_observation(command: str) -> _ProcessObservation:
    return _ProcessObservation(
        status="missing",
        returncode=None,
        duration_s=0.0,
        stdout=b"",
        stderr=f"{command} not found on PATH".encode("utf-8"),
        terminal_outcome="FAILED",
        process_spawned=False,
    )


def _read_declared_artifacts(
    root: Path,
    declared: tuple[tuple[str, Path], ...],
    observation: _ProcessObservation,
) -> tuple[_ProcessObservation, tuple[_NativeArtifactBytes, ...], tuple[str, ...]]:
    artifacts: list[_NativeArtifactBytes] = []
    missing: list[str] = []
    for relative, planned_path in declared:
        if planned_path.is_symlink() or not planned_path.is_file():
            missing.append(relative)
            continue
        resolved = planned_path.resolve(strict=True)
        if not _inside(root, resolved):
            raise EdaExecutionAdmissionError(
                f"declared artifact {relative!r} escaped cwd after execution"
            )
        with resolved.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise EdaExecutionAdmissionError(
                    f"declared artifact {relative!r} is not a regular file"
                )
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
                total += len(chunk)
            after = os.fstat(handle.fileno())
        if resolved.is_symlink() or not resolved.is_file():
            raise EdaExecutionAdmissionError(
                f"declared artifact {relative!r} changed path identity during read"
            )
        path_state = os.stat(resolved, follow_symlinks=False)
        before_identity = (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
        )
        after_identity = (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
        )
        path_identity = (
            path_state.st_dev,
            path_state.st_ino,
            path_state.st_size,
            path_state.st_mtime_ns,
        )
        if (
            before_identity != after_identity
            or before_identity != path_identity
            or total != after.st_size
        ):
            raise EdaExecutionAdmissionError(
                f"declared artifact {relative!r} changed while its bytes were read"
            )
        payload = b"".join(chunks)
        artifacts.append(
            _NativeArtifactBytes(
                path=relative,
                payload=payload,
                sha256=hashlib.sha256(payload).hexdigest(),
            )
        )

    if missing and observation.terminal_outcome == "COMPLETED":
        suffix = (
            "declared EDA artifacts missing after successful process exit: "
            + ", ".join(missing)
        ).encode("utf-8")
        separator = b"\n" if observation.stderr else b""
        observation = _ProcessObservation(
            status="failed",
            returncode=observation.returncode,
            duration_s=observation.duration_s,
            stdout=observation.stdout,
            stderr=observation.stderr + separator + suffix,
            terminal_outcome="FAILED",
            process_spawned=observation.process_spawned,
        )
    return observation, tuple(artifacts), tuple(missing)


def _store_observation(
    *,
    artifact_store: ArtifactStore,
    authorization: NonRuntimeEffectAuthorization,
    execution: EffectExecutionRequest,
    start_receipt: LeasedEffectStartReceipt,
    argv: tuple[str, ...],
    cwd: Path,
    observation: _ProcessObservation,
    native_artifacts: tuple[_NativeArtifactBytes, ...],
    missing_artifact_paths: tuple[str, ...],
    plan: EdaExecutionPlan,
    pre_workspace_manifest: VivadoProjectManifest,
    pre_authoritative_manifest: VivadoProjectManifest,
    trusted_tcl_payload: bytes,
    post_workspace_manifest: VivadoProjectManifest | None,
    post_authoritative_manifest: VivadoProjectManifest | None,
) -> _StoredObservation:
    created_at = _utc_timestamp()
    source_revision = authorization.request.provenance.source_revision
    trace_id = authorization.request.provenance.trace_id or current_trace_id()
    common_inputs = tuple(sorted({execution.digest, start_receipt.receipt_sha256}))

    def retain_manifest(
        manifest: VivadoProjectManifest | None,
        *,
        kind: str,
        filename_hint: str,
    ) -> ArtifactLocator | None:
        if manifest is None:
            return None
        return artifact_store.put_bytes(
            manifest.canonical_bytes,
            expected_sha256=manifest.sha256,
            media_type="application/json",
            metadata={
                "kind": kind,
                "execution_id": execution.execution_id,
                "filename_hint": filename_hint,
            },
            provenance=ContractProvenance(
                origin="daedalus.chip_design.executor",
                source_revision=source_revision,
                created_at=created_at,
                input_digests=tuple(
                    sorted(
                        {
                            *common_inputs,
                            manifest.source_identity_sha256,
                        }
                    )
                ),
                trace_id=trace_id,
            ).to_dict(),
        )

    pre_workspace_locator = retain_manifest(
        pre_workspace_manifest,
        kind="eda_pre_workspace_manifest",
        filename_hint=f"{execution.execution_id}-pre-workspace-manifest.json",
    )
    pre_authoritative_locator = retain_manifest(
        pre_authoritative_manifest,
        kind="eda_pre_authoritative_manifest",
        filename_hint=f"{execution.execution_id}-pre-authoritative-manifest.json",
    )
    assert pre_workspace_locator is not None
    assert pre_authoritative_locator is not None
    trusted_tcl_locator = artifact_store.put_bytes(
        trusted_tcl_payload,
        expected_sha256=plan.trusted_tcl_sha256,
        media_type="text/x-tcl",
        metadata={
            "kind": "eda_trusted_tcl",
            "execution_id": execution.execution_id,
            "filename_hint": "vivado_project_flow.tcl",
        },
        provenance=ContractProvenance(
            origin="daedalus.chip_design.executor",
            source_revision=source_revision,
            created_at=created_at,
            input_digests=common_inputs,
            trace_id=trace_id,
        ).to_dict(),
    )

    post_workspace_locator = retain_manifest(
        post_workspace_manifest,
        kind="eda_post_workspace_manifest",
        filename_hint=f"{execution.execution_id}-post-workspace-manifest.json",
    )
    post_authoritative_locator = retain_manifest(
        post_authoritative_manifest,
        kind="eda_post_authoritative_manifest",
        filename_hint=f"{execution.execution_id}-post-authoritative-manifest.json",
    )

    retained_artifacts: list[ExecutionArtifact] = []
    for artifact in native_artifacts:
        locator = artifact_store.put_bytes(
            artifact.payload,
            expected_sha256=artifact.sha256,
            media_type="application/octet-stream",
            metadata={
                "kind": "eda_native_artifact",
                "execution_id": execution.execution_id,
                "declared_path": artifact.path,
                "filename_hint": Path(artifact.path).name,
            },
            provenance=ContractProvenance(
                origin="daedalus.chip_design.executor",
                source_revision=source_revision,
                created_at=created_at,
                input_digests=common_inputs,
                trace_id=trace_id,
            ).to_dict(),
        )
        if (
            locator.artifact_sha256 != artifact.sha256
            or locator.byte_length != len(artifact.payload)
        ):
            raise EdaExecutionError(
                f"CAS identity mismatch while retaining {artifact.path!r}"
            )
        retained_artifacts.append(
            ExecutionArtifact(
                path=artifact.path,
                sha256=locator.artifact_sha256,
                locator=locator.locator_uri,
                byte_length=locator.byte_length,
            )
        )

    stdout_sha256 = hashlib.sha256(observation.stdout).hexdigest()
    stdout_locator = artifact_store.put_bytes(
        observation.stdout,
        expected_sha256=stdout_sha256,
        media_type="text/plain",
        metadata={
            "kind": "eda_console",
            "stream": "stdout",
            "execution_id": execution.execution_id,
            "filename_hint": f"{execution.execution_id}-stdout.log",
        },
        provenance=ContractProvenance(
            origin="daedalus.chip_design.executor",
            source_revision=source_revision,
            created_at=created_at,
            input_digests=common_inputs,
            trace_id=trace_id,
        ).to_dict(),
    )
    stderr_sha256 = hashlib.sha256(observation.stderr).hexdigest()
    stderr_locator = artifact_store.put_bytes(
        observation.stderr,
        expected_sha256=stderr_sha256,
        media_type="text/plain",
        metadata={
            "kind": "eda_console",
            "stream": "stderr",
            "execution_id": execution.execution_id,
            "filename_hint": f"{execution.execution_id}-stderr.log",
        },
        provenance=ContractProvenance(
            origin="daedalus.chip_design.executor",
            source_revision=source_revision,
            created_at=created_at,
            input_digests=common_inputs,
            trace_id=trace_id,
        ).to_dict(),
    )

    receipt_body = {
        "schema": _RECEIPT_SCHEMA,
        "execution_id": execution.execution_id,
        "execution_request_sha256": execution.digest,
        "operation_sha256": execution.operation_sha256,
        "execution_plan": plan.to_dict(),
        "effect_start_receipt": start_receipt.to_dict(),
        "argv": list(argv),
        "cwd": str(cwd),
        "status": observation.status,
        "returncode": observation.returncode,
        "duration_s": observation.duration_s,
        "process_spawned": observation.process_spawned,
        "intended_effect_terminal_outcome": observation.terminal_outcome,
        "stdout_sha256": stdout_locator.artifact_sha256,
        "stdout_locator": stdout_locator.locator_uri,
        "stderr_sha256": stderr_locator.artifact_sha256,
        "stderr_locator": stderr_locator.locator_uri,
        "artifacts": [asdict(artifact) for artifact in retained_artifacts],
        "missing_artifact_paths": list(missing_artifact_paths),
        "pre_workspace_manifest_sha256": pre_workspace_manifest.sha256,
        "pre_workspace_source_identity_sha256": (
            pre_workspace_manifest.source_identity_sha256
        ),
        "pre_workspace_manifest_locator": pre_workspace_locator.locator_uri,
        "pre_authoritative_manifest_sha256": pre_authoritative_manifest.sha256,
        "pre_authoritative_source_identity_sha256": (
            pre_authoritative_manifest.source_identity_sha256
        ),
        "pre_authoritative_manifest_locator": (
            pre_authoritative_locator.locator_uri
        ),
        "trusted_tcl_sha256": plan.trusted_tcl_sha256,
        "trusted_tcl_locator": trusted_tcl_locator.locator_uri,
        "post_workspace_manifest_sha256": (
            post_workspace_manifest.sha256
            if post_workspace_manifest is not None
            else None
        ),
        "post_source_identity_sha256": (
            post_workspace_manifest.source_identity_sha256
            if post_workspace_manifest is not None
            else None
        ),
        "post_workspace_manifest_locator": (
            post_workspace_locator.locator_uri
            if post_workspace_locator is not None
            else None
        ),
        "post_authoritative_manifest_sha256": (
            post_authoritative_manifest.sha256
            if post_authoritative_manifest is not None
            else None
        ),
        "post_authoritative_source_identity_sha256": (
            post_authoritative_manifest.source_identity_sha256
            if post_authoritative_manifest is not None
            else None
        ),
        "post_authoritative_manifest_locator": (
            post_authoritative_locator.locator_uri
            if post_authoritative_locator is not None
            else None
        ),
        "observed_at": created_at,
        "security_boundary_claimed": False,
    }
    receipt_bytes = canonical_json(receipt_body).encode("ascii")
    receipt_sha256 = hashlib.sha256(receipt_bytes).hexdigest()
    receipt_inputs = {
        *common_inputs,
        stdout_sha256,
        stderr_sha256,
        *(artifact.sha256 for artifact in retained_artifacts),
        pre_workspace_manifest.sha256,
        pre_authoritative_manifest.sha256,
        plan.trusted_tcl_sha256,
    }
    if post_workspace_manifest is not None:
        receipt_inputs.update(
            {
                post_workspace_manifest.sha256,
                post_workspace_manifest.source_identity_sha256,
            }
        )
    if post_authoritative_manifest is not None:
        receipt_inputs.update(
            {
                post_authoritative_manifest.sha256,
                post_authoritative_manifest.source_identity_sha256,
            }
        )
    receipt_locator = artifact_store.put_bytes(
        receipt_bytes,
        expected_sha256=receipt_sha256,
        media_type="application/json",
        metadata={
            "kind": "eda_execution_receipt",
            "execution_id": execution.execution_id,
            "status": observation.status,
            "filename_hint": f"{execution.execution_id}-receipt.json",
        },
        provenance=ContractProvenance(
            origin="daedalus.chip_design.executor",
            source_revision=source_revision,
            created_at=created_at,
            input_digests=tuple(sorted(receipt_inputs)),
            trace_id=trace_id,
        ).to_dict(),
    )
    return _StoredObservation(
        stdout=stdout_locator,
        stderr=stderr_locator,
        receipt=receipt_locator,
        artifacts=tuple(retained_artifacts),
        pre_workspace_manifest=pre_workspace_locator,
        pre_authoritative_manifest=pre_authoritative_locator,
        trusted_tcl=trusted_tcl_locator,
        post_workspace_manifest=post_workspace_locator,
        post_authoritative_manifest=post_authoritative_locator,
    )


def run_admitted_eda(
    argv: Sequence[str],
    *,
    cwd: str | Path,
    authorization: NonRuntimeEffectAuthorization,
    execution: EffectExecutionRequest,
    artifact_store: ArtifactStore,
    plan: EdaExecutionPlan | None = None,
    timeout_s: float = 300.0,
    env_overrides: Mapping[str, str] | None = None,
    artifact_paths: Sequence[str | Path] = (),
) -> ExecutionResult:
    """Run one locally installed EDA tool behind the canonical effect lease."""

    clean_argv, root, timeout, poll, overrides, declared_artifacts = (
        _normalise_live_inputs(
            argv,
            cwd=cwd,
            timeout_s=timeout_s,
            poll_s=_POLL_INTERVAL_S,
            env_overrides=env_overrides,
            artifact_paths=artifact_paths,
        )
    )
    if type(plan) is EdaExecutionPlan:
        environment = sanitized_eda_environment(
            root,
            phase=plan.phase,
            workspace_manifest_sha256=plan.workspace_manifest_sha256,
            output_dir=clean_argv[12],
        )
    else:
        environment = sanitized_eda_environment(root)
    pre_authoritative_manifest, pre_workspace_manifest = _validate_admission(
        clean_argv,
        root=root,
        timeout_s=timeout,
        environment=environment,
        declared_artifacts=declared_artifacts,
        authorization=authorization,
        execution=execution,
        artifact_store=artifact_store,
        plan=plan,
        env_overrides=overrides,
    )
    assert plan is not None  # exact type was checked above
    trusted_tcl_payload = _trusted_tcl_payload(plan)

    # Consume caller-issued authority; never issue or widen it here.
    authorization.grant()
    start = authorization.begin_effect(execution)
    if not start.execute:
        try:
            replay_state = authorization.effect_ledger.execution_state(
                execution.execution_id
            )
        except BaseException as exc:
            raise _reconciliation_error(
                authorization=authorization,
                execution=execution,
                start_receipt=start.receipt,
                phase="replay-state",
                cause=exc,
            ) from exc
        if replay_state == "STARTED":
            raise _reconciliation_error(
                authorization=authorization,
                execution=execution,
                start_receipt=start.receipt,
                phase="pending-replay",
                cause_sha256=canonical_sha(
                    {
                        "phase": "pending-replay",
                        "execution_id": execution.execution_id,
                        "state": replay_state,
                    }
                ),
            )
        if replay_state not in _TERMINAL_EXECUTION_STATES:
            raise _reconciliation_error(
                authorization=authorization,
                execution=execution,
                start_receipt=start.receipt,
                phase="replay-state",
                cause_sha256=canonical_sha(
                    {
                        "phase": "replay-state",
                        "execution_id": execution.execution_id,
                        "state": replay_state,
                    }
                ),
            )
        return ExecutionResult(
            status="replay",
            argv=clean_argv,
            cwd=str(root),
            returncode=None,
            duration_s=0.0,
            stdout="",
            stderr="",
            executed=False,
            start_receipt=start.receipt,
        )

    post_workspace_manifest: VivadoProjectManifest | None = None
    post_authoritative_manifest: VivadoProjectManifest | None = None

    # Discovery happens after the durable start so a missing tool still gets a
    # terminal receipt rather than becoming an unledgered live-path exception.
    try:
        resolved = shutil.which(clean_argv[0], path=environment.get("PATH"))
        if resolved:
            resolved = _validated_resolved_vivado_launcher(
                clean_argv[0],
                resolved,
                root=root,
                environment=environment,
                plan=plan,
            )
            # Spool inside the exact leased workspace. System-temp spooling
            # would be a real filesystem write outside the execution plan even
            # though it is deleted on close. The constructors stay here,
            # directly after the durable start, so repository-write inventory
            # can bind both writes to this exact lease rather than relying on
            # private-helper reachability.
            stdout_file = tempfile.TemporaryFile(mode="w+b", dir=str(root))
            try:
                stderr_file = tempfile.TemporaryFile(mode="w+b", dir=str(root))
            except BaseException:
                stdout_file.close()
                raise
            observation = _run_managed_process(
                (resolved, *clean_argv[1:]),
                cwd=root,
                env=environment,
                stdout_file=stdout_file,
                stderr_file=stderr_file,
                timeout_s=timeout,
                poll_s=poll,
                authority_check=authorization.verify,
                pre_spawn_check=lambda: (
                    _validate_canonical_vivado_argv(
                        clean_argv,
                        root=root,
                        plan=plan,
                    ),
                    _validate_workspace_binding(
                        clean_argv,
                        root=root,
                        plan=plan,
                        declared_artifacts=declared_artifacts,
                    ),
                    _validate_authoritative_source(plan),
                    _validate_startup_surface(
                        resolved,
                        root=root,
                        environment=environment,
                        plan=plan,
                    ),
                ),
            )
        else:
            observation = _missing_tool_observation(clean_argv[0])
    except _PostSpawnStateUnknown as exc:
        raise _reconciliation_error(
            authorization=authorization,
            execution=execution,
            start_receipt=start.receipt,
            phase=exc.phase,
            cause=exc.cause,
        ) from exc
    except _UNKNOWN_ABORTS:
        raise
    except Exception as exc:
        observation = _error_observation(exc)

    if observation.process_spawned:
        verification_errors: list[tuple[str, Exception]] = []
        try:
            post_workspace_manifest = _validate_post_execution_workspace(
                clean_argv,
                root=root,
                plan=plan,
            )
        except _UNKNOWN_ABORTS as exc:
            raise _reconciliation_error(
                authorization=authorization,
                execution=execution,
                start_receipt=start.receipt,
                phase="post-execution-workspace",
                cause=exc,
            ) from exc
        except Exception as exc:
            verification_errors.append(("post-execution-workspace", exc))

        # The authoritative source is disjoint from the mutable workspace and
        # must be measured independently. A workspace failure must not mask a
        # concurrent source mutation or suppress the source evidence when it
        # is still readable.
        try:
            post_authoritative_manifest = _validate_post_execution_source(plan)
        except _UNKNOWN_ABORTS as exc:
            raise _reconciliation_error(
                authorization=authorization,
                execution=execution,
                start_receipt=start.receipt,
                phase="post-execution-source",
                cause=exc,
            ) from exc
        except Exception as exc:
            verification_errors.append(("post-execution-source", exc))

        if verification_errors:
            suffix = b"\n".join(
                (
                    f"{phase} verification failed "
                    f"(cause_sha256={_exception_detail(phase, exc)})"
                ).encode("ascii")
                for phase, exc in verification_errors
            )
            separator = b"\n" if observation.stderr else b""
            observation = _ProcessObservation(
                status="failed",
                returncode=observation.returncode,
                duration_s=observation.duration_s,
                stdout=observation.stdout,
                stderr=observation.stderr + separator + suffix,
                terminal_outcome="FAILED",
                process_spawned=True,
            )

    try:
        observation, native_artifacts, missing_artifacts = _read_declared_artifacts(
            root,
            declared_artifacts,
            observation,
        )
        stored = _store_observation(
            artifact_store=artifact_store,
            authorization=authorization,
            execution=execution,
            start_receipt=start.receipt,
            argv=clean_argv,
            cwd=root,
            observation=observation,
            native_artifacts=native_artifacts,
            missing_artifact_paths=missing_artifacts,
            plan=plan,
            pre_workspace_manifest=pre_workspace_manifest,
            pre_authoritative_manifest=pre_authoritative_manifest,
            trusted_tcl_payload=trusted_tcl_payload,
            post_workspace_manifest=post_workspace_manifest,
            post_authoritative_manifest=post_authoritative_manifest,
        )
    except BaseException as exc:
        raise _reconciliation_error(
            authorization=authorization,
            execution=execution,
            start_receipt=start.receipt,
            phase="artifact-evidence",
            cause=exc,
        ) from exc

    detail_sha256 = None
    if observation.terminal_outcome != "COMPLETED":
        detail_sha256 = canonical_sha(
            {
                "status": observation.status,
                "returncode": observation.returncode,
                "receipt_sha256": stored.receipt.artifact_sha256,
            }
        )
    output_digests = (
        stored.stdout.artifact_sha256,
        stored.stderr.artifact_sha256,
        stored.receipt.artifact_sha256,
        *(artifact.sha256 for artifact in stored.artifacts),
    )
    try:
        terminal = authorization.finish_effect(
            start.receipt,
            outcome=observation.terminal_outcome,
            output_digests=output_digests,
            detail_sha256=detail_sha256,
        )
    except BaseException as exc:
        raise _reconciliation_error(
            authorization=authorization,
            execution=execution,
            start_receipt=start.receipt,
            phase="terminal-persistence",
            cause=exc,
            stored=stored,
        ) from exc

    stdout, stdout_truncated = _bounded(observation.stdout)
    stderr, stderr_truncated = _bounded(observation.stderr)
    return ExecutionResult(
        status=observation.status,
        argv=clean_argv,
        cwd=str(root),
        returncode=observation.returncode,
        duration_s=observation.duration_s,
        stdout=stdout,
        stderr=stderr,
        truncated=stdout_truncated or stderr_truncated,
        executed=observation.process_spawned,
        start_receipt=start.receipt,
        terminal_receipt=terminal,
        stdout_sha256=stored.stdout.artifact_sha256,
        stderr_sha256=stored.stderr.artifact_sha256,
        receipt_sha256=stored.receipt.artifact_sha256,
        stdout_locator=stored.stdout.locator_uri,
        stderr_locator=stored.stderr.locator_uri,
        receipt_locator=stored.receipt.locator_uri,
        pre_workspace_manifest_locator=(
            stored.pre_workspace_manifest.locator_uri
        ),
        pre_authoritative_manifest_locator=(
            stored.pre_authoritative_manifest.locator_uri
        ),
        trusted_tcl_locator=stored.trusted_tcl.locator_uri,
        post_workspace_manifest_sha256=(
            post_workspace_manifest.sha256
            if post_workspace_manifest is not None
            else None
        ),
        post_source_identity_sha256=(
            post_workspace_manifest.source_identity_sha256
            if post_workspace_manifest is not None
            else None
        ),
        post_workspace_manifest_locator=(
            stored.post_workspace_manifest.locator_uri
            if stored.post_workspace_manifest is not None
            else None
        ),
        post_authoritative_manifest_sha256=(
            post_authoritative_manifest.sha256
            if post_authoritative_manifest is not None
            else None
        ),
        post_authoritative_source_identity_sha256=(
            post_authoritative_manifest.source_identity_sha256
            if post_authoritative_manifest is not None
            else None
        ),
        post_authoritative_manifest_locator=(
            stored.post_authoritative_manifest.locator_uri
            if stored.post_authoritative_manifest is not None
            else None
        ),
        artifacts=stored.artifacts,
        missing_artifact_paths=missing_artifacts,
    )


def execute_argv(
    argv: Sequence[str],
    *,
    cwd: str | Path,
    timeout_s: float = 300.0,
    dry_run: bool = True,
    env_overrides: Mapping[str, str] | None = None,
    authorization: NonRuntimeEffectAuthorization | None = None,
    execution: EffectExecutionRequest | None = None,
    artifact_store: ArtifactStore | None = None,
    artifact_paths: Sequence[str | Path] = (),
) -> ExecutionResult:
    """Plan an argv unchanged, or delegate a live run to the admitted seam."""

    if not argv or not str(argv[0]).strip():
        raise ValueError("argv must contain a command")
    root = Path(cwd).resolve()
    if not root.is_dir():
        raise ValueError(f"cwd is not a directory: {root}")
    clean_argv = tuple(str(value) for value in argv)
    if dry_run:
        return ExecutionResult(
            status="planned",
            argv=clean_argv,
            cwd=str(root),
            returncode=None,
            duration_s=0.0,
            stdout="",
            stderr="",
        )

    return run_admitted_eda(
        clean_argv,
        cwd=root,
        authorization=authorization,  # type: ignore[arg-type]
        execution=execution,  # type: ignore[arg-type]
        artifact_store=artifact_store,  # type: ignore[arg-type]
        timeout_s=timeout_s,
        env_overrides=env_overrides,
        artifact_paths=artifact_paths,
    )


__all__ = [
    "EdaExecutionAdmissionError",
    "EdaExecutionError",
    "EdaExecutionReconciliationRequired",
    "EdaExecutionStateError",
    "ExecutionArtifact",
    "ExecutionResult",
    "RetainedExecutionObservation",
    "execute_argv",
    "recover_retained_execution",
    "run_admitted_eda",
]
