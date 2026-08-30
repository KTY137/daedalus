# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import dataclasses
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from daedalus.runtimes import (
    RuntimeConformanceEnvelope,
    RuntimeProfile,
    build_probe_identity,
    load_runtime_profiles,
    materialize_runtime_manifest,
)

ROOT = Path(__file__).resolve().parents[2]
CATALOG = ROOT / "configs" / "runtimes" / "gate0-runtime-profiles-v1.json"
REVISION = "8" * 40
NOW = datetime(2026, 8, 3, 1, 0, tzinfo=timezone.utc)
DIGESTS = {
    "adapter": "1" * 64,
    "executable": "2" * 64,
    "environment": "3" * 64,
    "fixture": "4" * 64,
}


def _manifest(profile: RuntimeProfile):
    return materialize_runtime_manifest(
        profile,
        runtime_version="fixture-1",
        adapter_version="adapter-1",
        source_revision=REVISION,
        adapter_sha256=DIGESTS["adapter"],
        executable_sha256=DIGESTS["executable"],
        environment_sha256=DIGESTS["environment"],
        fixture_suite_sha256=DIGESTS["fixture"],
        created_at=NOW.isoformat(),
    )


def test_string_repacked_as_sequence_is_refused(tmp_path: Path) -> None:
    payload = json.loads(CATALOG.read_text(encoding="utf-8"))
    payload["profiles"][0]["declared_tools"] = "read_file"
    path = tmp_path / "string-sequence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="sequence, not a string"):
        load_runtime_profiles(path)


def test_probe_components_must_already_be_bound_by_manifest_provenance() -> None:
    profile = load_runtime_profiles(CATALOG)["claude_code_cli"]
    manifest = _manifest(profile)
    weakened = dataclasses.replace(
        manifest,
        provenance=dataclasses.replace(
            manifest.provenance,
            input_digests=tuple(
                digest
                for digest in manifest.provenance.input_digests
                if digest != DIGESTS["adapter"]
            ),
        ),
    )
    with pytest.raises(ValueError, match="does not bind probe component"):
        build_probe_identity(
            profile,
            weakened,
            probe_id="weakened-probe",
            authority="offline-fixture",
            adapter_sha256=DIGESTS["adapter"],
            executable_sha256=DIGESTS["executable"],
            environment_sha256=DIGESTS["environment"],
            fixture_suite_sha256=DIGESTS["fixture"],
            collected_at=NOW.isoformat(),
        )


def test_probe_and_envelope_timestamp_repackaging_is_refused() -> None:
    profile = load_runtime_profiles(CATALOG)["codex_cli"]
    manifest = _manifest(profile)
    identity = build_probe_identity(
        profile,
        manifest,
        probe_id="timestamp-probe",
        authority="offline-fixture",
        adapter_sha256=DIGESTS["adapter"],
        executable_sha256=DIGESTS["executable"],
        environment_sha256=DIGESTS["environment"],
        fixture_suite_sha256=DIGESTS["fixture"],
        collected_at=NOW.isoformat(),
    )
    with pytest.raises(ValueError, match="collected_at contradicts"):
        dataclasses.replace(
            identity,
            collected_at=(NOW + timedelta(seconds=1)).isoformat(),
        )

    envelope = RuntimeConformanceEnvelope(
        envelope_id="timestamp-envelope",
        runtime_id=profile.runtime_id,
        authority="offline-fixture",
        status="passed",
        runtime_manifest_sha256=manifest.digest,
        probe_identity_sha256=identity.digest,
        conformance_receipt_sha256="5" * 64,
        source_revision=REVISION,
        created_at=NOW.isoformat(),
        provenance=dataclasses.replace(
            identity.provenance,
            origin="runtimes.conformance-envelope",
            input_digests=(manifest.digest, identity.digest, "5" * 64),
            trace_id="timestamp-envelope",
        ),
    )
    with pytest.raises(ValueError, match="created_at contradicts"):
        dataclasses.replace(
            envelope,
            created_at=(NOW + timedelta(seconds=1)).isoformat(),
        )
