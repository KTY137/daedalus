# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Bounded mutation campaign for repository HEAD revision verification."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = Path("daedalus/gates/repository_head_revision.py")
TESTS = ("tests/gates/test_repository_head_revision.py",)

MUTATIONS = (
    (
        "second-observation-reuse",
        "    second = _resolve_once(root)\n",
        "    second = first\n",
    ),
    (
        "observation-comparison-bypass",
        "    if first.to_dict() != second.to_dict():\n",
        "    if False:\n",
    ),
    (
        "expected-revision-comparison-bypass",
        "    if first.resolved_revision != expected:\n",
        "    if False:\n",
    ),
    (
        "loose-ref-symlink-check-bypass",
        "        if stat.S_ISLNK(metadata.st_mode):\n",
        "        if False:\n",
    ),
    (
        "packed-ref-uniqueness-bypass",
        "    if len(matches) != 1:\n",
        "    if False:\n",
    ),
    (
        "nested-symbolic-ref-bypass",
        '        if reference_line.startswith("ref: "):\n',
        "        if False:\n",
    ),
    (
        "commit-object-claim-escalation",
        '            "commit_object_verified": False,\n',
        '            "commit_object_verified": True,\n',
    ),
    (
        "worktree-clean-claim-escalation",
        '            "worktree_clean_verified": False,\n',
        '            "worktree_clean_verified": True,\n',
    ),
    (
        "process-spawn-claim-escalation",
        '            "process_spawned": False,\n',
        '            "process_spawned": True,\n',
    ),
    (
        "receipt-live-comparison-bypass",
        "    if rebuilt.to_dict() != receipt.to_dict():\n",
        "    if False:\n",
    ),
)


def _run(mutated_source: str, name: str) -> None:
    with tempfile.TemporaryDirectory(prefix=f"daedalus-{name}-") as directory:
        sandbox = Path(directory)
        shutil.copytree(ROOT / "daedalus", sandbox / "daedalus")
        target = sandbox / MODULE
        target.write_text(mutated_source, encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONPATH"] = (
            str(sandbox) + os.pathsep + env.get("PYTHONPATH", "")
        )
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
            raise SystemExit(
                f"mutation seam is not unique for {name}: {count}"
            )
        _run(source.replace(old, new, 1), name)
    print(f"killed {len(MUTATIONS)} repository HEAD revision mutants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
