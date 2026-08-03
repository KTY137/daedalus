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

_SUPPORT_PATH = Path(__file__).with_name("release_support.py")
_SPEC = importlib.util.spec_from_file_location("_release_support_verifier", _SUPPORT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SUPPORT)


def verification(root: Path) -> dict[str, object]:
    values = _SUPPORT.assembly_arguments(root)
    values.pop("release_id")
    values["now"] = _SUPPORT.NOW + timedelta(minutes=3)
    return values


def test_retained_closed_release_requires_independent_reconstruction(tmp_path: Path) -> None:
    root = _SUPPORT.repo_root(tmp_path)
    report = _SUPPORT.local_report()
    index = _SUPPORT.evidence_index(report)
    bundle = _SUPPORT.trust_bundle(index, root)
    release = _SUPPORT.assemble(report, index, bundle, root)

    assert gate0_release_verification_blockers(
        release,
        report,
        index,
        bundle,
        **verification(root),
    ) == ()
    assert_gate0_release_report(
        release,
        report,
        index,
        bundle,
        **verification(root),
    )


def test_valid_but_open_release_retains_current_blockers(tmp_path: Path) -> None:
    root = _SUPPORT.repo_root(tmp_path)
    report = _SUPPORT.local_report()
    index = _SUPPORT.evidence_index(report, owner_present=False)
    bundle = _SUPPORT.trust_bundle(index, root)
    release = _SUPPORT.assemble(report, index, bundle, root)

    blockers = gate0_release_verification_blockers(
        release,
        report,
        index,
        bundle,
        **verification(root),
    )
    assert blockers == ("owner-decision:missing",)
    with pytest.raises(ValueError, match="owner-decision:missing"):
        assert_gate0_release_report(
            release,
            report,
            index,
            bundle,
            **verification(root),
        )


def test_directly_repacked_release_contract_is_not_authoritative(tmp_path: Path) -> None:
    root = _SUPPORT.repo_root(tmp_path)
    report = _SUPPORT.local_report()
    index = _SUPPORT.evidence_index(report)
    bundle = _SUPPORT.trust_bundle(index, root)
    release = _SUPPORT.assemble(report, index, bundle, root)
    repacked = dataclasses.replace(
        release,
        exact_head_blockers=("invented-release-blocker",),
    )

    blockers = gate0_release_verification_blockers(
        repacked,
        report,
        index,
        bundle,
        **verification(root),
    )
    assert "release:projection-mismatch" in blockers
    with pytest.raises(ValueError, match="projection-mismatch"):
        assert_gate0_release_report(
            repacked,
            report,
            index,
            bundle,
            **verification(root),
        )


def test_bundle_expiry_or_workflow_drift_invalidates_retained_release(tmp_path: Path) -> None:
    root = _SUPPORT.repo_root(tmp_path)
    report = _SUPPORT.local_report()
    index = _SUPPORT.evidence_index(report)
    bundle = _SUPPORT.trust_bundle(index, root)
    release = _SUPPORT.assemble(report, index, bundle, root)

    expired = verification(root)
    expired["now"] = _SUPPORT.NOW + timedelta(hours=3)
    blockers = gate0_release_verification_blockers(
        release,
        report,
        index,
        bundle,
        **expired,
    )
    assert "release:trust-bundle-binding" in blockers
    assert "release:no-longer-current" in blockers

    workflow = root / _SUPPORT.WORKFLOW_PATH
    workflow.write_text("name: changed\non: [push]\njobs: {}\n", encoding="utf-8")
    blockers = gate0_release_verification_blockers(
        release,
        report,
        index,
        bundle,
        **verification(root),
    )
    assert "release:trust-bundle-binding" in blockers
    assert "release:projection-unverifiable" in blockers
    assert "release:no-longer-current" in blockers


def test_substituted_report_index_or_bundle_is_refused(tmp_path: Path) -> None:
    root = _SUPPORT.repo_root(tmp_path)
    report = _SUPPORT.local_report()
    index = _SUPPORT.evidence_index(report)
    bundle = _SUPPORT.trust_bundle(index, root)
    release = _SUPPORT.assemble(report, index, bundle, root)

    substituted_report = _SUPPORT.local_report(diagnostics=("substituted",))
    blockers = gate0_release_verification_blockers(
        release,
        substituted_report,
        index,
        bundle,
        **verification(root),
    )
    assert "release:mechanical-report-mismatch" in blockers
    assert "release:projection-mismatch" in blockers

    changed_bundle = dataclasses.replace(bundle, signature_sha256="f" * 64)
    blockers = gate0_release_verification_blockers(
        release,
        report,
        index,
        changed_bundle,
        **verification(root),
    )
    assert "release:trust-bundle-mismatch" in blockers
    assert "release:trust-bundle-signature" in blockers


def test_verifier_refuses_naive_current_time(tmp_path: Path) -> None:
    root = _SUPPORT.repo_root(tmp_path)
    report = _SUPPORT.local_report()
    index = _SUPPORT.evidence_index(report)
    bundle = _SUPPORT.trust_bundle(index, root)
    release = _SUPPORT.assemble(report, index, bundle, root)
    arguments = verification(root)
    arguments["now"] = datetime(2026, 8, 3, 12, 3)

    with pytest.raises(ValueError, match="timezone"):
        gate0_release_verification_blockers(
            release,
            report,
            index,
            bundle,
            **arguments,
        )
