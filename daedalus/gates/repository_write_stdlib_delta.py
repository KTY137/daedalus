# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Revision-bound additive inventory for stdlib write/process surfaces.

This module is deliberately inert.  It does not patch the canonical repository
write inventory and it never classifies a surface as guarded or trusted.  It
exists to make concrete false-negative families machine-visible before a later
reviewed integration packet extends the canonical scanner.
"""
from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from daedalus.gates.repository_write_inventory import (
    RepositoryWriteInventory,
    RepositoryWriteInventoryError,
    scan_repository_write_surfaces,
)
from daedalus.spine.envelope import canonical_json


_SOURCE_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_MODE_OPENERS: Mapping[str, tuple[int, str, frozenset[str]]] = {
    "gzip.open": (1, "rb", frozenset({"w", "a", "x", "+"})),
    "bz2.open": (1, "rb", frozenset({"w", "a", "x", "+"})),
    "lzma.open": (1, "rb", frozenset({"w", "a", "x", "+"})),
    "tarfile.open": (1, "r", frozenset({"w", "a", "x", "+"})),
    "zipfile.ZipFile": (1, "r", frozenset({"w", "a", "x", "+"})),
}

_UNCONDITIONAL_FILESYSTEM = frozenset(
    {
        "os.write",
        "os.writev",
        "os.pwrite",
        "os.pwritev",
        "os.ftruncate",
        "os.utime",
        "os.setxattr",
        "os.removexattr",
        "shutil.make_archive",
        "shutil.unpack_archive",
        "tempfile.TemporaryFile",
        "tempfile.SpooledTemporaryFile",
    }
)

_PROCESS_SURFACES = frozenset(
    {
        "asyncio.create_subprocess_exec",
        "asyncio.create_subprocess_shell",
        "subprocess.getoutput",
        "subprocess.getstatusoutput",
        "os.execl",
        "os.execle",
        "os.execlp",
        "os.execlpe",
        "os.execv",
        "os.execve",
        "os.execvp",
        "os.execvpe",
        "os.posix_spawn",
        "os.posix_spawnp",
        "os.spawnl",
        "os.spawnle",
        "os.spawnlp",
        "os.spawnlpe",
        "os.spawnv",
        "os.spawnve",
        "os.spawnvp",
        "os.spawnvpe",
        "pty.spawn",
        "multiprocessing.Process",
        "concurrent.futures.ProcessPoolExecutor",
    }
)

_STREAM_SINKS = frozenset(
    {
        "json.dump",
        "pickle.dump",
        "marshal.dump",
        "csv.writer",
        "csv.DictWriter",
    }
)

_GENERIC_SINK_METHODS = frozenset(
    {"write", "writelines", "writerow", "writerows", "truncate"}
)

# ``open`` enters this scanner's tracked terminals only through the five
# ``_MODE_OPENERS`` above, and those are matched by their resolved name before
# any terminal fallback runs.  Every remaining call whose syntactic terminal is
# ``open`` -- ``os.open``, the builtin ``open``, ``io.open``, ``X.open(mode)``
# -- is classified by the generation-1 base scanner with exact flag and mode
# semantics, and the base deliberately leaves the position empty when it proves
# the call read-only.  Re-flagging those as "unresolved" here would contradict a
# decision made with more information and would re-add a surface the base just
# cleared.  This scanner is the delta; it does not restate the base.
_BASE_OWNED_TERMINALS = frozenset({"open"})

_TRACKED_TERMINALS = frozenset(
    {
        *(name.rsplit(".", 1)[-1] for name in _MODE_OPENERS),
        *(name.rsplit(".", 1)[-1] for name in _UNCONDITIONAL_FILESYSTEM),
        *(name.rsplit(".", 1)[-1] for name in _PROCESS_SURFACES),
        *(name.rsplit(".", 1)[-1] for name in _STREAM_SINKS),
        *_GENERIC_SINK_METHODS,
    }
)

_ALLOWED_KINDS = frozenset(
    {
        "archive_or_compressed_write",
        "ambiguous_archive_or_compressed_mode",
        "filesystem_mutation",
        "process_effect_unknown",
        "stream_write_sink",
        "ambiguous_stdlib_binding",
    }
)


class RepositoryWriteStdlibDeltaError(RuntimeError):
    """The additive scanner cannot produce revision-bound evidence."""


@dataclass(frozen=True, order=True)
class RepositoryWriteStdlibFinding:
    path: str
    line: int
    column: int
    kind: str
    callee: str
    operation: str

    def __post_init__(self) -> None:
        if not _safe_relative_posix(self.path):
            raise ValueError("finding path must be repository-relative POSIX")
        if type(self.line) is not int or type(self.column) is not int:
            raise ValueError("finding position must use strict integers")
        if self.line < 1 or self.column < 0:
            raise ValueError("finding position is invalid")
        if self.kind not in _ALLOWED_KINDS:
            raise ValueError("finding kind is invalid")
        if not self.callee or any(ch.isspace() for ch in self.callee):
            raise ValueError("finding callee is invalid")
        if not self.operation or any(ch in self.operation for ch in "\r\n"):
            raise ValueError("finding operation is invalid")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "kind": self.kind,
            "callee": self.callee,
            "operation": self.operation,
            "blocking": True,
        }


@dataclass(frozen=True)
class RepositoryWriteStdlibDelta:
    source_revision: str
    base_inventory_digest: str
    scan_input_sha256: str
    files_scanned: int
    findings: tuple[RepositoryWriteStdlibFinding, ...]

    def __post_init__(self) -> None:
        if not _SOURCE_REVISION.fullmatch(self.source_revision):
            raise ValueError("source_revision must be a lowercase 40-hex commit")
        if not _SHA256.fullmatch(self.base_inventory_digest):
            raise ValueError("base_inventory_digest must be lowercase sha256")
        if not _SHA256.fullmatch(self.scan_input_sha256):
            raise ValueError("scan_input_sha256 must be lowercase sha256")
        if type(self.files_scanned) is not int or self.files_scanned < 1:
            raise ValueError("files_scanned must be a positive strict integer")
        if not isinstance(self.findings, tuple):
            raise ValueError("findings must be an immutable tuple")
        if tuple(sorted(self.findings)) != self.findings:
            raise ValueError("findings must be sorted")
        if len(set(self.findings)) != len(self.findings):
            raise ValueError("findings must be unique")

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-gate0-repository-write-stdlib-delta/1",
            "source_revision": self.source_revision,
            "base_inventory_digest": self.base_inventory_digest,
            "scan_input_sha256": self.scan_input_sha256,
            "files_scanned": self.files_scanned,
            "findings": [finding.to_dict() for finding in self.findings],
            "finding_count": len(self.findings),
            "canonical_scanner_integrated": False,
            "closed": False,
            "blockers": [
                "canonical-scanner-integration-missing",
                *(
                    ["additional-write-surfaces-present"]
                    if self.findings
                    else []
                ),
            ],
        }

    @property
    def digest(self) -> str:
        return hashlib.sha256(
            canonical_json(self._payload()).encode("ascii")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self._payload(), "digest": self.digest}


def _safe_relative_posix(value: object) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    # PurePosixPath, not Path: on Windows a rooted-but-driveless value such as
    # "/daedalus/a.py" is not reported as absolute, so the platform-dependent
    # Path would let an absolute POSIX path pass as repository-relative.
    path = PurePosixPath(value)
    return (
        not path.is_absolute()
        and all(part not in {"", ".", ".."} for part in path.parts)
        and path.as_posix() == value
    )


def _syntactic_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _syntactic_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _aliases(tree: ast.AST) -> dict[str, frozenset[str]]:
    candidates: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                bound = item.asname or item.name.split(".", 1)[0]
                resolved = item.name if item.asname else bound
                candidates.setdefault(bound, set()).add(resolved)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            for item in node.names:
                if item.name == "*":
                    continue
                bound = item.asname or item.name
                candidates.setdefault(bound, set()).add(
                    f"{node.module}.{item.name}"
                )
    return {name: frozenset(values) for name, values in candidates.items()}


def _rebound_names(tree: ast.AST) -> frozenset[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(
            node.ctx, (ast.Store, ast.Del)
        ):
            names.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
            for argument in (
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
            ):
                names.add(argument.arg)
            if node.args.vararg:
                names.add(node.args.vararg.arg)
            if node.args.kwarg:
                names.add(node.args.kwarg.arg)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
    return frozenset(names)


def _resolve(
    raw: str,
    *,
    aliases: Mapping[str, frozenset[str]],
    rebound: frozenset[str],
) -> tuple[str | None, bool]:
    root, dot, suffix = raw.partition(".")
    if root in rebound:
        return None, True
    candidates = aliases.get(root)
    if candidates is None:
        return raw, False
    if len(candidates) != 1:
        return None, True
    resolved = next(iter(candidates))
    return (f"{resolved}.{suffix}" if dot else resolved), False


def _literal_string(node: ast.AST | None) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def _keyword(call: ast.Call, name: str) -> tuple[ast.AST | None, bool]:
    values = [keyword.value for keyword in call.keywords if keyword.arg == name]
    return (
        values[0] if len(values) == 1 else None,
        len(values) > 1 or any(keyword.arg is None for keyword in call.keywords),
    )


def _mode_finding(
    call: ast.Call,
    *,
    callee: str,
) -> tuple[str, str] | None:
    position, default, write_tokens = _MODE_OPENERS[callee]
    node, ambiguous = _keyword(call, "mode")
    if node is None and len(call.args) > position:
        node = call.args[position]
    if ambiguous:
        return (
            "ambiguous_archive_or_compressed_mode",
            "expanded-or-duplicate-mode",
        )
    if node is None:
        mode = default
    else:
        mode = _literal_string(node)
        if mode is None:
            return (
                "ambiguous_archive_or_compressed_mode",
                "dynamic-mode",
            )
    if any(token in mode for token in write_tokens):
        return ("archive_or_compressed_write", mode)
    return None


def _classify(
    call: ast.Call,
    *,
    raw: str,
    resolved: str | None,
    ambiguous: bool,
    aliases: Mapping[str, frozenset[str]],
) -> tuple[str, str, str] | None:
    terminal = raw.rsplit(".", 1)[-1]
    root = raw.partition(".")[0]
    if ambiguous and terminal not in _BASE_OWNED_TERMINALS and (
        terminal in _TRACKED_TERMINALS
        or any(
            candidate.rsplit(".", 1)[-1] in _TRACKED_TERMINALS
            for candidate in aliases.get(root, ())
        )
    ):
        return (
            "ambiguous_stdlib_binding",
            raw,
            "rebound-or-conflicting-binding",
        )
    if resolved in _MODE_OPENERS:
        mode = _mode_finding(call, callee=resolved)
        return None if mode is None else (mode[0], resolved, mode[1])
    if resolved in _UNCONDITIONAL_FILESYSTEM:
        return (
            "filesystem_mutation",
            resolved,
            resolved.rsplit(".", 1)[-1],
        )
    if resolved in _PROCESS_SURFACES:
        return (
            "process_effect_unknown",
            resolved,
            resolved.rsplit(".", 1)[-1],
        )
    if resolved in _STREAM_SINKS:
        return (
            "stream_write_sink",
            resolved,
            resolved.rsplit(".", 1)[-1],
        )
    if terminal in _GENERIC_SINK_METHODS:
        return ("stream_write_sink", resolved or raw, terminal)
    if terminal in _TRACKED_TERMINALS and terminal not in _BASE_OWNED_TERMINALS:
        return (
            "ambiguous_stdlib_binding",
            resolved or raw,
            "unresolved-tracked-terminal",
        )
    return None


def _production_files(root: Path) -> tuple[Path, ...]:
    package = root / "daedalus"
    try:
        resolved_package = package.resolve(strict=True)
        resolved_package.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise RepositoryWriteStdlibDeltaError(
            "daedalus package root is missing or escapes repository"
        ) from exc
    if package.is_symlink() or not resolved_package.is_dir():
        raise RepositoryWriteStdlibDeltaError(
            "daedalus package root must be a regular non-symlink directory"
        )
    files: list[Path] = []
    try:
        candidates = tuple(package.rglob("*.py"))
    except OSError as exc:
        raise RepositoryWriteStdlibDeltaError(
            "cannot enumerate production package"
        ) from exc
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(resolved_package)
        except (OSError, RuntimeError, ValueError) as exc:
            raise RepositoryWriteStdlibDeltaError(
                "production Python file escapes package root"
            ) from exc
        if candidate.is_symlink() or not candidate.is_file():
            raise RepositoryWriteStdlibDeltaError(
                "production Python path must be a regular non-symlink file"
            )
        files.append(candidate)
    if not files:
        raise RepositoryWriteStdlibDeltaError(
            "production package contains no Python files"
        )
    return tuple(sorted(files, key=lambda item: item.as_posix()))


def _scan_input(files: Iterable[Path], root: Path) -> str:
    entries: list[dict[str, str]] = []
    try:
        for path in files:
            entries.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                }
            )
    except (OSError, ValueError) as exc:
        raise RepositoryWriteStdlibDeltaError(
            "cannot bind delta to production file bytes"
        ) from exc
    return hashlib.sha256(canonical_json(entries).encode("ascii")).hexdigest()


def _findings_for_file(root: Path, path: Path) -> tuple[RepositoryWriteStdlibFinding, ...]:
    relative = path.relative_to(root).as_posix()
    try:
        source = path.read_bytes().decode("utf-8")
        tree = ast.parse(source, filename=str(path), type_comments=True)
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise RepositoryWriteStdlibDeltaError(
            f"cannot parse production Python file: {relative}"
        ) from exc
    aliases = _aliases(tree)
    rebound = _rebound_names(tree)
    findings: list[RepositoryWriteStdlibFinding] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        raw = _syntactic_name(node.func)
        if raw is None:
            if isinstance(node.func, ast.Attribute) and node.func.attr in _GENERIC_SINK_METHODS:
                raw = f"<expression>.{node.func.attr}"
                resolved, ambiguous = raw, False
            else:
                continue
        else:
            resolved, ambiguous = _resolve(
                raw,
                aliases=aliases,
                rebound=rebound,
            )
        classified = _classify(
            node,
            raw=raw,
            resolved=resolved,
            ambiguous=ambiguous,
            aliases=aliases,
        )
        if classified is None:
            continue
        kind, callee, operation = classified
        findings.append(
            RepositoryWriteStdlibFinding(
                path=relative,
                line=node.lineno,
                column=node.col_offset,
                kind=kind,
                callee=callee,
                operation=operation,
            )
        )
    return tuple(sorted(findings))


def scan_repository_write_stdlib_delta(
    repository_root: str | Path,
    *,
    source_revision: str,
) -> RepositoryWriteStdlibDelta:
    """Produce an inert additive delta bound to the base inventory and bytes."""

    if not isinstance(source_revision, str) or not _SOURCE_REVISION.fullmatch(source_revision):
        raise RepositoryWriteStdlibDeltaError(
            "source_revision must be a lowercase 40-hex commit"
        )
    try:
        root = Path(repository_root).resolve(strict=True)
    except (OSError, RuntimeError, TypeError) as exc:
        raise RepositoryWriteStdlibDeltaError(
            "repository root does not resolve"
        ) from exc
    try:
        base: RepositoryWriteInventory = scan_repository_write_surfaces(
            root,
            source_revision=source_revision,
        )
    except RepositoryWriteInventoryError as exc:
        raise RepositoryWriteStdlibDeltaError(
            "base repository write inventory failed"
        ) from exc
    files = _production_files(root)
    base_positions = {
        (site.path, site.line, site.column) for site in base.callsites
    }
    findings = tuple(
        sorted(
            finding
            for path in files
            for finding in _findings_for_file(root, path)
            if (finding.path, finding.line, finding.column) not in base_positions
        )
    )
    # An identity failure of the container below raises a bare ValueError from
    # the frozen dataclass.  The composing scanner
    # (daedalus/gates/repository_write_inventory_v2.py) converts it to its
    # declared refusal type so it cannot escape a caller's fail-closed handler.
    return RepositoryWriteStdlibDelta(
        source_revision=source_revision,
        base_inventory_digest=base.digest,
        scan_input_sha256=_scan_input(files, root),
        files_scanned=len(files),
        findings=findings,
    )
