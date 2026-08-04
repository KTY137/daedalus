from __future__ import annotations

import ast
import inspect

import daedalus.gates.baseline as baseline_module
import daedalus.gates.baseline_verifier as verifier_module


def test_baseline_creation_requires_current_writer_inventory_evidence() -> None:
    source = inspect.getsource(baseline_module.create_gate0_baseline)
    assert "report.event_store_writer_inventory_sha256" in source
    assert "if writer_digest is None" in source
    assert "Gate baseline requires a bound Event-Store writer inventory" in source
    assert 'payload["report_sha256"]' in source
    assert "_sha256_json(payload)" in source
    assert "report.blockers" in source


def test_monotonicity_requires_an_externally_pinned_baseline_digest() -> None:
    source = inspect.getsource(baseline_module.assess_gate0_monotonicity)
    assert "expected_baseline_sha256" in source
    assert "_constant_time_equal(expected_digest, baseline.digest)" in source
    assert "expected baseline digest mismatch" in source
    assert "current_blockers - baseline_blockers" in source
    assert 'status="passed" if not new else "failed"' in source


def test_receipt_verifier_recomputes_instead_of_trusting_serialized_partitions() -> None:
    source = inspect.getsource(
        verifier_module.verify_gate0_monotonicity_receipt
    )
    assert "assess_gate0_monotonicity(" in source
    assert "if receipt != recomputed" in source
    assert "does not match recomputed evidence" in source
    assert 'receipt.status != "passed"' in source
    assert "receipt.new_blockers" in source


def test_baseline_and_receipt_wires_are_exact_and_canonical() -> None:
    baseline_source = inspect.getsource(baseline_module.GateBaseline.from_dict)
    receipt_source = inspect.getsource(
        baseline_module.GateMonotonicityReceipt.from_dict
    )
    for source in (baseline_source, receipt_source):
        assert "set(payload) != expected_fields" in source
        assert "dict(payload) !=" in source
        assert "digest mismatch" in source
    assert "blocker_set_sha256 does not bind blockers" in inspect.getsource(
        baseline_module.GateBaseline.__post_init__
    )
    receipt_init = inspect.getsource(
        baseline_module.GateMonotonicityReceipt.__post_init__
    )
    assert "blocker partitions must be disjoint" in receipt_init
    assert "status does not match new blockers" in receipt_init


def test_untrusted_file_loaders_are_bounded_and_reject_duplicate_keys() -> None:
    source = inspect.getsource(baseline_module._load_json_object)
    assert "read_bytes()" in source
    assert "len(raw) > max_bytes" in source
    assert 'decode("utf-8")' in source
    assert "object_pairs_hook=_reject_duplicate_keys" in source
    assert "parse_constant=_reject_constant" in source
    assert "JSONDecodeError" in source
    assert "evidence root must be an object" in source


def test_baseline_module_does_not_perform_git_network_or_repository_writes() -> None:
    tree = ast.parse(inspect.getsource(baseline_module))
    forbidden_calls = {
        "write_text",
        "write_bytes",
        "unlink",
        "mkdir",
        "rename",
        "replace",
        "rmdir",
        "Popen",
        "run",
        "system",
        "urlopen",
        "request",
    }
    observed: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute):
            observed.add(node.func.attr)
        elif isinstance(node.func, ast.Name):
            observed.add(node.func.id)
    assert forbidden_calls.isdisjoint(observed)


def test_no_baseline_path_can_create_owner_approval_or_gate_closure() -> None:
    source = inspect.getsource(baseline_module) + inspect.getsource(verifier_module)
    for forbidden in (
        "OwnerApproval(",
        "issue_owner_approval",
        "promote_candidates",
        "security_boundary_claimed=True",
        "closed=True",
        "merge_pull_request",
    ):
        assert forbidden not in source
