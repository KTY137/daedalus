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


# The module that DEFINES the trust root. It is not a consumer of itself.
TRUST_ROOT_MODULE = PACKAGE / "kernel" / "signed_approval.py"

# Production modules reviewed and accepted as consumers of the signed-tag
# trust root. Empty: the mechanism is armed and nothing in the package
# consults it. Adding a name here is a security review, not bookkeeping --
# it is the moment two approval mechanisms become simultaneously live.
AUTHORIZED_TRUST_ROOT_CONSUMERS: frozenset[str] = frozenset()


def _signed_approval_importers() -> dict[str, list[int]]:
    """Every module in the package that imports the signed-tag trust root.

    Found via the AST, over the WHOLE package, because the boundary is not one
    file. ``promote_candidates`` is declared in ``kairos/gated_writes.py``
    while the authorization helpers live in ``kernel/promotion.py``; a pin that
    reads only one of them is blind to a wiring landing in the other. It was
    measured blind: wiring the signed root into ``gated_writes.py`` left the
    lane suite green at 75 passed.
    """
    found: dict[str, list[int]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        if path == TRUST_ROOT_MODULE:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - defensive
            continue
        lines: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "signed_approval" or module.endswith(
                    ".signed_approval"
                ):
                    lines.append(node.lineno)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "signed_approval" or alias.name.endswith(
                        ".signed_approval"
                    ):
                        lines.append(node.lineno)
        if lines:
            found[str(path.relative_to(PACKAGE.parent).as_posix())] = sorted(lines)
    return found


def test_signed_tag_root_is_not_yet_binding_on_the_boundary() -> None:
    """Pins an honest, uncomfortable fact so it cannot drift into a claim.

    ``daedalus/kernel/signed_approval.py`` exists, is fault-injected and is
    mutation-proven, but the promotion boundary does not consult it yet.
    Authorization still authenticates against ``owner_keyring``, which
    ``promote_candidates`` receives from its caller -- so the trust root of a
    live promotion is still chosen by whoever calls it.

    Until that changes, no one may describe the boundary as protected by an
    owner signature. When it does change, this test fails, and whoever makes
    it fail is the person who gets to update the assurance wording and the
    ``promotion.owner_approval`` inventory row in the same breath.

    The pin is package-wide on purpose. Naming ``kernel/promotion.py`` alone
    watched a file the boundary is not defined in; the definition site is
    ``kairos/gated_writes.py``, which this module already names as
    ``DEFINITION``. An import anywhere under ``daedalus/`` is the earliest
    syntactic evidence that the second mechanism became reachable, so that is
    what is watched.
    """
    importers = _signed_approval_importers()
    unreviewed = sorted(set(importers) - AUTHORIZED_TRUST_ROOT_CONSUMERS)

    assert unreviewed == [], (
        "the signed-tag trust root is now reachable from the package: "
        f"{ {name: importers[name] for name in unreviewed} }. "
        "Re-check what approval_assurance and promotion.owner_approval are "
        "allowed to claim, then add the module to "
        "AUTHORIZED_TRUST_ROOT_CONSUMERS."
    )
    # The two files the wiring would most plausibly land in, named explicitly
    # so the intent survives a refactor that moves the AST scan.
    for rel in (PACKAGE / "kernel" / "promotion.py", DEFINITION):
        text = rel.read_text(encoding="utf-8")
        assert "signed_approval" not in text, (
            f"{rel.name} now names the signed-tag trust root; update this test "
            "and the assurance wording in the same breath."
        )
    authorization = (PACKAGE / "kernel" / "promotion.py").read_text(encoding="utf-8")
    assert "owner_keyring" in authorization


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
