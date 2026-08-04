"""Conservative revision-bound inventory of production write-capable callsites.

This inventory is discovery evidence, not a proof that a callsite targets the
Primary Checkout. Every write-capable or unresolved process/filesystem surface
remains blocking until a later packet binds its target and guard contract. The
scanner is deliberately syntax-based and fail-closed: ambiguity may create an
extra blocker but may not make a questionable production path disappear.
"""
from __future__ import annotations

import ast
import hashlib
import re
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from daedalus.spine.envelope import canonical_json


_SOURCE_REVISION = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

_FILESYSTEM_FUNCTIONS = frozenset(
    {
        "os.remove",
        "os.unlink",
        "os.rename",
        "os.renames",
        "os.replace",
        "os.mkdir",
        "os.makedirs",
        "os.rmdir",
        "os.removedirs",
        "os.link",
        "os.symlink",
        "os.chmod",
        "os.chown",
        "os.truncate",
        "shutil.copy",
        "shutil.copy2",
        "shutil.copyfile",
        "shutil.copytree",
        "shutil.move",
        "shutil.rmtree",
        "shutil.copymode",
        "shutil.copystat",
        "shutil.chown",
        "tempfile.mkstemp",
        "tempfile.mkdtemp",
        "tempfile.NamedTemporaryFile",
        "tempfile.TemporaryDirectory",
    }
)
_PATH_METHODS = frozenset(
    {
        "write_text",
        "write_bytes",
        "touch",
        "mkdir",
        "unlink",
        "rename",
        "replace",
        "chmod",
        "symlink_to",
        "hardlink_to",
        "rmdir",
    }
)
_PROCESS_FUNCTIONS = frozenset(
    {
        "subprocess.run",
        "subprocess.Popen",
        "subprocess.call",
        "subprocess.check_call",
        "subprocess.check_output",
        "os.system",
        "os.popen",
    }
)
_SQLITE_CONNECT = frozenset({"sqlite3.connect"})
_OPEN_FUNCTIONS = frozenset({"open", "io.open"})
_TRACKED_TERMINALS = frozenset(
    {
        *(name.rsplit(".", 1)[-1] for name in _FILESYSTEM_FUNCTIONS),
        *(name.rsplit(".", 1)[-1] for name in _PROCESS_FUNCTIONS),
        *(name.rsplit(".", 1)[-1] for name in _SQLITE_CONNECT),
        *_PATH_METHODS,
        "open",
    }
)
_ALLOWED_KINDS = frozenset(
    {
        "filesystem_mutation",
        "path_mutation",
        "write_mode_open",
        "ambiguous_open_mode",
        "os_open_write",
        "ambiguous_os_open_flags",
        "sqlite_write_or_create",
        "sqlite_read_only",
        "ambiguous_sqlite_mode",
        "git_mutation_process",
        "process_effect_unknown",
        "ambiguous_binding",
    }
)
_BLOCKING_KINDS = _ALLOWED_KINDS - {"sqlite_read_only"}
_GIT_MUTATING_COMMANDS = frozenset(
    {
        "add",
        "am",
        "apply",
        "branch",
        "checkout",
        "cherry-pick",
        "clean",
        "commit",
        "config",
        "gc",
        "merge",
        "mv",
        "rebase",
        "reset",
        "restore",
        "revert",
        "rm",
        "stash",
        "switch",
        "symbolic-ref",
        "tag",
        "update-index",
        "update-ref",
        "worktree",
    }
)


class RepositoryWriteInventoryError(RuntimeError):
    """The repository write-surface inventory cannot be produced honestly."""


@dataclass(frozen=True, order=True)
class RepositoryWriteCallsite:
    path: str
    line: int
    column: int
    kind: str
    callee: str
    operation: str

    def __post_init__(self) -> None:
        if not _safe_relative_posix(self.path):
            raise ValueError("callsite path must be repository-relative POSIX")
        if self.line < 1 or self.column < 0:
            raise ValueError("callsite position is invalid")
        if self.kind not in _ALLOWED_KINDS:
            raise ValueError("unknown repository write callsite kind")
        if not self.callee or any(ch.isspace() for ch in self.callee):
            raise ValueError("callsite callee is invalid")
        if not self.operation or any(ch in self.operation for ch in "\r\n"):
            raise ValueError("callsite operation is invalid")

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
            "operation": self.operation,
            "blocking": self.blocking,
        }


