# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import daedalus.runtimes.provider_invocation_registry as registry_module


SOURCE_PATH = Path(inspect.getsourcefile(registry_module) or "")
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _definition(name: str):
    matches = [
        node
        for node in ast.walk(TREE)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
        and node.name == name
    ]
    assert len(matches) == 1, name
    return matches[0]


def _call_name(call: ast.Call) -> str:
    parts: list[str] = []
    node: ast.AST = call.func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def _calls(node: ast.AST) -> tuple[str, ...]:
    return tuple(
        _call_name(item)
        for item in ast.walk(node)
        if isinstance(item, ast.Call)
    )


def test_registry_manifest_has_no_execution_or_loading_authority() -> None:
    forbidden_imports = {
        "subprocess",
        "socket",
        "requests",
        "urllib",
        "httpx",
        "aiohttp",
        "importlib",
        "ctypes",
        "sqlite3",
    }
    imports = {
        alias.name
        for node in TREE.body
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_from = {
        node.module or ""
        for node in TREE.body
        if isinstance(node, ast.ImportFrom)
    }
    assert not (imports | imported_from) & forbidden_imports
    assert "Callable" not in SOURCE
    assert "callback" in SOURCE  # explicit non-authority documentation
    assert "invoke(" not in SOURCE
    assert "exec(" not in SOURCE
    assert "eval(" not in SOURCE
    assert "begin_effect" not in SOURCE
    assert "OwnerApproval" not in SOURCE
    assert "PromotionReceipt" not in SOURCE


def test_descriptor_binds_provider_adapter_implementation_and_artifact() -> None:
    cls = _definition("ProviderAdapterDescriptor")
    fields = {
        node.target.id
        for node in cls.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
    }
    assert fields == {
        "provider_id",
        "adapter_id",
        "implementation_id",
        "adapter_artifact_sha256",
        "adapter_config_sha256",
        "entrypoint_id",
        "runtime_id",
        "source_revision",
    }
    constructor = next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "__post_init__"
    )
    constructor_source = ast.get_source_segment(SOURCE, constructor) or ""
    assert "_identifier" in _calls(constructor)
    assert "_sha256" in _calls(constructor)
    assert "_revision" in _calls(constructor)
    assert "implementation_id" in constructor_source


def test_manifest_requires_canonical_unique_provider_mapping_and_revision() -> None:
    cls = _definition("ProviderInvocationRegistryManifest")
    constructor = next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "__post_init__"
    )
    source = ast.get_source_segment(SOURCE, constructor) or ""
    assert "type(self.descriptors) is not tuple" in source
    assert "type(item) is not ProviderAdapterDescriptor" in source
    assert "sorted(self.descriptors" in source
    assert "len(set(provider_ids)) != len(provider_ids)" in source
    assert "item.source_revision != self.source_revision" in source


def test_registry_digest_covers_implementation_identity_and_all_descriptors() -> None:
    descriptor = _definition("ProviderAdapterDescriptor")
    descriptor_to_dict = next(
        node
        for node in descriptor.body
        if isinstance(node, ast.FunctionDef) and node.name == "to_dict"
    )
    assert "dataclasses.asdict" in _calls(descriptor_to_dict)

    manifest = _definition("ProviderInvocationRegistryManifest")
    manifest_to_dict = next(
        node
        for node in manifest.body
        if isinstance(node, ast.FunctionDef) and node.name == "to_dict"
    )
    source = ast.get_source_segment(SOURCE, manifest_to_dict) or ""
    assert "item.to_dict" in source
    assert "source_revision" in source
    assert "registry_id" in source

    digest = next(
        node
        for node in manifest.body
        if isinstance(node, ast.FunctionDef) and node.name == "digest"
    )
    assert "self.to_dict" in _calls(digest)
    assert "canonical_sha" in _calls(digest)


def test_resolution_uses_provider_lookup_then_every_subject_static_field() -> None:
    descriptor = _definition("ProviderAdapterDescriptor")
    mismatch = next(
        node
        for node in descriptor.body
        if isinstance(node, ast.FunctionDef) and node.name == "mismatch_fields"
    )
    source = ast.get_source_segment(SOURCE, mismatch) or ""
    for field in (
        "provider_id",
        "adapter_id",
        "adapter_artifact_sha256",
        "adapter_config_sha256",
        "entrypoint_id",
        "runtime_id",
        "source_revision",
    ):
        assert field in source
    assert "type(subject) is not ProviderInvocationSubject" in source

    manifest = _definition("ProviderInvocationRegistryManifest")
    resolve = next(
        node
        for node in manifest.body
        if isinstance(node, ast.FunctionDef) and node.name == "resolve"
    )
    calls = _calls(resolve)
    assert "self.descriptor_for_provider" in calls
    assert "descriptor.mismatch_fields" in calls
    assert "type(subject) is not ProviderInvocationSubject" in (
        ast.get_source_segment(SOURCE, resolve) or ""
    )


def test_exact_parse_shape_and_noncanonical_builder_boundary_are_separate() -> None:
    manifest = _definition("ProviderInvocationRegistryManifest")
    parser = next(
        node
        for node in manifest.body
        if isinstance(node, ast.FunctionDef) and node.name == "from_dict"
    )
    parser_source = ast.get_source_segment(SOURCE, parser) or ""
    assert "set(payload) != expected" in parser_source
    assert "descriptors must be a list" in parser_source
    assert "ProviderAdapterDescriptor.from_dict" in parser_source

    builder = _definition("build_provider_invocation_registry_manifest")
    builder_source = ast.get_source_segment(SOURCE, builder) or ""
    assert "isinstance(descriptors, (str, bytes, Mapping))" in builder_source
    assert "type(item) is not ProviderAdapterDescriptor" in builder_source
    assert "sorted(rows" in builder_source


def test_public_surface_is_manifest_only() -> None:
    assert set(registry_module.__all__) == {
        "ProviderAdapterDescriptor",
        "ProviderInvocationRegistryError",
        "ProviderInvocationRegistryManifest",
        "ProviderInvocationRegistryResolutionError",
        "ProviderInvocationRegistryShapeError",
        "build_provider_invocation_registry_manifest",
    }
