"""KiCad artifact classification and effect-free project discovery.

Mirrors :mod:`daedalus.chip_design.sources`: a stable vocabulary before any
tool is invoked. Discovery reads directory entries and file bytes; it writes
nothing, follows no symlink into a new root, and starts no process.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

__all__ = [
    "ArtifactSpec",
    "DEFAULT_MAX_FILES",
    "DEFAULT_MAX_HASH_BYTES",
    "ProjectSpec",
    "classify_artifact",
    "discover_artifacts",
    "discover_projects",
    "is_authoritative",
]

DEFAULT_MAX_FILES = 20_000
DEFAULT_MAX_HASH_BYTES = 64 * 1024 * 1024


@dataclass(frozen=True)
class ArtifactSpec:
    path: str
    kind: str
    fmt: str
    role: str
    authoritative: bool
    size_bytes: int = -1
    sha256: str = ""
    hash_status: str = "not_hashed"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ProjectSpec:
    name: str
    project_file: str
    schematics: tuple[ArtifactSpec, ...]
    boards: tuple[ArtifactSpec, ...]
    other: tuple[ArtifactSpec, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "project_file": self.project_file,
            "schematics": [item.to_dict() for item in self.schematics],
            "boards": [item.to_dict() for item in self.boards],
            "other": [item.to_dict() for item in self.other],
        }


# suffix -> (kind, format, role, authoritative)
#
# "authoritative" marks the files a KiCad design is *defined* by. Caches, local
# settings and generated fabrication output are inspectable but never identity.
_SUFFIXES: dict[str, tuple[str, str, str, bool]] = {
    ".kicad_pro": ("project", "json", "kicad/project", True),
    ".kicad_sch": ("schematic", "sexpr", "kicad/schematic", True),
    ".kicad_pcb": ("board", "sexpr", "kicad/board", True),
    ".kicad_sym": ("symbol_library", "sexpr", "kicad/library", True),
    ".kicad_mod": ("footprint", "sexpr", "kicad/library", True),
    ".kicad_dru": ("design_rules", "sexpr", "kicad/rules", True),
    ".kicad_wks": ("drawing_sheet", "sexpr", "kicad/drawing-sheet", True),
    ".kicad_prl": ("local_settings", "json", "kicad/gui-state", False),
    ".kicad_sym_cache": ("symbol_cache", "sexpr", "kicad/cache", False),
    ".net": ("netlist", "sexpr", "generated/netlist", False),
    ".gbr": ("gerber", "text", "generated/fabrication", False),
    ".gbrjob": ("gerber_job", "json", "generated/fabrication", False),
    ".drl": ("drill", "text", "generated/fabrication", False),
    ".step": ("model_3d", "binary", "generated/3d", False),
    ".stp": ("model_3d", "binary", "generated/3d", False),
    ".wrl": ("model_3d", "text", "generated/3d", False),
    ".cir": ("spice_netlist", "text", "simulation/netlist", False),
}

_IGNORED_DIRS = {
    ".git", ".hg", ".svn", ".venv", "venv", "env", "__pycache__",
    "node_modules", "dist", "build", "out", "target", ".cache",
    ".pytest_cache", ".mypy_cache", ".ruff_cache", ".idea", ".vs",
    "fp-info-cache", "3d-models",
}

# KiCad writes "<project>-backups" next to the project; a backup is not the
# design and must never be mistaken for one.
_IGNORED_DIR_SUFFIXES = ("-backups",)


def classify_artifact(path: str | os.PathLike[str]) -> ArtifactSpec | None:
    candidate = Path(path)
    raw = _SUFFIXES.get(candidate.suffix.lower())
    if raw is None:
        return None
    kind, fmt, role, authoritative = raw
    return ArtifactSpec(
        path=candidate.as_posix(),
        kind=kind,
        fmt=fmt,
        role=role,
        authoritative=authoritative,
    )


def is_authoritative(path: str | os.PathLike[str]) -> bool:
    spec = classify_artifact(path)
    return bool(spec and spec.authoritative)


def _identity(path: Path, *, max_hash_bytes: int) -> tuple[int, str, str]:
    try:
        size = path.stat().st_size
    except OSError as exc:
        return -1, "", f"unreadable: {exc.strerror or exc}"
    if size > max_hash_bytes:
        return size, "", "skipped_too_large"
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        return size, "", f"unreadable: {exc.strerror or exc}"
    return size, digest, "sha256"


def discover_artifacts(
    root: str | os.PathLike[str],
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_hash_bytes: int = DEFAULT_MAX_HASH_BYTES,
    ignored_dirs: Iterable[str] = (),
) -> tuple[list[ArtifactSpec], bool]:
    """Walk ``root`` for recognized KiCad artifacts in stable order.

    Returns ``(artifacts, truncated)``. ``max_files`` is an exact output bound,
    so zero returns nothing; a negative bound or a non-directory root is
    refused rather than silently reported as an empty design. ``truncated`` is
    conservative: reaching the bound sets it even when nothing was left over.
    """

    if max_files < 0:
        raise ValueError("max_files must be >= 0")
    if max_hash_bytes < 0:
        raise ValueError("max_hash_bytes must be >= 0")
    base = Path(root).resolve()
    if not base.is_dir():
        raise ValueError(f"scan root is not a directory: {base}")
    if max_files == 0:
        return [], True

    ignored = _IGNORED_DIRS | {str(item) for item in ignored_dirs}
    out: list[ArtifactSpec] = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in ignored
            and not name.startswith(".")
            and not name.casefold().endswith(_IGNORED_DIR_SUFFIXES)
        )
        for name in sorted(filenames):
            full = Path(dirpath) / name
            spec = classify_artifact(full)
            if spec is None:
                continue
            size, digest, status = _identity(full, max_hash_bytes=max_hash_bytes)
            relative = full.resolve().relative_to(base).as_posix()
            out.append(
                ArtifactSpec(
                    path=relative,
                    kind=spec.kind,
                    fmt=spec.fmt,
                    role=spec.role,
                    authoritative=spec.authoritative,
                    size_bytes=size,
                    sha256=digest,
                    hash_status=status,
                )
            )
            if len(out) >= max_files:
                return out, True
    return out, False


def discover_projects(
    root: str | os.PathLike[str],
    *,
    max_files: int = DEFAULT_MAX_FILES,
    max_hash_bytes: int = DEFAULT_MAX_HASH_BYTES,
) -> dict[str, object]:
    """Group discovered artifacts into KiCad projects.

    A project is a ``.kicad_pro`` file; its schematics and board are the
    artifacts sharing its directory. Files that belong to no project are
    reported as ``unbound`` rather than being attached to the nearest guess --
    KiCad allows a standalone board, and inventing an owner would be a claim.
    """

    artifacts, truncated = discover_artifacts(
        root, max_files=max_files, max_hash_bytes=max_hash_bytes
    )
    by_directory: dict[str, list[ArtifactSpec]] = {}
    for item in artifacts:
        by_directory.setdefault(str(Path(item.path).parent.as_posix()), []).append(item)

    projects: list[dict[str, object]] = []
    claimed: set[str] = set()
    for item in artifacts:
        if item.kind != "project":
            continue
        directory = str(Path(item.path).parent.as_posix())
        siblings = by_directory.get(directory, [])
        schematics = tuple(s for s in siblings if s.kind == "schematic")
        boards = tuple(s for s in siblings if s.kind == "board")
        other = tuple(
            s for s in siblings if s.kind not in {"schematic", "board", "project"}
        )
        claimed.update(s.path for s in (*schematics, *boards, *other))
        claimed.add(item.path)
        projects.append(
            ProjectSpec(
                name=Path(item.path).stem,
                project_file=item.path,
                schematics=schematics,
                boards=boards,
                other=other,
            ).to_dict()
        )

    unbound = [item.to_dict() for item in artifacts if item.path not in claimed]
    return {
        "root": Path(root).resolve().as_posix(),
        "artifact_count": len(artifacts),
        "truncated": truncated,
        "max_files": max_files,
        "project_count": len(projects),
        "projects": sorted(projects, key=lambda row: str(row["project_file"])),
        "unbound": unbound,
    }
