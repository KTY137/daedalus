from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "promotion_recovery_decision.py"
TESTS = (
    "tests/kernel/test_promotion_recovery_decision.py",
    "tests/kernel/test_promotion_recovery_decision_review.py",
)
MUTATIONS = (
    (
        "skip-plan-digest-verification",
        "    _verify_plan_digest(plan)\n",
        "    pass  # mutant skips recovery plan digest verification\n",
    ),
    (
        "accept-automatic-reexecution-plan",
        "        or plan.automatic_external_reexecution is not False\n",
        "        or False  # mutant accepts automatic reexecution claim\n",
    ),
    (
        "trust-declared-promotion-authorization-digest",
        "        authorization_digest = _promotion_authorization_digest(authorization)\n",
        "        authorization_digest = authorization.authorization_sha256  # mutant\n",
    ),
    (
        "skip-signature-comparison",
        "    if not hmac.compare_digest(decision.signature_sha256, expected_signature):\n",
        "    if False:  # mutant accepts forged owner signature\n",
    ),
    (
        "skip-recovery-plan-subject-comparison",
        '        "recovery_plan_sha256": (\n            decision.recovery_plan_sha256,\n            expectation.recovery_plan_sha256,\n        ),\n',
        "",
    ),
    (
        "skip-source-revision-comparison",
        '        "source_revision": (\n            decision.provenance.source_revision,\n            expectation.source_revision,\n        ),\n',
        "",
    ),
    (
        "allow-overlong-recovery-decision",
        "    if expires - issued > _MAX_RECOVERY_DECISION_TTL:\n",
        "    if False:  # mutant removes Gate-0 recovery TTL\n",
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
        sys.stderr.write("baseline failed before recovery-decision mutations\n")
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
    print(f"all {len(MUTATIONS)} recovery-decision mutations were killed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
