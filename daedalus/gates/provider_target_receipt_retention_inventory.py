"""Revision- and byte-bound inventory for provider-target receipt retention.

The retained-receipt ledger introduced explicit Event-Store, SQLite schema, and
CAS writes. This scanner makes every currently known effectful call site in that
module machine-readable. It is discovery evidence only: it does not register an
entrypoint, bind a guard contract, consume an Effect Lease, or authorize a write.
"""
from __future__ import annotations

import ast
import hashlib
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from daedalus.spine.envelope import canonical_json

_SOURCE_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SOURCE_PATH = "daedalus/runtimes/provider_target_receipt_ledger.py"
_MAX_SOURCE_BYTES = 2 * 1024 * 1024


class ProviderTargetReceiptRetentionInventoryError(RuntimeError):
    """The retention inventory could not be produced without ambiguity."""


@dataclass(frozen=True, order=True)
class ProviderTargetReceiptRetentionSurface:
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
            "schema_write",
            "event_store_write",
            "cas_write",
            "transitive_effectful_call",
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
            "effect_lease_consumed": False,
            "primary_checkout_target_proven": False,
            "blocking": True,
        }


@dataclass(frozen=True)
class ProviderTargetReceiptRetentionInventory:
    source_revision: str
    source_sha256: str
    source_size: int
    surfaces: tuple[ProviderTargetReceiptRetentionSurface, ...]

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
    def blockers(self) -> tuple[ProviderTargetReceiptRetentionSurface, ...]:
        return self.surfaces

    @property
    def closed(self) -> bool:
        return False

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-gate0-provider-target-receipt-retention-inventory/1",
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
            "effect_lease_semantics_verified": False,
            "primary_checkout_mutation_excluded": False,
            "blockers": [
                "provider-target-receipt-retention-surfaces-not-canonically-registered",
                "provider-target-receipt-retention-surfaces-not-guarded",
                "provider-target-receipt-retention-effect-lease-not-consumed",
                "provider-target-receipt-retention-primary-checkout-target-not-proven",
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


def _class_methods(tree: ast.Module) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    classes = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ProviderTargetReceiptLedger"
    ]
    if len(classes) != 1:
        raise ProviderTargetReceiptRetentionInventoryError(
            "expected exactly one ProviderTargetReceiptLedger class"
        )
    methods: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for node in classes[0].body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name in methods:
                raise ProviderTargetReceiptRetentionInventoryError(
                    f"duplicate retention method: {node.name}"
                )
            methods[node.name] = node
    required = {
        "_install_single_receipt_invariant",
        "_record_or_recover_intent",
        "retain",
    }
    missing = sorted(required - methods.keys())
    if missing:
        raise ProviderTargetReceiptRetentionInventoryError(
            "required retention methods are missing: " + ", ".join(missing)
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
        raise ProviderTargetReceiptRetentionInventoryError(
            f"expected exactly one {label} call in {method.name}, found {len(matches)}"
        )
    return matches[0]


def _callee_is(name: str) -> Callable[[ast.Call], bool]:
    return lambda call: _syntactic_name(call.func) == name


def _execute_name_argument(name: str) -> Callable[[ast.Call], bool]:
    def matches(call: ast.Call) -> bool:
        if _syntactic_name(call.func) != "connection.execute" or not call.args:
            return False
        return isinstance(call.args[0], ast.Name) and call.args[0].id == name

    return matches


def _surface(
    node: ast.Call,
    *,
    function: str,
    kind: str,
    callee: str,
    operation: str,
    externally_reachable_via: str,
) -> ProviderTargetReceiptRetentionSurface:
    return ProviderTargetReceiptRetentionSurface(
        function=function,
        line=node.lineno,
        column=node.col_offset,
        kind=kind,
        callee=callee,
        operation=operation,
        externally_reachable_via=externally_reachable_via,
    )


def _discover_surfaces(
    tree: ast.Module,
) -> tuple[ProviderTargetReceiptRetentionSurface, ...]:
    methods = _class_methods(tree)
    rows: list[ProviderTargetReceiptRetentionSurface] = []

    invariant_txn = _exact_call(
        methods["_install_single_receipt_invariant"],
        label="schema transaction",
        predicate=_callee_is("self.spine._txn"),
    )
    rows.append(
        _surface(
            invariant_txn,
            function="ProviderTargetReceiptLedger._install_single_receipt_invariant",
            kind="transitive_effectful_call",
            callee="self.spine._txn",
            operation="open-canonical-event-store-writer-transaction",
            externally_reachable_via="ProviderTargetReceiptLedger.retain",
        )
    )

    invariant_write = _exact_call(
        methods["_install_single_receipt_invariant"],
        label="unique-index schema write",
        predicate=_execute_name_argument("expected"),
    )
    rows.append(
        _surface(
            invariant_write,
            function="ProviderTargetReceiptLedger._install_single_receipt_invariant",
            kind="schema_write",
            callee="connection.execute",
            operation="create-or-reverify-partial-unique-index",
            externally_reachable_via="ProviderTargetReceiptLedger.retain",
        )
    )

    record_intent = _exact_call(
        methods["_record_or_recover_intent"],
        label="canonical intent write",
        predicate=_callee_is("self.spine.record_intent"),
    )
    rows.append(
        _surface(
            record_intent,
            function="ProviderTargetReceiptLedger._record_or_recover_intent",
            kind="event_store_write",
            callee="self.spine.record_intent",
            operation="append-receipt-retention-intent",
            externally_reachable_via="ProviderTargetReceiptLedger.retain",
        )
    )

    for label, callee, kind, operation in (
        (
            "invariant wrapper",
            "self._install_single_receipt_invariant",
            "transitive_effectful_call",
            "invoke-schema-invariant-writer",
        ),
        (
            "intent wrapper",
            "self._record_or_recover_intent",
            "transitive_effectful_call",
            "invoke-canonical-intent-writer",
        ),
        (
            "CAS publication",
            "self.source_store.put_bytes",
            "cas_write",
            "publish-authenticated-receipt-bytes",
        ),
        (
            "terminal completion",
            "self.spine.mark_completed",
            "event_store_write",
            "append-receipt-retention-terminal",
        ),
    ):
        call = _exact_call(methods["retain"], label=label, predicate=_callee_is(callee))
        rows.append(
            _surface(
                call,
                function="ProviderTargetReceiptLedger.retain",
                kind=kind,
                callee=callee,
                operation=operation,
                externally_reachable_via="ProviderTargetReceiptLedger.retain",
            )
        )

    return tuple(sorted(rows))


def _read_stable_source(path: Path) -> bytes:
    try:
        before = path.lstat()
    except OSError as exc:
        raise ProviderTargetReceiptRetentionInventoryError(
            "retention source could not be inspected"
        ) from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ProviderTargetReceiptRetentionInventoryError(
            "retention source must be one real regular file"
        )
    try:
        raw = path.read_bytes()
        after = path.lstat()
    except OSError as exc:
        raise ProviderTargetReceiptRetentionInventoryError(
            "retention source could not be read"
        ) from exc
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if before_identity != after_identity or after.st_size != len(raw):
        raise ProviderTargetReceiptRetentionInventoryError(
            "retention source changed during inventory"
        )
    if not raw or len(raw) > _MAX_SOURCE_BYTES:
        raise ProviderTargetReceiptRetentionInventoryError(
            "retention source size is invalid"
        )
    return raw


def scan_provider_target_receipt_retention(
    repository_root: str | os.PathLike[str],
    *,
    source_revision: str,
) -> ProviderTargetReceiptRetentionInventory:
    """Inventory exact retention writes without granting execution authority."""

    if not isinstance(source_revision, str) or not _SOURCE_REVISION.fullmatch(source_revision):
        raise ProviderTargetReceiptRetentionInventoryError(
            "source_revision must be a lowercase 40-hex commit"
        )
    root = Path(repository_root)
    try:
        if root.is_symlink() or not root.is_dir():
            raise ProviderTargetReceiptRetentionInventoryError(
                "repository root must be one real directory"
            )
    except OSError as exc:
        raise ProviderTargetReceiptRetentionInventoryError(
            "repository root could not be inspected"
        ) from exc
    raw = _read_stable_source(root / _SOURCE_PATH)
    if raw.startswith(b"\xef\xbb\xbf") or b"\x00" in raw:
        raise ProviderTargetReceiptRetentionInventoryError(
            "retention source contains forbidden encoding markers"
        )
    try:
        source = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ProviderTargetReceiptRetentionInventoryError(
            "retention source is not strict UTF-8"
        ) from exc
    try:
        tree = ast.parse(source, filename=_SOURCE_PATH)
    except (SyntaxError, ValueError, RecursionError) as exc:
        raise ProviderTargetReceiptRetentionInventoryError(
            "retention source could not be parsed"
        ) from exc
    return ProviderTargetReceiptRetentionInventory(
        source_revision=source_revision,
        source_sha256=hashlib.sha256(raw).hexdigest(),
        source_size=len(raw),
        surfaces=_discover_surfaces(tree),
    )


__all__ = [
    "ProviderTargetReceiptRetentionInventory",
    "ProviderTargetReceiptRetentionInventoryError",
    "ProviderTargetReceiptRetentionSurface",
    "scan_provider_target_receipt_retention",
]
