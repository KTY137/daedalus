from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from tools.architecture_boundaries import (
    ArchitectureBoundaryError,
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


def test_frozen_repository_baseline_is_exact_and_green() -> None:
    contract = load_contract(CONTRACT_PATH)
    report = evaluate_repository(ROOT, contract)

    assert len(contract.baseline) == 23
    assert report.current == contract.baseline
    assert report.allowlisted == contract.baseline
    assert report.new == ()
    assert report.resolved == ()
    assert report.shim_entry_count == 10
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
