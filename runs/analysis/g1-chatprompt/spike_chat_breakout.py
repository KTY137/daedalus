"""SPIKE (scratch, packet G1-SEC-02): drive the REAL ``ikarus_os._codex`` with a
stub ``.cmd`` standing in for the npm codex shim, and ask whether a CHAT MESSAGE
can execute a command.

Nothing here spawns the real codex: ``resolve_runtime_command`` is pointed at a
stub ``.cmd`` we write ourselves, so no model turn is billed. The payload is a
canary ``echo`` -- it creates a file and nothing else.
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

PY = sys.executable

# The stub records what the child ACTUALLY received: argv and stdin. It also
# honours --output-last-message so _codex()'s read-back finds real content.
CAPTURE = """\
import json, sys
from pathlib import Path
here = Path(__file__).resolve().parent
argv = sys.argv[1:]
(here / "argv.json").write_text(json.dumps(argv), encoding="utf-8")
data = sys.stdin.buffer.read() if not sys.stdin.isatty() else b""
(here / "stdin.bin").write_bytes(data)
if "--output-last-message" in argv:
    Path(argv[argv.index("--output-last-message") + 1]).write_text(
        "stub reply", encoding="utf-8")
"""


def case(label: str, message: str, model: str | None = None) -> None:
    from daedalus import budget, ikarus_os

    # A FRESH ledger per case, and never the operator's: this drives a REAL
    # spawn, and the budget interposer reserves a worst-case $2 per vendor
    # spawn, so the $5 period ceiling refuses the third case otherwise.
    os.environ["DAEDALUS_BUDGET_LEDGER"] = str(
        Path(tempfile.mkdtemp(prefix="spike-ledger-")) / "ledger.json")
    budget.reset_default_ledger()

    box = Path(tempfile.mkdtemp(prefix="chat-breakout-"))
    (box / "capture.py").write_text(CAPTURE, encoding="utf-8")
    shim = box / "codex.cmd"
    shim.write_text(f'@echo off\r\n"{PY}" "%~dp0capture.py" %*\r\n', encoding="utf-8")
    canary = box / "canary.txt"
    message = message.replace("<CANARY>", str(canary))
    if model:
        model = model.replace("<CANARY>", str(canary))

    with mock.patch("daedalus.runtime_registry.resolve_runtime_command",
                    return_value=str(shim)):
        try:
            out = ikarus_os._codex(message, model=model, timeout_s=60)
            err = None
        except Exception as exc:  # a refusal is an outcome, not a crash
            out, err = None, f"{type(exc).__name__}: {exc}"

    argv_file = box / "argv.json"
    argv = json.loads(argv_file.read_text(encoding="utf-8")) if argv_file.exists() else None
    stdin_file = box / "stdin.bin"
    seen_stdin = stdin_file.read_bytes() if stdin_file.exists() else b""
    print(f"--- {label}")
    print(f"    reply       : {out!r}")
    print(f"    raised      : {err!r}")
    print(f"    CANARY      : {canary.exists()}")
    if canary.exists():
        print(f"    canary body : {canary.read_text(encoding='utf-8', errors='replace')!r}")
    print(f"    argv seen   : {argv!r}")
    print(f"    stdin bytes : {len(seen_stdin)}")
    print(f"    stdin head  : {seen_stdin[:120]!r}")
    print(f"    payload on stdin intact: "
          f"{message.encode('utf-8') in seen_stdin}")


if __name__ == "__main__":
    case("A single-line chat message with a quote break-out",
         'what is 2+2" & echo pwned > "<CANARY>" & rem ')
    case("B unquoted redirect target",
         'what is 2+2" & echo pwned > <CANARY> & rem ')
    case("C %VAR% expansion inside a chat message",
         "tell me about %USERNAME% and %PATH:~0,4%")
    # D/E: the argv element the caller actually controls end-to-end.
    # POST /api/ikarus/ask -> body["model"] -> ask(model=) -> _llm -> _codex
    # -> args += ["--model", model].  Single-line, no SYSTEM prefix, so the
    # newline truncation that neuters A-C does not apply here at all.
    case("D --model carries a quote break-out", "what is 2+2",
         model='gpt-5" & echo pwned > "<CANARY>" & rem ')
    case("E --model carries %VAR% expansion", "what is 2+2",
         model="gpt-5-%USERNAME%")
    print("--- list2cmdline reference")
    for arg in ('a"b', "a&b", "a%USERNAME%b"):
        print(f"    {arg!r} -> {subprocess.list2cmdline([arg])!r}")
