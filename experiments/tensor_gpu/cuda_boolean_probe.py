"""Bounded CUDA/Tensor-Core probe for Boolean Fourfold relation composition.

This is an isolated experiment. It does not add a production backend or make
GPU results authoritative. The current stdlib ``TypedRelationBlock`` remains
the executable semantic oracle; this module only asks whether an FP16/BF16
CUDA GEMM can reproduce Boolean support faster for sufficiently large blocks.

RT cores and raster units are deliberately not targeted. The matrix multiply
is submitted through PyTorch/cuBLAS, which may select Tensor Cores when the
installed CUDA build, GPU capability, dtype, and shape permit it. Actual
Tensor-Core use requires an external profiler to prove; the report therefore
records only ``tensor_core_candidate=true`` and never claims hardware-unit use.
"""
from __future__ import annotations

import argparse
import importlib
import json
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from daedalus.twin.relation_blocks import (
    MAX_BLOCK_ENTRIES,
    MAX_REFERENCE_OPERATIONS,
    RelationSignature,
    TypedRelationBlock,
)
from daedalus.twin.semiring import BooleanSemiring

if __package__:
    from .boolean_probe_contract import (
        MAX_CASES,
        MIB,
        ProbeCase,
        SUPPORTED_DTYPES,
        build_boolean_case,
        estimate_dense_device_bytes,
        exact_reference_operation_count,
        padded,
        ratio,
        same_support,
        write_report,
    )
else:  # direct ``python experiments/tensor_gpu/cuda_boolean_probe.py``
    from boolean_probe_contract import (
        MAX_CASES,
        MIB,
        ProbeCase,
        SUPPORTED_DTYPES,
        build_boolean_case,
        estimate_dense_device_bytes,
        exact_reference_operation_count,
        padded,
        ratio,
        same_support,
        write_report,
    )

SCHEMA = "daedalus-tensor-cuda-boolean-probe/1"


