from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from daedalus.chip_design.executor import EdaExecutionError
from daedalus.chip_design.execution_plan import EdaExecutionPlan
from daedalus.chip_design.completion_publication import (
    record_chip_eda_publication,
)
from daedalus.chip_design.lease_ports import validate_eda_execution_plan
from daedalus.chip_design.publication_verifier import (
    verify_chip_eda_publication_graph,
)
from daedalus.gates.repository_head_revision import (
    RepositoryHeadRevisionBindingError,
    verify_repository_head_revision,
)
from daedalus.kernel import offload_lease
from daedalus.kernel.offload_lease import (
    CHIP_EDA_ENTRYPOINT_ID,
    ISSUER_EFFECTS,
    WaveOffloadLease,
    chip_eda_lease_id,
    issuable_row,
)
from daedalus.schemas import ContractProvenance
from daedalus.storage import ArtifactStore
from daedalus.spine.effect_boundary import (
    ENTRYPOINTS,
    Effect,
    GuardAnchor,
    GuardDecision,
    Surface,
    Wiring,
    begin_effect,
)
from daedalus.spine.envelope import canonical_json, canonical_sha
from daedalus.spine.killswitch import KillSwitch


CHIP_TARGET = "daedalus.chip_design.cli:main"
CHIP_EFFECTS = (
    Effect.FILESYSTEM_WRITE,
    Effect.PROCESS_SPAWN,
    Effect.PROCESS_CONTROL,
)
CHIP_GUARDS = (
    "budget.process_guard",
    "provider.write_policy",
    "containment.attempt",
)


def _write_detached_head(root: Path, revision: str) -> None:
    git_dir = root / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "HEAD").write_bytes((revision + "\n").encode("ascii"))


def _operation_plan(source_root: Path, worktree_root: Path) -> EdaExecutionPlan:
    return EdaExecutionPlan.build(
        phase="inspect",
        argv=("vivado",),
        source_root=source_root,
        source_project=source_root / "demo.xpr",
        cwd=worktree_root,
        artifact_paths=(".daedalus-chip/inspect.json",),
        artifact_store_root=worktree_root / ".authority-artifacts",
        timeout_s=60,
        environment={},
        source_manifest_sha256="1" * 64,
        workspace_manifest_sha256="2" * 64,
        source_identity_sha256="3" * 64,
        trusted_tcl_sha256="4" * 64,
        launcher_sha256="5" * 64,
        publication_adapter_sha256="6" * 64,
    )


def _grant_real_chip_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    attempt_id: str,
) -> tuple[WaveOffloadLease, Path, EdaExecutionPlan]:
    authority_root = tmp_path / "authority"
    project_root = tmp_path / "project"
    worktree_root = tmp_path / "isolated-worktree"
    authority_root.mkdir()
    project_root.mkdir()
    worktree_root.mkdir()
    revision = "a" * 40
    _write_detached_head(authority_root, revision)
    policy = authority_root / ".agentenv" / "chip-eda-policy.json"
    policy.parent.mkdir()
    policy.write_text(
        json.dumps({"policy": {"write_allow": ["."]}}),
        encoding="utf-8",
    )
    permit = tmp_path / "operator-control" / "killswitch"
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(permit))
    KillSwitch(repo_root=authority_root).arm(note="chip effect-boundary test")
    operation_plan = _operation_plan(project_root, worktree_root)

    granted = offload_lease.acquire_chip_eda_lease(
        authority_root,
        project_root=project_root,
        worktree_root=worktree_root,
        containment_evidence="isolated Vivado project workspace",
        write_policy_path=policy.relative_to(authority_root),
        operation_plan=operation_plan,
        source_revision=revision,
        execution_plan_validator=validate_eda_execution_plan,
        repository_head_verifier=verify_repository_head_revision,
        mission_id="chip-test",
        attempt_id=attempt_id,
    )

    assert type(granted) is WaveOffloadLease, getattr(granted, "reasons", ())
    return granted, authority_root, operation_plan


def test_chip_lease_id_is_stable_and_binds_mission_and_attempt() -> None:
    assert chip_eda_lease_id("chip-test", "attempt-1") == (
        "chip-60d5a59a9aec613746df3f3561a70d1507a2ebc6"
    )
    assert chip_eda_lease_id("chip-test", "attempt-1") == chip_eda_lease_id(
        "chip-test", "attempt-1"
    )
    assert chip_eda_lease_id("other-mission", "attempt-1") != chip_eda_lease_id(
        "chip-test", "attempt-1"
    )
    assert chip_eda_lease_id("chip-test", "attempt-2") != chip_eda_lease_id(
        "chip-test", "attempt-1"
    )


