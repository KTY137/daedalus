"""Structural resolution of exact Daedalus Python implementation targets.

This module joins a canonical ``daedalus.module:Qualified.name`` target to an
exact repository source snapshot and a unique Python AST definition chain. It
establishes structural presence only. It does not execute imports, evaluate
decorators, infer behavior, replay a guard, authenticate evidence, or grant
effect, approval, promotion, or Gate authority.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from daedalus.gates.repository_tree import (
    RepositorySourceSnapshot,
    RepositoryTreeReadError,
    read_repository_source,
)


_TARGET = re.compile(
    r"^(daedalus(?:\.[A-Za-z_][A-Za-z0-9_]*)*):"
    r"([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*)$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PythonTargetStructureError(RuntimeError):
    """A Python target is malformed, missing, ambiguous, or stale."""


class PythonTargetSourceError(PythonTargetStructureError):
    """The target source cannot be read or parsed exactly."""


class PythonTargetBindingError(PythonTargetStructureError):
    """The target or source digest differs from the expected subject."""


def parse_python_target(value: object) -> tuple[str, tuple[str, ...]]:
    if not isinstance(value, str):
        raise PythonTargetStructureError(
            "target must be a canonical Daedalus Python target"
        )
    match = _TARGET.fullmatch(value)
    if match is None:
        raise PythonTargetStructureError(
            "target must be a canonical Daedalus Python target"
        )
    return match.group(1), tuple(match.group(2).split("."))


def module_repository_path(module_name: str) -> str:
    module, _ = parse_python_target(f"{module_name}:placeholder")
    return module.replace(".", "/") + ".py"


def _definition_kind(node: ast.AST) -> str:
    if isinstance(node, ast.AsyncFunctionDef):
        return "async_function"
    if isinstance(node, ast.FunctionDef):
        return "function"
    if isinstance(node, ast.ClassDef):
        return "class"
    raise PythonTargetStructureError(
        "target chain contains an unsupported definition kind"
    )


def _named_definitions(
    body: Sequence[ast.stmt],
    name: str,
) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, ...]:
    return tuple(
        node
        for node in body
        if isinstance(
            node,
            (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
        )
        and node.name == name
    )


def _resolve_definition_chain(
    tree: ast.Module,
    names: tuple[str, ...],
) -> tuple[ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, ...]:
    if not names:
        raise PythonTargetStructureError("target object chain is empty")
    body: Sequence[ast.stmt] = tree.body
    resolved: list[
        ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef
    ] = []
    for index, name in enumerate(names):
        matches = _named_definitions(body, name)
        if not matches:
            raise PythonTargetBindingError(
                f"target definition is missing: {'.'.join(names[: index + 1])}"
            )
        if len(matches) != 1:
            raise PythonTargetBindingError(
                f"target definition is ambiguous: {'.'.join(names[: index + 1])}"
            )
        selected = matches[0]
        resolved.append(selected)
        if index < len(names) - 1:
            if not isinstance(selected, ast.ClassDef):
                raise PythonTargetBindingError(
                    "only classes may contain a qualified target child"
                )
            body = selected.body
    return tuple(resolved)


@dataclass(frozen=True)
class PythonTargetStructure:
    target: str
    module_name: str
    object_path: tuple[str, ...]
    source_path: str
    source_sha256: str
    source_size: int
    definition_kind: str
    line: int
    column: int
    end_line: int
    end_column: int
    chain_kinds: tuple[str, ...]

    def __post_init__(self) -> None:
        parsed_module, parsed_path = parse_python_target(self.target)
        if self.module_name != parsed_module:
            raise ValueError("module_name differs from target")
        if self.object_path != parsed_path:
            raise ValueError("object_path differs from target")
        if self.source_path != module_repository_path(self.module_name):
            raise ValueError("source_path differs from module mapping")
        if (
            not isinstance(self.source_sha256, str)
            or _SHA256.fullmatch(self.source_sha256) is None
        ):
            raise ValueError("source_sha256 must be lowercase sha256")
        if type(self.source_size) is not int or self.source_size < 0:
            raise ValueError("source_size must be a non-negative strict integer")
        allowed = {"class", "function", "async_function"}
        if self.definition_kind not in allowed:
            raise ValueError("definition_kind is unsupported")
        for field_name in ("line", "end_line"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{field_name} must be a positive strict integer")
        for field_name in ("column", "end_column"):
            value = getattr(self, field_name)
            if type(value) is not int or value < 0:
                raise ValueError(
                    f"{field_name} must be a non-negative strict integer"
                )
        if self.end_line < self.line:
            raise ValueError("definition end precedes its start")
        if not isinstance(self.chain_kinds, tuple) or not self.chain_kinds:
            raise ValueError("chain_kinds must be a non-empty immutable tuple")
        if len(self.chain_kinds) != len(self.object_path):
            raise ValueError("chain_kinds length differs from object_path")
        if any(kind not in allowed for kind in self.chain_kinds):
            raise ValueError("chain_kinds contains an unsupported kind")
        if any(kind != "class" for kind in self.chain_kinds[:-1]):
            raise ValueError("qualified target parents must be classes")
        if self.chain_kinds[-1] != self.definition_kind:
            raise ValueError("definition_kind differs from the chain terminal")

    def to_dict(self) -> dict[str, object]:
        return {
            "target": self.target,
            "module_name": self.module_name,
            "object_path": list(self.object_path),
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "source_size": self.source_size,
            "definition_kind": self.definition_kind,
            "line": self.line,
            "column": self.column,
            "end_line": self.end_line,
            "end_column": self.end_column,
            "chain_kinds": list(self.chain_kinds),
            "structural_target_verified": True,
            "behavior_verified": False,
            "executed": False,
        }


def resolve_python_target_structure(
    repository_root: Path,
    target: str,
    *,
    expected_source_sha256: str,
) -> PythonTargetStructure:
    module_name, object_path = parse_python_target(target)
    if (
        not isinstance(expected_source_sha256, str)
        or _SHA256.fullmatch(expected_source_sha256) is None
    ):
        raise PythonTargetStructureError(
            "expected_source_sha256 must be lowercase sha256"
        )
    source_path = module_repository_path(module_name)
    try:
        snapshot = read_repository_source(repository_root, source_path)
    except RepositoryTreeReadError as exc:
        raise PythonTargetSourceError(
            f"target source cannot be read: {source_path}"
        ) from exc
    if snapshot.source_sha256 != expected_source_sha256:
        raise PythonTargetBindingError(
            "target source digest differs from expectation"
        )
    tree = _parse_source(snapshot)
    chain = _resolve_definition_chain(tree, object_path)
    terminal = chain[-1]
    if (
        terminal.end_lineno is None
        or terminal.end_col_offset is None
    ):
        raise PythonTargetSourceError(
            "target definition lacks complete source positions"
        )
    return PythonTargetStructure(
        target=target,
        module_name=module_name,
        object_path=object_path,
        source_path=source_path,
        source_sha256=snapshot.source_sha256,
        source_size=snapshot.size,
        definition_kind=_definition_kind(terminal),
        line=terminal.lineno,
        column=terminal.col_offset,
        end_line=terminal.end_lineno,
        end_column=terminal.end_col_offset,
        chain_kinds=tuple(_definition_kind(node) for node in chain),
    )


def _parse_source(snapshot: RepositorySourceSnapshot) -> ast.Module:
    if not isinstance(snapshot, RepositorySourceSnapshot):
        raise PythonTargetSourceError("source snapshot type is invalid")
    try:
        parsed = ast.parse(
            snapshot.source,
            filename=snapshot.path,
            mode="exec",
            type_comments=True,
        )
    except (SyntaxError, ValueError, MemoryError, RecursionError) as exc:
        raise PythonTargetSourceError(
            f"target source is not a valid bounded Python module: {snapshot.path}"
        ) from exc
    if not isinstance(parsed, ast.Module):
        raise PythonTargetSourceError("target source did not parse as a module")
    return parsed


__all__ = [
    "PythonTargetBindingError",
    "PythonTargetSourceError",
    "PythonTargetStructure",
    "PythonTargetStructureError",
    "module_repository_path",
    "parse_python_target",
    "resolve_python_target_structure",
]
