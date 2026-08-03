from __future__ import annotations

import dataclasses
import importlib.util
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from daedalus.gates import (
    assert_gate0_release_report,
    gate0_release_verification_blockers,
)

_SUPPORT_PATH = Path(__file__).with_name("test_gate0_release_assembly.py")
_SPEC = importlib.util.spec_from_file_location("_gate0_release_test_support", _SUPPORT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SUPPORT)


def verification(value):
    return {
        "current_revision": _SUPPORT.REVISION,
        "current_tree_revision": _SUPPORT.TREE,
        "now": _SUPPORT.NOW + timedelta(minutes=2),
        **_SUPPORT.trust_sets(value),
    }


def test_retained_closed_release_requires_successful_independent_reconstruction() -> None:
    report = _SUPPORT.local_report()
    index = _SUPPORT.evidence_index(report)
    release = _SUPPORT.assemble(report, index)

    assert gate0_release_verification_blockers(
        release,
        report,
        index,
        **verification(index),
    ) == ()
    assert_gate0_release_report(release, report, index, **verification(index))


def test_directly_repacked_release_contract_is_not_authoritative() -> None:
    report = _SUPPORT.local_report()
    index = _SUPPORT.evidence_index(report)
    release = _SUPPORT.assemble(report, index)
    repacked = dataclasses.replace(
        release,
        exact_head_blockers=("invented-release-blocker",),
    )

    blockers = gate0_release_verification_blockers(
        repacked,
        report,
        index,
        **verification(index),
    )
    assert "release:projection-mismatch" in blockers
    with pytest.raises(ValueError, match="projection-mismatch"):
        assert_gate0_release_report(repacked, report, index, **verification(index))


def test_release_is_rechecked_after_runtime_and_index_expiry() -> None:
    report = _SUPPORT.local_report()
    index = _SUPPORT.evidence_index(report)
    release = _SUPPORT.assemble(report, index)
    arguments = verification(index)
    arguments["now"] = _SUPPORT.NOW + timedelta(days=2)

    blockers = gate0_release_verification_blockers(
        release,
        report,
        index,
        **arguments,
    )
    assert "index:expired" in blockers
    assert "runtime:claude-code-cli:expired" in blockers
    assert "workflow:gate0-required:expired" in blockers
    assert "release:no-longer-current" in blockers


def test_substituted_mechanical_report_or_index_is_refused() -> None:
    report = _SUPPORT.local_report()
    index = _SUPPORT.evidence_index(report)
    release = _SUPPORT.assemble(report, index)
    substituted_report = _SUPPORT.local_report(
        diagnostics=("substituted",),
    )

    blockers = gate0_release_verification_blockers(
        release,
        substituted_report,
        index,
        **verification(index),
    )
    assert "release:mechanical-report-mismatch" in blockers
    assert "release:projection-mismatch" in blockers
    assert "assembly:gate-report-artifact-mismatch" in blockers


def test_verifier_refuses_naive_current_time() -> None:
    report = _SUPPORT.local_report()
    index = _SUPPORT.evidence_index(report)
    release = _SUPPORT.assemble(report, index)
    arguments = verification(index)
    arguments["now"] = datetime(2026, 8, 3, 10, 2)

    with pytest.raises(ValueError, match="timezone"):
        gate0_release_verification_blockers(
            release,
            report,
            index,
            **arguments,
        )
