"""Copy both arms' artifacts to X/ and Y/ under a SEALED random mapping.

Per the pre-registration: the mapping is written to a file nobody opens until
every verdict is in, and identifying traces are stripped -- a branch name, a
receipt, or a comment naming the process gives the arm away instantly.

Judges see only `runs/ab/blind/X` and `runs/ab/blind/Y`.
"""
from __future__ import annotations

import json
import random
import re
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
AB_ROOT = Path(r"C:\Users\nukei\Desktop\ab_run")
BLIND = HERE / "blind"
SEAL = HERE / "receipts" / "SEALED_MAPPING.json"

# Traces that would name the process rather than describe the code.
TELLS = [
    (re.compile(r"(?i)\bdaedalus\b"), "the harness"),
    (re.compile(r"(?i)\bdistilled context\b"), "the provided context"),
    (re.compile(r"(?i)\barm\s*[AB]\b"), "this implementation"),
    (re.compile(r"(?i)\bDSS\b"), "the planner"),
    (re.compile(r"(?i)\bgate feedback\b"), "feedback"),
]


def strip(text: str) -> str:
    for pattern, replacement in TELLS:
        text = pattern.sub(replacement, text)
    return text


def main() -> int:
    if SEAL.exists():
        print(f"refusing to reseal: {SEAL} already exists")
        return 1
    import sys as _sys
    _repo_root = str(HERE.parents[1])
    if _repo_root not in _sys.path:
        _sys.path.insert(0, _repo_root)
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "runs.ab.blind",
        REGISTRY_BY_ID["runs.ab.blind"].effects,
        (process_guard_boundary_decision(),),
    )
    arms = ["A", "B"]
    random.shuffle(arms)
    mapping = {"X": arms[0], "Y": arms[1]}

    if BLIND.exists():
        shutil.rmtree(BLIND)
    for label, arm in mapping.items():
        src = AB_ROOT / f"arm{arm}" / "design" / "visual-lab" / "src" / "core"
        dst = BLIND / label
        dst.mkdir(parents=True)
        for f in sorted(src.glob("*.ts")):
            (dst / f.name).write_text(
                strip(f.read_text(encoding="utf-8", errors="replace")),
                encoding="utf-8")

    SEAL.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
    print(f"sealed. judges read {BLIND}/X and {BLIND}/Y")
    for label in ("X", "Y"):
        files = sorted(p.name for p in (BLIND / label).glob("*.ts"))
        total = sum((BLIND / label / f).stat().st_size for f in files)
        print(f"  {label}: {len(files)} files, {total} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
