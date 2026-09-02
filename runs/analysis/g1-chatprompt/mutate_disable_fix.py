"""Disable the G1-SEC-02 fix IN PLACE so the new tests can be shown RED, then
restore byte-for-byte. Anchors are asserted UNIQUE before substitution -- an
injection that lands at the wrong site proves nothing about the right one.

usage: mutate_disable_fix.py disable | restore
"""
import sys
from pathlib import Path

TARGET = Path(__file__).resolve().parents[3] / "daedalus" / "ikarus_os.py"
BACKUP = Path(__file__).resolve().parent / "ikarus_os.py.orig"

MUTATIONS = [
    # 1. the prompt goes back into argv, exactly as it was before the fix
    ('            # PROMPT == "-": codex exec reads the instructions from stdin.\n'
     '            args.append("-")\n',
     '            args.append(prompt)\n'),
    # 2. ...and stdin goes back to DEVNULL (the `with open(...)` stays, so the
    #    file is still written -- only the child stops receiving it)
    ("                    errors=\"replace\", timeout=timeout_s, stdin=fin, check=False,\n",
     "                    errors=\"replace\", timeout=timeout_s, "
     "stdin=subprocess.DEVNULL, check=False,\n"),
    # 3. the fail-closed guard is neutered at its source, so ALL FOUR call
    #    sites lose it at once and the symbol stays importable
    ("    reason = cmd_shim_refusal(argv)\n",
     "    reason = None\n"),
    # 4. the streaming fallback stops speaking the refusal and lets it escape
    #    the generator again (the pre-fix behaviour: sse.py's generic
    #    `except Exception` renders it as "I hit a snag: ...")
    ('            yield "final", _reconcile_final(\n'
     "                route, _refusal_envelope(project, exc.receipt))\n"
     "            return\n"
     '        yield "final", _reconcile_final(route, envelope)\n',
     "            raise\n"
     '        yield "final", _reconcile_final(route, envelope)\n'),
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
