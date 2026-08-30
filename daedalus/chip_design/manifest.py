"""Deterministic, relocation-safe manifests for AMD Vivado projects.

The XPR file is treated as untrusted input data.  This module parses its XML
without importing or executing any project content, records direct file-set
references, and gives the authoritative ``.xpr``, ``.bd`` and ``.xci`` bytes
stable SHA-256 identities.  Paths that escape the declared project root are
reported but never opened by the manifest builder.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from xml.etree import ElementTree


MANIFEST_SCHEMA = "daedalus-chip-vivado-project-manifest/1"
_MAX_XPR_BYTES = 16 * 1024 * 1024
_MAX_BLOCK_DESIGN_BYTES = 64 * 1024 * 1024
_MAX_REFERENCES = 100_000
_MACRO = re.compile(r"^\$([A-Za-z][A-Za-z0-9_]*)(?:[\\/](.*))?$")
_RUN_VOLATILE_ELEMENTS = frozenset({"GeneratedRun"})
_RUN_VOLATILE_ATTRIBUTES = frozenset(
    {
        "AutoIncrementalDir",
        "AutoRQSDir",
        "CurrentStep",
        "Dir",
        "EndTime",
        "LaunchOptions",
        "LastModified",
        "Progress",
        "StartTime",
        "State",
        "Status",
        "Timestamp",
    }
)
_RUN_NON_SEMANTIC_ROOT_ATTRIBUTES = frozenset(
    {
        "Description",
        "IncludeInArchive",
        "ParallelReportGen",
    }
)
_FILE_VOLATILE_ATTRIBUTES = frozenset(
    {
        "ImportPath",
        "ImportTime",
        "LastModified",
        "Timestamp",
    }
)
_PROJECT_VOLATILE_OPTIONS = frozenset(
    {
        "DcpsUptoDate",
        "Id",
        # The package-owned live flow forces this to disabled before every
        # synthesis-capable phase and records that fact in its summary.
        "IPCachePermission",
        "SimCompileState",
    }
)
_CUSTOM_IP_REPOSITORY_PROPERTY_NAMES = frozenset(
    {
        # XPR XML uses the singular spelling while Vivado exposes the
        # fileset property as IP_REPO_PATHS.
        "iprepopath",
        "iprepopaths",
    }
)
_INCLUDE_DIRECTORY_PROPERTY_NAMES = frozenset(
    {
        "includedir",
        "includedirs",
        "verilogincludedir",
        "verilogincludedirs",
    }
)
_CUSTOM_BOARD_REPOSITORY_PROPERTY_NAMES = frozenset(
    {
        "boardpartrepopath",
        "boardpartrepopaths",
        "boardrepopath",
        "boardrepopaths",
    }
)
_ACTIVE_REFERENCE_TYPES = frozenset(
    {
        "file",
        "ip_configuration",
        "block_design_dependency",
        "ip_dependency",
        "run_generated_state",
    }
)


class VivadoManifestError(ValueError):
    """The project cannot be represented by the bounded manifest contract."""


def _strip_extended_windows_prefix(value: str) -> str:
    if value.startswith("\\\\?\\UNC\\"):
        return "\\\\" + value[8:]
    if value.startswith("\\\\?\\"):
        return value[4:]
    return value


def canonical_path_identity(path: str | os.PathLike[str]) -> str:
    """Return one comparison spelling for long/short and case-varied paths.

    Existing Windows components are resolved by the OS, which expands an 8.3
    alias to the same final path as its long spelling.  The returned value is
    for identity comparison only; it is not placed in the portable manifest.
    """

    raw = os.fspath(path)
    absolute = os.path.abspath(raw)
    resolved = os.path.realpath(absolute)
    resolved = _strip_extended_windows_prefix(resolved)
    return os.path.normcase(os.path.normpath(resolved))


def canonical_path(path: str | os.PathLike[str]) -> Path:
    """Return the resolved filesystem path while tolerating a missing leaf."""

    return Path(_strip_extended_windows_prefix(os.path.realpath(os.path.abspath(os.fspath(path)))))


def _is_within(root: Path, candidate: Path) -> bool:
    root_id = canonical_path_identity(root)
    candidate_id = canonical_path_identity(candidate)
    try:
        common = os.path.commonpath((root_id, candidate_id))
    except ValueError:  # different Windows drives, or otherwise incomparable
        return False
    return os.path.normcase(common) == os.path.normcase(root_id)


def _is_proper_within(root: Path, candidate: Path) -> bool:
    return _is_within(root, candidate) and (
        canonical_path_identity(root) != canonical_path_identity(candidate)
    )


def _relative_path(root: Path, candidate: Path) -> str:
    return os.path.relpath(canonical_path(candidate), canonical_path(root)).replace("\\", "/")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_regular_file(path: Path) -> tuple[str, int]:
    """Hash one stable regular file and refuse a change during the read."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        if not path.is_file():
            raise OSError("not a regular file")
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
        raise OSError("file changed while its identity was computed")
    return digest.hexdigest(), total


def _read_stable_regular_file(path: Path, *, max_bytes: int) -> bytes:
    """Read one bounded file snapshot and reject identity drift during I/O."""

    if path.is_symlink() or not path.is_file():
        raise OSError("not a regular non-symlink file")
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        if before.st_size > max_bytes:
            raise OSError(f"file exceeds the {max_bytes}-byte parser bound")
        payload = handle.read(max_bytes + 1)
        after = os.fstat(handle.fileno())
    before_identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_identity = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if (
        before_identity != after_identity
        or len(payload) != after.st_size
        or len(payload) > max_bytes
    ):
        raise OSError("file changed while its bytes were read")
    return payload


def _strict_json_loads(payload: bytes) -> object:
    """Parse standards-conforming JSON with one unambiguous object mapping.

    Python's default decoder accepts duplicate object keys and non-finite
    constants. Neither has portable meaning across Vivado JSON consumers, so
    the manifest refuses both instead of assuming last-wins semantics.
    """

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> object:
        raise ValueError(f"non-finite JSON constant: {value}")

    return json.loads(
        payload,
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )


def _local_name(element: ElementTree.Element) -> str:
    return str(element.tag).rsplit("}", 1)[-1]


def _children(element: ElementTree.Element, name: str) -> Iterable[ElementTree.Element]:
    return (child for child in element if _local_name(child) == name)


def _first_option(element: ElementTree.Element, name: str) -> str:
    for child in element.iter():
        if _local_name(child) == "Option" and child.get("Name") == name:
            return str(child.get("Val") or "")
    return ""


def _normalized_property_name(value: str) -> str:
    return "".join(character for character in value.casefold() if character.isalnum())


_FILESYSTEMISH_SUFFIX = re.compile(
    r"\.(?:bd|bin|coe|csv|dat|dcp|elf|hex|mem|mif|prj|sv|tcl|txt|v|vhd|vhdl|xdc|xci)$",
    re.IGNORECASE,
)


def _direct_parameter_strings(value: object) -> tuple[str, ...]:
    """Read a scalar or conventional ``[{value: ...}]`` parameter payload."""

    if isinstance(value, str):
        return (value,)
    if isinstance(value, dict):
        direct = value.get("value")
        return (direct,) if isinstance(direct, str) else ()
    if isinstance(value, list):
        return tuple(
            direct
            for item in value
            if isinstance(item, dict)
            for direct in (item.get("value"),)
            if isinstance(direct, str)
        )
    return ()


def _looks_like_filesystem_value(value: str) -> bool:
    candidate = str(value).strip()
    if not candidate:
        return False
    return bool(
        re.match(r"^(?:[A-Za-z]:[\\/]|[\\/]{1,2}|\.\.?[\\/])", candidate)
        or "/" in candidate
        or "\\" in candidate
        or _FILESYSTEMISH_SUFFIX.search(candidate)
    )


def _declared_property_values(
    document: ElementTree.Element,
    *,
    normalized_names: frozenset[str],
) -> tuple[str, ...]:
    values: list[str] = []
    for current in document.iter():
        declared_names = {
            _normalized_property_name(str(current.get("Name") or "")),
            _normalized_property_name(_local_name(current)),
        }
        if declared_names & normalized_names:
            raw = str(current.get("Val") or current.text or "").strip()
            if raw not in {"", "{}"}:
                values.append(raw)
        for attribute_name, attribute_value in current.attrib.items():
            if (
                _normalized_property_name(str(attribute_name))
                not in normalized_names
            ):
                continue
            raw = str(attribute_value).strip()
            if raw not in {"", "{}"}:
                values.append(raw)
    return tuple(values)


def _declared_custom_ip_repository_paths(
    document: ElementTree.Element,
) -> tuple[str, ...]:
    """Return custom IP repository declarations without opening them.

    Vivado serializes the source-fileset property as ``IPRepoPath`` in XPR
    XML, while Tcl exposes ``IP_REPO_PATHS``. Both spellings are recognized.
    """

    return _declared_property_values(
        document,
        normalized_names=_CUSTOM_IP_REPOSITORY_PROPERTY_NAMES,
    )


def _file_contains_token(
    path: Path,
    token: bytes,
    *,
    case_insensitive: bool = False,
) -> bool:
    """Search a regular file as a bounded-memory, stable byte stream."""

    overlap = max(0, len(token) - 1)
    needle = token.lower() if case_insensitive else token
    tail = b""
    found = False
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            combined = tail + (chunk.lower() if case_insensitive else chunk)
            if needle in combined:
                found = True
                break
            tail = combined[-overlap:] if overlap else b""
        after = os.fstat(handle.fileno())
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
    if before_identity != after_identity:
        raise OSError("file changed while transitive-input directives were scanned")
    return found


