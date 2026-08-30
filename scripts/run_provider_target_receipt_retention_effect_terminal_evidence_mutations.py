# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Bounded mutation campaign for persisted Effect-terminal evidence."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = Path(
    "daedalus/runtimes/"
    "provider_target_receipt_retention_effect_terminal_evidence.py"
)
TESTS = (
    "tests/runtimes/"
    "test_provider_target_receipt_retention_effect_terminal_evidence.py",
    "tests/runtimes/"
    "test_provider_target_receipt_retention_effect_terminal_evidence_review.py",
)

MUTATIONS = (
    (
        "exact-public-subject-type-bypass",
        "    for value, expected, label in exact:\n"
        "        if type(value) is not expected:\n"
        "            raise ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError(\n"
        "                f\"{label} must be exact {expected.__name__}\"\n"
        "            )\n\n"
        "    revision = _commit_revision(\n",
        "    for value, expected, label in exact:\n"
        "        if False:\n"
        "            raise ProviderTargetReceiptRetentionEffectTerminalEvidenceShapeError(\n"
        "                f\"{label} must be exact {expected.__name__}\"\n"
        "            )\n\n"
        "    revision = _commit_revision(\n",
    ),
    (
        "commit-revision-width-bypass",
        "    if len(revision) != 40:\n",
        "    if False:\n",
    ),
    (
        "effect-store-hardlink-bypass",
        "    if info.st_nlink != 1:\n",
        "    if False:\n",
    ),
    (
        "completed-evidence-revision-bypass",
        "    if completed_evidence.source_revision != revision:\n",
        "    if False:\n",
    ),
    (
        "authority-revision-bypass",
        "    if authority_revisions != {revision}:\n",
        "    if False:\n",
    ),
    (
        "completed-effect-state-bypass",
        '    if snapshot.state != "COMPLETED":\n',
        "    if False:\n",
    ),
    (
        "start-receipt-digest-bypass",
        "    if start_receipt_sha != expected_start_sha:\n",
        "    if False:\n",
    ),
    (
        "terminal-start-binding-bypass",
        "        or terminal.lease_sha256 != authorization.lease.digest\n",
        "        or False\n",
    ),
    (
        "terminal-receipt-digest-bypass",
        "    if terminal_receipt_sha != expected_terminal_sha:\n",
        "    if False:\n",
    ),
    (
        "first-store-identity-fence-bypass",
        "    if store_mid != store_before:\n",
        "    if False:\n",
    ),
    (
        "second-store-identity-fence-bypass",
        "    if store_after != store_before:\n",
        "    if False:\n",
    ),
    (
        "double-read-state-fence-bypass",
        "    if first != second:\n",
        "    if False:\n",
    ),
    (
        "start-receipt-evidence-binding-bypass",
        "    if start.receipt_sha256 != completed_evidence.start_receipt_sha256:\n",
        "    if False:\n",
    ),
    (
        "terminal-receipt-evidence-binding-bypass",
        "    if terminal.receipt_sha256 != completed_evidence.terminal_receipt_sha256:\n",
        "    if False:\n",
    ),
    (
        "terminal-output-binding-bypass",
        "    if terminal.output_digests != (\n"
        "        completed_evidence.receipt_artifact_sha256,\n"
        "    ):\n",
        "    if False:\n",
    ),
    (
        "closure-claim-escalation",
        "            **{field: False for field in _FALSE_CLAIMS},\n",
        '            **{field: field == "closed" for field in _FALSE_CLAIMS},\n',
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
    print(f"killed {len(MUTATIONS)} Effect-terminal evidence mutants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
