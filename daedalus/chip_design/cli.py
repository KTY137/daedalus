"""Canonical command line surface for Daedalus chip-design work.

Read-only inventory and planning never start an external process. The sole
live path accepts an authoritative Vivado project plus a disjoint workspace
copy and consumes a caller-issued kernel effect lease before starting Vivado.
Project automation Tcl and launch hooks are refused; live project runs use the
static Tcl file shipped in this package. Declared XDC files remain executable
Vivado constraint Tcl and therefore require operator trust.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from daedalus.gates.repository_head_revision import (
    RepositoryHeadRevisionReceipt,
    RepositoryHeadRevisionError,
    verify_repository_head_revision,
)
from daedalus.kernel.effect_replay import (
    EffectExecutionReplaySnapshot,
    inspect_effect_execution,
)
from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.kernel.offload_lease import (
    CHIP_EDA_ENTRYPOINT_ID,
    LEASE_EXECUTION_RECORD_SCHEMA,
    LEASE_SUBJECT_RECORD_SCHEMA,
    LEASE_TERMINAL_RECORD_SCHEMA,
    WaveLeaseDenied,
    WaveLeaseKillSwitchEngaged,
    acquire_chip_eda_lease,
    chip_eda_lease_id,
    control_root,
    emit_effect_lease_terminal_record,
    lease_ledger_path,
    read_issuer_keyring,
    rebuild_effect_lease_authorization,
    record_chip_eda_publication,
    write_evidence_root,
    write_root_identity_sha256,
)
from daedalus.kernel.effects import EffectLeaseReplay
from daedalus.schemas import ContractProvenance
from daedalus.spine.envelope import canonical_json, canonical_sha
from daedalus.storage import ArtifactStore

from .contracts import (
    ChipArtifact,
    ChipRunReceipt,
    build_chip_contracts,
    build_chip_runtime_manifest,
    build_evidence_packet,
    default_dimensions,
    utc_now,
)
from .executor import (
    EdaExecutionError,
    EdaExecutionReconciliationRequired,
    ExecutionResult,
    RetainedExecutionObservation,
    execute_argv,
    recover_retained_execution,
    run_admitted_eda,
)
from .execution_plan import (
    EdaExecutionPlan,
    sanitized_eda_environment,
    trusted_windows_command_interpreter,
)
from .manifest import (
    MANIFEST_SCHEMA,
    VivadoProjectManifest,
    build_vivado_project_manifest,
    canonical_path,
    canonical_path_identity,
)
from .sources import classify_source, discover_sources
from .toolchains import (
    all_tool_status,
    build_rtl_lint_argv,
    build_tcl_argv,
    find_trusted_vendor_tool_path,
    trusted_launcher_sha256,
    tool_status,
)
from .vivado_reports import (
    VivadoReportResult,
    parse_vivado_message_counts_bytes,
    parse_vivado_report,
    parse_vivado_report_bytes,
)
from .vivado_tcl import (
    build_vivado_flow_argv,
    expected_vivado_output_paths,
    trusted_vivado_tcl,
)


PLAN_SCHEMA = "daedalus-chip-vivado-plan/1"
RUN_SCHEMA = "daedalus-chip-vivado-run-result/1"
_REVISION = re.compile(r"^[0-9a-f]{40}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}$")
_SUMMARY_KEY = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_VIVADO_SHORT_VERSION = re.compile(
    r"\bVivado\s+v\d{4}\.\d+(?:\.\d+)?\b", re.IGNORECASE
)
_PHASES = ("inspect", "synth", "impl")
_LIMITATIONS = (
    "A successful Vivado process or generated bitstream is not FPGA signoff.",
    "Simulation, formal, CDC/RDC, equivalence, power, Vitis software, hardware-in-loop, and FPGA programming were not run.",
    "The in-process guard and isolated workspace are not an operating-system sandbox.",
    "The kernel lease requests no egress endpoint, but this does not prove offline or no-egress execution.",
    "Declared XDC is executable Tcl; Vivado, XDC, and vendor support processes retain ambient host filesystem, network, and secret access outside OS confinement.",
    "Vivado support binaries and vendor catalog resources are a trusted-but-unbound vendor TCB beyond the byte-bound launcher.",
    "The authority HEAD receipt does not bind the imported Python adapter/parser bytes, commit object, or worktree cleanliness.",
    "Concurrent host mutation outside the retained source/workspace snapshots can invalidate conclusions.",
    "No merge or promotion is authorized by this evidence.",
)


class _RetainedLeaseReconciliation(RuntimeError):
    """A prior deterministic lease exists but has no publishable terminal."""

    def __init__(self, *, execution_id: str, phase: str, detail: str) -> None:
        super().__init__(detail)
        self.execution_id = execution_id
        self.phase = phase
        self.cause_sha256 = canonical_sha(
            {
                "schema": "daedalus-chip-reconciliation-cause/1",
                "execution_id": execution_id,
                "phase": phase,
                "detail": detail,
            }
        )


@dataclass(frozen=True)
class _RecoveredPhase:
    authorization: Any
    execution: EffectExecutionRequest
    replay: EffectExecutionReplaySnapshot
    retained: RetainedExecutionObservation
    store: ArtifactStore
    terminal_record: Mapping[str, Any]
    subject_record_sha256: str
    execution_record_sha256: str
    authority_head_record_sha256: str


@dataclass(frozen=True)
class _RetainedJsonArtifact:
    body: Mapping[str, Any]
    payload: bytes
    sha256: str
    locator_uri: str


def _strict_canonical_object(payload: bytes, *, label: str) -> dict[str, Any]:
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
        raise ValueError(f"{label} is malformed JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    if canonical_json(value).encode("ascii") != payload:
        raise ValueError(f"{label} is not canonical JSON")
    return value


def _validated_evidence_record(path: Path, *, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} is not a regular non-symlink file")
    payload = path.read_bytes()
    body = _strict_canonical_object(payload, label=label)
    record_sha256 = body.get("record_sha256")
    if not isinstance(record_sha256, str) or record_sha256 != path.stem:
        raise ValueError(f"{label} filename does not match record identity")
    subject = {key: value for key, value in body.items() if key != "record_sha256"}
    if canonical_sha(subject) != record_sha256:
        raise ValueError(f"{label} record digest is invalid")
    return body


def _matching_evidence_records(
    evidence_root: Path,
    kind: str,
    *,
    predicate: Any,
) -> tuple[dict[str, Any], ...]:
    root = evidence_root / kind
    if not root.exists():
        return ()
    if root.is_symlink() or not root.is_dir():
        raise ValueError(f"{kind} evidence root is not a regular directory")
    matches: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.json"), key=lambda item: item.name):
        body = _validated_evidence_record(path, label=f"{kind} evidence record")
        if predicate(body):
            matches.append(body)
    return tuple(matches)


def _unique_evidence_record(
    evidence_root: Path,
    kind: str,
    *,
    predicate: Any,
    required: bool,
) -> dict[str, Any] | None:
    matches = _matching_evidence_records(
        evidence_root,
        kind,
        predicate=predicate,
    )
    if not matches and not required:
        return None
    if len(matches) != 1:
        raise ValueError(f"expected one {kind} evidence record, found {len(matches)}")
    return matches[0]


def _effect_execution_from_dict(value: object) -> EffectExecutionRequest:
    expected = {
        "execution_id",
        "idempotency_key",
        "requested_effects",
        "writable_paths",
        "egress_endpoints",
        "tools",
        "secret_refs",
        "max_cost_microusd",
        "kill_switch_ref",
        "kill_switch_generation",
        "operation_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ValueError("retained EDA execution request has unexpected fields")
    sequence_fields = (
        "requested_effects",
        "writable_paths",
        "egress_endpoints",
        "tools",
        "secret_refs",
    )
    if any(
        not isinstance(value[field], list)
        or not all(isinstance(item, str) for item in value[field])
        for field in sequence_fields
    ):
        raise ValueError("retained EDA execution request has malformed arrays")
    execution = EffectExecutionRequest(
        execution_id=value["execution_id"],
        idempotency_key=value["idempotency_key"],
        requested_effects=tuple(value["requested_effects"]),
        writable_paths=tuple(value["writable_paths"]),
        egress_endpoints=tuple(value["egress_endpoints"]),
        tools=tuple(value["tools"]),
        secret_refs=tuple(value["secret_refs"]),
        max_cost_microusd=value["max_cost_microusd"],
        kill_switch_ref=value["kill_switch_ref"],
        kill_switch_generation=value["kill_switch_generation"],
        operation_sha256=value["operation_sha256"],
    )
    if canonical_json(execution.to_dict()) != canonical_json(dict(value)):
        raise ValueError("retained EDA execution request is noncanonical")
    return execution


def _recover_phase(
    *,
    authority_root: Path,
    source_revision: str,
    mission_id: str,
    attempt_id: str,
    phase: str,
) -> _RecoveredPhase | None:
    """Recover a terminal phase without consulting live project inputs."""

    evidence_root = write_evidence_root(authority_root, source_revision)
    expected_lease_id = chip_eda_lease_id(mission_id, attempt_id)
    subject = _unique_evidence_record(
        evidence_root,
        "lease-subject",
        predicate=lambda body: (
            body.get("schema") == LEASE_SUBJECT_RECORD_SCHEMA
            and body.get("lease_id") == expected_lease_id
        ),
        required=False,
    )
    if subject is None:
        return None
    subject_fields = {
        "schema",
        "source_revision",
        "entrypoint_id",
        "lease_id",
        "lease_sha256",
        "issuer_key_id",
        "kill_switch_generation",
        "ledger_path",
        "positions",
        "issuer_target",
        "issuer_module_path",
        "lease",
        "request",
        "policy_decision",
        "guard_decisions",
        "control_root_sha256",
        "recorded_at",
        "record_sha256",
    }
    if set(subject) not in (subject_fields, subject_fields | {"execution_limit_policy"}):
        raise ValueError("retained EDA lease-subject record has unexpected fields")
    expected_control_root = control_root(authority_root)
    if (
        subject.get("source_revision") != source_revision
        or subject.get("entrypoint_id") != CHIP_EDA_ENTRYPOINT_ID
        or subject.get("positions") != 1
        or subject.get("control_root_sha256")
        != write_root_identity_sha256(expected_control_root)
        or canonical_path_identity(subject.get("ledger_path", ""))
        != canonical_path_identity(lease_ledger_path(authority_root))
    ):
        raise ValueError("retained EDA lease-subject authority binding is invalid")

    keyring = read_issuer_keyring(authority_root)
    authorization = rebuild_effect_lease_authorization(
        subject,
        keyring=keyring,
        ledger_path=lease_ledger_path(authority_root),
    )
    if (
        authorization.request.mission_id != mission_id
        or authorization.request.attempt_id != attempt_id
        or authorization.lease.lease_id != expected_lease_id
        or authorization.lease.entrypoint_id != CHIP_EDA_ENTRYPOINT_ID
    ):
        raise ValueError("retained EDA lease does not name the requested phase identity")

    execution_id = f"{expected_lease_id}-exec-1"
    execution_record = _unique_evidence_record(
        evidence_root,
        "lease-execution",
        predicate=lambda body: (
            body.get("schema") == LEASE_EXECUTION_RECORD_SCHEMA
            and body.get("execution_id") == execution_id
        ),
        required=False,
    )
    if execution_record is None:
        raise _RetainedLeaseReconciliation(
            execution_id=execution_id,
            phase=phase,
            detail="prior EDA lease has no retained execution identity",
        )
    if set(execution_record) != {
        "schema",
        "source_revision",
        "entrypoint_id",
        "lease_sha256",
        "subject_record_sha256",
        "execution_id",
        "execution_request_sha256",
        "execution",
        "control_root_sha256",
        "recorded_at",
        "record_sha256",
    }:
        raise ValueError("retained EDA execution record has unexpected fields")
    if (
        execution_record["source_revision"] != source_revision
        or execution_record["entrypoint_id"] != CHIP_EDA_ENTRYPOINT_ID
        or execution_record["lease_sha256"] != authorization.lease.digest
        or execution_record["subject_record_sha256"] != subject["record_sha256"]
        or execution_record["control_root_sha256"]
        != write_root_identity_sha256(expected_control_root)
    ):
        raise ValueError("retained EDA execution evidence binding is invalid")
    execution = _effect_execution_from_dict(execution_record["execution"])
    if execution.digest != execution_record["execution_request_sha256"]:
        raise ValueError("retained EDA execution digest is invalid")

    replay = inspect_effect_execution(authorization, execution)
    if replay is None:
        raise _RetainedLeaseReconciliation(
            execution_id=execution_id,
            phase=phase,
            detail="prior EDA execution identity has no durable start",
        )
    if replay.pending_reconciliation or replay.terminal_receipt is None:
        raise EdaExecutionReconciliationRequired(
            start_receipt=replay.start_receipt,
            phase="retained-started-execution",
            cause_sha256=canonical_sha(
                {
                    "schema": "daedalus-chip-reconciliation-cause/1",
                    "execution_id": execution_id,
                    "state": replay.state,
                }
            ),
            execution_id=execution_id,
            execution_request_sha256=execution.digest,
            effect_ledger_path=str(lease_ledger_path(authority_root)),
        )

    store = ArtifactStore(evidence_root / "artifacts")
    retained = recover_retained_execution(
        artifact_store=store,
        execution=execution,
        start_receipt=replay.start_receipt,
        terminal_receipt=replay.terminal_receipt,
    )
    if (
        retained.plan.phase != phase
        or retained.plan.digest != authorization.request.operation_sha256
        or canonical_path_identity(retained.plan.artifact_store_root)
        != canonical_path_identity(store.root)
    ):
        raise ValueError("retained EDA execution plan does not match recovery identity")

    authority_head_record = _unique_evidence_record(
        evidence_root,
        "authority-head",
        predicate=lambda body: (
            body.get("schema") == "daedalus-chip-authority-head-record/1"
            and body.get("lease_sha256") == authorization.lease.digest
        ),
        required=True,
    )
    assert authority_head_record is not None
    if set(authority_head_record) != {
        "schema",
        "entrypoint_id",
        "lease_sha256",
        "operation_sha256",
        "repository_head_receipt",
        "record_sha256",
    }:
        raise ValueError("retained EDA authority-head record has unexpected fields")
    head_receipt = RepositoryHeadRevisionReceipt.from_dict(
        authority_head_record["repository_head_receipt"]
    )
    if (
        authority_head_record["entrypoint_id"] != CHIP_EDA_ENTRYPOINT_ID
        or authority_head_record["operation_sha256"] != retained.plan.digest
        or head_receipt.expected_revision != source_revision
        or head_receipt.resolved_revision != source_revision
    ):
        raise ValueError("retained EDA authority-head record is not plan-bound")

    terminal_record = emit_effect_lease_terminal_record(
        subject,
        execution,
        evidence_root=evidence_root,
        control_root_path=expected_control_root,
        keyring=keyring,
        ledger_path=lease_ledger_path(authority_root),
    )
    if (
        terminal_record.get("schema") != LEASE_TERMINAL_RECORD_SCHEMA
        or terminal_record.get("execution_id") != execution_id
        or terminal_record.get("receipt_sha256")
        != replay.terminal_receipt.receipt_sha256
    ):
        raise ValueError("retained EDA terminal evidence is invalid")
    return _RecoveredPhase(
        authorization=authorization,
        execution=execution,
        replay=replay,
        retained=retained,
        store=store,
        terminal_record=terminal_record,
        subject_record_sha256=str(subject["record_sha256"]),
        execution_record_sha256=str(execution_record["record_sha256"]),
        authority_head_record_sha256=str(authority_head_record["record_sha256"]),
    )


def _emit(payload: Mapping[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(dict(payload), indent=2, sort_keys=True, default=str))
        return
    status = payload.get("status") or payload.get("verdict") or "ok"
    print(str(status).upper())
    for key, value in payload.items():
        if key not in {"status", "manifest", "steps"}:
            print(f"{key}: {value}")


def _print_execution(result: ExecutionResult, *, as_json: bool) -> int:
    payload = result.to_dict()
    if as_json:
        print(json.dumps(payload, indent=2, default=str))
    else:
        print(f"{result.status.upper()}  {result.duration_s}s")
        print("argv:", " ".join(result.argv))
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
    return 0 if result.status in {"ok", "planned", "replay"} else 1


def _add_legacy_live_arguments(parser: argparse.ArgumentParser) -> None:
    """Keep old flags parseable so the retired live doors fail explicitly."""

    parser.add_argument("--authority-root")
    parser.add_argument("--project-root")
    parser.add_argument("--source-revision")
    parser.add_argument("--writable-path", action="append", default=[])
    parser.add_argument("--artifact", action="append", default=[])
    parser.add_argument("--mission-id", default="chip-cli")
    parser.add_argument("--attempt-id")


def _phase_sequence(phase: str) -> tuple[str, ...]:
    if phase == "full":
        return ("synth", "impl")
    if phase not in _PHASES:
        raise ValueError(f"unsupported Vivado phase: {phase}")
    return (phase,)


def _identifier(value: str, label: str) -> str:
    text = str(value)
    if not _IDENTIFIER.fullmatch(text):
        raise ValueError(
            f"{label} must start with an alphanumeric character, use only "
            "letters, digits, '.', '_', ':', '/', or '-', and be at most 200 characters"
        )
    return text


def _phase_identifier(base: str, phase: str, label: str) -> str:
    suffix = f"-{phase}"
    if len(base) + len(suffix) > 200:
        raise ValueError(f"{label} is too long once the phase suffix is added")
    return _identifier(base + suffix, label)


def _disjoint(left: Path, right: Path) -> bool:
    left_id = canonical_path_identity(left)
    right_id = canonical_path_identity(right)
    try:
        common = os.path.commonpath((left_id, right_id))
    except ValueError:
        return True
    return os.path.normcase(common) not in {
        os.path.normcase(left_id),
        os.path.normcase(right_id),
    }


def _manifest_payload(manifest: VivadoProjectManifest) -> dict[str, Any]:
    return {**manifest.to_dict(), "sha256": manifest.sha256}


def _manifest_refusal_reasons(manifest: VivadoProjectManifest) -> tuple[str, ...]:
    reasons: list[str] = []
    for label, values in (
        ("custom IP repositories", manifest.custom_ip_repository_paths),
        ("custom board repositories", manifest.custom_board_repository_paths),
        ("include directories", manifest.include_directory_values),
        (
            "Verilog transitive-input directives",
            manifest.verilog_transitive_input_directive_files,
        ),
        (
            "VHDL transitive-input directives",
            manifest.vhdl_transitive_input_directive_files,
        ),
        ("opaque IP containers", manifest.refused_core_container_files),
        ("unsafe dependency roots", manifest.refused_dependency_roots),
        ("unsafe fileset roots", manifest.refused_fileset_roots),
        ("unsupported block-design paths", manifest.refused_block_design_files),
        (
            "unsupported IP-configuration paths",
            manifest.refused_ip_configuration_files,
        ),
        ("refused run argument values", manifest.refused_run_argument_values),
        ("unsafe run state paths", manifest.refused_run_state_paths),
        ("refused active file modes", manifest.refused_active_file_modes),
    ):
        if values:
            reasons.append(f"{label}={len(values)}")
    for status, label in (
        ("outside", "outside references"),
        ("missing", "missing references"),
        ("unresolved", "unresolved references"),
        ("unreadable", "unreadable references"),
    ):
        count = sum(
            reference.status == status
            for reference in manifest.blocking_file_references
        )
        if count:
            reasons.append(f"{label}={count}")
    return tuple(reasons)


def _require_complete_manifest(
    manifest: VivadoProjectManifest,
    *,
    label: str,
) -> None:
    if manifest.complete:
        return
    detail = ", ".join(_manifest_refusal_reasons(manifest)) or "unknown reason"
    raise ValueError(f"{label} Vivado project manifest is incomplete: {detail}")


def _vivado_command(value: str | None) -> str:
    # Planning deliberately does not discover or start a tool. A live run may
    # receive an absolute operator-selected launcher; otherwise discovery is
    # deferred to the admitted executor so a missing tool gets a terminal fact.
    return str(value).strip() if value and str(value).strip() else "vivado"


def _path_within(root: Path, candidate: Path) -> bool:
    try:
        common = os.path.commonpath(
            (canonical_path_identity(root), canonical_path_identity(candidate))
        )
    except ValueError:
        return False
    return os.path.normcase(common) == os.path.normcase(canonical_path_identity(root))


def _live_vivado_command(
    selected: str | None,
    *,
    source_root: Path,
    workspace_root: Path,
) -> str:
    """Pin live execution to effect-free vendor/operator discovery.

    Live G1 execution requires one launcher under a package-known standard AMD
    installation layout. An explicit CLI value may only confirm, never
    replace, that discovered path; PATH and environment overrides are not live
    launcher authorities.
    """

    discovered = find_trusted_vendor_tool_path("vivado")
    if not discovered:
        if selected and str(selected).strip():
            raise ValueError(
                "--vivado cannot supply an undiscovered launcher; configure the "
                "standard AMD Vivado installation or install Vivado"
            )
        raise ValueError(
            "no Vivado launcher exists under a package-known AMD installation root"
        )
    launcher = canonical_path(discovered)
    if not launcher.is_file():
        raise ValueError(f"discovered Vivado launcher is not a file: {launcher}")
    if _path_within(source_root, launcher) or _path_within(workspace_root, launcher):
        raise ValueError("Vivado launcher must not come from source or workspace content")
    leaf = launcher.name.casefold()
    if leaf not in {"vivado", "vivado.exe", "vivado.bat"}:
        raise ValueError(f"discovered launcher is not Vivado: {launcher}")
    if selected and str(selected).strip():
        chosen = canonical_path(str(selected).strip())
        if canonical_path_identity(chosen) != canonical_path_identity(launcher):
            raise ValueError("--vivado must exactly match the discovered Vivado launcher")
    return str(launcher)


def _validate_selected_runs(
    manifest: VivadoProjectManifest,
    *,
    synth_run: str,
    impl_run: str,
) -> None:
    synth_matches = tuple(run for run in manifest.runs if run.name == synth_run)
    impl_matches = tuple(run for run in manifest.runs if run.name == impl_run)
    if len(synth_matches) != 1 or len(impl_matches) != 1:
        raise ValueError("selected Vivado runs must each resolve exactly once")
    synth = synth_matches[0]
    impl = impl_matches[0]
    design_sets = tuple(
        fileset
        for fileset in manifest.filesets
        if fileset.kind == "DesignSrcs" and fileset.top == manifest.top
    )
    if not design_sets:
        raise ValueError("manifest has no primary design fileset for the selected top")
    primary = sorted(
        design_sets,
        key=lambda item: (item.name != "sources_1", item.name),
    )[0]
    constraint_sets = {
        fileset.name for fileset in manifest.filesets if fileset.kind == "Constrs"
    }
    if "synth" not in synth.kind.casefold() or "synth" in impl.kind.casefold():
        raise ValueError("selected Vivado runs have swapped or unsupported run kinds")
    if synth.source_set != primary.name:
        raise ValueError("selected synthesis run does not use the primary design fileset")
    if synth.part != manifest.part or impl.part != manifest.part:
        raise ValueError("selected Vivado run part differs from the project part")
    if (
        not synth.constraints_set
        or synth.constraints_set not in constraint_sets
        or impl.constraints_set != synth.constraints_set
    ):
        raise ValueError("selected Vivado runs do not share one declared constraint set")
    if impl.synthesis_run != synth.name:
        raise ValueError("selected implementation run is not linked to synthesis")


def _planned_step(
    manifest: VivadoProjectManifest,
    *,
    phase: str,
    output_dir: Path,
    command: str,
    jobs: int,
    synth_run: str,
    impl_run: str,
) -> dict[str, Any]:
    _validate_selected_runs(
        manifest,
        synth_run=synth_run,
        impl_run=impl_run,
    )
    project = manifest.project_root / Path(manifest.project.path)
    argv = build_vivado_flow_argv(
        phase,
        project,
        project_root=manifest.project_root,
        output_dir=output_dir,
        expected_part=manifest.part,
        expected_top=manifest.top,
        expected_board_part=manifest.board_part,
        synth_run=synth_run,
        impl_run=impl_run,
        jobs=jobs,
        command=command,
    )
    trusted = trusted_vivado_tcl()
    return {
        "schema": PLAN_SCHEMA,
        "phase": phase,
        "manifest_sha256": manifest.sha256,
        "source_identity_sha256": manifest.source_identity_sha256,
        "trusted_tcl_sha256": trusted.sha256,
        "trusted_tcl_path": trusted.path,
        "project_root": str(manifest.project_root),
        "output_dir": str(output_dir),
        "argv": argv,
        "effects": ["filesystem_write", "process_control", "process_spawn"],
        "network_capability_requested": False,
        "secret_capability_requested": False,
        "os_network_confinement_claimed": False,
        "os_secret_isolation_claimed": False,
        "promotion": False,
        "security_boundary_claimed": False,
    }


def _output_dir(root: Path, base: str, run_id: str, phase: str) -> Path:
    raw = Path(base)
    base_path = raw if raw.is_absolute() else root / raw
    return canonical_path(base_path / run_id / phase)


def _expected_outputs(root: Path, output_dir: Path, phase: str) -> tuple[str, ...]:
    return expected_vivado_output_paths(root, output_dir, phase)


def _read_summary(
    path: Path,
    *,
    phase: str,
    project_file: str | Path,
    part: str,
    board_part: str,
    top: str,
    synth_run: str,
    impl_run: str,
    jobs: int,
    retained_payload: bytes | None = None,
) -> dict[str, Any]:
    """Parse one exact package-owned flow summary from one byte snapshot."""

    display = str(path)
    try:
        if retained_payload is None:
            if path.is_symlink() or not path.is_file():
                status = "missing" if not path.exists() else "unparseable"
                return {
                    "identity": {
                        "kind": "flow_summary",
                        "status": status,
                        "path": display,
                        "sha256": None,
                        "byte_length": None,
                        "metrics": {},
                        "error": (
                            "flow summary is not a regular non-symlink file"
                        ),
                    },
                    "values": {},
                }
            with path.open("rb") as handle:
                before = os.fstat(handle.fileno())
                if before.st_size > 1024 * 1024:
                    raise ValueError("flow summary exceeds the parser bound")
                payload = handle.read(1024 * 1024 + 1)
                after = os.fstat(handle.fileno())
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
            if (
                before_identity != after_identity
                or len(payload) != after.st_size
                or len(payload) > 1024 * 1024
            ):
                raise ValueError("flow summary changed while it was read")
        else:
            if not isinstance(retained_payload, bytes):
                raise TypeError("retained flow summary payload must be bytes")
            payload = retained_payload
            if len(payload) > 1024 * 1024:
                raise ValueError("flow summary exceeds the parser bound")
        text = payload.decode("utf-8-sig")
    except (OSError, TypeError, UnicodeError, ValueError) as exc:
        return {
            "identity": {
                "kind": "flow_summary",
                "status": "unparseable",
                "path": display,
                "sha256": None,
                "byte_length": None,
                "metrics": {},
                "error": str(exc),
            },
            "values": {},
            "error": str(exc),
        }
    digest = hashlib.sha256(payload).hexdigest()
    byte_length = len(payload)

    def unparseable(error: str) -> dict[str, Any]:
        return {
            "identity": {
                "kind": "flow_summary",
                "status": "unparseable",
                "path": display,
                "sha256": digest,
                "byte_length": byte_length,
                "metrics": {},
                "error": error,
            },
            "values": {},
            "error": error,
        }

    identity = {
        "kind": "flow_summary",
        "status": "parsed",
        "path": display,
        "sha256": digest,
        "byte_length": byte_length,
        "metrics": {},
        "error": "",
    }
    values: dict[str, str] = {}
    for line in text.splitlines():
        if not line:
            continue
        if "=" not in line:
            return unparseable("flow summary contains a malformed line")
        key, value = line.split("=", 1)
        if not _SUMMARY_KEY.fullmatch(key):
            return unparseable("flow summary contains an invalid key")
        if key in values:
            return unparseable(f"flow summary repeats key {key}")
        values[key] = value

    common = {
        "schema": "daedalus-vivado-flow-summary/1",
        "phase": phase,
        "part": str(part),
        "board_part": str(board_part),
        "top": str(top),
        "synth_run": str(synth_run),
        "impl_run": str(impl_run),
    }
    for key, expected in common.items():
        if values.get(key) != expected:
            return unparseable(
                f"flow summary {key} does not match the execution plan"
            )
    tool = values.get("tool", "")
    if not _VIVADO_SHORT_VERSION.search(tool):
        return unparseable("flow summary has no parseable Vivado version")
    try:
        if canonical_path_identity(values.get("project", "")) != (
            canonical_path_identity(project_file)
        ):
            return unparseable(
                "flow summary project does not match the execution plan"
            )
    except (OSError, TypeError, ValueError):
        return unparseable("flow summary project path is invalid")

    phase_keys = {
        "inspect": {
            "synth_status",
            "synth_progress",
            "impl_status",
            "impl_progress",
            "ip_count",
            "locked_ip_count",
        },
        "synth": {
            "ip_cache",
            "regenerated_ip_source_count",
            "status",
            "progress",
            "jobs",
        },
        "impl": {
            "fresh_synthesis",
            "ip_cache",
            "regenerated_ip_source_count",
            "synth_status",
            "synth_progress",
            "status",
            "progress",
            "jobs",
        },
    }
    common_keys = set(common) | {"tool", "project"}
    expected_keys = common_keys | phase_keys[phase]
    if set(values) != expected_keys:
        return unparseable(
            "flow summary keys do not match the package-owned phase schema"
        )

    if phase == "inspect":
        for key in (
            "synth_status",
            "synth_progress",
            "impl_status",
            "impl_progress",
        ):
            if not values[key]:
                return unparseable(f"flow summary {key} is empty")
        for key in ("ip_count", "locked_ip_count"):
            if not values[key].isdigit():
                return unparseable(f"flow summary {key} is not an integer")
        if int(values["locked_ip_count"]) > int(values["ip_count"]):
            return unparseable("flow summary locked IP count exceeds total IP count")
    else:
        if values["ip_cache"] != "disabled":
            return unparseable("flow summary does not prove disabled IP cache")
        if not values["regenerated_ip_source_count"].isdigit():
            return unparseable(
                "flow summary regenerated IP source count is not an integer"
            )
        if values["jobs"] != str(jobs):
            return unparseable("flow summary jobs does not match the execution plan")
        if "complete" not in values["status"].casefold() or values["progress"] != "100%":
            return unparseable("flow summary phase did not reach Complete/100%")
        if phase == "impl" and (
            values["fresh_synthesis"] != "1"
            or "complete" not in values["synth_status"].casefold()
            or values["synth_progress"] != "100%"
        ):
            return unparseable(
                "flow summary does not prove fresh synthesis Complete/100%"
            )
    return {"identity": identity, "values": dict(sorted(values.items()))}


def _parse_phase_reports(
    output_dir: Path,
    phase: str,
    *,
    project_file: str | Path,
    part: str,
    board_part: str,
    top: str,
    synth_run: str,
    impl_run: str,
    jobs: int,
) -> tuple[dict[str, VivadoReportResult], dict[str, Any]]:
    summary = _read_summary(
        output_dir / f"{phase}_summary.txt",
        phase=phase,
        project_file=project_file,
        part=part,
        board_part=board_part,
        top=top,
        synth_run=synth_run,
        impl_run=impl_run,
        jobs=jobs,
    )
    if phase == "inspect":
        return {}, summary
    reports: dict[str, VivadoReportResult] = {
        "utilization": parse_vivado_report("utilization", output_dir / "utilization.rpt"),
        "timing": parse_vivado_report("timing", output_dir / "timing_summary.rpt"),
        "drc": parse_vivado_report("drc", output_dir / "drc.rpt"),
        "methodology": parse_vivado_report("methodology", output_dir / "methodology.rpt"),
    }
    if phase == "impl":
        reports["route_status"] = parse_vivado_report(
            "route_status", output_dir / "route_status.rpt"
        )
    return reports, summary


def _retained_native_payload(
    store: ArtifactStore,
    result: ExecutionResult,
    filename: str,
) -> tuple[bytes | None, str]:
    matches = tuple(
        artifact
        for artifact in result.artifacts
        if Path(artifact.path).name == filename
    )
    missing = tuple(
        path for path in result.missing_artifact_paths if Path(path).name == filename
    )
    if not matches and len(missing) == 1:
        return None, f"retained-missing:{missing[0]}"
    if len(matches) != 1 or missing:
        raise EdaExecutionError(
            f"retained EDA result has no unique output state for {filename!r}"
        )
    artifact = matches[0]
    locator = store.verify(
        store.load_locator(_locator_digest(artifact.locator))
    )
    if (
        locator.artifact_sha256 != artifact.sha256
        or locator.byte_length != artifact.byte_length
    ):
        raise EdaExecutionError(
            f"retained EDA locator disagrees with {filename!r} identity"
        )
    payload = store.get_bytes(locator.artifact_sha256)
    return payload, artifact.locator


def _parse_retained_phase_reports(
    store: ArtifactStore,
    result: ExecutionResult,
    phase: str,
    *,
    project_file: str | Path,
    part: str,
    board_part: str,
    top: str,
    synth_run: str,
    impl_run: str,
    jobs: int,
) -> tuple[dict[str, VivadoReportResult], dict[str, Any]]:
    summary_payload, summary_display = _retained_native_payload(
        store,
        result,
        f"{phase}_summary.txt",
    )
    if summary_payload is None:
        summary = {
            "identity": {
                "kind": "flow_summary",
                "status": "missing",
                "path": summary_display,
                "sha256": None,
                "byte_length": None,
                "metrics": {},
                "error": "declared Vivado summary was not retained",
            },
            "values": {},
        }
    else:
        summary = _read_summary(
            Path(summary_display),
            phase=phase,
            project_file=project_file,
            part=part,
            board_part=board_part,
            top=top,
            synth_run=synth_run,
            impl_run=impl_run,
            jobs=jobs,
            retained_payload=summary_payload,
        )
    if phase == "inspect":
        return {}, summary
    reports: dict[str, VivadoReportResult] = {}
    for kind in ("utilization", "timing", "drc", "methodology"):
        filename = _REPORT_FILENAMES[kind]
        payload, display = _retained_native_payload(store, result, filename)
        reports[kind] = (
            VivadoReportResult(
                kind=kind,
                status="missing",
                path=display,
                sha256=None,
                byte_length=None,
                error="declared Vivado report was not retained",
            )
            if payload is None
            else parse_vivado_report_bytes(kind, payload, display_path=display)
        )
    if phase == "impl":
        filename = _REPORT_FILENAMES["route_status"]
        payload, display = _retained_native_payload(store, result, filename)
        reports["route_status"] = (
            VivadoReportResult(
                kind="route_status",
                status="missing",
                path=display,
                sha256=None,
                byte_length=None,
                error="declared Vivado report was not retained",
            )
            if payload is None
            else parse_vivado_report_bytes(
                "route_status",
                payload,
                display_path=display,
            )
        )
    return reports, summary


_REPORT_FILENAMES = {
    "utilization": "utilization.rpt",
    "timing": "timing_summary.rpt",
    "drc": "drc.rpt",
    "methodology": "methodology.rpt",
    "route_status": "route_status.rpt",
}


def _phase_artifact_binding(
    *,
    phase: str,
    result: ExecutionResult,
    reports: Mapping[str, VivadoReportResult],
    summary: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove parsed identities equal the already-retained native bytes."""

    by_leaf: dict[str, list[Any]] = {}
    for artifact in result.artifacts:
        by_leaf.setdefault(Path(artifact.path).name, []).append(artifact)
    checks: dict[str, Any] = {}

    def bind(name: str, filename: str, identity: Mapping[str, Any]) -> None:
        retained = by_leaf.get(filename, [])
        parsed_sha = identity.get("sha256")
        parsed_size = identity.get("byte_length")
        passed = (
            len(retained) == 1
            and identity.get("status") == "parsed"
            and isinstance(parsed_sha, str)
            and parsed_sha == retained[0].sha256
            and isinstance(parsed_size, int)
            and parsed_size == retained[0].byte_length
        )
        checks[name] = {
            "status": "passed" if passed else "failed",
            "filename": filename,
            "parsed_sha256": parsed_sha,
            "parsed_byte_length": parsed_size,
            "retained_sha256": retained[0].sha256 if len(retained) == 1 else None,
            "retained_byte_length": (
                retained[0].byte_length if len(retained) == 1 else None
            ),
            "retained_matches": len(retained),
        }

    summary_identity = summary.get("identity", {})
    bind(
        "summary",
        f"{phase}_summary.txt",
        summary_identity if isinstance(summary_identity, Mapping) else {},
    )
    for name, report in reports.items():
        if name == "messages":
            passed = (
                isinstance(result.stdout_sha256, str)
                and report.sha256 == result.stdout_sha256
            )
            checks[name] = {
                "status": "passed" if passed else "failed",
                "parsed_sha256": report.sha256,
                "retained_sha256": result.stdout_sha256,
                "retained_locator": result.stdout_locator,
            }
            continue
        filename = _REPORT_FILENAMES.get(name)
        if filename is not None:
            bind(name, filename, report.to_dict())
    return {
        "status": (
            "passed"
            if checks and all(row["status"] == "passed" for row in checks.values())
            else "failed"
        ),
        "checks": dict(sorted(checks.items())),
    }