def _semantic_run_configuration(element: ElementTree.Element) -> dict[str, Any]:
    """Project one run to deterministic, relocation-stable semantics.

    Vivado persists mutable run state and execution directories next to the
    authored strategy.  Those values differ after copying or opening a project
    and are not design configuration.  The remaining recursive XML projection
    binds strategy handles, ordered steps and options, report strategy, and
    other authored run properties without depending on the workspace path.
    """

    def project(
        current: ElementTree.Element, *, root: bool = False
    ) -> dict[str, Any] | None:
        element_name = _local_name(current)
        if element_name in _RUN_VOLATILE_ELEMENTS:
            return None
        attributes = {
            str(name): str(value)
            for name, value in sorted(current.attrib.items())
            if str(name) not in _RUN_VOLATILE_ATTRIBUTES
            and not (root and str(name) in _RUN_NON_SEMANTIC_ROOT_ATTRIBUTES)
        }
        children = [
            child_body
            for child in current
            if (child_body := project(child)) is not None
        ]
        body: dict[str, Any] = {
            "element": element_name,
            "attributes": attributes,
            "children": children,
        }
        text = str(current.text or "").strip()
        if text:
            body["text"] = text
        return body

    configuration = project(element, root=True)
    if configuration is None:  # a Run itself is never a volatile child
        raise VivadoManifestError("cannot project Vivado Run configuration")
    return configuration


