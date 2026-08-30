# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

from daedalus.gates.provider_observation_persistence_inventory import (
    scan_provider_observation_persistence,
)


ROOT = Path(__file__).resolve().parents[2]


def test_same_source_bytes_cannot_reuse_report_digest_across_revisions() -> None:
    first = scan_provider_observation_persistence(
        ROOT,
        source_revision="1" * 40,
    )
    stale = scan_provider_observation_persistence(
        ROOT,
        source_revision="2" * 40,
    )
    assert stale.source_sha256 == first.source_sha256
    assert stale.surfaces == first.surfaces
    assert stale.source_revision != first.source_revision
    assert stale.digest != first.digest
