# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Registry and deterministic argv builders for chip-design toolchains.

No function in this module uses a shell. Tool-specific Tcl invocation is
encoded as data/argv so vendor syntax does not leak into arbitrary subprocess
strings scattered across Daedalus.
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

from .sources import classify_source


@dataclass(frozen=True)
class EdaToolSpec:
    id: str
    label: str
    command: str
    roles: tuple[str, ...]
    languages: tuple[str, ...] = ()
    version_args: tuple[str, ...] = ()
    tcl_backend: str = ""
    accepts_tcl_args: bool = False
    proprietary: bool = False
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


TOOLS: tuple[EdaToolSpec, ...] = (
    EdaToolSpec(
        id="tclsh", label="Tcl shell", command="tclsh",
        roles=("tcl",), tcl_backend="tclsh", accepts_tcl_args=True,
        notes="Generic Tcl interpreter; use vendor backends for vendor commands.",
    ),
    EdaToolSpec(
        id="verilator", label="Verilator", command="verilator",
        roles=("lint", "simulation"), languages=("verilog", "systemverilog"),
        version_args=("--version",),
        notes="Fast RTL lint/compile/simulation front end.",
    ),
    EdaToolSpec(
        id="verible", label="Verible SystemVerilog linter",
        command="verible-verilog-lint", roles=("style_lint", "syntax"),
        languages=("verilog", "systemverilog"), version_args=("--version",),
        notes="SystemVerilog developer tooling: parser/linter/formatter ecosystem.",
    ),
    EdaToolSpec(
        id="iverilog", label="Icarus Verilog", command="iverilog",
        roles=("simulation", "compile"), languages=("verilog", "systemverilog"),
        version_args=("-V",),
    ),
    EdaToolSpec(
        id="ghdl", label="GHDL", command="ghdl",
        roles=("simulation", "compile"), languages=("vhdl",),
        version_args=("--version",),
    ),
    EdaToolSpec(
        id="yosys", label="Yosys", command="yosys",
        roles=("synthesis", "formal_frontend", "tcl"),
        languages=("verilog", "systemverilog"), version_args=("-V",),
        tcl_backend="yosys",
        notes="Tcl is supported with yosys -c; script argv is intentionally not guessed.",
    ),
    EdaToolSpec(
        id="sby", label="SymbiYosys", command="sby",
        roles=("formal",), languages=("verilog", "systemverilog"),
        version_args=("--version",),
    ),
    EdaToolSpec(
        id="openroad", label="OpenROAD", command="openroad",
        roles=("physical_design", "sta", "tcl"), languages=("verilog",),
        version_args=("-version",), tcl_backend="openroad",
        notes="Runs Tcl command files; Daedalus adds -no_init -exit for reproducibility.",
    ),
    EdaToolSpec(
        id="vivado", label="AMD Vivado", command="vivado",
        roles=("fpga", "synthesis", "implementation", "simulation", "tcl"),
        languages=("verilog", "systemverilog", "vhdl"), version_args=("-version",),
        tcl_backend="vivado", accepts_tcl_args=True, proprietary=True,
    ),
    EdaToolSpec(
        id="quartus", label="Altera/Intel Quartus Prime", command="quartus_sh",
        roles=("fpga", "synthesis", "implementation", "sta", "tcl"),
        languages=("verilog", "systemverilog", "vhdl"), version_args=("--version",),
        tcl_backend="quartus", accepts_tcl_args=True, proprietary=True,
    ),
)

_TOOL_BY_ID = {tool.id: tool for tool in TOOLS}


def get_tool(tool_id: str) -> EdaToolSpec:
    try:
        return _TOOL_BY_ID[tool_id]
    except KeyError as exc:
        raise KeyError(f"unknown EDA tool '{tool_id}'") from exc


