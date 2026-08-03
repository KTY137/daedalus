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

    mutations: list[tuple[str, str, str]] = [
        (
            "execute-pending-replay",
            "            if not begin.execute:\n",
            "            if False:\n",
        ),
        (
            "ignore-primary-checkout-mutation",
            "    if primary_before != primary_after:\n",
            "    if False:\n",
        ),
        (
            "single-sample-primary-fingerprint",
            "    second = _primary_inventory(root)\n",
            "    second = first\n",
        ),
        (
            "randomize-integration-branch",
            "    return f\"kairos-integration-{authorization.authorization_sha256[:40]}\"\n",
            "    return f\"kairos-integration-{uuid.uuid4().hex}\"\n",
        ),
        (
            "omit-promotion-ledger-authority",
            "    if approval_ledger is None or promotion_ledger is None or not owner_keyring:\n",
            "    if approval_ledger is None or not owner_keyring:\n",
        ),
        (
            "retry-pending-mutation",
            "                return _reconcile_pending(\n",
            "                begin = type('Replay', (), {'execute': True, 'start': begin.start})()\n                if False:\n                    return _reconcile_pending(\n",
        ),
    ]

    killed: list[str] = []
    try:
        for label, old, new in mutations:
            mutated = _replace_once(source, old, new, label)
            TARGET.write_text(mutated, encoding="utf-8")
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
