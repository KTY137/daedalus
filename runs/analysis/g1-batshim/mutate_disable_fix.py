"""Disable the G1-SEC-01 fix in place so the new tests can be shown RED, then
restore byte-for-byte. Anchors are asserted UNIQUE before substitution -- an
injection that lands at the wrong site proves nothing.

usage: mutate_disable_fix.py disable | restore
"""
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[3] / "daedalus" / "providers" / "codex_cli.py"
BACKUP = Path(__file__).resolve().parent / "codex_cli.py.orig"

MUTATIONS = [
    # the prompt goes back into argv, exactly as it was before the fix
    ('            # PROMPT == "-": codex exec reads the instructions from stdin.\n'
     '            cmd.append("-")\n',
     '            cmd.append(prompt)\n'),
    # ...and stdin goes back to DEVNULL
    ("                        stdin=fin,\n",
     "                        stdin=subprocess.DEVNULL,\n"),
    # the fail-closed guard is neutered (still importable: symbols stay)
    ("            refusal = cmd_shim_refusal(cmd)\n",
     "            refusal = None\n"),
]


def main() -> int:
    mode = sys.argv[1]
    if mode == "restore":
        TARGET.write_text(BACKUP.read_text(encoding="utf-8"), encoding="utf-8",
                          newline="")
        print("restored", TARGET)
        return 0
    src = TARGET.read_text(encoding="utf-8")
    BACKUP.write_text(src, encoding="utf-8", newline="")
    for old, new in MUTATIONS:
        count = src.count(old)
        assert count == 1, f"anchor is not unique ({count}x): {old!r}"
        src = src.replace(old, new)
    TARGET.write_text(src, encoding="utf-8", newline="")
    print(f"disabled {len(MUTATIONS)} guards in", TARGET)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
