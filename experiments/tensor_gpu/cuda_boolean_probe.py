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
import hashlib
import importlib
import json
import math
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from daedalus.twin.relation_blocks import (
    MAX_BLOCK_ENTRIES,
    MAX_REFERENCE_OPERATIONS,
    ProjectionSubject,
    RelationSignature,
    TypedAxis,
    TypedRelationBlock,
)
from daedalus.twin.semiring import BooleanSemiring

SCHEMA = "daedalus-tensor-cuda-boolean-probe/1"
MAX_AXIS = 8_192
MAX_REPEATS = 100
MAX_WARMUP = 50
MAX_DEVICE_MIB = 32_768
_SUPPORTED_DTYPES = frozenset({"float16", "bfloat16"})
_MIB = 1024 * 1024
_INT64_BYTES = 8


class ProbeBlocked(RuntimeError):
    """A measured environment or bound prevents the probe from running."""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class ProbeCase:
    size: int
    density: float
    repeats: int = 20
    warmup: int = 5
    dtype_name: str = "float16"
    tile_multiple: int = 8
    max_device_mib: int = 1_024
    cpu_max_operations: int = MAX_REFERENCE_OPERATIONS

    def __post_init__(self) -> None:
        if type(self.size) is not int or not 2 <= self.size <= MAX_AXIS:
            raise ValueError(f"size must be an integer from 2 to {MAX_AXIS}")
        if type(self.density) is not float or not math.isfinite(self.density):
            raise ValueError("density must be a finite float")
        if not 0.0 < self.density <= 1.0:
            raise ValueError("density must be in (0, 1]")
        if type(self.repeats) is not int or not 1 <= self.repeats <= MAX_REPEATS:
            raise ValueError(f"repeats must be an integer from 1 to {MAX_REPEATS}")
        if type(self.warmup) is not int or not 0 <= self.warmup <= MAX_WARMUP:
            raise ValueError(f"warmup must be an integer from 0 to {MAX_WARMUP}")
        if self.dtype_name not in _SUPPORTED_DTYPES:
            raise ValueError(f"dtype_name must be one of {sorted(_SUPPORTED_DTYPES)}")
        if self.tile_multiple not in (8, 16):
            raise ValueError("tile_multiple must be 8 or 16")
        if (
            type(self.max_device_mib) is not int
            or not 64 <= self.max_device_mib <= MAX_DEVICE_MIB
        ):
            raise ValueError(
                f"max_device_mib must be an integer from 64 to {MAX_DEVICE_MIB}"
            )
        if (
            type(self.cpu_max_operations) is not int
            or not 0 <= self.cpu_max_operations <= MAX_REFERENCE_OPERATIONS
        ):
            raise ValueError(
                "cpu_max_operations must be a bounded non-negative integer"
            )
        width = _row_width(self.size, self.density)
        if self.size * width > MAX_BLOCK_ENTRIES:
            raise ValueError(
                "input relation exceeds TypedRelationBlock entry limit; "
                f"size={self.size}, row_width={width}, entries={self.size * width}"
            )


@dataclass(frozen=True)
class _GpuExecution:
    block: TypedRelationBlock[bool]
    pack_to_device_ms: float
    kernel_ms: tuple[float, ...]
    readback_and_canonicalize_ms: float
    peak_device_bytes: int
    output_entries: int


def _row_width(size: int, density: float) -> int:
    return max(1, min(size, int(round(size * density))))