@dataclass(frozen=True)
class RepositoryWriteInventory:
    source_revision: str
    package_root: str
    scan_input_sha256: str
    files_scanned: int
    callsites: tuple[RepositoryWriteCallsite, ...]

    def __post_init__(self) -> None:
        if not _SOURCE_REVISION.fullmatch(self.source_revision):
            raise ValueError("source_revision must be a lowercase 40-hex commit")
        if not _safe_relative_posix(self.package_root):
            raise ValueError("package_root must be repository-relative POSIX")
        if not _SHA256.fullmatch(self.scan_input_sha256):
            raise ValueError("scan_input_sha256 must be lowercase sha256")
        if self.files_scanned < 1:
            raise ValueError("inventory must scan at least one production file")
        if tuple(sorted(self.callsites)) != self.callsites:
            raise ValueError("callsites must be sorted")
        if len(set(self.callsites)) != len(self.callsites):
            raise ValueError("callsites must be unique")

    @property
    def blockers(self) -> tuple[RepositoryWriteCallsite, ...]:
        return tuple(site for site in self.callsites if site.blocking)

    @property
    def closed(self) -> bool:
        return not self.blockers

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": "daedalus-gate0-repository-write-inventory/1",
            "source_revision": self.source_revision,
            "package_root": self.package_root,
            "scan_input_sha256": self.scan_input_sha256,
            "files_scanned": self.files_scanned,
            "callsites": [site.to_dict() for site in self.callsites],
            "blocker_count": len(self.blockers),
            "closed": self.closed,
            "scope": "potential_repository_write_surface",
            "primary_checkout_target_proven": False,
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
        raise RepositoryWriteInventoryError(
            "relative import escapes production package"
        )
    if ascent:
        package_parts = package_parts[:-ascent]
    if module:
        package_parts.extend(module.split("."))
    resolved = ".".join(package_parts)
    if not _inside_daedalus(resolved):
        raise RepositoryWriteInventoryError(
            "relative import escapes production package"
        )
    return resolved


