# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools import source_provenance as provenance


def _policy() -> dict[str, object]:
    return {
        "copyright_header": "SPDX-FileCopyrightText: 2026 Kaya Yesilyurt",
        "license_header": "SPDX-License-Identifier: Apache-2.0",
    }


def test_python_header_preserves_shebang_and_encoding_cookie() -> None:
    original = b"#!/usr/bin/env python3\n# -*- coding: utf-8 -*-\nprint('ok')\n"

    rendered = provenance.add_header("tool.py", original, _policy())

    assert rendered.startswith(
        b"#!/usr/bin/env python3\n"
        b"# -*- coding: utf-8 -*-\n"
        b"# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt\n"
        b"# SPDX-License-Identifier: Apache-2.0\n"
    )


def test_html_header_follows_doctype() -> None:
    original = b"<!doctype html>\n<html></html>\n"

    rendered = provenance.add_header("index.html", original, _policy())

    assert rendered.startswith(
        b"<!doctype html>\n"
        b"<!-- SPDX-FileCopyrightText: 2026 Kaya Yesilyurt\n"
        b"     SPDX-License-Identifier: Apache-2.0 -->\n"
    )


def test_css_header_follows_charset() -> None:
    original = b'@charset "UTF-8";\nbody {}\n'

    rendered = provenance.add_header("styles.css", original, _policy())

    assert rendered.startswith(
        b'@charset "UTF-8";\n'
        b"/* SPDX-FileCopyrightText: 2026 Kaya Yesilyurt\n"
        b" * SPDX-License-Identifier: Apache-2.0 */\n"
    )


def test_apply_is_idempotent() -> None:
    original = b"#!/bin/sh\necho ok\n"

    first = provenance.add_header("bootstrap.sh", original, _policy())
    second = provenance.add_header("bootstrap.sh", first, _policy())

    assert second == first


def test_header_text_inside_source_does_not_satisfy_preamble() -> None:
    body = (
        b'COPYRIGHT = "SPDX-FileCopyrightText: 2026 Kaya Yesilyurt"\n'
        b'LICENSE = "SPDX-License-Identifier: Apache-2.0"\n'
    )

    assert not provenance.has_exact_header("module.py", body, _policy())


def test_policy_excludes_fixtures_and_separate_license_domain() -> None:
    policy = provenance.load_policy()

    assert provenance.is_candidate("daedalus/core.py", policy)
    assert provenance.is_candidate("tests/test_core.py", policy)
    assert not provenance.is_candidate("tests/fixtures/sample.py", policy)
    assert not provenance.is_candidate("vscode-agent-env/extension.js", policy)
    assert not provenance.is_candidate("experiments/frozen/search.py", policy)
    assert not provenance.is_candidate("daedalus/kairos/archive.py", policy)


def _run_git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)


def _snapshot_repo(tmp_path: Path) -> tuple[Path, Path]:
    (tmp_path / "provenance").mkdir()
    (tmp_path / "src").mkdir()
    policy = {
        "schema": "daedalus-source-watermark-policy/1",
        "copyright_header": "SPDX-FileCopyrightText: 2026 Kaya Yesilyurt",
        "license_header": "SPDX-License-Identifier: Apache-2.0",
        "license_identifier": "Apache-2.0",
        "include": {"prefixes": {"src/": [".py"]}, "paths": []},
        "exclude": {"paths": [], "prefixes": [], "reason": "test"},
    }
    policy_path = tmp_path / "provenance" / "source-watermark-policy.json"
    policy_path.write_text(json.dumps(policy) + "\n", encoding="utf-8")
    (tmp_path / "provenance" / "source-watermark-allowed-signers").write_text(
        "test@example.invalid ssh-ed25519 AAAATEST test\n", encoding="utf-8"
    )
    (tmp_path / "NOTICE").write_text("test notice\n", encoding="utf-8")
    (tmp_path / ".gitattributes").write_text("*.py text eol=lf\n", encoding="utf-8")
    source = tmp_path / "src" / "subject.py"
    source.write_bytes(
        b"# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt\r\n"
        b"# SPDX-License-Identifier: Apache-2.0\r\n"
        b"\r\nprint('first')\r\n"
    )
    _run_git(tmp_path, "init", "-q")
    _run_git(tmp_path, "add", ".")
    manifest_path = tmp_path / "manifest.json"
    manifest = provenance.build_manifest(
        tmp_path,
        policy_path,
        target_ref="main",
        base_revision="a" * 40,
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return policy_path, manifest_path


def test_manifest_hashes_prospective_index_bytes(tmp_path: Path) -> None:
    policy_path, manifest_path = _snapshot_repo(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = hashlib.sha256(
        b"# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt\n"
        b"# SPDX-License-Identifier: Apache-2.0\n"
        b"\nprint('first')\n"
    ).hexdigest()

    assert manifest["files"] == [{"path": "src/subject.py", "sha256": expected}]
    assert provenance.verify_manifest(
        tmp_path,
        manifest_path,
        policy_path,
        expected_target_ref="main",
        expected_base_revision="a" * 40,
    ) == []


def test_render_manifest_cli_emits_fixed_utf8_lf(tmp_path: Path) -> None:
    policy_path, _ = _snapshot_repo(tmp_path)
    expected_manifest = provenance.build_manifest(
        tmp_path,
        policy_path,
        target_ref="main",
        base_revision="a" * 40,
    )
    expected = (
        json.dumps(expected_manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            str(provenance.__file__),
            "--root",
            str(tmp_path),
            "--policy",
            str(policy_path),
            "render-manifest",
            "--target-ref",
            "main",
            "--base-revision",
            "a" * 40,
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    assert completed.stdout == expected
    assert b"\r" not in completed.stdout


def test_manifest_verification_detects_content_and_metadata_drift(tmp_path: Path) -> None:
    policy_path, manifest_path = _snapshot_repo(tmp_path)
    source = tmp_path / "src" / "subject.py"
    source.write_text("# changed after staging\n", encoding="utf-8")

    assert provenance.verify_manifest(tmp_path, manifest_path, policy_path) == []

    _run_git(tmp_path, "add", "src/subject.py")
    failures = provenance.verify_manifest(
        tmp_path,
        manifest_path,
        policy_path,
        expected_target_ref="wrong",
        expected_base_revision="b" * 40,
    )

    assert "file digest mismatch: src/subject.py" in failures
    assert "staged source lacks watermark: src/subject.py" in failures
    assert "manifest target_ref does not match expected target" in failures
    assert "manifest base_revision does not match expected base" in failures


def test_manifest_verification_rejects_omitted_candidate(tmp_path: Path) -> None:
    policy_path, manifest_path = _snapshot_repo(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"] = []
    manifest["file_count"] = 0
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    failures = provenance.verify_manifest(tmp_path, manifest_path, policy_path)

    assert "manifest files are incomplete, duplicated, or unsorted" in failures
    assert "manifest file_count does not match policy candidates" in failures


def test_repository_reader_refuses_path_escape(tmp_path: Path) -> None:
    with pytest.raises(provenance.ProvenanceError, match="unsafe repository path"):
        provenance.read_repository_file(tmp_path, "../outside.py")


def test_cli_has_no_effectful_apply_or_output_command() -> None:
    with pytest.raises(SystemExit):
        provenance.parse_args(["apply"])
    with pytest.raises(SystemExit):
        provenance.parse_args(["manifest", "--target-ref", "main"])
