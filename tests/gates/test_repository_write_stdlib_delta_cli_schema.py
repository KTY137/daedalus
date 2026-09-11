from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import daedalus.gates.repository.write_stdlib_delta as delta


REVISION = "c" * 40
ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "report_repository_write_stdlib_delta.py"
SCHEMA = (
    ROOT
    / "configs"
    / "schemas"
    / "repository-write-stdlib-delta-v1.schema.json"
)


def _repository(tmp_path: Path, source: str) -> Path:
    root = tmp_path / "repo"
    package = root / "daedalus"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "sample.py").write_text(source, encoding="utf-8")
    return root


def _env() -> dict[str, str]:
    """Pin the subprocess to the checkout under test.

    Running a script puts the script's own directory on sys.path, not the cwd,
    so `daedalus` would otherwise resolve against whatever copy happens to be
    installed in site-packages rather than this tree.
    """

    environment = dict(os.environ)
    inherited = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        f"{ROOT}{os.pathsep}{inherited}" if inherited else str(ROOT)
    )
    return environment


def _run(repository: Path, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--repository-root",
            str(repository),
            "--source-revision",
            REVISION,
            *extra,
        ],
        cwd=ROOT,
        env=_env(),
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_emits_one_canonical_open_delta(tmp_path: Path) -> None:
    # gzip/bz2/lzma/tarfile openers are owned by the canonical scanner now, so
    # they no longer reach the additive delta.  zipfile is the archive family
    # the base scanner still misses, which is exactly what the delta reports.
    repository = _repository(
        tmp_path,
        "import zipfile\nzipfile.ZipFile('state.zip', 'w')\n",
    )

    result = _run(repository)

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.endswith("\n")
    assert result.stdout.count("\n") == 1
    payload = json.loads(result.stdout)
    assert payload["schema"] == (
        "daedalus-gate0-repository-write-stdlib-delta/1"
    )
    assert payload["source_revision"] == REVISION
    assert payload["finding_count"] == 1
    assert payload["canonical_scanner_integrated"] is False
    assert payload["closed"] is False


def test_cli_scoped_no_additional_surfaces_assertion(tmp_path: Path) -> None:
    blocked = _repository(
        tmp_path / "blocked",
        "import os\nos.write(fd, b'x')\n",
    )
    clear = _repository(tmp_path / "clear", "value = 1\n")

    blocked_result = _run(blocked, "--require-no-additional-surfaces")
    clear_result = _run(clear, "--require-no-additional-surfaces")

    assert blocked_result.returncode == 1
    assert json.loads(blocked_result.stdout)["finding_count"] == 1
    assert clear_result.returncode == 0
    clear_payload = json.loads(clear_result.stdout)
    assert clear_payload["finding_count"] == 0
    assert clear_payload["closed"] is False
    assert clear_payload["blockers"] == [
        "canonical-scanner-integration-missing"
    ]


def test_cli_refusal_is_stderr_only(tmp_path: Path) -> None:
    repository = _repository(tmp_path, "def broken(:\n")

    result = _run(repository)

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr.startswith(
        "repository-write stdlib delta refused: "
    )


def test_schema_matches_runtime_contract() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {
        "schema",
        "source_revision",
        "base_inventory_digest",
        "scan_input_sha256",
        "files_scanned",
        "findings",
        "finding_count",
        "canonical_scanner_integrated",
        "closed",
        "blockers",
        "digest",
    }
    finding = schema["properties"]["findings"]["items"]
    assert finding["additionalProperties"] is False
    assert set(finding["properties"]["kind"]["enum"]) == set(
        delta._ALLOWED_KINDS
    )
    assert finding["properties"]["blocking"] == {"const": True}
    assert schema["properties"]["canonical_scanner_integrated"] == {
        "const": False
    }
    assert schema["properties"]["closed"] == {"const": False}
