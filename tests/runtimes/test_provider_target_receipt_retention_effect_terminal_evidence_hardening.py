# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import dataclasses
import os
import runpy
from pathlib import Path

import pytest

import daedalus.runtimes.provider_target_receipt_retention_effect_terminal_evidence as terminal_module
from daedalus.kernel.effect_replay import EffectExecutionReplaySnapshot
from daedalus.runtimes.provider_target_receipt_retention_effect_terminal_evidence import (
    ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError,
)


_HELPERS = runpy.run_path(
    str(
        Path(__file__).with_name(
            "test_provider_target_receipt_retention_effect_terminal_evidence.py"
        )
    )
)
_subjects = _HELPERS["_subjects"]
_completed = _HELPERS["_completed"]
_snapshot = _HELPERS["_snapshot"]
_verify = _HELPERS["_verify"]


def test_effect_terminal_evidence_refuses_completed_evidence_mutation_window(
    tmp_path,
    monkeypatch,
) -> None:
    subjects = _subjects(tmp_path)
    completed = _completed(subjects)
    snapshot = _snapshot(subjects, completed)
    calls = 0

    def mutating_read(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            object.__setattr__(completed, "admission_sha256", "f" * 64)
        return snapshot

    monkeypatch.setattr(
        terminal_module,
        "inspect_effect_execution",
        mutating_read,
    )
    with pytest.raises(
        ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError,
        match="completed evidence or Effect authority changed",
    ):
        _verify(subjects, completed)


def test_effect_terminal_evidence_refuses_authority_mutation_window(
    tmp_path,
    monkeypatch,
) -> None:
    subjects = _subjects(tmp_path)
    completed = _completed(subjects)
    snapshot = _snapshot(subjects, completed)
    calls = 0

    def mutating_read(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            object.__setattr__(
                subjects.authorization.effect_ledger,
                "path",
                tmp_path / "replacement-effect-leases.sqlite3",
            )
            subjects.authorization.effect_ledger.path.write_bytes(b"replacement")
        return snapshot

    monkeypatch.setattr(
        terminal_module,
        "inspect_effect_execution",
        mutating_read,
    )
    with pytest.raises(
        ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError,
        match="completed evidence or Effect authority changed",
    ):
        _verify(subjects, completed)


def test_effect_terminal_evidence_refuses_symlinked_effect_store(
    tmp_path,
    monkeypatch,
) -> None:
    subjects = _subjects(tmp_path)
    completed = _completed(subjects)
    snapshot = _snapshot(subjects, completed)
    alias = tmp_path / "effect-store-link.sqlite3"
    try:
        alias.symlink_to(subjects.effect_store)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks are unavailable on this platform")
    object.__setattr__(subjects.authorization.effect_ledger, "path", alias)
    monkeypatch.setattr(
        terminal_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: snapshot,
    )

    with pytest.raises(
        ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError,
        match="must not contain symlinks",
    ):
        _verify(subjects, completed)


def test_effect_terminal_evidence_refuses_duplicate_terminal_outputs(
    tmp_path,
    monkeypatch,
) -> None:
    subjects = _subjects(tmp_path)
    completed = _completed(subjects)
    snapshot = _snapshot(subjects, completed)
    duplicate = dataclasses.replace(
        snapshot.terminal_receipt,
        output_digests=(
            completed.receipt_artifact_sha256,
            completed.receipt_artifact_sha256,
        ),
    )
    malformed = EffectExecutionReplaySnapshot(
        snapshot.start_receipt,
        "COMPLETED",
        duplicate,
    )
    monkeypatch.setattr(
        terminal_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: malformed,
    )

    with pytest.raises(
        ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError,
        match="not sorted and unique",
    ):
        _verify(subjects, completed)


def test_effect_terminal_evidence_refuses_terminal_before_start(
    tmp_path,
    monkeypatch,
) -> None:
    subjects = _subjects(tmp_path)
    completed = _completed(subjects)
    snapshot = _snapshot(
        subjects,
        completed,
        terminal_overrides={"finished_at": "2026-08-05T07:59:59.000000+00:00"},
    )
    monkeypatch.setattr(
        terminal_module,
        "inspect_effect_execution",
        lambda *args, **kwargs: snapshot,
    )

    with pytest.raises(
        ProviderTargetReceiptRetentionEffectTerminalEvidenceBindingError,
        match="precedes its start",
    ):
        _verify(subjects, completed)
