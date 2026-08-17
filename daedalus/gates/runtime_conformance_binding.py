"""Bind runtime-conformance receipts into the Gate-0 report, or say why not.

The canonical producer of a :class:`RuntimeConformanceReceipt` is
``daedalus.kernel.runtime_conformance.assemble_recorded_conformance``.  At this
revision that producer is exercised only in-process (tests and the fixture CI
job) and the trust ledger retains nothing but each receipt's digest, so no
persisted receipt bundle exists that a report could cite at a source revision.

This module therefore does two things and refuses to invent a third.  It binds
receipts when a caller actually has them — in memory or as a persisted bundle
directory — and it verifies more than the old placeholder did: the status, the
uniqueness of receipt ids, and revision atomicity against the report's own
revision.  When there are none it emits a blocker naming the exact missing link
rather than a placeholder, so the gap is legible instead of merely unbound.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from daedalus.schemas import RuntimeConformanceReceipt


CANONICAL_PRODUCER = (
    "daedalus.kernel.runtime_conformance.assemble_recorded_conformance"
)
UNBOUND_ROW = "runtime-conformance-receipts:unbound:no-persisted-receipt-bundle"
_MAX_RECEIPT_BYTES = 4 * 1024 * 1024
_SAFE_TEXT = re.compile(r"[^A-Za-z0-9._:/@=-]+")


def _safe(value: object, *, maximum: int = 200) -> str:
    text = _SAFE_TEXT.sub("-", str(value)).strip("-")
    return (text or "unspecified")[:maximum]


@dataclass(frozen=True)
class RuntimeConformanceBinding:
    """What the gate report may say about runtime-conformance evidence."""

    bound: bool
    failures: tuple[str, ...]
    diagnostics: tuple[str, ...]
    receipt_sha256s: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "failures", tuple(sorted(set(self.failures))))
        object.__setattr__(self, "diagnostics", tuple(sorted(set(self.diagnostics))))
        object.__setattr__(self, "receipt_sha256s", tuple(sorted(set(self.receipt_sha256s))))
        if self.bound and not self.receipt_sha256s:
            raise ValueError("a bound conformance binding must cite at least one receipt")


def _load_bundle(
    directory: Path,
) -> tuple[tuple[RuntimeConformanceReceipt, ...], tuple[str, ...]]:
    if not directory.is_dir():
        return (), ("receipt-bundle:absent",)
    receipts: list[RuntimeConformanceReceipt] = []
    failures: list[str] = []
    for path in sorted(directory.glob("*.json")):
        try:
            raw = path.read_bytes()
        except OSError:
            failures.append(f"receipt-bundle:unreadable:{_safe(path.name)}")
            continue
        if len(raw) > _MAX_RECEIPT_BYTES:
            failures.append(f"receipt-bundle:oversized:{_safe(path.name)}")
            continue
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            failures.append(f"receipt-bundle:malformed:{_safe(path.name)}")
            continue
        if not isinstance(payload, dict):
            failures.append(f"receipt-bundle:malformed:{_safe(path.name)}")
            continue
        try:
            receipts.append(RuntimeConformanceReceipt.from_dict(payload))
        except (TypeError, ValueError):
            failures.append(f"receipt-bundle:not-a-conformance-receipt:{_safe(path.name)}")
    return tuple(receipts), tuple(failures)


def bind_runtime_conformance_receipts(
    receipts: Sequence[RuntimeConformanceReceipt] = (),
    *,
    source_revision: str,
    receipt_dir: str | Path | None = None,
) -> RuntimeConformanceBinding:
    """Bind conformance receipts, or emit a blocker naming the exact missing link."""

    rows = tuple(receipts)
    if any(not isinstance(row, RuntimeConformanceReceipt) for row in rows):
        raise ValueError("runtime conformance binding requires exact receipts")

    bundle_failures: tuple[str, ...] = ()
    if receipt_dir is not None:
        loaded, bundle_failures = _load_bundle(Path(receipt_dir))
        rows = rows + loaded

    if not rows:
        return RuntimeConformanceBinding(
            bound=False,
            failures=(UNBOUND_ROW, *bundle_failures),
            diagnostics=(
                "blocker:runtime_conformance_receipts:unbound",
                f"info:runtime_conformance.canonical_producer:{CANONICAL_PRODUCER}",
                "info:runtime_conformance.gap:"
                "the-producer-runs-in-process-and-persists-no-receipt-artifact",
            ),
        )

    failures = list(bundle_failures)
    receipt_ids = [receipt.receipt_id for receipt in rows]
    for receipt_id in sorted({name for name in receipt_ids if receipt_ids.count(name) > 1}):
        failures.append(f"{_safe(receipt_id)}:duplicate-receipt-id")
    for receipt in rows:
        if receipt.status != "passed":
            failures.append(f"{receipt.receipt_id}:{receipt.status}")
        if receipt.source_revision != source_revision:
            failures.append(
                f"{receipt.receipt_id}:stale-revision:{_safe(receipt.source_revision)}"
            )
    diagnostics = [
        f"info:runtime_conformance.canonical_producer:{CANONICAL_PRODUCER}",
        f"info:runtime_conformance.receipts:{len(rows)}",
    ]
    return RuntimeConformanceBinding(
        bound=True,
        failures=tuple(failures),
        diagnostics=tuple(diagnostics),
        receipt_sha256s=tuple(receipt.digest for receipt in rows),
    )


__all__ = [
    "CANONICAL_PRODUCER",
    "RuntimeConformanceBinding",
    "UNBOUND_ROW",
    "bind_runtime_conformance_receipts",
]
