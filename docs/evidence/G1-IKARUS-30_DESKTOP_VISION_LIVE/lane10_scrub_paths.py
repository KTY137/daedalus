"""G1-IKARUS-30 second privacy pass: every spelling of the home directory.

The first pass (``lane10_redact.py``) removed owner *content* from the OCR
output but replaced only one spelling of the home *path*, and it never saw two
producers at all: the adapter's refusal strings, which embed absolute paths --
the kill switch names its own permit file -- and ``lane10_setup.py``, which
dumped its report unfiltered. This pass rewrites the retained bytes.

Three spellings occur in practice and all three are handled:

    C:\\Users\\<name>      the plain Windows path
    C:/Users/<name>      the forward-slash form pathlib and JSON both emit
    C:\\\\Users\\\\<name>    the JSON-escaped doubled-backslash form

Idempotent: run it again and nothing changes. It rewrites files in place under
its own directory plus the packet, and reports what it touched.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys

OUT = Path(__file__).resolve().parent
PACKET = OUT.parents[1] / "work-packets" / "G1-IKARUS-30_DESKTOP_VISION_LIVE.md"
HOME = str(Path.home())
PLACEHOLDER = "<USERPROFILE>"

# Longest first: the escaped form contains neither of the others as a prefix,
# but ordering is stated explicitly rather than left to dict iteration luck.
SPELLINGS = (
    HOME.replace("\\", "\\\\"),
    HOME.replace("\\", "/"),
    HOME,
)


def scrub(path: Path) -> int:
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return 0
    replaced = 0
    for spelling in SPELLINGS:
        replaced += text.count(spelling)
        text = text.replace(spelling, PLACEHOLDER)
    if replaced:
        path.write_text(text, encoding="utf-8", newline="\n")
    return replaced


def main() -> int:
    targets = [p for p in sorted(OUT.iterdir())
               if p.is_file() and p.name not in {"MANIFEST.json", Path(__file__).name}]
    targets.append(PACKET)
    touched = {}
    for target in targets:
        count = scrub(target)
        if count:
            touched[target.name] = count
    remaining = {p.name: p.read_text(encoding="utf-8", errors="ignore").count(HOME)
                 for p in targets}
    print(json.dumps({"replacements_by_file": touched,
                      "remaining_home_path_occurrences": sum(remaining.values())},
                     indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
