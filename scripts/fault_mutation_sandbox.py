"""Sandboxed pytest runner shared by the fault-matrix mutation campaigns.

The measurement is only valid if the MUTATED module copy is the one pytest
imports. Mechanism:

* the pytest subprocess starts with ``cwd=<sandbox>``; ``python -m pytest``
  prepends its cwd to ``sys.path``, so ``daedalus`` resolves inside the
  sandbox before any other path, and the relative test paths resolve to the
  sandboxed tests;
* ``PYTHONPATH`` is replaced (not extended) with the sandbox, so no inherited
  entry can shadow it;
* ``__pycache__`` is never copied, so stale or hash-based bytecode cannot
  resurrect the clean module.

Because a silent fallback to the clean checkout renders every "mutants
killed" number meaningless, each campaign is fail-closed:

1. the clean source must PASS inside the sandbox (otherwise kills would not
   be attributable to the mutation);
2. a canary mutant -- the clean module with a module-level ``raise``
   appended -- must FAIL with its marker visible in the pytest output. If
   the clean checkout were imported instead, the canary survives and the
   campaign aborts instead of reporting numbers; a failure without the
   marker aborts too, because it is not attributable to the sandboxed
   import.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CANARY_MARKER = "DAEDALUS-FAULT-SANDBOX-CANARY"


def _pytest_in_sandbox(
    root: Path,
    module: Path,
    tests: tuple[str, ...],
    source: str,
    prefix: str,
    name: str,
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory(prefix=f"{prefix}{name}-") as directory:
        sandbox = Path(directory)
        ignore = shutil.ignore_patterns("__pycache__")
        shutil.copytree(root / "daedalus", sandbox / "daedalus", ignore=ignore)
        shutil.copytree(root / "tests", sandbox / "tests", ignore=ignore)
        shutil.copytree(root / "configs", sandbox / "configs", ignore=ignore)
        (sandbox / module).write_text(source, encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONPATH"] = str(sandbox)
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        return subprocess.run(
            [sys.executable, "-m", "pytest", "-q", *tests],
            cwd=sandbox,
            env=env,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )


def _verify_sandbox_bites(
    root: Path,
    module: Path,
    tests: tuple[str, ...],
    clean_source: str,
    prefix: str,
) -> None:
    baseline = _pytest_in_sandbox(
        root, module, tests, clean_source, prefix, "clean-baseline"
    )
    if baseline.returncode != 0:
        raise SystemExit(
            "clean baseline FAILED inside the sandbox: mutant kills would "
            "not be attributable to the mutation; refusing to report "
            "mutation results\n" + baseline.stdout
        )
    poisoned = (
        clean_source
        + f'\nraise RuntimeError("{CANARY_MARKER}")  # sandbox canary\n'
    )
    canary = _pytest_in_sandbox(
        root, module, tests, poisoned, prefix, "sandbox-canary"
    )
    if canary.returncode == 0:
        raise SystemExit(
            "sandbox canary SURVIVED: pytest imported the clean checkout, "
            "not the sandboxed copy; refusing to report mutation results\n"
            + canary.stdout
        )
    if CANARY_MARKER not in canary.stdout:
        raise SystemExit(
            "sandbox canary died without its marker: the failure is not "
            "attributable to the sandboxed module import; refusing to "
            "report mutation results\n" + canary.stdout
        )
    print("self-probe: clean baseline passed, sandbox canary killed "
          f"({CANARY_MARKER}) -- sandbox import verified")


def run_campaign(
    root: Path,
    module: Path,
    tests: tuple[str, ...],
    mutations: tuple[tuple[str, str, str], ...],
    prefix: str,
    summary: str,
) -> int:
    source = (root / module).read_text(encoding="utf-8")
    for name, old, new in mutations:
        count = source.count(old)
        if count != 1:
            raise SystemExit(f"mutation seam is not unique for {name}: {count}")
    _verify_sandbox_bites(root, module, tests, source, prefix)
    for name, old, new in mutations:
        result = _pytest_in_sandbox(
            root, module, tests, source.replace(old, new, 1), prefix, name
        )
        if result.returncode == 0:
            raise SystemExit(f"mutant survived: {name}\n{result.stdout}")
        print(f"killed: {name}")
    print(summary.format(count=len(mutations)))
    return 0