def test_chip_console_has_one_central_issuable_owner() -> None:
    rows = [row for row in ENTRYPOINTS if row.target == CHIP_TARGET]

    assert len(rows) == 1
    row = rows[0]
    assert row.id == CHIP_EDA_ENTRYPOINT_ID
    assert row.surface is Surface.CLI
    assert row.wiring is Wiring.CENTRAL
    assert row.effects == CHIP_EFFECTS
    assert row.guard_contracts == CHIP_GUARDS
    assert row.anchors == (
        GuardAnchor(CHIP_TARGET, "run_admitted_eda"),
        GuardAnchor(
            "daedalus.chip_design.executor:run_admitted_eda",
            "begin_effect",
        ),
    )
    assert Effect.NETWORK_EGRESS not in row.effects
    assert Effect.SPEND not in row.effects
    assert Effect.SECRETS not in row.effects

    spec, reasons = issuable_row(CHIP_EDA_ENTRYPOINT_ID)
    assert reasons == ()
    assert spec == row
    assert Effect.PROCESS_CONTROL.value in ISSUER_EFFECTS


def test_chip_console_can_begin_only_through_its_central_contract() -> None:
    row = next(row for row in ENTRYPOINTS if row.id == CHIP_EDA_ENTRYPOINT_ID)
    decisions = tuple(
        GuardDecision(contract, True, f"test evidence for {contract}")
        for contract in row.guard_contracts
    )

    receipt = begin_effect(row.id, row.effects, decisions)

    assert receipt.entrypoint_id == CHIP_EDA_ENTRYPOINT_ID
    assert receipt.target == CHIP_TARGET
    assert receipt.requested_effects == tuple(
        sorted(effect.value for effect in CHIP_EFFECTS)
    )
    assert receipt.to_dict()["security_boundary_claimed"] is False


def test_chip_lease_wrapper_pins_capability_and_containment_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    authority_root = tmp_path / "authority"
    project_root = tmp_path / "project"
    worktree_root = tmp_path / "isolated-worktree"
    captured: dict[str, Any] = {}
    sentinel = object()
    _write_detached_head(authority_root, "a" * 40)
    operation_plan = _operation_plan(project_root, worktree_root)

    def fake_acquire(repo_root: str | Path, **kwargs: Any) -> object:
        captured["repo_root"] = repo_root
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(offload_lease, "_acquire_effect_lease_impl", fake_acquire)

    result = offload_lease.acquire_chip_eda_lease(
        authority_root,
        project_root=project_root,
        worktree_root=worktree_root,
        containment_evidence="isolated Vivado project workspace",
        write_policy_path=".agentenv/chip-eda-policy.json",
        operation_plan=operation_plan,
        source_revision="a" * 40,
        execution_plan_validator=validate_eda_execution_plan,
        repository_head_verifier=verify_repository_head_revision,
        mission_id="chip-test",
        attempt_id="attempt-1",
    )

    assert result is sentinel
    assert captured == {
        "repo_root": authority_root,
        "entrypoint_id": CHIP_EDA_ENTRYPOINT_ID,
        "positions": 1,
        "lanes": (),
        "max_spend_usd": None,
        "contained": True,
        "containment_evidence": "isolated Vivado project workspace",
        "subject_root": project_root,
        "worktree_root": worktree_root,
        "write_policy_path": ".agentenv/chip-eda-policy.json",
        "operation_sha256": operation_plan.digest,
        "lease_id": captured["lease_id"],
        "source_revision": "a" * 40,
        "mission_id": "chip-test",
        "attempt_id": "attempt-1",
        "writable_paths": (".",),
        "tools": ("vivado",),
    }
    assert captured["lease_id"] == chip_eda_lease_id("chip-test", "attempt-1")


