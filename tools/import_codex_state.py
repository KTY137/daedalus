"""Safely import offline Codex sessions and memories from another machine.

Dry-run is the default. This intentionally is not a general CODEX_HOME sync:
credentials, config, logs, SQLite state, caches, and temporary directories are
outside the allowlist. Stop Codex on the source machine and make its CODEX_HOME
available as a local/mounted directory before applying.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


# A checked-out tool is commonly launched as ``python tools/<name>.py``. In
# that mode Python only adds ``tools/`` to sys.path, so bind the repository root
# explicitly before importing the canonical Daedalus effect boundary.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


MEMORY_FILES = frozenset({"MEMORY.md", "memory_summary.md", "raw_memories.md"})
MEMORY_DIRS = frozenset({"extensions", "rollout_summaries"})


@dataclass
class ImportReport:
    source: str
    destination: str
    apply: bool
    copied: list[str]
    identical: list[str]
    conflicts: list[str]
    skipped: list[str]


def _digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _allowed_files(source: Path):
    roots = [source / "sessions"]
    memory = source / "memories"
    for name in sorted(MEMORY_DIRS):
        roots.append(memory / name)
    for root in roots:
        if not root.is_dir() or root.is_symlink():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and not path.is_symlink():
                yield path, path.relative_to(source)
    for name in sorted(MEMORY_FILES):
        path = memory / name
        if path.is_file() and not path.is_symlink():
            yield path, path.relative_to(source)


def import_state(source: Path, destination: Path, *, apply: bool = False) -> ImportReport:
    source = source.resolve()
    destination = destination.resolve()
    if source == destination:
        raise ValueError("source and destination CODEX_HOME are the same directory")
    if not source.is_dir():
        raise ValueError(f"source CODEX_HOME does not exist: {source}")
    if not destination.is_dir():
        raise ValueError(f"destination CODEX_HOME does not exist: {destination}")

    report = ImportReport(str(source), str(destination), apply, [], [], [], [])
    for incoming, relative in _allowed_files(source):
        target = destination / relative
        rel = relative.as_posix()
        if target.exists():
            if not target.is_file() or target.is_symlink():
                report.conflicts.append(rel)
            elif _digest(incoming) == _digest(target):
                report.identical.append(rel)
            else:
                report.conflicts.append(rel)
            continue
        report.copied.append(rel)
        if apply:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(incoming, target)
    return report


def main() -> int:
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "tools.codex_state_import",
        REGISTRY_BY_ID["tools.codex_state_import"].effects,
        (process_guard_boundary_decision(),),
    )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="offline/mounted laptop CODEX_HOME")
    parser.add_argument("destination", type=Path, help="this host's existing CODEX_HOME")
    parser.add_argument("--apply", action="store_true", help="copy missing allowlisted files")
    args = parser.parse_args()
    try:
        report = import_state(args.source, args.destination, apply=args.apply)
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(asdict(report), indent=2, ensure_ascii=False))
    return 2 if report.conflicts else 0


if __name__ == "__main__":
    raise SystemExit(main())
