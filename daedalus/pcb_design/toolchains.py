"""Registry and effect-free discovery for PCB toolchains.

The honesty contract is inherited from :mod:`daedalus.chip_design.toolchains`
and tightened: nothing in this module starts a process, so ``status`` can never
cross a process boundary merely by being asked. A version therefore has three
possible provenances, and the report always says which one it is:

``version_source = ""``
    No version is known. This is the normal answer.
``version_source = "install_path"``
    A KiCad series (``8.0``, ``9.0``) was read out of the installation
    directory name. It identifies the *install*, not the running binary, and it
    is a weaker claim than a probe. It is never reported as ``version``.
``version_source = "probe"``
    Only :func:`interpret_version_probe` produces this, and only from output a
    caller obtained elsewhere under an admitted effect path. This package has
    no such path, which is the point.

Python modules (``pcbnew``, ``kipy``) are located with ``find_spec`` and are
deliberately **never imported**: importing ``pcbnew`` loads a large native
extension and, on some builds, initialises KiCad state. Absence here is also
not proof KiCad is absent -- KiCad ships ``pcbnew`` inside its own bundled
interpreter, invisible to this one. The report says so instead of concluding.
"""
from __future__ import annotations

import glob
import importlib.util
import os
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

__all__ = [
    "PcbToolSpec",
    "TOOLS",
    "all_tool_status",
    "find_tool_path",
    "get_tool",
    "interpret_version_probe",
    "tool_status",
]


@dataclass(frozen=True)
class PcbToolSpec:
    id: str
    label: str
    kind: str  # "executable" | "python_module"
    command: str = ""
    module: str = ""
    roles: tuple[str, ...] = ()
    version_args: tuple[str, ...] = ()
    required_for: tuple[str, ...] = ()
    notes: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


TOOLS: tuple[PcbToolSpec, ...] = (
    PcbToolSpec(
        id="kicad-cli",
        label="KiCad command line",
        kind="executable",
        command="kicad-cli",
        roles=("erc", "drc", "netlist_export", "bom_export", "gerber_export", "drill_export"),
        version_args=("--version",),
        required_for=("erc", "drc", "netlist", "bom", "gerbers", "drill"),
        notes=(
            "The only admissible source of ERC/DRC evidence. Its documented exit "
            "codes are distinct (5 = violations found with --exit-code-violations); "
            "they are retained, never collapsed to pass/fail."
        ),
    ),
    PcbToolSpec(
        id="kicad",
        label="KiCad GUI application",
        kind="executable",
        command="kicad",
        roles=("gui",),
        version_args=("--version",),
        notes=(
            "Discovery only. A GUI is not an evaluator and Daedalus never "
            "automates one; it is listed because its presence explains where "
            "kicad-cli lives."
        ),
    ),
    PcbToolSpec(
        id="ngspice",
        label="ngspice circuit simulator",
        kind="executable",
        command="ngspice",
        roles=("simulation",),
        version_args=("-v",),
        required_for=("spice",),
        notes=(
            "KiCad bundles ngspice as a shared library for its own simulator; a "
            "bundled DLL is not a callable executable and is not reported as one."
        ),
    ),
    PcbToolSpec(
        id="gerbv",
        label="gerbv Gerber viewer",
        kind="executable",
        command="gerbv",
        roles=("gerber_view", "gerber_render"),
        version_args=("--version",),
        required_for=("gerber_render",),
        notes="Independent renderer for exported fabrication output.",
    ),
    PcbToolSpec(
        id="pcbnew",
        label="KiCad Python API (SWIG, KiCad 8)",
        kind="python_module",
        module="pcbnew",
        roles=("board_scripting",),
        notes=(
            "Located but never imported. Only importable from KiCad's bundled "
            "interpreter, so absence in this interpreter is not evidence that "
            "KiCad is absent -- read the kicad-cli row for that."
        ),
    ),
    PcbToolSpec(
        id="kipy",
        label="KiCad IPC API client (KiCad 9)",
        kind="python_module",
        module="kipy",
        roles=("board_scripting",),
        notes=(
            "The KiCad 9 replacement for SWIG scripting. It talks to a running "
            "KiCad over IPC, which is an effect; discovery only."
        ),
    ),
)

