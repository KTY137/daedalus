from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import daedalus.runtimes.provider_target_receipt_retention_preflight as preflight_module
from daedalus.gates.provider_target_receipt_retention_inventory import (
    ProviderTargetReceiptRetentionInventory,
    ProviderTargetReceiptRetentionSurface,
    scan_provider_target_receipt_retention,
)
from daedalus.gates.repository_head_revision import verify_repository_head_revision
from daedalus.kernel.artifacts import ArtifactRef
from daedalus.kernel.contracts import EffectLease
from daedalus.kernel.effects import EffectExecutionRequest
from daedalus.runtimes.provider_target_receipt_retention_contract import (
    RETENTION_ENTRYPOINT,
    build_provider_target_receipt_retention_operation_subject,
    issue_provider_target_receipt_retention_operation_authority,
)
from daedalus.runtimes.provider_target_receipt_retention_preflight import (
    ProviderTargetReceiptRetentionPreflightBindingError,
    ProviderTargetReceiptRetentionPreflightReceipt,
    ProviderTargetReceiptRetentionPreflightShapeError,
    verify_provider_target_receipt_retention_preflight,
)
from daedalus.runtimes.provider_target_verification_contracts import (
    ProviderExecutableTargetVerificationReceipt,
    VerifiedPythonTarget,
)
from daedalus.schemas import ContractProvenance, EffectScope

REVISION = "415b07394ac4c5d2fc7481e27c9c47b40119d859"
NOW = datetime(2026, 8, 5, 5, 30, tzinfo=timezone.utc)
SECRET = b"retention-preflight-authority-secret-at-least-32-bytes"
KEYRING = {"retention-preflight-key": SECRET}
EVENT_PATH = "attempt/state/spine.sqlite3"
CAS_PATH = "attempt/cas/receipts"


def _write_head(root: Path, revision: str) -> None:
    """Write ``.git/HEAD`` byte-exactly.

    Git writes ``.git/HEAD`` with a single LF on every platform, and the
    revision fence refuses a CR. ``Path.write_text`` opens in text mode and
    translates ``\\n`` to ``os.linesep``, so on Windows it would emit CRLF and
    make the fixture -- not the guard -- the thing under test.
    """
    (root / ".git" / "HEAD").write_bytes((revision + "\n").encode("ascii"))


def _repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    (root / ".git").mkdir(parents=True)
    _write_head(root, REVISION)
    source = (
        Path(__file__).resolve().parents[2]
        / "daedalus"
        / "runtimes"
        / "provider_target_receipt_ledger.py"
    )
    target = root / "daedalus" / "runtimes" / source.name
    target.parent.mkdir(parents=True)
    target.write_bytes(source.read_bytes())
    return root


def _verified_target(name: str) -> VerifiedPythonTarget:
    return VerifiedPythonTarget(
        target=f"daedalus.runtimes.provider_runtime_broker:{name}",
        repository_path="daedalus/runtimes/provider_runtime_broker.py",
        source_sha256=("a" if name == "run_runtime_provider" else "b") * 64,
        source_size=2048,
        qualified_name=name,
        node_kind="function",
        line=10 if name == "run_runtime_provider" else 30,
        end_line=20 if name == "run_runtime_provider" else 40,
    )


def _provider_receipt() -> ProviderExecutableTargetVerificationReceipt:
    source_tree_sha256 = "1" * 64
    return ProviderExecutableTargetVerificationReceipt(
        verifier_id="verifier.provider-target",
        verifier_key_id="provider-target-key",
        source_revision=REVISION,
        source_tree_id="provider-target-source-tree",
        source_tree_sha256=source_tree_sha256,
        source_tree_locator=ArtifactRef.from_sha256(source_tree_sha256).locator,
        target_authority_sha256="2" * 64,
        target_projection_sha256="3" * 64,
        target_manifest_sha256="4" * 64,
        target_descriptor_sha256="5" * 64,
        provider_id="provider.fixture",
        adapter_id="adapter.fixture",
        implementation_id="implementation.fixture",
        entrypoint_id="provider.runtime-fixture",
        runtime_id="runtime.fixture",
        execution_id="provider-execution",
        idempotency_key="provider-idempotency",
        lease_sha256="6" * 64,
        invoke=_verified_target("run_runtime_provider"),
        output_digests=_verified_target("materialize_output_digests"),
        signature_sha256="7" * 64,
    )


