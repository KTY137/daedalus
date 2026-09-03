from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "daedalus" / "gates" / "repository" / "write_inventory.py"
TESTS = (
    "tests/gates/test_repository_write_inventory.py",
    "tests/gates/test_repository_write_inventory_cli.py",
    "tests/gates/test_repository_write_inventory_review.py",
    "tests/gates/test_repository_write_inventory_schema.py",
)
MUTATIONS = (
    (
        "launder-filesystem-mutations",
        '_BLOCKING_KINDS = _ALLOWED_KINDS - {"sqlite_read_only"}\n',
        '_BLOCKING_KINDS = _ALLOWED_KINDS - {"sqlite_read_only", "filesystem_mutation"}  # mutant\n',
    ),
    (
        "ignore-write-open-modes",
        '    if any(token in mode for token in "wax+"):\n',
        '    if False:  # mutant: ignore literal write modes\n',
    ),
    (
        "downgrade-git-mutation-kind",
        '            return ("git_mutation_process", f"git {command}")\n',
        '            return ("process_effect_unknown", f"git {command}")  # mutant\n',
    ),
    (
        "accept-nonrevision-label",
        '        or not _SOURCE_REVISION.fullmatch(source_revision)\n',
        '        or False  # mutant: accept any source label\n',
    ),
    (
        "unbind-production-file-bytes",
        '                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),\n',
        '                    "sha256": hashlib.sha256(b"").hexdigest(),  # mutant\n',
    ),
    (
        "drop-expression-method-fallback",
        '                and node.func.attr in (_PATH_METHODS | {"open"})\n',
        '                and False  # mutant: drop expression method calls\n',
    ),
    (
        "launder-sqlite-default-connect",
        '    return ("sqlite_write_or_create", "default-connect")\n',
        '    return ("sqlite_read_only", "default-connect")  # mutant\n',
    ),
    (
        "accept-symlinked-package-root",
        '    if package_root.is_symlink() or not resolved_package.is_dir():\n',
        '    if False:  # mutant: accept redirected package roots\n',
    ),
)


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def main() -> int:
    original = SOURCE.read_text(encoding="utf-8")
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("baseline failed before repository-write mutations\n")
        sys.stderr.write(baseline.stdout)
        sys.stderr.write(baseline.stderr)
        return 2

    survivors: list[str] = []
    try:
        for name, needle, replacement in MUTATIONS:
            count = original.count(needle)
            if count != 1:
                sys.stderr.write(
                    f"mutation {name} expected one source seam, found {count}\n"
                )
                return 3
            SOURCE.write_text(
                original.replace(needle, replacement, 1),
                encoding="utf-8",
            )
            result = _run()
            if result.returncode == 0:
                survivors.append(name)
                sys.stderr.write(f"SURVIVED: {name}\n")
            else:
                print(f"killed: {name}")
            SOURCE.write_text(original, encoding="utf-8")
    finally:
        SOURCE.write_text(original, encoding="utf-8")

    if survivors:
        sys.stderr.write("surviving mutations: " + ", ".join(survivors) + "\n")
        return 1
    print(f"all {len(MUTATIONS)} repository-write mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
