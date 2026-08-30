# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR = ROOT / "tests" / "fixtures" / "undeclared_secret_fault_executor.py"
SOURCE = EXECUTOR.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _calls(name: str) -> list[ast.Call]:
    result: list[ast.Call] = []
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == name:
            result.append(node)
        elif isinstance(node.func, ast.Attribute) and node.func.attr == name:
            result.append(node)
    return result


def _function(name: str) -> ast.FunctionDef:
    for node in TREE.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"missing function {name}")


def _render_probe_node(node: ast.AST) -> str:
    values: dict[str, object] = {
        "_SECRET_NAME": "DAEDALUS_UNDECLARED_SECRET_PROBE",
        "roots_literal": repr(
            ("/run/secrets", "/var/run/secrets", "/run/credentials")
        ),
    }
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(_render_probe_node(value) for value in node.values)
    if isinstance(node, ast.FormattedValue):
        if not isinstance(node.value, ast.Name) or node.value.id not in values:
            raise AssertionError("unexpected formatted probe expression")
        value = values[node.value.id]
        if node.conversion == -1:
            return str(value)
        if node.conversion == ord("r"):
            return repr(value)
        raise AssertionError("unexpected probe format conversion")
    raise AssertionError(f"unsupported probe AST node: {type(node).__name__}")


def _embedded_probe() -> str:
    function = _function("_secret_probe_command")
    for statement in function.body:
        if not isinstance(statement, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "script"
            for target in statement.targets
        ):
            return _render_probe_node(statement.value)
    raise AssertionError("missing embedded secret probe")


def test_fixture_has_one_production_sandbox_boundary_and_no_second_launcher() -> None:
    assert len(_calls("run_in_docker_sandbox")) == 1
    assert "import subprocess" not in SOURCE
    assert "from subprocess" not in SOURCE
    assert "shell=True" not in SOURCE.replace(" ", "")
    forbidden = {
        "Popen",
        "run",
        "call",
        "check_call",
        "check_output",
        "system",
        "popen",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
    }
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden


def test_probe_compiles_enumerates_names_only_and_inspects_secret_mounts() -> None:
    probe = _embedded_probe()
    compile(probe, "<undeclared-secret-probe>", "exec")
    required = (
        "sorted(os.environ.keys())",
        "os.environ[secret_name]",
        "/proc/self/mountinfo",
        "/run/secrets",
        "/var/run/secrets",
        "/run/credentials",
        "secret_mount_detected",
        "secret_artifact_count",
        "artifact_scan_bounded",
        "environment_names_sha256",
        "mountinfo_sha256",
        "raise SystemExit(76 if isolated else 77)",
        "raise SystemExit(78)",
    )
    for expression in required:
        assert expression in probe
    for forbidden in (
        "os.environ.items",
        "os.environ.values",
        "dict(os.environ)",
        "print(",
        "stdout",
        "stderr",
    ):
        assert forbidden not in probe


def test_review_reconstruction_has_no_dynamic_eval_or_exec_call() -> None:
    review_tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    forbidden_calls = [
        node
        for node in ast.walk(review_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"eval", "exec"}
    ]
    assert forbidden_calls == []


def test_host_canary_is_locked_inherited_removed_only_if_unchanged() -> None:
    function = _function("_execute_undeclared_secret")
    text = ast.get_source_segment(SOURCE, function) or ""
    required = (
        "with _HOST_ENV_LOCK",
        "if _SECRET_NAME in os.environ",
        "canary = secrets.token_hex(32)",
        "os.environ[_SECRET_NAME] = canary",
        "receipt = run_in_docker_sandbox(policy, _secret_probe_command())",
        "finally:",
        "retained = os.environ.get(_SECRET_NAME)",
        "if retained == canary",
        "del os.environ[_SECRET_NAME]",
        "host_environment_restored = True",
        "host_environment_restored = False",
        'detail_code="host-secret-probe-name-collision"',
        'detail_code="host-secret-probe-mutated"',
    )
    for expression in required:
        assert expression in text
    assert "os.environ.pop(_SECRET_NAME" not in text
    call = _calls("run_in_docker_sandbox")[0]
    call_text = ast.get_source_segment(SOURCE, call) or ""
    assert "canary" not in call_text
    assert "secret_name" not in call_text


