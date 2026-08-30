# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import inspect

import daedalus.runtimes.provider_invocation as provider_invocation


def test_invocation_subject_module_is_non_executing_identity_only() -> None:
    source = inspect.getsource(provider_invocation)
    tree = ast.parse(source)
    forbidden_import_roots = {
        "asyncio",
        "httpx",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                called.add(node.func.id)
            elif isinstance(node.func, ast.Attribute):
                called.add(node.func.attr)
    assert imported.isdisjoint(forbidden_import_roots)
    assert {"exec", "eval", "compile", "system", "popen"}.isdisjoint(called)
    assert "Callable" not in source
    assert "ProviderInvocationSubject" in provider_invocation.__all__


def test_exact_subject_contains_every_required_binding_dimension() -> None:
    fields = {
        field.name
        for field in provider_invocation.dataclasses.fields(
            provider_invocation.ProviderInvocationSubject
        )
    }
    assert fields == {
        "provider_id",
        "adapter_id",
        "adapter_artifact_sha256",
        "adapter_config_sha256",
        "entrypoint_id",
        "runtime_id",
        "execution_id",
        "idempotency_key",
        "execution_request_sha256",
        "lease_sha256",
        "source_revision",
    }


def test_subject_digest_is_canonical_and_not_caller_supplied() -> None:
    source = inspect.getsource(provider_invocation.ProviderInvocationSubject)
    assert "def digest" in source
    assert "canonical_sha(self.to_dict())" in source
    assert "digest:" not in source
