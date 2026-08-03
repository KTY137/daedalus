from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR = ROOT / "tests" / "fixtures" / "unauthorized_egress_fault_executor.py"
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


def _embedded_probe() -> str:
    function = _function("_network_probe_command")
    for statement in function.body:
        if not isinstance(statement, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "script"
            for target in statement.targets
        ):
            value = ast.literal_eval(statement.value)
            assert isinstance(value, str)
            return value
    raise AssertionError("missing embedded network probe")


def test_fixture_has_one_production_sandbox_boundary_and_no_host_network_path() -> None:
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
        "urlopen",
        "create_connection",
    }
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute):
            assert node.func.attr not in forbidden


def test_probe_compiles_uses_fixed_ip_and_inspects_namespace_state() -> None:
    probe = _embedded_probe()
    compile(probe, "<unauthorized-egress-probe>", "exec")
    required = (
        "/sys/class/net",
        "/proc/net/route",
        "socket.AF_INET",
        "socket.SOCK_STREAM",
        "sock.connect(('198.51.100.1', 443))",
        "interfaces == ['lo']",
        "len(fields) >= 8",
        "fields[1] == '00000000'",
        "fields[7] == '00000000'",
        "(int(fields[3], 16) & 1) != 0",
        "not default_route",
        "not connected",
        "error_number == 101",
        "egress-started",
        "egress-observed.json",
    )
    for expression in required:
        assert expression in probe
    for forbidden in (
        "getaddrinfo",
        "gethostbyname",
        "gethostbyaddr",
        "create_connection",
        "http.client",
        "urllib",
        "requests",
    ):
        assert forbidden not in probe


def test_pass_requires_exact_network_none_namespace_and_connect_denial() -> None:
    function = _function("_execute_unauthorized_egress")
    text = ast.get_source_segment(SOURCE, function) or ""
    required = (
        'network=_NETWORK_MODE',
        'receipt.launch_state == "completed"',
        "receipt.returncode == _DENIED_RETURNCODE",
        "receipt.timed_out is False",
        "receipt.error_code is None",
        "started_marker_exists",
        'marker_status == "valid"',
        'marker["supported"] is True',
        'marker["interfaces"] == ["lo"]',
        'marker["default_route"] is False',
        'marker["endpoint_host"] == _ENDPOINT_HOST',
        'marker["endpoint_port"] == _ENDPOINT_PORT',
        'marker["connect_succeeded"] is False',
        'marker["errno"] == _CONNECT_ERRNO',
    )
    for expression in required:
        assert expression in text
    assert '_NETWORK_MODE = "none"' in SOURCE
    assert '_CONNECT_ERRNO = 101' in SOURCE
    assert '_DENIED_RETURNCODE = 73' in SOURCE


def test_inspection_unavailable_is_one_exact_block_not_a_broad_escape() -> None:
    function = _function("_execute_unauthorized_egress")
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
        'marker["interfaces"] == []',
        'marker["default_route"] is False',
        'marker["connect_succeeded"] is False',
        'marker["errno"] is None',
        'detail_code="network-namespace-inspection-unavailable"',
    )
    for expression in required:
        assert expression in block
    assert "_INSPECTION_UNAVAILABLE_RETURNCODE = 75" in SOURCE


def test_marker_wire_is_bounded_duplicate_rejecting_and_exact() -> None:
    function = _function("_read_marker")
    text = ast.get_source_segment(SOURCE, function) or ""
    assert "_MAX_MARKER_BYTES" in text
    assert "object_pairs_hook=_strict_object" in text
    assert "parse_constant=" in text
    assert "set(payload) != expected" in text
    assert "interfaces != sorted(set(interfaces))" in text
    assert "len(interfaces) > 32" in text
    assert 'payload["endpoint_host"] != _ENDPOINT_HOST' in text
    assert 'payload["endpoint_port"] != _ENDPOINT_PORT' in text
    strict = ast.get_source_segment(SOURCE, _function("_strict_object")) or ""
    assert "duplicate marker key" in strict


def test_prestart_refusal_is_blocked_before_denial_evaluation() -> None:
    function = _function("_execute_unauthorized_egress")
    text = ast.get_source_segment(SOURCE, function) or ""
    refusal = text.index("if receipt.refused_before_start")
    exact_denial = text.index("exact_denial =")
    assert refusal < exact_denial
    refusal_block = text[refusal:exact_denial]
    assert 'detail_code="sandbox-unavailable"' in refusal_block
    assert 'status="passed"' not in refusal_block


def test_implementation_identity_binds_production_source_endpoint_and_policy() -> None:
    function = _function("implementation_sha256")
    text = ast.get_source_segment(SOURCE, function) or ""
    required = (
        "Path(__file__).resolve()",
        "_sandbox_source_path()",
        '"marker_schema": _MARKER_SCHEMA',
        '"image": _IMAGE',
        '"network": _NETWORK_MODE',
        '"endpoint_host": _ENDPOINT_HOST',
        '"endpoint_port": _ENDPOINT_PORT',
        '"connect_errno": _CONNECT_ERRNO',
        '"timeout_s": _TIMEOUT_S',
    )
    for binding in required:
        assert binding in text


def test_retained_evidence_excludes_exception_text_and_temporary_paths() -> None:
    function = _function("_execute_unauthorized_egress")
    text = ast.get_source_segment(SOURCE, function) or ""
    assert '"stdout"' not in text
    assert '"stderr"' not in text
    assert '"exception"' not in text
    assert '"temporary"' not in text
    assert "receipt.to_dict()" in text
    assert '"docker_cli_sha256"' in SOURCE
    assert '"sandbox_source_sha256"' in SOURCE
    assert '"egress_marker_sha256"' in SOURCE


def test_candidate_output_cannot_claim_trust_attestation_or_gate_closure() -> None:
    assert '"trusted": True' not in SOURCE
    assert '"attested": True' not in SOURCE
    assert '"gate_closure_claimed": True' not in SOURCE
    assert '"trusted": False' in SOURCE
    assert '"attested": False' in SOURCE
    assert '"gate_closure_claimed": False' in SOURCE


def test_host_execution_boundary_does_not_launder_exceptions() -> None:
    function = _function("_execute_unauthorized_egress")
    handlers = [
        node for node in ast.walk(function) if isinstance(node, ast.ExceptHandler)
    ]
    assert handlers == []
