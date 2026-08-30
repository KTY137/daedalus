# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Deterministic inventory of canonical Event-Store construction sites.

The inventory is deliberately syntax-based and fail-closed. It does not claim
that every dynamic Python call can be resolved. Direct, shadowed or otherwise
ambiguous ``SpineLedger`` construction remains a blocker until it is migrated
or classified by a stronger verifier. The report is bound to one repository
revision and to the exact bytes of every scanned production Python file.
"""
from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .envelope import canonical_json


_SOURCE_REVISION = re.compile(r"^[0-9a-f]{40}$")
_DIRECT_CALLEES = frozenset(
    {
        "daedalus.spine.SpineLedger",
        "daedalus.spine.ledger.SpineLedger",
    }
)
_FACTORY_CALLEES = frozenset(
    {
        "daedalus.spine.open_gate0_spine_writer",
        "daedalus.spine.durability.open_gate0_spine_writer",
    }
)
_TRACKED_TERMINALS = frozenset({"SpineLedger", "open_gate0_spine_writer"})
_BLOCKING_KINDS = frozenset(
    {"legacy_direct", "ambiguous_direct", "ambiguous_binding"}
)
_ALLOWED_KINDS = frozenset(
    {
        "gate0_factory",
        "read_only",
        "legacy_direct",
        "ambiguous_direct",
        "ambiguous_binding",
    }
)


class WriterInventoryError(RuntimeError):
    """The production writer inventory cannot be produced honestly."""


@dataclass(frozen=True, order=True)
class WriterCallsite:
    path: str
    line: int
    column: int
    kind: str
    callee: str

    def __post_init__(self) -> None:
        if not _safe_relative_posix(self.path):
            raise ValueError("writer callsite path must be repository-relative POSIX")
        if self.line < 1 or self.column < 0:
            raise ValueError("writer callsite position is invalid")
        if self.kind not in _ALLOWED_KINDS:
            raise ValueError("unknown writer callsite kind")
        if not self.callee or any(ch.isspace() for ch in self.callee):
            raise ValueError("writer callsite callee is invalid")

    @property
    def blocking(self) -> bool:
        return self.kind in _BLOCKING_KINDS

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "kind": self.kind,
            "callee": self.callee,
            "blocking": self.blocking,
        }


@dataclass(frozen=True)
class WriterInventory:
    source_revision: str
    package_root: str
    scan_input_sha256: str
    files_scanned: int
    callsites: tuple[WriterCallsite, ...]

    def __post_init__(self) -> None:
        if not _SOURCE_REVISION.fullmatch(self.source_revision):
            raise ValueError("source_revision must be a lowercase 40-hex commit")
        if not _safe_relative_posix(self.package_root):
            raise ValueError("package_root must be repository-relative POSIX")
        if not re.fullmatch(r"[0-9a-f]{64}", self.scan_input_sha256):
            raise ValueError("scan_input_sha256 must be lowercase sha256")
        if self.files_scanned < 1:
            raise ValueError("writer inventory must scan at least one file")
        if tuple(sorted(self.callsites)) != self.callsites:
            raise ValueError("writer callsites must be sorted")
        if len(set(self.callsites)) != len(self.callsites):
            raise ValueError("writer callsites must be unique")

    @property
    def blockers(self) -> tuple[WriterCallsite, ...]:
        return tuple(site for site in self.callsites if site.blocking)

    @property
    def closed(self) -> bool:
        return not self.blockers

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-gate0-event-store-writer-inventory/1",
            "source_revision": self.source_revision,
            "package_root": self.package_root,
            "scan_input_sha256": self.scan_input_sha256,
            "files_scanned": self.files_scanned,
            "callsites": [site.to_dict() for site in self.callsites],
            "blocker_count": len(self.blockers),
            "closed": self.closed,
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self._payload()).encode("ascii")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "digest": self.digest}


def _safe_relative_posix(value: str) -> bool:
    return bool(
        value
        and not value.startswith("/")
        and "\\" not in value
        and value not in {".", ".."}
        and not value.startswith("../")
    )


def _inside_daedalus(module: str) -> bool:
    return module == "daedalus" or module.startswith("daedalus.")


def _module_name(package_root: Path, path: Path) -> tuple[str, bool]:
    relative = path.relative_to(package_root).with_suffix("")
    parts = [package_root.name, *relative.parts]
    is_package = parts[-1] == "__init__"
    if is_package:
        parts.pop()
    return ".".join(parts), is_package


def _relative_module(
    module: str | None,
    level: int,
    *,
    current_module: str,
    current_is_package: bool,
) -> str:
    if level == 0:
        return module or ""
    package_parts = current_module.split(".")
    if not current_is_package:
        package_parts.pop()
    ascent = level - 1
    if ascent and ascent >= len(package_parts):
        raise WriterInventoryError("relative import escapes production package")
    if ascent:
        package_parts = package_parts[:-ascent]
    if module:
        package_parts.extend(module.split("."))
    resolved = ".".join(package_parts)
    if not _inside_daedalus(resolved):
        raise WriterInventoryError("relative import escapes production package")
    return resolved


def _alias_candidates(
    tree: ast.AST,
    *,
    current_module: str,
    current_is_package: bool,
) -> dict[str, frozenset[str]]:
    candidates: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                bound = item.asname or item.name.split(".")[0]
                resolved = item.name if item.asname else bound
                candidates.setdefault(bound, set()).add(resolved)
        elif isinstance(node, ast.ImportFrom):
            base = _relative_module(
                node.module,
                node.level,
                current_module=current_module,
                current_is_package=current_is_package,
            )
            for item in node.names:
                if item.name == "*":
                    continue
                bound = item.asname or item.name
                resolved = f"{base}.{item.name}" if base else item.name
                candidates.setdefault(bound, set()).add(resolved)
    return {name: frozenset(values) for name, values in candidates.items()}


def _root_name(node: ast.expr) -> str | None:
    current = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


def _syntactic_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _syntactic_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _add_arguments(names: set[str], arguments: ast.arguments) -> None:
    for argument in (
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
    ):
        names.add(argument.arg)
    if arguments.vararg is not None:
        names.add(arguments.vararg.arg)
    if arguments.kwarg is not None:
        names.add(arguments.kwarg.arg)


def _bound_names(tree: ast.AST) -> frozenset[str]:
    """Return names rebound outside imports, conservatively file-wide.

    A local rebinding can therefore create an extra blocker, but it cannot make
    an unsafe writer look admitted. That is the required direction for Gate 0.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(
            node.ctx, (ast.Store, ast.Del)
        ):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
            _add_arguments(names, node.args)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Lambda):
            _add_arguments(names, node.args)
        elif isinstance(node, ast.ExceptHandler) and isinstance(node.name, str):
            names.add(node.name)
        elif isinstance(node, ast.Attribute) and isinstance(
            node.ctx, (ast.Store, ast.Del)
        ):
            root = _root_name(node)
            if root:
                names.add(root)
    return frozenset(names)