def tool_status(tool_id: str, *, timeout_s: float = 5.0) -> dict[str, object]:
    spec = get_tool(tool_id)
    path = shutil.which(spec.command)
    base = spec.to_dict()
    if not path:
        return {**base, "available": False, "command_path": "", "version": "",
                "last_error": f"{spec.command} not found on PATH"}
    if not spec.version_args:
        return {**base, "available": True, "command_path": path, "version": "",
                "last_error": ""}
    try:
        completed = subprocess.run(
            [path, *spec.version_args], text=True, capture_output=True,
            timeout=timeout_s, check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {**base, "available": False, "command_path": path, "version": "",
                "last_error": str(exc)}
    output = (completed.stdout or completed.stderr or "").strip()
    return {
        **base,
        "available": completed.returncode == 0,
        "command_path": path,
        "version": output if completed.returncode == 0 else "",
        "last_error": "" if completed.returncode == 0 else (output or f"exit {completed.returncode}"),
    }


def all_tool_status(*, timeout_s: float = 5.0) -> list[dict[str, object]]:
    return [tool_status(tool.id, timeout_s=timeout_s) for tool in TOOLS]


def _confined_file(repo_root: str | Path, path: str | Path, *, suffixes: Iterable[str] = ()) -> Path:
    root = Path(repo_root).resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes repository root: {path}") from exc
    if not candidate.is_file():
        raise ValueError(f"file does not exist: {candidate}")
    allowed = {s.lower() for s in suffixes}
    if allowed and candidate.suffix.lower() not in allowed:
        raise ValueError(f"unsupported file extension for {candidate.name}; expected {sorted(allowed)}")
    return candidate


def _confined_dir(repo_root: str | Path, path: str | Path) -> Path:
    root = Path(repo_root).resolve()
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path escapes repository root: {path}") from exc
    if not candidate.is_dir():
        raise ValueError(f"directory does not exist: {candidate}")
    return candidate


def build_tcl_argv(
    tool_id: str,
    script: str | Path,
    *,
    repo_root: str | Path,
    script_args: Iterable[str] = (),
) -> list[str]:
    spec = get_tool(tool_id)
    if not spec.tcl_backend:
        raise ValueError(f"tool '{tool_id}' is not registered as a Tcl backend")
    script_path = _confined_file(repo_root, script, suffixes=(".tcl",))
    args = [str(a) for a in script_args]
    if args and not spec.accepts_tcl_args:
        raise ValueError(
            f"tool '{tool_id}' has no documented direct Tcl argv mapping in Daedalus; "
            "encode parameters in the script/config instead"
        )
    if spec.tcl_backend == "tclsh":
        return [spec.command, str(script_path), *args]
    if spec.tcl_backend == "vivado":
        argv = [spec.command, "-mode", "batch", "-source", str(script_path)]
        if args:
            argv.extend(["-tclargs", *args])
        return argv
    if spec.tcl_backend == "quartus":
        return [spec.command, "-t", str(script_path), *args]
    if spec.tcl_backend == "yosys":
        return [spec.command, "-c", str(script_path)]
    if spec.tcl_backend == "openroad":
        return [spec.command, "-no_init", "-exit", str(script_path)]
    raise AssertionError(f"unhandled Tcl backend: {spec.tcl_backend}")


def build_rtl_lint_argv(
    tool_id: str,
    sources: Iterable[str | Path],
    *,
    repo_root: str | Path,
    top: str | None = None,
    include_dirs: Iterable[str | Path] = (),
    defines: Iterable[str] = (),
) -> list[str]:
    if tool_id not in {"verilator", "verible"}:
        raise ValueError("RTL lint currently supports 'verilator' or 'verible'")
    resolved: list[Path] = []
    for source in sources:
        p = _confined_file(repo_root, source, suffixes=(".v", ".sv", ".vh", ".svh"))
        spec = classify_source(p)
        if spec is None or spec.language not in {"verilog", "systemverilog"}:
            raise ValueError(f"not Verilog/SystemVerilog RTL: {source}")
        resolved.append(p)
    if not resolved:
        raise ValueError("at least one RTL source is required")

    if tool_id == "verible":
        if top or tuple(include_dirs) or tuple(defines):
            raise ValueError("top/include/define options belong to elaborating lint; use verilator")
        return [get_tool(tool_id).command, *(str(p) for p in resolved)]

    argv = [get_tool(tool_id).command, "--lint-only", "-Wall"]
    if top:
        argv.extend(["--top-module", top])
    for directory in include_dirs:
        argv.append(f"-I{_confined_dir(repo_root, directory)}")
    for define in defines:
        text = str(define).strip()
        if not text or any(ch.isspace() for ch in text):
            raise ValueError(f"invalid Verilog define: {define!r}")
        argv.append(f"-D{text}")
    argv.extend(str(p) for p in resolved)
    return argv
