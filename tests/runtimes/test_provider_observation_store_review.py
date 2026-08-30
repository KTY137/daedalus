# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import daedalus.runtimes.provider_observation_store as store_module


SOURCE_PATH = Path(inspect.getsourcefile(store_module) or "")
SOURCE = SOURCE_PATH.read_text(encoding="utf-8")
TREE = ast.parse(SOURCE)


def _definition(name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef:
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


def test_module_has_no_provider_effect_or_promotion_authority() -> None:
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
    forbidden_imports = {
        "subprocess",
        "socket",
        "requests",
        "urllib",
        "git",
        "pygit2",
    }
    assert not (imports | imported_from) & forbidden_imports
    assert "run_runtime_provider" not in SOURCE
    assert "begin_effect" not in SOURCE
    assert "OwnerApproval" not in SOURCE
    assert "PromotionReceipt" not in SOURCE
    assert "closed = True" not in SOURCE
    assert "closed=True" not in SOURCE


def test_compatibility_constructor_cannot_initialize_or_repair_store() -> None:
    cls = _definition("PreprovisionedProviderObservationBindingLedger")
    constructor = next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    )
    calls = _calls(constructor)
    assert "super" not in calls
    assert not any(name.endswith("._initialize") for name in calls)
    assert not any(name.endswith(".mkdir") for name in calls)
    assert "sqlite3.connect" not in calls
    assert "inspect_provider_observation_binding_store" in calls


def test_normal_connections_are_existing_store_only_and_replay_is_read_only() -> None:
    opener = _definition("_open_sqlite")
    opener_source = ast.get_source_segment(SOURCE, opener) or ""
    assert 'mode not in {"ro", "rw"}' in opener_source
    assert "sqlite3.connect" in _calls(opener)
    assert "?mode={mode}" in opener_source
    assert "rwc" not in opener_source
    assert "PRAGMA query_only=ON" in opener_source

    cls = _definition("PreprovisionedProviderObservationBindingLedger")
    reader = next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "_connect_read_only"
    )
    writer = next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "_connect"
    )
    load = next(
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "load"
    )
    reader_source = ast.get_source_segment(SOURCE, reader) or ""
    writer_source = ast.get_source_segment(SOURCE, writer) or ""
    assert 'mode="ro"' in reader_source
    assert "query_only=True" in reader_source
    assert 'mode="rw"' in writer_source
    assert "query_only=False" in writer_source
    assert "self._connect_read_only" in _calls(load)
    assert "self._connect" not in _calls(load)


def test_initializer_is_the_only_schema_writer_and_publishes_without_clobber() -> None:
    initializer = _definition("initialize_provider_observation_binding_store")
    calls = _calls(initializer)
    assert "tempfile.mkstemp" in calls
    assert "os.link" in calls
    assert "inspect_provider_observation_binding_store" in calls
    assert "_fsync_file" in calls
    assert "_fsync_directory" in calls

    schema_create_calls = []
    for node in ast.walk(TREE):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute) or node.func.attr != "execute":
            continue
        if not node.args:
            continue
        argument = node.args[0]
        if isinstance(argument, ast.Name) and argument.id in {
            "_BINDINGS_SQL",
            "_METADATA_SQL",
        }:
            schema_create_calls.append(node)
    assert len(schema_create_calls) == 2
    initializer_nodes = set(ast.walk(initializer))
    assert all(call in initializer_nodes for call in schema_create_calls)

    call_nodes = [
        node
        for node in ast.walk(initializer)
        if isinstance(node, ast.Call)
    ]
    link_line = min(
        node.lineno for node in call_nodes if _call_name(node) == "os.link"
    )
    unlink_line = min(
        node.lineno for node in call_nodes if _call_name(node) == "temporary.unlink"
    )
    inspect_line = min(
        node.lineno
        for node in call_nodes
        if _call_name(node) == "inspect_provider_observation_binding_store"
    )
    assert link_line < unlink_line < inspect_line


def test_exact_revision_target_and_primary_checkout_fences_are_structural() -> None:
    target = _definition("ProviderObservationStoreTarget")
    target_source = ast.get_source_segment(SOURCE, target) or ""
    assert "_revision" in target_source
    assert "_validated_target_path" in target_source
    assert "canonical_sha" in target_source

    validator = _definition("_validated_target_path")
    validator_source = ast.get_source_segment(SOURCE, validator) or ""
    assert "_roots_overlap" in validator_source
    assert "_is_within" in validator_source
    assert "Primary Checkout" in validator_source
    assert "st_nlink != 1" in validator_source
    assert "is_symlink" in validator_source

    verifier = _definition("_verify_schema")
    verifier_source = ast.get_source_segment(SOURCE, verifier) or ""
    assert "target.digest" in verifier_source
    assert "target.source_revision" in verifier_source
    assert "SCHEMA_SHA256" in verifier_source
    assert "metadata cardinality" in verifier_source


def test_sidecars_identity_and_cleanup_are_fail_closed() -> None:
    sidecars = _definition("_refuse_existing_sidecars")
    sidecar_source = ast.get_source_segment(SOURCE, sidecars) or ""
    assert '"-journal"' in sidecar_source
    assert '"-wal"' in sidecar_source
    assert '"-shm"' in sidecar_source
    assert "os.path.lexists" in _calls(sidecars)

    identity = _definition("_same_identity")
    identity_source = ast.get_source_segment(SOURCE, identity) or ""
    assert "st_dev" in identity_source
    assert "st_ino" in identity_source
    assert "stat.S_ISREG" in _calls(identity)

    initializer = _definition("initialize_provider_observation_binding_store")
    initializer_source = ast.get_source_segment(SOURCE, initializer) or ""
    assert "published_identity is not None" in initializer_source
    assert "_same_identity" in initializer_source
