"""Registry and deterministic argv builders for chip-design toolchains.

No function in this module uses a shell. Tool-specific Tcl invocation is
encoded as data/argv so vendor syntax does not leak into arbitrary subprocess
strings scattered across Daedalus.
"""
from __future__ import annotations

import glob
import hashlib
import os
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, Mapping

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
        id="vitis", label="AMD Vitis", command="vitis",
        roles=("embedded_software", "hardware_platform", "acceleration"),
        version_args=("-version",), proprietary=True,
        notes=(
            "Discovery only in the Gate-1 Vivado slice; an XSA without a Vitis "
            "workspace/application is not an executable software mission."
        ),
    ),
    EdaToolSpec(
        id="xsct", label="AMD XSCT", command="xsct",
        roles=("embedded_software", "tcl"), version_args=("-version",),
        proprietary=True,
        notes="Discovery only; no XSCT execution adapter is admitted by this slice.",
    ),
    EdaToolSpec(
        id="quartus", label="Altera/Intel Quartus Prime", command="quartus_sh",
        roles=("fpga", "synthesis", "implementation", "sta", "tcl"),
        languages=("verilog", "systemverilog", "vhdl"), version_args=("--version",),
        tcl_backend="quartus", accepts_tcl_args=True, proprietary=True,
    ),
)

_TOOL_BY_ID = {tool.id: tool for tool in TOOLS}

_WINDOWS_TOOL_GLOBS: Mapping[str, tuple[str, ...]] = {
    # AMD's unified 2025.x installer uses C:/Xilinx/<release>/Vivado while
    # older installers commonly use C:/Xilinx/Vivado/<release>.
    "vivado": (
        "C:/Xilinx/*/Vivado/bin/vivado.bat",
        "C:/Xilinx/Vivado/*/bin/vivado.bat",
    ),
    "vitis": (
        "C:/Xilinx/*/Vitis/bin/vitis.bat",
        "C:/Xilinx/Vitis/*/bin/vitis.bat",
    ),
    "xsct": (
        "C:/Xilinx/*/Vitis/bin/xsct.bat",
        "C:/Xilinx/Vitis/*/bin/xsct.bat",
    ),
    "quartus": (
        "C:/intelFPGA*/*/quartus/bin64/quartus_sh.exe",
        "C:/altera/*/quartus/bin64/quartus_sh.exe",
    ),
}

_POSIX_TOOL_GLOBS: Mapping[str, tuple[str, ...]] = {
    "vivado": (
        "/opt/Xilinx/*/Vivado/bin/vivado",
        "/opt/Xilinx/Vivado/*/bin/vivado",
        "/tools/Xilinx/*/Vivado/bin/vivado",
        "/tools/Xilinx/Vivado/*/bin/vivado",
    ),
}

_VIVADO_VERSION_RE = re.compile(r"\bVivado\s+v(?P<version>\d{4}\.\d+(?:\.\d+)?)\b", re.IGNORECASE)


def get_tool(tool_id: str) -> EdaToolSpec:
    try:
        return _TOOL_BY_ID[tool_id]
    except KeyError as exc:
        raise KeyError(f"unknown EDA tool '{tool_id}'") from exc


