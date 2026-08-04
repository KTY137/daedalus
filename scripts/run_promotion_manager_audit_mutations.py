from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "daedalus" / "kairos" / "promotion_manager_audit.py"
BOUNDARY = ROOT / "daedalus" / "kairos" / "promotion_manager_boundary.py"
TESTS = (
    "tests/kernel/test_promotion_manager_audit.py",
    "tests/kernel/test_promotion_manager_boundary.py",
    "tests/kernel/test_promotion_manager_boundary_review.py",
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
    originals = {AUDIT: AUDIT.read_bytes(), BOUNDARY: BOUNDARY.read_bytes()}
    baseline = _run()
    if baseline.returncode != 0:
        sys.stderr.write("promotion manager audit mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    mutations = (
        (
            AUDIT,
            "launder-multiple-reaper-rows",
            "        if len(matches) != 1 or not isinstance(matches[0].get(\"action\"), str):\n",
            "        if False or not isinstance(matches[0].get(\"action\"), str):\n",
        ),
        (
            AUDIT,
            "drop-allocation-failure-status",
            '                        status="failed",\n                        error=_error_record(exc),\n',
            '                        status="succeeded",\n                        worktree_path="unknown",\n',
        ),
        (
            AUDIT,
            "drop-cleanup-failure-status",
            '                        status="failed",\n                        error=_error_record(exc),\n',
            '                        status="succeeded",\n',
        ),
        (
            AUDIT,
            "drop-reaper-failure-status",
            '                        status="failed",\n                        error=_error_record(exc),\n',
            '                        status="succeeded",\n                        result=(),\n',
        ),
        (
            AUDIT,
            "collapse-audit-digest",
            "        return canonical_sha(self.to_dict())\n",
            '        return "0" * 64\n',
        ),
        (
            BOUNDARY,
            "treat-pending-refusal-branch-as-absent",
            '        if action in {"deleted", "absent"}:\n',
            '        if action in {"deleted", "absent", "pending"}:\n',
        ),
        (
            BOUNDARY,
            "drop-success-reaper-action-check",
            '        if action != "retained":\n',
            "        if False:\n",
        ),
        (
            BOUNDARY,
            "trust-stale-success-revision",
            "        if (\n            integration_revision != current_revision\n            or report.get(\"integration_revision\") != current_revision\n        ):\n",
            "        if False:\n",
        ),
        (
            BOUNDARY,
            "drop-audit-report-binding",
            '        enriched["manager_audit"] = snapshot.to_dict()\n',
            '        enriched["manager_audit"] = {}\n',
        ),
        (
            BOUNDARY,
            "drop-audit-digest-binding",
            '        enriched["manager_audit_sha256"] = snapshot.digest\n',
            '        enriched["manager_audit_sha256"] = "0" * 64\n',
        ),
        (
            BOUNDARY,
            "bypass-completion-assessment",
            "        assessed_outcome, assessed_branch, assessed_revision = _assess_completion(\n",
            "        assessed_outcome, assessed_branch, assessed_revision = outcome, integration_branch, integration_revision\n        if False:\n            _assess_completion(\n",
        ),
        (
            BOUNDARY,
            "launder-untyped-ledger",
            "        if not isinstance(delegate, self.ledger_type):\n",
            "        if False:\n",
        ),
        (
            BOUNDARY,
            "replace-public-ledger-class-with-wrapper",
            '    namespace["PromotionExecutionLedger"] = ledger_type\n',
            '    namespace["PromotionExecutionLedger"] = state.wrap_ledger\n',
        ),
    )

    killed: list[str] = []
    try:
        for target, label, old, new in mutations:
            source = originals[target].decode("utf-8")
            target.write_text(
                _replace_once(source, old, new, label),
                encoding="utf-8",
            )
            result = _run()
            if result.returncode == 0:
                sys.stderr.write(f"survived mutation: {label}\n")
                sys.stderr.write(result.stdout + result.stderr)
                return 1
            killed.append(label)
            target.write_bytes(originals[target])
    finally:
        for target, original in originals.items():
            target.write_bytes(original)

    for target, original in originals.items():
        if target.read_bytes() != original:
            raise RuntimeError(f"mutation runner failed to restore {target}")
    print("killed promotion-manager mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
