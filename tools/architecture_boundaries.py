"""Deterministic tracked-source import-boundary contract.

The checker parses only Python files returned by ``git ls-files`` below the
configured source root.  It never imports repository modules.  Existing
violations are retained as an exact, reviewable baseline: removing debt is
allowed, while a new or relocated violation fails the check.

This is structural evidence only.  Dynamic imports, runtime dispatch,
monkey-patching and generated code remain outside the observation boundary.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence


_MODULE_NAME = re.compile(r"^daedalus(?:\.[A-Za-z_][A-Za-z0-9_]*)*$")
_RULE_ID = re.compile(r"^[a-z][a-z0-9-]*$")
_ALLOWED_IMPORT_KINDS = frozenset({"import", "import_from"})
_MAX_SOURCE_BYTES = 2 * 1024 * 1024


class ArchitectureBoundaryError(RuntimeError):
    """The boundary contract or the tracked source set cannot be measured."""


def _is_module_or_child(module: str, prefix: str) -> bool:
    return module == prefix or module.startswith(prefix + ".")


def _require_dict(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ArchitectureBoundaryError(f"{field} must be an object")
    if any(not isinstance(key, str) for key in value):
        raise ArchitectureBoundaryError(f"{field} keys must be strings")
    return value


def _require_exact_keys(
    value: dict[str, object],
    *,
    expected: set[str],
    field: str,
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise ArchitectureBoundaryError(
            f"{field} keys differ: missing={missing}, extra={extra}"
        )


def _require_non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ArchitectureBoundaryError(
            f"{field} must be a non-empty, trimmed string"
        )
    return value


def _require_module_prefix(value: object, field: str) -> str:
    module = _require_non_empty_string(value, field)
    if _MODULE_NAME.fullmatch(module) is None:
        raise ArchitectureBoundaryError(
            f"{field} must be a canonical daedalus module prefix"
        )
    return module


def _require_module_prefixes(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise ArchitectureBoundaryError(f"{field} must be a non-empty array")
    prefixes = tuple(
        _require_module_prefix(item, f"{field}[{index}]")
        for index, item in enumerate(value)
    )
    if len(prefixes) != len(set(prefixes)):
        raise ArchitectureBoundaryError(f"{field} contains duplicate prefixes")
    if tuple(sorted(prefixes)) != prefixes:
        raise ArchitectureBoundaryError(f"{field} must be sorted")
    return prefixes


@dataclass(frozen=True, order=True)
class BoundaryViolation:
    """One statically observed forbidden import edge."""

    rule_id: str
    source_path: str
    source_module: str
    target_module: str
    line: int
    column: int
    kind: str

    def __post_init__(self) -> None:
        if _RULE_ID.fullmatch(self.rule_id) is None:
            raise ArchitectureBoundaryError("violation rule_id is invalid")
        if (
            not self.source_path.startswith("daedalus/")
            or not self.source_path.endswith(".py")
            or "\\" in self.source_path
            or "/../" in f"/{self.source_path}/"
        ):
            raise ArchitectureBoundaryError(
                "violation source_path must be normalized tracked Python source"
            )
        _require_module_prefix(self.source_module, "violation.source_module")
        _require_module_prefix(self.target_module, "violation.target_module")
        if type(self.line) is not int or self.line < 1:
            raise ArchitectureBoundaryError(
                "violation line must be a positive strict integer"
            )
        if type(self.column) is not int or self.column < 0:
            raise ArchitectureBoundaryError(
                "violation column must be a non-negative strict integer"
            )
        if self.kind not in _ALLOWED_IMPORT_KINDS:
            raise ArchitectureBoundaryError("violation import kind is invalid")

    @classmethod
    def from_dict(cls, value: object, field: str) -> "BoundaryViolation":
        payload = _require_dict(value, field)
        keys = {
            "rule_id",
            "source_path",
            "source_module",
            "target_module",
            "line",
            "column",
            "kind",
        }
        _require_exact_keys(payload, expected=keys, field=field)
        return cls(
            rule_id=_require_non_empty_string(
                payload["rule_id"], f"{field}.rule_id"
            ),
            source_path=_require_non_empty_string(
                payload["source_path"], f"{field}.source_path"
            ),
            source_module=_require_module_prefix(
                payload["source_module"], f"{field}.source_module"
            ),
            target_module=_require_module_prefix(
                payload["target_module"], f"{field}.target_module"
            ),
            line=payload["line"],  # type: ignore[arg-type]
            column=payload["column"],  # type: ignore[arg-type]
            kind=_require_non_empty_string(payload["kind"], f"{field}.kind"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "rule_id": self.rule_id,
            "source_path": self.source_path,
            "source_module": self.source_module,
            "target_module": self.target_module,
            "line": self.line,
            "column": self.column,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class ImportBoundaryRule:
    """A directed source-prefix to forbidden-target-prefix rule."""

    rule_id: str
    source_prefixes: tuple[str, ...]
    forbidden_target_prefixes: tuple[str, ...]
    rationale: str
    target_owner: str

    @classmethod
    def from_dict(cls, value: object, field: str) -> "ImportBoundaryRule":
        payload = _require_dict(value, field)
        keys = {
            "id",
            "source_prefixes",
            "forbidden_target_prefixes",
            "rationale",
            "target_owner",
        }
        _require_exact_keys(payload, expected=keys, field=field)
        rule_id = _require_non_empty_string(payload["id"], f"{field}.id")
        if _RULE_ID.fullmatch(rule_id) is None:
            raise ArchitectureBoundaryError(f"{field}.id is invalid")
        return cls(
            rule_id=rule_id,
            source_prefixes=_require_module_prefixes(
                payload["source_prefixes"], f"{field}.source_prefixes"
            ),
            forbidden_target_prefixes=_require_module_prefixes(
                payload["forbidden_target_prefixes"],
                f"{field}.forbidden_target_prefixes",
            ),
            rationale=_require_non_empty_string(
                payload["rationale"], f"{field}.rationale"
            ),
            target_owner=_require_non_empty_string(
                payload["target_owner"], f"{field}.target_owner"
            ),
        )

    def applies_to(self, source_module: str) -> bool:
        return any(
            _is_module_or_child(source_module, prefix)
            for prefix in self.source_prefixes
        )

    def forbidden_target(self, candidates: Sequence[str]) -> str | None:
        for candidate in candidates:
            if any(
                _is_module_or_child(candidate, prefix)
                for prefix in self.forbidden_target_prefixes
            ):
                return candidate
        return None


@dataclass(frozen=True)
class ImportBoundaryContract:
    """Validated machine-readable boundary rules and debt baseline."""

    contract_id: str
    master_plan_revision: int
    active_gate: int
    baseline_revision: str
    source_root: str
    tracked_source_command: tuple[str, ...]
    rules: tuple[ImportBoundaryRule, ...]
    baseline: tuple[BoundaryViolation, ...]
    shim_registry: str


@dataclass(frozen=True, order=True)
class ShimEntry:
    """One owned compatibility import with an explicit retirement gate."""

    import_path: str
    owner: str
    targets: tuple[str, ...]
    kind: str
    removal_criteria: str

    @classmethod
    def from_dict(cls, value: object, field: str) -> "ShimEntry":
        payload = _require_dict(value, field)
        keys = {"import_path", "owner", "targets", "kind", "removal_criteria"}
        _require_exact_keys(payload, expected=keys, field=field)
        return cls(
            import_path=_require_module_prefix(
                payload["import_path"], f"{field}.import_path"
            ),
            owner=_require_non_empty_string(payload["owner"], f"{field}.owner"),
            targets=_require_module_prefixes(
                payload["targets"], f"{field}.targets"
            ),
            kind=_require_non_empty_string(payload["kind"], f"{field}.kind"),
            removal_criteria=_require_non_empty_string(
                payload["removal_criteria"], f"{field}.removal_criteria"
            ),
        )


@dataclass(frozen=True)
class _ImportReference:
    candidates: tuple[str, ...]
    line: int
    column: int
    kind: str


@dataclass(frozen=True)
class BoundaryReport:
    """Deterministic comparison between current edges and reviewed debt."""

    contract_id: str
    master_plan_revision: int
    active_gate: int
    baseline_revision: str
    tracked_python_files: int
    shim_entry_count: int
    current: tuple[BoundaryViolation, ...]
    allowlisted: tuple[BoundaryViolation, ...]
    new: tuple[BoundaryViolation, ...]
    resolved: tuple[BoundaryViolation, ...]

    @property
    def passed(self) -> bool:
        return not self.new

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "contract_id": self.contract_id,
            "master_plan_revision": self.master_plan_revision,
            "active_gate": self.active_gate,
            "baseline_revision": self.baseline_revision,
            "tracked_python_files": self.tracked_python_files,
            "shim_entry_count": self.shim_entry_count,
            "current_violation_count": len(self.current),
            "allowlisted_violation_count": len(self.allowlisted),
            "new_violation_count": len(self.new),
            "resolved_baseline_count": len(self.resolved),
            "passed": self.passed,
            "current_violations": [item.to_dict() for item in self.current],
            "allowlisted_violations": [
                item.to_dict() for item in self.allowlisted
            ],
            "new_violations": [item.to_dict() for item in self.new],
            "resolved_baseline": [item.to_dict() for item in self.resolved],
            "evidence_basis": "python_ast_direct_syntax",
            "runtime_status": "runtime_unknown",
            "unsupported_runtime": [
                "dynamic_imports",
                "generated_code",
                "monkey_patching",
                "runtime_dispatch",
            ],
        }


def load_contract(path: Path) -> ImportBoundaryContract:
    """Load and strictly validate one JSON boundary contract."""
    if not isinstance(path, Path):
        raise ArchitectureBoundaryError("contract path must be pathlib.Path")
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ArchitectureBoundaryError(
            f"boundary contract cannot be read: {path}"
        ) from exc
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ArchitectureBoundaryError("boundary contract is not strict JSON") from exc
    payload = _require_dict(value, "contract")
    keys = {
        "schema_version",
        "contract_id",
        "master_plan_revision",
        "active_gate",
        "baseline_revision",
        "source",
        "rules",
        "baseline",
        "shim_registry",
    }
    _require_exact_keys(payload, expected=keys, field="contract")
    if payload["schema_version"] != 1:
        raise ArchitectureBoundaryError("unsupported boundary schema_version")
    contract_id = _require_non_empty_string(
        payload["contract_id"], "contract.contract_id"
    )
    master_plan_revision = payload["master_plan_revision"]
    if type(master_plan_revision) is not int or master_plan_revision < 1:
        raise ArchitectureBoundaryError(
            "contract.master_plan_revision must be a positive strict integer"
        )
    active_gate = payload["active_gate"]
    if type(active_gate) is not int or not 0 <= active_gate <= 5:
        raise ArchitectureBoundaryError(
            "contract.active_gate must be a strict integer from 0 through 5"
        )
    baseline_revision = _require_non_empty_string(
        payload["baseline_revision"], "contract.baseline_revision"
    )
    if re.fullmatch(r"[0-9a-f]{40}", baseline_revision) is None:
        raise ArchitectureBoundaryError(
            "contract.baseline_revision must be a full lowercase Git SHA-1"
        )

    source = _require_dict(payload["source"], "contract.source")
    _require_exact_keys(
        source,
        expected={"root", "tracked_source_command", "include_suffixes"},
        field="contract.source",
    )
    source_root = _require_non_empty_string(
        source["root"], "contract.source.root"
    )
    if source_root != "daedalus":
        raise ArchitectureBoundaryError(
            "contract.source.root must remain the canonical daedalus package"
        )
    command = source["tracked_source_command"]
    if not isinstance(command, list) or any(
        not isinstance(item, str) for item in command
    ):
        raise ArchitectureBoundaryError(
            "contract.source.tracked_source_command must be a string array"
        )
    tracked_source_command = tuple(command)
    expected_command = ("git", "ls-files", "-z", "--", "daedalus")
    if tracked_source_command != expected_command:
        raise ArchitectureBoundaryError(
            "tracked source command must be the pinned git ls-files command"
        )
    if source["include_suffixes"] != [".py"]:
        raise ArchitectureBoundaryError(
            "contract source suffix must remain the Python source set"
        )

    raw_rules = payload["rules"]
    if not isinstance(raw_rules, list) or not raw_rules:
        raise ArchitectureBoundaryError("contract.rules must be non-empty")
    rules = tuple(
        ImportBoundaryRule.from_dict(item, f"contract.rules[{index}]")
        for index, item in enumerate(raw_rules)
    )
    rule_ids = tuple(rule.rule_id for rule in rules)
    if len(rule_ids) != len(set(rule_ids)):
        raise ArchitectureBoundaryError("contract.rules contains duplicate IDs")
    if tuple(sorted(rule_ids)) != rule_ids:
        raise ArchitectureBoundaryError("contract.rules must be sorted by ID")

    raw_baseline = payload["baseline"]
    if not isinstance(raw_baseline, list):
        raise ArchitectureBoundaryError("contract.baseline must be an array")
    baseline = tuple(
        BoundaryViolation.from_dict(item, f"contract.baseline[{index}]")
        for index, item in enumerate(raw_baseline)
    )
    if tuple(sorted(baseline)) != baseline:
        raise ArchitectureBoundaryError(
            "contract.baseline must use deterministic violation order"
        )
    if len(baseline) != len(set(baseline)):
        raise ArchitectureBoundaryError(
            "contract.baseline contains duplicate violations"
        )
    known_rule_ids = set(rule_ids)
    unknown_rules = sorted(
        {item.rule_id for item in baseline} - known_rule_ids
    )
    if unknown_rules:
        raise ArchitectureBoundaryError(
            f"contract.baseline names unknown rules: {unknown_rules}"
        )

    shim_registry = _require_non_empty_string(
        payload["shim_registry"], "contract.shim_registry"
    )
    if shim_registry != "docs/architecture/shim-registry.json":
        raise ArchitectureBoundaryError(
            "contract.shim_registry must name the reviewed registry"
        )
    return ImportBoundaryContract(
        contract_id=contract_id,
        master_plan_revision=master_plan_revision,
        active_gate=active_gate,
        baseline_revision=baseline_revision,
        source_root=source_root,
        tracked_source_command=tracked_source_command,
        rules=rules,
        baseline=baseline,
        shim_registry=shim_registry,
    )


def load_shim_registry(
    path: Path,
    contract: ImportBoundaryContract,
) -> tuple[ShimEntry, ...]:
    """Load the registry and bind it to the same plan, gate and baseline."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ArchitectureBoundaryError(
            f"shim registry cannot be read: {path}"
        ) from exc
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise ArchitectureBoundaryError("shim registry is not strict JSON") from exc
    payload = _require_dict(value, "shim_registry")
    keys = {
        "schema_version",
        "registry_id",
        "master_plan_revision",
        "active_gate",
        "baseline_revision",
        "entries",
    }
    _require_exact_keys(payload, expected=keys, field="shim_registry")
    if payload["schema_version"] != 1:
        raise ArchitectureBoundaryError("unsupported shim registry schema_version")
    _require_non_empty_string(payload["registry_id"], "shim_registry.registry_id")
    if payload["master_plan_revision"] != contract.master_plan_revision:
        raise ArchitectureBoundaryError(
            "shim registry master-plan revision differs from boundary contract"
        )
    if payload["active_gate"] != contract.active_gate:
        raise ArchitectureBoundaryError(
            "shim registry active gate differs from boundary contract"
        )
    if payload["baseline_revision"] != contract.baseline_revision:
        raise ArchitectureBoundaryError(
            "shim registry baseline revision differs from boundary contract"
        )
    raw_entries = payload["entries"]
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ArchitectureBoundaryError("shim registry entries must be non-empty")
    entries = tuple(
        ShimEntry.from_dict(item, f"shim_registry.entries[{index}]")
        for index, item in enumerate(raw_entries)
    )
    if tuple(sorted(entries)) != entries:
        raise ArchitectureBoundaryError(
            "shim registry entries must be sorted by import path"
        )
    import_paths = tuple(entry.import_path for entry in entries)
    if len(import_paths) != len(set(import_paths)):
        raise ArchitectureBoundaryError(
            "shim registry contains duplicate import paths"
        )
    return entries


