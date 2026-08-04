from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "promotion_recovery_consumption.py"
TESTS = (
    "tests/kernel/test_promotion_recovery_consumption.py",
    "tests/kernel/test_promotion_recovery_consumption_review.py",
)
MUTATIONS = (
    (
        "use-deferred-transaction",
        '            connection.execute("BEGIN IMMEDIATE")\n',
        '            connection.execute("BEGIN")  # mutant\n',
    ),
    (
        "skip-transaction-state-verification",
        "            verified = verify_promotion_recovery_decision(\n"
        "                decision,\n"
        "                keyring=keyring,\n"
        "                capability=capability,\n"
        "                promotion_ledger=promotion_ledger,\n"
        "                now=transaction_at,\n"
        "            )\n",
        "            verified = preflight  # mutant\n",
    ),
    (
        "ignore-authority-change-before-persistence",
        "            if verified != preflight or expectation != preflight_expectation:\n",
        "            if False:  # mutant\n",
    ),
    (
        "ignore-persistence-expiry",
        "            if consumed_at >= verified.expires_at:\n",
        "            if False:  # mutant\n",
    ),
    (
        "allow-second-decision-for-same-promotion",
        "                    promotion_authorization_sha256 TEXT NOT NULL UNIQUE,\n",
        "                    promotion_authorization_sha256 TEXT NOT NULL,  -- mutant\n",
    ),
    (
        "skip-persisted-signature-check",
        "        if not hmac.compare_digest(\n"
        "            stored_decision.signature_sha256,\n"
        "            _signature(stored_decision.signing_digest, secret),\n"
        "        ):\n",
        "        if False:  # mutant\n",
    ),
    (
        "ignore-redundant-operation-column",
        '            or row["operation"] != stored_verified.operation\n',
        "",
    ),
    (
        "accept-extra-consumption-fields",
        "        if actual != expected:\n",
        "        if False:  # mutant accepts unbound fields\n",
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
    original = TARGET.read_text(encoding="utf-8")
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("baseline failed before recovery-consumption mutations\n")
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
            TARGET.write_text(
                original.replace(needle, replacement, 1),
                encoding="utf-8",
            )
            result = _run()
            if result.returncode == 0:
                survivors.append(name)
                sys.stderr.write(f"SURVIVED: {name}\n")
            else:
                print(f"killed: {name}")
            TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")

    if survivors:
        sys.stderr.write("surviving mutations: " + ", ".join(survivors) + "\n")
        return 1
    print(f"all {len(MUTATIONS)} recovery-consumption mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
