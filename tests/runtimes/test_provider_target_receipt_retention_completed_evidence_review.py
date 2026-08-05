from __future__ import annotations

import ast
import inspect

import daedalus.runtimes.provider_target_receipt_retention_completed_evidence as completed


_FORBIDDEN_CALL_NAMES = {
    "begin_effect",
    "finish_effect",
    "grant",
    "mark_cancelled",
    "mark_completed",
    "mark_failed",
    "mkdir",
    "open",
    "Popen",
    "put_bytes",
    "record_intent",
    "rename",
    "replace",
    "retain",
    "run",
    "system",
    "unlink",
    "write",
    "write_bytes",
    "write_text",
}


def _tree() -> ast.Module:
    return ast.parse(inspect.getsource(completed))


def test_completed_evidence_module_has_no_writer_or_execution_call_surface() -> None:
    called: set[str] = set()
    imported_modules: set[str] = set()

    for node in ast.walk(_tree()):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_modules.add(node.module)
        elif isinstance(node, ast.Call):
            target = node.func
            if isinstance(target, ast.Name):
                called.add(target.id)
            elif isinstance(target, ast.Attribute):
                called.add(target.attr)

    assert called.isdisjoint(_FORBIDDEN_CALL_NAMES)
    assert "sqlite3" not in imported_modules
    assert "subprocess" not in imported_modules
    assert "socket" not in imported_modules
    assert "daedalus.kernel.authorization" not in imported_modules


def test_public_verifier_exactly_types_every_structured_subject() -> None:
    source = inspect.getsource(
        completed.verify_provider_target_receipt_retention_completed_evidence
    )

    for subject, expected in (
        ("admission", "ProviderTargetReceiptRetentionAdmissionReceipt"),
        ("recovery", "ProviderTargetReceiptRetentionRecoveryDecision"),
        ("retention_ledger", "ProviderTargetReceiptLedger"),
        ("receipt", "ProviderExecutableTargetVerificationReceipt"),
        ("target_authority", "ProviderExecutableTargetAuthority"),
        ("invocation_authority", "ProviderInvocationObservationAuthority"),
        ("identity_registry", "ProviderInvocationRegistryManifest"),
        ("execution", "EffectExecutionRequest"),
        ("target_manifest", "ProviderExecutableTargetManifest"),
        ("source_tree_ref", "ArtifactRef"),
    ):
        assert f"({subject}, {expected}" in source or (
            f"            {subject},\n            {expected}," in source
        )
    assert "type(value) is not expected" in source
    assert "isinstance(max_source_bytes, bool)" in source


def test_admission_topology_is_exactly_bound_to_live_ledger_identities() -> None:
    source = inspect.getsource(completed._bind_admission_topology)

    for field in (
        "primary_checkout_path",
        "retention_root_path",
        "event_store_path",
        "receipt_cas_path",
    ):
        assert f'"{field}",' in source
    assert "Path(getattr(admission, field)).is_absolute()" in source
    assert "expected[key] != observed[key]" in source
    assert "root_path == primary_path" in source
    assert "root_path in primary_path.parents" in source
    assert "primary_path in root_path.parents" in source
    assert "root_path not in event_path.parents" in source
    assert "root_path not in cas_path.parents" in source


def test_authentication_and_retained_reads_are_surrounded_by_identity_fences() -> None:
    source = inspect.getsource(
        completed.verify_provider_target_receipt_retention_completed_evidence
    )

    topology_before = source.index("topology_before = _bind_admission_topology")
    artifact_before = source.index("artifact_identity_before = _artifact_file_identity")
    authenticate = source.index("verify_provider_target_verification_receipt(")
    topology_mid = source.index("topology_mid = _bind_admission_topology")
    first_read = source.index("intent = _read_intent(")
    topology_after = source.index("topology_after = _bind_admission_topology")
    second_read = source.index("final_intent = _read_intent(")
    final_subjects = source.index("final_subjects = _canonical_subjects")

    assert (
        topology_before
        < artifact_before
        < authenticate
        < topology_mid
        < first_read
        < topology_after
        < second_read
        < final_subjects
    )
    assert source.count("_bind_admission_topology(") == 3
    assert "topology_mid != topology_before" in source
    assert "artifact_identity_mid != artifact_identity_before" in source
    assert "topology_after != topology_before" in source
    assert "artifact_identity_after != artifact_identity_before" in source
    assert "intent != final_intent" in source


def test_file_identity_fence_rejects_symlinks_non_regular_and_hard_links() -> None:
    source = inspect.getsource(completed._path_identity)

    assert "_contains_symlink(absolute)" in source
    assert "stat.S_ISDIR" in source
    assert "stat.S_ISREG" in source
    assert "info.st_nlink != 1" in source
    assert '"device": int(info.st_dev)' in source
    assert '"inode": int(info.st_ino)' in source


def test_evidence_receipt_cannot_claim_effect_or_gate_authority() -> None:
    source = inspect.getsource(
        completed.ProviderTargetReceiptRetentionCompletedEvidenceReceipt.to_dict
    )

    for claim in (
        '"persisted_effect_terminal_verified"',
        '"automatic_reexecution_allowed"',
        '"effect_start_authorized"',
        '"retention_write_authorized"',
        '"effect_terminalization_authorized"',
        '"canonical_entrypoint_registered"',
        '"gate_transition_authorized"',
        '"closed"',
    ):
        assert claim in inspect.getsource(completed)
    assert '"admission_topology_bound": True' in source
    assert "**{field: False for field in _FALSE_CLAIMS}" in source
    assert "Callable" not in inspect.getsource(completed)
    assert "OwnerApproval" not in inspect.getsource(completed)
    assert "Promotion" not in inspect.getsource(completed)