def _tracked_python_paths(
    repository_root: Path,
    contract: ImportBoundaryContract,
) -> tuple[str, ...]:
    try:
        completed = subprocess.run(
            list(contract.tracked_source_command),
            cwd=repository_root,
            check=False,
            capture_output=True,
            text=False,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ArchitectureBoundaryError("git ls-files could not run") from exc
    if completed.returncode != 0:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        raise ArchitectureBoundaryError(
            f"git ls-files failed with exit {completed.returncode}: {stderr}"
        )
    try:
        decoded = completed.stdout.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ArchitectureBoundaryError(
            "git ls-files returned a non-UTF-8 tracked path"
        ) from exc
    paths = tuple(
        sorted(
            path
            for path in decoded.split("\0")
            if path and path.endswith(".py")
        )
    )
    if not paths:
        raise ArchitectureBoundaryError("tracked Python source set is empty")
    expected_prefix = contract.source_root + "/"
    if any(
        not path.startswith(expected_prefix)
        or "\\" in path
        or "/../" in f"/{path}/"
        for path in paths
    ):
        raise ArchitectureBoundaryError(
            "git ls-files returned a path outside the declared source root"
        )
    return paths


def _tracked_module_paths(module: str) -> tuple[str, str]:
    stem = module.replace(".", "/")
    return f"{stem}.py", f"{stem}/__init__.py"


def validate_shim_locators(
    repository_root: Path,
    contract: ImportBoundaryContract,
    entries: Sequence[ShimEntry],
) -> None:
    """Require every facade and target module to exist in the tracked census."""
    tracked = set(_tracked_python_paths(repository_root, contract))
    for entry in entries:
        if not any(path in tracked for path in _tracked_module_paths(entry.import_path)):
            raise ArchitectureBoundaryError(
                f"shim import locator is not tracked: {entry.import_path}"
            )
        for target in entry.targets:
            if not any(path in tracked for path in _tracked_module_paths(target)):
                raise ArchitectureBoundaryError(
                    f"shim target locator is not tracked: {target}"
                )


def _module_name_for_path(path: str) -> str:
    parts = path[:-3].split("/")
    if parts[-1] == "__init__":
        parts.pop()
    module = ".".join(parts)
    return _require_module_prefix(module, "tracked source module")


def _read_tracked_source(repository_root: Path, path: str) -> str:
    """Read one bounded regular file without following a path component link."""
    current = repository_root
    metadata = None
    parts = path.split("/")
    for index, part in enumerate(parts):
        current = current / part
        try:
            metadata = current.lstat()
        except OSError as exc:
            raise ArchitectureBoundaryError(
                f"tracked source is unavailable: {path}"
            ) from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise ArchitectureBoundaryError(
                f"tracked source path contains a symlink: {path}"
            )
        if index < len(parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
            raise ArchitectureBoundaryError(
                f"tracked source parent is not a directory: {path}"
            )
    if metadata is None or not stat.S_ISREG(metadata.st_mode):
        raise ArchitectureBoundaryError(
            f"tracked source is not a regular file: {path}"
        )
    if metadata.st_size > _MAX_SOURCE_BYTES:
        raise ArchitectureBoundaryError(
            f"tracked source exceeds the bounded source size: {path}"
        )
    try:
        resolved = current.resolve(strict=True)
        resolved.relative_to(repository_root)
        source_bytes = current.read_bytes()
        after = current.lstat()
    except (OSError, ValueError) as exc:
        raise ArchitectureBoundaryError(
            f"tracked source cannot be read safely: {path}"
        ) from exc
    before_identity = (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if (
        before_identity != after_identity
        or stat.S_ISLNK(after.st_mode)
        or not stat.S_ISREG(after.st_mode)
        or len(source_bytes) != metadata.st_size
    ):
        raise ArchitectureBoundaryError(
            f"tracked source changed during measurement: {path}"
        )
    if len(source_bytes) > _MAX_SOURCE_BYTES or b"\0" in source_bytes:
        raise ArchitectureBoundaryError(
            f"tracked source is not bounded Python text: {path}"
        )
    try:
        return source_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ArchitectureBoundaryError(
            f"tracked source cannot be read as UTF-8: {path}"
        ) from exc


def _import_from_candidates(
    node: ast.ImportFrom,
    *,
    source_module: str,
    is_package: bool,
) -> tuple[str, ...]:
    if node.level:
        package = source_module if is_package else source_module.rpartition(".")[0]
        relative = "." * node.level + (node.module or "")
        try:
            base = importlib.util.resolve_name(relative, package)
        except (ImportError, ValueError) as exc:
            raise ArchitectureBoundaryError(
                f"relative import cannot be resolved in {source_module} at "
                f"line {node.lineno}"
            ) from exc
    else:
        base = node.module or ""
    if not base:
        return ()
    candidates = [base]
    candidates.extend(
        f"{base}.{alias.name}"
        for alias in node.names
        if alias.name != "*"
    )
    return tuple(candidates)


def _import_references(
    tree: ast.Module,
    *,
    source_module: str,
    is_package: bool,
) -> Iterable[_ImportReference]:
    nodes = sorted(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ),
        key=lambda node: (node.lineno, node.col_offset),
    )
    for node in nodes:
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield _ImportReference(
                    candidates=(alias.name,),
                    line=node.lineno,
                    column=node.col_offset,
                    kind="import",
                )
            continue
        candidates = _import_from_candidates(
            node,
            source_module=source_module,
            is_package=is_package,
        )
        if candidates:
            yield _ImportReference(
                candidates=candidates,
                line=node.lineno,
                column=node.col_offset,
                kind="import_from",
            )


def scan_repository(
    repository_root: Path,
    contract: ImportBoundaryContract,
) -> tuple[tuple[BoundaryViolation, ...], int]:
    """Return forbidden direct-syntax import edges from tracked Python only."""
    if not isinstance(repository_root, Path):
        raise ArchitectureBoundaryError("repository_root must be pathlib.Path")
    try:
        root = repository_root.resolve(strict=True)
    except OSError as exc:
        raise ArchitectureBoundaryError("repository root is unavailable") from exc
    paths = _tracked_python_paths(root, contract)
    violations: list[BoundaryViolation] = []
    for path in paths:
        source = _read_tracked_source(root, path)
        try:
            tree = ast.parse(source, filename=path, type_comments=True)
        except (SyntaxError, ValueError, MemoryError, RecursionError) as exc:
            raise ArchitectureBoundaryError(
                f"tracked source cannot be parsed: {path}: {exc}"
            ) from exc
        source_module = _module_name_for_path(path)
        applicable_rules = tuple(
            rule for rule in contract.rules if rule.applies_to(source_module)
        )
        if not applicable_rules:
            continue
        for reference in _import_references(
            tree,
            source_module=source_module,
            is_package=path.endswith("/__init__.py"),
        ):
            for rule in applicable_rules:
                target = rule.forbidden_target(reference.candidates)
                if target is None:
                    continue
                violations.append(
                    BoundaryViolation(
                        rule_id=rule.rule_id,
                        source_path=path,
                        source_module=source_module,
                        target_module=target,
                        line=reference.line,
                        column=reference.column,
                        kind=reference.kind,
                    )
                )
    ordered = tuple(sorted(violations))
    if len(ordered) != len(set(ordered)):
        raise ArchitectureBoundaryError(
            "scanner produced duplicate forbidden import edges"
        )
    return ordered, len(paths)


def evaluate_repository(
    repository_root: Path,
    contract: ImportBoundaryContract,
) -> BoundaryReport:
    shim_entries = load_shim_registry(
        repository_root / contract.shim_registry,
        contract,
    )
    validate_shim_locators(repository_root, contract, shim_entries)
    current, tracked_count = scan_repository(repository_root, contract)
    current_set = set(current)
    baseline_set = set(contract.baseline)
    return BoundaryReport(
        contract_id=contract.contract_id,
        master_plan_revision=contract.master_plan_revision,
        active_gate=contract.active_gate,
        baseline_revision=contract.baseline_revision,
        tracked_python_files=tracked_count,
        shim_entry_count=len(shim_entries),
        current=current,
        allowlisted=tuple(sorted(current_set & baseline_set)),
        new=tuple(sorted(current_set - baseline_set)),
        resolved=tuple(sorted(baseline_set - current_set)),
    )


def render_human(report: BoundaryReport) -> str:
    status = "PASS" if report.passed else "FAIL"
    lines = [
        (
            f"{status} {report.contract_id}: "
            f"tracked_python_files={report.tracked_python_files} "
            f"shims={report.shim_entry_count} "
            f"current={len(report.current)} "
            f"allowlisted={len(report.allowlisted)} "
            f"new={len(report.new)} resolved={len(report.resolved)}"
        ),
        "Existing allowlisted edges are architecture debt, not approved design.",
    ]
    for label, items in (
        ("NEW", report.new),
        ("BASELINE", report.allowlisted),
        ("RESOLVED", report.resolved),
    ):
        for item in items:
            lines.append(
                f"{label} {item.rule_id} {item.source_path}:"
                f"{item.line}:{item.column} -> {item.target_module}"
            )
    return "\n".join(lines) + "\n"


__all__ = [
    "ArchitectureBoundaryError",
    "BoundaryReport",
    "BoundaryViolation",
    "ImportBoundaryContract",
    "ImportBoundaryRule",
    "ShimEntry",
    "evaluate_repository",
    "load_contract",
    "load_shim_registry",
    "render_human",
    "scan_repository",
    "validate_shim_locators",
]
