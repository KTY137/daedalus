from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR_PATH = ROOT / "tests" / "fixtures" / "unauthorized_egress_fault_executor.py"


def _source() -> str:
    return EXECUTOR_PATH.read_text(encoding="utf-8")


def _call_names() -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(_source(), filename=str(EXECUTOR_PATH))):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            names.append(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            names.append(node.func.attr)
    return names


def test_one_production_sandbox_boundary_and_no_fixture_launcher() -> None:
    calls = _call_names()
    assert calls.count("run_in_docker_sandbox") == 1
    assert "Popen" not in calls
    assert "subprocess" not in _source()
    assert "shell=True" not in _source().replace(" ", "")


def test_pass_depends_on_exact_topology_endpoint_errno_and_start() -> None:
    source = _source()
    for fragment in (
        'receipt.launch_state == "completed"',
        "receipt.returncode == _DENIED_RETURNCODE",
        "started_marker_exists",
        'marker["supported"] is True',
        'marker["interfaces"] == ["lo"]',
        'marker["default_route"] is False',
        'marker["endpoint_host"] == _ENDPOINT_HOST',
        'marker["endpoint_port"] == _ENDPOINT_PORT',
        'marker["connect_succeeded"] is False',
        'marker["errno"] == _CONNECT_ERRNO',
        'network=_NETWORK_MODE',
        '_NETWORK_MODE = "none"',
    ):
        assert fragment in source


def test_probe_uses_numeric_egress_and_observes_namespace() -> None:
    source = _source()
    for fragment in (
        "socket.socket",
        "sock.connect(('198.51.100.1', 443))",
        "/proc/net/route",
        "/sys/class/net",
        "/workspace/egress-started",
        "/workspace/egress-observed.json",
    ):
        assert fragment in source


def test_default_route_detection_uses_the_active_route_flag() -> None:
    source = _source()
    assert "int(fields[3], 16) & 0x1" in source
    assert "int(fields[3], 16) & 2" not in source


def test_marker_parser_refuses_ambiguity_and_endpoint_substitution() -> None:
    source = _source()
    for fragment in (
        "duplicate marker key",
        "non-finite marker value",
        "set(payload) != expected",
        'payload["endpoint_host"] != _ENDPOINT_HOST',
        'payload["endpoint_port"] != _ENDPOINT_PORT',
        "len(interfaces) > 32",
    ):
        assert fragment in source


def test_evidence_cannot_claim_trust_or_retain_plaintext_docker_output() -> None:
    source = _source()
    assert '"trusted": False' in source
    assert '"attested": False' in source
    assert '"gate_closure_claimed": False' in source
    assert '"stdout":' not in source
    assert '"stderr":' not in source
    assert "proc.stdout" not in source
    assert "proc.stderr" not in source


def test_mutation_targets_remain_in_review_surface() -> None:
    source = _source()
    targets = {
        "network": 'network=_NETWORK_MODE',
        "returncode": "receipt.returncode == _DENIED_RETURNCODE",
        "start": "started_marker_exists",
        "route": 'marker["default_route"] is False',
        "route-active-flag": "int(fields[3], 16) & 0x1",
        "interface": 'marker["interfaces"] == ["lo"]',
        "errno": 'marker["errno"] == _CONNECT_ERRNO',
        "sandbox-identity": '"sandbox_sha256": _file_sha256(_sandbox_source_path())',
    }
    assert [name for name, fragment in targets.items() if fragment not in source] == []
