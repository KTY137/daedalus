from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXECUTOR = ROOT / "tests" / "fixtures" / "container_oom_fault_executor.py"
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


def test_allocation_program_cannot_self_signal_or_claim_success() -> None:
    function = _function("_allocation_command")
    text = ast.get_source_segment(SOURCE, function) or ""
    for forbidden in (
        "os.kill",
        "signal.",
        "SIGKILL",
        "SIGTERM",
        "sys.exit",
        "SystemExit",
        "subprocess",
        "socket",
        "requests",
    ):
        assert forbidden not in text
    assert "while True" in text
    assert "bytearray" in text
    assert "oom-started" in text


def test_pass_requires_started_container_exact_sigkill_and_memory_policy() -> None:
    function = _function("_execute_container_oom")
    text = ast.get_source_segment(SOURCE, function) or ""
    required = (
        'receipt.launch_state == "completed"',
        "receipt.returncode == _OOM_RETURNCODE",
        "receipt.timed_out is False",
        "receipt.error_code is None",
        "marker_exists",
        "memory=_MEMORY",
        'network="none"',
        "pids_limit=32",
    )
    for expression in required:
        assert expression in text
    assert '_OOM_RETURNCODE = 137' in SOURCE
    assert '_MEMORY = "64m"' in SOURCE
    assert "@sha256:" in SOURCE


def test_prestart_refusal_is_blocked_and_never_counted_as_oom() -> None:
    function = _function("_execute_container_oom")
    text = ast.get_source_segment(SOURCE, function) or ""
    refusal = text.index("if receipt.refused_before_start")
    exact_oom = text.index("exact_oom =")
    assert refusal < exact_oom
    refusal_block = text[refusal:exact_oom]
    assert 'detail_code="sandbox-unavailable"' in refusal_block
    assert "status=\"passed\"" not in refusal_block


def test_implementation_identity_binds_executor_production_source_image_and_limits() -> None:
    function = _function("implementation_sha256")
    text = ast.get_source_segment(SOURCE, function) or ""
    for binding in (
        "Path(__file__).resolve()",
        "_sandbox_source_path()",
        '"image": _IMAGE',
        '"memory": _MEMORY',
        '"timeout_s": _TIMEOUT_S',
    ):
        assert binding in text


def test_retained_evidence_excludes_plaintext_outputs_and_temporary_paths() -> None:
    function = _function("_execute_container_oom")
    text = ast.get_source_segment(SOURCE, function) or ""
    assert '"stdout"' not in text
    assert '"stderr"' not in text
    assert '"temporary"' not in text
    assert "receipt.to_dict()" in text
    assert '"docker_cli_sha256"' in SOURCE
    assert '"sandbox_source_sha256"' in SOURCE


def test_candidate_output_cannot_claim_trust_attestation_or_gate_closure() -> None:
    assert '"trusted": True' not in SOURCE
    assert '"attested": True' not in SOURCE
    assert '"gate_closure_claimed": True' not in SOURCE
    assert '"trusted": False' in SOURCE
    assert '"attested": False' in SOURCE
    assert '"gate_closure_claimed": False' in SOURCE


def test_only_expected_exception_boundary_is_present() -> None:
    # Host control-flow exceptions must not be converted into a passed result.
    handlers = [node for node in ast.walk(TREE) if isinstance(node, ast.ExceptHandler)]
    assert handlers == []
