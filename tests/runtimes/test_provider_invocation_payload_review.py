# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
from pathlib import Path


MODULE = Path("daedalus/runtimes/provider_invocation_payload.py")


def test_payload_boundary_remains_non_executing_and_non_authorizing() -> None:
    source = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported_roots: set[str] = set()
    called_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called_names.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called_names.add(node.func.attr)

    assert not imported_roots.intersection(
        {"subprocess", "socket", "requests", "httpx", "urllib", "importlib"}
    )
    assert not called_names.intersection(
        {
            "run_runtime_provider",
            "begin_effect",
            "grant",
            "bind_start",
            "Popen",
            "run",
            "system",
            "exec",
            "eval",
            "__import__",
        }
    )


def test_payload_receipt_keeps_execution_claims_false() -> None:
    source = MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    text = ast.unparse(tree)

    assert '"provider_execution_allowed": False' in source
    assert '"effect_start_authorized": False' in source
    assert '"callback_seam_removed": False' in source
    assert "ProviderInvocationObservationAuthority" not in text
    assert "RuntimeBoundEffectAuthorization" not in text
