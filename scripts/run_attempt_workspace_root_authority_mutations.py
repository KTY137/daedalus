# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "attempt_workspace.py"
TESTS = (
    "tests/kernel/test_isolated_attempt_workspace_root_authority.py",
    "tests/kernel/test_isolated_attempt_workspace_identity_review.py",
    "tests/kernel/test_isolated_attempt_lifecycle.py",
    "tests/kernel/test_isolated_attempt_lifecycle_adversarial.py",
    "tests/kernel/test_isolated_attempt_time_and_preflight.py",
    "tests/kernel/test_isolated_attempt_time_tampering.py",
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
        sys.stderr.write("Attempt workspace-root mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    mutations = (
        (
            "create-caller-selected-workspace-root",
            """    try:
        parent = raw_parent.resolve(strict=True)
""",
            """    raw_parent.mkdir(parents=True, exist_ok=True)
    try:
        parent = raw_parent.resolve(strict=True)
""",
        ),
        (
            "admit-protected-primary-overlap",
            """    _assert_disjoint(
        prospective,
        primary,
        "workspace parent and primary checkout",
    )
""",
            "",
        ),
        (
            "retain-replaced-root-identity",
            """        if (
            current != parent
            or _workspace_root_identity(current) != self.workspace_parent_sha256
        ):
            raise AttemptWorkspaceError(
                "workspace parent identity changed after admission"
            )
""",
            """        if False:
            raise AttemptWorkspaceError(
                "workspace parent identity changed after admission"
            )
""",
        ),
        (
            "materialize-without-last-root-revalidation",
            """        if not begin.execute:
            return PreparedAttempt(begin=begin, workspace=None)
        self._require_stable_workspace_parent()
        workspace = self.workspace_parent.joinpath(*relative.split("/"))
""",
            """        if not begin.execute:
            return PreparedAttempt(begin=begin, workspace=None)
        workspace = self.workspace_parent.joinpath(*relative.split("/"))
""",
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
                return 1
            killed.append(label)
            TARGET.write_bytes(original)
    finally:
        TARGET.write_bytes(original)

    if TARGET.read_bytes() != original:
        raise RuntimeError("mutation runner failed to restore attempt_workspace.py")
    print("killed mutations: " + ", ".join(killed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