def _is_linklike(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction is not None and is_junction():
        return True
    if os.name == "nt":
        try:
            attributes = int(getattr(os.lstat(path), "st_file_attributes", 0))
        except OSError:
            return False
        return bool(attributes & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT
    return False


def _fixed_glob_root(pattern: str) -> Path:
    parts = Path(pattern).parts
    fixed: list[str] = []
    for part in parts:
        if any(character in part for character in "*?["):
            break
        fixed.append(part)
    if not fixed:
        raise ValueError(f"vendor path pattern has no fixed root: {pattern}")
    return Path(*fixed).resolve(strict=False)


def _has_linklike_component(path: Path, *, stop: Path) -> bool:
    candidate = path.absolute()
    boundary = stop.absolute()
    while True:
        if _is_linklike(candidate):
            return True
        if os.path.normcase(str(candidate)) == os.path.normcase(str(boundary)):
            return False
        parent = candidate.parent
        if parent == candidate:
            return True
        candidate = parent


def _path_within(root: Path, candidate: Path) -> bool:
    try:
        common = os.path.commonpath((str(root), str(candidate)))
    except ValueError:
        return False
    return os.path.normcase(common) == os.path.normcase(str(root))


def trusted_vendor_tool_paths(tool_id: str) -> tuple[str, ...]:
    """Return launchers under package-known vendor installation layouts.

    This inventory deliberately ignores PATH and ``DAEDALUS_*_COMMAND``.
    Those remain useful for effect-free status reporting, but are not an
    authority for the live Gate-1 Vivado boundary.
    """

    get_tool(tool_id)  # validate the id even when no layout is registered
    patterns = (
        _WINDOWS_TOOL_GLOBS.get(tool_id, ())
        if os.name == "nt"
        else _POSIX_TOOL_GLOBS.get(tool_id, ())
    )
    paths: set[str] = set()
    for pattern in patterns:
        fixed_root = _fixed_glob_root(pattern)
        for raw in glob.glob(pattern):
            candidate = Path(raw).expanduser()
            if (
                not candidate.is_file()
                or _has_linklike_component(candidate, stop=fixed_root)
            ):
                continue
            resolved_root = fixed_root.resolve(strict=False)
            resolved_candidate = candidate.resolve(strict=True)
            if not _path_within(resolved_root, resolved_candidate):
                continue
            paths.add(str(resolved_candidate))
    return tuple(sorted(paths, key=str.casefold))


def find_trusted_vendor_tool_path(tool_id: str) -> str:
    """Select the newest lexical package-known vendor install, if present."""

    paths = trusted_vendor_tool_paths(tool_id)
    return paths[-1] if paths else ""


def is_trusted_vendor_tool_path(tool_id: str, path: str | Path) -> bool:
    """Whether ``path`` is one of the current standard-install identities."""

    candidate = os.path.normcase(str(Path(path).expanduser().resolve(strict=False)))
    return any(
        os.path.normcase(value) == candidate
        for value in trusted_vendor_tool_paths(tool_id)
    )


def trusted_launcher_sha256(path: str | Path) -> str:
    """Hash one stable regular launcher snapshot, refusing read-time drift."""

    candidate = Path(path).expanduser()
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError(f"launcher is not a regular non-symlink file: {candidate}")
    digest = hashlib.sha256()
    with candidate.open("rb") as handle:
        before = os.fstat(handle.fileno())
        total = 0
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
        after = os.fstat(handle.fileno())
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if identity_before != identity_after or total != after.st_size:
        raise ValueError("launcher changed while its SHA-256 was computed")
    return digest.hexdigest()


def find_tool_path(tool_id: str) -> str:
    """Resolve one registered executable without starting a process.

    An explicit ``DAEDALUS_<TOOL>_COMMAND`` value wins. On Windows, a small
    vendor-install inventory covers the standard Vivado/Quartus layouts used
    by machines where the vendor launcher is deliberately absent from PATH.
    """

    spec = get_tool(tool_id)
    override = os.environ.get(f"DAEDALUS_{spec.id.upper()}_COMMAND", "").strip()
    if override:
        candidate = Path(override).expanduser().resolve(strict=False)
        return str(candidate) if candidate.is_file() else ""
    path = shutil.which(spec.command)
    if path:
        return str(Path(path).resolve())
    return find_trusted_vendor_tool_path(spec.id)


def interpret_version_probe(
    tool_id: str,
    *,
    returncode: int | None,
    stdout: str = "",
    stderr: str = "",
) -> dict[str, object]:
    """Interpret already-admitted probe output; this function has no effects.

    AMD's Windows ``vivado.bat -version`` launcher is known to emit a valid
    version banner while returning 1. A parseable vendor banner proves the
    tool identity, but the non-zero launcher result remains visible as a
    warning rather than being rewritten to success.
    """

    spec = get_tool(tool_id)
    output = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part).strip()
    version = ""
    if spec.id == "vivado":
        match = _VIVADO_VERSION_RE.search(output)
        if match:
            version = match.group("version")
    elif returncode == 0 and output:
        version = output.splitlines()[0].strip()

    if returncode == 0:
        status = "ok"
        warning = ""
        error = ""
    elif version:
        status = "warning"
        warning = f"version banner parsed although launcher exited {returncode}"
        error = ""
    else:
        status = "failed"
        warning = ""
        error = output or ("probe did not start" if returncode is None else f"exit {returncode}")
    return {
        "probe_status": status,
        "version": version,
        "version_probe_returncode": returncode,
        "probe_warning": warning,
        "last_error": error,
        "probe_output": output,
    }


def tool_status(tool_id: str) -> dict[str, object]:
    """Return effect-free discovery status.

    Version execution is intentionally separate: callers must feed a probe
    through the admitted EDA executor and then use :func:`interpret_version_probe`.
    Merely asking for status can therefore never cross a process boundary.
    """

    spec = get_tool(tool_id)
    path = find_tool_path(tool_id)
    base = spec.to_dict()
    if not path:
        return {**base, "available": False, "command_path": "", "version": "",
                "probe_status": "not_run", "version_probe_returncode": None,
                "probe_warning": "", "last_error": f"{spec.command} not found"}
    return {
        **base,
        "available": True,
        "command_path": path,
        "version": "",
        "probe_status": "not_run",
        "version_probe_returncode": None,
        "probe_warning": "",
        "last_error": "",
    }


def all_tool_status() -> list[dict[str, object]]:
    return [tool_status(tool.id) for tool in TOOLS]


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