def _execution() -> EffectExecutionRequest:
    return EffectExecutionRequest(
        execution_id="retention-execution",
        idempotency_key="retention-idempotency",
        requested_effects=("filesystem_write",),
        writable_paths=(EVENT_PATH, CAS_PATH),
        kill_switch_ref="retention-kill-switch",
        kill_switch_generation=23,
    )


def _lease() -> EffectLease:
    request_sha256 = "c" * 64
    policy_sha256 = "d" * 64
    registry_sha256 = "e" * 64
    return EffectLease(
        lease_id="provider-target-receipt-retention-lease",
        request_id="provider-target-receipt-retention-request",
        request_sha256=request_sha256,
        policy_decision_id="provider-target-receipt-retention-policy",
        policy_decision_sha256=policy_sha256,
        registry_sha256=registry_sha256,
        entrypoint_id=RETENTION_ENTRYPOINT,
        requested_effects=("filesystem_write",),
        effect_scope=EffectScope(
            read_only=False,
            writable_paths=(EVENT_PATH, CAS_PATH),
            kill_switch_ref="retention-kill-switch",
        ),
        idempotency_namespace="provider-target-receipt-retention",
        kill_switch_generation=23,
        runtime_id="",
        runtime_manifest_sha256=None,
        runtime_conformance_sha256=None,
        issuer_key_id="effect-lease-key",
        issued_at=(NOW - timedelta(minutes=1)).isoformat(timespec="microseconds"),
        expires_at=(NOW + timedelta(minutes=30)).isoformat(timespec="microseconds"),
        signature_sha256="f" * 64,
        provenance=ContractProvenance(
            origin="test.provider-target-receipt-retention-preflight",
            source_revision=REVISION,
            created_at=(NOW - timedelta(minutes=1)).isoformat(timespec="microseconds"),
            input_digests=(request_sha256, policy_sha256, registry_sha256),
            trace_id="provider-target-receipt-retention-preflight-trace",
        ),
    )


def _subjects(root: Path):
    receipt = _provider_receipt()
    execution = _execution()
    lease = _lease()
    inventory = scan_provider_target_receipt_retention(
        root,
        source_revision=REVISION,
    )
    subject = build_provider_target_receipt_retention_operation_subject(
        receipt=receipt,
        retention_inventory_sha256=inventory.digest,
        retention_inventory_source_revision=inventory.source_revision,
        retention_inventory_source_sha256=inventory.source_sha256,
        execution=execution,
        effect_lease=lease,
        event_store_scope_path=EVENT_PATH,
        receipt_cas_scope_path=CAS_PATH,
    )
    authority = issue_provider_target_receipt_retention_operation_authority(
        authority_id="authority.provider-target-receipt-retention",
        authority_key_id="retention-preflight-key",
        authority_secret=SECRET,
        nonce="provider-target-receipt-retention-preflight-nonce",
        subject=subject,
        issued_at=NOW - timedelta(seconds=5),
        expires_at=NOW + timedelta(minutes=5),
    )
    head_receipt = verify_repository_head_revision(root, REVISION)
    return receipt, execution, lease, inventory, subject, authority, head_receipt


def _call(
    root: Path,
    receipt,
    execution,
    lease,
    inventory,
    authority,
    head_receipt,
    *,
    event_path: str = EVENT_PATH,
    cas_path: str = CAS_PATH,
):
    return verify_provider_target_receipt_retention_preflight(
        root,
        head_receipt,
        receipt,
        inventory,
        authority,
        execution,
        lease,
        expected_authority_id="authority.provider-target-receipt-retention",
        authority_keyring=KEYRING,
        event_store_scope_path=event_path,
        receipt_cas_scope_path=cas_path,
        at=NOW,
    )


def _verify(root: Path):
    receipt, execution, lease, inventory, subject, authority, head_receipt = _subjects(root)
    result = _call(
        root,
        receipt,
        execution,
        lease,
        inventory,
        authority,
        head_receipt,
    )
    return result, (receipt, execution, lease, inventory, subject, authority, head_receipt)


