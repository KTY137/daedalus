from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from threading import Barrier, Event, Lock
from types import SimpleNamespace

import pytest

from daedalus.atomic import ExclusiveFileLock
from daedalus.orchestration.genesis.admission import (
    GENESIS_RUN_ID_NAMESPACE_VERSION,
    build_genesis_plan,
    normalize_genesis_request,
)
from daedalus.orchestration.genesis import service as service_module
from daedalus.orchestration.genesis.service import (
    GenesisConflictError,
    read_genesis_preview,
    run_genesis,
)
from daedalus.spine.killswitch import KillSwitch


@pytest.fixture
def authority(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "authority"
    repo.mkdir()
    monkeypatch.setenv(
        "DAEDALUS_KILLSWITCH",
        str(tmp_path / "control" / "killswitch"),
    )
    return repo


def test_run_command_resolves_only_spawn_argv_and_records_path_free_interpreter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from daedalus.orchestration.execution import attempts as attempts_module

    displayed = ("python", "-I", "-S", "verify.py")
    resolved = (str(tmp_path / "private-profile" / "python.exe"), *displayed[1:])
    provenance = {
        "implementation": "cpython",
        "version": "3.13.7",
        "platform": "win32",
        "binary_sha256": "a" * 64,
    }
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        service_module,
        "resolve_python_argv",
        lambda argv: resolved,
    )
    monkeypatch.setattr(
        service_module,
        "interpreter_provenance",
        lambda executable: provenance,
    )

    def fake_command_gate(argv, **_kwargs):
        captured["spawn_argv"] = tuple(argv)

        def gate(context):
            captured["task_argv"] = context.task.gate_argv
            return SimpleNamespace(
                returncode=0,
                output="GENESIS_OK\n",
                timed_out=False,
                cancelled=False,
                duration_s=0.125,
                containment=SimpleNamespace(
                    summary=lambda: {"contained": True, "mechanism": "test"}
                ),
            )

        return gate

    monkeypatch.setattr(attempts_module, "command_gate", fake_command_gate)
    observation = service_module._run_command(
        "runtime",
        displayed,
        task_id="genesis-portable-interpreter",
        candidate_tree_sha256="b" * 64,
        workspace=tmp_path,
        switch=SimpleNamespace(
            checkpoint=lambda: None,
            should_stop=lambda: False,
        ),
        timeout_s=30.0,
    )

    payload = observation.to_dict()
    assert captured == {"spawn_argv": resolved, "task_argv": displayed}
    assert payload["schema"] == "daedalus-genesis-command-observation/2"
    assert payload["argv"] == list(displayed)
    assert payload["interpreter"] == provenance
    assert str(tmp_path) not in json.dumps(payload["interpreter"])


