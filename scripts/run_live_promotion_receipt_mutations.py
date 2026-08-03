from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kairos" / "gated_writes.py"
TESTS = (
    "tests/kernel/test_live_promotion_seam.py",
    "tests/kernel/test_live_promotion_seam_review.py",
    "tests/kernel/test_live_promotion_receipts.py",
    "tests/kernel/test_primary_checkout_fingerprint.py",
    "tests/kernel/test_live_promotion_legacy_retirement.py",
    "tests/kernel/test_promotion_receipts.py",
    "tests/kernel/test_promotion_receipts_review.py",
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
        sys.stderr.write("focused baseline failed\n" + baseline.stdout + baseline.stderr)
        return 2

    mutations = [
        (
            "accept-noncanonical-promotion-ledger",
            "    if not isinstance(promotion_ledger, PromotionLedger):\n",
            "    if False:\n",
        ),
        (
            "reexecute-pending-or-terminal-start",
            "            if not begin_result.execute:\n",
            "            if False:\n",
        ),
        (
            "allow-dirty-primary-before-start",
            "            if not primary_clean:\n",
            "            if False:\n",
        ),
        (
            "ignore-primary-checkout-mutation",
            "            primary_unchanged = (\n",
            "            primary_unchanged = True or (\n",
        ),
        (
            "skip-terminal-readback",
            "            persisted = promotion_ledger.verify_receipt(completion)\n",
            "            persisted = completion\n",
        ),
    ]

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
        raise RuntimeError("mutation runner failed to restore source bytes")
    print("killed mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