class ProbeBlocked(RuntimeError):
    """A measured environment or bound prevents the probe from running."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class _GpuExecution:
    block: TypedRelationBlock[bool]
    pack_to_device_ms: float
    output_allocate_ms: float
    kernel_ms: tuple[float, ...]
    readback_and_canonicalize_ms: float
    peak_device_bytes: int
    output_entries: int


def _load_torch() -> Any:
    try:
        return importlib.import_module("torch")
    except ModuleNotFoundError as exc:
        if exc.name == "torch":
            raise ProbeBlocked(
                "torch-not-installed",
                "install a CUDA-enabled PyTorch build before running this probe",
            ) from exc
        raise


def _device_info(torch: Any, device_index: int, dtype_name: str) -> dict[str, Any]:
    if not bool(torch.cuda.is_available()):
        raise ProbeBlocked(
            "cuda-unavailable",
            "PyTorch is installed, but torch.cuda.is_available() is false",
        )
    count = int(torch.cuda.device_count())
    if type(device_index) is not int or not 0 <= device_index < count:
        raise ProbeBlocked(
            "cuda-device-missing",
            f"device_index={device_index} is outside the available range 0..{count - 1}",
        )
    if dtype_name == "bfloat16" and not bool(torch.cuda.is_bf16_supported()):
        raise ProbeBlocked(
            "bfloat16-unsupported",
            "the selected CUDA device does not support bfloat16 execution",
        )
    with torch.cuda.device(device_index):
        name = str(torch.cuda.get_device_name(device_index))
        major, minor = torch.cuda.get_device_capability(device_index)
        free_bytes, total_bytes = torch.cuda.mem_get_info(device_index)
    return {
        "device_index": device_index,
        "device_name": name,
        "compute_capability": f"{major}.{minor}",
        "cuda_runtime": str(getattr(torch.version, "cuda", None)),
        "torch_version": str(torch.__version__),
        "free_device_bytes_at_start": int(free_bytes),
        "total_device_bytes": int(total_bytes),
        "tensor_core_candidate": (major, minor) >= (7, 0),
        "tensor_core_proven": False,
        "tensor_core_proof_required": "Nsight Compute/System or cuBLAS kernel tracing",
        "rt_cores_used": False,
        "raster_units_used": False,
    }


def _torch_dtype(torch: Any, dtype_name: str) -> Any:
    return {
        "float16": torch.float16,
        "bfloat16": torch.bfloat16,
    }[dtype_name]


def _csr_row_indices(block: TypedRelationBlock[bool]) -> list[int]:
    rows: list[int] = []
    for row in range(len(block.row_axis.labels)):
        rows.extend([row] * (block.row_offsets[row + 1] - block.row_offsets[row]))
    return rows


def _dense_from_block(
    torch: Any,
    block: TypedRelationBlock[bool],
    *,
    device: str,
    dtype: Any,
    padded_size: int,
) -> Any:
    if block.semiring_name != "boolean" or any(value is not True for value in block.values):
        raise ValueError("CUDA probe accepts canonical Boolean relation blocks only")
    dense = torch.zeros(
        (padded_size, padded_size),
        dtype=dtype,
        device=device,
    )
    if block.entry_count:
        rows = torch.tensor(
            _csr_row_indices(block),
            dtype=torch.int64,
            device=device,
        )
        columns = torch.tensor(
            block.column_indices,
            dtype=torch.int64,
            device=device,
        )
        dense[rows, columns] = 1
    return dense


def _validate_gpu_operands(
    left: TypedRelationBlock[bool],
    right: TypedRelationBlock[bool],
) -> None:
    if not isinstance(left, TypedRelationBlock) or not isinstance(
        right, TypedRelationBlock
    ):
        raise ValueError("GPU operands must be TypedRelationBlock values")
    if left.semiring_name != "boolean" or right.semiring_name != "boolean":
        raise ValueError("GPU probe currently supports the Boolean semiring only")
    if left.subject != right.subject:
        raise ValueError("GPU operands must bind the same exact Fourfold subject")
    if left.column_axis != right.row_axis:
        raise ValueError("GPU matrix composition requires an exact typed middle axis")
    if len(left.row_axis.labels) != len(left.column_axis.labels):
        raise ValueError("current probe requires a square left block")
    if len(right.row_axis.labels) != len(right.column_axis.labels):
        raise ValueError("current probe requires a square right block")
    if len(left.row_axis.labels) != len(right.column_axis.labels):
        raise ValueError("current probe requires one common square probe size")


def _resident_mm(torch: Any, left_dense: Any, right_dense: Any, product: Any) -> Any:
    """Execute one 2-D CUDA GEMM into an already allocated output tensor."""

    return torch.mm(left_dense, right_dense, out=product)


def _gpu_boolean_matmul(
    torch: Any,
    left: TypedRelationBlock[bool],
    right: TypedRelationBlock[bool],
    case: ProbeCase,
    *,
    device_index: int,
    free_device_bytes: int,
) -> _GpuExecution:
    _validate_gpu_operands(left, right)
    estimated = estimate_dense_device_bytes(case)
    admitted = min(case.max_device_mib * MIB, free_device_bytes // 2)
    if estimated > admitted:
        raise ProbeBlocked(
            "device-memory-bound",
            f"estimated {estimated} bytes exceeds admitted {admitted} bytes",
        )

    device = f"cuda:{device_index}"
    dtype = _torch_dtype(torch, case.dtype_name)
    padded_size = padded(case.size, case.tile_multiple)
    torch.cuda.synchronize(device_index)
    torch.cuda.reset_peak_memory_stats(device_index)

    started = time.perf_counter_ns()
    with torch.inference_mode():
        left_dense = _dense_from_block(
            torch,
            left,
            device=device,
            dtype=dtype,
            padded_size=padded_size,
        )
        right_dense = _dense_from_block(
            torch,
            right,
            device=device,
            dtype=dtype,
            padded_size=padded_size,
        )
    torch.cuda.synchronize(device_index)
    pack_ms = (time.perf_counter_ns() - started) / 1_000_000.0

    started = time.perf_counter_ns()
    with torch.inference_mode():
        product = torch.empty(
            (padded_size, padded_size),
            dtype=dtype,
            device=device,
        )
    torch.cuda.synchronize(device_index)
    output_allocate_ms = (time.perf_counter_ns() - started) / 1_000_000.0

    with torch.inference_mode():
        for _ in range(case.warmup):
            _resident_mm(torch, left_dense, right_dense, product)
        torch.cuda.synchronize(device_index)

        kernel_ms: list[float] = []
        for _ in range(case.repeats):
            start_event = torch.cuda.Event(enable_timing=True)
            end_event = torch.cuda.Event(enable_timing=True)
            start_event.record()
            _resident_mm(torch, left_dense, right_dense, product)
            end_event.record()
            torch.cuda.synchronize(device_index)
            kernel_ms.append(float(start_event.elapsed_time(end_event)))

    started = time.perf_counter_ns()
    support = (product[: case.size, : case.size] > 0).to(
        device="cpu",
        dtype=torch.uint8,
    )
    torch.cuda.synchronize(device_index)
    positions = support.nonzero(as_tuple=False).tolist()
    if len(positions) > MAX_BLOCK_ENTRIES:
        raise ProbeBlocked(
            "output-entry-bound",
            f"Boolean support contains {len(positions)} entries, above {MAX_BLOCK_ENTRIES}",
        )
    coordinates = tuple(
        (
            left.row_axis.labels[row],
            right.column_axis.labels[column],
            True,
        )
        for row, column in positions
    )
    block = TypedRelationBlock.from_coordinates(
        subject=left.subject,
        signature=RelationSignature(
            left.signature.source_plane,
            "cuda_probe_composed",
            right.signature.target_plane,
        ),
        row_axis=left.row_axis,
        column_axis=right.column_axis,
        coordinates=coordinates,
        semiring=BooleanSemiring(),
    )
    readback_ms = (time.perf_counter_ns() - started) / 1_000_000.0
    peak_bytes = int(torch.cuda.max_memory_allocated(device_index))

    del support, product, left_dense, right_dense
    torch.cuda.empty_cache()
    return _GpuExecution(
        block=block,
        pack_to_device_ms=pack_ms,
        output_allocate_ms=output_allocate_ms,
        kernel_ms=tuple(kernel_ms),
        readback_and_canonicalize_ms=readback_ms,
        peak_device_bytes=peak_bytes,
        output_entries=block.entry_count,
    )


def run_case(
    case: ProbeCase,
    *,
    torch: Any,
    device_info: dict[str, Any],
) -> dict[str, Any]:
    build_started = time.perf_counter_ns()
    left, right, fixture = build_boolean_case(case)
    build_ms = (time.perf_counter_ns() - build_started) / 1_000_000.0
    operation_count = exact_reference_operation_count(left, right)

    cpu_block: TypedRelationBlock[bool] | None = None
    cpu_ms: float | None = None
    cpu_status = "skipped-operation-bound"
    if operation_count <= case.cpu_max_operations:
        cpu_started = time.perf_counter_ns()
        cpu_block = left.matmul(
            right,
            BooleanSemiring(),
            relation="cuda_probe_composed",
            max_operations=case.cpu_max_operations,
        )
        cpu_ms = (time.perf_counter_ns() - cpu_started) / 1_000_000.0
        cpu_status = "verified"

    gpu = _gpu_boolean_matmul(
        torch,
        left,
        right,
        case,
        device_index=int(device_info["device_index"]),
        free_device_bytes=int(device_info["free_device_bytes_at_start"]),
    )
    kernel_median = float(statistics.median(gpu.kernel_ms))
    end_to_end_ms = (
        gpu.pack_to_device_ms
        + gpu.output_allocate_ms
        + kernel_median
        + gpu.readback_and_canonicalize_ms
    )
    support_equal = None if cpu_block is None else same_support(cpu_block, gpu.block)
    if support_equal is False:
        raise AssertionError("CUDA Boolean support differs from the stdlib CSR oracle")

    return {
        "status": "verified" if support_equal is True else "performance-only",
        "claim": "none",
        "case": {
            "size": case.size,
            "dtype": case.dtype_name,
            "tile_multiple": case.tile_multiple,
            "padded_size": padded(case.size, case.tile_multiple),
            "repeats": case.repeats,
            "warmup": case.warmup,
            "max_device_mib": case.max_device_mib,
            **fixture,
        },
        "construction": {
            "typed_csr_inputs_ms": build_ms,
            "estimated_device_bytes": estimate_dense_device_bytes(case),
            "reference_operation_count": operation_count,
        },
        "cpu_reference": {
            "status": cpu_status,
            "elapsed_ms": cpu_ms,
            "output_entries": None if cpu_block is None else cpu_block.entry_count,
            "digest": None if cpu_block is None else cpu_block.digest,
        },
        "gpu": {
            "pack_to_device_ms": gpu.pack_to_device_ms,
            "output_allocate_ms": gpu.output_allocate_ms,
            "kernel_ms_median": kernel_median,
            "kernel_ms_min": min(gpu.kernel_ms),
            "kernel_ms_max": max(gpu.kernel_ms),
            "readback_and_canonicalize_ms": gpu.readback_and_canonicalize_ms,
            "one_shot_end_to_end_ms": end_to_end_ms,
            "peak_device_bytes": gpu.peak_device_bytes,
            "output_entries": gpu.output_entries,
            "digest": gpu.block.digest,
        },
        "correctness": {
            "cpu_oracle_executed": cpu_block is not None,
            "boolean_support_equal": support_equal,
        },
        "diagnostic_ratios": {
            "cpu_over_resident_gpu_kernel": ratio(cpu_ms, kernel_median),
            "cpu_over_gpu_one_shot": ratio(cpu_ms, end_to_end_ms),
        },
    }


def blocked_report(reason: str, detail: str) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "blocked",
        "authority": "diagnostic-only",
        "claim": "none",
        "reason": reason,
        "detail": detail,
        "cases": [],
    }


def _cuda_oom_result(torch: Any, exc: BaseException, case: ProbeCase) -> dict[str, Any] | None:
    """Translate only PyTorch's explicit CUDA OOM type into blocked evidence."""

    oom_type = getattr(torch, "OutOfMemoryError", None)
    if not isinstance(oom_type, type) or not isinstance(exc, oom_type):
        return None
    try:
        torch.cuda.empty_cache()
    except Exception:
        # Cleanup is best-effort after the allocator already refused work. The
        # original OOM remains the measured reason; cleanup cannot turn it green.
        pass
    return {
        "status": "blocked",
        "claim": "none",
        "reason": "cuda-out-of-memory",
        "detail": str(exc),
        "case": {
            "size": case.size,
            "density": case.density,
            "dtype": case.dtype_name,
            "estimated_device_bytes": estimate_dense_device_bytes(case),
        },
    }


