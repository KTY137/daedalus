from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "promotion_effect_entry.py"
TESTS = (
    "tests/kernel/test_promotion_effect_entry.py",
    "tests/kernel/test_promotion_effect_entry_review.py",
)
MUTATIONS = (
    (
        "ignore-retained-promotion-before-lease",
        "        if retained_promotion is not None:\n"
        "            raise PromotionEffectEntryMismatch(\n"
        "                \"promotion execution exists before exact Effect-Lease persistence\"\n"
        "            )\n",
        "        if False:  # mutant ignores retained promotion\n"
        "            raise PromotionEffectEntryMismatch(\n"
        "                \"promotion execution exists before exact Effect-Lease persistence\"\n"
        "            )\n",
    ),
    (
        "begin-before-grant",
        "    capability.grant()\n"
        "    begun = capability.begin()\n",
        "    begun = capability.begin()  # mutant starts before grant\n"
        "    capability.grant()\n",
    ),
    (
        "execute-on-replayed-start",
        "    if not begun.execute:\n"
        "        return _route_nonexecuting(capability, promotion_ledger, after)\n",
        "    if False:  # mutant treats exact replay as fresh execution\n"
        "        return _route_nonexecuting(capability, promotion_ledger, after)\n",
    ),
    (
        "ignore-poststart-promotion-race",
        "        or after.promotion is not None\n",
        "        or False  # mutant ignores existing promotion start\n",
    ),
    (
        "ignore-lease-identity-collision",
        "    if (\n"
        "        str(row[\"lease_sha256\"]) != capability.authorization.lease.digest\n"
        "        or str(row[\"lease_id\"]) != capability.authorization.lease.lease_id\n"
        "    ):\n"
        "        raise PromotionEffectEntryMismatch(\n"
        "            \"persisted Effect-Lease identity collides with another authority\"\n"
        "        )\n",
        "    if False:  # mutant accepts digest/id collision\n"
        "        raise PromotionEffectEntryMismatch(\n"
        "            \"persisted Effect-Lease identity collides with another authority\"\n"
        "        )\n",
    ),
    (
        "route-pending-as-execute",
        "        return PromotionEffectEntryResult(\n"
        "            action=\"pending_reconciliation\",\n"
        "            decision=decision,\n"
        "        )\n",
        "        return PromotionEffectEntryResult(\n"
        "            action=\"execute_promotion\",  # mutant re-executes pending\n"
        "            decision=decision,\n"
        "            start_receipt=decision.effect.start_receipt,\n"
        "        )\n",
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
        sys.stderr.write("baseline failed before promotion-entry mutations\n")
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
            TARGET.write_text(original.replace(needle, replacement, 1), encoding="utf-8")
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
    print(f"all {len(MUTATIONS)} promotion-entry mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