def test_real_chip_grant_retains_full_authority_head_binding(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    granted, authority_root, operation_plan = _grant_real_chip_lease(
        tmp_path,
        monkeypatch,
        attempt_id="attempt-authority-head",
    )

    assert granted.evidence_errors == []
    assert granted.lease_id == chip_eda_lease_id(
        "chip-test", "attempt-authority-head"
    )
    record_sha256 = granted.evidence_records["authority_head"]
    record_path = (
        Path(granted.evidence_root)
        / "authority-head"
        / f"{record_sha256}.json"
    )
    body = json.loads(record_path.read_text(encoding="utf-8"))
    digest_material = dict(body)
    assert digest_material.pop("record_sha256") == record_sha256
    assert canonical_sha(digest_material) == record_sha256
    assert set(body) == {
        "schema",
        "entrypoint_id",
        "lease_sha256",
        "operation_sha256",
        "repository_head_receipt",
        "record_sha256",
    }
    assert body["schema"] == "daedalus-chip-authority-head-record/1"
    assert body["entrypoint_id"] == CHIP_EDA_ENTRYPOINT_ID
    assert body["lease_sha256"] == granted.lease.digest
    assert body["operation_sha256"] == operation_plan.digest
    assert body["operation_sha256"] == granted.request.operation_sha256
    expected_head = verify_repository_head_revision(authority_root, "a" * 40)
    assert body["repository_head_receipt"] == expected_head.to_dict()
    assert set(body["repository_head_receipt"]) == {
        "schema",
        "expected_revision",
        "resolved_revision",
        "head_mode",
        "head_ref",
        "resolution_source",
        "head_sha256",
        "head_size",
        "reference_path",
        "reference_sha256",
        "reference_size",
        "repository_head_verified",
        "commit_object_verified",
        "worktree_clean_verified",
        "process_spawned",
        "repository_mutated",
    }


def test_execution_for_indexes_successful_execution_record_by_execution_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    granted, _authority_root, operation_plan = _grant_real_chip_lease(
        tmp_path,
        monkeypatch,
        attempt_id="attempt-execution-record",
    )

    execution = granted.execution_for(
        0,
        (".",),
        ("vivado",),
        operation_sha256=operation_plan.digest,
    )

    key = f"lease_execution:{execution.execution_id}"
    record_sha256 = granted.evidence_records[key]
    record_path = (
        Path(granted.evidence_root)
        / "lease-execution"
        / f"{record_sha256}.json"
    )
    body = json.loads(record_path.read_text(encoding="utf-8"))
    assert body["record_sha256"] == record_sha256
    assert body["execution_id"] == execution.execution_id
    assert body["execution_request_sha256"] == execution.digest
    assert canonical_sha(body["execution"]) == canonical_sha(execution.to_dict())
    assert body["lease_sha256"] == granted.lease.digest
    assert body["subject_record_sha256"] == granted.evidence_records["lease_subject"]


def test_evidence_record_refuses_wrong_preexisting_content_addressed_bytes(
    tmp_path: Path,
) -> None:
    body: dict[str, Any] = {"schema": "test-record/1", "value": "exact"}
    body["record_sha256"] = canonical_sha(body)
    target = tmp_path / "records" / "test" / f"{body['record_sha256']}.json"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"{}")

    with pytest.raises(ValueError, match="bytes contradict"):
        offload_lease._publish_evidence_record(tmp_path / "records", "test", body)


