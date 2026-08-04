from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


REVISION = "c" * 40
ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "report_repository_write_inventory.py"


def _repository(tmp_path: Path, source: str) -> Path:
    root = tmp_path / "repo"
    package = root / "daedalus"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "sample.py").write_text(source, encoding="utf-8")
    return root


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_emits_one_canonical_report(tmp_path: Path) -> None:
    repository = _repository(
        tmp_path,
        "from pathlib import Path\nPath('x').write_text('x')\n",
    )

    result = _run(str(repository), "--source-revision", REVISION)

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.endswith("\n")
    assert result.stdout.count("\n") == 1
    payload = json.loads(result.stdout)
    assert payload["schema"] == "daedalus-gate0-repository-write-inventory/1"
    assert payload["source_revision"] == REVISION
    assert payload["closed"] is False
    assert payload["blocker_count"] == 1
    assert payload["primary_checkout_target_proven"] is False


def test_require_closed_is_a_scoped_assertion(tmp_path: Path) -> None:
    blocked = _repository(
        tmp_path / "blocked",
        "open('state.json', 'w').write('{}')\n",
    )
    clear = _repository(tmp_path / "clear", "value = 1\n")

    blocked_result = _run(
        str(blocked),
        "--source-revision",
        REVISION,
        "--require-closed",
    )
    clear_result = _run(
        str(clear),
        "--source-revision",
        REVISION,
        "--require-closed",
    )

    assert blocked_result.returncode == 1
    assert json.loads(blocked_result.stdout)["closed"] is False
    assert clear_result.returncode == 0
    assert json.loads(clear_result.stdout)["closed"] is True


def test_cli_refusal_is_stderr_only(tmp_path: Path) -> None:
    repository = _repository(tmp_path, "def broken(:\n")

    result = _run(str(repository), "--source-revision", REVISION)

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith("repository write inventory refused: ")
