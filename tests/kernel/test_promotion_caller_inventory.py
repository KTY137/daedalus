"""Inventory of everything that can reach the promotion boundary.

The sealed promotion path is currently armed but untriggered: no production
code calls ``promote_candidates``. That is a safe state and a fragile one --
code nobody executes can acquire a caller in a routine change, and the first
execution would then also be the first time its authorization was exercised.

These tests hold that line from both ends. The call-site inventory fails when
a production caller appears, forcing whoever adds it to say so out loud. The
refusal tests fail if a caller that supplies no authenticated capability ever
stops being refused.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[2] / "daedalus"
BOUNDARY = "promote_candidates"

# The single definition site. Anything else calling the boundary is a caller.
DEFINITION = PACKAGE / "kairos" / "gated_writes.py"

# Production callers that have been reviewed and proven to supply an
# authenticated, persisted capability. Adding a name here is a security
# review, not a bookkeeping change.
AUTHORIZED_PRODUCTION_CALLERS: frozenset[str] = frozenset()


def _call_sites() -> dict[str, list[int]]:
    """Every real call to the boundary in the package, found via the AST.

    Comments and docstrings mention ``promote_candidates`` in several modules;
    a text search would report those as callers. Only ``Call`` nodes count.
    """
    found: dict[str, list[int]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - defensive
            continue
        lines: list[int] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = (
                func.id
                if isinstance(func, ast.Name)
                else func.attr
                if isinstance(func, ast.Attribute)
                else None
            )
            if name == BOUNDARY:
                lines.append(node.lineno)
        if lines:
            found[str(path.relative_to(PACKAGE.parent).as_posix())] = lines
    return found


def test_no_unreviewed_production_caller_reaches_promotion() -> None:
    sites = _call_sites()
    sites.pop(str(DEFINITION.relative_to(PACKAGE.parent).as_posix()), None)
    unreviewed = sorted(set(sites) - AUTHORIZED_PRODUCTION_CALLERS)
    assert unreviewed == [], (
        "a production caller of the sealed promotion boundary appeared: "
        f"{ {name: sites[name] for name in unreviewed} }. "
        "Prove it supplies an authenticated persisted capability, then add it "
        "to AUTHORIZED_PRODUCTION_CALLERS."
    )


def test_the_boundary_is_still_armed_but_untriggered() -> None:
    """States the measured fact this file exists to protect."""
    assert AUTHORIZED_PRODUCTION_CALLERS == frozenset()


@pytest.fixture()
def boundary():
    from daedalus.kairos import gated_writes

    return gated_writes.promote_candidates


def _call(boundary, tmp_path, **changes):
    values = {
        "repo_root": str(tmp_path),
        "candidates": [],
        "project": None,
        "availability": {},
        "consumed_approval": None,
        "evidence_packet": None,
        "target_ref": "experimental",
    }
    values.update(changes)
    return boundary(**values)


def _is_refusal(report: dict) -> bool:
    return (
        report["promoted"] == []
        and report["integration_branch"] is None
        and report["authorization"] is None
        and len(report["refused"]) >= 1
    )


def test_caller_without_ledger_or_keyring_is_refused(boundary, tmp_path) -> None:
    report = _call(boundary, tmp_path)

    assert _is_refusal(report)
    assert "persisted ApprovalLedger and owner keyring are mandatory" in (
        report["refused"][0]["reason"]
    )


def test_caller_supplying_only_a_keyring_is_refused(boundary, tmp_path) -> None:
    report = _call(boundary, tmp_path, owner_keyring={("owner", "key"): b"x" * 32})

    assert _is_refusal(report)


def test_caller_supplying_an_empty_keyring_is_refused(boundary, tmp_path) -> None:
    report = _call(boundary, tmp_path, approval_ledger=object(), owner_keyring={})

    assert _is_refusal(report)


def test_refusal_needs_no_repository_at_all(boundary, tmp_path) -> None:
    """The refusal precedes every Git, lock, worktree and ledger effect."""
    absent = tmp_path / "not-a-repository"
    report = _call(boundary, absent)

    assert _is_refusal(report)
    assert not absent.exists()
