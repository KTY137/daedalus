from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus" / "kernel" / "attempt_workspace.py"
TESTS = (
    "tests/kernel/test_isolated_attempt_workspace_topology_review.py",
    "tests/kernel/test_isolated_attempt_lifecycle.py",
    "tests/kernel/test_isolated_attempt_lifecycle_adversarial.py",
    "tests/kernel/test_isolated_attempt_lifecycle_review.py",
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
        sys.stderr.write("attempt-workspace topology mutation baseline failed\n")
        sys.stderr.write(baseline.stdout + baseline.stderr)
        return 2

    prospective_preflight = """        _require_disjoint_workspace_parent(
            prospective_parent,
            primary_checkout=primary,
            cas_root=cas_root,
        )
        try:
"""
    identity_check = """        if current != parent or _path_identity(current) != self.workspace_parent_sha256:
            raise AttemptWorkspaceError(
                "workspace parent identity changed after coordinator admission"
            )
"""
    pre_materialization = """        if not begin.execute:
            return PreparedAttempt(begin=begin, workspace=None)
        self._require_stable_workspace_parent()
        workspace = self.workspace_parent.joinpath(*relative.split("/"))
"""
    mutations = (
        (
            "admit-prospective-path-overlapping-protected-root",
            prospective_preflight,
            "        try:\n",
        ),
        (
            "retain-replaced-workspace-parent-authority",
            identity_check,
            "        if False:\n            raise AttemptWorkspaceError(\n                \"workspace parent identity changed after coordinator admission\"\n            )\n",
        ),
        (
            "materialize-without-last-stability-recheck",
            pre_materialization,
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
