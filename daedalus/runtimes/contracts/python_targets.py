"""Neutral structural receipt for a gate-resolved Python target."""

from __future__ import annotations

import re
from dataclasses import dataclass


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


__all__ = [
    "PythonTargetBindingError",
    "PythonTargetSourceError",
    "PythonTargetStructure",
    "PythonTargetStructureError",
    "module_repository_path",
    "parse_python_target",
]