def _resolve_name(
    raw: str,
    *,
    aliases: Mapping[str, frozenset[str]],
    rebound: frozenset[str],
) -> tuple[str | None, bool]:
    root, dot, suffix = raw.partition(".")
    candidates = aliases.get(root)
    if root in rebound:
        return None, True
    if candidates is None:
        return raw, False
    if len(candidates) != 1:
        return None, True
    resolved_root = next(iter(candidates))
    return f"{resolved_root}.{suffix}" if dot else resolved_root, False


def _targets_writer(values: Iterable[str]) -> bool:
    return any(value.rsplit(".", 1)[-1] in _TRACKED_TERMINALS for value in values)


def _assignment_aliases(
    tree: ast.AST,
    *,
    aliases: Mapping[str, frozenset[str]],
    rebound: frozenset[str],
) -> frozenset[str]:
    """Find simple indirect aliases so their calls cannot disappear."""
    indirect: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)):
            continue
        value = node.value
        if not isinstance(value, (ast.Name, ast.Attribute)):
            continue
        raw = _syntactic_name(value)
        if raw is None:
            continue
        resolved, _ = _resolve_name(raw, aliases=aliases, rebound=rebound)
        if (resolved or raw).rsplit(".", 1)[-1] not in _TRACKED_TERMINALS:
            continue
        targets: tuple[ast.expr, ...]
        if isinstance(node, ast.Assign):
            targets = tuple(node.targets)
        else:
            targets = (node.target,)
        for target in targets:
            if isinstance(target, ast.Name):
                indirect.add(target.id)
    return frozenset(indirect)


def _direct_kind(call: ast.Call) -> str:
    read_only: bool | None = None
    ambiguous = False
    seen_read_only = False
    for keyword in call.keywords:
        if keyword.arg is None:
            ambiguous = True
        elif keyword.arg == "read_only":
            if seen_read_only:
                ambiguous = True
            seen_read_only = True
            if isinstance(keyword.value, ast.Constant) and isinstance(
                keyword.value.value, bool
            ):
                read_only = keyword.value.value
            else:
                ambiguous = True
    if ambiguous:
        return "ambiguous_direct"
    return "read_only" if read_only is True else "legacy_direct"