def test_terminal_chip_publication_rejects_incomplete_graph_before_index(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    granted, authority_root, operation_plan = _grant_real_chip_lease(
        tmp_path,
        monkeypatch,
        attempt_id="attempt-terminal-publication",
    )
    execution = granted.execution_for(
        1,
        (".",),
        ("vivado",),
        operation_sha256=operation_plan.digest,
    )
    started = granted.authorization.begin_effect(execution)
    assert started.execute is True
    store = ArtifactStore(Path(granted.evidence_root) / "artifacts")
    provenance = ContractProvenance(
        origin="test.chip-terminal-publication",
        source_revision="a" * 40,
        created_at="2026-08-30T10:00:00+00:00",
        input_digests=(operation_plan.digest,),
    ).to_dict()
    incomplete_raw_payload = canonical_json(
        {
            "schema": "daedalus.eda-execution-receipt/3",
            "execution_id": execution.execution_id,
            "execution_request_sha256": execution.digest,
            "operation_sha256": execution.operation_sha256,
            "execution_plan": operation_plan.to_dict(),
            "effect_start_receipt": started.receipt.to_dict(),
        }
    ).encode("ascii")
    raw = store.put_bytes(
        incomplete_raw_payload,
        media_type="application/json",
        metadata={
            "kind": "eda_execution_receipt",
            "execution_id": execution.execution_id,
        },
        provenance=provenance,
    )
    terminal = granted.authorization.finish_effect(
        started.receipt,
        outcome="FAILED",
        output_digests=(raw.artifact_sha256,),
    )
    placeholder = canonical_json(
        {"schema": "daedalus.test-incomplete-publication/1"}
    ).encode("ascii")
    chip = store.put_bytes(
        placeholder,
        media_type="application/json",
        metadata={"kind": "chip_run_receipt", "phase": "inspect"},
        provenance=provenance,
    )
    evidence = store.put_bytes(
        placeholder,
        media_type="application/json",
        metadata={"kind": "chip_evidence_packet", "phase": "inspect"},
        provenance=provenance,
    )
    subject_digest = granted.evidence_records["lease_subject"]
    subject_path = (
        Path(granted.evidence_root)
        / "lease-subject"
        / f"{subject_digest}.json"
    )
    subject = json.loads(subject_path.read_text(encoding="utf-8"))
    terminal_record = offload_lease.emit_effect_lease_terminal_record(
        subject,
        execution,
        evidence_root=granted.evidence_root,
        control_root_path=granted.control_root_path,
        keyring=offload_lease.read_issuer_keyring(authority_root),
        ledger_path=granted.ledger_path,
    )

    with pytest.raises(
        EdaExecutionError,
        match="retained EDA execution receipt has unexpected fields",
    ):
        offload_lease._record_chip_eda_publication(
            authority_root=authority_root,
            evidence_root=granted.evidence_root,
            source_revision="a" * 40,
            authorization=granted.authorization,
            execution=execution,
            terminal_receipt=terminal,
            artifact_store=store,
            phase="inspect",
            publication_adapter_sha256=operation_plan.publication_adapter_sha256,
            lease_sha256=granted.lease.digest,
            execution_id=execution.execution_id,
            execution_request_sha256=execution.digest,
            terminal_receipt_sha256=terminal.receipt_sha256,
            raw_execution_receipt_sha256=raw.artifact_sha256,
            raw_execution_receipt_locator=raw.locator_uri,
            chip_receipt_sha256=chip.artifact_sha256,
            chip_receipt_locator=chip.locator_uri,
            evidence_packet_sha256=evidence.artifact_sha256,
            evidence_packet_locator=evidence.locator_uri,
            authority_head_record_sha256=granted.evidence_records["authority_head"],
            lease_subject_record_sha256=subject_digest,
            lease_execution_record_sha256=granted.evidence_records[
                f"lease_execution:{execution.execution_id}"
            ],
            lease_terminal_record_sha256=terminal_record["record_sha256"],
            finished_at=terminal.finished_at,
            publication_recorder=record_chip_eda_publication,
        )

    assert (
        offload_lease.load_chip_eda_publication(
            granted.evidence_root,
            source_revision="a" * 40,
            execution_id=execution.execution_id,
        )
        is None
    )


def test_authority_head_publication_failure_stays_visible_on_granted_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publish = offload_lease._publish_evidence_record

    def fail_authority_head(
        root: str | Path,
        kind: str,
        body: Mapping[str, Any],
    ) -> Path:
        if kind == "authority-head":
            raise OSError("authority-head store unavailable")
        return publish(root, kind, body)

    monkeypatch.setattr(
        offload_lease,
        "_publish_evidence_record",
        fail_authority_head,
    )
    granted, _authority_root, _operation_plan = _grant_real_chip_lease(
        tmp_path,
        monkeypatch,
        attempt_id="attempt-authority-head-failure",
    )

    assert "lease_subject" in granted.evidence_records
    assert "disjointness" in granted.evidence_records
    assert "authority_head" not in granted.evidence_records
    assert any(
        error
        == "authority_head: OSError: authority-head store unavailable"
        for error in granted.evidence_errors
    )
    assert not (Path(granted.evidence_root) / "authority-head").exists()


@pytest.mark.parametrize(
    ("plan_source", "plan_worktree", "message"),
    (
        ("other-source", "worktree", "source_root"),
        ("project", "other-worktree", "cwd"),
    ),
)
def test_chip_lease_wrapper_binds_plan_roots_to_containment_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    plan_source: str,
    plan_worktree: str,
    message: str,
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> object:
        raise AssertionError("root mismatch reached the effect issuer")

    monkeypatch.setattr(offload_lease, "_acquire_effect_lease_impl", forbidden)
    with pytest.raises(ValueError, match=message):
        offload_lease.acquire_chip_eda_lease(
            tmp_path / "authority",
            project_root=tmp_path / "project",
            worktree_root=tmp_path / "worktree",
            containment_evidence="isolated Vivado project workspace",
            write_policy_path=".agentenv/chip-eda-policy.json",
            operation_plan=_operation_plan(
                tmp_path / plan_source,
                tmp_path / plan_worktree,
            ),
            source_revision="a" * 40,
            execution_plan_validator=validate_eda_execution_plan,
            repository_head_verifier=verify_repository_head_revision,
            mission_id="chip-test",
            attempt_id="attempt-root-mismatch",
        )


def test_chip_lease_wrapper_refuses_authority_head_mismatch_before_issuer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_root = tmp_path / "authority"
    _write_detached_head(authority_root, "b" * 40)

    def forbidden(*_args: Any, **_kwargs: Any) -> object:
        raise AssertionError("HEAD mismatch reached the effect issuer")

    monkeypatch.setattr(offload_lease, "_acquire_effect_lease_impl", forbidden)

    with pytest.raises(RepositoryHeadRevisionBindingError, match="HEAD differs"):
        offload_lease.acquire_chip_eda_lease(
            authority_root,
            project_root=tmp_path / "project",
            worktree_root=tmp_path / "isolated-worktree",
            containment_evidence="isolated Vivado project workspace",
            write_policy_path=".agentenv/chip-eda-policy.json",
            operation_plan=_operation_plan(
                tmp_path / "project", tmp_path / "isolated-worktree"
            ),
            source_revision="a" * 40,
            execution_plan_validator=validate_eda_execution_plan,
            repository_head_verifier=verify_repository_head_revision,
            mission_id="chip-test",
            attempt_id="attempt-head-mismatch",
        )


def test_chip_lease_wrapper_requires_explicit_head_verifier_before_issuer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> object:
        raise AssertionError("missing HEAD verifier reached the effect issuer")

    monkeypatch.setattr(offload_lease, "_acquire_effect_lease_impl", forbidden)

    with pytest.raises(TypeError, match="repository_head_verifier"):
        offload_lease.acquire_chip_eda_lease(
            tmp_path / "authority",
            project_root=tmp_path / "project",
            worktree_root=tmp_path / "isolated-worktree",
            containment_evidence="isolated Vivado project workspace",
            write_policy_path=".agentenv/chip-eda-policy.json",
            operation_plan=_operation_plan(
                tmp_path / "project", tmp_path / "isolated-worktree"
            ),
            source_revision="a" * 40,
            mission_id="chip-test",
            attempt_id="attempt-missing-head-verifier",
        )


def test_chip_lease_wrapper_refuses_unbound_head_receipt_before_issuer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected_revision = "a" * 40
    other_revision = "b" * 40
    authority_root = tmp_path / "authority"
    _write_detached_head(authority_root, expected_revision)
    valid_payload = verify_repository_head_revision(
        authority_root, expected_revision
    ).to_dict()

    class UnboundReceipt:
        def __init__(self) -> None:
            self.expected_revision = expected_revision
            self.resolved_revision = other_revision

        def to_dict(self) -> dict[str, Any]:
            return {**valid_payload, "resolved_revision": self.resolved_revision}

    def wrong_port(_root: Path, _revision: str) -> UnboundReceipt:
        return UnboundReceipt()

    def forbidden(*_args: Any, **_kwargs: Any) -> object:
        raise AssertionError("unbound HEAD receipt reached the effect issuer")

    monkeypatch.setattr(offload_lease, "_acquire_effect_lease_impl", forbidden)

    with pytest.raises(ValueError, match="not bound.*source_revision"):
        offload_lease.acquire_chip_eda_lease(
            authority_root,
            project_root=tmp_path / "project",
            worktree_root=tmp_path / "isolated-worktree",
            containment_evidence="isolated Vivado project workspace",
            write_policy_path=".agentenv/chip-eda-policy.json",
            operation_plan=_operation_plan(
                tmp_path / "project", tmp_path / "isolated-worktree"
            ),
            source_revision=expected_revision,
            execution_plan_validator=validate_eda_execution_plan,
            repository_head_verifier=wrong_port,
            mission_id="chip-test",
            attempt_id="attempt-unbound-head-receipt",
        )


def test_chip_lease_wrapper_refuses_non_40_hex_revision_before_head_or_issuer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> object:
        raise AssertionError("invalid revision reached HEAD verification or issuer")

    monkeypatch.setattr(offload_lease, "_acquire_effect_lease_impl", forbidden)

    with pytest.raises(TypeError, match="40-hex source_revision"):
        offload_lease.acquire_chip_eda_lease(
            tmp_path,
            project_root=tmp_path / "project",
            worktree_root=tmp_path / "isolated-worktree",
            containment_evidence="isolated Vivado project workspace",
            write_policy_path=".agentenv/chip-eda-policy.json",
            operation_plan=_operation_plan(
                tmp_path / "project", tmp_path / "isolated-worktree"
            ),
            source_revision="a" * 64,
            execution_plan_validator=validate_eda_execution_plan,
            repository_head_verifier=forbidden,
            mission_id="chip-test",
            attempt_id="attempt-wide-revision",
        )


def test_public_generic_issuer_refuses_chip_row_before_any_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_args: Any, **_kwargs: Any) -> object:
        raise AssertionError("chip request reached the generic issuer implementation")

    monkeypatch.setattr(offload_lease, "_acquire_effect_lease_impl", forbidden)

    with pytest.raises(TypeError, match="acquire_chip_eda_lease"):
        offload_lease.acquire_effect_lease(
            tmp_path,
            entrypoint_id=CHIP_EDA_ENTRYPOINT_ID,
            source_revision="a" * 40,
            mission_id="chip-test",
            attempt_id="attempt-generic-bypass",
            positions=1,
        )


