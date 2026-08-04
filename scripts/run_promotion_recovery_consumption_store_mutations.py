from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (
    ROOT
    / "daedalus"
    / "kernel"
    / "promotion_recovery_consumption_store.py"
)
TESTS = (
    "tests/test_promotion_recovery_consumption_store.py",
    "tests/test_promotion_recovery_consumption_store_review.py",
)
MUTATIONS = (
    (
        "allow-create-on-normal-writer-open",
        '        mode = "ro" if read_only else "rw"\n',
        '        mode = "ro" if read_only else "rwc"  # mutant\n',
    ),
    (
        "skip-preexisting-target-refusal",
        "    if os.path.lexists(target):\n",
        "    if False:  # mutant: ignore an existing target\n",
    ),
    (
        "replace-target-during-publication",
        "            os.link(temporary, target)\n",
        "            os.replace(temporary, target)  # mutant\n",
    ),
    (
        "accept-store-identity-substitution",
        "        if status.identity != self._store_identity:\n",
        "        if False:  # mutant: accept substituted store identity\n",
    ),
    (
        "accept-table-sql-drift",
        "        if not isinstance(object_sql, str) or _normalized_sql(object_sql) != (\n",
        "        if False and (not isinstance(object_sql, str) or _normalized_sql(object_sql) != (\n",
    ),
    (
        "accept-nullability-drift",
        "        if tuple(int(row[3]) for row in table_rows) != (1,) * len(_COLUMNS):\n",
        "        if False:  # mutant: accept nullable columns\n",
    ),
    (
        "accept-unique-index-drift",
        "        if projected_contract != _UNIQUE_INDEX_CONTRACT:\n",
        "        if False:  # mutant: accept unique-index drift\n",
    ),
    (
        "unlink-foreign-replacement-during-cleanup",
        "    if current_identity != published_identity:\n        return\n",
        "    if False:  # mutant: unlink even when target identity changed\n        return\n",
    ),
    (
        "skip-preopen-store-verification",
        "        status = inspect_promotion_recovery_consumption_store(self.path)\n        self._require_same_store(status)\n        mode = \"ro\" if read_only else \"rw\"\n",
        "        status = self.store_status  # mutant: no explicit pre-open inspection\n        mode = \"ro\" if read_only else \"rw\"\n",
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
        sys.stderr.write("baseline failed before recovery-store mutations\n")
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
    print(f"all {len(MUTATIONS)} recovery-store mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