def test_web_genesis_runs_end_to_end_and_replays_exactly(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(authority)
    result = run_genesis(
        "Build a local task board with search",
        target="web",
        request_key="genesis:test-web",
    )

    assert result["status"] == "preview-ready"
    assert result["defaults"]["base_repository"] is None
    assert result["publication"] == {
        "status": "not-requested",
        "owner_approval_required": True,
        "automatic_promotion": False,
    }
    assert result["candidate"]["sha256"]
    assert result["evidence"]["status"] == "passed"
    assert result["roundtrip"]["status"] == "passed"
    assert all(result["roundtrip"]["checks"].values())
    assert result["roundtrip"]["checks"]["containment"] is True
    assert result["roundtrip"]["checks"]["package"] is True
    assert result["roundtrip"]["checks"]["tensor_kernel"] is True
    assert result["request_key"] == "genesis:test-web"
    assert result["roundtrip"]["checks"]["certified_template_conformance"] is True
    assert result["roundtrip"]["feature_assurance"] == {
        "approved_web_app_template_sha256": (
            service_module._APPROVED_WEB_APP_TEMPLATE_SHA256
        ),
        "browser_behavior_verified": False,
        "candidate_owned": False,
        "mechanism": "kernel-owned certified-template conformance",
        "runtime_behavior_verified_by_this_check": False,
        "limitation": (
            "The exact approved app.js template and CONFIG are checked, but "
            "browser interactions are not executed; behavioral "
            "browser verification remains a separate release gap."
        ),
    }
    assert result["preview"]["path"].endswith("/preview/")
    assert KillSwitch(repo_root=authority).read_state().running is True

    html, media_type = read_genesis_preview(result["run_id"], "")
    javascript, javascript_type = read_genesis_preview(result["run_id"], "app.js")
    assert b"<!doctype html>" in html
    assert b'id="filter" type="search"' in html
    assert b"Build a local task board with search" in javascript
    assert b"function filterItems(items, query)" in javascript
    assert media_type == "text/html; charset=utf-8"
    assert "javascript" in javascript_type

    candidate_lock = service_module.control_root(authority) / "candidate-execution.lock"
    with ExclusiveFileLock(candidate_lock, timeout_s=0, label="post-run lock probe"):
        pass

    replay = run_genesis(
        "Build a local task board with search",
        target="web",
        request_key="genesis:test-web",
        repo_root=authority,
    )
    assert replay == result


def test_green_replay_and_preview_refuse_missing_candidate_or_evidence_cas(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = run_genesis(
        "Build a local task board with search",
        target="web",
        request_key="genesis:missing-green-cas",
        repo_root=authority,
    )
    assert result["status"] == "preview-ready"

    store = service_module.SourceTreeStore.open_existing(
        service_module.control_root(authority) / "genesis" / "source-cas"
    )
    candidate_ref = service_module.ArtifactRef.from_sha256(
        result["candidate"]["sha256"]
    )
    manifest = store.load_tree(candidate_ref)
    missing_entry = next(entry for entry in manifest.entries if entry.path == "app.js")
    missing_ref = service_module.ArtifactRef.from_sha256(missing_entry.blob_sha256)
    missing_payload = store.read_bytes(missing_ref, max_bytes=missing_entry.size)
    missing_path = (
        store.objects / missing_ref.sha256[:2] / missing_ref.sha256[2:]
    )
    missing_path.unlink()

    arguments = {
        "prompt": "Build a local task board with search",
        "target": "web",
        "request_key": "genesis:missing-green-cas",
        "repo_root": authority,
    }
    with pytest.raises(service_module.GenesisError, match="candidate source tree"):
        run_genesis(**arguments)
    with pytest.raises(
        service_module.GenesisPreviewError, match="candidate source tree"
    ):
        read_genesis_preview(result["run_id"], "index.html", repo_root=authority)

    assert store.put_bytes(missing_payload) == missing_ref
    materialization_ref = service_module.ArtifactRef.from_sha256(
        result["artifacts"]["materialization_plan"]["sha256"]
    )
    materialization = service_module.MaterializationPlan.from_dict(
        json.loads(
            store.read_bytes(
                materialization_ref,
                max_bytes=service_module.MAX_REPORT_BYTES,
            )
        )
    )
    input_payload = store.read_bytes(
        materialization.input_tree,
        max_bytes=service_module.MAX_REPORT_BYTES,
    )
    input_path = (
        store.objects
        / materialization.input_tree.sha256[:2]
        / materialization.input_tree.sha256[2:]
    )
    input_path.unlink()
    with pytest.raises(service_module.GenesisError, match="empty input source tree"):
        run_genesis(**arguments)
    with pytest.raises(
        service_module.GenesisPreviewError, match="empty input source tree"
    ):
        read_genesis_preview(result["run_id"], "index.html", repo_root=authority)
    assert store.put_bytes(input_payload) == materialization.input_tree

    evidence_ref = service_module.ArtifactRef.from_sha256(
        result["artifacts"]["evidence"]["sha256"]
    )
    evidence_payload = store.read_bytes(
        evidence_ref,
        max_bytes=service_module.MAX_REPORT_BYTES,
    )
    evidence_path = (
        store.objects / evidence_ref.sha256[:2] / evidence_ref.sha256[2:]
    )
    evidence_path.unlink()

    with pytest.raises(service_module.GenesisError, match="EvidencePacket"):
        run_genesis(**arguments)
    with pytest.raises(service_module.GenesisPreviewError, match="EvidencePacket"):
        read_genesis_preview(result["run_id"], "index.html", repo_root=authority)
    assert store.put_bytes(evidence_payload) == evidence_ref

    for artifact_name, label in (
        ("roundtrip", "RoundTripReport"),
        ("run_record", "GenesisRunRecord"),
    ):
        ref = service_module.ArtifactRef.from_sha256(
            result["artifacts"][artifact_name]["sha256"]
        )
        payload = store.read_bytes(ref, max_bytes=service_module.MAX_REPORT_BYTES)
        path = store.objects / ref.sha256[:2] / ref.sha256[2:]
        path.unlink()
        with pytest.raises(service_module.GenesisError, match=label):
            run_genesis(**arguments)
        with pytest.raises(service_module.GenesisPreviewError, match=label):
            read_genesis_preview(
                result["run_id"],
                "index.html",
                repo_root=authority,
            )
        assert store.put_bytes(payload) == ref


def test_overlapping_identical_requests_converge_on_one_terminal_receipt(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both callers miss the immutable fast path; only the slot owner builds."""

    immutable_arrived = Barrier(2)
    immutable_finished = Barrier(2)
    count_lock = Lock()
    immutable_reads = 0
    wal_visible_reads = 0
    lease_calls = 0
    materializations = 0
    original_read = service_module._read_existing
    original_acquire = service_module.acquire_effect_lease
    original_write = service_module._write_rendered_files

    def synchronized_read(
        paths: object,
        request: object,
        *,
        immutable: bool = True,
    ) -> dict[str, object] | None:
        nonlocal immutable_reads, wal_visible_reads
        if immutable:
            immutable_arrived.wait(timeout=10)
            result = original_read(paths, request, immutable=True)
            assert result is None
            with count_lock:
                immutable_reads += 1
            immutable_finished.wait(timeout=10)
            return None
        with count_lock:
            wal_visible_reads += 1
        return original_read(paths, request, immutable=False)

    monkeypatch.setattr(service_module, "_read_existing", synchronized_read)
    def counted_acquire(*args: object, **kwargs: object):
        nonlocal lease_calls
        with count_lock:
            lease_calls += 1
        return original_acquire(*args, **kwargs)

    def counted_write(*args: object, **kwargs: object):
        nonlocal materializations
        with count_lock:
            materializations += 1
        return original_write(*args, **kwargs)

    monkeypatch.setattr(service_module, "acquire_effect_lease", counted_acquire)
    monkeypatch.setattr(service_module, "_write_rendered_files", counted_write)
    monkeypatch.setattr(service_module, "GENESIS_CONTROL_LOCK_TIMEOUT_S", 60.0)

    def invoke() -> dict[str, object]:
        return run_genesis(
            "Build a local task board with search",
            target="web",
            request_key="genesis:overlapping-identical",
            repo_root=authority,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(invoke)
        second_future = executor.submit(invoke)
        first = first_future.result(timeout=90)
        second = second_future.result(timeout=90)

    assert first == second
    assert first["status"] == "preview-ready"
    assert immutable_reads == 2
    assert wal_visible_reads == 2
    assert lease_calls == 2
    assert materializations == 1


def test_request_arriving_during_uncheckpointed_attempt_waits_for_exact_replay(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An immutable projection racing a live WAL is only a fast-path miss."""

    attempt_started = Event()
    second_fast_read_started = Event()
    original_prepare = service_module.IsolatedAttemptCoordinator.prepare
    original_read = service_module._read_existing

    def hold_first_after_attempt_start(self: object, *args: object, **kwargs: object):
        prepared = original_prepare(self, *args, **kwargs)
        attempt_started.set()
        assert second_fast_read_started.wait(timeout=10)
        return prepared

    def observe_racing_read(
        paths: object,
        request: object,
        *,
        immutable: bool = True,
    ) -> dict[str, object] | None:
        if immutable and attempt_started.is_set():
            second_fast_read_started.set()
        return original_read(paths, request, immutable=immutable)

    monkeypatch.setattr(
        service_module.IsolatedAttemptCoordinator,
        "prepare",
        hold_first_after_attempt_start,
    )
    monkeypatch.setattr(service_module, "_read_existing", observe_racing_read)
    monkeypatch.setattr(service_module, "GENESIS_CONTROL_LOCK_TIMEOUT_S", 60.0)

    def invoke() -> dict[str, object]:
        return run_genesis(
            "Build a local task board with search",
            target="web",
            request_key="genesis:uncheckpointed-race",
            repo_root=authority,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_future = executor.submit(invoke)
        assert attempt_started.wait(timeout=30)
        assert Path(f"{service_module.resolve_spine_db_path(authority)[0]}-wal").is_file()
        second_future = executor.submit(invoke)
        first = first_future.result(timeout=90)
        second = second_future.result(timeout=90)

    assert first == second
    assert first["status"] == "preview-ready"


def test_retry_after_grant_before_attempt_uses_a_fresh_outer_lease(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_acquire = service_module.acquire_effect_lease
    original_execution_for = service_module.WaveOffloadLease.execution_for
    granted_leases: list[object] = []
    execution_calls = 0

    def record_grant(*args: object, **kwargs: object):
        assert "lease_id" not in kwargs
        granted = original_acquire(*args, **kwargs)
        granted_leases.append(granted)
        return granted

    def fail_first_execution(self: object, *args: object, **kwargs: object):
        nonlocal execution_calls
        execution_calls += 1
        if execution_calls == 1:
            raise RuntimeError("fault after grant before Attempt start")
        return original_execution_for(self, *args, **kwargs)

    monkeypatch.setattr(service_module, "acquire_effect_lease", record_grant)
    monkeypatch.setattr(
        service_module.WaveOffloadLease,
        "execution_for",
        fail_first_execution,
    )
    arguments = {
        "prompt": "Build a local task board with search",
        "target": "web",
        "request_key": "genesis:fresh-retry-lease",
        "repo_root": authority,
    }

    with pytest.raises(RuntimeError, match="fault after grant"):
        run_genesis(**arguments)
    result = run_genesis(**arguments)

    assert result["status"] == "preview-ready"
    assert execution_calls == 2
    assert len(granted_leases) == 2
    assert all(isinstance(lease, service_module.WaveOffloadLease) for lease in granted_leases)
    assert granted_leases[0].lease_id != granted_leases[1].lease_id
    lock_path = service_module.control_root(authority) / "candidate-execution.lock"
    with ExclusiveFileLock(lock_path, timeout_s=0, label="fresh retry lock probe"):
        pass


def test_attempt_commit_wins_over_transient_outer_effect_terminal_failure(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from daedalus.kernel.authorization import NonRuntimeEffectAuthorization

    original_finish = NonRuntimeEffectAuthorization.finish_effect
    outcomes: list[str] = []

    def fail_once_after_attempt_commit(
        self: NonRuntimeEffectAuthorization,
        *args: object,
        **kwargs: object,
    ):
        outcomes.append(str(kwargs["outcome"]))
        if len(outcomes) == 1:
            raise OSError("transient outer terminal fault")
        return original_finish(self, *args, **kwargs)

    monkeypatch.setattr(
        NonRuntimeEffectAuthorization,
        "finish_effect",
        fail_once_after_attempt_commit,
    )
    arguments = {
        "prompt": "Build a local task board with search",
        "target": "web",
        "request_key": "genesis:attempt-commit-wins",
        "repo_root": authority,
    }

    first = run_genesis(**arguments)
    replay = run_genesis(**arguments)

    assert first == replay
    assert first["status"] == "preview-ready"
    assert outcomes == ["COMPLETED", "COMPLETED"]


def test_persistent_outer_terminal_failure_reports_reconciliation_debt_without_rewrite(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from daedalus.kernel.authorization import NonRuntimeEffectAuthorization

    original_finish = NonRuntimeEffectAuthorization.finish_effect
    outcomes: list[str] = []

    def always_fail(
        self: NonRuntimeEffectAuthorization,
        *args: object,
        **kwargs: object,
    ) -> object:
        del self, args
        outcomes.append(str(kwargs["outcome"]))
        raise OSError("persistent outer terminal fault")

    monkeypatch.setattr(NonRuntimeEffectAuthorization, "finish_effect", always_fail)
    arguments = {
        "prompt": "Build a local task board with search",
        "target": "web",
        "request_key": "genesis:persistent-reconciliation-debt",
        "repo_root": authority,
    }

    with pytest.raises(
        service_module.GenesisError,
        match="needs ledger/evidence reconciliation",
    ):
        run_genesis(**arguments)
    assert outcomes == ["COMPLETED", "COMPLETED"]

    monkeypatch.setattr(NonRuntimeEffectAuthorization, "finish_effect", original_finish)
    with pytest.raises(
        service_module.GenesisReconciliationError,
        match="bound terminal evidence is missing",
    ):
        run_genesis(**arguments)
    run_id = normalize_genesis_request(
        arguments["prompt"],
        target=arguments["target"],
        request_key=arguments["request_key"],
    ).run_id
    with pytest.raises(
        service_module.GenesisPreviewError,
        match="bound terminal evidence is missing",
    ):
        read_genesis_preview(run_id, "index.html", repo_root=authority)


def test_missing_outer_terminal_evidence_reports_reconciliation_debt(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_retain = service_module.WaveOffloadLease.retain_terminal_record

    def lose_terminal_evidence(
        self: service_module.WaveOffloadLease,
        execution: object,
    ) -> None:
        del self, execution
        return None

    monkeypatch.setattr(
        service_module.WaveOffloadLease,
        "retain_terminal_record",
        lose_terminal_evidence,
    )
    arguments = {
        "prompt": "Build a local task board with search",
        "target": "web",
        "request_key": "genesis:missing-terminal-evidence",
        "repo_root": authority,
    }

    with pytest.raises(
        service_module.GenesisError,
        match="needs ledger/evidence reconciliation",
    ):
        run_genesis(**arguments)

    monkeypatch.setattr(
        service_module.WaveOffloadLease,
        "retain_terminal_record",
        original_retain,
    )
    with pytest.raises(
        service_module.GenesisReconciliationError,
        match="bound terminal evidence is missing",
    ):
        run_genesis(**arguments)
    run_id = normalize_genesis_request(
        arguments["prompt"],
        target=arguments["target"],
        request_key=arguments["request_key"],
    ).run_id
    with pytest.raises(
        service_module.GenesisPreviewError,
        match="bound terminal evidence is missing",
    ):
        read_genesis_preview(run_id, "index.html", repo_root=authority)


def test_missing_execution_evidence_refuses_before_candidate_work(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from daedalus.kernel import offload_lease as offload_lease_module

    monkeypatch.setattr(
        offload_lease_module,
        "record_effect_lease_execution",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        service_module,
        "_write_rendered_files",
        lambda *_args, **_kwargs: pytest.fail(
            "candidate work started without retained execution evidence"
        ),
    )

    with pytest.raises(
        service_module.GenesisError,
        match="invocation effect evidence was not retained",
    ):
        run_genesis(
            "Build a local task board with search",
            target="web",
            request_key="genesis:missing-execution-record",
            repo_root=authority,
        )


def test_failed_attempt_settlement_debt_is_not_returned_as_a_normal_failure(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcomes: list[str] = []

    def fail_after_attempt_start(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("fault after Attempt start")

    def refuse_settlement(
        _granted: object,
        _effect_start: object,
        _execution: object,
        *,
        outcome: str,
        output_digests: object,
        detail_sha256: str,
    ) -> bool:
        del output_digests, detail_sha256
        outcomes.append(outcome)
        return False

    monkeypatch.setattr(
        service_module,
        "_write_rendered_files",
        fail_after_attempt_start,
    )
    monkeypatch.setattr(
        service_module,
        "_settle_committed_genesis_effect",
        refuse_settlement,
    )

    with pytest.raises(
        service_module.GenesisReconciliationError,
        match="failed Attempt is canonical",
    ):
        run_genesis(
            "Build a local task board with search",
            target="web",
            request_key="genesis:failed-settlement-debt",
            repo_root=authority,
        )
    assert outcomes == ["FAILED"]


def test_failed_attempt_receipt_commit_debt_is_not_returned_as_normal_failure(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_after_attempt_start(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("fault after Attempt start")

    def refuse_terminal_receipt(*_args: object, **_kwargs: object) -> None:
        raise OSError("terminal receipt unavailable")

    monkeypatch.setattr(
        service_module,
        "_write_rendered_files",
        fail_after_attempt_start,
    )
    monkeypatch.setattr(
        service_module.AttemptLedger,
        "complete",
        refuse_terminal_receipt,
    )

    with pytest.raises(
        service_module.GenesisReconciliationError,
        match="terminal receipt could not be committed",
    ):
        run_genesis(
            "Build a local task board with search",
            target="web",
            request_key="genesis:failed-receipt-debt",
            repo_root=authority,
        )


def test_operation_lease_binding_is_stable_across_invocation_timestamps() -> None:
    request = normalize_genesis_request(
        "Build a local task board with search",
        target="web",
        request_key="genesis:stable-operation-binding",
    )
    files = service_module.render_project(
        request.prompt,
        product_name=request.product_name,
        target=request.target,
        features=request.features,
    )

    def bound_at(created_at: str):
        plan = build_genesis_plan(request, created_at=created_at)
        empty_tree = service_module._empty_input_tree(plan, created_at=created_at)
        return service_module.bind_genesis_attempt(
            plan,
            input_tree=empty_tree.ref,
            expected_outputs=tuple(files),
            python_version="3.12.0",
            created_at=created_at,
        )

    first = bound_at("2026-09-04T10:00:00.000000+00:00")
    second = bound_at("2026-09-04T10:00:01.000000+00:00")

    assert first.materialization.digest != second.materialization.digest
    assert service_module._genesis_operation_sha(request, first, files) == (
        service_module._genesis_operation_sha(request, second, files)
    )


def test_preview_refuses_candidate_not_bound_by_terminal_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = normalize_genesis_request(
        "Build a local task board",
        request_key="genesis:preview-cross-bind",
    )
    source_store = tmp_path / "cas"
    source_store.mkdir()
    spine_db = tmp_path / "spine.sqlite3"
    spine_db.touch()
    report_candidate = service_module.ArtifactRef.from_sha256("a" * 64)
    receipt_candidate = service_module.ArtifactRef.from_sha256("b" * 64)
    report_ref = service_module.ArtifactRef.from_sha256("c" * 64)
    report = service_module.canonical_json(
        {
            "run_id": request.run_id,
            "status": "preview-ready",
            "candidate": {"sha256": report_candidate.sha256},
        }
    ).encode("ascii")

    class Store:
        @staticmethod
        def read_bytes(ref: object, *, max_bytes: int) -> bytes:
            assert ref == report_ref
            assert max_bytes == service_module.MAX_REPORT_BYTES
            return report

    existing = SimpleNamespace(
        start=SimpleNamespace(source_revision=request.source_revision),
        completion=SimpleNamespace(
            receipt=SimpleNamespace(
                outcome="succeeded",
                candidate_tree=receipt_candidate,
                report=report_ref,
                source_revision=request.source_revision,
            )
        ),
    )
    monkeypatch.setattr(
        service_module,
        "_state_paths",
        lambda *_args: SimpleNamespace(source_store=source_store, spine_db=spine_db),
    )
    monkeypatch.setattr(
        service_module.SourceTreeStore,
        "open_existing",
        lambda *_args: Store(),
    )
    monkeypatch.setattr(
        service_module.AttemptLedger,
        "lookup_read_only",
        lambda *_args, **_kwargs: existing,
    )

    with pytest.raises(
        service_module.GenesisPreviewError,
        match="does not match its terminal Attempt receipt",
    ):
        read_genesis_preview(request.run_id, "index.html", repo_root=tmp_path)


def test_cli_genesis_is_green_without_claiming_browser_preview(authority: Path) -> None:
    result = run_genesis(
        "Create a command-line task tracker",
        target="cli",
        request_key="genesis:test-cli",
        repo_root=authority,
    )

    assert result["status"] == "succeeded"
    assert result["request_key"] == "genesis:test-cli"
    assert result["preview"] is None
    assert result["evidence"]["status"] == "passed"
    assert result["roundtrip"]["checks"]["cli_black_box"] is True
    assert result["roundtrip"]["feature_assurance"] == {
        "browser_behavior_verified": False,
        "candidate_owned": False,
        "cli_black_box_verified": True,
        "mechanism": (
            "kernel-owned structural source conformance plus contained "
            "CLI black-box scenario"
        ),
        "runtime_behavior_verified_by_this_check": True,
    }
    assert result["candidate"]["files"] == [
        "README.md",
        "app.py",
        "fourfold.json",
        "schemas/item.schema.json",
        "tests/test_app.py",
    ]


def test_blocked_request_has_no_filesystem_effect(authority: Path) -> None:
    result = run_genesis(
        "Build an app that must use OAuth login",
        request_key="genesis:test-blocked",
        repo_root=authority,
    )

    assert result["status"] == "blocked"
    assert result["request_key"] == "genesis:test-blocked"
    assert result["admission"]["effect_started"] is False
    assert result["candidate"] is None
    assert list(authority.iterdir()) == []


@pytest.mark.parametrize(
    "prompt",
    (
        "Build a calculator",
        "Create a weather dashboard",
        "Make a platform game",
    ),
)
def test_product_shapes_outside_the_local_collection_slice_block_before_effects(
    authority: Path,
    prompt: str,
) -> None:
    result = run_genesis(
        prompt,
        request_key=f"genesis:unsupported:{prompt}",
        repo_root=authority,
    )

    assert result["status"] == "blocked"
    assert result["admission"]["effect_started"] is False
    assert any("Unsupported product shape" in row for row in result["blockers"])
    assert list(authority.iterdir()) == []


@pytest.mark.parametrize(
    "requirement",
    (
        "Stripe payments",
        "login",
        "calendar",
        "Pomodoro",
        "Firebase",
        "Supabase",
        "an API",
        "reminders",
        "tags",
        "due dates",
        "attachments",
        "export",
        "Kanban",
        "AI",
        "maps",
        "a calculator",
        "weather",
        "a game",
        "ecommerce",
        "React",
        "Rust",
        "Electron",
        "a smartwatch",
        "VR",
    ),
)
def test_unknown_piggyback_requirement_blocks_before_any_effect(
    authority: Path,
    requirement: str,
) -> None:
    result = run_genesis(
        f"Build a local task list with {requirement}",
        request_key=f"genesis:unsupported-requirement:{requirement}",
        repo_root=authority,
    )

    assert result["status"] == "blocked"
    assert result["admission"]["effect_started"] is False
    grammar_blockers = [
        row
        for row in result["blockers"]
        if row.startswith("Unsupported Genesis v1 requirement token(s):")
    ]
    assert len(grammar_blockers) == 1
    assert len(grammar_blockers[0]) < 1_000
    assert result["candidate"] is None
    assert list(authority.iterdir()) == []


def test_unsupported_requirement_diagnostic_is_deduplicated_and_bounded() -> None:
    unknown = " ".join(f"extra{index}" for index in range(100))
    request = normalize_genesis_request(
        f"Build a local task list with {unknown}",
        request_key="genesis:bounded-unsupported-requirements",
    )

    grammar = [
        row
        for row in request.blockers
        if row.startswith("Unsupported Genesis v1 requirement token(s):")
    ]
    assert len(grammar) == 1
    assert "(+88 more)" in grammar[0]
    assert len(grammar[0]) < 1_000


@pytest.mark.parametrize(
    ("prompt", "expected_target"),
    (
        ("Build a native desktop task board", "desktop"),
        ("Build an inventory app as an APK for the Play Store", "mobile"),
        ("Build a mobile notes app for the App Store", "mobile"),
        ("Build a local task list with packaging", "web"),
        ("Build a local task list with signing", "web"),
        ("Build a local task list with publication", "web"),
    ),
)
def test_explicit_native_or_store_packaging_blocks_before_effects(
    authority: Path,
    prompt: str,
    expected_target: str,
) -> None:
    result = run_genesis(
        prompt,
        request_key=f"genesis:native-block:{expected_target}:{prompt}",
        repo_root=authority,
    )

    assert result["status"] == "blocked"
    assert result["target"] == expected_target
    assert result["admission"]["effect_started"] is False
    assert result["candidate"] is None
    assert any("native or store packaging" in row for row in result["blockers"])
    assert list(authority.iterdir()) == []


@pytest.mark.parametrize(
    "prompt",
    (
        "Build a desktop task board",
        "Build a mobile notes collection",
        "Build a desktop task list without native packaging",
    ),
)
def test_pwa_targets_without_native_requirement_remain_admitted(prompt: str) -> None:
    request = normalize_genesis_request(
        prompt,
        request_key=f"genesis:pwa-admission:{prompt}",
    )

    assert request.admitted is True
    assert request.target in {"desktop", "mobile"}
    assert any("installable offline PWA" in notice for notice in request.notices)


def test_explicit_pwa_alias_remains_admitted_with_non_native_notice() -> None:
    request = normalize_genesis_request(
        "Build a local task board",
        target="pwa",
        request_key="genesis:pwa-alias-admission",
    )

    assert request.admitted is True
    assert request.target == "web"
    assert any("offline browser application" in notice for notice in request.notices)
    assert any("not as a native store package" in notice for notice in request.notices)


def test_certified_template_check_rejects_missing_requested_search(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_render = service_module.render_project

    def render_without_search_wiring(*args: object, **kwargs: object) -> dict[str, bytes]:
        files = dict(real_render(*args, **kwargs))
        source = files["app.js"].decode("utf-8")
        files["app.js"] = source.replace(
            "if (filterInput) filterInput.addEventListener('input', render);",
            "// search wiring removed by the candidate",
            1,
        ).encode("utf-8")
        return files

    monkeypatch.setattr(service_module, "render_project", render_without_search_wiring)
    result = run_genesis(
        "Build a local task board with search",
        target="web",
        request_key="genesis:feature-search-mutation",
        repo_root=authority,
    )

    assert result["status"] == "failed"
    assert result["evidence"]["status"] == "failed"
    assert result["roundtrip"]["status"] == "failed"
    assert result["roundtrip"]["checks"]["certified_template_conformance"] is False
    assert result["roundtrip"]["checks"]["test"] is True
    assert result["preview"] is None
    assert any(
        "certified_template_conformance check failed" in row
        for row in result["blockers"]
    )


def test_certified_template_check_rejects_a_noop_web_create_item(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_render = service_module.render_project

    def render_noop_create(*args: object, **kwargs: object) -> dict[str, bytes]:
        files = dict(real_render(*args, **kwargs))
        source = files["app.js"].decode("utf-8")
        original = "state.items.push({ id: state.nextId, title, details, done: false });"
        replacement = "void title; void details; // candidate no-op"
        assert source.count(original) == 1
        files["app.js"] = source.replace(original, replacement, 1).encode("utf-8")
        return files

    monkeypatch.setattr(service_module, "render_project", render_noop_create)
    result = run_genesis(
        "Build a local task board",
        target="web",
        request_key="genesis:noop-web-create",
        repo_root=authority,
    )

    assert result["status"] == "failed"
    assert result["roundtrip"]["checks"]["test"] is True
    assert result["roundtrip"]["checks"]["certified_template_conformance"] is False
    assert result["preview"] is None


def test_kernel_structural_feature_check_rejects_unwired_cli_search(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_render = service_module.render_project

    def render_without_search_command(*args: object, **kwargs: object) -> dict[str, bytes]:
        files = dict(real_render(*args, **kwargs))
        source = files["app.py"].decode("utf-8")
        files["app.py"] = source.replace(
            'search_parser = commands.add_parser("search")',
            'search_parser = commands.add_parser("lookup")',
            1,
        ).encode("utf-8")
        return files

    monkeypatch.setattr(service_module, "render_project", render_without_search_command)
    result = run_genesis(
        "Create a command-line inventory with search",
        target="cli",
        request_key="genesis:feature-cli-search-mutation",
        repo_root=authority,
    )

    assert result["status"] == "failed"
    assert result["evidence"]["status"] == "failed"
    assert result["roundtrip"]["checks"]["feature_conformance"] is False
    assert result["roundtrip"]["checks"]["test"] is True


def test_one_request_key_cannot_be_rebound(authority: Path) -> None:
    run_genesis(
        "Build the first local task board",
        request_key="genesis:test-conflict",
        repo_root=authority,
    )

    with pytest.raises(GenesisConflictError, match="request_key"):
        run_genesis(
            "Build a different local task board",
            request_key="genesis:test-conflict",
            repo_root=authority,
        )


def test_explicit_target_and_stack_flags_are_preserved_in_identity_and_intent() -> None:
    implicit = normalize_genesis_request(
        "Build a local task board",
        request_key="genesis:required-flags",
    )
    explicit = normalize_genesis_request(
        "Build a local task board",
        target="web",
        stack="python-stdlib",
        request_key="genesis:required-flags",
    )

    assert implicit.admitted is True
    assert implicit.target_required is False
    assert implicit.stack_required is False
    assert implicit.requested_target is None
    assert implicit.requested_stack is None
    assert explicit.admitted is True
    assert explicit.target_required is True
    assert explicit.stack_required is True
    assert explicit.requested_target == "web"
    assert explicit.requested_stack == "python-stdlib"
    assert explicit.defaults["target_required"] is True
    assert explicit.defaults["stack_required"] is True
    assert explicit.run_id == implicit.run_id
    assert explicit.source_revision != implicit.source_revision

    plan = build_genesis_plan(
        explicit,
        created_at="2026-09-04T00:00:00.000000+00:00",
    )
    assert plan.intent.target_required is True
    assert plan.intent.stack_required is True
    assert plan.intent.target == "web"
    assert plan.intent.stack == "python-stdlib"


def test_each_gate_starts_from_captured_candidate_cas_and_test_mutation_is_ephemeral(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_render = service_module.render_project
    real_run_command = service_module._run_command
    observed: list[tuple[str, str, Path]] = []

    def render_with_mutating_candidate_test(
        *args: object, **kwargs: object
    ) -> dict[str, bytes]:
        files = dict(real_render(*args, **kwargs))
        tests = files["tests/test_project.py"].decode("utf-8")
        marker = '\n\nif __name__ == "__main__":\n'
        mutation = (
            "\n    def test_zz_mutates_only_its_gate_workspace(self) -> None:\n"
            "        (ROOT / 'app.js').write_text('// poisoned by candidate test\\n', encoding='utf-8')\n"
            "        (ROOT / 'fourfold.json').write_text('{}\\n', encoding='utf-8')\n"
        )
        assert tests.count(marker) == 1
        files["tests/test_project.py"] = tests.replace(
            marker,
            mutation + marker,
            1,
        ).encode("utf-8")
        return files

    def observe_command(name: str, *args: object, **kwargs: object):
        observed.append(
            (
                name,
                str(kwargs["candidate_tree_sha256"]),
                Path(kwargs["workspace"]),
            )
        )
        return real_run_command(name, *args, **kwargs)

    monkeypatch.setattr(
        service_module,
        "render_project",
        render_with_mutating_candidate_test,
    )
    monkeypatch.setattr(service_module, "_run_command", observe_command)
    result = run_genesis(
        "Build a local task board with search",
        target="web",
        request_key="genesis:fresh-cas-gates",
        repo_root=authority,
    )

    candidate_sha = result["candidate"]["sha256"]
    assert result["status"] == "preview-ready"
    assert result["roundtrip"]["checks"]["test"] is True
    assert result["roundtrip"]["checks"]["certified_template_conformance"] is True
    assert {name for name, _, _ in observed} == {
        "build",
        "test",
        "runtime",
        "package",
    }
    assert all(digest == candidate_sha for _, digest, _ in observed)
    assert len({workspace for _, _, workspace in observed}) == len(observed)
    test_workspace = next(
        workspace for name, _, workspace in observed if name == "test"
    )
    assert (test_workspace / "app.js").read_text(encoding="utf-8").startswith(
        "// poisoned by candidate test"
    )
    for name in ("runtime", "package"):
        workspace = next(
            row_workspace
            for row_name, _, row_workspace in observed
            if row_name == name
        )
        assert "function createItem" in (workspace / "app.js").read_text(
            encoding="utf-8"
        )
    preview_source, _ = read_genesis_preview(
        result["run_id"],
        "app.js",
        repo_root=authority,
    )
    assert b"function createItem" in preview_source
    assert b"poisoned by candidate test" not in preview_source

    source_store = service_module.SourceTreeStore.open_existing(
        service_module.control_root(authority) / "genesis" / "source-cas"
    )
    packet = json.loads(
        source_store.read_bytes(
            service_module.ArtifactRef.from_sha256(
                result["artifacts"]["evidence"]["sha256"]
            ),
            max_bytes=service_module.MAX_REPORT_BYTES,
        )
    )
    assert packet["subject_sha256"] == candidate_sha
    genesis_items = [
        item
        for item in packet["items"]
        if item["evaluator"].startswith("genesis.")
    ]
    assert genesis_items
    assert all(
        item["details"]["candidate_tree_sha256"] == candidate_sha
        for item in genesis_items
    )


def test_normalization_defaults_are_visible_and_target_inference_is_stable() -> None:
    cli = normalize_genesis_request(
        "Eine App für die Kommandozeile",
        request_key="genesis:normalize",
    )
    duplicate = normalize_genesis_request(
        "Eine App für die Kommandozeile",
        request_key="genesis:normalize",
    )

    assert cli.target == "cli"
    assert cli.defaults["authentication"] is False
    assert cli.defaults["telemetry"] is False
    assert "optional search/filter" in cli.defaults["capability_scope"]
    assert cli.run_id == duplicate.run_id
    assert cli.source_revision == duplicate.source_revision

    german_collection = normalize_genesis_request(
        "Eine lokale Liste f\u00fcr Wartungsaufgaben",
        request_key="genesis:german-collection",
    )
    assert german_collection.admitted is True


def test_explicit_unsupported_stack_blocks_before_planning() -> None:
    request = normalize_genesis_request(
        "Build a local board",
        target="web",
        stack="required-react-cloud-stack",
        request_key="genesis:unsupported-stack",
    )

    assert request.admitted is False
    assert any("Unsupported required stack" in blocker for blocker in request.blockers)


def test_owner_stop_is_sticky_and_blocks_before_genesis_state(authority: Path) -> None:
    switch = KillSwitch(repo_root=authority)
    switch.stop("test owner stop")

    result = run_genesis(
        "Build a local board",
        target="web",
        request_key="genesis:sticky-stop",
        repo_root=authority,
    )

    assert result["status"] == "blocked"
    assert result["admission"] == {
        "effect_started": False,
        "genesis_control": "blocked",
    }
    assert any("stop marker" in blocker for blocker in result["blockers"])
    assert switch.marker_path.is_file()
    assert switch.read_state().running is False


def test_parallel_candidate_is_retryably_blocked_before_an_attempt(
    authority: Path,
) -> None:
    lock_path = service_module.control_root(authority) / "candidate-execution.lock"
    with ExclusiveFileLock(lock_path, timeout_s=0, label="test Genesis holder"):
        result = run_genesis(
            "Build another local board",
            target="web",
            request_key="genesis:parallel-refusal",
            repo_root=authority,
        )

    assert result["status"] == "blocked"
    assert result["request_key"] == "genesis:parallel-refusal"
    assert result["admission"]["effect_started"] is False
    assert any("execution slot" in blocker for blocker in result["blockers"])
    assert not (authority / "runs" / "spine" / "spine.sqlite3").exists()
    assert KillSwitch(repo_root=authority).read_state().running is False


def test_running_result_retains_request_key_and_limits_replay_claim() -> None:
    request = normalize_genesis_request(
        "Build a local task board",
        request_key="genesis:pending-result",
    )

    result = service_module._pending_result(request)

    assert result["request_key"] == request.request_key
    assert result["status"] == "running"
    assert any("only replays terminal receipts" in row for row in result["blockers"])
    assert any("crash reconciliation is not implemented" in row for row in result["blockers"])


def test_pending_effect_replay_error_releases_global_candidate_lock(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class ReplayAuthorization:
        @staticmethod
        def begin_effect(_execution: object) -> object:
            return type("EffectStart", (), {"execute": False})()

    class ReplayLease:
        authorization = ReplayAuthorization()

        @staticmethod
        def execution_for(*_args: object, **_kwargs: object) -> object:
            return object()

    read_count = 0

    def fail_during_effect_replay(*_args: object, **_kwargs: object) -> None:
        nonlocal read_count
        read_count += 1
        if read_count == 1:
            return None
        raise RuntimeError("retained replay read failed")

    monkeypatch.setattr(service_module, "WaveOffloadLease", ReplayLease)
    monkeypatch.setattr(
        service_module,
        "acquire_effect_lease",
        lambda *_args, **_kwargs: ReplayLease(),
    )
    monkeypatch.setattr(
        service_module,
        "_invocation_effect_identity",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(service_module, "_read_existing", fail_during_effect_replay)

    with pytest.raises(RuntimeError, match="retained replay read failed"):
        run_genesis(
            "Build a local task board",
            target="web",
            request_key="genesis:replay-read-error",
            repo_root=authority,
        )

    assert read_count == 2
    lock_path = service_module.control_root(authority) / "candidate-execution.lock"
    with ExclusiveFileLock(lock_path, timeout_s=0, label="replay lock probe"):
        pass


def test_post_attempt_failure_report_replays_with_bound_failed_effect(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_after_attempt_start(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("fault after Attempt start")

    monkeypatch.setattr(
        service_module,
        "_write_rendered_files",
        fail_after_attempt_start,
    )
    arguments = {
        "prompt": "Build a local task board with search",
        "target": "web",
        "request_key": "genesis:failed-effect-replay",
        "repo_root": authority,
    }

    first = run_genesis(**arguments)
    replay = run_genesis(**arguments)

    assert first == replay
    assert first["status"] == "failed"
    assert first["invocation_effect"]["expected_terminal_state"] == "failed"


def test_cleanup_failure_still_releases_shared_candidate_lock(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_materialization(*args: object, **kwargs: object) -> None:
        raise RuntimeError("materialization probe failure")

    def fail_watch_cleanup(self: KillSwitch) -> None:
        raise RuntimeError("watch cleanup failed")

    monkeypatch.setattr(
        service_module,
        "_write_rendered_files",
        fail_materialization,
    )
    monkeypatch.setattr(
        KillSwitch,
        "stop_watch",
        fail_watch_cleanup,
    )

    with pytest.raises(RuntimeError, match="watch cleanup failed"):
        run_genesis(
            "Build a local task board",
            target="web",
            request_key="genesis:cleanup-lock-release",
            repo_root=authority,
        )

    lock_path = service_module.control_root(authority) / "candidate-execution.lock"
    with ExclusiveFileLock(lock_path, timeout_s=0, label="cleanup lock probe"):
        pass


def test_stop_during_build_is_retained_as_negative_evidence(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_run_command = service_module._run_command
    stopped = False

    def stop_before_command(*args: object, **kwargs: object):
        nonlocal stopped
        switch = kwargs["switch"]
        assert isinstance(switch, KillSwitch)
        if not stopped:
            stopped = True
            switch.stop("test cancellation during Genesis")
        return real_run_command(*args, **kwargs)

    monkeypatch.setattr(service_module, "_run_command", stop_before_command)
    arguments = {
        "prompt": "Build a local board",
        "target": "web",
        "request_key": "genesis:cancelled",
        "repo_root": authority,
    }
    result = run_genesis(**arguments)
    switch = KillSwitch(repo_root=authority)

    assert result["status"] == "failed"
    assert result["preview"] is None
    assert any("kill switch engaged" in blocker for blocker in result["blockers"])
    assert switch.marker_path.is_file()
    assert switch.read_state().running is False


def test_failed_candidate_replay_requires_negative_candidate_and_evidence_bytes(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_run_command = service_module._run_command

    def fail_build(name: str, *args: object, **kwargs: object):
        observation = real_run_command(name, *args, **kwargs)
        if name == "build":
            return replace(observation, returncode=1, output="forced build failure")
        return observation

    monkeypatch.setattr(service_module, "_run_command", fail_build)
    arguments = {
        "prompt": "Build a local board",
        "target": "web",
        "request_key": "genesis:negative-cas-replay",
        "repo_root": authority,
    }
    result = run_genesis(**arguments)
    assert result["status"] == "failed"
    assert result["candidate"] is not None
    assert result["evidence"]["status"] == "failed"
    assert run_genesis(**arguments) == result

    store = service_module.SourceTreeStore.open_existing(
        service_module.control_root(authority) / "genesis" / "source-cas"
    )
    candidate_ref = service_module.ArtifactRef.from_sha256(
        result["candidate"]["sha256"]
    )
    manifest = store.load_tree(candidate_ref)
    entry = manifest.entries[0]
    blob_ref = service_module.ArtifactRef.from_sha256(entry.blob_sha256)
    blob = store.read_bytes(blob_ref, max_bytes=entry.size)
    blob_path = store.objects / blob_ref.sha256[:2] / blob_ref.sha256[2:]
    blob_path.unlink()
    with pytest.raises(service_module.GenesisError, match="candidate source tree"):
        run_genesis(**arguments)
    assert store.put_bytes(blob) == blob_ref

    packet_ref = service_module.ArtifactRef.from_sha256(
        result["artifacts"]["evidence"]["sha256"]
    )
    packet = service_module.EvidencePacket.from_dict(
        json.loads(
            store.read_bytes(packet_ref, max_bytes=service_module.MAX_REPORT_BYTES)
        )
    )
    evidence_store = service_module.ArtifactStore(
        service_module.control_root(authority)
        / "genesis"
        / "evidence"
        / result["run_id"]
    )
    locator_digest = packet.items[0].evidence_locator.rsplit(":", 1)[-1]
    evidence_locator = evidence_store.load_locator(locator_digest)
    evidence_locator.blob_path.unlink()
    with pytest.raises(service_module.GenesisError, match="evidence artifact"):
        run_genesis(**arguments)


@pytest.mark.skipif(
    service_module.sys.platform != "win32",
    reason="the canonical candidate write-containment mechanism is Windows MIC",
)
def test_candidate_process_cannot_write_outside_its_workspace(
    authority: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outside = tmp_path / "outside-workspace.txt"
    real_render = service_module.render_project

    def escaping_render(*args: object, **kwargs: object) -> dict[str, bytes]:
        files = dict(real_render(*args, **kwargs))
        source = files["app.py"].decode("utf-8")
        insertion = (
            "from pathlib import Path as _EscapePath\n"
            f"_EscapePath({str(outside)!r}).write_text('escaped', encoding='utf-8')\n"
        )
        marker = "from __future__ import annotations\n"
        files["app.py"] = source.replace(marker, marker + insertion, 1).encode("utf-8")
        return files

    monkeypatch.setattr(service_module, "render_project", escaping_render)
    result = run_genesis(
        "Create a command-line task tracker",
        target="cli",
        request_key="genesis:escape-regression",
        repo_root=authority,
    )

    assert outside.exists() is False
    assert result["status"] == "failed"
    assert result["evidence"]["status"] == "failed"
    assert result["preview"] is None


def test_legacy_item_collection_identity_and_evaluator_remain_frozen() -> None:
    request = normalize_genesis_request(
        "Build a local task board with search",
        target="web",
        request_key="genesis:test-web",
    )
    created_at = "2026-09-05T00:00:00+00:00"
    plan = build_genesis_plan(request, created_at=created_at)
    files = service_module.render_project(
        request.prompt,
        request.product_name,
        request.target,
        features=request.features,
    )
    empty = service_module._empty_input_tree(plan, created_at=created_at)
    bound = service_module.bind_genesis_attempt(
        plan,
        input_tree=empty.ref,
        expected_outputs=tuple(files),
        python_version="3.13.7",
        created_at=created_at,
    )

    assert request.blueprint == "item-collection-v1"
    assert request.policy_version == "11.2"
    assert GENESIS_RUN_ID_NAMESPACE_VERSION == "11.2"
    assert request.source_revision == "f89c0355c51a979aaf5e21bb315fb8e685ca587b"
    assert request.run_id == "genesis-c68374a179a83ebd864f3f58"
    assert service_module._APPROVED_WEB_APP_TEMPLATE_SHA256 == (
        "8f0c5f1981bc8e08f355478f3a80a03a8a62198b5697924aed5cf5987d292275"
    )
    assert service_module._CLI_BLACK_BOX_TEMPLATE_SHA256 == (
        "f42cdefe973e6fa392e925877d008e4eafcdbc1be5dba800fd49012ee7055be7"
    )
    assert service_module._EVALUATOR_SHA256 == (
        "197bc14cf98255c08f16a0b1447e8d9598f5114b9d829c9674321e697364dde7"
    )
    assert plan.policy.digest == (
        "b3880070365348374ab49796a2ce4232b2f8ce50f15ece10a3a9dc86907c5da7"
    )
    assert plan.product.digest == (
        "d882837e7046de89b7eb16554d3ec51d120924ee65932d07362978832d159998"
    )
    assert plan.target_spec.digest == (
        "dc5d06c8f6cc360029fab2fc341a99738ae90c9e65ac259ddc5eee0b0dda6854"
    )
    assert plan.mission.digest == (
        "3d425c397622ce037f8bc91fdade72fb68eb2710745515d6799b73bfdef26366"
    )
    assert bound.materialization.digest == (
        "aedee10979712d09d90b020bb50ef59dd05ee800784a6fd4129bd6121c7293af"
    )
    assert bound.toolchain.digest == (
        "2095c854125423dfe48d77a5c216e6585dffbbd5bd01e10cf4481bd9d08bb178"
    )
    assert bound.attempt.digest == (
        "d49f5cbb7fa47951b1338908020c3cdfdf9a8560a1d04c14a500cb5b642e9bdc"
    )
    rendered_digest = hashlib.sha256(
        b"".join(path.encode() + b"\0" + payload for path, payload in files.items())
    ).hexdigest()
    assert rendered_digest == (
        "0fa4045c654f65c39fb3d5f01b8259f06dadfa49b3fcd218022e8248097c970a"
    )
    assert service_module._genesis_operation_sha(request, bound, files) == (
        "8a2209481e31282f724d625ed7e543519a7d7d118d9fd5c973d8f36510f8c46a"
    )
    assert service_module._genesis_operation_sha(request, bound, files, tensor_kernel=True) == (
        "e6d37c5046c11a8226dac10a093fb0a2400bdf0c696b2cf688ab9c9c372ca6be"
    )


@pytest.mark.parametrize(
    ("prompt", "expected_blueprint", "admitted"),
    (
        ("Build a local kanban board", "kanban-board-v1", True),
        ("Build a local kanban-board with search", "kanban-board-v1", True),
        ("Build a local task board", "item-collection-v1", True),
        ("Build a local kanban boards", "item-collection-v1", False),
        ("Build a local kanbanboard", "item-collection-v1", False),
    ),
)
def test_only_exact_kanban_phrase_selects_the_new_blueprint(
    prompt: str,
    expected_blueprint: str,
    admitted: bool,
) -> None:
    request = normalize_genesis_request(
        prompt,
        request_key=f"genesis:kanban-routing:{prompt}",
    )

    assert request.blueprint == expected_blueprint
    assert request.admitted is admitted
    assert request.policy_version == (
        "12.1" if expected_blueprint == "kanban-board-v1" else "11.2"
    )


@pytest.mark.parametrize("target", ("web", "desktop", "mobile"))
def test_kanban_policy_admits_only_the_three_pwa_targets(target: str) -> None:
    request = normalize_genesis_request(
        "Build a local kanban board",
        target=target,
        request_key=f"genesis:kanban-target:{target}",
    )
    plan = build_genesis_plan(
        request,
        created_at="2026-09-05T00:00:00+00:00",
    )

    assert request.admitted is True
    assert request.target == target
    assert plan.policy.policy_version == "12.1"
    assert plan.policy.allowed_targets == ("desktop", "mobile", "web")
    assert "cli" not in plan.policy.allowed_targets


@pytest.mark.parametrize(
    ("prompt", "target", "stack"),
    (
        ("Build a local kanban board", "cli", None),
        ("Build a local kanban board with custom columns", "web", None),
        ("Build a local kanban board with swimlanes", "web", None),
        ("Build a local kanban board", "web", "custom-stack"),
    ),
)
def test_unsupported_kanban_requirements_refuse_before_any_effect(
    authority: Path,
    prompt: str,
    target: str,
    stack: str | None,
) -> None:
    result = run_genesis(
        prompt,
        target=target,
        stack=stack,
        request_key=f"genesis:kanban-refusal:{prompt}:{target}:{stack}",
        repo_root=authority,
    )

    assert result["status"] == "blocked"
    assert result["admission"]["effect_started"] is False
    assert result["candidate"] is None
    assert list(authority.iterdir()) == []


def test_kanban_runs_replays_and_previews_with_its_persisted_profile(
    authority: Path,
) -> None:
    legacy = run_genesis(
        "Build a local task board",
        target="web",
        request_key="genesis:legacy-beside-kanban",
        repo_root=authority,
    )
    assert legacy["status"] == "preview-ready"

    result = run_genesis(
        "Build a local kanban board with search",
        target="web",
        request_key="genesis:kanban-e2e",
        repo_root=authority,
    )

    assert result["status"] == "preview-ready"
    assert result["defaults"]["blueprint"] == "kanban-board-v1"
    assert result["defaults"]["product_class"] == "local-first kanban board"
    assert result["candidate"]["files"] == [
        "README.md",
        "app.js",
        "fourfold.json",
        "icons/icon-192.svg",
        "icons/icon-512.svg",
        "index.html",
        "manifest.webmanifest",
        "model.py",
        "schemas/card.schema.json",
        "server.py",
        "service-worker.js",
        "styles.css",
        "tests/test_project.py",
    ]
    assert result["roundtrip"]["checks"]["kanban_template_conformance"] is True
    assert result["roundtrip"]["feature_assurance"] == {
        "approved_kanban_app_template_sha256": (
            service_module._APPROVED_KANBAN_APP_TEMPLATE_SHA256
        ),
        "approved_kanban_model_sha256": service_module._APPROVED_KANBAN_MODEL_SHA256,
        "approved_kanban_schema_sha256": service_module._APPROVED_KANBAN_SCHEMA_SHA256,
        "blueprint": "kanban-board-v1",
        "browser_behavior_verified": False,
        "candidate_owned": False,
        "kanban_template_verified": True,
        "mechanism": (
            "kernel-owned certified kanban template plus pinned model/schema "
            "conformance"
        ),
        "runtime_behavior_verified_by_this_check": False,
        "limitation": (
            "Exact generated source identities and fixed-column wiring are "
            "checked, but browser interactions are not executed; behavioral "
            "browser verification remains a separate release gap."
        ),
    }
    assert result["publication"] == {
        "status": "not-requested",
        "owner_approval_required": True,
        "automatic_promotion": False,
    }

    page, media_type = read_genesis_preview(
        result["run_id"],
        "index.html",
        repo_root=authority,
    )
    app, app_type = read_genesis_preview(
        result["run_id"],
        "app.js",
        repo_root=authority,
    )
    assert page.count(b'class="kanban-column"') == 3
    assert b'id="filter" type="search"' in page
    assert b"function moveCard(id, direction)" in app
    assert b"Move Back" in app and b"Move Forward" in app
    assert media_type == "text/html; charset=utf-8"
    assert "javascript" in app_type

    replay = run_genesis(
        "Build a local kanban board with search",
        target="web",
        request_key="genesis:kanban-e2e",
        repo_root=authority,
    )
    assert replay == result
    assert run_genesis(
        "Build a local task board",
        target="web",
        request_key="genesis:legacy-beside-kanban",
        repo_root=authority,
    ) == legacy
    legacy_page, _ = read_genesis_preview(
        legacy["run_id"],
        "index.html",
        repo_root=authority,
    )
    assert b'id="item-form"' in legacy_page

    store = service_module.SourceTreeStore.open_existing(
        service_module.control_root(authority) / "genesis" / "source-cas"
    )
    roundtrip_ref = service_module._report_artifact_ref(result, "roundtrip")
    roundtrip = service_module._load_genesis_contract(
        store,
        roundtrip_ref,
        service_module.RoundTripReport,
        label="RoundTripReport",
    )
    assert roundtrip.checks["tensor_kernel"] is True
    # New round trips bind both the frozen base evaluator and tensor projection.
    # Historical reports continue to verify against the unchanged base digest.
    assert roundtrip.evaluator_sha256 == (
        "4bce7a41d5a6d41c2642cff964a2b590c38d32f72e84621ff7b378e17004edb7"
    )
    assert service_module._evaluator_sha256("kanban-board-v1", tensor_kernel=False) == service_module._KANBAN_EVALUATOR_SHA256


def test_same_request_key_cannot_fork_between_legacy_and_kanban_profiles(
    authority: Path,
) -> None:
    legacy = normalize_genesis_request(
        "Build a local task board",
        target="web",
        request_key="genesis:cross-profile",
    )
    kanban = normalize_genesis_request(
        "Build a local kanban board",
        target="web",
        request_key="genesis:cross-profile",
    )
    assert legacy.run_id == kanban.run_id
    assert legacy.attempt_id == kanban.attempt_id
    assert legacy.source_revision != kanban.source_revision

    first = run_genesis(
        legacy.prompt,
        target="web",
        request_key=legacy.request_key,
        repo_root=authority,
    )
    assert first["status"] == "preview-ready"
    with pytest.raises(GenesisConflictError, match="request_key"):
        run_genesis(
            kanban.prompt,
            target="web",
            request_key=kanban.request_key,
            repo_root=authority,
        )


def test_unknown_persisted_policy_blueprint_pair_has_no_evaluator() -> None:
    request = normalize_genesis_request(
        "Build a local kanban board",
        target="web",
        request_key="genesis:unknown-persisted-profile",
    )
    plan = build_genesis_plan(
        request,
        created_at="2026-09-05T00:00:00+00:00",
    )

    with pytest.raises(service_module.GenesisError, match="combination is unsupported"):
        service_module._persisted_blueprint(
            replace(plan.policy, policy_version="99.0"),
            plan.product,
        )
    with pytest.raises(service_module.GenesisError, match="combination is unsupported"):
        service_module._persisted_blueprint(
            plan.policy,
            replace(plan.product, defaults={**plan.product.defaults, "blueprint": "other"}),
        )


@pytest.mark.parametrize(
    ("label", "relative", "original", "replacement"),
    (
        (
            "noop-move",
            "app.js",
            b"card.column = COLUMNS[next];",
            b"card.column = card.column;",
        ),
        (
            "model-column",
            "model.py",
            b'(\"backlog\", \"in-progress\", \"done\")',
            b'(\"backlog\", \"review\", \"done\")',
        ),
        (
            "schema-column",
            "schemas/card.schema.json",
            b'\"in-progress\"',
            b'\"review\"',
        ),
        (
            "column-markup",
            "index.html",
            b'data-column=\"done\"',
            b'data-column=\"archive\"',
        ),
        (
            "requested-search",
            "index.html",
            b'<label for=\"filter\">Search cards</label>',
            b'<p>Search removed</p>',
        ),
    ),
)
def test_kanban_independent_evaluator_turns_mutations_red(
    authority: Path,
    monkeypatch: pytest.MonkeyPatch,
    label: str,
    relative: str,
    original: bytes,
    replacement: bytes,
) -> None:
    real_render = service_module.render_project

    def mutated_render(*args: object, **kwargs: object) -> dict[str, bytes]:
        files = dict(real_render(*args, **kwargs))
        assert files[relative].count(original) == 1
        files[relative] = files[relative].replace(original, replacement, 1)
        return files

    monkeypatch.setattr(service_module, "render_project", mutated_render)
    result = run_genesis(
        "Build a local kanban board with search",
        target="web",
        request_key=f"genesis:kanban-mutation:{label}",
        repo_root=authority,
    )

    assert result["status"] == "failed"
    assert result["evidence"]["status"] == "failed"
    assert result["roundtrip"]["status"] == "failed"
    assert result["roundtrip"]["checks"]["kanban_template_conformance"] is False
    assert result["preview"] is None
    assert any(
        "kanban_template_conformance check failed" in blocker
        for blocker in result["blockers"]
    )


@pytest.mark.skipif(__import__("os").name != "nt", reason="native candidate runtime acceptance runs on Windows CI")
def test_tensor_failure_is_retained_and_failed_roundtrip_replays(authority, monkeypatch):
    def refuse(*args, **kwargs):
        raise ValueError("injected invalid tensor revision")
    monkeypatch.setattr(service_module, "compile_runtime_projection", refuse)
    kwargs = {"repo_root": authority, "target": "web", "request_key": "genesis:tensor-refusal"}
    result = run_genesis("Build a local task board with search", **kwargs)
    assert result["status"] == "failed", result
    assert result["roundtrip"]["checks"]["tensor_kernel"] is False
    assert result["roundtrip"]["checks"]["build"] is True
    assert any("tensor_kernel" in name for name in result["evidence"]["checks"])
    assert run_genesis("Build a local task board with search", **kwargs) == result