def run_probe(
    cases: Sequence[ProbeCase],
    *,
    device_index: int = 0,
) -> dict[str, Any]:
    if isinstance(cases, (str, bytes)) or not isinstance(cases, Sequence):
        raise ValueError("cases must be a bounded sequence")
    if not cases or len(cases) > MAX_CASES:
        raise ValueError(f"cases must contain between 1 and {MAX_CASES} entries")
    if any(not isinstance(case, ProbeCase) for case in cases):
        raise ValueError("cases must contain ProbeCase values")

    try:
        torch = _load_torch()
        device = _device_info(torch, device_index, cases[0].dtype_name)
    except ProbeBlocked as exc:
        return blocked_report(exc.reason, exc.detail)

    results: list[dict[str, Any]] = []
    for case in cases:
        if case.dtype_name != cases[0].dtype_name:
            raise ValueError("one run must use one dtype so device evidence is unambiguous")
        try:
            results.append(run_case(case, torch=torch, device_info=device))
        except ProbeBlocked as exc:
            results.append(
                {
                    "status": "blocked",
                    "claim": "none",
                    "reason": exc.reason,
                    "detail": exc.detail,
                    "case": {
                        "size": case.size,
                        "density": case.density,
                        "dtype": case.dtype_name,
                    },
                }
            )
        except Exception as exc:
            blocked = _cuda_oom_result(torch, exc, case)
            if blocked is None:
                raise
            results.append(blocked)

    return {
        "schema": SCHEMA,
        "status": (
            "completed"
            if all(result["status"] in {"verified", "performance-only"} for result in results)
            else "completed-with-blocked-cases"
        ),
        "authority": "diagnostic-only",
        "claim": "none",
        "semantic_scope": "Boolean relation support only",
        "device": device,
        "cases": results,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Compare the bounded stdlib Boolean CSR oracle with an aligned "
            "FP16/BF16 CUDA dense GEMM candidate."
        )
    )
    parser.add_argument("--sizes", type=int, nargs="+", default=(256, 512, 1024))
    parser.add_argument("--densities", type=float, nargs="+", default=(0.005, 0.02))
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--warmup", type=int, default=5)
    parser.add_argument("--dtype", choices=sorted(SUPPORTED_DTYPES), default="float16")
    parser.add_argument("--tile-multiple", type=int, choices=(8, 16), default=8)
    parser.add_argument("--device-index", type=int, default=0)
    parser.add_argument("--max-device-mib", type=int, default=1024)
    parser.add_argument(
        "--cpu-max-operations",
        type=int,
        default=MAX_REFERENCE_OPERATIONS,
    )
    parser.add_argument("--output", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    cases = tuple(
        ProbeCase(
            size=size,
            density=float(density),
            repeats=args.repeats,
            warmup=args.warmup,
            dtype_name=args.dtype,
            tile_multiple=args.tile_multiple,
            max_device_mib=args.max_device_mib,
            cpu_max_operations=args.cpu_max_operations,
        )
        for size in args.sizes
        for density in args.densities
    )
    report = run_probe(cases, device_index=args.device_index)
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False)
    print(rendered)
    if args.output is not None:
        write_report(args.output, report)
    return 0 if report["status"].startswith("completed") else 2


if __name__ == "__main__":
    raise SystemExit(main())
