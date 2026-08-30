# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

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
        "first-head-fence-bypass",
        "    # First HEAD fence: the signed revision must be current before source reads.\n"
        "    try:\n"
        "        verify_repository_head_revision_receipt(\n",
        "    # First HEAD fence: the signed revision must be current before source reads.\n"
        "    try:\n"
        "        (lambda *args, **kwargs: None)(\n",
    ),
    (
        "second-head-fence-bypass",
        "    # Second HEAD fence: refuse a revision change during inventory reconstruction.\n"
        "    try:\n"
        "        verify_repository_head_revision_receipt(\n",
        "    # Second HEAD fence: refuse a revision change during inventory reconstruction.\n"
        "    try:\n"
        "        (lambda *args, **kwargs: None)(\n",
    ),
    (
        "inventory-live-rebuild-bypass",
        "        rebuilt_inventory = scan_provider_target_receipt_retention(\n",
        "        rebuilt_inventory = (lambda *args, **kwargs: inventory)(\n",
    ),
    (
        "inventory-comparison-bypass",
        "    if rebuilt_inventory != inventory or rebuilt_inventory.digest != inventory_digest:\n",
        "    if False:\n",
    ),
    (
        "guard-evidence-comparison-bypass",
        "        or decision.evidence != expected_evidence\n",
        "        or False\n",
    ),
    (
        "subject-digest-recheck-bypass",
        "        _require_unchanged_digest(value, digest, label)\n",
        "        pass\n",
    ),
    (
        "revision-width-bypass",
        '_SOURCE_REVISION = re.compile(r"^[0-9a-f]{40}$")\n',
        '_SOURCE_REVISION = re.compile(r"^[0-9a-f]{40,64}$")\n',
    ),
    (
        "inventory-size-bound-bypass",
        "        if source_size > _MAX_INVENTORY_SOURCE_BYTES:\n",
        "        if False:\n",
    ),
    (
        "surface-count-bound-bypass",
        "        if surface_count != _EXPECTED_RETENTION_SURFACE_COUNT:\n",
        "        if False:\n",
    ),
    (
        "scope-overlap-bypass",
        "        if _paths_overlap(\n",
        "        if False and _paths_overlap(\n",
    ),
    (
        "exact-inventory-surface-type-bypass",
        "            type(row) is not ProviderTargetReceiptRetentionSurface\n",
        "            False\n",
    ),
    (
        "canonical-scope-path-bypass",
        "    if path != value:\n",
        "    if False:\n",
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