def _rule_report_passed(report: VivadoReportResult) -> bool:
    if report.status != "parsed":
        return False
    checks_found = report.metrics.get("checks_found")
    if isinstance(checks_found, bool) or not isinstance(checks_found, int):
        return False
    if checks_found != 0:
        return False
    counts = report.metrics.get("severity_counts", {})
    if not isinstance(counts, Mapping):
        return False
    return not any(int(value or 0) > 0 for value in counts.values())


def _verdict_and_dimensions(
    phase: str,
    result: ExecutionResult,
    reports: Mapping[str, VivadoReportResult],
) -> tuple[str, dict[str, str]]:
    dimensions = default_dimensions(phase)
    if result.status == "timeout":
        return "cancelled", dimensions
    if result.status in {"missing", "error"}:
        return "error", dimensions
    if result.status != "ok":
        return "failed", dimensions
    if phase == "inspect":
        return "inconclusive", dimensions

    dimensions["synthesis"] = "passed"
    timing = reports["timing"]
    if timing.status == "parsed":
        checks = timing.metrics.get("check_timing", {})
        checks_clean = isinstance(checks, Mapping) and not any(
            int(value or 0) > 0 for value in checks.values()
        )
        dimensions["timing"] = (
            "passed"
            if bool(timing.metrics.get("constraints_met")) and checks_clean
            else "failed"
        )
    else:
        dimensions["timing"] = "failed"

    dimensions["drc"] = "passed" if _rule_report_passed(reports["drc"]) else "failed"
    dimensions["methodology"] = (
        "passed" if _rule_report_passed(reports["methodology"]) else "failed"
    )
    if phase == "impl":
        route = reports["route_status"]
        dimensions["implementation"] = (
            "passed"
            if route.status == "parsed" and bool(route.metrics.get("complete"))
            else "failed"
        )
    failed = any(value == "failed" for value in dimensions.values())
    # Even an entirely clean build remains inconclusive until the explicitly
    # not-run assurance dimensions have independent evidence.
    return ("failed" if failed else "inconclusive"), dimensions


