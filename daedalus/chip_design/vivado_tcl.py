"""Package-owned Vivado Tcl identity and argv construction.

No project-provided script is accepted by this module.  The one executable Tcl
surface is a static package resource; project/run values are appended after
``-tclargs`` as distinct argv items and never interpolated into Tcl source.
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .manifest import canonical_path, canonical_path_identity


_TEMPLATE_NAME = "vivado_project_flow.tcl"
_PHASES = frozenset({"inspect", "synth", "impl"})
_RUN_NAME = re.compile(r"^[A-Za-z0-9_.:-]{1,200}$")
_PART_NAME = re.compile(r"^[A-Za-z0-9_.:+-]{1,200}$")
_COMMAND_NAMES = frozenset({"vivado", "vivado.exe", "vivado.bat"})
_MAX_TEMPLATE_BYTES = 256 * 1024
_OUTPUT_NAMES = {
    "inspect": ("inspect_summary.txt",),
    "synth": (
        "synth_summary.txt",
        "utilization.rpt",
        "timing_summary.rpt",
        "drc.rpt",
        "methodology.rpt",
        "design.dcp",
    ),
    "impl": (
        "impl_summary.txt",
        "utilization.rpt",
        "timing_summary.rpt",
        "drc.rpt",
        "methodology.rpt",
        "route_status.rpt",
        "synth_design.dcp",
        "design.dcp",
        "design.bit",
    ),
}


class VivadoTclContractError(ValueError):
    """A value cannot enter the trusted Vivado Tcl invocation contract."""


@dataclass(frozen=True)
class TrustedVivadoTcl:
    path: str
    sha256: str
    byte_length: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def trusted_vivado_tcl() -> TrustedVivadoTcl:
    """Return the installed static template path and its content identity."""

    package_dir = canonical_path(Path(__file__).parent)
    path = canonical_path(package_dir / "tcl" / _TEMPLATE_NAME)
    try:
        common = os.path.commonpath(
            (canonical_path_identity(package_dir), canonical_path_identity(path))
        )
    except ValueError as exc:
        raise VivadoTclContractError("trusted Tcl path is outside the package") from exc
    if os.path.normcase(common) != os.path.normcase(canonical_path_identity(package_dir)):
        raise VivadoTclContractError("trusted Tcl path is outside the package")
    if path.is_symlink() or not path.is_file():
        raise VivadoTclContractError(f"trusted Vivado Tcl is not a regular package file: {path}")
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            if before.st_size > _MAX_TEMPLATE_BYTES:
                raise VivadoTclContractError(
                    "trusted Vivado Tcl exceeds the template byte bound"
                )
            payload = handle.read(_MAX_TEMPLATE_BYTES + 1)
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise VivadoTclContractError(f"cannot read trusted Vivado Tcl: {exc}") from exc
    before_identity = (
        before.st_dev,
        before.st_ino,
        before.st_size,
        before.st_mtime_ns,
    )
    after_identity = (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    )
    if before_identity != after_identity or len(payload) != after.st_size:
        raise VivadoTclContractError("trusted Vivado Tcl changed while it was read")
    if not payload or len(payload) > _MAX_TEMPLATE_BYTES:
        raise VivadoTclContractError("trusted Vivado Tcl has an invalid byte length")
    return TrustedVivadoTcl(
        path=str(path),
        sha256=hashlib.sha256(payload).hexdigest(),
        byte_length=len(payload),
    )


def _inside(root: Path, candidate: Path) -> bool:
    try:
        common = os.path.commonpath(
            (canonical_path_identity(root), canonical_path_identity(candidate))
        )
    except ValueError:
        return False
    return os.path.normcase(common) == os.path.normcase(canonical_path_identity(root))


def _text(value: object, name: str, *, max_length: int = 1000) -> str:
    if not isinstance(value, str):
        raise VivadoTclContractError(f"{name} must be a string")
    if not value or not value.strip() or "\x00" in value:
        raise VivadoTclContractError(f"{name} must be non-empty and contain no NUL")
    if "\r" in value or "\n" in value or len(value) > max_length:
        raise VivadoTclContractError(f"{name} has an invalid length or newline")
    return value


def _run_name(value: object, name: str) -> str:
    text = _text(value, name, max_length=200)
    if not _RUN_NAME.fullmatch(text):
        raise VivadoTclContractError(f"{name} is not an exact Vivado run name")
    return text


def _command(value: str | os.PathLike[str], project_root: Path) -> str:
    text = _text(os.fspath(value), "command", max_length=4096)
    name = Path(text).name.lower()
    if name not in _COMMAND_NAMES:
        raise VivadoTclContractError("command must resolve to the AMD Vivado launcher")
    has_path = Path(text).is_absolute() or any(sep in text for sep in ("/", "\\"))
    if has_path:
        path = canonical_path(text)
        if _inside(project_root, path):
            raise VivadoTclContractError("Vivado launcher must not come from the project")
        if not path.is_file():
            raise VivadoTclContractError(f"Vivado launcher does not exist: {path}")
        return str(path)
    return text


def build_vivado_flow_argv(
    phase: str,
    project_file: str | os.PathLike[str],
    *,
    project_root: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    expected_part: str,
    expected_top: str,
    expected_board_part: str = "",
    synth_run: str = "synth_1",
    impl_run: str = "impl_1",
    jobs: int = 1,
    command: str | os.PathLike[str] = "vivado",
) -> list[str]:
    """Build the only supported project-flow argv; this function writes nothing."""

    phase_text = _text(phase, "phase", max_length=20).lower()
    if phase_text not in _PHASES:
        raise VivadoTclContractError(
            f"phase must be one of {', '.join(sorted(_PHASES))}"
        )
    if isinstance(jobs, bool) or not isinstance(jobs, int) or not 1 <= jobs <= 64:
        raise VivadoTclContractError("jobs must be an integer between 1 and 64")
    root = canonical_path(project_root)
    if not root.is_dir():
        raise VivadoTclContractError(f"project root is not a directory: {root}")
    project_input = Path(project_file)
    project = canonical_path(
        project_input if project_input.is_absolute() else root / project_input
    )
    if not _inside(root, project):
        raise VivadoTclContractError("project file escapes the declared project root")
    if project.suffix.lower() != ".xpr" or not project.is_file():
        raise VivadoTclContractError(f"project file is not a regular .xpr: {project}")
    output_input = Path(output_dir)
    output = canonical_path(output_input if output_input.is_absolute() else root / output_input)
    output_root = canonical_path(root / ".daedalus-chip")
    if (
        not _inside(output_root, output)
        or canonical_path_identity(output) == canonical_path_identity(output_root)
    ):
        raise VivadoTclContractError(
            "output directory must be a proper descendant of the dedicated "
            ".daedalus-chip workspace root"
        )
    if output.exists() and not output.is_dir():
        raise VivadoTclContractError(f"output path exists but is not a directory: {output}")

    part = _text(expected_part, "expected_part", max_length=200)
    if not _PART_NAME.fullmatch(part):
        raise VivadoTclContractError("expected_part is not a valid exact part identifier")
    top = _text(expected_top, "expected_top", max_length=500)
    board_part = str(expected_board_part)
    if (
        "\x00" in board_part
        or "\r" in board_part
        or "\n" in board_part
        or len(board_part) > 500
        or (board_part and not _PART_NAME.fullmatch(board_part))
    ):
        raise VivadoTclContractError("expected_board_part is not a valid identifier")
    synth = _run_name(synth_run, "synth_run")
    impl = _run_name(impl_run, "impl_run")
    launcher = _command(command, root)
    template = trusted_vivado_tcl()
    return [
        launcher,
        "-mode",
        "batch",
        "-nojournal",
        "-nolog",
        "-notrace",
        "-source",
        template.path,
        "-tclargs",
        phase_text,
        str(root),
        str(project),
        str(output),
        part,
        board_part,
        top,
        synth,
        impl,
        str(jobs),
    ]


def expected_vivado_output_paths(
    project_root: str | os.PathLike[str],
    output_dir: str | os.PathLike[str],
    phase: str,
) -> tuple[str, ...]:
    """Return the one exact declared-output set for a trusted flow phase."""

    phase_text = _text(phase, "phase", max_length=20).lower()
    if phase_text not in _PHASES:
        raise VivadoTclContractError(
            f"phase must be one of {', '.join(sorted(_PHASES))}"
        )
    root = canonical_path(project_root)
    output = canonical_path(output_dir)
    output_root = canonical_path(root / ".daedalus-chip")
    if (
        not _inside(output_root, output)
        or canonical_path_identity(output) == canonical_path_identity(output_root)
    ):
        raise VivadoTclContractError(
            "output directory must be a proper descendant of the dedicated "
            ".daedalus-chip workspace root"
        )
    relative_dir = Path(os.path.relpath(output, root))
    return tuple(
        (relative_dir / name).as_posix() for name in _OUTPUT_NAMES[phase_text]
    )


build_vivado_project_flow_argv = build_vivado_flow_argv
get_trusted_vivado_tcl = trusted_vivado_tcl


__all__ = [
    "TrustedVivadoTcl",
    "VivadoTclContractError",
    "build_vivado_flow_argv",
    "build_vivado_project_flow_argv",
    "expected_vivado_output_paths",
    "get_trusted_vivado_tcl",
    "trusted_vivado_tcl",
]
