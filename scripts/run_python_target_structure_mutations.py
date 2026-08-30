#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Run bounded mutations against structural Python target resolution."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/python_target_structure.py"
TEST_FILE = "tests/gates/test_python_target_structure.py"
MUTATIONS = {
    "allow-malformed-target": (
        "if match is None:",
        "if False and match is None:",
        "test_target_grammar_is_strict",
    ),
    "ignore-source-digest": (
        "if snapshot.source_sha256 != expected_source_sha256:",
        "if False and snapshot.source_sha256 != expected_source_sha256:",
        "test_stale_source_digest_fails_before_ast_projection",
    ),
    "ignore-missing-definition": (
        "if not matches:",
        "if False and not matches:",
        "test_missing_definition_fails",
    ),
    "ignore-ambiguous-definition": (
        "if len(matches) != 1:",
        "if False and len(matches) != 1:",
        "test_duplicate_definition_chain_is_ambiguous",
    ),
    "allow-function-parent": (
        "if not isinstance(selected, ast.ClassDef):",
        "if False and not isinstance(selected, ast.ClassDef):",
        "test_only_classes_may_contain_qualified_children",
    ),
    "forge-behavior": (
        '"behavior_verified": False',
        '"behavior_verified": True',
        "test_structural_target_binds_exact_source_without_execution",
    ),
    "forge-execution": (
        '"executed": False',
        '"executed": True',
        "test_structural_target_binds_exact_source_without_execution",
    ),
    "detach-chain-terminal": (
        "if self.chain_kinds[-1] != self.definition_kind:",
        "if False and self.chain_kinds[-1] != self.definition_kind:",
        "test_structure_rejects_detached_chain_terminal",
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
    print(f"killed {len(MUTATIONS)} Python-target mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