def test_preflight_round_trip_binds_all_inert_subjects(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    result, subjects = _verify(root)
    receipt, execution, lease, inventory, subject, authority, head_receipt = subjects

    assert result.source_revision == REVISION
    assert result.repository_head_receipt_sha256 == head_receipt.digest
    assert result.provider_target_receipt_sha256 == receipt.digest
    assert result.retention_inventory_sha256 == inventory.digest
    assert result.retention_inventory_source_sha256 == inventory.source_sha256
    assert result.retention_inventory_surface_count == 7
    assert result.retention_authority_sha256 == authority.digest
    assert result.retention_subject_sha256 == subject.digest
    assert result.retention_execution_request_sha256 == execution.digest
    assert result.retention_effect_lease_sha256 == lease.digest
    assert ProviderTargetReceiptRetentionPreflightReceipt.from_dict(
        result.to_dict()
    ) == result
    assert result.to_dict()["repository_head_stable_across_inventory"] is True
    assert result.to_dict()["persisted_effect_lease_verified"] is False
    assert result.to_dict()["retention_effect_started"] is False
    assert result.to_dict()["retention_write_performed"] is False
    assert result.to_dict()["canonical_entrypoint_registered"] is False
    assert result.to_dict()["closed"] is False


def test_invalid_authority_refuses_before_repository_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path)
    receipt, execution, lease, inventory, _, authority, head_receipt = _subjects(root)
    invalid = dataclasses.replace(authority, signature_sha256="0" * 64)
    reads: list[str] = []

    def unexpected_head(*args, **kwargs):
        reads.append("head")
        raise AssertionError("HEAD read occurred before authority refusal")

    def unexpected_inventory(*args, **kwargs):
        reads.append("inventory")
        raise AssertionError("inventory read occurred before authority refusal")

    monkeypatch.setattr(
        preflight_module,
        "verify_repository_head_revision_receipt",
        unexpected_head,
    )
    monkeypatch.setattr(
        preflight_module,
        "scan_provider_target_receipt_retention",
        unexpected_inventory,
    )

    with pytest.raises(
        ProviderTargetReceiptRetentionPreflightBindingError,
        match="authority did not authenticate",
    ):
        _call(
            root,
            receipt,
            execution,
            lease,
            inventory,
            invalid,
            head_receipt,
        )
    assert reads == []


