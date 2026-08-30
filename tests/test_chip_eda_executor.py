from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import pytest

import daedalus.chip_design.executor as executor_module
from daedalus.chip_design.executor import (
    EdaExecutionAdmissionError,
    EdaExecutionError,
    EdaExecutionReconciliationRequired,
    execute_argv,
    recover_retained_execution,
    run_admitted_eda,
)
from daedalus.chip_design.execution_plan import (
    EdaExecutionPlan,
    publication_adapter_sha256,
    sanitized_eda_environment,
    trusted_windows_command_interpreter,
)
from daedalus.chip_design.manifest import build_vivado_project_manifest
from daedalus.chip_design.toolchains import trusted_launcher_sha256
from daedalus.chip_design.vivado_tcl import (
    build_vivado_flow_argv,
    expected_vivado_output_paths,
    trusted_vivado_tcl,
)
from daedalus.kernel.effects import (
    EffectExecutionRequest,
    EffectStartResult,
    EffectTerminalReceipt,
    LeasedEffectStartReceipt,
)
from daedalus.spine.effect_boundary import Effect
from daedalus.storage import ArtifactCorruption, ArtifactNotFound, ArtifactStore


REVISION = "a" * 40


class _FakeEffectLedger:
    def __init__(
        self,
        *,
        state: str | None,
        error: BaseException | None,
    ) -> None:
        self.path = Path("fake-effect-ledger.sqlite3")
        self.state = state
        self.error = error

    def execution_state(self, _execution_id: str) -> str | None:
        if self.error is not None:
            raise self.error
        return self.state


class _FakeAuthorization:
    def __init__(
        self,
        events: list[str],
        *,
        replay: bool = False,
        replay_state: str | None = "COMPLETED",
        state_error: BaseException | None = None,
        verify_error: BaseException | None = None,
        verify_error_at: int = 1,
        finish_error: BaseException | None = None,
    ) -> None:
        self.events = events
        self.replay = replay
        self.verify_error = verify_error
        self.verify_error_at = verify_error_at
        self.finish_error = finish_error
        self.verify_calls = 0
        self.finish_calls: list[dict[str, object]] = []
        self.request = SimpleNamespace(
            entrypoint_id="cli.daedalus_chip",
            effect_scope=SimpleNamespace(timeout_s=10),
            provenance=SimpleNamespace(
                source_revision=REVISION,
                trace_id="trace-chip-executor",
            ),
        )
        self.lease = SimpleNamespace(entrypoint_id="cli.daedalus_chip")
        self.effect_ledger = _FakeEffectLedger(
            state=replay_state,
            error=state_error,
        )
        self.start_receipt: LeasedEffectStartReceipt | None = None

    def verify(self) -> None:
        self.verify_calls += 1
        if (
            self.verify_error is not None
            and self.verify_calls >= self.verify_error_at
        ):
            raise self.verify_error

    def grant(self) -> None:
        self.events.append("grant")

    def begin_effect(self, execution: EffectExecutionRequest) -> EffectStartResult:
        self.events.append("begin")
        self.start_receipt = LeasedEffectStartReceipt(
            lease_sha256="b" * 64,
            execution_id=execution.execution_id,
            idempotency_key=execution.idempotency_key,
            execution_request_sha256=execution.digest,
            boundary_receipt_sha256="c" * 64,
            started_at="2026-08-30T10:00:00.000000+00:00",
            receipt_sha256="d" * 64,
        )
        return EffectStartResult(
            receipt=self.start_receipt,
            execute=not self.replay,
        )

    def finish_effect(
        self,
        start_receipt: LeasedEffectStartReceipt,
        *,
        outcome: str,
        output_digests=(),
        detail_sha256: str | None = None,
    ) -> EffectTerminalReceipt:
        self.events.append("finish")
        if self.finish_error is not None:
            raise self.finish_error
        call = {
            "start_receipt": start_receipt,
            "outcome": outcome.upper(),
            "output_digests": tuple(sorted(set(output_digests))),
            "detail_sha256": detail_sha256,
        }
        self.finish_calls.append(call)
        return EffectTerminalReceipt(
            lease_sha256=start_receipt.lease_sha256,
            execution_id=start_receipt.execution_id,
            start_receipt_sha256=start_receipt.receipt_sha256,
            outcome=outcome.upper(),
            output_digests=call["output_digests"],
            detail_sha256=detail_sha256,
            finished_at="2026-08-30T10:00:01.000000+00:00",
            receipt_sha256="e" * 64,
        )


class _FakeManagedProcess:
    def __init__(
        self,
        argv,
        *,
        events: list[str],
        stdout,
        stderr,
        returncode: int,
        stdout_bytes: bytes,
        stderr_bytes: bytes,
        hang: bool,
        interrupt: BaseException | None,
        cancel_error: BaseException | None,
        cancel_proves_exit: bool,
        context_enter_error: BaseException | None,
        context_exit_error: BaseException | None,
        after_spawn: Callable[[], None] | None,
        write_outputs: bool,
        **_kwargs,
    ) -> None:
        self.events = events
        self._returncode = returncode
        self.hang = hang
        self.interrupt = interrupt
        self.cancel_error = cancel_error
        self.cancel_proves_exit = cancel_proves_exit
        self.context_enter_error = context_enter_error
        self.context_exit_error = context_exit_error
        self.interrupted = False
        self.cancelled = False
        events.append("spawn")
        stdout.write(stdout_bytes)
        stderr.write(stderr_bytes)
        if write_outputs:
            root = Path(argv[10])
            for relative in expected_vivado_output_paths(
                root, argv[12], argv[9]
            ):
                output = root / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(f"retained {relative}\n".encode("ascii"))
        if after_spawn is not None:
            after_spawn()

    @property
    def returncode(self) -> int | None:
        if self.cancelled:
            return -9
        return None if self.hang else self._returncode

    def poll(self) -> int | None:
        if self.interrupt is not None and not self.interrupted:
            self.interrupted = True
            raise self.interrupt
        return self.returncode

    def cancel(self):
        self.events.append("cancel")
        if self.cancel_error is not None:
            raise self.cancel_error
        self.cancelled = self.cancel_proves_exit
        return SimpleNamespace(stage="tree_kill", returncode=self.returncode)

    def __enter__(self):
        if self.context_enter_error is not None:
            raise self.context_enter_error
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        if self.returncode is None:
            self.cancel()
        if self.context_exit_error is not None:
            raise self.context_exit_error


def _execution(operation_sha256: str) -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="chip-execution-1",
        idempotency_key="chip-idempotency-1",
        requested_effects=(
            Effect.FILESYSTEM_WRITE.value,
            Effect.PROCESS_CONTROL.value,
            Effect.PROCESS_SPAWN.value,
        ),
        writable_paths=(".",),
        tools=("vivado",),
        kill_switch_ref="chip-kill-switch",
        kill_switch_generation=4,
        operation_sha256=operation_sha256,
    )


def _store(tmp_path: Path) -> ArtifactStore:
    return ArtifactStore(tmp_path / "cas", min_free_gib=0)