_TOOL_BY_ID = {tool.id: tool for tool in TOOLS}

_WINDOWS_GLOBS: Mapping[str, tuple[str, ...]] = {
    "kicad-cli": (
        "C:/Program Files/KiCad/*/bin/kicad-cli.exe",
        "C:/Program Files (x86)/KiCad/*/bin/kicad-cli.exe",
    ),
    "kicad": (
        "C:/Program Files/KiCad/*/bin/kicad.exe",
        "C:/Program Files (x86)/KiCad/*/bin/kicad.exe",
    ),
    "ngspice": (
        "C:/Program Files/ngspice*/bin/ngspice.exe",
        "C:/Spice64/bin/ngspice.exe",
    ),
    "gerbv": (
        "C:/Program Files/gerbv*/bin/gerbv.exe",
        "C:/Program Files (x86)/gerbv*/bin/gerbv.exe",
    ),
}

_POSIX_GLOBS: Mapping[str, tuple[str, ...]] = {
    "kicad-cli": (
        "/usr/bin/kicad-cli",
        "/usr/local/bin/kicad-cli",
        "/opt/kicad/bin/kicad-cli",
        "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad-cli",
    ),
    "kicad": (
        "/usr/bin/kicad",
        "/usr/local/bin/kicad",
        "/Applications/KiCad/KiCad.app/Contents/MacOS/kicad",
    ),
    "ngspice": ("/usr/bin/ngspice", "/usr/local/bin/ngspice"),
    "gerbv": ("/usr/bin/gerbv", "/usr/local/bin/gerbv"),
}

# "C:/Program Files/KiCad/9.0/bin/kicad-cli.exe" -> "9.0"
_KICAD_SERIES_RE = re.compile(r"[\\/]KiCad[\\/](\d+\.\d+)[\\/]", re.IGNORECASE)

_KICAD_CLI_VERSION_RE = re.compile(r"\b(\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.~]+)?)\b")
_NGSPICE_VERSION_RE = re.compile(r"\bngspice[- ](\d+[0-9A-Za-z.]*)", re.IGNORECASE)
_GERBV_VERSION_RE = re.compile(r"\bgerbv\s+(?:version\s+)?(\d+\.\d+[0-9A-Za-z.]*)", re.IGNORECASE)

_VERSION_PATTERNS = {
    "kicad-cli": _KICAD_CLI_VERSION_RE,
    "kicad": _KICAD_CLI_VERSION_RE,
    "ngspice": _NGSPICE_VERSION_RE,
    "gerbv": _GERBV_VERSION_RE,
}


def get_tool(tool_id: str) -> PcbToolSpec:
    try:
        return _TOOL_BY_ID[tool_id]
    except KeyError as exc:
        raise KeyError(f"unknown PCB tool '{tool_id}'") from exc


def _env_override(spec: PcbToolSpec) -> str:
    key = f"DAEDALUS_PCB_{spec.id.upper().replace('-', '_')}_COMMAND"
    return os.environ.get(key, "").strip()


def _glob_candidates(tool_id: str) -> tuple[str, ...]:
    table = _WINDOWS_GLOBS if os.name == "nt" else _POSIX_GLOBS
    return table.get(tool_id, ())


def find_tool_path(tool_id: str) -> tuple[str, str]:
    """Resolve one executable without starting a process.

    Returns ``(path, how)`` where ``how`` is ``"env_override"``, ``"path"``,
    ``"install_glob"`` or ``""``. An override that does not resolve to a file
    yields ``("", "env_override_missing")`` instead of quietly falling through
    to PATH -- an operator who names a binary gets an answer about that binary.
    """

    spec = get_tool(tool_id)
    if spec.kind != "executable":
        return "", ""
    override = _env_override(spec)
    if override:
        candidate = Path(override).expanduser()
        try:
            resolved = candidate.resolve(strict=False)
        except OSError:
            return "", "env_override_missing"
        if resolved.is_file():
            return resolved.as_posix(), "env_override"
        return "", "env_override_missing"
    found = shutil.which(spec.command)
    if found:
        return Path(found).resolve(strict=False).as_posix(), "path"
    for pattern in _glob_candidates(tool_id):
        for match in sorted(glob.glob(pattern)):
            candidate = Path(match)
            if candidate.is_file():
                return candidate.resolve(strict=False).as_posix(), "install_glob"
    return "", ""


