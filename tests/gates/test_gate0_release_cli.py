from __future__ import annotations

import importlib.util
import json
from datetime import timedelta
from pathlib import Path

import pytest

from daedalus.gates.release_cli import main

_SUPPORT_PATH = Path(__file__).with_name("release_support.py")
_SPEC = importlib.util.spec_from_file_location("_release_cli_support", _SUPPORT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SUPPORT)

_SECRET_ENV = "DAEDALUS_TEST_RELEASE_COLLECTOR_SECRET"


def _write(path: Path, value) -> Path:
    path.write_text(
        json.dumps(value.to_dict(), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return path


def _fixture(tmp_path: Path) -> dict[str, object]:
    root = _SUPPORT.repo_root(tmp_path)
    report = _SUPPORT.local_report()
    index = _SUPPORT.evidence_index(report)
    bundle = _SUPPORT.trust_bundle(index, root)
    release = _SUPPORT.assemble(report, index, bundle, root)
    return {
        "root": root,
        "report": _write(tmp_path / "mechanical-report.json", report),
        "index": _write(tmp_path / "evidence-index.json", index),
        "bundle": _write(tmp_path / "trust-bundle.json", bundle),
        "release": _write(tmp_path / "release.json", release),
    }


def _argv(files: dict[str, object], **changes: str) -> list[str]:
    values = {
        "release": str(files["release"]),
        "mechanical-report": str(files["report"]),
        "evidence-index": str(files["index"]),
        "trust-bundle": str(files["bundle"]),
        "repo-root": str(files["root"]),
        "collector-id": _SUPPORT.COLLECTOR_ID,
        "collector-key-id": _SUPPORT.COLLECTOR_KEY_ID,
        "collector-secret-env": _SECRET_ENV,
        "current-revision": _SUPPORT.REVISION,
        "current-tree-revision": _SUPPORT.TREE,
        "now": (_SUPPORT.NOW + timedelta(minutes=3)).isoformat(),
    }
    values.update(changes)
    result: list[str] = []
    for name, value in values.items():
        result.extend((f"--{name}", value))
    result.extend(("--workflow", f"{_SUPPORT.WORKFLOW_ID}={_SUPPORT.WORKFLOW_PATH}"))
    return result


def _output(capsys) -> dict[str, object]:
    captured = capsys.readouterr()
    assert captured.err == ""
    return json.loads(captured.out)


def test_valid_exact_head_release_verifies_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    files = _fixture(tmp_path)
    root = files["root"]
    before = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    monkeypatch.setenv(_SECRET_ENV, _SUPPORT.SECRET.decode("utf-8"))

    assert main(_argv(files)) == 0
    payload = _output(capsys)
    assert payload["contract_type"] == "daedalus-gate0-release-verification/1"
    assert payload["trusted"] is True
    assert payload["blockers"] == []
    assert payload["source_revision"] == _SUPPORT.REVISION
    assert payload["source_tree_revision"] == _SUPPORT.TREE

    after = {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }
    assert after == before


def test_missing_or_short_secret_refuses_without_disclosing_secret(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    files = _fixture(tmp_path)
    monkeypatch.delenv(_SECRET_ENV, raising=False)
    assert main(_argv(files)) == 2
    missing = _output(capsys)
    assert missing["trusted"] is False
    assert missing["blockers"] == ["verification-input:ValueError"]

    short = "short-secret"
    monkeypatch.setenv(_SECRET_ENV, short)
    assert main(_argv(files)) == 2
    payload = _output(capsys)
    assert payload["trusted"] is False
    assert short not in json.dumps(payload)


def test_stale_revision_and_changed_workflow_are_current_state_blockers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    files = _fixture(tmp_path)
    monkeypatch.setenv(_SECRET_ENV, _SUPPORT.SECRET.decode("utf-8"))

    assert main(_argv(files, **{"current-revision": "0" * 40})) == 1
    stale = _output(capsys)
    assert stale["trusted"] is False
    assert "release:trust-bundle-binding" in stale["blockers"]
    assert "release:no-longer-current" in stale["blockers"]

    workflow = Path(files["root"]) / _SUPPORT.WORKFLOW_PATH
    workflow.write_text("name: changed\non: [push]\njobs: {}\n", encoding="utf-8")
    assert main(_argv(files)) == 1
    drift = _output(capsys)
    assert drift["trusted"] is False
    assert "release:trust-bundle-binding" in drift["blockers"]
    assert "release:no-longer-current" in drift["blockers"]


def test_malformed_release_duplicate_mapping_and_naive_time_refuse(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    files = _fixture(tmp_path)
    monkeypatch.setenv(_SECRET_ENV, _SUPPORT.SECRET.decode("utf-8"))

    release_path = Path(files["release"])
    release_wire = release_path.read_text(encoding="utf-8").strip()
    release_path.write_text('{"closed":true,' + release_wire[1:], encoding="utf-8")
    assert main(_argv(files)) == 2
    malformed = _output(capsys)
    assert malformed["trusted"] is False
    assert malformed["blockers"] == ["verification-input:ValueError"]

    files = _fixture(tmp_path / "second")
    duplicate = _argv(files)
    duplicate.extend(("--workflow", f"{_SUPPORT.WORKFLOW_ID}=other.yml"))
    assert main(duplicate) == 2
    duplicate_result = _output(capsys)
    assert "duplicate workflow mapping" in duplicate_result["error"]

    assert main(_argv(files, now="2026-08-03T12:03:00")) == 2
    naive = _output(capsys)
    assert "timezone" in naive["error"]


def test_substituted_bundle_and_report_do_not_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    files = _fixture(tmp_path)
    monkeypatch.setenv(_SECRET_ENV, _SUPPORT.SECRET.decode("utf-8"))

    bundle_payload = json.loads(Path(files["bundle"]).read_text(encoding="utf-8"))
    bundle_payload["signature_sha256"] = "f" * 64
    Path(files["bundle"]).write_text(
        json.dumps(bundle_payload, sort_keys=True) + "\n", encoding="utf-8"
    )
    assert main(_argv(files)) == 1
    bundle_result = _output(capsys)
    assert "release:trust-bundle-signature" in bundle_result["blockers"]

    files = _fixture(tmp_path / "third")
    report_payload = json.loads(Path(files["report"]).read_text(encoding="utf-8"))
    report_payload["diagnostics"] = ["substituted"]
    Path(files["report"]).write_text(
        json.dumps(report_payload, sort_keys=True) + "\n", encoding="utf-8"
    )
    assert main(_argv(files)) == 2
    report_result = _output(capsys)
    assert report_result["trusted"] is False
