from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kairos" / "promotion_manager_replay.py"
TESTS = (
    "tests/kernel/test_promotion_manager_replay.py",
    "tests/kernel/test_promotion_manager_replay_review.py",
    "tests/kernel/test_promotion_manager_installation.py",
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
        sys.stderr.write("promotion manager replay mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    mutations = (
        (
            "trust-manager-audit-digest",
            "    if digest != canonical_sha(audit):\n",
            "    if False:\n",
        ),
        (
            "trust-report-receipt-branch-substitution",
            "    if report_branch != receipt.integration_branch:\n",
            "    if False:\n",
        ),
        (
            "trust-report-receipt-revision-substitution",
            "    if report_revision != receipt.integration_revision:\n",
            "    if False:\n",
        ),
        (
            "accept-success-without-retained-action",
            '        if _reaper_action(audit, branch) != "retained":\n',
            "        if False:\n",
        ),
        (
            "accept-refusal-with-pending-branch",
            '        if _reaper_action(audit, branch) not in {"deleted", "absent"}:\n',
            "        if False:\n",
        ),
        (
            "accept-fault-identity-not-matching-allocation",
            "        if receipt.integration_branch != branch or receipt.integration_revision is None:\n",
            "        if False:\n",
        ),
        (
            "trust-invalid-replay-completion",
            "        except PromotionManagerReplayError:\n            return replace(result, execute=False, completion=None)\n",
            "        except PromotionManagerReplayError:\n            return result\n",
        ),
        (
            "drop-manager-audit-report-binding",
            '        enriched["manager_audit"] = snapshot.to_dict()\n',
            '        enriched["manager_audit"] = {}\n',
        ),
        (
            "drop-manager-audit-digest-binding",
            '        enriched["manager_audit_sha256"] = snapshot.digest\n',
            '        enriched["manager_audit_sha256"] = "0" * 64\n',
        ),
        (
            "do-not-fix-terminal-branch-field",
            '        enriched["integration_branch"] = assessed_branch\n',
            '        enriched["integration_branch"] = integration_branch\n',
        ),
        (
            "do-not-fix-terminal-revision-field",
            '        enriched["integration_revision"] = assessed_revision\n',
            '        enriched["integration_revision"] = integration_revision\n',
        ),
        (
            "retain-non-replay-ledger-proxy",
            "    state.ledger_wrapper = _ReplayAuditedExecutionLedger\n",
            "    state.ledger_wrapper = manager_boundary._AuditedExecutionLedger\n",
        ),
        (
            "replace-public-ledger-class",
            '    namespace["_MANAGER_AUDIT_V1_LEDGER_TYPE"] = ledger_type\n',
            '    namespace["PromotionExecutionLedger"] = _ReplayAuditedExecutionLedger\n    namespace["_MANAGER_AUDIT_V1_LEDGER_TYPE"] = ledger_type\n',
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
        raise RuntimeError("replay mutation runner failed to restore source")
    print("killed promotion-manager replay mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
