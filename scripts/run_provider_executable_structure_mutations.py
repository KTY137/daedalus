"""Bounded mutation campaign for provider executable structure verification."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = Path("daedalus/runtimes/provider/executable_structure.py")
TESTS = ("tests/runtimes/test_provider_executable_structure.py",)

MUTATIONS = (
    (
        "authority-subject-type-bypass",
        "        if type(value) is not expected:\n",
        "        if False:\n",
    ),
    (
        "authenticated-projection-type-bypass",
        "    if type(projection) is not ProviderExecutableTargetProjection:\n",
        "    if False:\n",
    ),
    (
        "repository-root-shape-bypass",
        "    if not isinstance(repository_root, Path):\n",
        "    if False:\n",
    ),
    (
        "target-authority-digest-detachment",
        "        target_authority_sha256=target_authority.digest,\n",
        '        target_authority_sha256="0" * 64,\n',
    ),
    (
        "receipt-live-rebuild-bypass",
        "    if rebuilt.to_dict() != receipt.to_dict():\n",
        "    if False:\n",
    ),
    (
        "output-target-comparison-bypass",
        "    if retained_output.target != projection.output_digests_target:\n",
        "    if False:\n",
    ),
    (
        "invoke-source-comparison-bypass",
        "    if retained_invoke.source_sha256 != projection.invoke_source_sha256:\n",
        "    if False:\n",
    ),
    (
        "target-authority-claim-loss",
        '            "target_authority_authenticated": True,\n',
        '            "target_authority_authenticated": False,\n',
    ),
    (
        "provider-execution-claim-escalation",
        '            "provider_execution_allowed": False,\n',
        '            "provider_execution_allowed": True,\n',
    ),
    (
        "git-head-claim-escalation",
        '            "source_revision_verified_against_git_head": False,\n',
        '            "source_revision_verified_against_git_head": True,\n',
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
        if source.count(old) != 1:
            raise SystemExit(
                f"mutation seam is not unique for {name}: {source.count(old)}"
            )
        _run(source.replace(old, new, 1), name)
    print(f"killed {len(MUTATIONS)} provider structure mutants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
