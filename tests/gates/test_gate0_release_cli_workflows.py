from __future__ import annotations

import importlib.util
import json
from datetime import timedelta
from pathlib import Path

import pytest

from daedalus.gates.release_cli import main

_SUPPORT_PATH = Path(__file__).with_name("release_support.py")
_SPEC = importlib.util.spec_from_file_location("_release_cli_workflow_support", _SUPPORT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_SUPPORT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SUPPORT)

_SECRET_ENV = "DAEDALUS_TEST_RELEASE_WORKFLOW_SECRET"


def _write(path: Path, value) -> str:
    path.write_text(
        json.dumps(value.to_dict(), sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return str(path)


def test_wrong_adopted_workflow_path_cannot_be_replaced_by_bundle_contents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    root = _SUPPORT.repo_root(tmp_path)
    report = _SUPPORT.local_report()
    index = _SUPPORT.evidence_index(report)
    bundle = _SUPPORT.trust_bundle(index, root)
    release = _SUPPORT.assemble(report, index, bundle, root)
    monkeypatch.setenv(_SECRET_ENV, _SUPPORT.SECRET.decode("utf-8"))

    argv = [
        "--release", _write(tmp_path / "release.json", release),
        "--mechanical-report", _write(tmp_path / "report.json", report),
        "--evidence-index", _write(tmp_path / "index.json", index),
        "--trust-bundle", _write(tmp_path / "bundle.json", bundle),
        "--repo-root", str(root),
        "--collector-id", _SUPPORT.COLLECTOR_ID,
        "--collector-key-id", _SUPPORT.COLLECTOR_KEY_ID,
        "--collector-secret-env", _SECRET_ENV,
        "--workflow", f"{_SUPPORT.WORKFLOW_ID}=.github/workflows/wrong.yml",
        "--current-revision", _SUPPORT.REVISION,
        "--current-tree-revision", _SUPPORT.TREE,
        "--now", (_SUPPORT.NOW + timedelta(minutes=3)).isoformat(),
    ]

    assert main(argv) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["trusted"] is False
    assert "release:trust-bundle-binding" in payload["blockers"]
    assert "release:no-longer-current" in payload["blockers"]