def _aliases(
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


def _root_name(node: ast.expr) -> str | None:
    current = node
    while isinstance(current, ast.Attribute):
        current = current.value
    return current.id if isinstance(current, ast.Name) else None


def _rebound_names(tree: ast.AST) -> frozenset[str]:
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


def _syntactic_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _syntactic_name(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


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


def _literal_string(node: ast.AST | None) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _keyword(call: ast.Call, name: str) -> ast.AST | None:
    found: ast.AST | None = None
    for item in call.keywords:
        if item.arg is None:
            return None
        if item.arg == name:
            if found is not None:
                return None
            found = item.value
    return found


def _open_mode(call: ast.Call, *, method: bool) -> tuple[str, str] | None:
    mode_node = _keyword(call, "mode")
    if mode_node is None:
        index = 0 if method else 1
        if len(call.args) > index:
            mode_node = call.args[index]
    if mode_node is None:
        return None
    mode = _literal_string(mode_node)
    if mode is None:
        return ("ambiguous_open_mode", "dynamic-mode")
    if any(token in mode for token in "wax+"):
        return ("write_mode_open", mode)
    return None


def _os_open_flags(call: ast.Call) -> tuple[str, str] | None:
    node = _keyword(call, "flags")
    if node is None and len(call.args) > 1:
        node = call.args[1]
    if node is None:
        return ("ambiguous_os_open_flags", "missing-flags")
    names = {
        item.id
        for item in ast.walk(node)
        if isinstance(item, ast.Name)
    }
    attributes = {
        item.attr
        for item in ast.walk(node)
        if isinstance(item, ast.Attribute)
    }
    tokens = names | attributes
    write_tokens = {
        "O_WRONLY",
        "O_RDWR",
        "O_CREAT",
        "O_TRUNC",
        "O_APPEND",
        "O_EXCL",
    }
    if tokens.intersection(write_tokens):
        return ("os_open_write", "+".join(sorted(tokens.intersection(write_tokens))))
    if tokens and tokens <= {"O_RDONLY", "O_CLOEXEC", "O_NOFOLLOW", "O_DIRECTORY"}:
        return None
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return None if node.value == 0 else ("ambiguous_os_open_flags", str(node.value))
    return ("ambiguous_os_open_flags", "dynamic-flags")


def _sqlite_mode(call: ast.Call) -> tuple[str, str]:
    database = call.args[0] if call.args else _keyword(call, "database")
    uri_node = _keyword(call, "uri")
    uri_true = isinstance(uri_node, ast.Constant) and uri_node.value is True
    value = _literal_string(database)
    if value is None:
        return ("ambiguous_sqlite_mode", "dynamic-database")
    if uri_true and "?" in value:
        query = value.split("?", 1)[1]
        modes = [part.split("=", 1)[1] for part in query.split("&") if part.startswith("mode=")]
        if modes == ["ro"]:
            return ("sqlite_read_only", "mode=ro")
        if len(modes) == 1 and modes[0] in {"rw", "rwc", "memory"}:
            return ("sqlite_write_or_create", f"mode={modes[0]}")
        if modes:
            return ("ambiguous_sqlite_mode", "ambiguous-uri-mode")
    return ("sqlite_write_or_create", "default-connect")


def _process_tokens(call: ast.Call) -> tuple[str, ...] | None:
    command = call.args[0] if call.args else _keyword(call, "args")
    if isinstance(command, (ast.List, ast.Tuple)):
        tokens: list[str] = []
        for item in command.elts:
            value = _literal_string(item)
            if value is None:
                return None
            tokens.append(value)
        return tuple(tokens)
    literal = _literal_string(command)
    if literal is None:
        return None
    try:
        return tuple(shlex.split(literal, posix=True))
    except ValueError:
        return None


def _process_kind(call: ast.Call) -> tuple[str, str]:
    tokens = _process_tokens(call)
    if not tokens:
        return ("process_effect_unknown", "dynamic-command")
    executable = Path(tokens[0]).name.lower()
    if executable in {"git", "git.exe"} and len(tokens) > 1:
        command = tokens[1].lower()
        if command in _GIT_MUTATING_COMMANDS:
            return ("git_mutation_process", f"git {command}")
        return ("process_effect_unknown", f"git {command}")
    return ("process_effect_unknown", executable)


def _targets_tracked(values: Iterable[str]) -> bool:
    return any(value.rsplit(".", 1)[-1] in _TRACKED_TERMINALS for value in values)


def _indirect_aliases(
    tree: ast.AST,
    *,
    aliases: Mapping[str, frozenset[str]],
    rebound: frozenset[str],
) -> frozenset[str]:
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


def _classify_call(
    call: ast.Call,
    *,
    raw: str,
    resolved: str | None,
    ambiguous: bool,
    aliases: Mapping[str, frozenset[str]],
    indirect: frozenset[str],
) -> tuple[str, str, str] | None:
    terminal = raw.rsplit(".", 1)[-1]
    root = raw.partition(".")[0]
    resolved_terminal = (resolved or "").rsplit(".", 1)[-1]
    if raw in indirect or terminal in indirect:
        return ("ambiguous_binding", raw, "indirect-call-alias")
    if ambiguous and (
        terminal in _TRACKED_TERMINALS or _targets_tracked(aliases.get(root, ()))
    ):
        return ("ambiguous_binding", raw, "rebound-or-conflicting-binding")
    if resolved in _FILESYSTEM_FUNCTIONS:
        return ("filesystem_mutation", resolved, resolved.rsplit(".", 1)[-1])
    if terminal in _PATH_METHODS:
        return ("path_mutation", resolved or raw, terminal)
    if resolved in _PROCESS_FUNCTIONS:
        kind, operation = _process_kind(call)
        return (kind, resolved, operation)
    if resolved in _SQLITE_CONNECT:
        kind, operation = _sqlite_mode(call)
        return (kind, resolved, operation)
    if resolved == "os.open":
        classified = _os_open_flags(call)
        if classified is None:
            return None
        kind, operation = classified
        return (kind, resolved, operation)
    if resolved in _OPEN_FUNCTIONS:
        classified = _open_mode(call, method=False)
        if classified is None:
            return None
        kind, operation = classified
        return (kind, resolved, operation)
    if terminal == "open":
        classified = _open_mode(call, method=True)
        if classified is None:
            return None
        kind, operation = classified
        return (kind, resolved or raw, operation)
    if terminal in _TRACKED_TERMINALS or resolved_terminal in _TRACKED_TERMINALS:
        return ("ambiguous_binding", resolved or raw, "unresolved-tracked-terminal")
    return None


def _callsites_for_file(
    repository_root: Path,
    package_root: Path,
    path: Path,
) -> tuple[RepositoryWriteCallsite, ...]:
    relative = path.relative_to(repository_root).as_posix()
    try:
        source = path.read_bytes().decode("utf-8")
        tree = ast.parse(source, filename=str(path), type_comments=True)
    except (OSError, UnicodeDecodeError, SyntaxError) as exc:
        raise RepositoryWriteInventoryError(
            f"cannot parse production Python file: {relative}"
        ) from exc
    module, is_package = _module_name(package_root, path)
    aliases = _aliases(
        tree,
        current_module=module,
        current_is_package=is_package,
    )
    rebound = _rebound_names(tree)
    indirect = _indirect_aliases(tree, aliases=aliases, rebound=rebound)
    sites: list[RepositoryWriteCallsite] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        raw = _syntactic_name(node.func)
        if raw is None:
            continue
        resolved, ambiguous = _resolve_name(
            raw,
            aliases=aliases,
            rebound=rebound,
        )
        classified = _classify_call(
            node,
            raw=raw,
            resolved=resolved,
            ambiguous=ambiguous,
            aliases=aliases,
            indirect=indirect,
        )
        if classified is None:
            continue
        kind, callee, operation = classified
        sites.append(
            RepositoryWriteCallsite(
                path=relative,
                line=node.lineno,
                column=node.col_offset,
                kind=kind,
                callee=callee,
                operation=operation,
            )
        )
    return tuple(sorted(sites))


def _production_files(package_root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    resolved_package = package_root.resolve(strict=True)
    try:
        candidates = tuple(package_root.rglob("*.py"))
    except OSError as exc:
        raise RepositoryWriteInventoryError(
            "cannot enumerate production package"
        ) from exc
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(resolved_package)
        except (OSError, ValueError) as exc:
            raise RepositoryWriteInventoryError(
                "production Python file escapes or cannot resolve inside package root"
            ) from exc
        if candidate.is_symlink() or not candidate.is_file():
            raise RepositoryWriteInventoryError(
                "production Python path must be a regular non-symlink file"
            )
        files.append(candidate)
    if not files:
        raise RepositoryWriteInventoryError(
            "production package contains no Python files"
        )
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
        raise RepositoryWriteInventoryError(
            "cannot bind inventory to production file bytes"
        ) from exc
    return hashlib.sha256(canonical_json(entries).encode("ascii")).hexdigest()


def scan_repository_write_surfaces(
    repository_root: str | Path,
    *,
    source_revision: str,
) -> RepositoryWriteInventory:
    """Inventory production write-capable callsites for one exact revision."""

    if not _SOURCE_REVISION.fullmatch(str(source_revision)):
        raise RepositoryWriteInventoryError(
            "source_revision must be a lowercase 40-hex commit"
        )
    try:
        root = Path(repository_root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RepositoryWriteInventoryError(
            "repository root does not resolve"
        ) from exc
    package_root = root / "daedalus"
    try:
        resolved_package = package_root.resolve(strict=True)
        resolved_package.relative_to(root)
    except (OSError, ValueError, RuntimeError) as exc:
        raise RepositoryWriteInventoryError(
            "daedalus package root is missing or escapes repository"
        ) from exc
    if package_root.is_symlink() or not resolved_package.is_dir():
        raise RepositoryWriteInventoryError(
            "daedalus package root must be a regular non-symlink directory"
        )
    files = _production_files(package_root)
    callsites = tuple(
        sorted(
            site
            for path in files
            for site in _callsites_for_file(root, package_root, path)
        )
    )
    return RepositoryWriteInventory(
        source_revision=str(source_revision),
        package_root=package_root.relative_to(root).as_posix(),
        scan_input_sha256=_scan_input(files, root),
        files_scanned=len(files),
        callsites=callsites,
    )
