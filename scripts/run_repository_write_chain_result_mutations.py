#!/usr/bin/env python3
"""Run bounded mutations against the repository-write chain-result contract."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "daedalus/gates/repository_write_chain_result.py"
TESTS = ("tests/gates/test_repository_write_chain_result.py",)
MUTATIONS = {
    "authenticate-a-blocked-surface": (
        "        return not self.candidate_blockers and authenticated_over_stages(\n",
        "        return authenticated_over_stages(\n",
    ),
    "authenticate-an-incomplete-inventory": (
        "        return bool(self.surfaces) and not self.missing_surface_count and all(\n",
        "        return bool(self.surfaces) and all(\n",
    ),
    "accept-forged-derived-fields": (
        "        if dict(value) != result.to_dict():\n",
        "        if False and dict(value) != result.to_dict():\n",
    ),
    "accept-forged-surface-authentication": (
        '        if value["authenticated"] != result.authenticated:\n',
        '        if False and value["authenticated"] != result.authenticated:\n',
    ),
    "accept-a-missing-stage-report": (
        "    if set(reports) != set(AuthenticationStage):\n",
        "    if False and set(reports) != set(AuthenticationStage):\n",
    ),
}


def main() -> int:
    original = TARGET.read_text(encoding="utf-8")
    survivors: list[str] = []
    try:
        for name, (needle, replacement) in MUTATIONS.items():
            count = original.count(needle)
            if count != 1:
                raise RuntimeError(
                    f"mutation {name} expected one source anchor, found {count}"
                )
            TARGET.write_text(original.replace(needle, replacement), encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", *TESTS],
                cwd=ROOT,
                check=False,
                capture_output=True,
                text=True,
                timeout=60,
                env={**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"},
            )
            if completed.returncode == 0:
                survivors.append(name)
            TARGET.write_text(original, encoding="utf-8")
    finally:
        TARGET.write_text(original, encoding="utf-8")
    if survivors:
        print("surviving mutations: " + ", ".join(survivors), file=sys.stderr)
        return 1
    print(f"killed {len(MUTATIONS)} repository-write chain-result mutations")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
