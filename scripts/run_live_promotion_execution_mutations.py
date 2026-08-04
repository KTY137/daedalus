from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TESTS = (
    "tests/kernel/test_live_promotion_seam.py",
    "tests/kernel/test_live_promotion_seam_review.py",
    "tests/kernel/test_live_promotion_execution_adversarial.py",
    "tests/kernel/test_live_promotion_fault_identity_review.py",
    "tests/kernel/test_promotion_fingerprint.py",
    "tests/kernel/test_promotion_execution.py",
)


@dataclass(frozen=True)
class Mutation:
    label: str
    target: Path
    old: str
    new: str


def _run() -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", *TESTS],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def _replace_once(source: str, mutation: Mutation) -> str:
    count = source.count(mutation.old)
    if count != 1:
        raise RuntimeError(
            f"{mutation.label}: expected one mutation site, found {count}"
        )
    return source.replace(mutation.old, mutation.new, 1)


def main() -> int:
    seam = ROOT / "daedalus" / "kairos" / "gated_writes.py"
    fingerprint = ROOT / "daedalus" / "kernel" / "promotion_fingerprint.py"
    originals = {path: path.read_bytes() for path in (seam, fingerprint)}
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("live promotion execution mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    mutations = (
        Mutation(
            "allow-missing-execution-ledger",
            seam,
            "        or not isinstance(promotion_execution_ledger, PromotionExecutionLedger)\n",
            "        or False\n",
        ),
        Mutation(
            "reexecute-pending-or-terminal-promotion",
            seam,
            "    if not begin.execute:\n",
            "    if False:\n",
        ),
        Mutation(
            "accept-substituted-live-authorization",
            seam,
            "            if live_authorization.authorization_sha256 != authorization.authorization_sha256:\n",
            "            if False:\n",
        ),
        Mutation(
            "regenerate-stale-owner-approved-candidate",
            seam,
            "            if artifact.base_revision != live_authorization.live_target_revision:\n",
            "            if False:\n",
        ),
        Mutation(
            "misclassify-post-mutation-authorization-error",
            seam,
            "    except PromotionAuthorizationError as exc:\n        if mutation_entered:\n",
            "    except PromotionAuthorizationError as exc:\n        if False:\n",
        ),
        Mutation(
            "forget-created-branch-on-revision-lookup-fault",
            seam,
            "            report=report,\n            integration_branch=integration_branch,\n            integration_revision=integration_revision,\n        )\n\n    try:\n        primary_after",
            "        )\n\n    try:\n        primary_after",
        ),
        Mutation(
            "copy-raw-report-into-fault-receipt",
            seam,
            '        "observed_report": report is not None,\n',
            '        "observed_report": report,\n',
        ),
        Mutation(
            "release-result-without-after-fingerprint",
            seam,
            "    try:\n        primary_after = fingerprint_primary_checkout(root)\n        completion = promotion_execution_ledger.complete(\n",
            "    try:\n        primary_after = begin.start.primary_checkout_before_sha256\n        completion = promotion_execution_ledger.complete(\n",
        ),
        Mutation(
            "trust-redirected-checkout-root",
            fingerprint,
            "        if stat.S_ISLNK(submitted_metadata.st_mode):\n",
            "        if False:\n",
        ),
        Mutation(
            "include-control-state-in-primary-identity",
            fingerprint,
            "        if relative.parts and relative.parts[0].casefold() in _EXCLUDED_ROOTS:\n",
            "        if False:\n",
        ),
    )

    killed: list[str] = []
    try:
        for mutation in mutations:
            original = originals[mutation.target]
            source = original.decode("utf-8")
            mutation.target.write_text(
                _replace_once(source, mutation),
                encoding="utf-8",
            )
            result = _run()
            if result.returncode == 0:
                sys.stderr.write(f"survived mutation: {mutation.label}\n")
                sys.stderr.write(result.stdout + result.stderr)
                return 1
            killed.append(mutation.label)
            mutation.target.write_bytes(original)
    finally:
        for path, original in originals.items():
            path.write_bytes(original)

    for path, original in originals.items():
        if path.read_bytes() != original:
            raise RuntimeError(f"mutation runner failed to restore {path}")
    print("killed mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
