from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "daedalus" / "runtimes" / "provider_observation_store.py"
TESTS = (
    "tests/runtimes/test_provider_observation_store.py",
    "tests/runtimes/test_provider_observation_store_review.py",
)
MUTATIONS = (
    (
        "accept-overlapping-attempt-and-primary-roots",
        "    if _roots_overlap(attempt_root, primary_root):\n",
        "    if False:  # mutant: accept overlapping authority roots\n",
    ),
    (
        "accept-target-outside-attempt-root",
        "    if not _is_within(parent, attempt_root):\n",
        "    if False:  # mutant: accept target outside attempt root\n",
    ),
    (
        "accept-hard-link-alias",
        "    if result.st_nlink != 1:\n",
        "    if False:  # mutant: accept a hard-link alias\n",
    ),
    (
        "accept-sqlite-sidecars",
        "        if os.path.lexists(Path(str(path) + suffix)):\n",
        "        if False:  # mutant: accept pre-existing sidecars\n",
    ),
    (
        "allow-create-capable-normal-open",
        "    if mode not in {\"ro\", \"rw\"}:\n",
        "    if mode not in {\"ro\", \"rw\", \"rwc\"}:  # mutant\n",
    ),
    (
        "detach-persisted-target-digest",
        "            or str(row[1]) != target.digest\n",
        "            or False  # mutant: ignore target digest\n",
    ),
    (
        "detach-persisted-source-revision",
        "            or str(row[2]) != target.source_revision\n",
        "            or False  # mutant: ignore source revision\n",
    ),
    (
        "accept-store-identity-replacement",
        "        if status.identity != self._store_identity:\n",
        "        if False:  # mutant: accept replacement inode\n",
    ),
    (
        "route-replay-through-writer",
        "            connection = self._connect_read_only()\n",
        "            connection = self._connect()  # mutant: replay opens writer\n",
    ),
    (
        "replace-no-clobber-publication",
        "        os.link(temporary, path)\n",
        "        os.replace(temporary, path)  # mutant: clobber-capable publish\n",
    ),
    (
        "retain-staging-hard-link-alias",
        "        temporary.unlink()\n        _fsync_file(path)\n",
        "        pass  # mutant: retain staging alias\n        _fsync_file(path)\n",
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
        sys.stderr.write("baseline failed before provider-store mutations\n")
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
    print(f"all {len(MUTATIONS)} provider-store mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