def _locator_digest(uri: str) -> str:
    prefix = "artifact-locator:sha256:"
    if not str(uri).startswith(prefix):
        raise ValueError(f"invalid artifact locator URI: {uri}")
    return str(uri)[len(prefix) :]


def _stored_artifact(
    store: ArtifactStore,
    payload: bytes,
    *,
    name: str,
    role: str,
    media_type: str,
    provenance: ContractProvenance,
    expected_sha256: str | None = None,
    local_path: str = "",
) -> ChipArtifact:
    locator = store.put_bytes(
        payload,
        expected_sha256=expected_sha256,
        media_type=media_type,
        metadata={"kind": role, "filename_hint": name},
        provenance=provenance.to_dict(),
    )
    return ChipArtifact.from_locator(
        name=name,
        role=role,
        locator=locator,
        media_type=media_type,
        local_path=local_path,
    )


def _artifact_from_locator(
    store: ArtifactStore,
    *,
    name: str,
    role: str,
    locator_uri: str,
    expected_sha256: str,
    expected_payload: bytes | None = None,
    media_type: str = "application/octet-stream",
    local_path: str = "",
) -> ChipArtifact:
    locator = store.verify(store.load_locator(_locator_digest(locator_uri)))
    if locator.artifact_sha256 != expected_sha256:
        raise ValueError(f"{name} locator does not bind its declared artifact digest")
    if expected_payload is not None and store.get_bytes(expected_sha256) != expected_payload:
        raise ValueError(f"{name} retained bytes do not match the recomputed artifact")
    return ChipArtifact.from_locator(
        name=name,
        role=role,
        locator=locator,
        media_type=media_type,
        local_path=local_path,
    )


