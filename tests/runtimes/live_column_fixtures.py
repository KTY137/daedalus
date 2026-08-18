"""Shared construction of a ``live-runtime`` conformance bundle for tests.

These bundles are *live-shaped*, not live: nothing here observed a real provider
against the conformance checks. That is exactly what the tests need and exactly
what a real run must not accept -- so the shape is built here, in test code that
declares itself, while the collector and the probes keep refusing to synthesize
live evidence of their own.

The provider binary is a real file on disk with real bytes, because the drift
probe measures it and mutates a copy of it. Only the conformance *observations*
are fabricated.
"""
from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from daedalus.kernel.runtime_conformance import (
    RecordedObservation,
    assemble_recorded_conformance,
)
from daedalus.runtimes.profiles import (
    RuntimeConformanceEnvelope,
    RuntimeProbeIdentity,
    bind_conformance_envelope,
    build_probe_identity,
    load_runtime_profiles,
    materialize_runtime_manifest,
)
from daedalus.schemas import (
    RUNTIME_CONFORMANCE_CHECKS,
    RuntimeConformanceReceipt,
    RuntimeManifest,
)

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "configs" / "runtimes" / "gate0-runtime-profiles-v1.json"

REVISION = "b" * 40
NOW = datetime(2026, 8, 18, 6, 0, tzinfo=timezone.utc)
RUNTIME_ID = "ollama_http"


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class LiveBundleFixture:
    """Everything a live probe needs, plus the on-disk layout it reads."""

    bundle_dir: Path
    provider_binary: Path
    manifest: RuntimeManifest
    identity: RuntimeProbeIdentity
    receipt: RuntimeConformanceReceipt
    envelope: RuntimeConformanceEnvelope

    @property
    def finished_at(self) -> datetime:
        return datetime.fromisoformat(
            self.receipt.finished_at.replace("Z", "+00:00")
        ).astimezone(timezone.utc)


def build_live_bundle(
    tmp_path: Path,
    *,
    authority: str = "live-runtime",
    revision: str = REVISION,
    now: datetime = NOW,
    runtime_id: str = RUNTIME_ID,
    all_checks_pass: bool = True,
    write: bool = True,
) -> LiveBundleFixture:
    """Build one complete conformance bundle and lay it out on disk."""

    tmp_path.mkdir(parents=True, exist_ok=True)
    provider_binary = tmp_path / "provider-binary.bin"
    provider_binary.write_bytes(b"daedalus-test-provider-image\x00" + revision.encode())
    executable_sha = hashlib.sha256(provider_binary.read_bytes()).hexdigest()

    profile = load_runtime_profiles(CATALOG)[runtime_id]
    adapter_sha = _digest(f"adapter/{runtime_id}")
    environment_sha = _digest(f"environment/{runtime_id}")
    fixture_sha = _digest(f"fixture-suite/{runtime_id}")

    manifest = materialize_runtime_manifest(
        profile,
        runtime_version=f"live-contract/{runtime_id}",
        adapter_version=f"source/{adapter_sha[:16]}",
        source_revision=revision,
        adapter_sha256=adapter_sha,
        executable_sha256=executable_sha,
        environment_sha256=environment_sha,
        fixture_suite_sha256=fixture_sha,
        created_at=now.isoformat(),
    )
    identity = build_probe_identity(
        profile,
        manifest,
        probe_id=f"{runtime_id}-{authority}",
        authority=authority,
        adapter_sha256=adapter_sha,
        executable_sha256=executable_sha,
        environment_sha256=environment_sha,
        fixture_suite_sha256=fixture_sha,
        collected_at=now.isoformat(),
    )
    observations = {
        name: RecordedObservation(
            passed=all_checks_pass or name != "workspace-isolation",
            detail=f"{name} observed against the runtime",
            transcript={
                "schema": "daedalus-live-runtime-observation/1",
                "check": name,
                "probe_identity_sha256": identity.digest,
            },
        )
        for name in RUNTIME_CONFORMANCE_CHECKS
    }
    receipt = assemble_recorded_conformance(
        manifest,
        observations=observations,
        artifact_root=tmp_path / "cas",
        receipt_id=f"{runtime_id}-live-receipt",
        started_at=now.isoformat(),
        finished_at=(now + timedelta(seconds=1)).isoformat(),
        trace_id=identity.probe_id,
    )
    receipt = dataclasses.replace(
        receipt,
        provenance=dataclasses.replace(
            receipt.provenance,
            input_digests=tuple(
                sorted({*receipt.provenance.input_digests, identity.digest})
            ),
        ),
    )
    envelope = bind_conformance_envelope(
        manifest,
        identity,
        receipt,
        envelope_id=f"{runtime_id}-live-envelope",
        created_at=(now + timedelta(seconds=1)).isoformat(),
    )

    bundle_dir = tmp_path / "live-bundle"
    if write:
        bundle_dir.mkdir(parents=True, exist_ok=True)
        stem = runtime_id
        (bundle_dir / f"{stem}-envelope.json").write_text(
            envelope.to_json(), encoding="utf-8"
        )
        (bundle_dir / f"{stem}-probe-identity.json").write_text(
            identity.to_json(), encoding="utf-8"
        )
        (bundle_dir / f"{stem}-receipt.json").write_text(
            receipt.to_json(), encoding="utf-8"
        )
        (bundle_dir / f"{stem}-manifest.json").write_text(
            manifest.to_json(), encoding="utf-8"
        )
    return LiveBundleFixture(
        bundle_dir=bundle_dir,
        provider_binary=provider_binary,
        manifest=manifest,
        identity=identity,
        receipt=receipt,
        envelope=envelope,
    )