@pytest.mark.parametrize(
    ("name", "value"),
    (
        ("entrypoint_id", "python.offload"),
        ("positions", 2),
        ("lanes", ("ollama",)),
        ("max_spend_usd", 1.0),
        ("switch", object()),
        ("evidence_root", "elsewhere"),
        ("lease_id", "caller-chosen"),
        ("tools", ("git",)),
        ("writable_paths", ("build",)),
        ("operation_sha256", "e" * 64),
    ),
)
def test_chip_lease_wrapper_refuses_capability_overrides(
    tmp_path: Path, name: str, value: object
) -> None:
    override = {name: value}

    with pytest.raises(TypeError, match="callers may not override"):
        offload_lease.acquire_chip_eda_lease(
            tmp_path,
            project_root=tmp_path / "project",
            worktree_root=tmp_path / "worktree",
            containment_evidence="isolated project workspace",
            write_policy_path=".agentenv/chip-eda-policy.json",
            operation_plan=_operation_plan(
                tmp_path / "project", tmp_path / "worktree"
            ),
            source_revision="b" * 40,
            execution_plan_validator=validate_eda_execution_plan,
            repository_head_verifier=verify_repository_head_revision,
            mission_id="chip-test",
            attempt_id="attempt-override",
            **override,
        )


@pytest.mark.parametrize(
    ("project_root", "worktree_root", "evidence", "message"),
    (
        ("", "worktree", "isolated", "project_root"),
        ("project", "", "isolated", "worktree_root"),
        ("project", "worktree", "  ", "containment_evidence"),
    ),
)
def test_chip_lease_wrapper_requires_explicit_roots_and_evidence(
    tmp_path: Path,
    project_root: str,
    worktree_root: str,
    evidence: str,
    message: str,
) -> None:
    with pytest.raises(TypeError, match=message):
        offload_lease.acquire_chip_eda_lease(
            tmp_path,
            project_root=project_root,
            worktree_root=worktree_root,
            containment_evidence=evidence,
            write_policy_path=".agentenv/chip-eda-policy.json",
            operation_plan=_operation_plan(
                tmp_path / "project", tmp_path / "worktree"
            ),
            source_revision="c" * 40,
            execution_plan_validator=validate_eda_execution_plan,
            repository_head_verifier=verify_repository_head_revision,
            mission_id="chip-test",
            attempt_id="attempt-missing",
        )


def test_chip_lease_wrapper_refuses_in_memory_policy_override(tmp_path: Path) -> None:
    with pytest.raises(TypeError, match="callers may not override"):
        offload_lease.acquire_chip_eda_lease(
            tmp_path,
            project_root=tmp_path / "project",
            worktree_root=tmp_path / "worktree",
            containment_evidence="isolated project workspace",
            write_policy_path=".agentenv/chip-eda-policy.json",
            operation_plan=_operation_plan(
                tmp_path / "project", tmp_path / "worktree"
            ),
            write_policy=object(),
            source_revision="d" * 40,
            execution_plan_validator=validate_eda_execution_plan,
            repository_head_verifier=verify_repository_head_revision,
            mission_id="chip-test",
            attempt_id="attempt-policy-override",
        )
