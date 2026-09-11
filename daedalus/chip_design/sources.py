"""Hardware-design source classification.

This module is intentionally dependency-free. It gives Daedalus a stable
vocabulary for RTL, constraints and EDA automation files before any vendor or
open-source tool is invoked.
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class SourceSpec:
    path: str
    kind: str
    language: str
    role: str
    synthesizable: bool

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


# (kind, language, role, synthesizable)
_EXTENSIONS: dict[str, tuple[str, str, str, bool]] = {
    ".v": ("rtl", "verilog", "design/source", True),
    ".sv": ("rtl", "systemverilog", "design/source", True),
    ".vh": ("rtl_header", "verilog", "design/include", True),
    ".svh": ("rtl_header", "systemverilog", "design/include", True),
    ".vhd": ("rtl", "vhdl", "design/source", True),
    ".vhdl": ("rtl", "vhdl", "design/source", True),
    ".xdc": ("constraint", "xdc", "fpga/constraints", False),
    ".sdc": ("constraint", "sdc", "timing/constraints", False),
    ".qsf": ("constraint", "qsf", "quartus/project-constraints", False),
    ".xpr": ("project", "vivado-xpr", "vivado/project", False),
    ".bd": ("block_design", "vivado-bd", "vivado/source", True),
    ".xci": ("ip_config", "vivado-xci", "vivado/source", True),
    ".tcl": ("script", "tcl", "eda/automation", False),
    ".do": ("script", "tcl", "simulator/automation", False),
    ".sby": ("formal_config", "sby", "formal/config", False),
    ".f": ("filelist", "filelist", "build/source-list", False),
}

_IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "__pycache__",
    "node_modules", "dist", "build", "out", "target", ".cache",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".idea", ".vs",
    "ip_user_files", ".Xil",
}

_IGNORED_VENDOR_SUFFIXES = (".runs", ".cache", ".gen", ".sim", ".hw")


def classify_source(path: str | os.PathLike[str]) -> SourceSpec | None:
    p = Path(path)
    raw = _EXTENSIONS.get(p.suffix.lower())
    if raw is None:
        return None
    kind, language, role, synthesizable = raw
    return SourceSpec(
        path=p.as_posix(),
        kind=kind,
        language=language,
        role=role,
        synthesizable=synthesizable,
    )


def is_rtl(path: str | os.PathLike[str]) -> bool:
    spec = classify_source(path)
    return bool(spec and spec.kind in {"rtl", "rtl_header"})


def discover_sources(
    root: str | os.PathLike[str],
    *,
    max_files: int = 20_000,
    ignored_dirs: Iterable[str] = (),
) -> list[SourceSpec]:
    """Walk ``root`` and return recognized chip-design files in stable order.

    ``max_files`` is an exact output bound. Zero therefore means "return no
    files"; negative values are refused rather than accidentally returning one
    file after the first append. A missing/non-directory root is also refused
    rather than being misreported as an empty design.
    """
    if max_files < 0:
        raise ValueError("max_files must be >= 0")
    if max_files == 0:
        return []

    base = Path(root).resolve()
    if not base.is_dir():
        raise ValueError(f"scan root is not a directory: {base}")
    ignored = _IGNORED_DIRS | {str(x) for x in ignored_dirs}
    out: list[SourceSpec] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in ignored
            and not d.startswith(".")
            and not d.casefold().endswith(_IGNORED_VENDOR_SUFFIXES)
        )
        for name in sorted(filenames):
            spec = classify_source(Path(dirpath) / name)
            if spec is None:
                continue
            rel = (Path(dirpath) / name).resolve().relative_to(base).as_posix()
            out.append(SourceSpec(
                path=rel,
                kind=spec.kind,
                language=spec.language,
                role=spec.role,
                synthesizable=spec.synthesizable,
            ))
            if len(out) >= max_files:
                return out
    return out
