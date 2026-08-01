"""Content-addressed offline runtime-conformance evidence.

This harness does not trust a runtime manifest's declarations. A caller must
supply one recorded observation for every vendor-neutral fixture check. The
observations are stored as immutable content-addressed artifacts and assembled
into the canonical RuntimeConformanceReceipt contract.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from daedalus.schemas import (
    RUNTIME_CONFORMANCE_CHECKS,
    ConformanceCheck,
    ContractProvenance,
    ResourceUsage,
    RuntimeConformanceReceipt,
    RuntimeManifest,
)
from daedalus.spine.envelope import canonical_json, canonical_sha


class RuntimeConformanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class RecordedObservation:
    passed: bool
    detail: str
    transcript: Mapping[str, object]

    def __post_init__(self) -> None:
        if not isinstance(self.passed, bool):
            raise ValueError("recorded observation passed must be boolean")
        if len(self.detail) > 2000:
            raise ValueError("recorded observation detail is too long")
        # Canonicalization is the validation boundary for retained JSON.
        canonical_json(dict(self.transcript))


def _store_artifact(root: Path, payload: Mapping[str, object]) -> tuple[str, str]:
    raw = canonical_json(dict(payload)).encode("utf-8")
    digest = canonical_sha(dict(payload))
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{digest}.json"
    if path.exists():
        if path.read_bytes() != raw:
            raise RuntimeConformanceError("content-addressed evidence collision")
    else:
        path.write_bytes(raw)
    return digest, f"artifact-locator:sha256:{digest}"


def assemble_recorded_conformance(
    manifest: RuntimeManifest,
    *,
    observations: Mapping[str, RecordedObservation],
    artifact_root: str | Path,
    receipt_id: str,
    started_at: str,
    finished_at: str,
    usage: ResourceUsage | None = None,
    trace_id: str | None = None,
) -> RuntimeConformanceReceipt:
    """Assemble an exact, content-addressed offline fixture receipt."""
    names = set(observations)
    if names != set(RUNTIME_CONFORMANCE_CHECKS):
        missing = sorted(set(RUNTIME_CONFORMANCE_CHECKS) - names)
        extra = sorted(names - set(RUNTIME_CONFORMANCE_CHECKS))
        raise RuntimeConformanceError(
            f"observations must exactly cover runtime fixture checks (missing={missing}, extra={extra})"
        )
    root = Path(artifact_root).resolve()
    checks: list[ConformanceCheck] = []
    for name in sorted(RUNTIME_CONFORMANCE_CHECKS):
        observation = observations[name]
        payload = {
            "schema": "daedalus-runtime-observation/1",
            "runtime_manifest_sha256": manifest.digest,
            "source_revision": manifest.source_revision,
            "check": name,
            "passed": observation.passed,
            "detail": observation.detail,
            "transcript": dict(observation.transcript),
        }
        digest, locator = _store_artifact(root, payload)
        checks.append(
            ConformanceCheck(
                name=name,
                passed=observation.passed,
                evidence_sha256=digest,
                evidence_locator=locator,
                detail=observation.detail,
            )
        )
    inputs = (
        manifest.digest,
        *(check.evidence_sha256 for check in checks),
        *(check.evidence_locator.rsplit(":", 1)[-1] for check in checks),
    )
    return RuntimeConformanceReceipt(
        receipt_id=receipt_id,
        runtime_manifest_sha256=manifest.digest,
        source_revision=manifest.source_revision,
        status="passed" if all(check.passed for check in checks) else "failed",
        checks=tuple(checks),
        started_at=started_at,
        finished_at=finished_at,
        usage=usage or ResourceUsage(),
        provenance=ContractProvenance(
            origin="kernel.runtime-conformance.recorded",
            source_revision=manifest.source_revision,
            created_at=finished_at,
            input_digests=tuple(sorted(set(inputs))),
            trace_id=trace_id,
        ),
    )


def verify_current_conformance(
    receipt: RuntimeConformanceReceipt,
    manifest: RuntimeManifest,
    *,
    now: datetime,
    max_age: timedelta = timedelta(days=7),
) -> None:
    """Reject failed, stale, future or differently bound runtime evidence."""
    if receipt.runtime_manifest_sha256 != manifest.digest:
        raise RuntimeConformanceError("runtime conformance binds another manifest")
    if receipt.source_revision != manifest.source_revision:
        raise RuntimeConformanceError("runtime conformance binds another source revision")
    if receipt.status != "passed":
        raise RuntimeConformanceError("runtime conformance did not pass")
    instant = now.astimezone(timezone.utc)
    finished = datetime.fromisoformat(receipt.finished_at.replace("Z", "+00:00")).astimezone(timezone.utc)
    if finished > instant:
        raise RuntimeConformanceError("runtime conformance is from the future")
    if instant - finished > max_age:
        raise RuntimeConformanceError("runtime conformance receipt is stale")


__all__ = [
    "RecordedObservation",
    "RuntimeConformanceError",
    "assemble_recorded_conformance",
    "verify_current_conformance",
]
