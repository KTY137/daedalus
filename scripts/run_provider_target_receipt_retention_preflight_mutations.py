"""Bounded mutation campaign for receipt-retention admission preflight."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = Path(
    "daedalus/runtimes/provider_target_receipt_retention_preflight.py"
)
TESTS = (
    "tests/runtimes/test_provider_target_receipt_retention_preflight.py",
    "tests/runtimes/test_provider_target_receipt_retention_preflight_review.py",
)

MUTATIONS = (
    (
        "authority-verification-bypass",
        "        decision = authorize_provider_target_receipt_retention_operation(\n",
        "        decision = GuardDecision(\n",
    ),
    (
        "repository-head-reverification-bypass",
        "        verify_repository_head_revision_receipt(\n",
        "        (lambda *args, **kwargs: None)(\n",
    ),
    (
        "inventory-live-rebuild-bypass",
        "        rebuilt_inventory = scan_provider_target_receipt_retention(\n",
        "        rebuilt_inventory = (lambda *args, **kwargs: inventory)(\n",
    ),
    (
        "inventory-comparison-bypass",
        "    if rebuilt_inventory != inventory or rebuilt_inventory.digest != inventory.digest:\n",
        "    if False:\n",
    ),
    (
        "guard-evidence-comparison-bypass",
        "        or decision.evidence != expected_evidence\n",
        "        or False\n",
    ),
    (
        "persisted-lease-claim-escalation",
        '            "persisted_effect_lease_verified": False,\n',
        '            "persisted_effect_lease_verified": True,\n',
    ),
    (
        "effect-start-claim-escalation",
        '            "retention_effect_started": False,\n',
        '            "retention_effect_started": True,\n',
    ),
    (
        "closure-claim-escalation",
        '            "closed": False,\n',
        '            "closed": True,\n',
    ),
)


def _run(mutated_source: str, name: str) -> None:
    with tempfile.TemporaryDirectory(prefix=f"daedalus-{name}-") as directory:
        sandbox = Path(directory)
        shutil.copytree(ROOT / "daedalus", sandbox / "daedalus")
        target = sandbox / MODULE
        target.write_text(mutated_source, encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(sandbox) + os.pathsep + env.get("PYTHONPATH", "")
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *TESTS],
            cwd=ROOT,
            env=env,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if result.returncode == 0:
            raise SystemExit(f"mutant survived: {name}\n{result.stdout}")


def main() -> int:
    source = (ROOT / MODULE).read_text(encoding="utf-8")
    for name, old, new in MUTATIONS:
        count = source.count(old)
        if count != 1:
            raise SystemExit(f"mutation seam is not unique for {name}: {count}")
        _run(source.replace(old, new, 1), name)
    print(f"killed {len(MUTATIONS)} receipt-retention preflight mutants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
