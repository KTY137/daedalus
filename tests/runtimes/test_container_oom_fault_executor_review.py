# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

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


def test_allocation_program_observes_kernel_cgroup_state_and_cannot_self_signal() -> None:
    function = _function("_allocation_command")
    text = ast.get_source_segment(SOURCE, function) or ""
    for forbidden in (
        "os.kill",
        "signal.",
        "subprocess",
        "socket",
        "requests",
    ):
        assert forbidden not in text
    required = (
        "/sys/fs/cgroup/memory.events",
        "os.fork()",
        "os.waitpid",
        "os.waitstatus_to_exitcode",
        "oom_kill",
        "while True",
        "bytearray",
        "oom-started",
        "oom-observed.json",
        "unsupported()",
    )
    for expression in required:
        assert expression in text
    assert "SystemExit(70 if observed else 71)" in text
    assert "SystemExit(72)" in text


def test_pass_requires_explicit_oom_counters_sigkill_and_exact_policy() -> None:
    function = _function("_execute_container_oom")
    text = ast.get_source_segment(SOURCE, function) or ""
    required = (
        'receipt.launch_state == "completed"',
        "receipt.returncode == _OOM_OBSERVED_RETURNCODE",
        "receipt.timed_out is False",
        "receipt.error_code is None",
        "started_marker_exists",
        'marker_status == "valid"',
        'marker["supported"] is True',
        'marker["observed"] is True',
        'marker["after_oom"] > marker["before_oom"]',
        'marker["after_oom_kill"] > marker["before_oom_kill"]',
        'marker["child_exitcode"] == -9',
        "memory=_MEMORY",
        'network="none"',
        "pids_limit=32",
    )
    for expression in required:
        assert expression in text
    assert "_OOM_OBSERVED_RETURNCODE = 70" in SOURCE
    assert '_MEMORY = "64m"' in SOURCE
    assert "@sha256:" in SOURCE


def test_cgroup_unavailable_is_one_exact_block_not_a_broad_escape() -> None:
    function = _function("_execute_container_oom")
    text = ast.get_source_segment(SOURCE, function) or ""
    block_start = text.index("receipt.returncode == _CGROUP_UNAVAILABLE_RETURNCODE")
    payload_start = text.index("payload = {", block_start)
    block = text[block_start:payload_start]
    required = (
        "receipt.timed_out is False",
        "receipt.error_code is None",
        "started_marker_exists is False",
        'marker_status == "valid"',
        'marker["supported"] is False',
        'marker["observed"] is False',
        'marker["before_oom"] == 0',
        'marker["after_oom"] == 0',
        'marker["before_oom_kill"] == 0',
        'marker["after_oom_kill"] == 0',
        'marker["child_exitcode"] is None',
        'detail_code="cgroup-v2-memory-events-unavailable"',
    )
    for expression in required:
        assert expression in block
    assert "_CGROUP_UNAVAILABLE_RETURNCODE = 72" in SOURCE


def test_marker_wire_is_bounded_duplicate_rejecting_and_exact() -> None:
    function = _function("_read_oom_marker")
    text = ast.get_source_segment(SOURCE, function) or ""
    assert "_MAX_MARKER_BYTES" in text
    assert "object_pairs_hook=_strict_object" in text
    assert "parse_constant=" in text
    assert "set(payload) != expected" in text
    assert '"supported"' in text
    assert "isinstance(value, bool)" in text
    assert "value < 0" in text
    strict = ast.get_source_segment(SOURCE, _function("_strict_object")) or ""
    assert "duplicate marker key" in strict


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
        '"marker_schema": _MARKER_SCHEMA',
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
    assert '"oom_marker_sha256"' in SOURCE


def test_candidate_output_cannot_claim_trust_attestation_or_gate_closure() -> None:
    assert '"trusted": True' not in SOURCE
    assert '"attested": True' not in SOURCE
    assert '"gate_closure_claimed": True' not in SOURCE
    assert '"trusted": False' in SOURCE
    assert '"attested": False' in SOURCE
    assert '"gate_closure_claimed": False' in SOURCE


def test_execution_boundary_does_not_launder_exceptions() -> None:
    function = _function("_execute_container_oom")
    handlers = [
        node for node in ast.walk(function) if isinstance(node, ast.ExceptHandler)
    ]
    assert handlers == []