def test_pass_requires_exact_empty_secret_namespace_and_no_canary_retention() -> None:
    function = _function("_execute_undeclared_secret")
    text = ast.get_source_segment(SOURCE, function) or ""
    required = (
        'reference_mounts=()',
        'network="none"',
        'receipt.launch_state == "completed"',
        "receipt.returncode == _ISOLATED_RETURNCODE",
        "receipt.timed_out is False",
        "receipt.error_code is None",
        "started_marker_exists",
        'marker_status == "valid"',
        'marker["supported"] is True',
        'marker["secret_name_present"] is False',
        'marker["secret_value_read"] is False',
        'marker["environment_names_sha256"] != _ZERO_SHA256',
        'marker["mountinfo_sha256"] != _ZERO_SHA256',
        'marker["secret_mount_detected"] is False',
        'marker["secret_artifact_count"] == 0',
        'marker["artifact_scan_bounded"] is True',
        'canary_bytes not in canonical_json(payload).encode("utf-8")',
    )
    for expression in required:
        assert expression in text
    assert "_ISOLATED_RETURNCODE = 76" in SOURCE
    assert "_LEAK_RETURNCODE = 77" in SOURCE


def test_inspection_unavailable_is_one_exact_block_not_a_broad_escape() -> None:
    function = _function("_execute_undeclared_secret")
    text = ast.get_source_segment(SOURCE, function) or ""
    block_start = text.index(
        "receipt.returncode == _INSPECTION_UNAVAILABLE_RETURNCODE"
    )
    payload_start = text.index("payload = {", block_start)
    block = text[block_start:payload_start]
    required = (
        "receipt.timed_out is False",
        "receipt.error_code is None",
        "started_marker_exists is False",
        'marker_status == "valid"',
        'marker["supported"] is False',
        'marker["secret_name_present"] is False',
        'marker["secret_value_read"] is False',
        'marker["environment_names_sha256"] == _ZERO_SHA256',
        'marker["mountinfo_sha256"] == _ZERO_SHA256',
        'marker["secret_mount_detected"] is False',
        'marker["secret_artifact_count"] == 0',
        'marker["artifact_scan_bounded"] is True',
        'detail_code="secret-namespace-inspection-unavailable"',
    )
    for expression in required:
        assert expression in block
    assert "_INSPECTION_UNAVAILABLE_RETURNCODE = 78" in SOURCE


def test_marker_wire_is_bounded_exact_and_rejects_canary_bytes() -> None:
    function = _function("_read_marker")
    text = ast.get_source_segment(SOURCE, function) or ""
    required = (
        "_MAX_MARKER_BYTES",
        "forbidden_canary in payload_bytes",
        "object_pairs_hook=_strict_object",
        "parse_constant=",
        "set(payload) != expected",
        'payload["secret_name"] != _SECRET_NAME',
        "count > _MAX_SECRET_ARTIFACTS + 1",
    )
    for expression in required:
        assert expression in text
    strict = ast.get_source_segment(SOURCE, _function("_strict_object")) or ""
    assert "duplicate marker key" in strict


def test_base_payload_accepts_only_canary_digest_not_value() -> None:
    function = _function("_base_payload")
    text = ast.get_source_segment(SOURCE, function) or ""
    assert "canary_sha256" in text
    assert "canary:" not in text
    assert '"canary"' not in text
    assert '"canary_sha256"' in text


def test_implementation_identity_binds_production_source_and_secret_boundary() -> None:
    function = _function("implementation_sha256")
    text = ast.get_source_segment(SOURCE, function) or ""
    required = (
        "Path(__file__).resolve()",
        "_sandbox_source_path()",
        '"marker_schema": _MARKER_SCHEMA',
        '"image": _IMAGE',
        '"secret_name": _SECRET_NAME',
        '"secret_roots": list(_SECRET_ROOTS)',
        '"timeout_s": _TIMEOUT_S',
        '"max_secret_artifacts": _MAX_SECRET_ARTIFACTS',
    )
    for binding in required:
        assert binding in text


def test_retained_evidence_has_no_plaintext_environment_or_file_material() -> None:
    execute = ast.get_source_segment(SOURCE, _function("_execute_undeclared_secret")) or ""
    assert '"environment_names"' not in execute
    assert '"mountinfo"' not in execute
    assert '"secret_value"' not in execute
    assert '"stdout"' not in execute
    assert '"stderr"' not in execute
    assert "receipt.to_dict()" in execute
    assert '"canary_sha256"' in SOURCE
    assert '"secret_marker_sha256"' in SOURCE


def test_candidate_output_cannot_claim_trust_attestation_or_gate_closure() -> None:
    assert '"trusted": True' not in SOURCE
    assert '"attested": True' not in SOURCE
    assert '"gate_closure_claimed": True' not in SOURCE
    assert '"trusted": False' in SOURCE
    assert '"attested": False' in SOURCE
    assert '"gate_closure_claimed": False' in SOURCE


def test_host_execution_boundary_has_cleanup_finally_but_no_exception_laundering() -> None:
    function = _function("_execute_undeclared_secret")
    handlers = [
        node for node in ast.walk(function) if isinstance(node, ast.ExceptHandler)
    ]
    finalizers = [node for node in ast.walk(function) if isinstance(node, ast.Try)]
    assert handlers == []
    assert any(node.finalbody for node in finalizers)