def _retained_artifacts(
    *,
    store: ArtifactStore,
    source_manifest: VivadoProjectManifest,
    post_source_manifest: VivadoProjectManifest,
    workspace_manifest: VivadoProjectManifest,
    post_workspace_manifest: VivadoProjectManifest,
    trusted_payload: bytes,
    trusted_sha256: str,
    mission: Any,
    attempt: Any,
    runtime_manifest: Any,
    execution_plan: EdaExecutionPlan,
    lease: Any,
    result: ExecutionResult,
    created_at: str,
) -> list[ChipArtifact]:
    source_revision = source_manifest.source_identity_sha256
    common = ContractProvenance(
        origin="daedalus.chip_design.cli",
        source_revision=source_revision,
        created_at=created_at,
        input_digests=tuple(
            sorted(
                {
                    source_manifest.project.sha256,
                    source_manifest.sha256,
                    post_source_manifest.sha256,
                    workspace_manifest.sha256,
                    post_workspace_manifest.sha256,
                    trusted_sha256,
                    runtime_manifest.digest,
                    execution_plan.digest,
                }
            )
        ),
    )
    artifacts = [
        _stored_artifact(
            store,
            source_manifest.canonical_bytes,
            name="source-manifest.json",
            role="authoritative_manifest",
            media_type="application/json",
            provenance=common,
            expected_sha256=source_manifest.sha256,
        ),
        _stored_artifact(
            store,
            workspace_manifest.canonical_bytes,
            name="workspace-manifest.json",
            role="workspace_manifest",
            media_type="application/json",
            provenance=common,
            expected_sha256=workspace_manifest.sha256,
        ),
        _stored_artifact(
            store,
            trusted_payload,
            name="vivado_project_flow.tcl",
            role="trusted_tcl",
            media_type="text/x-tcl",
            provenance=common,
            expected_sha256=trusted_sha256,
        ),
        _stored_artifact(
            store,
            runtime_manifest.to_json().encode("ascii"),
            name="runtime-manifest.json",
            role="runtime_manifest",
            media_type="application/json",
            provenance=runtime_manifest.provenance,
            expected_sha256=runtime_manifest.digest,
        ),
        _stored_artifact(
            store,
            canonical_json(execution_plan.to_dict()).encode("ascii"),
            name="eda-execution-plan.json",
            role="execution_plan",
            media_type="application/json",
            provenance=common,
            expected_sha256=execution_plan.digest,
        ),
        _stored_artifact(
            store,
            mission.to_json().encode("ascii"),
            name="mission.json",
            role="mission_contract",
            media_type="application/json",
            provenance=mission.provenance,
            expected_sha256=mission.digest,
        ),
        _stored_artifact(
            store,
            attempt.to_json().encode("ascii"),
            name="attempt.json",
            role="attempt_contract",
            media_type="application/json",
            provenance=attempt.provenance,
            expected_sha256=attempt.digest,
        ),
        _stored_artifact(
            store,
            lease.policy_decision.to_json().encode("ascii"),
            name="policy-decision.json",
            role="policy_decision",
            media_type="application/json",
            provenance=lease.policy_decision.provenance,
            expected_sha256=lease.policy_decision.digest,
        ),
    ]
    post_manifest_rows = (
        (
            "post-source-manifest.json",
            "post_authoritative_manifest",
            post_source_manifest,
            result.post_authoritative_manifest_locator,
            result.post_authoritative_manifest_sha256,
        ),
        (
            "post-workspace-manifest.json",
            "post_workspace_manifest",
            post_workspace_manifest,
            result.post_workspace_manifest_locator,
            result.post_workspace_manifest_sha256,
        ),
    )
    for name, role, manifest, uri, digest in post_manifest_rows:
        if uri is not None and digest is not None:
            if digest != manifest.sha256:
                raise ValueError(
                    f"{name} result digest does not match the recomputed manifest"
                )
            artifacts.append(
                _artifact_from_locator(
                    store,
                    name=name,
                    role=role,
                    locator_uri=uri,
                    expected_sha256=digest,
                    expected_payload=manifest.canonical_bytes,
                    media_type="application/json",
                )
            )
        else:
            artifacts.append(
                _stored_artifact(
                    store,
                    manifest.canonical_bytes,
                    name=name,
                    role=role,
                    media_type="application/json",
                    provenance=common,
                    expected_sha256=manifest.sha256,
                )
            )
    for native in result.artifacts:
        artifacts.append(
            _artifact_from_locator(
                store,
                name=Path(native.path).name,
                role="vivado_native_output",
                locator_uri=native.locator,
                expected_sha256=native.sha256,
                local_path=native.path,
            )
        )
    console_rows = (
        ("vivado-stdout.log", "console_stdout", result.stdout_locator, result.stdout_sha256),
        ("vivado-stderr.log", "console_stderr", result.stderr_locator, result.stderr_sha256),
        (
            "eda-execution-receipt.json",
            "execution_receipt",
            result.receipt_locator,
            result.receipt_sha256,
        ),
    )
    for name, role, uri, digest in console_rows:
        if uri and digest:
            artifacts.append(
                _artifact_from_locator(
                    store,
                    name=name,
                    role=role,
                    locator_uri=uri,
                    expected_sha256=digest,
                )
            )
    return artifacts


