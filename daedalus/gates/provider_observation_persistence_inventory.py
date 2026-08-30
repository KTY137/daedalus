# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Revision-bound inventory delta for provider-observation persistence.

The provider-observation authority introduced a durable SQLite binding ledger.
This module makes every currently known filesystem/SQLite mutation path in that
ledger explicit and machine-readable.  It is discovery evidence only: it does
not authorize a write, prove checkout disjointness, implement a guard contract,
or integrate the rows into the canonical Gate-0 inventory.
"""
from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable

from daedalus.spine.envelope import canonical_json


_SOURCE_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SOURCE_PATH = "daedalus/runtimes/provider_observation.py"
_MAX_SOURCE_BYTES = 2 * 1024 * 1024


class ProviderObservationPersistenceInventoryError(RuntimeError):
    """The persistence inventory could not be produced without ambiguity."""


@dataclass(frozen=True, order=True)
class ProviderObservationPersistenceSurface:
    function: str
    line: int
    column: int
    kind: str
    callee: str
    operation: str
    externally_reachable_via: str

    def __post_init__(self) -> None:
        if not self.function or any(ch.isspace() for ch in self.function):
            raise ValueError("surface function is invalid")
        if type(self.line) is not int or type(self.column) is not int:
            raise ValueError("surface position must use strict integers")
        if self.line < 1 or self.column < 0:
            raise ValueError("surface position is invalid")
        if self.kind not in {
            "implicit_bootstrap",
            "filesystem_create",
            "sqlite_create_or_write",
            "sqlite_transaction_write",
            "read_path_create_capable",
            "transitive_read_path_create_capable",
        }:
            raise ValueError("surface kind is invalid")
        for label, value in (
            ("callee", self.callee),
            ("operation", self.operation),
            ("externally_reachable_via", self.externally_reachable_via),
        ):
            if not value or any(ch in value for ch in "\r\n"):
                raise ValueError(f"surface {label} is invalid")

    @property
    def blocking(self) -> bool:
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": _SOURCE_PATH,
            "function": self.function,
            "line": self.line,
            "column": self.column,
            "kind": self.kind,
            "callee": self.callee,
            "operation": self.operation,
            "externally_reachable_via": self.externally_reachable_via,
            "wiring": "inventory_only",
            "guard_contract_bound": False,
            "primary_checkout_target_proven": False,
            "blocking": True,
        }


@dataclass(frozen=True)
class ProviderObservationPersistenceInventory:
    source_revision: str
    source_sha256: str
    source_size: int
    surfaces: tuple[ProviderObservationPersistenceSurface, ...]

    def __post_init__(self) -> None:
        if not _SOURCE_REVISION.fullmatch(self.source_revision):
            raise ValueError("source_revision must be a lowercase 40-hex commit")
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_sha256):
            raise ValueError("source_sha256 must be lowercase sha256")
        if type(self.source_size) is not int or not (1 <= self.source_size <= _MAX_SOURCE_BYTES):
            raise ValueError("source_size is invalid")
        if not isinstance(self.surfaces, tuple) or not self.surfaces:
            raise ValueError("surfaces must be a non-empty immutable tuple")
        if self.surfaces != tuple(sorted(self.surfaces)):
            raise ValueError("surfaces must be sorted")
        if len(set(self.surfaces)) != len(self.surfaces):
            raise ValueError("surfaces must be unique")
        positions = {(row.line, row.column) for row in self.surfaces}
        if len(positions) != len(self.surfaces):
            raise ValueError("surface source positions must be unique")

    @property
    def blockers(self) -> tuple[ProviderObservationPersistenceSurface, ...]:
        return self.surfaces

    @property
    def closed(self) -> bool:
        return False

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-gate0-provider-observation-persistence-inventory/1",
            "source_revision": self.source_revision,
            "source_path": _SOURCE_PATH,
            "source_sha256": self.source_sha256,
            "source_size": self.source_size,
            "surfaces": [row.to_dict() for row in self.surfaces],
            "surface_count": len(self.surfaces),
            "blocker_count": len(self.blockers),
            "closed": False,
            "inventory_only": True,
            "canonical_inventory_integrated": False,
            "guard_contracts_complete": False,
            "primary_checkout_mutation_excluded": False,
            "blockers": [
                "provider-observation-persistence-surfaces-not-canonically-registered",
                "provider-observation-persistence-surfaces-not-guarded",
                "provider-observation-read-path-can-create-sqlite-file",
                "provider-observation-primary-checkout-target-not-excluded",
            ],
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(canonical_json(self._payload()).encode("ascii")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "digest": self.digest}


def _syntactic_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _syntactic_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _literal_text(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _class_methods(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    classes = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ProviderObservationBindingLedger"
    ]
    if len(classes) != 1:
        raise ProviderObservationPersistenceInventoryError(
            "expected exactly one ProviderObservationBindingLedger class"
        )
    methods: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in classes[0].body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in methods:
                raise ProviderObservationPersistenceInventoryError(
                    f"duplicate ledger method: {node.name}"
                )
            methods[node.name] = node
    required = {"__init__", "_connect", "_initialize", "bind_start", "load", "require_bound"}
    missing = sorted(required - methods.keys())
    if missing:
        raise ProviderObservationPersistenceInventoryError(
            "required ledger methods are missing: " + ", ".join(missing)
        )
    return methods


def _matching_calls(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    predicate: Callable[[ast.Call], bool],
) -> list[ast.Call]:
    return sorted(
        (node for node in ast.walk(method) if isinstance(node, ast.Call) and predicate(node)),
        key=lambda node: (node.lineno, node.col_offset),
    )


def _exact_call(
    method: ast.FunctionDef | ast.AsyncFunctionDef,
    *,
    label: str,
    predicate: Callable[[ast.Call], bool],
) -> ast.Call:
    matches = _matching_calls(method, predicate)
    if len(matches) != 1:
        raise ProviderObservationPersistenceInventoryError(
            f"expected exactly one {label} call in {method.name}, found {len(matches)}"
        )
    return matches[0]


def _callee_is(name: str) -> Callable[[ast.Call], bool]:
    return lambda call: _syntactic_name(call.func) == name


def _execute_sql(prefix: str) -> Callable[[ast.Call], bool]:
    normalized_prefix = " ".join(prefix.upper().split())

    def matches(call: ast.Call) -> bool:
        callee = _syntactic_name(call.func)
        if callee is None or not callee.endswith(".execute") or not call.args:
            return False
        raw = _literal_text(call.args[0])
        if raw is None:
            return False
        normalized = " ".join(raw.upper().split())
        return normalized.startswith(normalized_prefix)

    return matches


def _surface(
    node: ast.Call,
    *,
    function: str,
    kind: str,
    callee: str,
    operation: str,
    externally_reachable_via: str,
) -> ProviderObservationPersistenceSurface:
    return ProviderObservationPersistenceSurface(
        function=function,
        line=node.lineno,
        column=node.col_offset,
        kind=kind,
        callee=callee,
        operation=operation,
        externally_reachable_via=externally_reachable_via,
    )


def _discover_surfaces(tree: ast.Module) -> tuple[ProviderObservationPersistenceSurface, ...]:
    methods = _class_methods(tree)
    rows: list[ProviderObservationPersistenceSurface] = []

    constructor_initialize = _exact_call(
        methods["__init__"], label="implicit initializer", predicate=_callee_is("self._initialize")
    )
    rows.append(
        _surface(
            constructor_initialize,
            function="ProviderObservationBindingLedger.__init__",
            kind="implicit_bootstrap",
            callee="self._initialize",
            operation="constructor-implicitly-creates-parent-database-and-schema",
            externally_reachable_via="ProviderObservationBindingLedger(...)"
        )
    )

    sqlite_connect = _exact_call(
        methods["_connect"], label="sqlite connect", predicate=_callee_is("sqlite3.connect")
    )
    rows.append(
        _surface(
            sqlite_connect,
            function="ProviderObservationBindingLedger._connect",
            kind="sqlite_create_or_write",
            callee="sqlite3.connect",
            operation="default-read-write-create-mode",
            externally_reachable_via="constructor,bind_start,load,require_bound",
        )
    )

    parent_mkdir = _exact_call(
        methods["_initialize"],
        label="parent mkdir",
        predicate=_callee_is("self.path.parent.mkdir"),
    )
    rows.append(
        _surface(
            parent_mkdir,
            function="ProviderObservationBindingLedger._initialize",
            kind="filesystem_create",
            callee="Path.mkdir",
            operation="parents=true,exist_ok=true",
            externally_reachable_via="ProviderObservationBindingLedger(...)"
        )
    )

    create_schema = _exact_call(
        methods["_initialize"],
        label="schema creation",
        predicate=_execute_sql("CREATE TABLE IF NOT EXISTS provider_observation_bindings"),
    )
    rows.append(
        _surface(
            create_schema,
            function="ProviderObservationBindingLedger._initialize",
            kind="sqlite_create_or_write",
            callee="Connection.execute",
            operation="create-provider-observation-bindings-schema",
            externally_reachable_via="ProviderObservationBindingLedger(...)"
        )
    )

    bind_connect = _exact_call(
        methods["bind_start"], label="binding connect", predicate=_callee_is("self._connect")
    )
    rows.append(
        _surface(
            bind_connect,
            function="ProviderObservationBindingLedger.bind_start",
            kind="sqlite_create_or_write",
            callee="self._connect",
            operation="open-default-read-write-create-connection",
            externally_reachable_via="run_runtime_provider(fresh-start)"
        )
    )

    for label, prefix, operation in (
        ("begin immediate", "BEGIN IMMEDIATE", "begin-immediate-writer-transaction"),
        ("retained rollback", "ROLLBACK", "rollback-idempotent-existing-binding"),
        (
            "binding insert",
            "INSERT INTO provider_observation_bindings",
            "insert-authenticated-provider-observation-binding",
        ),
    ):
        call = _exact_call(methods["bind_start"], label=label, predicate=_execute_sql(prefix))
        rows.append(
            _surface(
                call,
                function="ProviderObservationBindingLedger.bind_start",
                kind="sqlite_transaction_write",
                callee="Connection.execute",
                operation=operation,
                externally_reachable_via="run_runtime_provider(fresh-start)",
            )
        )

    commit = _exact_call(
        methods["bind_start"], label="binding commit", predicate=_callee_is("connection.commit")
    )
    rows.append(
        _surface(
            commit,
            function="ProviderObservationBindingLedger.bind_start",
            kind="sqlite_transaction_write",
            callee="Connection.commit",
            operation="commit-authenticated-provider-observation-binding",
            externally_reachable_via="run_runtime_provider(fresh-start)",
        )
    )

    load_connect = _exact_call(
        methods["load"], label="load connect", predicate=_callee_is("self._connect")
    )
    rows.append(
        _surface(
            load_connect,
            function="ProviderObservationBindingLedger.load",
            kind="read_path_create_capable",
            callee="self._connect",
            operation="nominal-read-can-create-empty-sqlite-file",
            externally_reachable_via="load,require_bound,reconcile_runtime_provider_unknown",
        )
    )

    require_load = _exact_call(
        methods["require_bound"], label="require-bound load", predicate=_callee_is("self.load")
    )
    rows.append(
        _surface(
            require_load,
            function="ProviderObservationBindingLedger.require_bound",
            kind="transitive_read_path_create_capable",
            callee="self.load",
            operation="replay-and-recovery-read-transitively-can-create-sqlite-file",
            externally_reachable_via="run_runtime_provider(replay),reconcile_runtime_provider_unknown",
        )
    )

    return tuple(sorted(rows))


def scan_provider_observation_persistence(
    repository_root: str | Path,
    *,
    source_revision: str,
) -> ProviderObservationPersistenceInventory:
    """Inventory the exact persistence paths without granting any authority."""

    if not isinstance(source_revision, str) or not _SOURCE_REVISION.fullmatch(source_revision):
        raise ProviderObservationPersistenceInventoryError(
            "source_revision must be a lowercase 40-hex commit"
        )
    root = Path(repository_root)
    source_path = root / _SOURCE_PATH
    try:
        if source_path.is_symlink():
            raise ProviderObservationPersistenceInventoryError(
                "provider observation source must not be a symlink"
            )
        raw = source_path.read_bytes()
    except ProviderObservationPersistenceInventoryError:
        raise
    except OSError as exc:
        raise ProviderObservationPersistenceInventoryError(
            "provider observation source could not be read"
        ) from exc
    if not raw or len(raw) > _MAX_SOURCE_BYTES:
        raise ProviderObservationPersistenceInventoryError(
            "provider observation source size is invalid"
        )
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProviderObservationPersistenceInventoryError(
            "provider observation source is not UTF-8"
        ) from exc
    try:
        tree = ast.parse(source, filename=_SOURCE_PATH)
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise ProviderObservationPersistenceInventoryError(
            "provider observation source could not be parsed"
        ) from exc
    surfaces = _discover_surfaces(tree)
    return ProviderObservationPersistenceInventory(
        source_revision=source_revision,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        source_size=len(raw),
        surfaces=surfaces,
    )


__all__ = [
    "ProviderObservationPersistenceInventory",
    "ProviderObservationPersistenceInventoryError",
    "ProviderObservationPersistenceSurface",
    "scan_provider_observation_persistence",
]
