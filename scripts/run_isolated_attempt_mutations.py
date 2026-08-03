from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "attempts.py"
TESTS = (
    "tests/kernel/test_isolated_attempt_lifecycle.py",
    "tests/kernel/test_isolated_attempt_lifecycle_adversarial.py",
    "tests/kernel/test_isolated_attempt_lifecycle_review.py",
    "tests/kernel/test_source_tree_store.py",
    "tests/kernel/test_source_tree_store_adversarial.py",
)


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one mutation site, found {count}")
    return source.replace(old, new, 1)


def main() -> int:
    original = TARGET.read_bytes()
    source = original.decode("utf-8")
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("isolated-attempt mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    mutations = (
        (
            "reexecute-pending-or-terminal-attempt",
            "        if not begin.execute:\n            return PreparedAttempt(begin=begin, workspace=None)\n",
            "        if False:\n            return PreparedAttempt(begin=begin, workspace=None)\n",
        ),
        (
            "allow-coordinator-ledger-store-substitution",
            "        if ledger.source_store is not source_store:\n",
            "        if False:\n",
        ),
        (
            "accept-start-replay-with-changed-subject",
            "                    if not persisted.same_subject(start):\n",
            "                    if False:\n",
        ),
        (
            "allow-success-without-candidate-tree",
            "        if self.outcome == \"succeeded\" and self.candidate_tree is None:\n",
            "        if False:\n",
        ),
        (
            "terminalize-process-abort-as-known-fault",
            "        except Exception as exc:\n",
            "        except BaseException as exc:\n",
        ),
        (
            "skip-terminal-report-cas-check",
            "        self.source_store.read_bytes(report, max_bytes=_MAX_REPORT_BYTES)\n        candidate_ref = None\n",
            "        candidate_ref = None\n",
        ),
        (
            "skip-input-tree-cas-check-in-ledger",
            "        loaded = self.source_store.load_tree(input_tree.ref)\n        if loaded != input_tree.manifest:\n            raise AttemptBindingMismatch(\n                \"input tree manifest differs from the ledger CAS object\"\n            )\n",
            "        loaded = input_tree.manifest\n",
        ),
    )

    killed: list[str] = []
    try:
        for label, old, new in mutations:
            TARGET.write_text(
                _replace_once(source, old, new, label),
                encoding="utf-8",
            )
            result = _run()
            if result.returncode == 0:
                sys.stderr.write(f"survived mutation: {label}\n")
                return 1
            killed.append(label)
            TARGET.write_bytes(original)
    finally:
        TARGET.write_bytes(original)

    if TARGET.read_bytes() != original:
        raise RuntimeError("mutation runner failed to restore attempt source")
    print("killed mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