def _bound_inputs(
    tmp_path: Path,
    work: Path,
    *,
    argv: tuple[str, ...] | None = None,
    artifact_paths=None,
    timeout_s: float = 1,
    store: ArtifactStore | None = None,
    authorization: _FakeAuthorization | None = None,
) -> dict[str, object]:
    retained = store or _store(tmp_path)
    if argv is None:
        project = work / "design.xpr"
        rtl = work / "design.srcs" / "sources_1" / "new" / "top.sv"
        rtl.parent.mkdir(parents=True, exist_ok=True)
        rtl.write_text("module top; endmodule\n", encoding="ascii")
        project.write_text(
            """<?xml version="1.0" encoding="UTF-8"?>
<Project Product="Vivado" Version="7" Minor="64">
  <Configuration>
    <Option Name="Part" Val="xc7a35ticsg324-1L"/>
  </Configuration>
  <FileSets>
    <FileSet Name="sources_1" Type="DesignSrcs">
      <File Path="$PSRCDIR/sources_1/new/top.sv">
        <FileInfo><Attr Name="UsedIn" Val="synthesis"/></FileInfo>
      </File>
      <Config><Option Name="TopModule" Val="top"/></Config>
    </FileSet>
  </FileSets>
  <Runs>
    <Run Id="synth_1" Type="Ft3:Synth" SrcSet="sources_1"
         Part="xc7a35ticsg324-1L"/>
    <Run Id="impl_1" Type="Ft2:EntireDesign" SrcSet="sources_1"
         SynthRun="synth_1" Part="xc7a35ticsg324-1L"/>
  </Runs>
</Project>
""",
            encoding="ascii",
        )
        launcher = tmp_path / "vendor" / "Vivado" / "bin" / "vivado.bat"
        launcher.parent.mkdir(parents=True, exist_ok=True)
        launcher.write_bytes(b"@echo off\r\n")
        argv = tuple(
            build_vivado_flow_argv(
                "inspect",
                project,
                project_root=work,
                output_dir=work / ".daedalus-chip" / "eda-output",
                expected_part="xc7a35ticsg324-1L",
                expected_top="top",
                command=launcher,
            )
        )
    manifest = build_vivado_project_manifest(argv[11], project_root=work)
    assert manifest.complete
    if artifact_paths is None:
        artifact_paths = expected_vivado_output_paths(work, argv[12], "inspect")
    environment = sanitized_eda_environment(
        work,
        phase="inspect",
        workspace_manifest_sha256=manifest.sha256,
        output_dir=argv[12],
    )
    command_interpreter_path, command_interpreter_sha256 = (
        trusted_windows_command_interpreter()
    )
    plan = EdaExecutionPlan.build(
        phase="inspect",
        argv=argv,
        source_root=work,
        source_project=project,
        cwd=work,
        artifact_paths=artifact_paths,
        artifact_store_root=retained.root,
        timeout_s=timeout_s,
        environment=environment,
        source_manifest_sha256=manifest.sha256,
        workspace_manifest_sha256=manifest.sha256,
        source_identity_sha256=manifest.source_identity_sha256,
        trusted_tcl_sha256=trusted_vivado_tcl().sha256,
        launcher_sha256=trusted_launcher_sha256(argv[0]),
        publication_adapter_sha256=publication_adapter_sha256(),
        command_interpreter_path=command_interpreter_path,
        command_interpreter_sha256=command_interpreter_sha256,
    )
    if authorization is not None:
        authorization.request.operation_sha256 = plan.digest
    return {
        "argv": list(argv),
        "cwd": work,
        "execution": _execution(plan.digest),
        "artifact_store": retained,
        "plan": plan,
        "timeout_s": timeout_s,
        "artifact_paths": tuple(artifact_paths),
    }


def _install_fakes(
    monkeypatch: pytest.MonkeyPatch,
    events: list[str],
    *,
    returncode: int = 0,
    stdout: bytes = b"eda stdout\n",
    stderr: bytes = b"eda stderr\n",
    hang: bool = False,
    interrupt: BaseException | None = None,
    cancel_error: BaseException | None = None,
    cancel_proves_exit: bool = True,
    context_enter_error: BaseException | None = None,
    context_exit_error: BaseException | None = None,
    after_spawn: Callable[[], None] | None = None,
    write_outputs: bool = True,
    construction_error: BaseException | None = None,
) -> None:
    monkeypatch.setattr(
        executor_module,
        "NonRuntimeEffectAuthorization",
        _FakeAuthorization,
    )
    monkeypatch.setattr(
        executor_module.shutil,
        "which",
        lambda command, **_kwargs: str(Path(command).resolve(strict=False))
        if Path(command).is_file()
        else None,
    )
    monkeypatch.setattr(
        executor_module,
        "is_trusted_vendor_tool_path",
        lambda _tool, _path: True,
    )

    def process_factory(argv, **kwargs):
        if construction_error is not None:
            events.append("constructor")
            raise construction_error
        return _FakeManagedProcess(
            argv,
            events=events,
            returncode=returncode,
            stdout_bytes=stdout,
            stderr_bytes=stderr,
            hang=hang,
            interrupt=interrupt,
            cancel_error=cancel_error,
            cancel_proves_exit=cancel_proves_exit,
            context_enter_error=context_enter_error,
            context_exit_error=context_exit_error,
            after_spawn=after_spawn,
            write_outputs=write_outputs,
            **kwargs,
        )

    monkeypatch.setattr(executor_module, "ManagedProcess", process_factory)


def _artifact_bytes(store: ArtifactStore, locator_uri: str) -> bytes:
    locator = store.load_locator(locator_uri.rsplit(":", 1)[-1])
    return store.get_bytes(locator.artifact_sha256)


