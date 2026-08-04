#!/usr/bin/env python3
"""Run bounded mutations against exact repository-tree reads."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/repository_tree.py"
TEST_FILE = "tests/gates/test_repository_tree.py"
MUTATIONS = {
    "allow-drive-path": (
        r"(?![A-Za-z]:/)",
        "",
        "test_path_grammar_fails_closed",
    ),
    "allow-symlink-component": (
        "if stat.S_ISLNK(component.st_mode):",
        "if False and stat.S_ISLNK(component.st_mode):",
        "test_symlink_root_file_and_parent_are_refused",
    ),
    "ignore-before-open-identity": (
        "if (before.st_dev, before.st_ino, before.st_size) != (",
        "if False and (before.st_dev, before.st_ino, before.st_size) != (",
        "test_file_replacement_before_open_is_detected",
    ),
    "ignore-read-identity": (
        "if (\n        identity_before != identity_after\n        or identity_after != identity_path\n    ):",
        "if False and (\n        identity_before != identity_after\n        or identity_after != identity_path\n    ):",
        "test_descriptor_identity_change_is_detected",
    ),
    "ignore-incomplete-read": (
        "if len(source) != before.st_size:",
        "if False and len(source) != before.st_size:",
        "test_incomplete_descriptor_read_is_detected",
    ),
    "allow-invalid-utf8": (
        'source.decode("utf-8", errors="strict")',
        'source.decode("utf-8", errors="ignore")',
        "test_nul_and_non_utf8_sources_are_refused",
    ),
    "allow-nul-source": (
        'if b"\\x00" in source:',
        'if False and b"\\x00" in source:',
        "test_nul_and_non_utf8_sources_are_refused",
    ),
    "detach-snapshot-digest": (
        "if self.source_sha256 != expected:",
        "if False and self.source_sha256 != expected:",
        "test_snapshot_rejects_detached_digest_or_size",
    ),
}


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    survivors: list[str] = []
    timeouts: list[str] = []
    try:
        for name, (needle, replacement, test_name) in MUTATIONS.items():
            count = original.count(needle)
            if count != 1:
                raise RuntimeError(
                    f"mutation {name} expected one source anchor, found {count}"
                )
            TARGET.write_text(
                original.replace(needle, replacement),
                encoding="utf-8",
            )
            try:
                completed = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "-q",
                        f"{TEST_FILE}::{test_name}",
                    ],
                    cwd=ROOT,
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                    env={
                        **os.environ,
                        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                    },
                )
            except subprocess.TimeoutExpired:
                timeouts.append(name)
            else:
                if completed.returncode == 0:
                    survivors.append(name)
            finally:
                TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")
    if survivors or timeouts:
        if survivors:
            print("surviving mutations: " + ", ".join(survivors), file=sys.stderr)
        if timeouts:
            print("timed-out mutations: " + ", ".join(timeouts), file=sys.stderr)
        return 1
    print(f"killed {len(MUTATIONS)} repository-tree mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
