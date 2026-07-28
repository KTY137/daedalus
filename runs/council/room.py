"""Der Raum — a shared chatroom for agents from different vendors.

One append-only markdown file. Everybody reads the whole room before they
speak, everybody's turn lands in the same place, and a human can watch it
live in an editor.

  python runs/council/room.py show
  python runs/council/room.py say <who> <text-file>
  python runs/council/room.py ask codex   [--prompt-file F]
  python runs/council/room.py ask ollama  [--model qwen2.5-coder:14b]
  python runs/council/room.py ask agy     [--model ...]        # needs sign-in
  python runs/council/room.py who

The room file is plain markdown on purpose: no parsing ceremony, a human
opens it and reads a conversation.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOM = Path(__file__).resolve().parent / "room.md"
BENCH = os.environ.get("DAEDALUS_RTX_OLLAMA_HOST", "http://100.119.126.9:11434")
BENCH_SSH = "Administrator@100.119.126.9"

SPEAKERS = {
    "claude": ("Claude", "Anthropic · Fable 5"),
    "codex": ("Codex", "OpenAI · codex CLI"),
    "ollama": ("Ollama", "local · qwen2.5-coder"),
    "agy": ("Antigravity", "Google · agy CLI"),
    "opus": ("Opus", "Anthropic · Opus 4.6"),
    "kaya": ("Kaya", "human"),
}

HOUSE_RULES = """\
You are in a shared room with agents from other vendors. Everything below is
the full transcript so far; anyone may read it and anyone may reply.

House rules:
- Disagree when you disagree. Different vendors have different blind spots and
  that is the entire point of this room. Agreement that costs you nothing is
  worth nothing here.
- Address people by name when you answer them.
- Cite file:line when you make a claim about code. A claim without evidence is
  an opinion, and this room runs on evidence.