def _media_provenance(
    *, source_revision: str, created_at: str, input_digests: Sequence[str]
) -> ContractProvenance:
    return ContractProvenance(
        origin="daedalus.chip_design.cli",
        source_revision=source_revision,
        created_at=created_at,
        input_digests=tuple(sorted(set(input_digests))),
    )


def _retained_payload_from_locator(
    store: ArtifactStore,
    *,
    locator_uri: str,
    expected_sha256: str,
    label: str,
) -> tuple[bytes, Any]:
    locator = store.verify(store.load_locator(_locator_digest(locator_uri)))
    if locator.artifact_sha256 != expected_sha256:
        raise ValueError(f"{label} locator does not bind its declared digest")
    return store.get_bytes(expected_sha256), locator


def _retained_json_from_locator(
    store: ArtifactStore,
    *,
    locator_uri: str,
    expected_sha256: str,
    label: str,
) -> _RetainedJsonArtifact:
    payload, locator = _retained_payload_from_locator(
        store,
        locator_uri=locator_uri,
        expected_sha256=expected_sha256,
        label=label,
    )
    body = _strict_canonical_object(payload, label=label)
    return _RetainedJsonArtifact(
        body=body,
        payload=payload,
        sha256=locator.artifact_sha256,
        locator_uri=locator.locator_uri,
    )


def _validate_retained_manifest(
    retained: _RetainedJsonArtifact,
    *,
    expected_source_identity_sha256: str,
    label: str,
    require_complete: bool = True,
) -> None:
    body = retained.body
    project = body.get("project")
    if (
        body.get("schema") != MANIFEST_SCHEMA
        or (require_complete and body.get("complete") is not True)
        or body.get("source_identity_sha256")
        != expected_source_identity_sha256
        or not isinstance(project, Mapping)
        or not isinstance(project.get("sha256"), str)
    ):
        raise ValueError(f"{label} is not a complete plan-bound Vivado manifest")


def _retained_publication_artifacts(
    *,
    store: ArtifactStore,
    source_manifest: _RetainedJsonArtifact,
    workspace_manifest: _RetainedJsonArtifact,
    post_source_manifest: _RetainedJsonArtifact | None,
    post_workspace_manifest: _RetainedJsonArtifact | None,
    trusted_payload: bytes,
    trusted_locator_uri: str,
    mission: Any,
    attempt: Any,
    runtime_manifest: Any,
    execution_plan: EdaExecutionPlan,
    policy_decision: Any,
    retained: RetainedExecutionObservation,
    created_at: str,
) -> list[ChipArtifact]:
    result = retained.result
    source_identity = str(source_manifest.body["source_identity_sha256"])
    inputs = {
        source_manifest.sha256,
        workspace_manifest.sha256,
        execution_plan.trusted_tcl_sha256,
        runtime_manifest.digest,
        execution_plan.digest,
        retained.result.receipt_sha256,
    }
    if post_source_manifest is not None:
        inputs.add(post_source_manifest.sha256)
    if post_workspace_manifest is not None:
        inputs.add(post_workspace_manifest.sha256)
    common = ContractProvenance(
        origin="daedalus.chip_design.cli",
        source_revision=source_identity,
        created_at=created_at,
        input_digests=tuple(sorted(value for value in inputs if value is not None)),
    )
    artifacts = [
        _artifact_from_locator(
            store,
            name="source-manifest.json",
            role="authoritative_manifest",
            locator_uri=source_manifest.locator_uri,
            expected_sha256=source_manifest.sha256,
            expected_payload=source_manifest.payload,
            media_type="application/json",
        ),
        _artifact_from_locator(
            store,
            name="workspace-manifest.json",
            role="workspace_manifest",
            locator_uri=workspace_manifest.locator_uri,
            expected_sha256=workspace_manifest.sha256,
            expected_payload=workspace_manifest.payload,
            media_type="application/json",
        ),
        _artifact_from_locator(
            store,
            name="vivado_project_flow.tcl",
            role="trusted_tcl",
            locator_uri=trusted_locator_uri,
            expected_sha256=execution_plan.trusted_tcl_sha256,
            expected_payload=trusted_payload,
            media_type="text/x-tcl",
        ),
        _stored_artifact(
            store,
            runtime_manifest.to_json().encode("ascii"),
            name="runtime-manifest.json",
            role="runtime_manifest",
            media_type="application/json",
            provenance=runtime_manifest.provenance,
            expected_sha256=runtime_manifest.digest,
        ),
        _stored_artifact(
            store,
            canonical_json(execution_plan.to_dict()).encode("ascii"),
            name="eda-execution-plan.json",
            role="execution_plan",
            media_type="application/json",
            provenance=common,
            expected_sha256=execution_plan.digest,
        ),
        _stored_artifact(
            store,
            mission.to_json().encode("ascii"),
            name="mission.json",
            role="mission_contract",
            media_type="application/json",
            provenance=mission.provenance,
            expected_sha256=mission.digest,
        ),
        _stored_artifact(
            store,
            attempt.to_json().encode("ascii"),
            name="attempt.json",
            role="attempt_contract",
            media_type="application/json",
            provenance=attempt.provenance,
            expected_sha256=attempt.digest,
        ),
        _stored_artifact(
            store,
            policy_decision.to_json().encode("ascii"),
            name="policy-decision.json",
            role="policy_decision",
            media_type="application/json",
            provenance=policy_decision.provenance,
            expected_sha256=policy_decision.digest,
        ),
    ]
    for name, role, manifest in (
        (
            "post-source-manifest.json",
            "post_authoritative_manifest",
            post_source_manifest,
        ),
        (
            "post-workspace-manifest.json",
            "post_workspace_manifest",
            post_workspace_manifest,
        ),
    ):
        if manifest is not None:
            artifacts.append(
                _artifact_from_locator(
                    store,
                    name=name,
                    role=role,
                    locator_uri=manifest.locator_uri,
                    expected_sha256=manifest.sha256,
                    expected_payload=manifest.payload,
                    media_type="application/json",
                )
            )
    for native in result.artifacts:
        artifacts.append(
            _artifact_from_locator(
                store,
                name=Path(native.path).name,
                role="vivado_native_output",
                locator_uri=native.locator,
                expected_sha256=native.sha256,
                local_path=native.path,
            )
        )
    for name, role, uri, digest, expected_payload in (
        (
            "vivado-stdout.log",
            "console_stdout",
            result.stdout_locator,
            result.stdout_sha256,
            None,
        ),
        (
            "vivado-stderr.log",
            "console_stderr",
            result.stderr_locator,
            result.stderr_sha256,
            None,
        ),
        (
            "eda-execution-receipt.json",
            "execution_receipt",
            result.receipt_locator,
            result.receipt_sha256,
            retained.receipt_payload,
        ),
    ):
        if uri is None or digest is None:
            raise ValueError(f"terminal EDA result is missing {role}")
        artifacts.append(
            _artifact_from_locator(
                store,
                name=name,
                role=role,
                locator_uri=uri,
                expected_sha256=digest,
                expected_payload=expected_payload,
                media_type=("application/json" if role == "execution_receipt" else "text/plain"),
            )
        )
    return artifacts


