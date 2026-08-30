# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "promotion_execution.py"
TESTS = (
    "tests/kernel/test_promotion_execution.py",
    "tests/kernel/test_promotion_execution_adversarial.py",
    "tests/kernel/test_promotion_execution_review.py",
    "tests/kernel/test_promotion_execution_index_review.py",
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
        sys.stderr.write("promotion execution mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    mutations = (
        (
            "trust-declared-authorization-digest",
            "    if declared != canonical_sha(body):\n",
            "    if False:\n",
        ),
        (
            "drop-event-time-skew-refusal",
            "    if event - record > _MAX_EVENT_TIME_SKEW:\n",
            "    if False:\n",
        ),
        (
            "accept-substituted-report-authorization",
            '    if canonical.get("authorization") != expected_authorization:\n',
            "    if False:\n",
        ),
        (
            "accept-success-after-primary-checkout-mutation",
            "        if primary_changed:\n            raise PromotionExecutionBindingMismatch(\n                \"successful promotion changed the primary checkout\"\n            )\n",
            "        if False:\n            raise PromotionExecutionBindingMismatch(\n                \"successful promotion changed the primary checkout\"\n            )\n",
        ),
        (
            "terminal-receipt-does-not-bind-start",
            "        if receipt.start_sha256 != start.digest:\n",
            "        if False:\n",
        ),
        (
            "launder-changed-start-id-as-replay",
            '        ignored = {"started_at", "provenance"}\n',
            '        ignored = {"start_id", "started_at", "provenance"}\n',
        ),
        (
            "accept-completion-before-start",
            "        if _parse_utc(receipt.completed_at, \"completed_at\") < _parse_utc(\n",
            "        if False and _parse_utc(receipt.completed_at, \"completed_at\") < _parse_utc(\n",
        ),
        (
            "accept-non-finite-report-value-at-first-boundary",
            "        if not math.isfinite(value):\n",
            "        if False:\n",
        ),
        (
            "coerce-non-string-report-key-at-first-boundary",
            "            if not isinstance(key, str):\n",
            "            if False:\n",
        ),
        (
            "drop-canonical-round-trip-equality",
            "    if parsed != decoded:\n",
            "    if False:\n",
        ),
        (
            "drop-one-start-unique-index",
            '                    "CREATE UNIQUE INDEX IF NOT EXISTS "\n',
            '                    "CREATE INDEX IF NOT EXISTS "\n',
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
                sys.stderr.write(result.stdout + result.stderr)
                return 1
            killed.append(label)
            TARGET.write_bytes(original)
    finally:
        TARGET.write_bytes(original)

    if TARGET.read_bytes() != original:
        raise RuntimeError("mutation runner failed to restore production source")
    print("killed mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
