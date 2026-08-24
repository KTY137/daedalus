from __future__ import annotations

import csv
import re
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
ARCHIVE = ROOT / "docs" / "archive" / "ci-workflows" / "2026-08-25"
MANIFEST = ARCHIVE / "BASE_WORKFLOW_MANIFEST.tsv"
BASE_REVISION = "4b9dae0c4bce519f794d87474c62e1a13005cded"

ACTIVE = {
    "ci.yml",
    "fourfold-polyglot-probe.yml",
    "g0-canonical-fault-matrix-contract.yml",
}
MANUAL = {
    "fourfold-polyglot-probe.yml",
    "g0-canonical-fault-matrix-contract.yml",
}
PINNED_ACTION = re.compile(r"^[0-9a-f]{40}$")


def _text(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _yaml(name: str) -> dict:
    payload = yaml.load(_text(name), Loader=yaml.BaseLoader)
    assert isinstance(payload, dict)
    return payload


def _git(*args: str, binary: bool = False) -> str | bytes:
    completed = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    if binary:
        return completed.stdout
    return completed.stdout.decode("utf-8").strip()


def _manifest_rows() -> list[dict[str, str]]:
    with MANIFEST.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _parent_workflow_blobs() -> dict[str, str]:
    raw = _git(
        "ls-tree",
        "-rz",
        "--full-tree",
        BASE_REVISION,
        "--",
        ".github/workflows",
        binary=True,
    )
    assert isinstance(raw, bytes)
    result: dict[str, str] = {}
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        metadata, separator, path = entry.partition(b"\t")
        assert separator == b"\t"
        mode, object_type, blob = metadata.decode("ascii").split()
        assert mode == "100644"
        assert object_type == "blob"
        result[path.decode("utf-8")] = blob
    return result


def _validate_manifest_rows(
    rows: list[dict[str, str]], parent_blobs: dict[str, str]
) -> None:
    assert len(rows) == 98
    assert len({row["original_path"] for row in rows}) == 98
    assert len({row["current_path"] for row in rows}) == 98
    assert {row["original_path"] for row in rows} == set(parent_blobs)

    dispositions = [row["disposition"] for row in rows]
    assert dispositions.count("archived") == 96
    assert dispositions.count("active-manual") == 2

    retained = {
        Path(row["original_path"]).name
        for row in rows
        if row["disposition"] == "active-manual"
    }
    assert retained == MANUAL

    archived_targets: set[str] = set()
    for row in rows:
        original = row["original_path"]
        current = row["current_path"]
        base_blob = row["base_blob_sha1"]
        assert PINNED_ACTION.fullmatch(base_blob)
        assert base_blob == parent_blobs[original]

        if row["disposition"] == "archived":
            expected = f"docs/archive/ci-workflows/2026-08-25/{Path(original).name}"
            assert current == expected
            archived_targets.add(current)
        else:
            assert row["disposition"] == "active-manual"
            assert current == original

        target = ROOT / current
        assert target.is_file(), row

        if row["disposition"] == "archived":
            current_blob = _git(
                "hash-object",
                f"--path={original}",
                "--",
                str(target),
            )
            assert current_blob == base_blob

    archive_files = {
        path.relative_to(ROOT).as_posix() for path in ARCHIVE.glob("*.yml")
    }
    assert archive_files == archived_targets


def test_exactly_one_automatic_ci_and_two_manual_workflows_are_active() -> None:
    active = {path.name for path in WORKFLOWS.glob("*.y*ml")}
    assert active == ACTIVE

    ci_events = _yaml("ci.yml")["on"]
    assert set(ci_events) == {"pull_request", "push", "workflow_dispatch"}
    assert ci_events["pull_request"] == {"branches": ["main"]}
    assert ci_events["push"] == {"branches": ["main"]}
    assert "paths" not in ci_events["pull_request"]
    assert "paths" not in ci_events["push"]

    for name in MANUAL:
        assert set(_yaml(name)["on"]) == {"workflow_dispatch"}


def test_active_workflows_are_read_only_pinned_and_non_promoting() -> None:
    forbidden = (
        "pull_request_target",
        "contents: write",
        "id-token: write",
        "gh pr merge",
        "git push",
        "twine upload",
        "npm publish",
        "docker push",
        "tools/iron_plan_guard.py",
        "secrets.",
    )

    for name in ACTIVE:
        text = _text(name)
        payload = _yaml(name)
        assert payload["permissions"] == {"contents": "read"}
        assert not any(token in text.lower() for token in forbidden)

        uses = re.findall(r"uses:\s*([^@\s]+)@([^\s#]+)", text)
        assert uses
        for action, revision in uses:
            assert action.startswith("actions/")
            assert PINNED_ACTION.fullmatch(revision)

        checkout_count = sum(action == "actions/checkout" for action, _ in uses)
        assert text.count("persist-credentials: false") == checkout_count
        upload_count = sum(action == "actions/upload-artifact" for action, _ in uses)
        assert text.count("retention-days: 14") == upload_count


def test_ci_matrix_and_required_measurements_are_frozen() -> None:
    payload = _yaml("ci.yml")
    assert payload["jobs"]["test"]["timeout-minutes"] == "180"
    cells = payload["jobs"]["test"]["strategy"]["matrix"]["include"]
    assert cells == [
        {
            "label": "ubuntu-py312-seed0",
            "os": "ubuntu-latest",
            "python": "3.12",
            "hash-seed": "0",
            "build-products": "true",
        },
        {
            "label": "windows-py310-seed123456",
            "os": "windows-latest",
            "python": "3.10",
            "hash-seed": "123456",
            "build-products": "false",
        },
    ]

    text = _text("ci.yml")
    required = (
        'python -m pip install -e ".[test,yaml]"',
        "python -m compileall -q daedalus tests scripts tools",
        "python -m pytest -q -ra",
        "-p pytest_asyncio.plugin",
        "-p _hypothesis_pytestplugin",
        "--junitxml=pytest-results.xml",
        "python -m pip install build==1.5.0 twine==7.0.0",
        "python -m build --sdist --wheel",
        "python -m twine check dist/*",
        'cd "$RUNNER_TEMP"',
        'PYTHONPATH= "$wheel_root/bin/python"',
        '"$wheel_root/bin/daedalus" --help',
        "npm ci --prefix apps/web",
        "npm --prefix apps/web run test:motion",
        "npm --prefix apps/web run build",
        "git diff --exit-code --ignore-cr-at-eol -- apps/web/dist",
        "npm ci --prefix vscode-agent-env",
        "npm --prefix vscode-agent-env run check",
        "npm --prefix vscode-agent-env run package",
        "retention-days: 14",
        "git diff --exit-code",
    )
    for command in required:
        assert command in text


def test_parent_workflow_manifest_is_complete_and_destinations_exist() -> None:
    _validate_manifest_rows(_manifest_rows(), _parent_workflow_blobs())


def test_manifest_validator_kills_valid_looking_binding_mutants() -> None:
    rows = _manifest_rows()
    parent_blobs = _parent_workflow_blobs()

    wrong_sha = [dict(row) for row in rows]
    first = wrong_sha[0]["base_blob_sha1"]
    wrong_sha[0]["base_blob_sha1"] = ("0" if first[0] != "0" else "1") + first[1:]
    with pytest.raises(AssertionError):
        _validate_manifest_rows(wrong_sha, parent_blobs)

    swapped_sha = [dict(row) for row in rows]
    swapped_sha[0]["base_blob_sha1"], swapped_sha[1]["base_blob_sha1"] = (
        swapped_sha[1]["base_blob_sha1"],
        swapped_sha[0]["base_blob_sha1"],
    )
    with pytest.raises(AssertionError):
        _validate_manifest_rows(swapped_sha, parent_blobs)

    wrong_original = [dict(row) for row in rows]
    wrong_original[0]["original_path"] = wrong_original[1]["original_path"]
    with pytest.raises(AssertionError):
        _validate_manifest_rows(wrong_original, parent_blobs)


def test_archive_blob_binding_detects_semantic_byte_mutation(tmp_path: Path) -> None:
    row = next(row for row in _manifest_rows() if row["disposition"] == "archived")
    source = ROOT / row["current_path"]
    mutant = tmp_path / source.name
    mutant.write_bytes(source.read_bytes() + b"\n# semantic-mutant\n")
    mutant_blob = _git(
        "hash-object",
        f"--path={row['original_path']}",
        "--",
        str(mutant),
    )
    assert mutant_blob != row["base_blob_sha1"]


def test_manual_workflows_are_bounded_and_reproducible() -> None:
    fault = _yaml("g0-canonical-fault-matrix-contract.yml")
    assert set(fault["jobs"]) == {"focused", "mutation", "predecessor-regression"}
    assert fault["jobs"]["focused"]["timeout-minutes"] == "15"
    assert fault["jobs"]["focused"]["strategy"]["max-parallel"] == "4"
    assert fault["jobs"]["mutation"]["timeout-minutes"] == "20"
    assert fault["jobs"]["predecessor-regression"]["timeout-minutes"] == "30"

    for name in MANUAL:
        payload = _yaml(name)
        assert all("timeout-minutes" in job for job in payload["jobs"].values())

    fault_text = _text("g0-canonical-fault-matrix-contract.yml")
    assert fault_text.count("pip==26.1.2") == 3
    assert fault_text.count("pytest==9.1.1") == 3
    assert fault_text.count("jsonschema==4.23.0") == 3

    probe_text = _text("fourfold-polyglot-probe.yml")
    assert probe_text.count("pip==26.1.2") == 2
    assert "pytest==9.1.1" in probe_text


def test_retired_guard_calls_are_negative_evidence_only() -> None:
    archived = list(ARCHIVE.glob("*.yml"))
    texts = [path.read_text(encoding="utf-8") for path in archived]
    assert sum("tools/iron_plan_guard.py" in text for text in texts) == 94
    assert sum(text.count("tools/iron_plan_guard.py") for text in texts) == 170
    assert all("tools/iron_plan_guard.py" not in _text(name) for name in ACTIVE)


def test_manual_workflow_local_inputs_exist() -> None:
    required = (
        "daedalus/gates/fault_matrix.py",
        "configs/gates/g0-provider-target-receipt-retention-fault-matrix.json",
        "configs/schemas/fault-matrix-contract.schema.json",
        "tests/gates/test_fault_matrix_contract.py",
        "tests/gates/test_fault_matrix_contract_schema.py",
        "tests/gates/test_fault_matrix_contract_review.py",
        "scripts/run_fault_matrix_contract_exact_mutations.py",
        "tests/runtimes/test_provider_target_receipt_retention_preflight.py",
        "tests/runtimes/test_provider_target_receipt_retention_admission.py",
        "tests/runtimes/test_provider_target_receipt_retention_admission_review.py",
        "daedalus/twin/extractors",
        "scripts/fourfold_repo_probe.py",
        "scripts/fourfold_tree_sitter_probe.py",
        "scripts/fourfold_root_file_probe.py",
        "tests/twin/test_extractor_contracts.py",
        "tests/twin/test_tree_sitter_extractors.py",
        "tests/twin/test_root_file_extractor.py",
    )
    for relative in required:
        assert (ROOT / relative).exists(), relative


def test_fresh_test_dependencies_and_runtime_package_data_are_declared() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    required = (
        '"pytest==9.1.1"',
        '"pytest-asyncio==1.4.0"',
        '"hypothesis==6.163.0"',
        '"jsonschema==4.23.0"',
        '"pyyaml==6.0.2"',
        '"daedalus.kairos" = ["_gated_writes_legacy.py.src"]',
        '"daedalus.eval" = ["*.json"]',
        '"daedalus.gui" = ["probe.js"]',
        '"daedalus.providers" = ["personas.json"]',
    )
    for declaration in required:
        assert declaration in text