def _successful_retained_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Run the real executor retention path with only process control faked."""

    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    monkeypatch.setattr(
        executor_module,
        "_utc_timestamp",
        lambda: "2026-08-30T10:00:00.500000+00:00",
    )
    authorization = _FakeAuthorization(events)
    store = _store(tmp_path)
    bound = _bound_inputs(
        tmp_path,
        work,
        store=store,
        authorization=authorization,
    )
    result = run_admitted_eda(authorization=authorization, **bound)
    execution = bound["execution"]
    plan = bound["plan"]
    assert isinstance(execution, EffectExecutionRequest)
    assert isinstance(plan, EdaExecutionPlan)
    assert result.status == "ok"
    assert result.start_receipt is not None
    assert result.terminal_receipt is not None
    assert result.receipt_sha256 is not None
    assert result.receipt_locator is not None
    return work, store, execution, plan, result


def _terminal_bound_modified_receipt(
    store: ArtifactStore,
    result,
    mutate: Callable[[dict[str, object]], None],
) -> EffectTerminalReceipt:
    """Publish a modified raw receipt and model a terminal record binding it."""

    assert result.receipt_locator is not None
    assert result.receipt_sha256 is not None
    assert result.terminal_receipt is not None
    original_locator = store.verify(
        store.load_locator(result.receipt_locator.rsplit(":", 1)[-1])
    )
    body = json.loads(store.get_bytes(original_locator.artifact_sha256))
    assert isinstance(body, dict)
    mutate(body)
    payload = executor_module.canonical_json(body).encode("ascii")
    payload_sha256 = hashlib.sha256(payload).hexdigest()
    locator_manifest = original_locator.to_dict()
    replacement = store.put_bytes(
        payload,
        expected_sha256=payload_sha256,
        media_type=locator_manifest["media_type"],
        metadata=original_locator.metadata,
        provenance=original_locator.provenance,
    )

    outputs = set(result.terminal_receipt.output_digests)
    outputs.remove(result.receipt_sha256)
    outputs.add(replacement.artifact_sha256)
    output_digests = tuple(sorted(outputs))
    terminal_body = {
        "lease_sha256": result.terminal_receipt.lease_sha256,
        "execution_id": result.terminal_receipt.execution_id,
        "start_receipt_sha256": result.terminal_receipt.start_receipt_sha256,
        "outcome": result.terminal_receipt.outcome,
        "output_digests": list(output_digests),
        "detail_sha256": result.terminal_receipt.detail_sha256,
        "finished_at": result.terminal_receipt.finished_at,
    }
    return replace(
        result.terminal_receipt,
        output_digests=output_digests,
        receipt_sha256=executor_module.canonical_sha(terminal_body),
    )


def test_recover_retained_execution_roundtrip_uses_only_authenticated_cas(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work, store, execution, plan, result = _successful_retained_execution(
        tmp_path,
        monkeypatch,
    )

    # Recovery must not silently fall back to a later view of the live project.
    (work / "design.xpr").write_text("not the retained project\n", encoding="ascii")
    for artifact in result.artifacts:
        (work / artifact.path).write_bytes(b"not the retained native output\n")

    def forbidden_live_read(*_args, **_kwargs):
        raise AssertionError("retained recovery read the live Vivado project")

    monkeypatch.setattr(
        executor_module,
        "build_vivado_project_manifest",
        forbidden_live_read,
    )
    monkeypatch.setattr(executor_module, "trusted_vivado_tcl", forbidden_live_read)

    # A corrupt blob behind an unrelated global locator must not veto this
    # execution's recovery: candidate discovery authenticates locator metadata
    # first and verifies only the matching raw-receipt locator.
    receipt_locator = store.load_locator(result.receipt_locator.rsplit(":", 1)[-1])
    unrelated = store.put_bytes(
        b"unrelated global CAS payload\n",
        media_type="application/octet-stream",
        metadata={"kind": "unrelated-test-artifact"},
        provenance=receipt_locator.provenance,
    )
    unrelated.blob_path.write_bytes(b"corrupt unrelated blob\n")

    original_get_bytes = store.get_bytes
    payload_reads: list[str] = []

    def tracked_get_bytes(digest: str) -> bytes:
        payload_reads.append(digest)
        return original_get_bytes(digest)

    monkeypatch.setattr(store, "get_bytes", tracked_get_bytes)

    recovered = recover_retained_execution(
        artifact_store=store,
        execution=execution,
        start_receipt=result.start_receipt,
        terminal_receipt=result.terminal_receipt,
    )

    assert recovered.plan == plan
    assert recovered.result == result
    assert payload_reads == [result.receipt_sha256]
    monkeypatch.setattr(store, "get_bytes", original_get_bytes)
    assert recovered.receipt_payload == _artifact_bytes(
        store,
        result.receipt_locator,
    )
    assert recovered.receipt_body == json.loads(recovered.receipt_payload)
    for artifact in recovered.result.artifacts:
        assert _artifact_bytes(store, artifact.locator).startswith(b"retained ")


def test_recovery_streams_large_console_without_loading_terminal_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    large_stdout = b"a" * (1024 * 1024 - 1) + "€".encode() + b"z" * 200_000
    _install_fakes(monkeypatch, events, stdout=large_stdout)
    monkeypatch.setattr(
        executor_module,
        "_utc_timestamp",
        lambda: "2026-08-30T10:00:00.500000+00:00",
    )
    authorization = _FakeAuthorization(events)
    store = _store(tmp_path)
    bound = _bound_inputs(
        tmp_path,
        work,
        store=store,
        authorization=authorization,
    )
    result = run_admitted_eda(authorization=authorization, **bound)
    assert result.truncated is True

    original_get_bytes = store.get_bytes
    payload_reads: list[str] = []

    def tracked_get_bytes(digest: str) -> bytes:
        payload_reads.append(digest)
        return original_get_bytes(digest)

    monkeypatch.setattr(store, "get_bytes", tracked_get_bytes)
    recovered = recover_retained_execution(
        artifact_store=store,
        execution=bound["execution"],
        start_receipt=result.start_receipt,
        terminal_receipt=result.terminal_receipt,
    )

    assert recovered.result == result
    assert payload_reads == [result.receipt_sha256]


def test_recover_retained_execution_refuses_raw_receipt_blob_tamper(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _work, store, execution, _plan, result = _successful_retained_execution(
        tmp_path,
        monkeypatch,
    )
    locator = store.verify(
        store.load_locator(result.receipt_locator.rsplit(":", 1)[-1])
    )
    payload = locator.blob_path.read_bytes()
    locator.blob_path.write_bytes(b"!" + payload[1:])

    with pytest.raises(ArtifactCorruption, match="artifact blob corruption"):
        recover_retained_execution(
            artifact_store=store,
            execution=execution,
            start_receipt=result.start_receipt,
            terminal_receipt=result.terminal_receipt,
        )


def test_recovery_refuses_oversized_raw_receipt_before_loading_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _work, store, execution, _plan, result = _successful_retained_execution(
        tmp_path,
        monkeypatch,
    )
    original = store.load_locator(result.receipt_locator.rsplit(":", 1)[-1])
    oversized = store.put_bytes(
        b"x" * (executor_module._MAX_RECEIPT_BYTES + 1),
        media_type="application/json",
        metadata=original.metadata,
        provenance=original.provenance,
    )
    outputs = set(result.terminal_receipt.output_digests)
    outputs.remove(result.receipt_sha256)
    outputs.add(oversized.artifact_sha256)
    terminal = replace(
        result.terminal_receipt,
        output_digests=tuple(sorted(outputs)),
    )

    def forbidden_payload_load(_digest: str) -> bytes:
        raise AssertionError("oversized receipt payload was loaded")

    monkeypatch.setattr(store, "get_bytes", forbidden_payload_load)
    with pytest.raises(EdaExecutionError, match="exceeds the recovery limit"):
        recover_retained_execution(
            artifact_store=store,
            execution=execution,
            start_receipt=result.start_receipt,
            terminal_receipt=terminal,
        )


@pytest.mark.parametrize(
    ("missing_member", "error_type", "message"),
    (
        ("blob", ArtifactNotFound, "artifact (?:blob|object) is missing"),
        ("locator", EdaExecutionError, "no unique raw-receipt locator"),
    ),
)
def test_recover_retained_execution_refuses_missing_terminal_bound_cas_member(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    missing_member: str,
    error_type: type[Exception],
    message: str,
) -> None:
    _work, store, execution, _plan, result = _successful_retained_execution(
        tmp_path,
        monkeypatch,
    )
    locator = store.verify(
        store.load_locator(result.receipt_locator.rsplit(":", 1)[-1])
    )
    target = locator.blob_path if missing_member == "blob" else locator.locator_path
    assert target.resolve(strict=False).is_relative_to(tmp_path.resolve())
    target.unlink()

    with pytest.raises(error_type, match=message):
        recover_retained_execution(
            artifact_store=store,
            execution=execution,
            start_receipt=result.start_receipt,
            terminal_receipt=result.terminal_receipt,
        )


def test_recover_retained_execution_refuses_wrong_output_partition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _work, store, execution, _plan, result = _successful_retained_execution(
        tmp_path,
        monkeypatch,
    )

    def replace_declared_path(body: dict[str, object]) -> None:
        artifacts = body["artifacts"]
        assert isinstance(artifacts, list) and artifacts
        first = artifacts[0]
        assert isinstance(first, dict)
        first["path"] = ".daedalus-chip/eda-output/not-in-the-plan.txt"

    terminal = _terminal_bound_modified_receipt(
        store,
        result,
        replace_declared_path,
    )

    with pytest.raises(
        EdaExecutionError,
        match="outputs do not partition the execution plan",
    ):
        recover_retained_execution(
            artifact_store=store,
            execution=execution,
            start_receipt=result.start_receipt,
            terminal_receipt=terminal,
        )


def test_recover_retained_execution_refuses_unsorted_unexpected_inventory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _work, store, execution, _plan, result = _successful_retained_execution(
        tmp_path,
        monkeypatch,
    )

    def inject_unsorted_inventory(body: dict[str, object]) -> None:
        body["status"] = "failed"
        body["intended_effect_terminal_outcome"] = "FAILED"
        body["unexpected_artifact_paths"] = [
            ".daedalus-chip/eda-output/z",
            ".daedalus-chip/eda-output/a",
        ]

    terminal = _terminal_bound_modified_receipt(
        store,
        result,
        inject_unsorted_inventory,
    )
    failed_terminal_body = {
        "lease_sha256": terminal.lease_sha256,
        "execution_id": terminal.execution_id,
        "start_receipt_sha256": terminal.start_receipt_sha256,
        "outcome": "FAILED",
        "output_digests": list(terminal.output_digests),
        "detail_sha256": terminal.detail_sha256,
        "finished_at": terminal.finished_at,
    }
    terminal = replace(
        terminal,
        outcome="FAILED",
        receipt_sha256=executor_module.canonical_sha(failed_terminal_body),
    )

    with pytest.raises(EdaExecutionError, match="inventory is not sorted"):
        recover_retained_execution(
            artifact_store=store,
            execution=execution,
            start_receipt=result.start_receipt,
            terminal_receipt=terminal,
        )


def test_live_refuses_missing_authority_before_discovery_or_spawn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("live effect reached discovery or spawn")

    monkeypatch.setattr(executor_module.shutil, "which", forbidden)
    monkeypatch.setattr(executor_module, "ManagedProcess", forbidden)

    with pytest.raises(EdaExecutionAdmissionError, match="NonRuntimeEffectAuthorization"):
        execute_argv(["fake-eda"], cwd=work, dry_run=False)


def test_live_refuses_plan_or_environment_widening_before_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(events)
    bound = _bound_inputs(tmp_path, work, authorization=authorization)
    plan = bound["plan"]
    assert isinstance(plan, EdaExecutionPlan)

    with pytest.raises(EdaExecutionAdmissionError, match="environment overrides"):
        run_admitted_eda(
            authorization=authorization,
            env_overrides={"LM_LICENSE_FILE": "forbidden"},
            **bound,
        )
    assert events == []

    other_store = ArtifactStore(tmp_path / "other-cas", min_free_gib=0)
    with pytest.raises(EdaExecutionAdmissionError, match="does not match normalized"):
        run_admitted_eda(
            authorization=authorization,
            **{**bound, "artifact_store": other_store},
        )
    assert events == []


@pytest.mark.parametrize(
    ("request_operation", "message"),
    (
        (None, "must bind an operation_sha256"),
        ("f" * 64, "different EDA operation"),
    ),
)
def test_live_refuses_unsigned_or_mismatched_lease_operation_before_grant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request_operation: str | None,
    message: str,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(events)
    bound = _bound_inputs(tmp_path, work, authorization=authorization)
    authorization.request.operation_sha256 = request_operation

    with pytest.raises(
        EdaExecutionAdmissionError,
        match=message,
    ):
        run_admitted_eda(authorization=authorization, **bound)

    assert events == []


def test_live_refuses_empty_phase_output_contract_before_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(events)
    bound = _bound_inputs(
        tmp_path,
        work,
        artifact_paths=(),
        authorization=authorization,
    )

    with pytest.raises(EdaExecutionAdmissionError, match="exact output set"):
        run_admitted_eda(authorization=authorization, **bound)

    assert events == []


def test_live_refuses_authority_external_cas_before_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(events)
    authorization.effect_ledger.path = (
        tmp_path / "authority" / "effect-leases.sqlite3"
    ).resolve()
    bound = _bound_inputs(tmp_path, work, authorization=authorization)

    with pytest.raises(EdaExecutionAdmissionError, match="authority evidence root"):
        run_admitted_eda(authorization=authorization, **bound)

    assert events == []


def test_live_refuses_install_startup_tcl_before_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(events)
    bound = _bound_inputs(tmp_path, work, authorization=authorization)
    plan = bound["plan"]
    assert isinstance(plan, EdaExecutionPlan)
    launcher = Path(plan.argv[0])
    startup = launcher.parent.parent / "scripts" / "Vivado_init.tcl"
    startup.parent.mkdir(parents=True)
    startup.write_text("puts ambient\n", encoding="ascii")

    with pytest.raises(EdaExecutionAdmissionError, match="startup Tcl"):
        run_admitted_eda(authorization=authorization, **bound)

    assert events == []


def test_windows_batch_metacharacter_is_refused_before_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work (cmd-meta)"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(events)
    bound = _bound_inputs(tmp_path, work, authorization=authorization)

    with pytest.raises(EdaExecutionAdmissionError, match="cmd.exe metacharacter"):
        run_admitted_eda(authorization=authorization, **bound)

    assert events == []


@pytest.mark.parametrize(
    ("execution_change", "message"),
    (
        ({"operation_sha256": None}, "must bind an operation_sha256"),
        ({"operation_sha256": "f" * 64}, "different EDA execution plan"),
        ({"writable_paths": ("build",)}, "whole-workspace write scope"),
        ({"tools": ("python",)}, "exact Vivado tool scope"),
    ),
)
def test_live_refuses_unbound_or_widened_execution_scope_before_grant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    execution_change: dict[str, object],
    message: str,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(events)
    bound = _bound_inputs(tmp_path, work, authorization=authorization)
    execution = bound["execution"]
    assert isinstance(execution, EffectExecutionRequest)

    with pytest.raises(EdaExecutionAdmissionError, match=message):
        run_admitted_eda(
            authorization=authorization,
            **{**bound, "execution": replace(execution, **execution_change)},
        )

    assert events == []


def test_live_refuses_arbitrary_vivado_tcl_or_mislabeled_phase_before_grant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(events)
    bound = _bound_inputs(tmp_path, work, authorization=authorization)
    plan = bound["plan"]
    execution = bound["execution"]
    assert isinstance(plan, EdaExecutionPlan)
    assert isinstance(execution, EffectExecutionRequest)

    hostile_tcl = work / "hostile.tcl"
    hostile_tcl.write_text("exec calc\n", encoding="ascii")
    hostile_argv = list(plan.argv)
    hostile_argv[7] = str(hostile_tcl)
    hostile_plan = replace(plan, argv=tuple(hostile_argv))
    with pytest.raises(EdaExecutionAdmissionError, match="trusted flow"):
        run_admitted_eda(
            authorization=authorization,
            **{
                **bound,
                "argv": hostile_argv,
                "plan": hostile_plan,
                "execution": replace(
                    execution, operation_sha256=hostile_plan.digest
                ),
            },
        )

    mislabeled_plan = replace(plan, phase="synth")
    with pytest.raises(EdaExecutionAdmissionError, match="phase does not match"):
        run_admitted_eda(
            authorization=authorization,
            **{
                **bound,
                "plan": mislabeled_plan,
                "execution": replace(
                    execution, operation_sha256=mislabeled_plan.digest
                ),
            },
        )

    stale_tcl_plan = replace(plan, trusted_tcl_sha256="f" * 64)
    with pytest.raises(EdaExecutionAdmissionError, match="current package-owned"):
        run_admitted_eda(
            authorization=authorization,
            **{
                **bound,
                "plan": stale_tcl_plan,
                "execution": replace(
                    execution, operation_sha256=stale_tcl_plan.digest
                ),
            },
        )

    assert events == []


def test_exact_replay_is_inert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(events, replay=True)

    def forbidden(_command):
        raise AssertionError("replay performed executable discovery")

    monkeypatch.setattr(executor_module.shutil, "which", forbidden)
    store = _store(tmp_path)
    result = run_admitted_eda(
        authorization=authorization,
        **_bound_inputs(
            tmp_path, work, store=store, authorization=authorization
        ),
    )

    assert result.status == "replay"
    assert result.executed is False
    assert result.terminal_receipt is None
    assert authorization.finish_calls == []
    assert events == ["grant", "begin"]
    assert not store.root.exists()


def test_pending_started_replay_requires_reconciliation_before_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(
        events, replay=True, replay_state="STARTED"
    )

    def forbidden(_command):
        raise AssertionError("pending replay performed executable discovery")

    monkeypatch.setattr(executor_module.shutil, "which", forbidden)
    with pytest.raises(EdaExecutionReconciliationRequired) as caught:
        run_admitted_eda(
            authorization=authorization,
            **_bound_inputs(tmp_path, work, authorization=authorization),
        )

    assert caught.value.phase == "pending-replay"
    assert caught.value.execution_request_sha256 == (
        authorization.start_receipt.execution_request_sha256
    )
    assert caught.value.effect_ledger_path is not None
    assert caught.value.evidence_locators == ()
    assert authorization.finish_calls == []
    assert events == ["grant", "begin"]


def test_unreadable_replay_state_requires_reconciliation_before_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(
        events,
        replay=True,
        state_error=OSError("injected ledger read fault"),
    )

    def forbidden(_command):
        raise AssertionError("unknown replay performed executable discovery")

    monkeypatch.setattr(executor_module.shutil, "which", forbidden)
    with pytest.raises(EdaExecutionReconciliationRequired) as caught:
        run_admitted_eda(
            authorization=authorization,
            **_bound_inputs(tmp_path, work, authorization=authorization),
        )

    assert caught.value.phase == "replay-state"
    assert caught.value.start_receipt is authorization.start_receipt
    assert authorization.finish_calls == []
    assert events == ["grant", "begin"]


def test_success_persists_console_receipt_and_declared_artifact_before_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    relative_output = ".daedalus-chip/eda-output/inspect_summary.txt"
    native = work / relative_output
    events: list[str] = []
    _install_fakes(
        monkeypatch,
        events,
        stdout=b"raw success stdout\n",
        stderr=b"",
    )
    original_put = ArtifactStore.put_bytes

    def traced_put(self, *args, **kwargs):
        events.append("cas")
        return original_put(self, *args, **kwargs)

    monkeypatch.setattr(ArtifactStore, "put_bytes", traced_put)
    authorization = _FakeAuthorization(events)
    store = _store(tmp_path)
    result = run_admitted_eda(
        authorization=authorization,
        **_bound_inputs(
            tmp_path, work, store=store, authorization=authorization
        ),
    )

    assert result.status == "ok"
    assert result.executed is True
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.outcome == "COMPLETED"
    assert len(authorization.finish_calls) == 1
    assert events[:3] == ["grant", "begin", "spawn"]
    assert events[-1] == "finish"
    assert events.index("cas") > events.index("spawn")
    assert _artifact_bytes(store, result.stdout_locator or "") == b"raw success stdout\n"
    assert _artifact_bytes(store, result.stderr_locator or "") == b""
    assert len(result.artifacts) == 1
    assert result.artifacts[0].path == relative_output
    assert _artifact_bytes(store, result.artifacts[0].locator) == (
        b"retained .daedalus-chip/eda-output/inspect_summary.txt\n"
    )

    receipt = json.loads(_artifact_bytes(store, result.receipt_locator or ""))
    assert receipt["schema"] == "daedalus.eda-execution-receipt/3"
    assert receipt["intended_effect_terminal_outcome"] == "COMPLETED"
    assert receipt["effect_start_receipt"]["receipt_sha256"] == "d" * 64
    assert receipt["artifacts"][0]["sha256"] == result.artifacts[0].sha256
    assert receipt["unexpected_artifact_paths"] == []
    assert result.receipt_sha256 in result.terminal_receipt.output_digests
    assert result.artifacts[0].sha256 in result.terminal_receipt.output_digests

    retained = result.artifact_for(relative_output)
    native.write_bytes(b"MUTATED AFTER RETENTION")
    assert retained.sha256 == hashlib.sha256(
        b"retained .daedalus-chip/eda-output/inspect_summary.txt\n"
    ).hexdigest()
    assert retained.sha256 != hashlib.sha256(native.read_bytes()).hexdigest()
    assert _artifact_bytes(store, retained.locator) == (
        b"retained .daedalus-chip/eda-output/inspect_summary.txt\n"
    )


def test_nonzero_exit_is_terminal_failed_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events, returncode=7, stderr=b"synthesis failed")
    authorization = _FakeAuthorization(events)

    result = run_admitted_eda(
        authorization=authorization,
        **_bound_inputs(tmp_path, work, authorization=authorization),
    )

    assert result.status == "failed"
    assert result.returncode == 7
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.outcome == "FAILED"
    assert len(authorization.finish_calls) == 1
    assert authorization.finish_calls[0]["detail_sha256"] is not None


def test_timeout_cancels_managed_tree_and_terminalizes_cancelled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events, hang=True)
    authorization = _FakeAuthorization(events)

    result = run_admitted_eda(
        authorization=authorization,
        **_bound_inputs(
            tmp_path,
            work,
            timeout_s=0.01,
            authorization=authorization,
        ),
    )

    assert result.status == "timeout"
    assert result.returncode is None
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.outcome == "CANCELLED"
    assert events.count("cancel") == 1
    assert len(authorization.finish_calls) == 1


@pytest.mark.parametrize(
    "authority_fault",
    (OSError("injected kill-switch read fault"), ValueError("malformed generation")),
)
def test_live_authority_loss_cancels_known_tree_then_terminalizes_cancelled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    authority_fault: BaseException,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events, hang=True)
    authorization = _FakeAuthorization(
        events, verify_error=authority_fault, verify_error_at=3
    )

    result = run_admitted_eda(
        authorization=authorization,
        **_bound_inputs(tmp_path, work, authorization=authorization),
    )

    assert result.status == "cancelled"
    assert result.executed is True
    assert result.returncode == -9
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.outcome == "CANCELLED"
    assert "cause_sha256=" in result.stderr
    assert authorization.verify_calls == 3
    assert events.count("cancel") == 1
    assert len(authorization.finish_calls) == 1


def test_pre_spawn_authority_loss_never_constructs_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(
        events,
        verify_error=OSError("injected pre-spawn authority fault"),
        verify_error_at=1,
    )

    result = run_admitted_eda(
        authorization=authorization,
        **_bound_inputs(tmp_path, work, authorization=authorization),
    )

    assert result.status == "cancelled"
    assert result.executed is False
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.outcome == "CANCELLED"
    assert "spawn" not in events
    assert events == ["grant", "begin", "finish"]


def test_authority_revoked_during_input_closure_never_constructs_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(
        events,
        verify_error=OSError("revoked while manifests were rebound"),
        verify_error_at=2,
    )

    result = run_admitted_eda(
        authorization=authorization,
        **_bound_inputs(tmp_path, work, authorization=authorization),
    )

    assert result.status == "cancelled"
    assert result.executed is False
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.outcome == "CANCELLED"
    assert authorization.verify_calls == 2
    assert "spawn" not in events
    assert events == ["grant", "begin", "finish"]


def test_pre_spawn_workspace_drift_never_constructs_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(events)
    bound = _bound_inputs(tmp_path, work, authorization=authorization)
    launcher = str(bound["argv"][0])

    def discover_and_mutate(_command, **_kwargs):
        (work / "design.srcs" / "sources_1" / "new" / "top.sv").write_text(
            "module top; wire drift; endmodule\n",
            encoding="ascii",
        )
        return launcher

    monkeypatch.setattr(executor_module.shutil, "which", discover_and_mutate)
    result = run_admitted_eda(authorization=authorization, **bound)

    assert result.status == "error"
    assert result.executed is False
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.outcome == "FAILED"
    assert "spawn" not in events
    assert events == ["grant", "begin", "finish"]


def test_preexisting_vivado_output_root_is_refused_before_grant_or_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(events)
    bound = _bound_inputs(tmp_path, work, authorization=authorization)
    output_root = Path(bound["argv"][12])
    output_root.mkdir(parents=True)
    stale = output_root / "inspect_summary.txt"
    stale.write_bytes(b"stale output must not be reused\n")

    with pytest.raises(EdaExecutionAdmissionError, match="output root already exists"):
        run_admitted_eda(authorization=authorization, **bound)

    assert events == []
    assert stale.read_bytes() == b"stale output must not be reused\n"


def test_publication_adapter_mismatch_is_refused_before_grant_or_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(events)
    bound = _bound_inputs(tmp_path, work, authorization=authorization)
    plan = bound["plan"]
    assert isinstance(plan, EdaExecutionPlan)
    stale_plan = replace(plan, publication_adapter_sha256="f" * 64)
    execution = _execution(stale_plan.digest)
    authorization.request.operation_sha256 = stale_plan.digest

    with pytest.raises(EdaExecutionAdmissionError, match="publication adapter identity"):
        run_admitted_eda(
            authorization=authorization,
            **{**bound, "plan": stale_plan, "execution": execution},
        )

    assert events == []


def test_publication_adapter_drift_after_started_never_constructs_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(events)
    bound = _bound_inputs(tmp_path, work, authorization=authorization)
    plan = bound["plan"]
    assert isinstance(plan, EdaExecutionPlan)
    calls = 0

    def drifting_adapter() -> str:
        nonlocal calls
        calls += 1
        return plan.publication_adapter_sha256 if calls == 1 else "f" * 64

    monkeypatch.setattr(
        executor_module,
        "publication_adapter_sha256",
        drifting_adapter,
    )
    result = run_admitted_eda(authorization=authorization, **bound)

    assert calls == 2
    assert result.status == "error"
    assert result.executed is False
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.outcome == "FAILED"
    assert "spawn" not in events
    assert events == ["grant", "begin", "finish"]


def test_output_root_created_after_admission_is_retained_failed_without_spawn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(events)
    bound = _bound_inputs(tmp_path, work, authorization=authorization)
    output_root = Path(bound["argv"][12])
    unexpected = output_root / "late.txt"

    def create_output_root_during_authority_check() -> None:
        authorization.verify_calls += 1
        output_root.mkdir(parents=True)
        unexpected.write_bytes(b"late concurrent output\n")

    authorization.verify = create_output_root_during_authority_check  # type: ignore[method-assign]
    result = run_admitted_eda(authorization=authorization, **bound)

    relative = unexpected.relative_to(work).as_posix()
    assert result.status == "error"
    assert result.executed is False
    assert result.unexpected_artifact_paths == (relative,)
    assert tuple(artifact.path for artifact in result.artifacts) == (relative,)
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.outcome == "FAILED"
    assert "spawn" not in events
    assert events == ["grant", "begin", "finish"]
    assert unexpected.read_bytes() == b"late concurrent output\n"


def test_pre_spawn_trusted_tcl_drift_never_constructs_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(events)
    bound = _bound_inputs(tmp_path, work, authorization=authorization)
    trusted = trusted_vivado_tcl()
    calls = 0

    def drifting_trusted_tcl():
        nonlocal calls
        calls += 1
        if calls == 1:
            return trusted
        return replace(trusted, sha256="f" * 64)

    monkeypatch.setattr(
        executor_module,
        "trusted_vivado_tcl",
        drifting_trusted_tcl,
    )
    result = run_admitted_eda(authorization=authorization, **bound)

    assert calls == 2
    assert result.status == "error"
    assert result.executed is False
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.outcome == "FAILED"
    assert "spawn" not in events


def test_success_retains_exact_post_workspace_and_source_manifests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(events)
    bound = _bound_inputs(tmp_path, work, authorization=authorization)

    result = run_admitted_eda(authorization=authorization, **bound)

    assert result.status == "ok"
    assert result.post_workspace_manifest_locator is not None
    assert result.post_authoritative_manifest_locator is not None
    store = bound["artifact_store"]
    assert isinstance(store, ArtifactStore)
    current = build_vivado_project_manifest(work / "design.xpr", project_root=work)
    for uri, digest in (
        (
            result.post_workspace_manifest_locator,
            result.post_workspace_manifest_sha256,
        ),
        (
            result.post_authoritative_manifest_locator,
            result.post_authoritative_manifest_sha256,
        ),
    ):
        assert uri is not None and digest == current.sha256
        locator = store.verify(
            store.load_locator(uri.removeprefix("artifact-locator:sha256:"))
        )
        assert locator.artifact_sha256 == current.sha256
        assert store.get_bytes(locator.artifact_sha256) == current.canonical_bytes


def test_post_execution_workspace_drift_is_a_retained_terminal_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    rtl = work / "design.srcs" / "sources_1" / "new" / "top.sv"
    _install_fakes(
        monkeypatch,
        events,
        after_spawn=lambda: rtl.write_text(
            "module top; wire post_spawn_drift; endmodule\n", encoding="ascii"
        ),
    )
    authorization = _FakeAuthorization(events)

    result = run_admitted_eda(
        authorization=authorization,
        **_bound_inputs(tmp_path, work, authorization=authorization),
    )

    assert result.status == "failed"
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.outcome == "FAILED"
    assert "post-execution-workspace verification failed" in result.stderr
    assert result.post_workspace_manifest_locator is None
    # In this same-root fixture the authoritative source is independently
    # measured too, so the first failure cannot mask the second one.
    assert "post-execution-source verification failed" in result.stderr
    assert result.post_authoritative_manifest_locator is None


def test_post_execution_authoritative_source_drift_is_not_masked_by_workspace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    authorization = _FakeAuthorization(events)
    bound = _bound_inputs(tmp_path, work, authorization=authorization)
    source = tmp_path / "source"
    source.mkdir()
    source_project = source / "design.xpr"
    source_project.write_bytes((work / "design.xpr").read_bytes())
    source_rtl = source / "design.srcs" / "sources_1" / "new" / "top.sv"
    source_rtl.parent.mkdir(parents=True)
    source_rtl.write_bytes(
        (work / "design.srcs" / "sources_1" / "new" / "top.sv").read_bytes()
    )
    source_manifest = build_vivado_project_manifest(
        source_project, project_root=source
    )
    plan = replace(
        bound["plan"],
        source_root=str(source.resolve()),
        source_project=str(source_project.resolve()),
        source_manifest_sha256=source_manifest.sha256,
    )
    assert isinstance(plan, EdaExecutionPlan)
    bound["plan"] = plan
    bound["execution"] = _execution(plan.digest)
    authorization.request.operation_sha256 = plan.digest
    _install_fakes(
        monkeypatch,
        events,
        after_spawn=lambda: source_rtl.write_text(
            "module top; wire source_drift; endmodule\n", encoding="ascii"
        ),
    )

    result = run_admitted_eda(authorization=authorization, **bound)

    assert result.status == "failed"
    assert result.post_workspace_manifest_locator is not None
    assert result.post_workspace_manifest_sha256 is not None
    assert result.post_authoritative_manifest_locator is None
    assert result.post_authoritative_manifest_sha256 is None
    assert "post-execution-source verification failed" in result.stderr
    assert "post-execution-workspace verification failed" not in result.stderr


@pytest.mark.parametrize("abort", [KeyboardInterrupt(), SystemExit(9)])
def test_unknown_post_workspace_manifest_abort_requires_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    abort: BaseException,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(events)

    def interrupted(*_args, **_kwargs):
        raise abort

    monkeypatch.setattr(
        executor_module,
        "_validate_post_execution_workspace",
        interrupted,
    )

    with pytest.raises(EdaExecutionReconciliationRequired) as caught:
        run_admitted_eda(
            authorization=authorization,
            **_bound_inputs(tmp_path, work, authorization=authorization),
        )

    assert caught.value.phase == "post-execution-workspace"
    assert authorization.finish_calls == []
    assert events[:3] == ["grant", "begin", "spawn"]


def test_managed_process_constructor_fault_remains_started_for_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(
        monkeypatch,
        events,
        construction_error=RuntimeError("injected constructor fault"),
    )
    authorization = _FakeAuthorization(events)

    with pytest.raises(EdaExecutionReconciliationRequired) as caught:
        run_admitted_eda(
            authorization=authorization,
            **_bound_inputs(tmp_path, work, authorization=authorization),
        )

    assert caught.value.phase == "process-construction"
    assert authorization.finish_calls == []
    assert events == ["grant", "begin", "constructor"]


def test_authority_loss_without_proven_termination_stays_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(
        monkeypatch,
        events,
        hang=True,
        cancel_proves_exit=False,
    )
    authorization = _FakeAuthorization(
        events,
        verify_error=OSError("injected kill-switch fault"),
        verify_error_at=3,
    )

    with pytest.raises(EdaExecutionReconciliationRequired) as caught:
        run_admitted_eda(
            authorization=authorization,
            **_bound_inputs(tmp_path, work, authorization=authorization),
        )

    assert caught.value.phase == "kill-switch-cancellation"
    assert caught.value.start_receipt is authorization.start_receipt
    assert events.count("cancel") >= 1
    assert authorization.finish_calls == []


@pytest.mark.parametrize(
    ("fake_kwargs", "expected_phase"),
    (
        ({"interrupt": RuntimeError("injected poll fault"), "hang": True}, "process-poll"),
        ({"context_enter_error": RuntimeError("injected enter fault")}, "process-context-enter"),
        ({"context_exit_error": RuntimeError("injected exit fault")}, "process-context-exit"),
        ({"cancel_error": RuntimeError("injected cancel fault"), "hang": True}, "process-context-exit"),
    ),
)
def test_post_spawn_control_faults_never_fabricate_pre_spawn_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_kwargs: dict[str, object],
    expected_phase: str,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events, **fake_kwargs)
    authorization = _FakeAuthorization(events)

    with pytest.raises(EdaExecutionReconciliationRequired) as caught:
        run_admitted_eda(
            authorization=authorization,
            **_bound_inputs(
                tmp_path,
                work,
                timeout_s=0.001,
                authorization=authorization,
            ),
        )

    assert caught.value.phase == expected_phase
    assert caught.value.start_receipt is authorization.start_receipt
    assert caught.value.execution_id == authorization.start_receipt.execution_id
    assert caught.value.execution_request_sha256 == (
        authorization.start_receipt.execution_request_sha256
    )
    assert authorization.finish_calls == []
    assert events[:3] == ["grant", "begin", "spawn"]


def test_missing_tool_is_a_known_terminal_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    monkeypatch.setattr(
        executor_module.shutil, "which", lambda _command, **_kwargs: None
    )
    authorization = _FakeAuthorization(events)

    result = run_admitted_eda(
        authorization=authorization,
        **_bound_inputs(tmp_path, work, authorization=authorization),
    )

    assert result.status == "missing"
    assert result.executed is False
    assert "not found on PATH" in result.stderr
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.outcome == "FAILED"
    assert "spawn" not in events
    assert len(authorization.finish_calls) == 1


@pytest.mark.parametrize("abort", [KeyboardInterrupt(), SystemExit(9)])
def test_unknown_process_abort_reports_start_locator_without_terminal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    abort: BaseException,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events, hang=True, interrupt=abort)
    authorization = _FakeAuthorization(events)

    with pytest.raises(EdaExecutionReconciliationRequired) as caught:
        run_admitted_eda(
            authorization=authorization,
            **_bound_inputs(tmp_path, work, authorization=authorization),
        )

    assert caught.value.phase == "process-poll"
    assert caught.value.start_receipt is authorization.start_receipt
    assert caught.value.start_receipt_locator == f"effect-start:sha256:{'d' * 64}"
    assert caught.value.execution_id == "chip-execution-1"
    assert "chip-execution-1" in caught.value.execution_locator
    assert events[:3] == ["grant", "begin", "spawn"]
    assert events.count("cancel") == 1
    assert authorization.finish_calls == []
    assert not (tmp_path / "cas").exists()


@pytest.mark.parametrize("abort", [KeyboardInterrupt(), SystemExit(9)])
def test_unknown_authority_check_abort_stays_started_for_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    abort: BaseException,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events, hang=True)
    authorization = _FakeAuthorization(
        events,
        verify_error=abort,
        verify_error_at=3,
    )

    with pytest.raises(EdaExecutionReconciliationRequired) as caught:
        run_admitted_eda(
            authorization=authorization,
            **_bound_inputs(tmp_path, work, authorization=authorization),
        )

    assert caught.value.phase == "kill-switch-verification"
    assert caught.value.start_receipt is authorization.start_receipt
    assert events[:3] == ["grant", "begin", "spawn"]
    assert events.count("cancel") == 1
    assert authorization.finish_calls == []


def test_declared_artifact_read_refuses_identity_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "artifact-root"
    artifact = root / ".daedalus-chip" / "eda-output" / "inspect_summary.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"stable-looking bytes\n")
    observation = executor_module._ProcessObservation(
        status="ok",
        returncode=0,
        duration_s=0.1,
        stdout=b"",
        stderr=b"",
        terminal_outcome="COMPLETED",
        process_spawned=True,
    )
    original_fstat = executor_module.os.fstat
    calls = 0

    def drifting_fstat(fd: int):
        nonlocal calls
        calls += 1
        current = original_fstat(fd)
        if calls != 2:
            return current
        return SimpleNamespace(
            st_dev=current.st_dev,
            st_ino=current.st_ino,
            st_size=current.st_size,
            st_mtime_ns=current.st_mtime_ns + 1,
            st_mode=current.st_mode,
        )

    monkeypatch.setattr(executor_module.os, "fstat", drifting_fstat)

    with pytest.raises(EdaExecutionAdmissionError, match="changed while"):
        executor_module._read_declared_artifacts(
            root,
            ((".daedalus-chip/eda-output/inspect_summary.txt", artifact),),
            observation,
            output_root=root / ".daedalus-chip" / "eda-output",
        )


def test_missing_declared_output_turns_zero_exit_into_failed_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events, returncode=0, write_outputs=False)
    authorization = _FakeAuthorization(events)

    result = run_admitted_eda(
        authorization=authorization,
        **_bound_inputs(tmp_path, work, authorization=authorization),
    )

    assert result.status == "failed"
    assert result.returncode == 0
    assert result.missing_artifact_paths == (
        ".daedalus-chip/eda-output/inspect_summary.txt",
    )
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.outcome == "FAILED"


def test_unexpected_output_tree_is_sorted_retained_and_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    output_root = work / ".daedalus-chip" / "eda-output"
    monkeypatch.setattr(
        executor_module,
        "_utc_timestamp",
        lambda: "2026-08-30T10:00:00.500000+00:00",
    )

    def add_unexpected_tree() -> None:
        (output_root / "extra.txt").write_bytes(b"unexpected regular file\n")
        nested = output_root / "extra-dir" / "nested.bin"
        nested.parent.mkdir()
        nested.write_bytes(b"unexpected nested bytes\n")

    _install_fakes(monkeypatch, events, after_spawn=add_unexpected_tree)
    authorization = _FakeAuthorization(events)
    bound = _bound_inputs(tmp_path, work, authorization=authorization)
    result = run_admitted_eda(authorization=authorization, **bound)

    expected_unexpected = (
        ".daedalus-chip/eda-output/extra-dir",
        ".daedalus-chip/eda-output/extra-dir/nested.bin",
        ".daedalus-chip/eda-output/extra.txt",
    )
    assert result.status == "failed"
    assert result.terminal_receipt is not None
    assert result.terminal_receipt.outcome == "FAILED"
    assert result.unexpected_artifact_paths == expected_unexpected
    assert tuple(artifact.path for artifact in result.artifacts) == (
        ".daedalus-chip/eda-output/inspect_summary.txt",
        ".daedalus-chip/eda-output/extra-dir/nested.bin",
        ".daedalus-chip/eda-output/extra.txt",
    )
    assert _artifact_bytes(bound["artifact_store"], result.artifacts[1].locator) == (
        b"unexpected nested bytes\n"
    )
    receipt = json.loads(_artifact_bytes(bound["artifact_store"], result.receipt_locator))
    assert receipt["unexpected_artifact_paths"] == list(expected_unexpected)
    assert {artifact.sha256 for artifact in result.artifacts}.issubset(
        result.terminal_receipt.output_digests
    )
    recovered = recover_retained_execution(
        artifact_store=bound["artifact_store"],
        execution=bound["execution"],
        start_receipt=result.start_receipt,
        terminal_receipt=result.terminal_receipt,
    )
    assert recovered.result == result


def test_linklike_output_entry_is_reported_without_following_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"must never be retained through output link\n")
    events: list[str] = []
    output_root = work / ".daedalus-chip" / "eda-output"

    def add_output_link() -> None:
        try:
            (output_root / "linked.bin").symlink_to(outside)
        except OSError as exc:  # pragma: no cover - host privilege dependent
            pytest.skip(f"host cannot create a test symlink: {exc}")

    _install_fakes(monkeypatch, events, after_spawn=add_output_link)
    authorization = _FakeAuthorization(events)
    bound = _bound_inputs(tmp_path, work, authorization=authorization)
    result = run_admitted_eda(authorization=authorization, **bound)

    linked = ".daedalus-chip/eda-output/linked.bin"
    assert result.status == "failed"
    assert result.unexpected_artifact_paths == (linked,)
    assert linked not in {artifact.path for artifact in result.artifacts}
    assert all(
        _artifact_bytes(bound["artifact_store"], artifact.locator)
        != outside.read_bytes()
        for artifact in result.artifacts
    )


def test_windows_reparse_attribute_is_linklike_without_following(
    tmp_path: Path,
) -> None:
    state = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
    assert executor_module._is_linklike_state(tmp_path / "junction", state)


def test_artifact_store_fault_after_process_requires_reconciliation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(events)

    def broken_put(*_args, **_kwargs):
        raise OSError("injected CAS fault")

    monkeypatch.setattr(ArtifactStore, "put_bytes", broken_put)
    with pytest.raises(EdaExecutionReconciliationRequired) as caught:
        run_admitted_eda(
            authorization=authorization,
            **_bound_inputs(tmp_path, work, authorization=authorization),
        )

    assert caught.value.phase == "artifact-evidence"
    assert authorization.finish_calls == []
    assert events[:3] == ["grant", "begin", "spawn"]


def test_console_capture_fault_after_spawn_stays_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(events)
    original_temporary_file = executor_module.tempfile.TemporaryFile
    calls = 0

    class _CaptureProxy:
        def __init__(self, raw, *, fail_flush: bool) -> None:
            self.raw = raw
            self.fail_flush = fail_flush

        def __getattr__(self, name: str):
            return getattr(self.raw, name)

        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb) -> None:
            self.raw.close()

        def flush(self) -> None:
            if self.fail_flush:
                raise OSError("injected stdout capture flush fault")
            self.raw.flush()

    def temporary_file(*args, **kwargs):
        nonlocal calls
        calls += 1
        return _CaptureProxy(
            original_temporary_file(*args, **kwargs),
            fail_flush=calls == 1,
        )

    monkeypatch.setattr(executor_module.tempfile, "TemporaryFile", temporary_file)
    with pytest.raises(EdaExecutionReconciliationRequired) as caught:
        run_admitted_eda(
            authorization=authorization,
            **_bound_inputs(tmp_path, work, authorization=authorization),
        )

    assert caught.value.phase == "capture-flush"
    assert caught.value.start_receipt is authorization.start_receipt
    assert authorization.finish_calls == []
    assert events[:3] == ["grant", "begin", "spawn"]


def test_terminal_persistence_fault_carries_ledger_and_cas_locators(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = tmp_path / "work"
    work.mkdir()
    events: list[str] = []
    _install_fakes(monkeypatch, events)
    authorization = _FakeAuthorization(
        events, finish_error=OSError("injected terminal ledger fault")
    )

    with pytest.raises(EdaExecutionReconciliationRequired) as caught:
        run_admitted_eda(
            authorization=authorization,
            **_bound_inputs(tmp_path, work, authorization=authorization),
        )

    error = caught.value
    assert error.phase == "terminal-persistence"
    assert error.start_receipt is authorization.start_receipt
    assert error.start_receipt_locator == f"effect-start:sha256:{'d' * 64}"
    assert error.effect_ledger_path is not None
    assert error.execution_locator.startswith("effect-ledger:")
    assert "#execution_id=chip-execution-1" in error.execution_locator
    assert len(error.evidence_locators) == 7
    assert all(
        locator.startswith("artifact-locator:sha256:")
        for locator in error.evidence_locators
    )
    assert events[-1] == "finish"


def test_executor_contains_no_direct_subprocess_bypass() -> None:
    source = Path(executor_module.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "subprocess.run",
        "subprocess.Popen",
        "subprocess.check_call",
        "subprocess.check_output",
        "os.system",
    ):
        assert forbidden not in source
