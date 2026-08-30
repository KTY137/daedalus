# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from daedalus.spine.ledger import ROOT


REVISION = "a" * 40
SCRIPT = ROOT / "scripts" / "report_spine_writer_inventory.py"


def _repo(tmp_path: Path, body: str) -> Path:
    root = tmp_path / "repo"
    package = root / "daedalus"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "app.py").write_text(body, encoding="utf-8")
    return root


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _run(root: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(root),
            "--source-revision",
            REVISION,
            *extra,
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def test_cli_prints_one_canonical_report_and_does_not_mutate_repository(tmp_path) -> None:
    root = _repo(
        tmp_path,
        "from daedalus.spine import open_gate0_spine_writer\n"
        "open_gate0_spine_writer('state.sqlite3')\n",
    )
    before = _tree_digest(root)

    result = _run(root, "--require-closed")

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    assert result.stdout.endswith("\n")
    assert result.stdout.count("\n") == 1
    payload = json.loads(result.stdout)
    assert payload["closed"] is True
    assert payload["blocker_count"] == 0
    assert payload["source_revision"] == REVISION
    assert _tree_digest(root) == before


def test_cli_emits_report_and_nonzero_when_blockers_remain(tmp_path) -> None:
    root = _repo(
        tmp_path,
        "from daedalus.spine import SpineLedger\n"
        "SpineLedger('state.sqlite3')\n",
    )

    result = _run(root, "--require-closed")

    assert result.returncode == 1
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["closed"] is False
    assert payload["blocker_count"] == 1
    assert payload["callsites"][0]["kind"] == "legacy_direct"


def test_cli_refusal_uses_stderr_and_no_partial_stdout(tmp_path) -> None:
    root = _repo(tmp_path, "VALUE = 1\n")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            str(root),
            "--source-revision",
            "not-a-revision",
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "writer inventory refused" in result.stderr
    assert "source_revision" in result.stderr