def test_stale_repository_head_refuses_after_authority_authentication(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    receipt, execution, lease, inventory, _, authority, head_receipt = _subjects(root)
    _write_head(root, "0" * 40)

    with pytest.raises(
        ProviderTargetReceiptRetentionPreflightBindingError,
        match="did not reverify before inventory",
    ):
        _call(
            root,
            receipt,
            execution,
            lease,
            inventory,
            authority,
            head_receipt,
        )


def test_head_change_during_inventory_rebuild_refuses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _repository(tmp_path)
    receipt, execution, lease, inventory, _, authority, head_receipt = _subjects(root)
    real_scan = preflight_module.scan_provider_target_receipt_retention

    def scan_then_move_head(*args, **kwargs):
        rebuilt = real_scan(*args, **kwargs)
        _write_head(root, "0" * 40)
        return rebuilt

    monkeypatch.setattr(
        preflight_module,
        "scan_provider_target_receipt_retention",
        scan_then_move_head,
    )
    with pytest.raises(
        ProviderTargetReceiptRetentionPreflightBindingError,
        match="did not reverify after inventory",
    ):
        _call(
            root,
            receipt,
            execution,
            lease,
            inventory,
            authority,
            head_receipt,
        )


def test_current_source_byte_drift_refuses(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    receipt, execution, lease, inventory, _, authority, head_receipt = _subjects(root)
    source = root / "daedalus" / "runtimes" / "provider_target_receipt_ledger.py"
    source.write_bytes(source.read_bytes() + b"\n# adversarial byte drift\n")

    with pytest.raises(
        ProviderTargetReceiptRetentionPreflightBindingError,
        match="inventory differs from current repository bytes",
    ):
        _call(
            root,
            receipt,
            execution,
            lease,
            inventory,
            authority,
            head_receipt,
        )


def test_inventory_digest_substitution_refuses_signed_subject(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    receipt, execution, lease, inventory, _, authority, head_receipt = _subjects(root)
    substituted = dataclasses.replace(inventory, source_sha256="0" * 64)

    with pytest.raises(
        ProviderTargetReceiptRetentionPreflightBindingError,
        match="authority did not authenticate",
    ):
        _call(
            root,
            receipt,
            execution,
            lease,
            substituted,
            authority,
            head_receipt,
        )


def test_hostile_inventory_surface_subclasses_refuse_before_digest(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    receipt, execution, lease, inventory, _, authority, head_receipt = _subjects(root)
    calls: list[str] = []

    class HostileSurface(ProviderTargetReceiptRetentionSurface):
        def to_dict(self):
            calls.append(self.function)
            return super().to_dict()

    hostile_surfaces = tuple(
        HostileSurface(
            function=row.function,
            line=row.line,
            column=row.column,
            kind=row.kind,
            callee=row.callee,
            operation=row.operation,
            externally_reachable_via=row.externally_reachable_via,
        )
        for row in inventory.surfaces
    )
    hostile_inventory = ProviderTargetReceiptRetentionInventory(
        source_revision=inventory.source_revision,
        source_sha256=inventory.source_sha256,
        source_size=inventory.source_size,
        surfaces=hostile_surfaces,
    )

    with pytest.raises(
        ProviderTargetReceiptRetentionPreflightShapeError,
        match="exact reviewed retention surfaces",
    ):
        _call(
            root,
            receipt,
            execution,
            lease,
            hostile_inventory,
            authority,
            head_receipt,
        )
    assert calls == []


def test_noncanonical_request_path_refuses_before_authority_comparison(
    tmp_path: Path,
) -> None:
    root = _repository(tmp_path)
    receipt, execution, lease, inventory, _, authority, head_receipt = _subjects(root)

    with pytest.raises(
        ProviderTargetReceiptRetentionPreflightShapeError,
        match="canonical repository-relative POSIX",
    ):
        _call(
            root,
            receipt,
            execution,
            lease,
            inventory,
            authority,
            head_receipt,
            cas_path="attempt//cas/receipts",
        )


def test_wire_claim_escalation_and_non_exact_fields_refuse(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    result, _ = _verify(root)
    payload = result.to_dict()
    payload["retention_effect_started"] = True
    with pytest.raises(
        ProviderTargetReceiptRetentionPreflightShapeError,
        match="unsupported claim",
    ):
        ProviderTargetReceiptRetentionPreflightReceipt.from_dict(payload)

    payload = result.to_dict()
    payload["unexpected"] = False
    with pytest.raises(
        ProviderTargetReceiptRetentionPreflightShapeError,
        match="fields are not exact",
    ):
        ProviderTargetReceiptRetentionPreflightReceipt.from_dict(payload)


def test_guard_evidence_detachment_refuses_receipt(tmp_path: Path) -> None:
    root = _repository(tmp_path)
    result, _ = _verify(root)
    payload = result.to_dict()
    payload["guard_evidence"] = "authority_sha256=" + "0" * 64
    with pytest.raises(
        ProviderTargetReceiptRetentionPreflightShapeError,
        match="guard_evidence",
    ):
        ProviderTargetReceiptRetentionPreflightReceipt.from_dict(payload)


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("source_revision", "a" * 64, "40-hex"),
        ("retention_inventory_source_size", 2 * 1024 * 1024 + 1, "scanner bound"),
        ("retention_inventory_surface_count", 6, "exact reviewed set"),
        ("receipt_cas_scope_path", "attempt/state", "must be disjoint"),
        (
            "receipt_cas_scope_path",
            "attempt//cas/receipts",
            "canonical repository-relative POSIX",
        ),
    ],
)
def test_malformed_revision_inventory_and_scope_refuse(
    tmp_path: Path,
    field: str,
    value: object,
    match: str,
) -> None:
    root = _repository(tmp_path)
    result, _ = _verify(root)
    payload = result.to_dict()
    payload[field] = value
    with pytest.raises(
        ProviderTargetReceiptRetentionPreflightShapeError,
        match=match,
    ):
        ProviderTargetReceiptRetentionPreflightReceipt.from_dict(payload)