def _padded(value: int, multiple: int) -> int:
    return ((value + multiple - 1) // multiple) * multiple


def _dtype_bytes(dtype_name: str) -> int:
    if dtype_name not in _SUPPORTED_DTYPES:
        raise ValueError(f"unsupported dtype {dtype_name!r}")
    return 2


def estimate_dense_device_bytes(case: ProbeCase) -> int:
    """Conservative explicit allocation estimate before CUDA admission.

    The dense resident set is two inputs, one GEMM output, and one Boolean
    support mask. Packing one CSR block also creates int64 row and column index
    tensors; the two inputs are packed sequentially, so only one such pair is
    counted at peak. cuBLAS workspace is implementation-owned and cannot be
    predicted here, which is why admission additionally reserves half of free
    VRAM as headroom and runtime OOM is converted to a blocked measurement.
    """

    padded = _padded(case.size, case.tile_multiple)
    cells = padded * padded
    dense_bytes = cells * (3 * _dtype_bytes(case.dtype_name) + 1)
    input_entries = case.size * _row_width(case.size, case.density)
    scatter_index_bytes = input_entries * 2 * _INT64_BYTES
    return dense_bytes + scatter_index_bytes


def _coprime_step(size: int, salt: int) -> int:
    step = (2 * salt + 1) % size
    if step == 0:
        step = 1
    while math.gcd(step, size) != 1:
        step = (step + 2) % size
        if step == 0:
            step = 1
    return step


def _relation_coordinates(
    labels: tuple[str, ...],
    *,
    row_width: int,
    salt: int,
) -> tuple[tuple[str, str, bool], ...]:
    size = len(labels)
    step = _coprime_step(size, salt)
    coordinates: list[tuple[str, str, bool]] = []
    for row in range(size):
        base = (row * (2 * salt + 17) + salt) % size
        for offset in range(row_width):
            column = (base + offset * step) % size
            coordinates.append((labels[row], labels[column], True))
    return tuple(coordinates)


def build_boolean_case(
    case: ProbeCase,
) -> tuple[TypedRelationBlock[bool], TypedRelationBlock[bool], dict[str, Any]]:
    """Build two exact typed relations with one shared middle axis."""

    labels = tuple(f"node-{index:05d}" for index in range(case.size))
    source_axis = TypedAxis("source-nodes", "code", labels)
    middle_axis = TypedAxis("middle-nodes", "code", labels)
    target_axis = TypedAxis("target-nodes", "code", labels)
    subject = ProjectionSubject(
        repository_id="KTY137/daedalus",
        source_revision="a" * 40,
        source_fourfold_sha256=hashlib.sha256(
            f"cuda-probe:{case.size}:{case.density:.12g}".encode("utf-8")
        ).hexdigest(),
    )
    row_width = _row_width(case.size, case.density)
    boolean = BooleanSemiring()
    left = TypedRelationBlock.from_coordinates(
        subject=subject,
        signature=RelationSignature("code", "cuda_probe_left", "code"),
        row_axis=source_axis,
        column_axis=middle_axis,
        coordinates=_relation_coordinates(labels, row_width=row_width, salt=19),
        semiring=boolean,
    )
    right = TypedRelationBlock.from_coordinates(
        subject=subject,
        signature=RelationSignature("code", "cuda_probe_right", "code"),
        row_axis=middle_axis,
        column_axis=target_axis,
        coordinates=_relation_coordinates(labels, row_width=row_width, salt=43),
        semiring=boolean,
    )
    return left, right, {
        "requested_density": case.density,
        "actual_density": row_width / case.size,
        "row_width": row_width,
        "left_entries": left.entry_count,
        "right_entries": right.entry_count,
    }


def exact_reference_operation_count(
    left: TypedRelationBlock[bool],
    right: TypedRelationBlock[bool],
) -> int:
    if left.column_axis != right.row_axis:
        raise ValueError("operation count requires an exactly shared middle axis")
    return sum(
        right.row_offsets[middle + 1] - right.row_offsets[middle]
        for middle in left.column_indices
    )


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
    admitted = min(case.max_device_mib * _MIB, free_device_bytes // 2)
    if estimated > admitted:
        raise ProbeBlocked(
            "device-memory-bound",
            f"estimated {estimated} bytes exceeds admitted {admitted} bytes",
        )

    device = f"cuda:{device_index}"
    dtype = _torch_dtype(torch, case.dtype_name)
    padded_size = _padded(case.size, case.tile_multiple)
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

    product = None
    with torch.inference_mode():
        for _ in range(case.warmup):
            product = torch.matmul(left_dense, right_dense)
        torch.cuda.synchronize(device_index)

        kernel_ms: list[float] = []
        for _ in range(case.repeats):
            start_event = torch.cuda.Event(enable_timing=True)
            end_event = torch.cuda.Event(enable_timing=True)
            start_event.record()
            product = torch.matmul(left_dense, right_dense)
            end_event.record()
            torch.cuda.synchronize(device_index)
            kernel_ms.append(float(start_event.elapsed_time(end_event)))

    assert product is not None
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
        kernel_ms=tuple(kernel_ms),
        readback_and_canonicalize_ms=readback_ms,
        peak_device_bytes=peak_bytes,
        output_entries=block.entry_count,
    )


def _same_support(
    left: TypedRelationBlock[bool],
    right: TypedRelationBlock[bool],
) -> bool:
    return (
        left.subject == right.subject
        and left.row_axis == right.row_axis
        and left.column_axis == right.column_axis
        and tuple(left.iter_entries()) == tuple(right.iter_entries())
    )


def _ratio(numerator: float | None, denominator: float) -> float | None:
    if numerator is None or denominator <= 0.0:
        return None
    return numerator / denominator


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
        + kernel_median
        + gpu.readback_and_canonicalize_ms
    )
    support_equal = None if cpu_block is None else _same_support(cpu_block, gpu.block)
    if support_equal is False:
        raise AssertionError("CUDA Boolean support differs from the stdlib CSR oracle")

    return {
        "status": "verified" if support_equal is True else "performance-only",
        "claim": "none",
        "case": {
            "size": case.size,
            "dtype": case.dtype_name,
            "tile_multiple": case.tile_multiple,
            "padded_size": _padded(case.size, case.tile_multiple),
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
            "cpu_over_resident_gpu_kernel": _ratio(cpu_ms, kernel_median),
            "cpu_over_gpu_one_shot": _ratio(cpu_ms, end_to_end_ms),
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
    if not cases:
        raise ValueError("at least one probe case is required")
    if len(cases) > 32:
        raise ValueError("at most 32 probe cases are allowed")
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


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


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
    parser.add_argument("--dtype", choices=sorted(_SUPPORTED_DTYPES), default="float16")
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