- If you could not verify something, say so instead of guessing.
- Be brief. This is a conversation, not a report.
"""


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%H:%M:%S")


def _ensure() -> None:
    ROOM.parent.mkdir(parents=True, exist_ok=True)
    if not ROOM.exists():
        ROOM.write_text(
            "# Der Raum\n\n"
            "A shared room for agents from different vendors. Append-only.\n\n",
            encoding="utf-8",
        )


def say(who: str, text: str) -> None:
    _ensure()
    name, tag = SPEAKERS.get(who, (who, "unknown"))
    with ROOM.open("a", encoding="utf-8") as fh:
        fh.write(f"\n---\n\n### {name}  ·  {tag}  ·  {_now()}\n\n{text.strip()}\n")
    print(f"[room] {name} spoke ({len(text)} chars)")


def transcript() -> str:
    _ensure()
    return ROOM.read_text(encoding="utf-8")


def _attach(paths: list[str], budget_chars: int = 40000) -> str:
    """Inline file bodies for speakers that cannot read the disk themselves.

    Ollama and agy get text only; without this they are asked about code they
    have never seen, and an honest model correctly answers nothing.
    """
    if not paths:
        return ""
    root = ROOM.parents[2]
    chunks, spent = [], 0
    for rel in paths:
        p = (root / rel).resolve()
        try:
            body = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            chunks.append(f"----- {rel} (unreadable: {exc}) -----")
            continue
        room_left = budget_chars - spent
        if room_left <= 0:
            chunks.append(f"----- {rel} (omitted: attachment budget spent) -----")
            continue
        if len(body) > room_left:
            body = body[:room_left] + f"\n... [truncated at {room_left} chars]"
        spent += len(body)
        chunks.append(f"----- {rel} -----\n{body}")
    return "\n\n===== ATTACHED FILES =====\n" + "\n\n".join(chunks) + "\n===== END FILES =====\n"


def _prompt_for(who: str, extra: str = "", attach: list[str] | None = None) -> str:
    name = SPEAKERS.get(who, (who, ""))[0]
    return (
        f"{HOUSE_RULES}\n"
        f"You are **{name}**. Read the room, then write ONLY your next turn —\n"
        f"no headers, no markdown title, no signature, just what you say.\n"
        f"{extra}\n\n"
        f"===== ROOM TRANSCRIPT =====\n{transcript()}\n===== END =====\n"
        f"{_attach(attach or [])}\n"
        f"Your turn, {name}:"
    )


def _exe(name: str) -> str:
    """Resolve a CLI to something CreateProcess can actually launch.

    npm shims on Windows are .cmd/.ps1; subprocess without a shell cannot
    launch the extensionless variant that shutil.which finds first.
    """
    import shutil

    for candidate in (f"{name}.cmd", f"{name}.exe", name):
        found = shutil.which(candidate)
        if found and Path(found).suffix.lower() in {".cmd", ".exe", ".bat"}:
            return found
    found = shutil.which(name)
    if not found:
        raise FileNotFoundError(f"{name} is not on PATH")
    return found


def ask_codex(extra: str = "", timeout: int = 900,
              attach: list[str] | None = None) -> str:
    prompt = _prompt_for("codex", extra, attach)
    pf = ROOM.parent / ".codex_prompt.txt"
    pf.write_text(prompt, encoding="utf-8")
    # The prompt goes in on stdin: a multi-line argument does not survive the
    # npm .cmd shim on Windows (it arrives truncated at the first newline).
    proc = subprocess.run(
        [_exe("codex"), "exec", "--sandbox", "read-only"],
        input=prompt,
        cwd=str(ROOM.parents[2]),
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    out = proc.stdout or ""
    # codex exec prints a preamble and token accounting; the reply is the tail
    marker = "tokens used"
    if marker in out:
        out = out.split(marker)[-1]
        out = "\n".join(out.splitlines()[1:])
    return out.strip() or f"(codex returned nothing; stderr: {proc.stderr[-400:]})"


def ask_opus(model: str = "claude-opus-4-6", extra: str = "",
             timeout: int = 900, attach: list[str] | None = None) -> str:
    """A second Anthropic head on a different model.

    Not vendor-independent — same weights family, same lab — but a different
    model with different training, and available while agy is quota-limited.
    Label it honestly in the room so nobody mistakes it for a fourth vendor.
    """
    prompt = _prompt_for("opus", extra, attach)
    proc = subprocess.run(
        [_exe("claude"), "-p", "--model", model, "--permission-mode", "plan"],
        input=prompt,
        cwd=str(ROOM.parents[2]),
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "").strip()
    return out or f"(opus returned nothing; stderr: {proc.stderr[-400:]})"


def ask_ollama(model: str = "qwen2.5-coder:14b", host: str = BENCH,
               extra: str = "", timeout: int = 900,
               attach: list[str] | None = None) -> str:
    prompt = _prompt_for("ollama", extra, attach)
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "options": {"num_ctx": 16384, "temperature": 0.4},
    }).encode()
    req = urllib.request.Request(
        f"{host}/api/chat", data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read())
    return (data.get("message", {}).get("content") or "").strip()


def ask_agy(model: str = "", extra: str = "", timeout: int = 900,
            attach: list[str] | None = None) -> str:
    prompt = _prompt_for("agy", extra, attach)
    pf = ROOM.parent / ".agy_prompt.txt"
    pf.write_text(prompt, encoding="utf-8")
    remote = "C:/Users/Administrator/.daedalus_room_prompt.txt"
    subprocess.run(["scp", str(pf), f"{BENCH_SSH}:{remote}"],
                   capture_output=True, text=True, timeout=120)
    cmd = f'agy -p "$(type {remote.replace("/", chr(92))})"'
    if model:
        cmd += f" --model {model}"
    proc = subprocess.run(["ssh", BENCH_SSH, cmd], capture_output=True,
                          text=True, timeout=timeout, encoding="utf-8",
                          errors="replace")
    out = (proc.stdout or "").strip()
    if not out or "sign in" in (proc.stderr or "").lower():
        return f"(agy unavailable: {(proc.stderr or 'no output')[-300:]})"
    return out


def who() -> None:
    print(f"room: {ROOM}")
    print(f"bench: {BENCH}")
    for key, (name, tag) in SPEAKERS.items():
        print(f"  {key:8s} {name:12s} {tag}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    sub.add_parser("who")
    s = sub.add_parser("say")
    s.add_argument("who")
    s.add_argument("textfile")
    a = sub.add_parser("ask")
    a.add_argument("vendor", choices=["codex", "ollama", "agy", "opus"])
    a.add_argument("--model", default="")
    a.add_argument("--extra", default="")
    a.add_argument("--timeout", type=int, default=900)
    a.add_argument("--attach", default="", help="comma-separated repo-relative files to inline")
    args = ap.parse_args()

    if args.cmd == "show":
        print(transcript())
    elif args.cmd == "who":
        who()
    elif args.cmd == "say":
        say(args.who, Path(args.textfile).read_text(encoding="utf-8"))
    elif args.cmd == "ask":
        t0 = time.time()
        att = [x.strip() for x in args.attach.split(",") if x.strip()]
        if args.vendor == "codex":
            reply = ask_codex(args.extra, args.timeout, att)
        elif args.vendor == "opus":
            reply = ask_opus(args.model or "claude-opus-4-6",
                             args.extra, args.timeout, att)
        elif args.vendor == "ollama":
            reply = ask_ollama(args.model or "qwen2.5-coder:14b",
                               extra=args.extra, timeout=args.timeout, attach=att)
        else:
            reply = ask_agy(args.model, args.extra, args.timeout, att)
        say(args.vendor, reply)
        print(f"[room] {args.vendor} replied in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
