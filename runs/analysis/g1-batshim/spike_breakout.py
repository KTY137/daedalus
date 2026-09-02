"""SPIKE 2 (scratch): with the payload BEFORE any newline, does the .cmd relay
execute it? Isolates the cmd.exe break-out from the newline truncation."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

PY = sys.executable
CAPTURE = """\
import json, sys
from pathlib import Path
here = Path(__file__).resolve().parent
(here / "argv.json").write_text(json.dumps(sys.argv[1:]), encoding="utf-8")
"""


def case(label: str, prompt: str) -> None:
    box = Path(tempfile.mkdtemp(prefix="breakout-"))
    (box / "capture.py").write_text(CAPTURE, encoding="utf-8")
    shim = box / "codex.cmd"
    shim.write_text(f'@echo off\r\n"{PY}" "%~dp0capture.py" %*\r\n', encoding="utf-8")
    canary = box / "canary.txt"
    prompt = prompt.replace("<CANARY>", str(canary))
    completed = subprocess.run(
        [str(shim), "exec", "--color", "never", prompt],
        cwd=str(box), text=True, capture_output=True, encoding="utf-8",
        errors="replace", stdin=subprocess.DEVNULL, timeout=60, check=False,
    )
    argv_file = box / "argv.json"
    argv = json.loads(argv_file.read_text(encoding="utf-8")) if argv_file.exists() else None
    print(f"--- {label}")
    print(f"    sent prompt : {prompt!r}")
    print(f"    rc          : {completed.returncode}")
    print(f"    CANARY      : {canary.exists()}")
    if canary.exists():
        print(f"    canary body : {canary.read_text(encoding='utf-8', errors='replace')!r}")
    print(f"    argv seen   : {argv!r}")
    if completed.stderr.strip():
        blob = completed.stderr.strip()[:200].encode("ascii", "replace").decode("ascii")
        print(f"    stderr      : {blob!r}")


if __name__ == "__main__":
    case("A quoted redirect target (payload's own quotes get \\\"-mangled)",
         'benign objective" & echo pwned > "<CANARY>" & rem ')
    case("A2 unquoted redirect target",
         'benign objective" & echo pwned > <CANARY> & rem ')
    case("B bare & without a quote break-out",
         'benign objective & echo pwned > <CANARY>')
    case("C payload on line 2 (today's build_prompt shape)",
         'Daedalus Bridge Protocol v1.\nObjective:\nbenign" & echo pwned > <CANARY> & rem ')
    case("D %VAR% expansion, no quotes at all",
         'benign objective %USERNAME% and %PATH:~0,4%')

    # E: does list2cmdline's "quote only if it contains a space" rule leave a
    #    space-free `&` argument unquoted (and therefore live)?
    import subprocess as _sp
    print("--- E list2cmdline quoting")
    for arg in ("a&b", "a & b", 'a"b', "a%USERNAME%b"):
        print(f"    {arg!r} -> {_sp.list2cmdline([arg])!r}")
    case("E space-free & argument (no quoting applies)",
         "benign&echo pwned><CANARY>")
