#!/usr/bin/env python3
"""Compatibility wrapper for the canonical declarative mutation runner."""
from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.mutation_score import main as mutation_main  # noqa: E402


SPEC = ROOT / "configs" / "mutations" / "repository-tree.json"


def main() -> int:
    return mutation_main(["--repo", str(ROOT), "--spec", str(SPEC)])


if __name__ == "__main__":
    raise SystemExit(main())
