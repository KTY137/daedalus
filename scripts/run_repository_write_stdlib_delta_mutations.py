from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "daedalus" / "gates" / "repository_write_stdlib_delta.py"
TESTS = (
    "tests/gates/test_repository_write_stdlib_delta.py",
    "tests/gates/test_repository_write_stdlib_delta_review.py",
)
MUTATIONS = (
    (
        "ignore-literal-compressed-write-mode",
        "    if any(token in mode for token in write_tokens):\n",
        "    if False:  # mutant: ignore literal write modes\n",
    ),
    (
        "launder-dynamic-compressed-mode",
        "                \"ambiguous_archive_or_compressed_mode\",\n                \"dynamic-mode\",\n",
        "                \"archive_or_compressed_write\",\n                \"read-only\",  # mutant\n",
    ),
    (
        "drop-fd-write-surface",
        '        "os.write",\n',
        '        "os.not_write",  # mutant\n',
    ),
    (
        "drop-async-process-surface",
        '        "asyncio.create_subprocess_exec",\n',
        '        "asyncio.not_create_subprocess_exec",  # mutant\n',
    ),
    (
        "drop-generic-write-sink",
        '    {"write", "writelines", "writerow", "writerows", "truncate"}\n',
        '    {"writelines", "writerow", "writerows", "truncate"}  # mutant\n',
    ),
    (
        "unbind-base-inventory-digest",
        "        base_inventory_digest=base.digest,\n",
        '        base_inventory_digest="0" * 64,  # mutant\n',
    ),
    (
        "claim-canonical-integration",
        '            "canonical_scanner_integrated": False,\n',
        '            "canonical_scanner_integrated": True,  # mutant\n',
    ),
    (
        "claim-delta-closure",
        '            "closed": False,\n',
        '            "closed": True,  # mutant\n',
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
        sys.stderr.write("baseline failed before stdlib-delta mutations\n")
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
    print(f"all {len(MUTATIONS)} stdlib-delta mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
