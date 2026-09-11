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
from pathlib import Path
from typing import Sequence

from daedalus.gates.repository.tree import (
    RepositorySourceSnapshot,
    RepositoryTreeReadError,
    read_repository_source,
)
from daedalus.runtimes.contracts.python_targets import (
    PythonTargetBindingError,
    PythonTargetSourceError,
    PythonTargetStructure,
    PythonTargetStructureError,
    module_repository_path,
    parse_python_target,
)


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


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
