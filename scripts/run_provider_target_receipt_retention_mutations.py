from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/runtimes/provider_target_receipt_ledger.py"
TESTS = (
    "tests/runtimes/test_provider_target_receipt_ledger.py",
    "tests/runtimes/test_provider_target_receipt_ledger_review.py",
)
MUTATIONS = {
    "skip-receipt-authentication": (
        "            projection = verify_provider_target_verification_receipt(\n",
        "            projection = None or verify_provider_target_verification_receipt(\n",
    ),
    "allow-primary-cas-overlap": (
        "    if _paths_overlap(primary, store_root):\n",
        "    if False and _paths_overlap(primary, store_root):\n",
    ),
    "allow-multiple-retention-intents": (
        "        if len(rows) != 1:\n",
        "        if False and len(rows) != 1:\n",
    ),
    "publish-before-intent": (
        "        existing = _read_intent(self.spine.path, key)\n",
        "        self.source_store.put_bytes(payload)\n        existing = _read_intent(self.spine.path, key)\n",
    ),
    "trust-completed-without-cas-readback": (
        "        try:\n            retained = self.source_store.read_bytes(\n",
        "        return\n        try:\n            retained = self.source_store.read_bytes(\n",
    ),
    "accept-terminal-failure": (
        "            if state == STATE_FAILED:\n",
        "            if False and state == STATE_FAILED:\n",
    ),
    "remove-receipt-unique-index": (
        "                    f\"CREATE UNIQUE INDEX IF NOT EXISTS {_UNIQUE_INDEX} \"\n",
        "                    f\"CREATE INDEX IF NOT EXISTS {_UNIQUE_INDEX} \"\n",
    ),
}


def _run_tests() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    baseline = _run_tests()
    if baseline.returncode != 0:
        print("baseline failed; refusing mutation claims")
        print(baseline.stdout)
        return 2

    survived: list[str] = []
    try:
        for name, (needle, replacement) in MUTATIONS.items():
            if original.count(needle) != 1:
                print(f"{name}: mutation needle is not unique")
                survived.append(name)
                continue
            TARGET.write_text(original.replace(needle, replacement), encoding="utf-8")
            result = _run_tests()
            if result.returncode == 0:
                print(f"SURVIVED: {name}")
                survived.append(name)
            else:
                print(f"KILLED: {name}")
            TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")

    if TARGET.read_text(encoding="utf-8") != original:
        print("source restoration failed")
        return 3
    if survived:
        print("surviving mutations: " + ", ".join(survived))
        return 1
    print(f"all {len(MUTATIONS)} bounded mutations killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
