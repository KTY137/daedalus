from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools.architecture_boundaries import (
    ArchitectureBoundaryError,
    ImportBoundaryRule,
    evaluate_repository,
    load_contract,
    scan_repository,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "docs/architecture/import-boundaries.json"


def _run_git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")


def _contract_payload(
    baseline: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "contract_id": "test-import-boundaries",
        "master_plan_revision": 11,
        "active_gate": 1,
        "baseline_revision": "1" * 40,
        "source": {
            "root": "daedalus",
            "tracked_source_command": [
                "git",
                "ls-files",
                "-z",
                "--",
                "daedalus",
            ],
            "include_suffixes": [".py"],
        },
        "rules": [
            {
                "id": "kernel-no-outer-layers",
                "source_prefixes": ["daedalus.kernel"],
                "forbidden_target_prefixes": ["daedalus.gates"],
                "allowed_target_prefixes": [],
                "rationale": "kernel remains below gates",
                "target_owner": "test-owner",
            }
        ],
        "baseline": baseline or [],
        "shim_registry": "docs/architecture/shim-registry.json",
    }


def _write_contract(
    root: Path,
    baseline: list[dict[str, object]] | None = None,
) -> Path:
    path = root / "docs/architecture/import-boundaries.json"
    _write_text(path, json.dumps(_contract_payload(baseline), indent=2) + "\n")
    registry = {
        "schema_version": 1,
        "registry_id": "test-shims",
        "master_plan_revision": 11,
        "active_gate": 1,
        "baseline_revision": "1" * 40,
        "entries": [
            {
                "import_path": "daedalus.kernel.clean",
                "owner": "test-owner",
                "targets": ["daedalus.kernel.clean"],
                "kind": "module_reexport",
                "removal_criteria": "Remove after source and wheel audits pass.",
            }
        ],
    }
    _write_text(
        root / "docs/architecture/shim-registry.json",
        json.dumps(registry, indent=2) + "\n",
    )
    return path


def _init_repository(root: Path) -> Path:
    _run_git(root, "init", "-q")
    clean = root / "daedalus/kernel/clean.py"
    _write_text(clean, "import os\n")
    _run_git(root, "add", "--", "daedalus/kernel/clean.py")
    return _write_contract(root)


#: The repository carries NO recorded architecture debt. It carried exactly one
#: until G1-SCC-CUT1: ``daedalus/kernel/attempt_execution.py:1209`` imported the
#: ``daedalus.offload`` workload from inside the kernel. A design review
#: (2026-09-02, offload-ports memo §0) had first found the arrangement was
#: laundering -- the exception lived in the kernel rule's
#: ``allowed_target_prefixes``, a field that GRANTS permission, while the
#: rationale prose claimed it was being recorded, and the instrument reported
#: zero. Moving it into ``baseline``, the field this contract's machinery
#: actually counts, made it visible; G1-SCC-CUT1 then removed the import
#: itself, so ``offload_runner`` takes the workload as an injected port and
#: refuses at composition time without one.
#:
#: The empty assertion below is the point. ``baseline`` is a pre-authorisation:
#: every entry in it is a violation the check agrees not to fail on, so a stale
#: entry silently licenses a re-import at that exact line. Restoring ``()`` the
#: moment the last entry is resolved is what keeps the field honest -- and it is
#: why a future packet that needs an exception must ADD a row here deliberately
#: rather than inherit one.


def test_frozen_repository_baseline_is_exact_and_green() -> None:
    contract = load_contract(CONTRACT_PATH)
    report = evaluate_repository(ROOT, contract)

    assert contract.baseline == ()
    assert report.current == ()
    assert report.allowlisted == ()
    assert report.new == ()
    assert report.resolved == ()
    # 21 since G1-HIER-10 registered ``daedalus.schemas``, the last unowned
    # facade of this class. A moving census, not an invariant: re-measure it in
    # the packet that adds or retires a shim.
    assert report.shim_entry_count == 21
    assert report.passed is True


def test_only_tracked_python_files_enter_the_measurement(tmp_path: Path) -> None:
    contract_path = _init_repository(tmp_path)
    untracked = tmp_path / "daedalus/kernel/untracked.py"
    _write_text(untracked, "from daedalus.gates import report\n")
    contract = load_contract(contract_path)

    violations, tracked_count = scan_repository(tmp_path, contract)
    assert tracked_count == 1
    assert violations == ()

    _run_git(tmp_path, "add", "--", "daedalus/kernel/untracked.py")
    violations, tracked_count = scan_repository(tmp_path, contract)
    assert tracked_count == 2
    assert len(violations) == 1
    assert violations[0].target_module == "daedalus.gates"


def test_exact_baseline_allows_removal_but_rejects_relocation(
    tmp_path: Path,
) -> None:
    contract_path = _init_repository(tmp_path)
    bad = tmp_path / "daedalus/kernel/bad.py"
    _write_text(bad, "from daedalus.gates import report\n")
    _run_git(tmp_path, "add", "--", "daedalus/kernel/bad.py")

    empty_contract = load_contract(contract_path)
    first = evaluate_repository(tmp_path, empty_contract)
    assert first.passed is False
    assert len(first.new) == 1

    baseline = [first.new[0].to_dict()]
    _write_contract(tmp_path, baseline)
    reviewed_contract = load_contract(contract_path)
    reviewed = evaluate_repository(tmp_path, reviewed_contract)
    assert reviewed.passed is True
    assert reviewed.allowlisted == tuple(first.new)

    _write_text(bad, "\nfrom daedalus.gates import report\n")
    relocated = evaluate_repository(tmp_path, reviewed_contract)
    assert relocated.passed is False
    assert len(relocated.new) == 1
    assert relocated.new[0].line == 2
    assert relocated.resolved == tuple(first.new)

    _write_text(bad, "import os\n")
    resolved = evaluate_repository(tmp_path, reviewed_contract)
    assert resolved.passed is True
    assert resolved.new == ()
    assert resolved.resolved == tuple(first.new)


def test_relative_import_cannot_bypass_the_boundary(tmp_path: Path) -> None:
    contract_path = _init_repository(tmp_path)
    bad = tmp_path / "daedalus/kernel/bad.py"
    _write_text(bad, "from .. import gates\n")
    _run_git(tmp_path, "add", "--", "daedalus/kernel/bad.py")

    report = evaluate_repository(tmp_path, load_contract(contract_path))
    assert report.passed is False
    assert len(report.new) == 1
    assert report.new[0].target_module == "daedalus.gates"


def test_shim_registry_must_bind_the_same_revision(tmp_path: Path) -> None:
    contract_path = _init_repository(tmp_path)
    registry_path = tmp_path / "docs/architecture/shim-registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["baseline_revision"] = "2" * 40
    _write_text(registry_path, json.dumps(registry, indent=2) + "\n")

    with pytest.raises(
        ArchitectureBoundaryError,
        match="baseline revision differs",
    ):
        evaluate_repository(tmp_path, load_contract(contract_path))


def test_missing_tracked_locator_fails_closed(tmp_path: Path) -> None:
    contract_path = _init_repository(tmp_path)
    (tmp_path / "daedalus/kernel/clean.py").unlink()

    with pytest.raises(
        ArchitectureBoundaryError,
        match="tracked source is unavailable",
    ):
        evaluate_repository(tmp_path, load_contract(contract_path))


def test_missing_shim_target_locator_fails_closed(tmp_path: Path) -> None:
    contract_path = _init_repository(tmp_path)
    registry_path = tmp_path / "docs/architecture/shim-registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    registry["entries"][0]["targets"] = ["daedalus.missing"]
    _write_text(registry_path, json.dumps(registry, indent=2) + "\n")

    with pytest.raises(
        ArchitectureBoundaryError,
        match="shim target locator is not tracked",
    ):
        evaluate_repository(tmp_path, load_contract(contract_path))


def _rule(*, forbidden: list[str], allowed: list[str]) -> ImportBoundaryRule:
    return ImportBoundaryRule.from_dict(
        {
            "id": "kernel-no-outer-layers",
            "source_prefixes": ["daedalus.kernel"],
            "forbidden_target_prefixes": forbidden,
            "allowed_target_prefixes": allowed,
            "rationale": "test rule",
            "target_owner": "test-owner",
        },
        "rules[0]",
    )


def test_a_denylist_rule_is_blind_to_every_module_it_did_not_enumerate() -> None:
    """The gap that made the allowlist mode necessary, pinned as a test.

    This is not a bug report against the old rule -- it is the reason the new
    mode exists, and it must keep failing loudly if anyone ever concludes the
    denylist alone was sufficient. Measured on the real contract 2026-09-02:
    ``kernel-no-outer-layers`` enumerated eight forbidden package prefixes
    while 76 modules sat flat directly under ``daedalus/``, so a kernel import
    of ``daedalus.offload`` was reported clean.
    """

    blind = _rule(forbidden=["daedalus.gates"], allowed=[])

    assert blind.forbidden_target(["daedalus.offload"]) is None
    assert blind.forbidden_target(["daedalus.core"]) is None
    assert blind.forbidden_target(["daedalus.gates.report"]) == "daedalus.gates.report"


def test_the_allowlist_refuses_a_target_no_denylist_entry_names() -> None:
    """Delete the allowlist branch in ``forbidden_target`` and this fails."""

    rule = _rule(forbidden=["daedalus.gates"], allowed=["daedalus.budget"])

    # Caught only because it is not on the allowlist -- no denylist entry
    # matches it, which the test above proves for the same input.
    assert rule.forbidden_target(["daedalus.offload"]) == "daedalus.offload"
    assert rule.forbidden_target(["daedalus.core"]) == "daedalus.core"


def test_the_allowlist_admits_foundation_own_layer_root_and_third_party() -> None:
    """A guard that refuses working code is worse than none; pin what passes."""

    rule = _rule(forbidden=["daedalus.gates"], allowed=["daedalus.budget"])

    assert rule.forbidden_target(["daedalus.budget"]) is None
    assert rule.forbidden_target(["daedalus.budget.ledger"]) is None
    # a layer may always import itself, without being listed as its own target
    assert rule.forbidden_target(["daedalus.kernel.contracts.base"]) is None
    # the bare distribution root is not a layer
    assert rule.forbidden_target(["daedalus"]) is None
    # anything outside the package is not this contract's business
    assert rule.forbidden_target(["json", "pytest", "pathlib.Path"]) is None


def test_the_denylist_keeps_priority_when_both_grounds_would_fire() -> None:
    """An operator should read the enumerated reason, not the generic one."""

    rule = _rule(forbidden=["daedalus.gates"], allowed=["daedalus.budget"])

    # ``daedalus.gates`` is both forbidden AND absent from the allowlist.
    assert rule.forbidden_target(["daedalus.gates", "daedalus.offload"]) == (
        "daedalus.gates"
    )


def test_an_empty_allowlist_is_accepted_but_an_absent_key_is_not() -> None:
    """Denylist-only must be sayable; acquiring a mode by omission must not."""

    assert _rule(forbidden=["daedalus.gates"], allowed=[]).allowed_target_prefixes == ()

    with pytest.raises(ArchitectureBoundaryError):
        ImportBoundaryRule.from_dict(
            {
                "id": "kernel-no-outer-layers",
                "source_prefixes": ["daedalus.kernel"],
                "forbidden_target_prefixes": ["daedalus.gates"],
                "rationale": "test rule",
                "target_owner": "test-owner",
            },
            "rules[0]",
        )


def test_the_allowlist_must_be_sorted_and_free_of_duplicates() -> None:
    """Same validation the denylist gets; an unordered contract is a diff trap."""

    for bad in (["daedalus.spine", "daedalus.budget"], ["daedalus.budget"] * 2):
        with pytest.raises(ArchitectureBoundaryError):
            _rule(forbidden=["daedalus.gates"], allowed=bad)


def test_the_allowlists_cannot_grow_quietly() -> None:
    """Pin every rule's allowed_target_prefixes to its exact membership.

    An allowlist entry GRANTS permission -- that is its ground-2 semantics in
    ``ImportBoundaryRule.forbidden_target``. The offload design review showed
    what happens when one is added without a counting instrument watching:
    a genuine inversion read as zero violations for a day. After this pin,
    widening any allowlist is a reviewed diff of this test, never a quiet
    JSON edit.
    """

    contract = load_contract(CONTRACT_PATH)
    memberships = {
        rule.rule_id: list(rule.allowed_target_prefixes)
        for rule in contract.rules
    }
    assert memberships == {
        "kernel-no-outer-layers": [
            "daedalus.atomic",
            "daedalus.budget",
            "daedalus.config",
            "daedalus.limit_policy",
            "daedalus.primary_tree",
            "daedalus.sensitivity",
            "daedalus.spine",
            "daedalus.storage",
            "daedalus.twin",
        ],
        "runtimes-no-gates": [],
        "spine-no-outer-layers": [
            "daedalus.atomic",
            "daedalus.budget",
            "daedalus.config",
            "daedalus.kernel",
            "daedalus.limit_policy",
            "daedalus.mapping",
            "daedalus.sensitivity",
            "daedalus.structcore",
        ],
        "twin-no-outer-layers": [
            "daedalus.kernel",
            "daedalus.spine",
            "daedalus.structcore",
        ],
    }
