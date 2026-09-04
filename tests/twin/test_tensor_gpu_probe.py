from __future__ import annotations

import ast
import json
import runpy
from pathlib import Path

import pytest

PROBE_PATH = (
    Path(__file__).parents[2]
    / "experiments"
    / "tensor_gpu"
    / "cuda_boolean_probe.py"
)
_NAMESPACE = runpy.run_path(str(PROBE_PATH))
ProbeCase = _NAMESPACE["ProbeCase"]
build_boolean_case = _NAMESPACE["build_boolean_case"]
blocked_report = _NAMESPACE["blocked_report"]
estimate_dense_device_bytes = _NAMESPACE["estimate_dense_device_bytes"]
exact_reference_operation_count = _NAMESPACE["exact_reference_operation_count"]
write_report = _NAMESPACE["write_report"]
BooleanSemiring = _NAMESPACE["BooleanSemiring"]


def test_probe_module_keeps_torch_optional_at_import_time() -> None:
    tree = ast.parse(PROBE_PATH.read_text(encoding="utf-8"))
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_from = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert "torch" not in imports
    assert "torch" not in imported_from


def test_probe_case_bounds_dense_input_and_execution() -> None:
    for kwargs in (
        {"size": 1, "density": 0.1},
        {"size": 8, "density": 0.0},
        {"size": 8, "density": float("nan")},
        {"size": 8, "density": 0.1, "repeats": 0},
        {"size": 8, "density": 0.1, "warmup": 51},
        {"size": 8, "density": 0.1, "dtype_name": "float32"},
        {"size": 8, "density": 0.1, "max_device_mib": 63},
    ):
        with pytest.raises(ValueError):
            ProbeCase(**kwargs)


def test_dense_memory_estimate_accounts_for_tensor_core_padding() -> None:
    case = ProbeCase(
        size=9,
        density=0.1,
        repeats=1,
        warmup=0,
        tile_multiple=8,
        max_device_mib=64,
    )
    assert estimate_dense_device_bytes(case) == 16 * 16 * 7


def test_synthetic_case_is_deterministic_and_matches_reference_contract() -> None:
    case = ProbeCase(
        size=8,
        density=0.25,
        repeats=1,
        warmup=0,
        max_device_mib=64,
    )
    left, right, metadata = build_boolean_case(case)
    repeated_left, repeated_right, repeated_metadata = build_boolean_case(case)

    assert left.digest == repeated_left.digest
    assert right.digest == repeated_right.digest
    assert metadata == repeated_metadata
    assert left.column_axis == right.row_axis
    operations = exact_reference_operation_count(left, right)
    assert operations > 0

    result = left.matmul(
        right,
        BooleanSemiring(),
        relation="cuda_probe_composed",
        max_operations=operations,
    )
    assert result.entry_count > 0
    assert result.subject == left.subject
    assert result.row_axis == left.row_axis
    assert result.column_axis == right.column_axis


def test_blocked_report_cannot_mint_a_gpu_or_benchmark_claim() -> None:
    report = blocked_report("cuda-unavailable", "no device")
    assert report == {
        "schema": "daedalus-tensor-cuda-boolean-probe/1",
        "status": "blocked",
        "authority": "diagnostic-only",
        "claim": "none",
        "reason": "cuda-unavailable",
        "detail": "no device",
        "cases": [],
    }


def test_report_write_is_atomic_and_strict_json(tmp_path: Path) -> None:
    target = tmp_path / "gpu" / "report.json"
    report = blocked_report("torch-not-installed", "install torch")
    write_report(target, report)

    assert json.loads(target.read_text(encoding="utf-8")) == report
    assert not target.with_name(target.name + ".tmp").exists()
