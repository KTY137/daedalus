from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "promotion_receipts.py"
TESTS = (
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

    mutations: list[tuple[str, str, str]] = [
        (
            "accept-forged-authorization-digest",
            "    if authorization_sha256 != canonical_sha(authorization_body):\n",
            "    if False:\n",
        ),
        (
            "execute-on-start-replay",
            "                        start=existing[0], execute=False, completion=completion\n",
            "                        start=existing[0], execute=True, completion=completion\n",
        ),
        (
            "allow-primary-checkout-mutation",
            "            and self.outcome != \"faulted\"\n",
            "            and False\n",
        ),
        (
            "ignore-persisted-receipt-digest",
            "        if receipt.digest != str(row[\"receipt_sha256\"]):\n",
            "        if False:\n",
        ),
        (
            "allow-success-without-integration-identity",
            "        if self.outcome == \"succeeded\" and (\n",
            "        if False and (\n",
        ),
        (
            "allow-empty-success-report",
            "        if len(promoted) != 1 or refused or not_gated:\n",
            "        if False:\n",
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
