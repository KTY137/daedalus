"""shift_ticker.py — the pane a person watches while an agent works.

Run it in tmux, screen, or any spare terminal:

    python -m daedalus.interfaces.cli.shift_ticker            # 60s cadence
    python -m daedalus.interfaces.cli.shift_ticker --every 300

WHAT IT IS FOR, AND WHAT IT IS NOT
----------------------------------
This is the HUMAN's view. It prints the time, the declared goal, how much of the
window is left, and the checkpoints the agent has written. It cannot reach the
agent -- a model only ever sees tool results and hook output -- so it is the
companion to the hooks package (``daedalus/hooks``, whose turn event carries
the clock; ``shift_hook.py`` until 2026-08-23), never a replacement. Building only this would
look like a fix and change nothing about the agent's blindness.

It also does not enforce anything. When the window passes it says so, loudly,
once per tick, and keeps running. A ticker that killed work on a deadline would
be a worse failure than a late finish: the agent may be three minutes from a
result, and nothing here knows that.

stdlib only; no daemon, no tmux dependency. It works in tmux because it works
anywhere.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from daedalus import shift as shift_mod  # noqa: E402

BAR = 28


def _bar(frac: float) -> str:
    filled = max(0, min(BAR, int(round(frac * BAR))))
    return "[" + "#" * filled + "." * (BAR - filled) + "]"


def render(root: Path) -> str:
    s = shift_mod.load(root)
    now = datetime.now().astimezone().strftime("%H:%M:%S")
    if not s.goal:
        return (f"{now}  no shift declared\n"
                f"          start one:  python -m daedalus.shift start "
                f'"the goal" "10:00" "what done means"')

    rem = s.remaining()
    el = s.elapsed()
    lines = [f"{now}  {s.goal}"]
    if s.done_means:
        lines.append(f"          done = {s.done_means}")
    if rem is not None and el is not None:
        total = (el + rem).total_seconds()
        frac = el.total_seconds() / total if total > 0 else 1.0
        if rem.total_seconds() <= 0:
            lines.append(f"          {_bar(1.0)}  WINDOW PASSED "
                         f"{shift_mod._hm(-rem)} ago (was {s.until})")
        else:
            lines.append(f"          {_bar(frac)}  {shift_mod._hm(rem)} left "
                         f"of {shift_mod._hm(el + rem)}  (until {s.until})")
    elif el is not None:
        lines.append(f"          {shift_mod._hm(el)} worked, no end declared")

    if s.notes:
        lines.append(f"          checkpoints ({len(s.notes)}):")
        for n in s.notes[-4:]:
            lines.append(f"            {n.get('at','--:--')}  {str(n.get('text',''))[:70]}")
    return "\n".join(lines)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="daedalus.interfaces.cli.shift_ticker",
                                description="Watch a declared working window.")
    p.add_argument("--every", type=float, default=60.0, help="seconds between ticks")
    p.add_argument("--once", action="store_true", help="print one tick and exit")
    args = p.parse_args(argv)
    root = Path(__file__).resolve().parents[3]

    try:
        while True:
            print(render(root), flush=True)
            if args.once:
                return 0
            print("-" * 62, flush=True)
            time.sleep(max(1.0, args.every))
    except KeyboardInterrupt:
        print("\nticker stopped (the shift itself is untouched)", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