def _module_status(spec: PcbToolSpec) -> dict[str, object]:
    origin = ""
    available = False
    error = ""
    try:
        found = importlib.util.find_spec(spec.module)
    except (ImportError, ValueError) as exc:
        found = None
        error = f"{type(exc).__name__}: {exc}"
    if found is not None:
        available = True
        origin = str(found.origin or "")
    return {
        **spec.to_dict(),
        "available": available,
        "command_path": origin,
        "discovered_via": "importlib.find_spec" if available else "",
        "imported": False,
        "version": "",
        "version_source": "",
        "install_series": "",
        "probe_status": "not_imported",
        "version_probe_returncode": None,
        "probe_warning": "",
        "last_error": error or ("" if available else f"module {spec.module!r} not importable here"),
    }


def tool_status(tool_id: str) -> dict[str, object]:
    """Effect-free discovery status for one registered tool.

    No subprocess and no module import happens here, by construction. The
    version stays empty; a caller that wants one must obtain a probe through an
    admitted effect path and feed it to :func:`interpret_version_probe`.
    """

    spec = get_tool(tool_id)
    if spec.kind == "python_module":
        return _module_status(spec)

    path, how = find_tool_path(tool_id)
    series = ""
    if path:
        match = _KICAD_SERIES_RE.search(path + "/")
        if match:
            series = match.group(1)
    base = spec.to_dict()
    if not path:
        return {
            **base,
            "available": False,
            "command_path": "",
            "discovered_via": how,
            "imported": False,
            "version": "",
            "version_source": "",
            "install_series": "",
            "probe_status": "not_run",
            "version_probe_returncode": None,
            "probe_warning": "",
            "last_error": (
                f"{spec.command}: named by environment override but not a file"
                if how == "env_override_missing"
                else f"{spec.command} not found on PATH or in a known install location"
            ),
        }
    return {
        **base,
        "available": True,
        "command_path": path,
        "discovered_via": how,
        "imported": False,
        "version": "",
        "version_source": "install_path" if series else "",
        "install_series": series,
        "probe_status": "not_run",
        "version_probe_returncode": None,
        "probe_warning": "",
        "last_error": "",
    }


def all_tool_status() -> list[dict[str, object]]:
    return [tool_status(tool.id) for tool in TOOLS]


def interpret_version_probe(
    tool_id: str,
    *,
    returncode: int | None,
    stdout: str = "",
    stderr: str = "",
) -> dict[str, object]:
    """Interpret already-obtained probe output. This function has no effects.

    A parseable banner is retained even when the launcher exited non-zero, but
    the non-zero result stays visible as a warning instead of being rewritten
    into success -- the same rule the Vivado slice applies to ``vivado.bat``.
    """

    spec = get_tool(tool_id)
    output = "\n".join(part for part in (stdout.strip(), stderr.strip()) if part).strip()
    version = ""
    pattern = _VERSION_PATTERNS.get(spec.id)
    if pattern is not None:
        match = pattern.search(output)
        if match:
            version = match.group(1)
    if not version and returncode == 0 and output:
        version = output.splitlines()[0].strip()

    if returncode == 0:
        status, warning, error = "ok", "", ""
    elif version:
        status = "warning"
        warning = f"version banner parsed although the launcher exited {returncode}"
        error = ""
    else:
        status = "failed"
        warning = ""
        error = output or (
            "probe did not start" if returncode is None else f"exit {returncode}"
        )
    return {
        "tool_id": spec.id,
        "probe_status": status,
        "version": version,
        "version_source": "probe" if version else "",
        "version_probe_returncode": returncode,
        "probe_warning": warning,
        "last_error": error,
        "probe_output": output,
    }
