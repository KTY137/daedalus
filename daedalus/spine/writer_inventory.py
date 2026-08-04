"""Deterministic inventory of canonical Event-Store construction sites.

The inventory is deliberately syntax-based and fail-closed.  It does not claim
that every dynamic Python call can be resolved; instead, direct or ambiguous
``SpineLedger`` construction remains a blocker until migrated or explicitly
classified.  The report is bound to one repository revision and to the exact
bytes of every scanned production Python file.
"""
from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

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
_BLOCKING_KINDS = frozenset({"legacy_direct", "ambiguous_direct"})


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
        if not self.path or self.path.startswith("/") or "\\" in self.path:
            raise ValueError("writer callsite path must be repository-relative POSIX")
        if self.line < 1 or self.column < 0:
            raise ValueError("writer callsite position is invalid")
        if self.kind not in {
            "gate0_factory",
            "read_only",
            "legacy_direct",
            "ambiguous_direct",
        }:
            raise ValueError("unknown writer callsite kind")
        if self.callee not in _DIRECT_CALLEES | _FACTORY_CALLEES:
            raise ValueError("unknown Event-Store callee")

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
        if not self.package_root or self.package_root.startswith("/"):
            raise ValueError("package_root must be repository-relative")
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
    if ascent > len(package_parts):
        raise WriterInventoryError("relative import escapes production package")
    if ascent:
        package_parts = package_parts[:-ascent]
    if module:
        package_parts.extend(module.split("."))
    return ".".join(package_parts)


def _aliases(
    tree: ast.AST,
    *,
    current_module: str,
    current_is_package: bool,
) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                bound = item.asname or item.name.split(".")[0]
                aliases[bound] = item.name if item.asname else bound
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
                aliases[bound] = f"{base}.{item.name}" if base else item.name
    return aliases


def _expression_name(node: ast.expr, aliases: dict[str, str]) -> str | None:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        base = _expression_name(node.value, aliases)
        return f"{base}.{node.attr}" if base else None
    return None


def _direct_kind(call: ast.Call) -> str:
    read_only = None
    ambiguous = False
    for keyword in call.keywords:
        if keyword.arg is None:
            ambiguous = True
        elif keyword.arg == "read_only":
            if isinstance(keyword.value, ast.Constant) and isinstance(
                keyword.value.value, bool
            ):
                read_only = keyword.value.value
            else:
                ambiguous = True
    if ambiguous:
        return "ambiguous_direct"
    if read_only is True:
        return "read_only"
    return "legacy_direct"


def _callsites_for_file(
    repository_root: Path,
    package_root: Path,
    path: Path,
) -> tuple[WriterCallsite, ...]:
    try:
        raw = path.read_bytes()
        source = raw.decode("utf-8")
        tree = ast.parse(source, filename=str(path), type_comments=True)
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        relative = path.relative_to(repository_root).as_posix()
        raise WriterInventoryError(
            f"cannot parse production Python file: {relative}"
        ) from exc
    module, is_package = _module_name(package_root, path)
    aliases = _aliases(
        tree,
        current_module=module,
        current_is_package=is_package,
    )
    relative = path.relative_to(repository_root).as_posix()
    sites: list[WriterCallsite] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = _expression_name(node.func, aliases)
        if callee in _FACTORY_CALLEES:
            kind = "gate0_factory"
        elif callee in _DIRECT_CALLEES:
            kind = _direct_kind(node)
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


def _production_files(repository_root: Path, package_root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    resolved_package = package_root.resolve(strict=True)
    for candidate in package_root.rglob("*.py"):
        resolved = candidate.resolve(strict=True)
        try:
            resolved.relative_to(resolved_package)
        except ValueError as exc:
            raise WriterInventoryError(
                "production Python symlink escapes the package root"
            ) from exc
        files.append(candidate)
    if not files:
        raise WriterInventoryError("production package contains no Python files")
    return tuple(sorted(files, key=lambda item: item.as_posix()))


def _scan_input(files: Iterable[Path], repository_root: Path) -> str:
    entries = [
        {
            "path": path.relative_to(repository_root).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in files
    ]
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
    root = Path(repository_root).resolve(strict=True)
    package_root = root / "daedalus"
    try:
        resolved_package = package_root.resolve(strict=True)
        resolved_package.relative_to(root)
    except (OSError, ValueError) as exc:
        raise WriterInventoryError(
            "repository must contain an in-root daedalus package"
        ) from exc
    files = _production_files(root, resolved_package)
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
