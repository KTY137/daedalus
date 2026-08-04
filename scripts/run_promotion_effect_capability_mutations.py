from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "promotion_effects.py"
TESTS = (
    "tests/kernel/test_promotion_effect_capability.py",
    "tests/kernel/test_promotion_effect_capability_review.py",
)
MUTATIONS = (
    (
        "accept-noncentral-row",
        "        if row.wiring is not Wiring.CENTRAL:\n"
        "            row_mismatches.append(\"wiring\")\n",
        "        if False:  # mutant accepts a non-central promotion row\n"
        "            row_mismatches.append(\"wiring\")\n",
    ),
    (
        "drop-promotion-provenance-binding",
        "        if missing_inputs:\n"
        "            raise PromotionEffectBindingMismatch(\n"
        "                \"effect lease request provenance does not bind the promotion subject: \"\n"
        "                + \", \".join(missing_inputs)\n"
        "            )\n",
        "        if False:  # mutant accepts detached promotion provenance\n"
        "            raise PromotionEffectBindingMismatch(\n"
        "                \"effect lease request provenance does not bind the promotion subject: \"\n"
        "                + \", \".join(missing_inputs)\n"
        "            )\n",
    ),
    (
        "detach-idempotency-key",
        "            \"idempotency_key\": (\n"
        "                self.execution.idempotency_key,\n"
        "                promotion_digest,\n"
        "            ),\n",
        "            \"idempotency_key\": (\n"
        "                self.execution.idempotency_key,\n"
        "                self.execution.idempotency_key,\n"
        "            ),\n",
    ),
    (
        "drop-owner-consumption-evidence",
        "        if guards[\"promotion.owner_approval\"].evidence != expected_owner_evidence:\n"
        "            raise PromotionEffectBindingMismatch(\n"
        "                \"owner-approval guard evidence does not bind approval consumption\"\n"
        "            )\n",
        "        if False:  # mutant accepts detached owner evidence\n"
        "            raise PromotionEffectBindingMismatch(\n"
        "                \"owner-approval guard evidence does not bind approval consumption\"\n"
        "            )\n",
    ),
    (
        "allow-hidden-egress",
        "        if scope.egress_endpoints or self.execution.egress_endpoints:\n"
        "            hidden_authority.append(\"egress\")\n",
        "        if False:  # mutant accepts hidden egress authority\n"
        "            hidden_authority.append(\"egress\")\n",
    ),
    (
        "allow-missing-git",
        "        if \"git\" not in scope.tools or \"git\" not in self.execution.tools:\n"
        "            hidden_authority.append(\"git_tool\")\n",
        "        if False:  # mutant accepts a promotion without git binding\n"
        "            hidden_authority.append(\"git_tool\")\n",
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
        sys.stderr.write("baseline failed before promotion-capability mutations\n")
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
    print(f"all {len(MUTATIONS)} promotion-capability mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