def _finalize_phase_publication(
    *,
    authority_root: Path,
    authority_source_revision: str,
    mission_id: str,
    attempt_id: str,
    run_id: str,
    phase: str,
    authorization: Any,
    execution: EffectExecutionRequest,
    retained: RetainedExecutionObservation,
    store: ArtifactStore,
    terminal_record: Mapping[str, Any],
    authority_head_record_sha256: str,
    subject_record_sha256: str,
    execution_record_sha256: str,
    recovered: bool,
) -> dict[str, Any]:
    result = retained.result
    plan = retained.plan
    terminal = result.terminal_receipt
    if terminal is None or result.start_receipt is None:
        raise EdaExecutionError("publication requires a retained terminal lifecycle")
    if (
        phase != plan.phase
        or execution.digest != result.start_receipt.execution_request_sha256
        or authorization.request.mission_id != mission_id
        or authorization.request.attempt_id != attempt_id
    ):
        raise EdaExecutionError("publication identity does not match retained execution")
    created_at = terminal.finished_at

    if (
        result.pre_authoritative_manifest_locator is None
        or result.pre_workspace_manifest_locator is None
        or result.trusted_tcl_locator is None
    ):
        raise EdaExecutionError("retained execution lacks immutable pre-run inputs")
    source_manifest = _retained_json_from_locator(
        store,
        locator_uri=result.pre_authoritative_manifest_locator,
        expected_sha256=plan.source_manifest_sha256,
        label="retained authoritative manifest",
    )
    workspace_manifest = _retained_json_from_locator(
        store,
        locator_uri=result.pre_workspace_manifest_locator,
        expected_sha256=plan.workspace_manifest_sha256,
        label="retained workspace manifest",
    )
    _validate_retained_manifest(
        source_manifest,
        expected_source_identity_sha256=plan.source_identity_sha256,
        label="retained authoritative manifest",
    )
    _validate_retained_manifest(
        workspace_manifest,
        expected_source_identity_sha256=plan.source_identity_sha256,
        label="retained workspace manifest",
    )
    trusted_payload, trusted_locator = _retained_payload_from_locator(
        store,
        locator_uri=result.trusted_tcl_locator,
        expected_sha256=plan.trusted_tcl_sha256,
        label="retained trusted Tcl",
    )

    post_source_manifest = (
        None
        if result.post_authoritative_manifest_locator is None
        or result.post_authoritative_manifest_sha256 is None
        else _retained_json_from_locator(
            store,
            locator_uri=result.post_authoritative_manifest_locator,
            expected_sha256=result.post_authoritative_manifest_sha256,
            label="retained post-authoritative manifest",
        )
    )
    post_workspace_manifest = (
        None
        if result.post_workspace_manifest_locator is None
        or result.post_workspace_manifest_sha256 is None
        else _retained_json_from_locator(
            store,
            locator_uri=result.post_workspace_manifest_locator,
            expected_sha256=result.post_workspace_manifest_sha256,
            label="retained post-workspace manifest",
        )
    )
    if post_source_manifest is not None:
        _validate_retained_manifest(
            post_source_manifest,
            expected_source_identity_sha256=(
                result.post_authoritative_source_identity_sha256 or ""
            ),
            label="retained post-authoritative manifest",
            require_complete=False,
        )
    if post_workspace_manifest is not None:
        _validate_retained_manifest(
            post_workspace_manifest,
            expected_source_identity_sha256=result.post_source_identity_sha256 or "",
            label="retained post-workspace manifest",
            require_complete=False,
        )

    reports, summary = _parse_retained_phase_reports(
        store,
        result,
        phase,
        project_file=plan.argv[11],
        part=plan.argv[13],
        board_part=plan.argv[14],
        top=plan.argv[15],
        synth_run=plan.argv[16],
        impl_run=plan.argv[17],
        jobs=int(plan.argv[18]),
    )
    if result.stdout_sha256 is None:
        raise EdaExecutionError("terminal EDA result lacks retained stdout")
    reports["messages"] = parse_vivado_message_counts_bytes(
        store.get_bytes(result.stdout_sha256),
        display_path=result.stdout_locator or "retained:vivado-stdout",
    )
    artifact_binding = _phase_artifact_binding(
        phase=phase,
        result=result,
        reports=reports,
        summary=summary,
    )
    verdict, dimensions = _verdict_and_dimensions(phase, result, reports)
    if artifact_binding["status"] != "passed":
        verdict = "failed"

    runtime_manifest = build_chip_runtime_manifest(
        source_revision=authority_source_revision,
        trusted_tcl_sha256=plan.trusted_tcl_sha256,
        launcher_sha256=plan.launcher_sha256,
        execution_plan_sha256=plan.digest,
        created_at=created_at,
    )
    mission, attempt = build_chip_contracts(
        mission_id=mission_id,
        attempt_id=attempt_id,
        phase=phase,
        manifest_sha256=plan.source_manifest_sha256,
        trusted_tcl_sha256=plan.trusted_tcl_sha256,
        runtime_manifest_sha256=runtime_manifest.digest,
        policy_decision_sha256=authorization.policy_decision.digest,
        policy_sha256=authorization.policy_decision.policy_sha256,
        timeout_s=max(1, int(math.ceil(float(plan.timeout_s)))),
        created_at=created_at,
    )
    artifacts = _retained_publication_artifacts(
        store=store,
        source_manifest=source_manifest,
        workspace_manifest=workspace_manifest,
        post_source_manifest=post_source_manifest,
        post_workspace_manifest=post_workspace_manifest,
        trusted_payload=trusted_payload,
        trusted_locator_uri=trusted_locator.locator_uri,
        mission=mission,
        attempt=attempt,
        runtime_manifest=runtime_manifest,
        execution_plan=plan,
        policy_decision=authorization.policy_decision,
        retained=retained,
        created_at=created_at,
    )
    report_payload = {name: report.to_dict() for name, report in reports.items()}
    metrics = {
        "source_manifest_sha256": source_manifest.sha256,
        "workspace_manifest_sha256": workspace_manifest.sha256,
        "post_authoritative_manifest_sha256": (
            None if post_source_manifest is None else post_source_manifest.sha256
        ),
        "post_authoritative_source_identity_sha256": (
            None
            if post_source_manifest is None
            else post_source_manifest.body["source_identity_sha256"]
        ),
        "authoritative_source_unchanged": (
            post_source_manifest is not None
            and post_source_manifest.sha256 == source_manifest.sha256
        ),
        "post_workspace_manifest_sha256": (
            None if post_workspace_manifest is None else post_workspace_manifest.sha256
        ),
        "post_source_identity_sha256": (
            None
            if post_workspace_manifest is None
            else post_workspace_manifest.body["source_identity_sha256"]
        ),
        "authored_source_identity_unchanged": (
            post_workspace_manifest is not None
            and post_workspace_manifest.body["source_identity_sha256"]
            == source_manifest.body["source_identity_sha256"]
        ),
        "runtime_manifest_sha256": runtime_manifest.digest,
        "summary": summary,
        "reports": report_payload,
        "messages": reports["messages"].to_dict(),
        "artifact_binding": artifact_binding,
        "execution_plan": plan.to_dict(),
        "execution_plan_sha256": plan.digest,
        "missing_artifact_paths": list(result.missing_artifact_paths),
        "publication_inputs": "authenticated-ledger-and-cas-only",
    }
    summary_values = summary.get("values", {})
    reported_version = (
        str(summary_values.get("tool", ""))
        if isinstance(summary_values, Mapping)
        else ""
    )
    tool = {
        "id": "vivado",
        "label": "AMD Vivado",
        "selected_command": str(plan.argv[0]),
        "launcher_sha256": plan.launcher_sha256,
        "reported_version": reported_version,
        "ambient_probe_status": "not_run",
        "security_boundary_claimed": False,
    }
    receipt = ChipRunReceipt(
        run_id=run_id,
        mission_id=mission_id,
        attempt_id=attempt_id,
        phase=phase,
        source_revision=plan.source_manifest_sha256,
        manifest_sha256=plan.source_manifest_sha256,
        trusted_tcl_sha256=plan.trusted_tcl_sha256,
        tool=tool,
        execution=result.to_dict(),
        effect_start=result.start_receipt.to_dict(),
        effect_terminal=terminal.to_dict(),
        artifacts=tuple(artifacts),
        metrics=metrics,
        dimensions=dimensions,
        verdict=verdict,
        limitations=_LIMITATIONS,
        created_at=created_at,
    )
    receipt_inputs = [
        attempt.digest,
        source_manifest.sha256,
        workspace_manifest.sha256,
        runtime_manifest.digest,
        plan.digest,
        plan.trusted_tcl_sha256,
        authorization.policy_decision.digest,
        *(artifact.artifact_sha256 for artifact in artifacts),
    ]
    receipt_locator = store.put_bytes(
        receipt.to_json().encode("ascii"),
        expected_sha256=receipt.digest,
        media_type="application/json",
        metadata={
            "kind": "chip_run_receipt",
            "phase": phase,
            "filename_hint": f"{run_id}-chip-receipt.json",
        },
        provenance=_media_provenance(
            source_revision=receipt.source_revision,
            created_at=receipt.created_at,
            input_digests=receipt_inputs,
        ).to_dict(),
    )
    evidence = build_evidence_packet(
        receipt=receipt,
        receipt_locator=receipt_locator,
        attempt=attempt,
        policy_decision_sha256=authorization.policy_decision.digest,
    )
    evidence_locator = store.put_bytes(
        evidence.to_json().encode("ascii"),
        expected_sha256=evidence.digest,
        media_type="application/json",
        metadata={
            "kind": "chip_evidence_packet",
            "phase": phase,
            "filename_hint": f"{run_id}-evidence.json",
        },
        provenance=evidence.provenance.to_dict(),
    )
    publication_record = record_chip_eda_publication(
        evidence_root=write_evidence_root(authority_root, authority_source_revision),
        source_revision=authority_source_revision,
        lease_sha256=authorization.lease.digest,
        execution_id=execution.execution_id,
        execution_request_sha256=execution.digest,
        terminal_receipt_sha256=terminal.receipt_sha256,
        raw_execution_receipt_sha256=str(result.receipt_sha256),
        raw_execution_receipt_locator=str(result.receipt_locator),
        chip_receipt_sha256=receipt.digest,
        chip_receipt_locator=receipt_locator.locator_uri,
        evidence_packet_sha256=evidence.digest,
        evidence_packet_locator=evidence_locator.locator_uri,
        authority_head_record_sha256=authority_head_record_sha256,
        lease_subject_record_sha256=subject_record_sha256,
        lease_execution_record_sha256=execution_record_sha256,
        lease_terminal_record_sha256=str(terminal_record["record_sha256"]),
        finished_at=created_at,
    )
    return {
        "phase": phase,
        "status": result.status,
        "returncode": result.returncode,
        "duration_s": result.duration_s,
        "process_spawned": False if recovered else result.executed,
        "execution_process_spawned": result.executed,
        "recovered": recovered,
        "publication_status": "complete",
        "verdict": verdict,
        "dimensions": dimensions,
        "metrics": metrics,
        "manifest_sha256": source_manifest.sha256,
        "source_identity_sha256": source_manifest.body["source_identity_sha256"],
        "workspace_manifest_sha256": workspace_manifest.sha256,
        "receipt_sha256": receipt.digest,
        "receipt_locator": receipt_locator.locator_uri,
        "evidence_sha256": evidence.digest,
        "evidence_locator": evidence_locator.locator_uri,
        "evaluation_status": evidence.evaluation_status,
        "terminal_record": dict(terminal_record),
        "publication_record_sha256": publication_record["record_sha256"],
        "limitations": list(receipt.limitations),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="daedalus-chip",
        description="Bounded RTL inventory and canonical AMD Vivado project execution.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    status = sub.add_parser("status", help="discover registered EDA tools without probing")
    status.add_argument("--timeout", type=float, default=5.0, help=argparse.SUPPRESS)
    status.add_argument("--json", action="store_true")

    scan = sub.add_parser("scan", help="classify RTL, constraints, projects and EDA scripts")
    scan.add_argument("root", nargs="?", default=".")
    scan.add_argument("--max-files", type=int, default=20_000)
    scan.add_argument("--json", action="store_true")

    classify = sub.add_parser("classify", help="classify explicit paths by extension")
    classify.add_argument("paths", nargs="+")
    classify.add_argument("--json", action="store_true")

    inspect = sub.add_parser("inspect", help="build a read-only manifest for one Vivado XPR")
    inspect.add_argument("project")
    inspect.add_argument("--project-root")
    inspect.add_argument("--json", action="store_true")

    plan = sub.add_parser("plan", help="build the trusted Vivado argv without execution")
    plan.add_argument("project")
    plan.add_argument("--project-root")
    plan.add_argument("--phase", choices=(*_PHASES, "full"), default="full")
    plan.add_argument("--output-dir", default=".daedalus-chip/plans")
    plan.add_argument("--vivado")
    plan.add_argument("--jobs", type=int, default=1)
    plan.add_argument("--synth-run", default="synth_1")
    plan.add_argument("--impl-run", default="impl_1")
    plan.add_argument("--json", action="store_true")

    run = sub.add_parser("run", help="execute package-owned Vivado Tcl in a disjoint workspace")
    run.add_argument("project", help="authoritative source XPR (never written)")
    run.add_argument("--project-root", help="root of the authoritative source project")
    run.add_argument("--workspace-project", required=True, help="matching isolated workspace XPR")
    run.add_argument("--workspace-root", help="root of the isolated workspace project")
    run.add_argument("--authority-root", required=True, help="operator-owned Daedalus checkout")
    run.add_argument(
        "--write-policy",
        default=".agentenv/chip-eda-policy.json",
        help="operator-owned policy JSON under the authority root",
    )
    run.add_argument("--source-revision", required=True, help="40-hex authority checkout revision")
    run.add_argument("--phase", choices=(*_PHASES, "full"), default="full")
    run.add_argument("--output-dir", default=".daedalus-chip/runs")
    run.add_argument("--vivado")
    run.add_argument("--jobs", type=int, default=1)
    run.add_argument("--synth-run", default="synth_1")
    run.add_argument("--impl-run", default="impl_1")
    run.add_argument("--timeout", type=float, default=7200.0)
    run.add_argument("--mission-id", default="chip-vivado")
    run.add_argument(
        "--attempt-id",
        required=True,
        help="stable operator-supplied identity; reuse it to obtain inert restart behavior",
    )
    run.add_argument("--writable-path", action="append", default=[])
    run.add_argument(
        "--confirm-project-writes",
        action="store_true",
        help="confirm that Vivado may mutate the entire isolated workspace",
    )
    run.add_argument("--json", action="store_true")

    tcl = sub.add_parser("tcl", help="plan a raw Tcl invocation; live mode is retired")
    tcl.add_argument("tool", choices=("tclsh", "vivado", "quartus", "yosys", "openroad"))
    tcl.add_argument("script")
    tcl.add_argument("--arg", dest="script_args", action="append", default=[])
    tcl.add_argument("--repo-root", default=".")
    tcl.add_argument("--timeout", type=float, default=3600.0)
    tcl.add_argument("--live", action="store_true")
    _add_legacy_live_arguments(tcl)
    tcl.add_argument("--json", action="store_true")

    lint = sub.add_parser("lint", help="plan Verilog/SystemVerilog lint; live mode is retired")
    lint.add_argument("sources", nargs="+")
    lint.add_argument("--tool", choices=("verilator", "verible"), default="verilator")
    lint.add_argument("--repo-root", default=".")
    lint.add_argument("--top")
    lint.add_argument("-I", "--include", action="append", default=[])
    lint.add_argument("-D", "--define", action="append", default=[])
    lint.add_argument("--timeout", type=float, default=300.0)
    lint.add_argument("--live", action="store_true")
    _add_legacy_live_arguments(lint)
    lint.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "status":
        rows = all_tool_status()
        if args.json:
            print(json.dumps(rows, indent=2, default=str))
        else:
            for row in rows:
                state = "READY" if row["available"] else "MISSING"
                detail = row.get("command_path") or row.get("last_error") or ""
                print(f"{state:<7} {row['id']:<10} {row['label']}: {detail}")
        return 0

    if args.command == "scan":
        try:
            rows = [item.to_dict() for item in discover_sources(args.root, max_files=args.max_files)]
        except ValueError as exc:
            parser.error(str(exc))
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            for row in rows:
                print(f"{row['kind']:<13} {row['language']:<13} {row['path']}")
        return 0

    if args.command == "classify":
        rows = []
        for path in args.paths:
            spec = classify_source(path)
            rows.append(spec.to_dict() if spec else {"path": path, "kind": "unknown"})
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            for row in rows:
                print(f"{row.get('kind', 'unknown'):<13} {row.get('language', ''):<13} {row['path']}")
        return 0

    if args.command in {"tcl", "lint"}:
        if args.live:
            parser.error(
                "raw Tcl/lint live execution is disabled; use 'daedalus-chip run' "
                "with an XPR and the package-owned trusted Vivado flow"
            )
        try:
            root = Path(args.repo_root).resolve()
            command = (
                build_tcl_argv(
                    args.tool,
                    args.script,
                    repo_root=root,
                    script_args=args.script_args,
                )
                if args.command == "tcl"
                else build_rtl_lint_argv(
                    args.tool,
                    args.sources,
                    repo_root=root,
                    top=args.top,
                    include_dirs=args.include,
                    defines=args.define,
                )
            )
            return _print_execution(execute_argv(command, cwd=root), as_json=args.json)
        except (KeyError, ValueError) as exc:
            parser.error(str(exc))

    if args.command == "inspect":
        try:
            manifest = build_vivado_project_manifest(
                args.project, project_root=args.project_root
            )
        except ValueError as exc:
            parser.error(str(exc))
        payload = _manifest_payload(manifest)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"Vivado project: {manifest.project.path}")
            print(f"part: {manifest.part}")
            print(f"top: {manifest.top}")
            print(f"complete: {manifest.complete}")
            print(f"manifest sha256: {manifest.sha256}")
            print(f"source identity: {manifest.source_identity_sha256}")
        return 0 if manifest.complete else 1

    if args.command == "plan":
        try:
            manifest = build_vivado_project_manifest(
                args.project, project_root=args.project_root
            )
            _require_complete_manifest(manifest, label="planned")
            phases = _phase_sequence(args.phase)
            steps = [
                _planned_step(
                    manifest,
                    phase=phase,
                    output_dir=_output_dir(manifest.project_root, args.output_dir, "plan", phase),
                    command=_vivado_command(args.vivado),
                    jobs=args.jobs,
                    synth_run=args.synth_run,
                    impl_run=args.impl_run,
                )
                for phase in phases
            ]
        except ValueError as exc:
            parser.error(str(exc))
        payload = steps[0] if len(steps) == 1 else {
            "schema": PLAN_SCHEMA,
            "phase": "full",
            "manifest_sha256": manifest.sha256,
            "source_identity_sha256": manifest.source_identity_sha256,
            "trusted_tcl_sha256": trusted_vivado_tcl().sha256,
            "steps": steps,
            "security_boundary_claimed": False,
        }
        _emit(payload, as_json=args.json)
        return 0

    if args.command != "run":
        parser.error(f"unknown command: {args.command}")

    # Everything below is the one effectful composition root. Publication
    # recovery is attempted before any live project/workspace read. Authority
    # HEAD, policy, tool, and manifest discovery are needed only for a phase
    # that has no prior deterministic lease.
    phase_payloads: list[dict[str, Any]] = []
    exit_code = 0
    try:
        if not args.confirm_project_writes:
            raise ValueError("run requires --confirm-project-writes")
        if tuple(args.writable_path) != (".",):
            raise ValueError(
                "run requires exactly one '--writable-path .' declaration because "
                "Vivado may update project and run state across the isolated workspace"
            )
        if not _REVISION.fullmatch(str(args.source_revision)):
            raise ValueError("--source-revision must be lowercase 40-hex")
        if not math.isfinite(float(args.timeout)) or float(args.timeout) <= 0:
            raise ValueError("--timeout must be a finite positive number")

        authority_root = canonical_path(args.authority_root)
        if not authority_root.is_dir():
            raise ValueError(f"authority root is not a directory: {authority_root}")
        phases = _phase_sequence(args.phase)
        attempt_base = _identifier(args.attempt_id, "attempt-id")
        mission_base = _identifier(args.mission_id, "mission-id")
        identities = [
            {
                "phase": phase,
                "attempt_id": _phase_identifier(
                    attempt_base, phase, "attempt-id"
                ),
                "mission_id": _phase_identifier(
                    mission_base, phase, "mission-id"
                ),
            }
            for phase in phases
        ]
        for item in identities:
            item["run_id"] = item["attempt_id"]

        prepared: list[dict[str, Any]] = []
        for index, item in enumerate(identities):
            phase = str(item["phase"])
            try:
                recovered_phase = _recover_phase(
                    authority_root=authority_root,
                    source_revision=args.source_revision,
                    mission_id=str(item["mission_id"]),
                    attempt_id=str(item["attempt_id"]),
                    phase=phase,
                )
            except EdaExecutionReconciliationRequired as exc:
                payload = {
                    "schema": RUN_SCHEMA,
                    "status": "reconciliation_required",
                    "phase": phase,
                    "process_spawned": None,
                    "process_state": "unknown",
                    "start_receipt": exc.start_receipt.to_dict(),
                    "reconciliation_phase": exc.phase,
                    "cause_sha256": exc.cause_sha256,
                    "execution_id": exc.execution_id,
                    "execution_request_sha256": exc.execution_request_sha256,
                    "execution_locator": exc.execution_locator,
                    "effect_ledger_path": exc.effect_ledger_path,
                    "evidence_locators": list(exc.evidence_locators),
                    "security_boundary_claimed": False,
                }
                _emit(payload, as_json=args.json)
                return 4
            except _RetainedLeaseReconciliation as exc:
                payload = {
                    "schema": RUN_SCHEMA,
                    "status": "reconciliation_required",
                    "phase": phase,
                    "process_spawned": False,
                    "process_state": "not_terminal",
                    "reconciliation_phase": exc.phase,
                    "cause_sha256": exc.cause_sha256,
                    "execution_id": exc.execution_id,
                    "security_boundary_claimed": False,
                }
                _emit(payload, as_json=args.json)
                return 4
            except Exception as exc:
                payload = {
                    "schema": RUN_SCHEMA,
                    "status": "publication_pending",
                    "phase": phase,
                    "process_spawned": False,
                    "execution_id": (
                        f"{chip_eda_lease_id(str(item['mission_id']), str(item['attempt_id']))}"
                        "-exec-1"
                    ),
                    "error": f"{type(exc).__name__}: {exc}",
                    "cause_sha256": canonical_sha(
                        {
                            "schema": "daedalus-chip-publication-error/1",
                            "phase": phase,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    ),
                    "security_boundary_claimed": False,
                }
                _emit(payload, as_json=args.json)
                return 5
            if recovered_phase is None:
                prepared.extend(dict(row) for row in identities[index:])
                break
            try:
                step = _finalize_phase_publication(
                    authority_root=authority_root,
                    authority_source_revision=args.source_revision,
                    mission_id=str(item["mission_id"]),
                    attempt_id=str(item["attempt_id"]),
                    run_id=str(item["run_id"]),
                    phase=phase,
                    authorization=recovered_phase.authorization,
                    execution=recovered_phase.execution,
                    retained=recovered_phase.retained,
                    store=recovered_phase.store,
                    terminal_record=recovered_phase.terminal_record,
                    authority_head_record_sha256=(
                        recovered_phase.authority_head_record_sha256
                    ),
                    subject_record_sha256=(
                        recovered_phase.subject_record_sha256
                    ),
                    execution_record_sha256=(
                        recovered_phase.execution_record_sha256
                    ),
                    recovered=True,
                )
            except Exception as exc:
                terminal = recovered_phase.replay.terminal_receipt
                assert terminal is not None
                payload = {
                    "schema": RUN_SCHEMA,
                    "status": "publication_pending",
                    "phase": phase,
                    "process_spawned": False,
                    "execution_id": recovered_phase.execution.execution_id,
                    "execution_request_sha256": recovered_phase.execution.digest,
                    "terminal_receipt_sha256": terminal.receipt_sha256,
                    "raw_execution_receipt_sha256": (
                        recovered_phase.retained.result.receipt_sha256
                    ),
                    "raw_execution_receipt_locator": (
                        recovered_phase.retained.result.receipt_locator
                    ),
                    "error": f"{type(exc).__name__}: {exc}",
                    "security_boundary_claimed": False,
                }
                _emit(payload, as_json=args.json)
                return 5
            phase_payloads.append(step)
            if step["status"] != "ok" or step["verdict"] == "failed":
                exit_code = 1
            if phase == "synth" and step["status"] != "ok":
                prepared = []
                break

        if not prepared:
            first = phase_payloads[0]
            last = phase_payloads[-1]
            payload = {
                "schema": RUN_SCHEMA,
                "status": "failed" if exit_code else "recovered",
                "phase": args.phase,
                "source_manifest_sha256": first["manifest_sha256"],
                "source_identity_sha256": first["source_identity_sha256"],
                "workspace_manifest_sha256": last["workspace_manifest_sha256"],
                "steps": phase_payloads,
                "promotion": False,
                "signoff": False,
                "security_boundary_claimed": False,
            }
            _emit(payload, as_json=args.json)
            return exit_code

        verify_repository_head_revision(authority_root, args.source_revision)
        source_manifest = build_vivado_project_manifest(
            args.project, project_root=args.project_root
        )
        workspace_manifest = build_vivado_project_manifest(
            args.workspace_project, project_root=args.workspace_root
        )
        source_root = source_manifest.project_root
        workspace_root = workspace_manifest.project_root
        if not _disjoint(source_root, workspace_root):
            raise ValueError("authoritative source and workspace roots must be disjoint")
        if not _disjoint(authority_root, source_root):
            raise ValueError(
                "operator authority and authoritative source roots must be disjoint"
            )
        if not _disjoint(authority_root, workspace_root):
            raise ValueError("operator authority and workspace roots must be disjoint")
        _require_complete_manifest(source_manifest, label="source")
        _require_complete_manifest(workspace_manifest, label="workspace")
        if source_manifest.source_identity_sha256 != workspace_manifest.source_identity_sha256:
            raise ValueError(
                "workspace source identity does not match the authoritative source identity"
            )

        trusted = trusted_vivado_tcl()
        trusted_payload = Path(trusted.path).read_bytes()
        if hashlib.sha256(trusted_payload).hexdigest() != trusted.sha256:
            raise ValueError("trusted Tcl changed while the run was prepared")
        command = _live_vivado_command(
            args.vivado,
            source_root=source_root,
            workspace_root=workspace_root,
        )
        launcher_sha256 = trusted_launcher_sha256(command)
        command_interpreter_path, command_interpreter_sha256 = (
            trusted_windows_command_interpreter()
        )
        expected_artifact_store_root = (
            write_evidence_root(authority_root, args.source_revision) / "artifacts"
        )
        for item in prepared:
            item["output_dir"] = _output_dir(
                workspace_root,
                args.output_dir,
                str(item["run_id"]),
                str(item["phase"]),
            )
    except (OSError, RepositoryHeadRevisionError, ValueError) as exc:
        parser.error(str(exc))

    last_workspace_manifest = workspace_manifest
    for item in prepared:
        phase = str(item["phase"])
        known_terminal_result: ExecutionResult | None = None
        known_execution: EffectExecutionRequest | None = None
        try:
            # Rebind both trees immediately before every phase.  Vivado may
            # legitimately rewrite workspace XPR/run state during synthesis;
            # implementation therefore receives a fresh exact manifest while
            # the authoritative source must remain byte-identical.
            phase_source_manifest = build_vivado_project_manifest(
                args.project, project_root=args.project_root
            )
            if phase_source_manifest.sha256 != source_manifest.sha256:
                raise ValueError(
                    "authoritative source changed after live preparation"
                )
            phase_workspace_manifest = build_vivado_project_manifest(
                args.workspace_project, project_root=args.workspace_root
            )
            _require_complete_manifest(
                phase_workspace_manifest,
                label="workspace",
            )
            if (
                phase_workspace_manifest.source_identity_sha256
                != phase_source_manifest.source_identity_sha256
            ):
                raise ValueError(
                    "workspace source identity changed before the Vivado phase"
                )
            last_workspace_manifest = phase_workspace_manifest
            output_dir = Path(item["output_dir"])
            phase_plan = _planned_step(
                phase_workspace_manifest,
                phase=phase,
                output_dir=output_dir,
                command=command,
                jobs=args.jobs,
                synth_run=args.synth_run,
                impl_run=args.impl_run,
            )
            phase_argv = tuple(str(value) for value in phase_plan["argv"])
            phase_artifact_paths = _expected_outputs(
                workspace_root, output_dir, phase
            )
            environment = sanitized_eda_environment(
                workspace_root,
                phase=phase,
                workspace_manifest_sha256=phase_workspace_manifest.sha256,
                output_dir=output_dir,
            )
            execution_plan = EdaExecutionPlan.build(
                phase=phase,
                argv=phase_argv,
                source_root=source_root,
                source_project=(
                    source_root / Path(phase_source_manifest.project.path)
                ),
                cwd=workspace_root,
                artifact_paths=phase_artifact_paths,
                artifact_store_root=expected_artifact_store_root,
                timeout_s=args.timeout,
                environment=environment,
                source_manifest_sha256=phase_source_manifest.sha256,
                workspace_manifest_sha256=phase_workspace_manifest.sha256,
                source_identity_sha256=phase_source_manifest.source_identity_sha256,
                trusted_tcl_sha256=trusted.sha256,
                launcher_sha256=launcher_sha256,
                command_interpreter_path=command_interpreter_path,
                command_interpreter_sha256=command_interpreter_sha256,
            )
            lease = acquire_chip_eda_lease(
                authority_root,
                project_root=source_root,
                worktree_root=workspace_root,
                containment_evidence=(
                    "operator supplied a source-identical disjoint Vivado workspace "
                    "and explicitly confirmed whole-workspace project writes"
                ),
                source_revision=args.source_revision,
                mission_id=str(item["mission_id"]),
                attempt_id=str(item["attempt_id"]),
                timeout_s=args.timeout,
                write_policy_path=args.write_policy,
                operation_plan=execution_plan,
            )
            if isinstance(lease, WaveLeaseDenied):
                parser.error("EDA effect lease denied: " + "; ".join(lease.reasons))
            required_grant_records = ("authority_head", "lease_subject")
            missing_grant_records = tuple(
                key for key in required_grant_records if not lease.evidence_records.get(key)
            )
            if missing_grant_records:
                raise EdaExecutionError(
                    "EDA grant is not recoverable before spawn; missing authority "
                    "record(s): " + ", ".join(missing_grant_records)
                )
            store = ArtifactStore(Path(lease.evidence_root) / "artifacts")
            if canonical_path_identity(store.root) != canonical_path_identity(
                expected_artifact_store_root
            ):
                raise EdaExecutionError(
                    "lease evidence root differs from the pre-signed execution plan"
                )
            execution = lease.execution_for(
                1,
                (".",),
                tools=("vivado",),
                operation_sha256=execution_plan.digest,
            )
            execution_record_key = f"lease_execution:{execution.execution_id}"
            if not lease.evidence_records.get(execution_record_key):
                raise EdaExecutionError(
                    "EDA execution identity is not recoverable before spawn; "
                    "its authority record was not retained"
                )
            # Registry conformance intentionally anchors this direct call in
            # ``main``: the externally reachable owner cannot hide another
            # effectful entrypoint behind a convenience wrapper.
            result = run_admitted_eda(
                phase_argv,
                cwd=workspace_root,
                authorization=lease.authorization,
                execution=execution,
                artifact_store=store,
                plan=execution_plan,
                timeout_s=args.timeout,
                artifact_paths=phase_artifact_paths,
            )
            if result.terminal_receipt is not None:
                known_terminal_result = result
                known_execution = execution
            terminal_record = lease.retain_terminal_record(execution)
            replayed = result.status == "replay"
            if replayed:
                replay = inspect_effect_execution(lease.authorization, execution)
                if (
                    replay is None
                    or replay.pending_reconciliation
                    or replay.terminal_receipt is None
                ):
                    raise EdaExecutionReconciliationRequired(
                        start_receipt=result.start_receipt,
                        phase="terminal-replay",
                        cause_sha256=canonical_sha(
                            {
                                "schema": "daedalus-chip-reconciliation-cause/1",
                                "execution_id": execution.execution_id,
                                "state": None if replay is None else replay.state,
                            }
                        ),
                        execution_id=execution.execution_id,
                        execution_request_sha256=execution.digest,
                        effect_ledger_path=lease.ledger_path,
                    )
                retained = recover_retained_execution(
                    artifact_store=store,
                    execution=execution,
                    start_receipt=replay.start_receipt,
                    terminal_receipt=replay.terminal_receipt,
                )
            else:
                if result.start_receipt is None or result.terminal_receipt is None:
                    raise EdaExecutionError(
                        "EDA execution returned without a terminal lifecycle"
                    )
                retained = recover_retained_execution(
                    artifact_store=store,
                    execution=execution,
                    start_receipt=result.start_receipt,
                    terminal_receipt=result.terminal_receipt,
                )
            known_terminal_result = retained.result
            known_execution = execution
            if terminal_record is None:
                raise EdaExecutionError(
                    "terminal EDA execution has no retained terminal authority record"
                )
            step = _finalize_phase_publication(
                authority_root=authority_root,
                authority_source_revision=args.source_revision,
                mission_id=str(item["mission_id"]),
                attempt_id=str(item["attempt_id"]),
                run_id=str(item["run_id"]),
                phase=phase,
                authorization=lease.authorization,
                execution=execution,
                retained=retained,
                store=store,
                terminal_record=terminal_record,
                authority_head_record_sha256=str(
                    lease.evidence_records["authority_head"]
                ),
                subject_record_sha256=str(
                    lease.evidence_records["lease_subject"]
                ),
                execution_record_sha256=str(
                    lease.evidence_records[execution_record_key]
                ),
                recovered=replayed,
            )
            step["lease_evidence_errors"] = list(lease.evidence_errors)
            phase_payloads.append(step)
            if step["status"] != "ok" or step["verdict"] == "failed":
                exit_code = 1
            if phase == "synth" and step["status"] != "ok":
                break
        except WaveLeaseKillSwitchEngaged as exc:
            parser.error(str(exc))
        except EdaExecutionReconciliationRequired as exc:
            payload = {
                "schema": RUN_SCHEMA,
                "status": "reconciliation_required",
                "phase": phase,
                # STARTED means the durable lifecycle cannot prove the host
                # process boundary's final state. Do not turn phase names into
                # a fabricated yes/no spawn claim.
                "process_spawned": None,
                "process_state": "unknown",
                "start_receipt": exc.start_receipt.to_dict(),
                "reconciliation_phase": exc.phase,
                "cause_sha256": exc.cause_sha256,
                "execution_id": exc.execution_id,
                "execution_request_sha256": exc.execution_request_sha256,
                "execution_locator": exc.execution_locator,
                "effect_ledger_path": exc.effect_ledger_path,
                "evidence_locators": list(exc.evidence_locators),
                "security_boundary_claimed": False,
            }
            _emit(payload, as_json=args.json)
            return 4
        except (
            EdaExecutionError,
            EffectLeaseReplay,
            OSError,
            RepositoryHeadRevisionError,
            ValueError,
        ) as exc:
            if (
                known_terminal_result is not None
                and known_terminal_result.terminal_receipt is not None
                and known_execution is not None
            ):
                terminal = known_terminal_result.terminal_receipt
                payload = {
                    "schema": RUN_SCHEMA,
                    "status": "publication_pending",
                    "phase": phase,
                    "process_spawned": known_terminal_result.executed,
                    "execution_id": known_execution.execution_id,
                    "execution_request_sha256": known_execution.digest,
                    "terminal_receipt_sha256": terminal.receipt_sha256,
                    "raw_execution_receipt_sha256": (
                        known_terminal_result.receipt_sha256
                    ),
                    "raw_execution_receipt_locator": (
                        known_terminal_result.receipt_locator
                    ),
                    "error": f"{type(exc).__name__}: {exc}",
                    "cause_sha256": canonical_sha(
                        {
                            "schema": "daedalus-chip-publication-error/1",
                            "phase": phase,
                            "execution_id": known_execution.execution_id,
                            "terminal_receipt_sha256": terminal.receipt_sha256,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    ),
                    "security_boundary_claimed": False,
                }
                _emit(payload, as_json=args.json)
                return 5
            payload = {
                "schema": RUN_SCHEMA,
                "status": "error",
                "phase": phase,
                "error": f"{type(exc).__name__}: {exc}",
                "security_boundary_claimed": False,
            }
            _emit(payload, as_json=args.json)
            return 1

    overall_status = "failed" if exit_code else "complete"
    first_step = phase_payloads[0]
    last_step = phase_payloads[-1]
    payload = {
        "schema": RUN_SCHEMA,
        "status": overall_status,
        "phase": args.phase,
        "source_manifest_sha256": first_step["manifest_sha256"],
        "source_identity_sha256": first_step["source_identity_sha256"],
        "workspace_manifest_sha256": last_step["workspace_manifest_sha256"],
        "steps": phase_payloads,
        "promotion": False,
        "signoff": False,
        "security_boundary_claimed": False,
    }
    _emit(payload, as_json=args.json)
    return exit_code


__all__ = ["PLAN_SCHEMA", "RUN_SCHEMA", "build_parser", "main"]
