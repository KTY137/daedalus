# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import dataclasses
import runpy
from pathlib import Path

import pytest

from daedalus.runtimes.provider_target_receipt_retention_completed_evidence import (
    ProviderTargetReceiptRetentionCompletedEvidenceBindingError,
)
from daedalus.runtimes.provider_target_receipt_retention_recovery import (
    decide_provider_target_receipt_retention_recovery,
)


_HELPERS = runpy.run_path(
    str(
        Path(__file__).with_name(
            "test_provider_target_receipt_retention_completed_evidence.py"
        )
    )
)
_topology_race_fixture = _HELPERS["_topology_race_fixture"]
_verify = _HELPERS["_verify"]


def _recovery(admission, revision):
    return decide_provider_target_receipt_retention_recovery(
        admission,
        expected_source_revision=revision,
    )


def test_completed_evidence_refuses_foreign_event_store_admission_path(
    tmp_path,
) -> None:
    fixture, receipt, spine, ledger, admission, _ = _topology_race_fixture(
        tmp_path
    )
    foreign = tmp_path / "foreign-event-store.sqlite3"
    foreign.write_bytes(b"not-the-canonical-event-store")
    detached = dataclasses.replace(admission, event_store_path=str(foreign.resolve()))

    with pytest.raises(
        ProviderTargetReceiptRetentionCompletedEvidenceBindingError,
        match="event_store identity is detached",
    ):
        _verify(
            detached,
            _recovery(detached, receipt.source_revision),
            ledger,
            receipt,
            fixture,
        )
    spine.close()


def test_completed_evidence_refuses_foreign_primary_checkout_admission_path(
    tmp_path,
) -> None:
    fixture, receipt, spine, ledger, admission, _ = _topology_race_fixture(
        tmp_path
    )
    foreign = tmp_path / "foreign-primary"
    foreign.mkdir()
    detached = dataclasses.replace(
        admission,
        primary_checkout_path=str(foreign.resolve()),
    )

    with pytest.raises(
        ProviderTargetReceiptRetentionCompletedEvidenceBindingError,
        match="primary_checkout identity is detached",
    ):
        _verify(
            detached,
            _recovery(detached, receipt.source_revision),
            ledger,
            receipt,
            fixture,
        )
    spine.close()


def test_completed_evidence_refuses_retention_root_that_does_not_contain_stores(
    tmp_path,
) -> None:
    fixture, receipt, spine, ledger, admission, _ = _topology_race_fixture(
        tmp_path
    )
    foreign = tmp_path / "foreign-retention-root"
    foreign.mkdir()
    detached = dataclasses.replace(
        admission,
        retention_root_path=str(foreign.resolve()),
    )

    with pytest.raises(
        ProviderTargetReceiptRetentionCompletedEvidenceBindingError,
        match="does not contain Event Store and receipt CAS",
    ):
        _verify(
            detached,
            _recovery(detached, receipt.source_revision),
            ledger,
            receipt,
            fixture,
        )
    spine.close()


def test_completed_evidence_refuses_relative_admission_paths(tmp_path) -> None:
    fixture, receipt, spine, ledger, admission, _ = _topology_race_fixture(
        tmp_path
    )
    detached = dataclasses.replace(admission, event_store_path="relative.sqlite3")

    with pytest.raises(
        ProviderTargetReceiptRetentionCompletedEvidenceBindingError,
        match="not an absolute admission path",
    ):
        _verify(
            detached,
            _recovery(detached, receipt.source_revision),
            ledger,
            receipt,
            fixture,
        )
    spine.close()


def test_completed_evidence_receipt_exposes_topology_binding_claim(tmp_path) -> None:
    fixture, receipt, spine, ledger, admission, recovery = _topology_race_fixture(
        tmp_path
    )

    evidence = _verify(admission, recovery, ledger, receipt, fixture)

    assert evidence.to_dict()["admission_topology_bound"] is True
    spine.close()
