#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Run bounded adversarial mutations against source-anchor semantics."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/repository_write_source_anchor_semantics.py"
TEST_FILE = "tests/gates/test_repository_write_source_anchor_semantics.py"
MUTATIONS = {
    "forge-complete-semantics": (
        '"semantic_receipts_verified": False',
        '"semantic_receipts_verified": True',
        "test_source_anchor_semantics_bind_authenticated_origin_and_exact_source",
    ),
    "forge-evidence-authentication": (
        '"evidence_authenticated": False',
        '"evidence_authenticated": True',
        "test_source_anchor_semantics_bind_authenticated_origin_and_exact_source",
    ),
    "forge-gate-binding": (
        '"gate_report_bound": False',
        '"gate_report_bound": True',
        "test_source_anchor_semantics_bind_authenticated_origin_and_exact_source",
    ),
    "forge-closed": (
        '"closed": False',
        '"closed": True',
        "test_source_anchor_semantics_bind_authenticated_origin_and_exact_source",
    ),
    "allow-multiple-anchors": (
        "if len(source_bindings) != 1:",
        "if False and len(source_bindings) != 1:",
        "test_every_classification_requires_exactly_one_anchor",
    ),
    "ignore-position-binding": (
        "if (\n            path != row.surface.path\n            or line != row.surface.line\n            or column != row.surface.column\n        ):",
        "if False and (\n            path != row.surface.path\n            or line != row.surface.line\n            or column != row.surface.column\n        ):",
        "test_payload_position_must_equal_the_classified_surface",
    ),
    "ignore-source-digest": (
        "if hashlib.sha256(source).hexdigest() != source_sha256:",
        "if False and hashlib.sha256(source).hexdigest() != source_sha256:",
        "test_changed_source_bytes_refuse_after_origin_authentication",
    ),
    "allow-whitespace-position": (
        "if selected[column : column + 1].isspace():",
        "if False and selected[column : column + 1].isspace():",
        "test_anchor_must_point_to_a_non_whitespace_byte",
    ),
    "allow-symlink-component": (
        "if stat.S_ISLNK(component.st_mode):",
        "if False and stat.S_ISLNK(component.st_mode):",
        "test_symlink_file_or_parent_is_refused",
    ),
    "ignore-chain-mismatch": (
        "if mismatches:",
        "if False and mismatches:",
        "test_cross_layer_digest_chain_cannot_be_detached",
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
    print(f"killed {len(MUTATIONS)} source-anchor semantic mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