def _callsites_for_file(
    repository_root: Path,
    package_root: Path,
    path: Path,
) -> tuple[WriterCallsite, ...]:
    try:
        source = path.read_bytes().decode("utf-8")
        tree = ast.parse(source, filename=str(path), type_comments=True)
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        relative = path.relative_to(repository_root).as_posix()
        raise WriterInventoryError(
            f"cannot parse production Python file: {relative}"
        ) from exc
    module, is_package = _module_name(package_root, path)
    aliases = _alias_candidates(
        tree,
        current_module=module,
        current_is_package=is_package,
    )
    rebound = _bound_names(tree)
    indirect = _assignment_aliases(tree, aliases=aliases, rebound=rebound)
    relative = path.relative_to(repository_root).as_posix()
    sites: list[WriterCallsite] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        raw = _syntactic_name(node.func)
        if raw is None:
            continue
        root = raw.partition(".")[0]
        resolved, ambiguous = _resolve_name(
            raw,
            aliases=aliases,
            rebound=rebound,
        )
        raw_terminal = raw.rsplit(".", 1)[-1]
        resolved_terminal = (resolved or "").rsplit(".", 1)[-1]
        tracked_alias = _targets_writer(aliases.get(root, ()))
        if raw in indirect or raw_terminal in indirect:
            kind = "ambiguous_binding"
            callee = raw
        elif ambiguous and (
            raw_terminal in _TRACKED_TERMINALS or tracked_alias
        ):
            kind = "ambiguous_binding"
            callee = raw
        elif resolved in _FACTORY_CALLEES:
            kind = "gate0_factory"
            callee = resolved
        elif resolved in _DIRECT_CALLEES:
            kind = _direct_kind(node)
            callee = resolved
        elif (
            raw_terminal in _TRACKED_TERMINALS
            or resolved_terminal in _TRACKED_TERMINALS
        ):
            kind = "ambiguous_binding"
            callee = resolved or raw
        else:
            continue
        sites.append(
            WriterCallsite(
                path=relative,
                line=node.lineno,
                column=node.col_offset,
                kind=kind,
                callee=callee,
            )
        )
    return tuple(sorted(sites))


def _production_files(package_root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    resolved_package = package_root.resolve(strict=True)
    try:
        candidates = tuple(package_root.rglob("*.py"))
    except OSError as exc:
        raise WriterInventoryError("cannot enumerate production package") from exc
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(resolved_package)
        except (OSError, ValueError) as exc:
            raise WriterInventoryError(
                "production Python file escapes or cannot resolve inside package root"
            ) from exc
        files.append(candidate)
    if not files:
        raise WriterInventoryError("production package contains no Python files")
    return tuple(sorted(files, key=lambda item: item.as_posix()))


def _scan_input(files: Iterable[Path], repository_root: Path) -> str:
    entries: list[dict[str, str]] = []
    try:
        for path in files:
            entries.append(
                {
                    "path": path.relative_to(repository_root).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    except (OSError, ValueError) as exc:
        raise WriterInventoryError(
            "cannot bind writer inventory to production file bytes"
        ) from exc
    return hashlib.sha256(canonical_json(entries).encode("ascii")).hexdigest()


def scan_event_store_writers(
    repository_root: str | Path,
    *,
    source_revision: str,
) -> WriterInventory:
    """Inventory production Event-Store constructors for one exact revision."""
    if not _SOURCE_REVISION.fullmatch(str(source_revision)):
        raise WriterInventoryError(
            "source_revision must be a lowercase 40-hex commit"
        )
    try:
        root = Path(repository_root).resolve(strict=True)
    except OSError as exc:
        raise WriterInventoryError("repository root does not exist") from exc
    package_root = root / "daedalus"
    try:
        resolved_package = package_root.resolve(strict=True)
        resolved_package.relative_to(root)
    except (OSError, ValueError) as exc:
        raise WriterInventoryError(
            "repository must contain an in-root daedalus package"
        ) from exc
    files = _production_files(resolved_package)
    sites = tuple(
        sorted(
            site
            for path in files
            for site in _callsites_for_file(root, resolved_package, path)
        )
    )
    return WriterInventory(
        source_revision=str(source_revision),
        package_root=resolved_package.relative_to(root).as_posix(),
        scan_input_sha256=_scan_input(files, root),
        files_scanned=len(files),
        callsites=sites,
    )


__all__ = [
    "WriterCallsite",
    "WriterInventory",
    "WriterInventoryError",
    "scan_event_store_writers",
]
