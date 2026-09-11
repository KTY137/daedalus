"""Exact, digest-bound inputs for one admitted Vivado process.

The generic Effect Lease bounds capabilities.  This chip-specific contract
binds those capabilities to the concrete argv, workspace, evidence store,
declared outputs, sanitized environment and authoritative input identities
that the executor is about to consume.  It is data only and owns no authority.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from daedalus.spine.envelope import canonical_sha


EDA_EXECUTION_PLAN_SCHEMA = "daedalus.chip-eda-execution-plan/5"
PUBLICATION_ADAPTER_SCHEMA = "daedalus.chip-publication-adapter/1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PHASES = frozenset({"inspect", "synth", "impl"})
_ENV_ALLOW = (
    "LANG",
    "NUMBER_OF_PROCESSORS",
    "OS",
    "PROCESSOR_ARCHITECTURE",
    "PROCESSOR_IDENTIFIER",
    "TZ",
)


def _digest(value: str, label: str) -> str:
    text = str(value)
    if not _SHA256.fullmatch(text):
        raise ValueError(f"{label} must be lowercase SHA-256")
    return text


def _canonical_directory(value: str | Path, label: str) -> str:
    path = Path(value).expanduser().resolve(strict=False)
    if not path.is_absolute():  # defensive; resolve should always be absolute
        raise ValueError(f"{label} must be absolute")
    return str(path)


def _absolute_path_text(value: str | Path, label: str) -> str:
    """Validate already-canonical retained path text without touching the FS."""

    text = str(value)
    if not text or "\x00" in text:
        raise ValueError(f"{label} must be a non-empty non-NUL path")
    path = Path(text)
    if not path.is_absolute() or os.path.normpath(text) != text:
        raise ValueError(f"{label} must be an absolute normalized path")
    return text


def _stable_regular_file_sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"not a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        total = 0
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
        after = os.fstat(handle.fileno())
    before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_identity != after_identity or total != after.st_size:
        raise ValueError("file changed while its SHA-256 was computed")
    return digest.hexdigest()


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


def _has_linklike_component(path: Path) -> bool:
    candidate = path.absolute()
    while True:
        if _is_linklike(candidate):
            return True
        parent = candidate.parent
        if parent == candidate:
            return False
        candidate = parent


def publication_adapter_sha256() -> str:
    """Bind a stable on-disk Daedalus Python adapter inventory.

    A terminal Vivado observation can be finalized after a restart.  Hashing
    the complete package Python inventory into the execution plan makes that
    projection fail closed when parser, contract, limitation, or kernel files
    change between STARTED and publication.  This is a stable disk-inventory
    identity, not proof that concurrently replaced bytes equal already-loaded
    code, that the checkout is clean, or that its bytes belong to a commit.
    """

    package_root = Path(__file__).resolve(strict=True).parents[1]

    def inventory() -> tuple[str, ...]:
        return tuple(
            sorted(
                path.relative_to(package_root).as_posix()
                for path in package_root.rglob("*.py")
                if "__pycache__" not in path.parts
            )
        )

    before = inventory()
    if not before:
        raise ValueError("Daedalus publication adapter inventory is empty")
    files: list[dict[str, str]] = []
    for relative in before:
        path = package_root / Path(relative)
        if _has_linklike_component(path):
            raise ValueError(
                "Daedalus publication adapter inventory contains a linked component"
            )
        files.append(
            {
                "path": relative,
                "sha256": _stable_regular_file_sha256(path),
            }
        )
    if inventory() != before:
        raise ValueError("Daedalus publication adapter inventory changed while hashing")
    return canonical_sha(
        {
            "schema": PUBLICATION_ADAPTER_SCHEMA,
            "python_implementation": sys.implementation.name,
            "python_cache_tag": str(sys.implementation.cache_tag or ""),
            "python_version": list(sys.version_info[:3]),
            "os_name": os.name,
            "files": files,
        }
    )


def trusted_windows_command_interpreter() -> tuple[str, str]:
    """Return the OS-reported System32 cmd.exe path and stable byte identity.

    Ambient ``SYSTEMROOT``, ``WINDIR`` and ``COMSPEC`` are deliberately not
    consulted: Windows may route a ``.bat`` launcher through cmd.exe even when
    Python is asked not to use a shell.
    """

    if os.name != "nt":
        return "", ""
    import ctypes

    buffer = ctypes.create_unicode_buffer(32768)
    length = int(ctypes.windll.kernel32.GetSystemDirectoryW(buffer, len(buffer)))
    if length <= 0 or length >= len(buffer):
        raise ValueError("Windows did not return a bounded system directory")
    raw_system_directory = Path(buffer.value)
    if (
        not raw_system_directory.is_absolute()
        or _has_linklike_component(raw_system_directory)
    ):
        raise ValueError("Windows system directory contains a linked component")
    raw_command_interpreter = raw_system_directory / "cmd.exe"
    if _has_linklike_component(raw_command_interpreter):
        raise ValueError("Windows command interpreter contains a linked component")
    system_directory = raw_system_directory.resolve(strict=True)
    if not system_directory.is_dir() or _is_linklike(system_directory):
        raise ValueError("Windows system directory is not a regular directory")
    command_interpreter = raw_command_interpreter.resolve(strict=True)
    if command_interpreter.parent != system_directory:
        raise ValueError("Windows command interpreter escaped the system directory")
    digest = _stable_regular_file_sha256(command_interpreter)
    return str(command_interpreter), digest


def sanitized_eda_environment(
    cwd: str | Path,
    *,
    host_environment: Mapping[str, str] | None = None,
    phase: str = "inspect",
    workspace_manifest_sha256: str = "0" * 64,
    output_dir: str | Path | None = None,
) -> dict[str, str]:
    """Build the fixed no-secret environment projection used for Vivado.

    License, proxy, cloud, token and credential variables are absent because
    only the small platform allow-list is copied. TEMP/TMP are pinned to the
    leased workspace. This is environment confinement, not network isolation.
    """

    root = _canonical_directory(cwd, "cwd")
    phase_text = str(phase)
    if phase_text not in _PHASES:
        raise ValueError(f"unsupported EDA phase: {phase_text}")
    workspace_digest = _digest(
        workspace_manifest_sha256, "workspace_manifest_sha256"
    )
    source = os.environ if host_environment is None else host_environment
    by_casefold = {str(key).casefold(): str(value) for key, value in source.items()}
    environment: dict[str, str] = {}
    for name in _ENV_ALLOW:
        value = by_casefold.get(name.casefold())
        if value is not None and "\x00" not in value:
            environment[name] = value
    # Do not inherit a tool-search path or user profile.  The launcher is an
    # absolute, byte-bound vendor-install path; a host PATH would reopen
    # executable selection inside the child.  Redirecting all common profile
    # roots into the already leased workspace prevents ambient user
    # Vivado_init.tcl discovery.
    if os.name == "nt":
        command_interpreter, _command_interpreter_sha256 = (
            trusted_windows_command_interpreter()
        )
        system32 = Path(command_interpreter).parent
        system_root = system32.parent
        environment["PATH"] = str(system32)
        environment["COMSPEC"] = command_interpreter
        environment["SYSTEMROOT"] = str(system_root)
        environment["WINDIR"] = str(system_root)
        environment["SYSTEMDRIVE"] = system_root.drive
        environment["PATHEXT"] = ".COM;.EXE;.BAT;.CMD"
    else:
        environment["PATH"] = "/usr/bin:/bin"
    output_identity = canonical_sha(
        {
            "output_dir": (
                _canonical_directory(output_dir, "output_dir")
                if output_dir is not None
                else root
            )
        }
    )
    profile_root = str(
        Path(root)
        / ".daedalus-chip-profile"
        / f"{phase_text}-{workspace_digest[:16]}-{output_identity[:16]}"
    )
    environment["APPDATA"] = profile_root
    environment["HOME"] = profile_root
    environment["USERPROFILE"] = profile_root
    environment["TEMP"] = root
    environment["TMP"] = root
    return dict(sorted(environment.items()))


def environment_sha256(environment: Mapping[str, str]) -> str:
    return canonical_sha(
        {str(key): str(value) for key, value in sorted(environment.items())}
    )


@dataclass(frozen=True)
class EdaExecutionPlan:
    phase: str
    argv: tuple[str, ...]
    source_root: str
    source_project: str
    cwd: str
    artifact_paths: tuple[str, ...]
    artifact_store_root: str
    timeout_s: float
    environment_keys: tuple[str, ...]
    environment_sha256: str
    source_manifest_sha256: str
    workspace_manifest_sha256: str
    source_identity_sha256: str
    trusted_tcl_sha256: str
    launcher_sha256: str
    publication_adapter_sha256: str
    command_interpreter_path: str = ""
    command_interpreter_sha256: str = ""
    schema: str = EDA_EXECUTION_PLAN_SCHEMA

    def __post_init__(self) -> None:
        if self.schema != EDA_EXECUTION_PLAN_SCHEMA:
            raise ValueError("unsupported EDA execution plan schema")
        if self.phase not in _PHASES:
            raise ValueError(f"unsupported EDA phase: {self.phase}")
        argv = tuple(str(value) for value in self.argv)
        if not argv or not argv[0].strip() or any("\x00" in value for value in argv):
            raise ValueError("argv must contain a non-NUL executable")
        object.__setattr__(self, "argv", argv)
        object.__setattr__(
            self,
            "source_root",
            _absolute_path_text(self.source_root, "source_root"),
        )
        source_project = _absolute_path_text(self.source_project, "source_project")
        try:
            common = os.path.commonpath((self.source_root, source_project))
        except ValueError as exc:
            raise ValueError("source_project must be inside source_root") from exc
        if os.path.normcase(common) != os.path.normcase(self.source_root):
            raise ValueError("source_project must be inside source_root")
        object.__setattr__(self, "source_project", source_project)
        object.__setattr__(self, "cwd", _absolute_path_text(self.cwd, "cwd"))
        object.__setattr__(
            self,
            "artifact_store_root",
            _absolute_path_text(self.artifact_store_root, "artifact_store_root"),
        )
        paths: list[str] = []
        for raw in self.artifact_paths:
            path = Path(str(raw))
            if path.is_absolute() or path.anchor or path.root or ".." in path.parts:
                raise ValueError("artifact paths must be relative to cwd")
            value = path.as_posix()
            if value in {"", "."}:
                raise ValueError("artifact paths must name files")
            paths.append(value)
        if len(set(paths)) != len(paths):
            raise ValueError("artifact paths must not contain duplicates")
        object.__setattr__(self, "artifact_paths", tuple(sorted(paths)))
        try:
            timeout = float(self.timeout_s)
        except (TypeError, ValueError) as exc:
            raise ValueError("timeout_s must be finite and positive") from exc
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout_s must be finite and positive")
        object.__setattr__(self, "timeout_s", timeout)
        keys = tuple(sorted(str(key) for key in self.environment_keys))
        if len(set(keys)) != len(keys) or any(not key or "=" in key for key in keys):
            raise ValueError("environment_keys must be unique valid names")
        object.__setattr__(self, "environment_keys", keys)
        for name in (
            "environment_sha256",
            "source_manifest_sha256",
            "workspace_manifest_sha256",
            "source_identity_sha256",
            "trusted_tcl_sha256",
            "launcher_sha256",
            "publication_adapter_sha256",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        interpreter_path = str(self.command_interpreter_path)
        interpreter_sha256 = str(self.command_interpreter_sha256)
        if bool(interpreter_path) != bool(interpreter_sha256):
            raise ValueError(
                "command interpreter path and SHA-256 must be supplied together"
            )
        if interpreter_path:
            object.__setattr__(
                self,
                "command_interpreter_path",
                _absolute_path_text(
                    interpreter_path,
                    "command_interpreter_path",
                ),
            )
            object.__setattr__(
                self,
                "command_interpreter_sha256",
                _digest(interpreter_sha256, "command_interpreter_sha256"),
            )

    @classmethod
    def build(
        cls,
        *,
        phase: str,
        argv: Sequence[str],
        source_root: str | Path,
        source_project: str | Path,
        cwd: str | Path,
        artifact_paths: Sequence[str | Path],
        artifact_store_root: str | Path,
        timeout_s: float,
        environment: Mapping[str, str],
        source_manifest_sha256: str,
        workspace_manifest_sha256: str,
        source_identity_sha256: str,
        trusted_tcl_sha256: str,
        launcher_sha256: str,
        publication_adapter_sha256: str,
        command_interpreter_path: str = "",
        command_interpreter_sha256: str = "",
    ) -> "EdaExecutionPlan":
        canonical_source_root = _canonical_directory(source_root, "source_root")
        canonical_source_project = str(
            Path(source_project).expanduser().resolve(strict=False)
        )
        canonical_cwd = _canonical_directory(cwd, "cwd")
        canonical_artifact_store = _canonical_directory(
            artifact_store_root,
            "artifact_store_root",
        )
        canonical_interpreter_path = (
            str(Path(command_interpreter_path).expanduser().resolve(strict=False))
            if command_interpreter_path
            else ""
        )
        return cls(
            phase=phase,
            argv=tuple(str(value) for value in argv),
            source_root=canonical_source_root,
            source_project=canonical_source_project,
            cwd=canonical_cwd,
            artifact_paths=tuple(str(value) for value in artifact_paths),
            artifact_store_root=canonical_artifact_store,
            timeout_s=timeout_s,
            environment_keys=tuple(str(key) for key in environment),
            environment_sha256=environment_sha256(environment),
            source_manifest_sha256=source_manifest_sha256,
            workspace_manifest_sha256=workspace_manifest_sha256,
            source_identity_sha256=source_identity_sha256,
            trusted_tcl_sha256=trusted_tcl_sha256,
            launcher_sha256=launcher_sha256,
            publication_adapter_sha256=publication_adapter_sha256,
            command_interpreter_path=canonical_interpreter_path,
            command_interpreter_sha256=command_interpreter_sha256,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "phase": self.phase,
            "argv": list(self.argv),
            "source_root": self.source_root,
            "source_project": self.source_project,
            "cwd": self.cwd,
            "artifact_paths": list(self.artifact_paths),
            "artifact_store_root": self.artifact_store_root,
            "timeout_s": self.timeout_s,
            "environment_keys": list(self.environment_keys),
            "environment_sha256": self.environment_sha256,
            "source_manifest_sha256": self.source_manifest_sha256,
            "workspace_manifest_sha256": self.workspace_manifest_sha256,
            "source_identity_sha256": self.source_identity_sha256,
            "trusted_tcl_sha256": self.trusted_tcl_sha256,
            "launcher_sha256": self.launcher_sha256,
            "publication_adapter_sha256": self.publication_adapter_sha256,
            "command_interpreter_path": self.command_interpreter_path,
            "command_interpreter_sha256": self.command_interpreter_sha256,
        }

    @classmethod
    def from_dict(cls, value: object) -> "EdaExecutionPlan":
        """Strictly rebuild a retained plan without consulting live inputs."""

        if not isinstance(value, Mapping):
            raise TypeError("retained EDA execution plan must be an object")
        expected = {
            "schema",
            "phase",
            "argv",
            "source_root",
            "source_project",
            "cwd",
            "artifact_paths",
            "artifact_store_root",
            "timeout_s",
            "environment_keys",
            "environment_sha256",
            "source_manifest_sha256",
            "workspace_manifest_sha256",
            "source_identity_sha256",
            "trusted_tcl_sha256",
            "launcher_sha256",
            "publication_adapter_sha256",
            "command_interpreter_path",
            "command_interpreter_sha256",
        }
        if set(value) != expected:
            raise ValueError("retained EDA execution plan has unexpected fields")
        argv = value.get("argv")
        artifact_paths = value.get("artifact_paths")
        environment_keys = value.get("environment_keys")
        if not isinstance(argv, list) or not all(
            isinstance(item, str) for item in argv
        ):
            raise TypeError("retained EDA execution plan argv must be strings")
        if not isinstance(artifact_paths, list) or not all(
            isinstance(item, str) for item in artifact_paths
        ):
            raise TypeError(
                "retained EDA execution plan artifact paths must be strings"
            )
        if not isinstance(environment_keys, list) or not all(
            isinstance(item, str) for item in environment_keys
        ):
            raise TypeError(
                "retained EDA execution plan environment keys must be strings"
            )
        return cls(
            schema=str(value["schema"]),
            phase=str(value["phase"]),
            argv=tuple(argv),
            source_root=str(value["source_root"]),
            source_project=str(value["source_project"]),
            cwd=str(value["cwd"]),
            artifact_paths=tuple(artifact_paths),
            artifact_store_root=str(value["artifact_store_root"]),
            timeout_s=value["timeout_s"],
            environment_keys=tuple(environment_keys),
            environment_sha256=str(value["environment_sha256"]),
            source_manifest_sha256=str(value["source_manifest_sha256"]),
            workspace_manifest_sha256=str(value["workspace_manifest_sha256"]),
            source_identity_sha256=str(value["source_identity_sha256"]),
            trusted_tcl_sha256=str(value["trusted_tcl_sha256"]),
            launcher_sha256=str(value["launcher_sha256"]),
            publication_adapter_sha256=str(value["publication_adapter_sha256"]),
            command_interpreter_path=str(value["command_interpreter_path"]),
            command_interpreter_sha256=str(
                value["command_interpreter_sha256"]
            ),
        )

    @property
    def digest(self) -> str:
        return canonical_sha(self.to_dict())


__all__ = [
    "EDA_EXECUTION_PLAN_SCHEMA",
    "PUBLICATION_ADAPTER_SCHEMA",
    "EdaExecutionPlan",
    "environment_sha256",
    "publication_adapter_sha256",
    "sanitized_eda_environment",
    "trusted_windows_command_interpreter",
]