def _semantic_run_configuration_sha256(element: ElementTree.Element) -> str:
    payload = json.dumps(
        _semantic_run_configuration(element),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return _sha256_bytes(payload)


def _refused_run_argument_values(element: ElementTree.Element) -> tuple[str, ...]:
    """Return run options that can admit unmanifested synthesis inputs."""

    refused: list[str] = []

    def inspect(logical_name: str, raw_value: str, element_name: str) -> None:
        raw_value = raw_value.strip()
        if not raw_value:
            return
        normalized_name = _normalized_property_name(logical_name)
        if (
            normalized_name.endswith("moreoptions")
            or normalized_name.endswith("includedirs")
            or normalized_name.endswith("argsfile")
            or normalized_name.endswith("argsfilepath")
            or normalized_name.endswith("launchoptions")
        ):
            refused.append(f"{logical_name}={raw_value}")
            return
        value_key = raw_value.casefold().replace("-", "_")
        if "_include_dirs" in value_key or re.search(
            r"(?:^|\s)_?file(?:\s|=|$)", value_key
        ):
            refused.append(f"{logical_name or element_name}={raw_value}")

    for current in element.iter():
        element_name = _local_name(current)
        for attribute_name, attribute_value in current.attrib.items():
            inspect(str(attribute_name), str(attribute_value), element_name)
        logical_name = str(
            current.get("Id")
            or current.get("Name")
            or current.get("Property")
            or ""
        )
        inspect(
            logical_name,
            str(current.get("Val") or current.get("Value") or ""),
            element_name,
        )
        inspect(logical_name, str(current.text or ""), element_name)
    return tuple(dict.fromkeys(refused))


def _semantic_fileset_configuration_sha256(
    element: ElementTree.Element,
) -> str:
    """Bind every non-file FileSet property in authored XML order.

    Vivado synthesis semantics include FileSet options such as Verilog
    defines, include directories and design mode. Direct ``File`` records are
    bound separately with bytes, order and per-file metadata; everything else
    is conservatively retained here so an unknown FileSet option cannot drift
    between authoritative source and execution workspace unnoticed.
    """

    def project(current: ElementTree.Element) -> dict[str, Any] | None:
        if _local_name(current) == "File":
            return None
        children = [
            child_body
            for child in current
            if (child_body := project(child)) is not None
        ]
        body: dict[str, Any] = {
            "element": _local_name(current),
            "attributes": {
                str(name): str(value)
                for name, value in sorted(current.attrib.items())
            },
            "children": children,
        }
        text = str(current.text or "").strip()
        if text:
            body["text"] = text
        return body

    configuration = project(element)
    if configuration is None:  # a FileSet itself is never a File
        raise VivadoManifestError("cannot project Vivado FileSet configuration")
    payload = json.dumps(
        configuration,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return _sha256_bytes(payload)


def _semantic_file_metadata(
    element: ElementTree.Element,
) -> tuple[tuple[str, str], ...]:
    """Bind authored Vivado file properties while excluding import history.

    File order is bound separately by ``sequence``.  Repeated attributes such
    as ``UsedIn`` are retained; sorting only normalizes XML serialization order
    within one File record, not the order of Files in a FileSet.
    """

    rows: list[tuple[str, str]] = [
        (f"File.{name}", str(value))
        for name, value in element.attrib.items()
        if str(name) != "Path"
    ]
    for child in element.iter():
        if _local_name(child) != "Attr":
            continue
        name = str(child.get("Name") or "")
        if not name or name in _FILE_VOLATILE_ATTRIBUTES:
            continue
        rows.append((name, str(child.get("Val") or "")))
    return tuple(sorted(rows))


def _semantic_file_configuration_sha256(element: ElementTree.Element) -> str:
    """Bind unknown per-file XML semantics without import-history noise."""

    def project(
        current: ElementTree.Element, *, root: bool = False
    ) -> dict[str, Any] | None:
        element_name = _local_name(current)
        if element_name == "Attr" and str(current.get("Name") or "") in (
            _FILE_VOLATILE_ATTRIBUTES
        ):
            return None
        attributes = {
            str(name): str(value)
            for name, value in sorted(current.attrib.items())
            if not (root and str(name) == "Path")
        }
        children = [
            child_body
            for child in current
            if (child_body := project(child)) is not None
        ]
        body: dict[str, Any] = {
            "element": element_name,
            "attributes": attributes,
            "children": children,
        }
        text = str(current.text or "").strip()
        if text:
            body["text"] = text
        return body

    configuration = project(element, root=True)
    if configuration is None:  # a File itself is never a volatile Attr
        raise VivadoManifestError("cannot project Vivado File configuration")
    payload = json.dumps(
        configuration,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return _sha256_bytes(payload)


def _metadata_value(
    metadata: tuple[tuple[str, str], ...], *names: str
) -> str:
    wanted = {name.casefold() for name in names}
    for name, value in metadata:
        if name.casefold() in wanted:
            return value
    return ""


def _kind_for(path: str, *, fileset_type: str = "") -> str:
    suffix = Path(path.replace("\\", "/")).suffix.lower()
    kinds = {
        ".xpr": "vivado_project",
        ".bd": "vivado_block_design",
        ".xci": "vivado_ip_configuration",
        ".v": "rtl",
        ".sv": "rtl",
        ".vh": "rtl_header",
        ".svh": "rtl_header",
        ".vhd": "rtl",
        ".vhdl": "rtl",
        ".xdc": "constraint",
        ".dcp": "checkpoint",
        ".bit": "bitstream",
        ".mem": "memory_initialization",
        ".prj": "project_configuration",
    }
    if suffix in kinds:
        return kinds[suffix]
    if fileset_type == "SimulationSrcs":
        return "simulation_source"
    return "project_file"


def _origin_for(raw_path: str, kind: str, *, reference_type: str) -> str:
    if reference_type == "import_origin":
        return "import_origin"
    if kind == "vivado_ip_configuration":
        return "ip_configuration"
    if kind == "vivado_block_design":
        return "block_design"
    upper = raw_path.upper()
    if upper.startswith("$PGENDIR") or upper.startswith("$PRUNDIR"):
        return "generated"
    if upper.startswith("$PCACHEDIR"):
        return "cache"
    return "project"


@dataclass(frozen=True)
class VivadoArtifactIdentity:
    path: str
    kind: str
    byte_length: int
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VivadoDerivedStateRoot:
    """Inspectable inventory of one compiler-managed project subtree."""

    role: str
    path: str
    status: str
    files: tuple[VivadoArtifactIdentity, ...]
    tree_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "path": self.path,
            "status": self.status,
            "file_count": len(self.files),
            "byte_length": sum(item.byte_length for item in self.files),
            "tree_sha256": self.tree_sha256,
            "files": [item.to_dict() for item in self.files],
        }


@dataclass(frozen=True)
class VivadoFileReference:
    raw_path: str
    path: str
    kind: str
    fileset: str
    reference_type: str
    origin: str
    used_in: tuple[str, ...]
    sequence: int
    configuration_sha256: str
    status: str
    inside_project: bool
    exists: bool
    file_type: str = ""
    processing_order: str = ""
    scoped_to_ref: str = ""
    scoped_to_cells: str = ""
    semantic_metadata: tuple[tuple[str, str], ...] = ()
    byte_length: int | None = None
    sha256: str | None = None
    error: str = ""
    _resolved_path: Path | None = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body.pop("_resolved_path", None)
        body["used_in"] = list(self.used_in)
        body["semantic_metadata"] = [
            {"name": name, "value": value}
            for name, value in self.semantic_metadata
        ]
        return body

    @property
    def resolved_path(self) -> Path | None:
        return self._resolved_path


@dataclass(frozen=True)
class VivadoFileSet:
    name: str
    kind: str
    top: str
    source_directory: str
    generated_directory: str
    reference_paths: tuple[str, ...]
    configuration_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "top": self.top,
            "source_directory": self.source_directory,
            "generated_directory": self.generated_directory,
            "reference_paths": list(self.reference_paths),
            "configuration_sha256": self.configuration_sha256,
        }


@dataclass(frozen=True)
class VivadoRun:
    name: str
    kind: str
    source_set: str
    constraints_set: str
    synthesis_run: str
    part: str
    directory: str
    configuration_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class VivadoProjectManifest:
    product: str
    format_version: str
    project: VivadoArtifactIdentity
    part: str
    board_part: str
    top: str
    project_configuration_sha256: str
    custom_ip_repository_paths: tuple[str, ...]
    custom_board_repository_paths: tuple[str, ...]
    include_directory_values: tuple[str, ...]
    derived_state_roots: tuple[VivadoDerivedStateRoot, ...]
    declared_generated_output_roots: tuple[str, ...]
    vendor_catalog_resource_values: tuple[str, ...]
    verilog_transitive_input_directive_files: tuple[str, ...]
    vhdl_transitive_input_directive_files: tuple[str, ...]
    refused_core_container_files: tuple[str, ...]
    refused_dependency_roots: tuple[str, ...]
    refused_fileset_roots: tuple[str, ...]
    refused_block_design_files: tuple[str, ...]
    refused_ip_configuration_files: tuple[str, ...]
    refused_run_argument_values: tuple[str, ...]
    refused_run_state_paths: tuple[str, ...]
    refused_active_file_modes: tuple[str, ...]
    filesets: tuple[VivadoFileSet, ...]
    file_references: tuple[VivadoFileReference, ...]
    runs: tuple[VivadoRun, ...]
    outside_references: tuple[str, ...]
    missing_references: tuple[str, ...]
    unresolved_references: tuple[str, ...]
    unreadable_references: tuple[str, ...]
    _project_root: Path = field(repr=False, compare=False)
    schema: str = MANIFEST_SCHEMA

    @property
    def project_root(self) -> Path:
        return self._project_root

    @property
    def blocking_file_references(self) -> tuple[VivadoFileReference, ...]:
        """Active project inputs that are not a present, readable snapshot."""

        return tuple(
            ref
            for ref in self.file_references
            if ref.reference_type in _ACTIVE_REFERENCE_TYPES
            and ref.status != "present"
        )

    @property
    def complete(self) -> bool:
        return (
            not self.custom_ip_repository_paths
            and not self.custom_board_repository_paths
            and not self.include_directory_values
            and not self.verilog_transitive_input_directive_files
            and not self.vhdl_transitive_input_directive_files
            and not self.refused_core_container_files
            and not self.refused_dependency_roots
            and not self.refused_fileset_roots
            and not self.refused_block_design_files
            and not self.refused_ip_configuration_files
            and not self.refused_run_argument_values
            and not self.refused_run_state_paths
            and not self.refused_active_file_modes
            and not self.blocking_file_references
        )

    def source_identity_body(self) -> dict[str, Any]:
        """Relocation-stable identity of authoritative design inputs.

        Raw XPR bytes remain available as ``project.sha256`` for exact audit,
        but Vivado rewrites the root ``Project Path`` and other run-local XML
        state when a project is copied.  Those volatile bytes must not make an
        otherwise identical isolated workspace look like a different authored
        design.  This projection therefore binds the selected semantic project
        configuration and every authored active input byte. Compiler products
        below XPR/XCI-declared generated, cache, run, and shared-output roots
        remain exact workspace-manifest inputs, but are excluded from candidate
        identity so a deterministic Vivado regeneration cannot mint a new
        authored candidate. Import-origin history is excluded as well.
        """

        inputs: list[dict[str, Any]] = []
        generated_roots = tuple(
            PurePosixPath(value)
            for value in self.declared_generated_output_roots
        )
        for ref in self.file_references:
            if ref.reference_type not in _ACTIVE_REFERENCE_TYPES:
                continue
            reference_path = PurePosixPath(ref.path)
            under_declared_output = ref.inside_project and any(
                reference_path == root or root in reference_path.parents
                for root in generated_roots
            )
            if (
                ref.origin == "import_origin"
                or ref.reference_type == "run_generated_state"
                or under_declared_output
            ):
                continue
            inputs.append(
                {
                    "sequence": len(inputs),
                    "path": ref.path if ref.inside_project else ref.raw_path,
                    "kind": ref.kind,
                    "fileset": ref.fileset,
                    "reference_type": ref.reference_type,
                    "origin": ref.origin,
                    "used_in": list(ref.used_in),
                    "configuration_sha256": ref.configuration_sha256,
                    "file_type": ref.file_type,
                    "processing_order": ref.processing_order,
                    "scoped_to_ref": ref.scoped_to_ref,
                    "scoped_to_cells": ref.scoped_to_cells,
                    "semantic_metadata": [
                        {"name": name, "value": value}
                        for name, value in ref.semantic_metadata
                    ],
                    "status": ref.status,
                    "byte_length": ref.byte_length,
                    "sha256": ref.sha256,
                }
            )
        return {
            "schema": "daedalus-chip-vivado-source-identity/3",
            "product": self.product,
            "format_version": self.format_version,
            "project_path": self.project.path,
            "part": self.part,
            "board_part": self.board_part,
            "top": self.top,
            "project_configuration_sha256": (
                self.project_configuration_sha256
            ),
            "derived_state_roots": [
                {"role": item.role, "path": item.path}
                for item in self.derived_state_roots
            ],
            "declared_generated_output_roots": list(
                self.declared_generated_output_roots
            ),
            "vendor_catalog_resource_values": list(
                self.vendor_catalog_resource_values
            ),
            "verilog_transitive_input_directive_files": list(
                self.verilog_transitive_input_directive_files
            ),
            "vhdl_transitive_input_directive_files": list(
                self.vhdl_transitive_input_directive_files
            ),
            "refused_core_container_files": list(
                self.refused_core_container_files
            ),
            "refused_dependency_roots": list(self.refused_dependency_roots),
            "refused_fileset_roots": list(self.refused_fileset_roots),
            "refused_block_design_files": list(
                self.refused_block_design_files
            ),
            "refused_ip_configuration_files": list(
                self.refused_ip_configuration_files
            ),
            "refused_run_argument_values": list(
                self.refused_run_argument_values
            ),
            "refused_run_state_paths": list(self.refused_run_state_paths),
            "refused_active_file_modes": list(self.refused_active_file_modes),
            "filesets": [
                {
                    "name": item.name,
                    "kind": item.kind,
                    "top": item.top,
                    "source_directory": item.source_directory,
                    "generated_directory": item.generated_directory,
                    "configuration_sha256": item.configuration_sha256,
                }
                for item in self.filesets
            ],
            "runs": [
                {
                    "name": item.name,
                    "kind": item.kind,
                    "source_set": item.source_set,
                    "constraints_set": item.constraints_set,
                    "synthesis_run": item.synthesis_run,
                    "part": item.part,
                    "configuration_sha256": item.configuration_sha256,
                }
                for item in self.runs
            ],
            "inputs": inputs,
        }

    @property
    def source_identity_sha256(self) -> str:
        payload = json.dumps(
            self.source_identity_body(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        return _sha256_bytes(payload)

    def to_dict(self) -> dict[str, Any]:
        """Portable canonical body; absolute execution roots are excluded."""

        return {
            "schema": self.schema,
            "product": self.product,
            "format_version": self.format_version,
            "project": self.project.to_dict(),
            "part": self.part,
            "board_part": self.board_part,
            "top": self.top,
            "project_configuration_sha256": (
                self.project_configuration_sha256
            ),
            "custom_ip_repository_paths": list(
                self.custom_ip_repository_paths
            ),
            "custom_board_repository_paths": list(
                self.custom_board_repository_paths
            ),
            "include_directory_values": list(self.include_directory_values),
            "derived_state_roots": [
                item.to_dict() for item in self.derived_state_roots
            ],
            "declared_generated_output_roots": list(
                self.declared_generated_output_roots
            ),
            "vendor_catalog_resource_values": list(
                self.vendor_catalog_resource_values
            ),
            "verilog_transitive_input_directive_files": list(
                self.verilog_transitive_input_directive_files
            ),
            "vhdl_transitive_input_directive_files": list(
                self.vhdl_transitive_input_directive_files
            ),
            "refused_core_container_files": list(
                self.refused_core_container_files
            ),
            "refused_dependency_roots": list(self.refused_dependency_roots),
            "refused_fileset_roots": list(self.refused_fileset_roots),
            "refused_block_design_files": list(
                self.refused_block_design_files
            ),
            "refused_ip_configuration_files": list(
                self.refused_ip_configuration_files
            ),
            "refused_run_argument_values": list(
                self.refused_run_argument_values
            ),
            "refused_run_state_paths": list(self.refused_run_state_paths),
            "refused_active_file_modes": list(self.refused_active_file_modes),
            "filesets": [item.to_dict() for item in self.filesets],
            "file_references": [item.to_dict() for item in self.file_references],
            "runs": [item.to_dict() for item in self.runs],
            "outside_references": list(self.outside_references),
            "missing_references": list(self.missing_references),
            "unresolved_references": list(self.unresolved_references),
            "unreadable_references": list(self.unreadable_references),
            "source_identity_sha256": self.source_identity_sha256,
            "complete": self.complete,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("ascii")

    @property
    def sha256(self) -> str:
        return _sha256_bytes(self.canonical_bytes)


def _macro_roots(project_root: Path, project_stem: str) -> dict[str, Path]:
    return {
        "PPRDIR": project_root,
        "PSRCDIR": project_root / f"{project_stem}.srcs",
        "PGENDIR": project_root / f"{project_stem}.gen",
        "PRUNDIR": project_root / f"{project_stem}.runs",
        "PCACHEDIR": project_root / f"{project_stem}.cache",
        "PIPUSERFILESDIR": project_root / f"{project_stem}.ip_user_files",
        "PSIMDIR": project_root / f"{project_stem}.sim",
        "PHWDIR": project_root / f"{project_stem}.hw",
    }


def _has_linklike_component(path: Path) -> bool:
    current = Path(os.path.abspath(os.fspath(path)))
    while True:
        if _is_linklike(current):
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent


def _resolve_reference(
    raw_path: str,
    *,
    project_root: Path,
    macro_roots: dict[str, Path],
    relative_to: Path | None = None,
) -> tuple[Path | None, str]:
    if not raw_path or "\x00" in raw_path or len(raw_path) > 4096:
        return None, "invalid path"
    match = _MACRO.fullmatch(raw_path)
    if match:
        base = macro_roots.get(match.group(1).upper())
        if base is None:
            return None, f"unknown XPR path macro ${match.group(1)}"
        tail = (match.group(2) or "").replace("\\", "/")
        candidate = base.joinpath(*[part for part in tail.split("/") if part])
        if _has_linklike_component(candidate):
            return None, "linked path component is refused"
        return canonical_path(candidate), ""
    if raw_path.startswith("$"):
        return None, "unresolved XPR path expression"
    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = (relative_to or project_root) / Path(raw_path.replace("\\", "/"))
    if _has_linklike_component(candidate):
        return None, "linked path component is refused"
    return canonical_path(candidate), ""


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


def _walk_project_dependency_files(root: Path, *, label: str) -> Iterable[Path]:
    """Yield one closed, deterministic source subtree without links."""

    if _is_linklike(root) or not root.is_dir():
        raise VivadoManifestError(
            f"{label} root is not a regular directory: {root}"
        )
    for current_raw, directory_names, file_names in os.walk(root, followlinks=False):
        current = Path(current_raw)
        directory_names.sort()
        file_names.sort()
        for name in tuple(directory_names):
            child = current / name
            if _is_linklike(child):
                raise VivadoManifestError(
                    f"linked {label} directory is refused: {child}"
                )
            if not _is_within(root, canonical_path(child)):
                raise VivadoManifestError(
                    f"{label} directory escaped its root: {child}"
                )
        for name in file_names:
            child = current / name
            if _is_linklike(child) or not child.is_file():
                raise VivadoManifestError(
                    f"non-regular {label} is refused: {child}"
                )
            resolved = canonical_path(child)
            if not _is_within(root, resolved):
                raise VivadoManifestError(
                    f"{label} escaped its root: {child}"
                )
            yield resolved


def _inventory_derived_state_root(
    state_root: Path,
    *,
    project_root: Path,
    role: str,
    max_files: int,
) -> VivadoDerivedStateRoot:
    """Hash an inspectable, stable snapshot of one compiler-state tree."""

    display_root = _relative_path(project_root, state_root)
    if not state_root.exists():
        body = {
            "role": role,
            "path": display_root,
            "status": "missing",
            "files": [],
        }
        return VivadoDerivedStateRoot(
            role=role,
            path=display_root,
            status="missing",
            files=(),
            tree_sha256=_sha256_bytes(
                json.dumps(
                    body,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode("ascii")
            ),
        )
    paths = tuple(
        _walk_project_dependency_files(
            state_root,
            label=f"Vivado {role} state",
        )
    )
    if len(paths) > max_files:
        raise VivadoManifestError(
            f"Vivado {role} state exceeds the remaining {max_files}-file "
            "manifest bound"
        )
    identities: list[VivadoArtifactIdentity] = []
    observed_stats: dict[str, tuple[int, int, int, int]] = {}
    for path in paths:
        digest, byte_length = _hash_regular_file(path)
        status = os.stat(path, follow_symlinks=False)
        if status.st_size != byte_length:
            raise VivadoManifestError(
                f"Vivado {role} state changed while inventoried: {path}"
            )
        observed_stats[canonical_path_identity(path)] = (
            status.st_dev,
            status.st_ino,
            status.st_size,
            status.st_mtime_ns,
        )
        identities.append(
            VivadoArtifactIdentity(
                path=_relative_path(project_root, path),
                kind=f"vivado_{role}_state",
                byte_length=byte_length,
                sha256=digest,
            )
        )
    second_paths = tuple(
        _walk_project_dependency_files(
            state_root,
            label=f"Vivado {role} state",
        )
    )
    if tuple(map(canonical_path_identity, paths)) != tuple(
        map(canonical_path_identity, second_paths)
    ):
        raise VivadoManifestError(
            f"Vivado {role} state file set changed while inventoried"
        )
    for path in second_paths:
        status = os.stat(path, follow_symlinks=False)
        observed = observed_stats[canonical_path_identity(path)]
        current = (
            status.st_dev,
            status.st_ino,
            status.st_size,
            status.st_mtime_ns,
        )
        if current != observed:
            raise VivadoManifestError(
                f"Vivado {role} state changed while inventoried: {path}"
            )
    body = {
        "role": role,
        "path": display_root,
        "status": "present",
        "files": [item.to_dict() for item in identities],
    }
    return VivadoDerivedStateRoot(
        role=role,
        path=display_root,
        status="present",
        files=tuple(identities),
        tree_sha256=_sha256_bytes(
            json.dumps(
                body,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ),
    )


def _block_design_path_refusals(
    path: Path,
    *,
    project_root: Path,
    macro_roots: dict[str, Path],
) -> tuple[str, ...]:
    """Validate the bounded Vivado JSON BD path surface supported by Gate 1."""

    display_path = _relative_path(project_root, path)
    try:
        payload = _read_stable_regular_file(
            path,
            max_bytes=_MAX_BLOCK_DESIGN_BYTES,
        )
        document = _strict_json_loads(payload)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return (f"{display_path}: unsupported BD JSON: {exc}",)
    if not isinstance(document, dict):
        return (f"{display_path}: unsupported BD JSON root",)
    design = document.get("design")
    design_info = design.get("design_info") if isinstance(design, dict) else None
    if not isinstance(design_info, dict):
        return (f"{display_path}: missing design.design_info",)

    path_values: list[tuple[str, object]] = [
        ("gen_directory", design_info.get("gen_directory"))
    ]
    path_suffixes = ("file", "filename", "filepath", "path", "directory", "dir")
    logical_path_keys = {"insthierpath", "instancepath"}
    nonfilesystem_keys = logical_path_keys | {
        "addressblock",
        "bmminfoaddressspace",
        "bmminfoprocessor",
        "cellname",
        "clkdomain",
        "clock",
        "description",
        "displayname",
        "interfaceports",
        "ports",
        "value",
        # Every occurrence is classified and checked as ``gen_directory``
        # below. Do not classify the same scalar a second time as unknown.
        "gendirectory",
    }

    def string_values(value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            return (value,)
        if isinstance(value, dict):
            direct = value.get("value")
            if isinstance(direct, str):
                return (direct,)
            return tuple(
                item
                for nested in value.values()
                for item in string_values(nested)
            )
        if isinstance(value, list):
            return tuple(
                item
                for nested in value
                for item in string_values(nested)
            )
        return ()

    def collect(current: object) -> None:
        if isinstance(current, dict):
            for key, value in current.items():
                normalized_key = _normalized_property_name(str(key))
                if normalized_key == "xcipath":
                    path_values.append(("xci_path", value))
                elif normalized_key == "gendirectory":
                    candidates = _direct_parameter_strings(value)
                    if candidates:
                        path_values.extend(
                            ("gen_directory", candidate)
                            for candidate in candidates
                        )
                    else:
                        path_values.append(("gen_directory", value))
                elif (
                    normalized_key.endswith(path_suffixes)
                    and normalized_key not in logical_path_keys
                ):
                    path_values.extend(
                        (f"path field {key}", item)
                        for item in string_values(value)
                    )
                elif normalized_key not in nonfilesystem_keys:
                    path_values.extend(
                        (f"unclassified field {key}", item)
                        for item in _direct_parameter_strings(value)
                        if _looks_like_filesystem_value(item)
                    )
                collect(value)
        elif isinstance(current, list):
            for value in current:
                collect(value)

    collect(document)
    refusals: list[str] = []
    bd_root = path.parent
    for role, raw_value in path_values:
        if not isinstance(raw_value, str) or not raw_value.strip():
            refusals.append(f"{display_path}: invalid {role}")
            continue
        resolved, error = _resolve_reference(
            raw_value,
            project_root=project_root,
            macro_roots=macro_roots,
            relative_to=bd_root,
        )
        if resolved is None or error:
            refusals.append(f"{display_path}: unresolved {role}")
            continue
        if not _is_within(project_root, resolved):
            refusals.append(f"{display_path}: {role} outside project root")
            continue
        if role == "gen_directory" and not _is_proper_within(
            macro_roots["PGENDIR"], resolved
        ):
            refusals.append(
                f"{display_path}: gen_directory outside generated root"
            )
            continue
        if role == "xci_path":
            if not _is_within(bd_root, resolved):
                refusals.append(f"{display_path}: xci_path outside BD tree")
            elif (
                resolved.suffix.casefold() != ".xci"
                or _is_linklike(resolved)
                or not resolved.is_file()
            ):
                refusals.append(f"{display_path}: invalid xci_path target")
        elif role.startswith("path field "):
            if (
                not _is_within(bd_root, resolved)
                or _is_linklike(resolved)
                or not resolved.exists()
            ):
                refusals.append(f"{display_path}: unbound {role}")
        elif role.startswith("unclassified field "):
            refusals.append(f"{display_path}: path-like {role} is unsupported")
    return tuple(refusals)


def _xci_path_contract(
    path: Path,
    *,
    project_root: Path,
    macro_roots: dict[str, Path],
) -> tuple[tuple[str, ...], tuple[Path, ...], tuple[str, ...]]:
    """Validate XCI paths and return its explicitly generated output roots."""

    display_path = _relative_path(project_root, path)
    try:
        payload = _read_stable_regular_file(
            path,
            max_bytes=_MAX_BLOCK_DESIGN_BYTES,
        )
        document = _strict_json_loads(payload)
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return ((f"{display_path}: unsupported XCI JSON: {exc}",), (), ())
    if (
        not isinstance(document, dict)
        or document.get("schema") != "xilinx.com:schema:json_instance:1.0"
        or not isinstance(document.get("ip_inst"), dict)
    ):
        return ((f"{display_path}: unsupported XCI schema",), (), ())
    ip_instance = document["ip_inst"]
    parameters = ip_instance.get("parameters")
    runtime = (
        parameters.get("runtime_parameters")
        if isinstance(parameters, dict)
        else None
    )
    component = (
        parameters.get("component_parameters")
        if isinstance(parameters, dict)
        else None
    )
    model = (
        parameters.get("model_parameters")
        if isinstance(parameters, dict)
        else None
    )
    if not isinstance(runtime, dict) or not isinstance(component, dict):
        return ((f"{display_path}: unsupported XCI parameter schema",), (), ())
    if model is not None and not isinstance(model, dict):
        return ((f"{display_path}: unsupported XCI model parameter schema",), (), ())

    def records(value: object) -> tuple[dict[str, object], ...] | None:
        if not isinstance(value, list) or any(
            not isinstance(item, dict) for item in value
        ):
            return None
        return tuple(value)

    refusals: list[str] = []
    generated_output_roots: list[Path] = []
    vendor_catalog_resources: list[str] = []
    classified_path_scalars: set[tuple[str, str]] = set()
    component_reference = ip_instance.get("component_reference")
    if (
        not isinstance(component_reference, str)
        or not component_reference.startswith("xilinx.com:")
    ):
        refusals.append(
            f"{display_path}: non-vendor or missing component_reference"
        )
    xci_root = path.parent
    output_values: list[tuple[str, object]] = [
        ("gen_directory", ip_instance.get("gen_directory"))
    ]
    for name in ("OUTPUTDIR", "SHAREDDIR"):
        values = records(runtime.get(name))
        output_values.append(
            (
                name,
                values[0].get("value")
                if values is not None and len(values) == 1
                else None,
            )
        )
    for role, raw_value in output_values:
        if not isinstance(raw_value, str) or not raw_value.strip():
            refusals.append(f"{display_path}: invalid {role}")
            continue
        classified_path_scalars.add(
            (_normalized_property_name(role), raw_value.strip())
        )
        resolved, error = _resolve_reference(
            raw_value,
            project_root=project_root,
            macro_roots=macro_roots,
            relative_to=xci_root,
        )
        if role in {"gen_directory", "OUTPUTDIR"}:
            allowed_roots = (macro_roots["PGENDIR"],)
            exact_allowed_roots: tuple[Path, ...] = ()
        else:
            allowed_roots = (
                macro_roots["PGENDIR"],
                macro_roots["PCACHEDIR"],
                macro_roots["PIPUSERFILESDIR"],
            )
            exact_allowed_roots = ()
            bd_shared_root = xci_root.parent.parent / "ipshared"
            if (
                xci_root.parent.name.casefold() == "ip"
                and _is_within(macro_roots["PSRCDIR"], bd_shared_root)
            ):
                exact_allowed_roots = (bd_shared_root,)
        if (
            resolved is None
            or error
            or not (
                any(_is_proper_within(root, resolved) for root in allowed_roots)
                or any(
                    canonical_path_identity(root)
                    == canonical_path_identity(resolved)
                    for root in exact_allowed_roots
                )
            )
        ):
            refusals.append(f"{display_path}: {role} outside dedicated output roots")
        else:
            generated_output_roots.append(resolved)

    path_suffixes = ("file", "filename", "filepath", "path", "directory", "dir")
    ignored_values = {"", "none", "no_coe_file_loaded", "false", "true"}
    for parameter_group in (component, model or {}):
        for name, raw_records in parameter_group.items():
            normalized_name = _normalized_property_name(str(name))
            if not normalized_name.endswith(path_suffixes):
                continue
            parameter_records = records(raw_records)
            if parameter_records is None:
                refusals.append(f"{display_path}: malformed file parameter {name}")
                continue
            for record in parameter_records:
                if record.get("enabled") is False:
                    continue
                raw_value = record.get("value")
                if not isinstance(raw_value, str):
                    refusals.append(
                        f"{display_path}: malformed file parameter {name} value"
                    )
                    continue
                value = raw_value.strip()
                if value.casefold() in ignored_values or value.isdecimal():
                    continue
                classified_path_scalars.add((normalized_name, value))
                generated_or_propagated = (
                    str(record.get("resolve_type") or "").casefold()
                    == "generated"
                    or str(record.get("value_src") or "").casefold()
                    == "ip_propagated"
                )
                if generated_or_propagated:
                    if value == "./" and normalized_name.endswith(
                        ("directory", "dir")
                    ):
                        continue
                    if re.fullmatch(r"[A-Za-z0-9_.-]+", value):
                        continue
                    refusals.append(
                        f"{display_path}: unsafe generated file parameter {name}"
                    )
                    continue
                resolved, error = _resolve_reference(
                    value,
                    project_root=project_root,
                    macro_roots=macro_roots,
                    relative_to=xci_root,
                )
                if (
                    resolved is None
                    or error
                    or not _is_within(xci_root, resolved)
                    or _is_linklike(resolved)
                    or not resolved.is_file()
                ):
                    refusals.append(
                        f"{display_path}: unbound user file parameter {name}"
                    )

    logical_path_keys = {"insthierpath", "instancepath"}

    def content_string_values(value: object) -> tuple[str, ...]:
        if isinstance(value, str):
            return (value,)
        if isinstance(value, dict):
            direct = value.get("value")
            if isinstance(direct, str):
                return (direct,)
            return tuple(
                item
                for nested in value.values()
                for item in content_string_values(nested)
            )
        if isinstance(value, list):
            return tuple(
                item
                for nested in value
                for item in content_string_values(nested)
            )
        return ()

    def inspect_vendor_content(current: object) -> None:
        if isinstance(current, dict):
            for name, value in current.items():
                normalized_name = _normalized_property_name(str(name))
                if (
                    normalized_name.endswith(path_suffixes)
                    and normalized_name not in logical_path_keys
                ):
                    for raw_value in content_string_values(value):
                        candidate = raw_value.strip()
                        if not candidate or candidate.casefold() in ignored_values:
                            continue
                        if re.fullmatch(r"data/[A-Za-z0-9_.-]+", candidate):
                            classified_path_scalars.add(
                                (normalized_name, candidate)
                            )
                            vendor_catalog_resources.append(
                                f"{display_path}:{name}={candidate}"
                            )
                        else:
                            refusals.append(
                                f"{display_path}: unbound vendor resource field {name}"
                            )
                inspect_vendor_content(value)
        elif isinstance(current, list):
            for value in current:
                inspect_vendor_content(value)

    inspect_vendor_content(ip_instance.get("contents"))

    nonfilesystem_keys = logical_path_keys | {
        "addressblock",
        "bmminfoaddressspace",
        "bmminfoprocessor",
        "cellname",
        "clkdomain",
        "clock",
        "description",
        "displayname",
        "interfaceports",
        "ports",
        "value",
    }

    def inspect_unclassified_paths(current: object) -> None:
        if isinstance(current, dict):
            for name, value in current.items():
                normalized_name = _normalized_property_name(str(name))
                for candidate in _direct_parameter_strings(value):
                    candidate = candidate.strip()
                    if not _looks_like_filesystem_value(candidate):
                        continue
                    if (
                        normalized_name in nonfilesystem_keys
                        or (normalized_name, candidate)
                        in classified_path_scalars
                    ):
                        continue
                    refusals.append(
                        f"{display_path}: path-like unclassified field {name} is unsupported"
                    )
                inspect_unclassified_paths(value)
        elif isinstance(current, list):
            for value in current:
                inspect_unclassified_paths(value)

    inspect_unclassified_paths(document)
    unique_output_roots = tuple(
        sorted(
            {canonical_path(root) for root in generated_output_roots},
            key=canonical_path_identity,
        )
    )
    return (
        tuple(refusals),
        unique_output_roots,
        tuple(sorted(set(vendor_catalog_resources))),
    )


def _dependency_configuration_sha256(relative_path: str, *, role: str) -> str:
    return _sha256_bytes(
        json.dumps(
            {
                "role": role,
                "relative_path": relative_path,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    )


def _semantic_project_configuration_sha256(
    document: ElementTree.Element,
    *,
    project_root: Path,
    macro_roots: dict[str, Path],
) -> str:
    """Bind root project options while normalizing relocation-only paths.

    Unknown options are retained rather than assumed harmless. The narrow
    exclusions are Vivado activity/state fields observed to change when a
    project is opened. Macro paths that stay within the project become stable
    relative paths; paths escaping the project retain their canonical external
    identity so board/IP dependency roots cannot drift silently.
    """

    def normalized_value(value: str) -> str:
        if value.startswith("$"):
            resolved, error = _resolve_reference(
                value,
                project_root=project_root,
                macro_roots=macro_roots,
            )
            if resolved is not None and not error:
                if _is_within(project_root, resolved):
                    return "project-path:" + _relative_path(project_root, resolved)
                return "external-path:" + canonical_path_identity(resolved)
        candidate = Path(value)
        if value and candidate.is_absolute():
            return "external-path:" + canonical_path_identity(candidate)
        return "literal:" + value

    def project(current: ElementTree.Element) -> dict[str, Any] | None:
        element_name = _local_name(current)
        if element_name == "Option":
            option_name = str(current.get("Name") or "")
            if option_name in _PROJECT_VOLATILE_OPTIONS or option_name.startswith("WT"):
                return None
        attributes: dict[str, str] = {}
        for name, value in sorted(current.attrib.items()):
            text = str(value)
            attributes[str(name)] = (
                normalized_value(text)
                if element_name == "Option" and str(name) == "Val"
                else text
            )
        children = [
            child_body
            for child in current
            if (child_body := project(child)) is not None
        ]
        body: dict[str, Any] = {
            "element": element_name,
            "attributes": attributes,
            "children": children,
        }
        text = str(current.text or "").strip()
        if text:
            body["text"] = text
        return body

    configurations = [
        body
        for node in _children(document, "Configuration")
        if (body := project(node)) is not None
    ]
    payload = json.dumps(
        configurations,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return _sha256_bytes(payload)


def _reference(
    raw_path: str,
    *,
    project_root: Path,
    macro_roots: dict[str, Path],
    fileset: str,
    fileset_type: str,
    reference_type: str,
    used_in: Iterable[str] = (),
    relative_to: Path | None = None,
    sequence: int,
    configuration_sha256: str,
    semantic_metadata: tuple[tuple[str, str], ...] = (),
) -> VivadoFileReference:
    resolved, resolution_error = _resolve_reference(
        raw_path,
        project_root=project_root,
        macro_roots=macro_roots,
        relative_to=relative_to,
    )
    kind = _kind_for(raw_path, fileset_type=fileset_type)
    origin = _origin_for(raw_path, kind, reference_type=reference_type)
    normalized_used_in = tuple(sorted({str(item) for item in used_in if str(item)}))
    metadata_fields = {
        "sequence": int(sequence),
        "file_type": _metadata_value(
            semantic_metadata, "FileType", "FILE_TYPE"
        ),
        "processing_order": _metadata_value(
            semantic_metadata, "ProcessingOrder", "PROCESSING_ORDER"
        ),
        "scoped_to_ref": _metadata_value(
            semantic_metadata, "ScopedToRef", "SCOPED_TO_REF"
        ),
        "scoped_to_cells": _metadata_value(
            semantic_metadata, "ScopedToCells", "SCOPED_TO_CELLS"
        ),
        "semantic_metadata": semantic_metadata,
        "configuration_sha256": configuration_sha256,
    }
    if resolved is None:
        return VivadoFileReference(
            raw_path=raw_path,
            path=raw_path,
            kind=kind,
            fileset=fileset,
            reference_type=reference_type,
            origin=origin,
            used_in=normalized_used_in,
            **metadata_fields,
            status="unresolved",
            inside_project=False,
            exists=False,
            error=resolution_error,
        )

    inside = _is_within(project_root, resolved)
    display_path = (
        _relative_path(project_root, resolved)
        if inside
        else canonical_path(resolved).as_posix()
    )
    exists = resolved.is_file()
    if not inside:
        return VivadoFileReference(
            raw_path=raw_path,
            path=display_path,
            kind=kind,
            fileset=fileset,
            reference_type=reference_type,
            origin=origin,
            used_in=normalized_used_in,
            **metadata_fields,
            status="outside",
            inside_project=False,
            exists=exists,
            error="reference resolves outside the declared project root",
            _resolved_path=resolved,
        )
    if not exists:
        return VivadoFileReference(
            raw_path=raw_path,
            path=display_path,
            kind=kind,
            fileset=fileset,
            reference_type=reference_type,
            origin=origin,
            used_in=normalized_used_in,
            **metadata_fields,
            status="missing",
            inside_project=True,
            exists=False,
            error="referenced file does not exist",
            _resolved_path=resolved,
        )

    # ImportPath is historical provenance, not an active input.  Do not read it
    # a second time even if it happens to point back into the project.
    if reference_type == "import_origin":
        return VivadoFileReference(
            raw_path=raw_path,
            path=display_path,
            kind=kind,
            fileset=fileset,
            reference_type=reference_type,
            origin=origin,
            used_in=normalized_used_in,
            **metadata_fields,
            status="present",
            inside_project=True,
            exists=True,
            _resolved_path=resolved,
        )
    try:
        digest, byte_length = _hash_regular_file(resolved)
    except OSError as exc:
        return VivadoFileReference(
            raw_path=raw_path,
            path=display_path,
            kind=kind,
            fileset=fileset,
            reference_type=reference_type,
            origin=origin,
            used_in=normalized_used_in,
            **metadata_fields,
            status="unreadable",
            inside_project=True,
            exists=True,
            error=str(exc),
            _resolved_path=resolved,
        )
    return VivadoFileReference(
        raw_path=raw_path,
        path=display_path,
        kind=kind,
        fileset=fileset,
        reference_type=reference_type,
        origin=origin,
        used_in=normalized_used_in,
        **metadata_fields,
        status="present",
        inside_project=True,
        exists=True,
        byte_length=byte_length,
        sha256=digest,
        _resolved_path=resolved,
    )


def build_vivado_project_manifest(
    xpr_path: str | os.PathLike[str],
    *,
    project_root: str | os.PathLike[str] | None = None,
    max_references: int = _MAX_REFERENCES,
) -> VivadoProjectManifest:
    """Parse one XPR and bind its direct project inputs without executing it."""

    if isinstance(max_references, bool) or not isinstance(max_references, int):
        raise VivadoManifestError("max_references must be an integer")
    if max_references < 1 or max_references > _MAX_REFERENCES:
        raise VivadoManifestError(
            f"max_references must be between 1 and {_MAX_REFERENCES}"
        )
    raw_xpr = Path(xpr_path)
    if project_root is None:
        lexical_xpr = raw_xpr if raw_xpr.is_absolute() else Path.cwd() / raw_xpr
        if _has_linklike_component(lexical_xpr):
            raise VivadoManifestError("XPR path contains a linked component")
        xpr = canonical_path(raw_xpr)
        root = canonical_path(xpr.parent)
    else:
        lexical_root = Path(project_root)
        if not lexical_root.is_absolute():
            lexical_root = Path.cwd() / lexical_root
        lexical_xpr = raw_xpr if raw_xpr.is_absolute() else lexical_root / raw_xpr
        if _has_linklike_component(lexical_root) or _has_linklike_component(
            lexical_xpr
        ):
            raise VivadoManifestError(
                "project root or XPR path contains a linked component"
            )
        root = canonical_path(project_root)
        xpr = canonical_path(raw_xpr if raw_xpr.is_absolute() else root / raw_xpr)
    if not root.is_dir():
        raise VivadoManifestError(f"project root is not a directory: {root}")
    if not _is_within(root, xpr):
        raise VivadoManifestError("XPR path escapes the declared project root")
    if xpr.suffix.lower() != ".xpr" or not xpr.is_file():
        raise VivadoManifestError(f"Vivado project is not a regular .xpr file: {xpr}")
    try:
        xpr_bytes = _read_stable_regular_file(xpr, max_bytes=_MAX_XPR_BYTES)
    except OSError as exc:
        raise VivadoManifestError(f"cannot read Vivado project: {exc}") from exc
    upper_xml = xpr_bytes.upper()
    if b"<!DOCTYPE" in upper_xml or b"<!ENTITY" in upper_xml:
        raise VivadoManifestError("DTD/entity declarations are not accepted in XPR input")
    try:
        document = ElementTree.fromstring(xpr_bytes)
    except ElementTree.ParseError as exc:
        raise VivadoManifestError(f"invalid XPR XML: {exc}") from exc
    if _local_name(document) != "Project" or document.get("Product") != "Vivado":
        raise VivadoManifestError("XML root is not an AMD Vivado Project")

    product = str(document.get("Product") or "")
    version = str(document.get("Version") or "")
    minor = str(document.get("Minor") or "")
    format_version = ".".join(part for part in (version, minor) if part)
    part = _first_option(document, "Part")
    board_part = _first_option(document, "BoardPart")
    macros = _macro_roots(root, xpr.stem)
    project_configuration_sha256 = _semantic_project_configuration_sha256(
        document,
        project_root=root,
        macro_roots=macros,
    )
    custom_ip_repository_paths = _declared_custom_ip_repository_paths(document)
    custom_board_repository_paths = _declared_property_values(
        document,
        normalized_names=_CUSTOM_BOARD_REPOSITORY_PROPERTY_NAMES,
    )
    include_directory_values = _declared_property_values(
        document,
        normalized_names=_INCLUDE_DIRECTORY_PROPERTY_NAMES,
    )

    references: list[VivadoFileReference] = []
    filesets: list[VivadoFileSet] = []
    design_tops: list[tuple[str, str]] = []
    active_sequence = 0
    refused_dependency_roots: list[str] = []
    refused_fileset_roots: list[str] = []
    refused_block_design_files: list[str] = []
    refused_run_state_paths: list[str] = []
    for default_launch in document.iter():
        if _local_name(default_launch) != "DefaultLaunch":
            continue
        raw_directory = str(default_launch.get("Dir") or "").strip()
        resolved_directory, resolution_error = _resolve_reference(
            raw_directory,
            project_root=root,
            macro_roots=macros,
        )
        if (
            not raw_directory
            or resolved_directory is None
            or resolution_error
            or not _is_within(macros["PRUNDIR"], resolved_directory)
        ):
            refused_run_state_paths.append("DefaultLaunch.Dir")
    for fileset_element in document.iter():
        if _local_name(fileset_element) != "FileSet":
            continue
        name = str(fileset_element.get("Name") or "")
        fileset_type = str(fileset_element.get("Type") or "")
        if not name:
            raise VivadoManifestError("XPR contains a nameless FileSet")
        top = _first_option(fileset_element, "TopModule")
        if fileset_type == "DesignSrcs" and top:
            design_tops.append((name, top))
        normalized_fileset_roots: dict[str, str] = {}
        for attribute_name, label in (
            ("RelSrcDir", "source"),
            ("RelGenDir", "generated"),
        ):
            raw_directory = str(fileset_element.get(attribute_name) or "").strip()
            if not raw_directory:
                normalized_fileset_roots[label] = ""
                continue
            resolved_directory, resolution_error = _resolve_reference(
                raw_directory,
                project_root=root,
                macro_roots=macros,
            )
            if resolved_directory is None or resolution_error:
                refused_fileset_roots.append(
                    f"{name}.{attribute_name}: {resolution_error or 'unresolved path'}"
                )
                normalized_fileset_roots[label] = raw_directory
                continue
            required_root = (
                macros["PSRCDIR"] if label == "source" else macros["PGENDIR"]
            )
            if not _is_within(required_root, resolved_directory):
                refused_fileset_roots.append(
                    f"{name}.{attribute_name}: outside dedicated {label} root"
                )
                normalized_fileset_roots[label] = canonical_path_identity(
                    resolved_directory
                )
                continue
            normalized_fileset_roots[label] = _relative_path(
                root, resolved_directory
            )
        fileset_paths: list[str] = []
        for file_element in _children(fileset_element, "File"):
            raw_path = str(file_element.get("Path") or "")
            if not raw_path:
                raise VivadoManifestError(f"FileSet {name!r} contains an empty File path")
            used_in = [
                str(attr.get("Val") or "")
                for attr in file_element.iter()
                if _local_name(attr) == "Attr" and attr.get("Name") == "UsedIn"
            ]
            semantic_metadata = _semantic_file_metadata(file_element)
            file_configuration_sha256 = (
                _semantic_file_configuration_sha256(file_element)
            )
            direct = _reference(
                raw_path,
                project_root=root,
                macro_roots=macros,
                fileset=name,
                fileset_type=fileset_type,
                reference_type="file",
                used_in=used_in,
                sequence=active_sequence,
                configuration_sha256=file_configuration_sha256,
                semantic_metadata=semantic_metadata,
            )
            references.append(direct)
            active_sequence += 1
            fileset_paths.append(direct.path)
            for attr in file_element.iter():
                if _local_name(attr) == "Attr" and attr.get("Name") == "ImportPath":
                    import_path = str(attr.get("Val") or "")
                    if import_path:
                        references.append(
                            _reference(
                                import_path,
                                project_root=root,
                                macro_roots=macros,
                                fileset=name,
                                fileset_type=fileset_type,
                                reference_type="import_origin",
                                sequence=direct.sequence,
                                configuration_sha256=file_configuration_sha256,
                                semantic_metadata=semantic_metadata,
                            )
                        )

            bd_parent = direct.resolved_path.parent if direct.resolved_path is not None else None
            for extended in file_element.iter():
                if _local_name(extended) != "CompFileExtendedInfo":
                    continue
                xci_path = str(extended.get("FileRelPathName") or "")
                if (
                    not xci_path
                    or Path(xci_path.replace("\\", "/")).suffix.lower()
                    not in {".xci", ".xcix", ".xco"}
                ):
                    continue
                xci = _reference(
                    xci_path,
                    project_root=root,
                    macro_roots=macros,
                    fileset=name,
                    fileset_type=fileset_type,
                    reference_type="ip_configuration",
                    used_in=used_in,
                    relative_to=bd_parent,
                    sequence=active_sequence,
                    configuration_sha256=file_configuration_sha256,
                    semantic_metadata=semantic_metadata,
                )
                references.append(xci)
                active_sequence += 1
                fileset_paths.append(xci.path)
                if (
                    direct.kind != "vivado_block_design"
                    or bd_parent is None
                    or xci.resolved_path is None
                    or not _is_within(bd_parent, xci.resolved_path)
                ):
                    refused_dependency_roots.append(
                        f"{direct.path} -> {xci.path}"
                    )

            dependency_roots: list[tuple[Path, str]] = []
            if direct.status == "present" and direct.resolved_path is not None:
                if direct.kind == "vivado_block_design":
                    dependency_roots.append(
                        (direct.resolved_path.parent, "block_design_dependency")
                    )
                elif direct.kind == "vivado_ip_configuration":
                    dependency_roots.append(
                        (direct.resolved_path.parent, "ip_dependency")
                    )
            for dependency_root, dependency_role in dependency_roots:
                if canonical_path_identity(dependency_root) == canonical_path_identity(
                    root
                ):
                    refused_dependency_roots.append(direct.path)
                    continue
                existing_identities = {
                    canonical_path_identity(reference.resolved_path)
                    for reference in references
                    if reference.resolved_path is not None
                }
                for dependency_path in _walk_project_dependency_files(
                    dependency_root,
                    label=dependency_role.replace("_", " "),
                ):
                    dependency_identity = canonical_path_identity(dependency_path)
                    if dependency_identity in existing_identities:
                        continue
                    relative_dependency = dependency_path.relative_to(
                        dependency_root
                    ).as_posix()
                    dependency = _reference(
                        relative_dependency,
                        project_root=root,
                        macro_roots=macros,
                        fileset=name,
                        fileset_type=fileset_type,
                        reference_type=dependency_role,
                        relative_to=dependency_root,
                        sequence=active_sequence,
                        configuration_sha256=(
                            _dependency_configuration_sha256(
                                relative_dependency,
                                role=dependency_role,
                            )
                        ),
                    )
                    references.append(dependency)
                    active_sequence += 1
                    fileset_paths.append(dependency.path)
                    existing_identities.add(dependency_identity)
                    if len(references) > max_references:
                        raise VivadoManifestError(
                            f"XPR exceeds the {max_references}-reference manifest bound"
                        )

            if len(references) > max_references:
                raise VivadoManifestError(
                    f"XPR exceeds the {max_references}-reference manifest bound"
                )
        filesets.append(
            VivadoFileSet(
                name=name,
                kind=fileset_type,
                top=top,
                source_directory=normalized_fileset_roots["source"],
                generated_directory=normalized_fileset_roots["generated"],
                reference_paths=tuple(fileset_paths),
                configuration_sha256=(
                    _semantic_fileset_configuration_sha256(fileset_element)
                ),
            )
        )

    top = ""
    if design_tops:
        top = sorted(design_tops, key=lambda item: (item[0] != "sources_1", item[0]))[0][1]
    if not part:
        raise VivadoManifestError("XPR does not declare a target Part")
    if not top:
        raise VivadoManifestError("XPR does not declare a design TopModule")

    runs: list[VivadoRun] = []
    refused_run_argument_values: list[str] = []
    for run in document.iter():
        if _local_name(run) != "Run":
            continue
        name = str(run.get("Id") or "")
        if not name:
            raise VivadoManifestError("XPR contains a nameless Run")
        run_configuration_sha256 = _semantic_run_configuration_sha256(run)
        refused_run_argument_values.extend(
            f"{name}: {value}" for value in _refused_run_argument_values(run)
        )
        for attribute_name in ("Dir", "AutoIncrementalDir", "AutoRQSDir"):
            raw_directory = str(run.get(attribute_name) or "").strip()
            if not raw_directory:
                continue
            resolved_directory, resolution_error = _resolve_reference(
                raw_directory,
                project_root=root,
                macro_roots=macros,
            )
            required_run_root = (
                macros["PRUNDIR"] if attribute_name == "Dir" else root
            )
            if (
                resolved_directory is None
                or resolution_error
                or not _is_within(required_run_root, resolved_directory)
            ):
                refused_run_state_paths.append(f"{name}.{attribute_name}")
        for generated_run in run.iter():
            if _local_name(generated_run) != "GeneratedRun":
                continue
            raw_directory = str(generated_run.get("Dir") or "").strip()
            raw_file = str(generated_run.get("File") or "").strip()
            generated_directory, directory_error = _resolve_reference(
                raw_directory,
                project_root=root,
                macro_roots=macros,
            )
            if (
                not raw_directory
                or generated_directory is None
                or directory_error
                or not _is_within(macros["PRUNDIR"], generated_directory)
            ):
                refused_run_state_paths.append(f"{name}.GeneratedRun.Dir")
                continue
            generated_file, file_error = _resolve_reference(
                raw_file,
                project_root=root,
                macro_roots=macros,
                relative_to=generated_directory,
            )
            if (
                not raw_file
                or generated_file is None
                or file_error
                or not _is_within(generated_directory, generated_file)
            ):
                refused_run_state_paths.append(f"{name}.GeneratedRun.File")
                continue
            if generated_file.exists():
                generated_reference = _reference(
                    raw_file,
                    project_root=root,
                    macro_roots=macros,
                    fileset=f"run:{name}",
                    fileset_type="RunState",
                    reference_type="run_generated_state",
                    relative_to=generated_directory,
                    sequence=active_sequence,
                    configuration_sha256=run_configuration_sha256,
                )
                references.append(generated_reference)
                active_sequence += 1
                if generated_reference.status != "present":
                    refused_run_state_paths.append(
                        f"{name}.GeneratedRun.File"
                    )
                if len(references) > max_references:
                    raise VivadoManifestError(
                        f"XPR exceeds the {max_references}-reference manifest bound"
                    )
        runs.append(
            VivadoRun(
                name=name,
                kind=str(run.get("Type") or ""),
                source_set=str(run.get("SrcSet") or ""),
                constraints_set=str(run.get("ConstrsSet") or ""),
                synthesis_run=str(run.get("SynthRun") or ""),
                part=str(run.get("Part") or ""),
                directory=str(run.get("Dir") or ""),
                configuration_sha256=run_configuration_sha256,
            )
        )

    outside = tuple(sorted({item.raw_path for item in references if item.status == "outside"}))
    missing = tuple(
        sorted(
            {
                item.raw_path
                for item in references
                if item.status == "missing"
                and item.reference_type in _ACTIVE_REFERENCE_TYPES
            }
        )
    )
    unresolved = tuple(
        sorted({item.raw_path for item in references if item.status == "unresolved"})
    )
    unreadable = tuple(
        sorted({item.raw_path for item in references if item.status == "unreadable"})
    )
    refused_ip_configuration_files: list[str] = []
    declared_generated_output_paths: list[Path] = []
    vendor_catalog_resource_values: list[str] = []
    inspected_block_designs: set[str] = set()
    for reference in references:
        if (
            reference.reference_type not in _ACTIVE_REFERENCE_TYPES
            or reference.kind != "vivado_block_design"
            or reference.status != "present"
            or reference.resolved_path is None
        ):
            continue
        identity = canonical_path_identity(reference.resolved_path)
        if identity in inspected_block_designs:
            continue
        inspected_block_designs.add(identity)
        refused_block_design_files.extend(
            _block_design_path_refusals(
                reference.resolved_path,
                project_root=root,
                macro_roots=macros,
            )
        )
    inspected_ip_configurations: set[str] = set()
    for reference in references:
        if (
            reference.reference_type not in _ACTIVE_REFERENCE_TYPES
            or reference.kind != "vivado_ip_configuration"
            or reference.status != "present"
            or reference.resolved_path is None
        ):
            continue
        identity = canonical_path_identity(reference.resolved_path)
        if identity in inspected_ip_configurations:
            continue
        inspected_ip_configurations.add(identity)
        xci_refusals, xci_output_roots, xci_vendor_resources = _xci_path_contract(
            reference.resolved_path,
            project_root=root,
            macro_roots=macros,
        )
        refused_ip_configuration_files.extend(xci_refusals)
        declared_generated_output_paths.extend(xci_output_roots)
        vendor_catalog_resource_values.extend(xci_vendor_resources)
    unique_generated_output_paths = tuple(
        sorted(
            {
                canonical_path(path)
                for path in declared_generated_output_paths
            },
            key=canonical_path_identity,
        )
    )
    declared_generated_output_roots = tuple(
        _relative_path(root, path)
        for path in unique_generated_output_paths
    )
    for reference in references:
        if (
            reference.reference_type not in {"file", "ip_configuration"}
            or reference.resolved_path is None
        ):
            continue
        for output_root in unique_generated_output_paths:
            if _is_within(output_root, reference.resolved_path):
                refused_dependency_roots.append(
                    "generated output root overlaps active authored input: "
                    + reference.path
                )
                break
    derived_state_roots: list[VivadoDerivedStateRoot] = []
    inventoried_files = 0
    for role, macro_name in (
        ("generated", "PGENDIR"),
        ("cache", "PCACHEDIR"),
        ("ip_user_files", "PIPUSERFILESDIR"),
        ("runs", "PRUNDIR"),
    ):
        remaining = max_references - len(references) - inventoried_files
        if remaining < 0:
            raise VivadoManifestError(
                f"XPR exceeds the {max_references}-reference manifest bound"
            )
        inventory = _inventory_derived_state_root(
            macros[macro_name],
            project_root=root,
            role=role,
            max_files=remaining,
        )
        derived_state_roots.append(inventory)
        inventoried_files += len(inventory.files)
    verilog_transitive_input_directive_files: list[str] = []
    vhdl_transitive_input_directive_files: list[str] = []
    refused_core_container_files = tuple(
        reference.path
        for reference in references
        if reference.reference_type in _ACTIVE_REFERENCE_TYPES
        and Path(reference.raw_path.replace("\\", "/")).suffix.casefold()
        in {".xcix", ".xco"}
    )
    refused_active_file_modes: list[str] = []
    verilog_extensions = frozenset({".v", ".sv", ".vh", ".svh"})
    vhdl_extensions = frozenset({".vhd", ".vhdl"})
    verilog_file_types = frozenset(
        {"verilog", "systemverilog", "verilogheader", "systemverilogheader"}
    )
    vhdl_file_types = frozenset({"vhdl", "vhdl2008"})
    for reference in references:
        if reference.reference_type not in _ACTIVE_REFERENCE_TYPES:
            continue
        extension = Path(reference.raw_path.replace("\\", "/")).suffix.casefold()
        file_type = reference.file_type.casefold()
        normalized_file_type = _normalized_property_name(reference.file_type)
        reason = ""
        if reference.reference_type == "file" and (
            extension == ".dcp"
            or normalized_file_type in {"designcheckpoint", "dcp"}
        ):
            reason = "active design checkpoint input"
        elif file_type == "tcl":
            reason = "FILE_TYPE Tcl"
        elif file_type == "xdc" and extension != ".xdc":
            reason = "FILE_TYPE XDC without .xdc suffix"
        elif extension == ".xdc" and file_type not in {"", "xdc"}:
            reason = f".xdc path with FILE_TYPE {reference.file_type}"
        elif (
            normalized_file_type in verilog_file_types
            and extension not in verilog_extensions
        ):
            reason = "Verilog FILE_TYPE without a Verilog suffix"
        elif (
            normalized_file_type in vhdl_file_types
            and extension not in vhdl_extensions
        ):
            reason = "VHDL FILE_TYPE without a VHDL suffix"
        elif (
            extension in verilog_extensions
            and normalized_file_type
            and normalized_file_type not in verilog_file_types
        ):
            reason = f"Verilog suffix with FILE_TYPE {reference.file_type}"
        elif (
            extension in vhdl_extensions
            and normalized_file_type
            and normalized_file_type not in vhdl_file_types
        ):
            reason = f"VHDL suffix with FILE_TYPE {reference.file_type}"
        elif extension in {".tcl", ".bat", ".cmd", ".exe", ".ps1"}:
            reason = f"automation suffix {extension}"
        elif (
            reference.reference_type == "file"
            and "synthesis" in reference.used_in
            and reference.kind == "project_file"
        ):
            reason = "unknown synthesis input type"
        if reason:
            refused_active_file_modes.append(f"{reference.path}: {reason}")
    for reference in references:
        if (
            reference.reference_type not in _ACTIVE_REFERENCE_TYPES
            or reference.status != "present"
            or reference.resolved_path is None
        ):
            continue
        extension = Path(reference.raw_path.replace("\\", "/")).suffix.casefold()
        normalized_file_type = _normalized_property_name(reference.file_type)
        if (
            extension not in verilog_extensions
            and normalized_file_type not in verilog_file_types
        ):
            continue
        try:
            contains_transitive_directive = any(
                _file_contains_token(reference.resolved_path, token)
                for token in (b"`include", b"$readmemh", b"$readmemb")
            )
        except OSError as exc:
            raise VivadoManifestError(
                f"cannot scan {reference.path!r} for Verilog transitive-input directives: {exc}"
            ) from exc
        if contains_transitive_directive:
            if reference.path not in verilog_transitive_input_directive_files:
                verilog_transitive_input_directive_files.append(reference.path)
    for reference in references:
        if (
            reference.reference_type not in _ACTIVE_REFERENCE_TYPES
            or reference.status != "present"
            or reference.resolved_path is None
        ):
            continue
        extension = Path(reference.raw_path.replace("\\", "/")).suffix.casefold()
        normalized_file_type = _normalized_property_name(reference.file_type)
        if (
            extension not in vhdl_extensions
            and normalized_file_type not in vhdl_file_types
        ):
            continue
        try:
            # Gate 1 does not attempt to interpret VHDL TextIO.  A FILE
            # declaration or the standard helpers below can make undeclared
            # external bytes affect synthesis, so conservatively refuse the
            # source until those inputs have an explicit manifest contract.
            contains_transitive_directive = any(
                _file_contains_token(
                    reference.resolved_path,
                    token,
                    case_insensitive=True,
                )
                for token in (b"file ", b"file\t", b"file\r", b"file\n", b"file_open", b"readline")
            )
        except OSError as exc:
            raise VivadoManifestError(
                f"cannot scan {reference.path!r} for VHDL transitive-input directives: {exc}"
            ) from exc
        if contains_transitive_directive:
            if reference.path not in vhdl_transitive_input_directive_files:
                vhdl_transitive_input_directive_files.append(reference.path)
    project_identity = VivadoArtifactIdentity(
        path=_relative_path(root, xpr),
        kind="vivado_project",
        byte_length=len(xpr_bytes),
        sha256=_sha256_bytes(xpr_bytes),
    )
    return VivadoProjectManifest(
        product=product,
        format_version=format_version,
        project=project_identity,
        part=part,
        board_part=board_part,
        top=top,
        project_configuration_sha256=project_configuration_sha256,
        custom_ip_repository_paths=custom_ip_repository_paths,
        custom_board_repository_paths=custom_board_repository_paths,
        include_directory_values=include_directory_values,
        derived_state_roots=tuple(derived_state_roots),
        declared_generated_output_roots=declared_generated_output_roots,
        vendor_catalog_resource_values=tuple(
            sorted(set(vendor_catalog_resource_values))
        ),
        verilog_transitive_input_directive_files=tuple(
            verilog_transitive_input_directive_files
        ),
        vhdl_transitive_input_directive_files=tuple(
            vhdl_transitive_input_directive_files
        ),
        refused_core_container_files=refused_core_container_files,
        refused_dependency_roots=tuple(refused_dependency_roots),
        refused_fileset_roots=tuple(refused_fileset_roots),
        refused_block_design_files=tuple(refused_block_design_files),
        refused_ip_configuration_files=tuple(
            refused_ip_configuration_files
        ),
        refused_run_argument_values=tuple(refused_run_argument_values),
        refused_run_state_paths=tuple(refused_run_state_paths),
        refused_active_file_modes=tuple(refused_active_file_modes),
        filesets=tuple(filesets),
        file_references=tuple(references),
        runs=tuple(sorted(runs, key=lambda item: item.name)),
        outside_references=outside,
        missing_references=missing,
        unresolved_references=unresolved,
        unreadable_references=unreadable,
        _project_root=root,
    )


# Narrow aliases for callers that naturally describe this operation as inspect.
inspect_vivado_project = build_vivado_project_manifest
load_vivado_project_manifest = build_vivado_project_manifest


__all__ = [
    "MANIFEST_SCHEMA",
    "VivadoArtifactIdentity",
    "VivadoDerivedStateRoot",
    "VivadoFileReference",
    "VivadoFileSet",
    "VivadoManifestError",
    "VivadoProjectManifest",
    "VivadoRun",
    "build_vivado_project_manifest",
    "canonical_path",
    "canonical_path_identity",
    "inspect_vivado_project",
    "load_vivado_project_manifest",
]
