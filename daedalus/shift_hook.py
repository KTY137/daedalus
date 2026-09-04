"""shift_hook.py — put the clock into the agent's context, every single turn.

THE FAILURE THIS CLOSES
-----------------------
An agent has no wall clock. It sees a conversation, and a conversation has no
duration: ten minutes of thinking and four hours of work look identical from the
inside. On 2026-07-30 that produced an agent announcing "it is 10 o'clock" at
03:10, having read a clock once at the start and estimated the rest from its own
sense of progress.

"Remember to check the time" does not fix that, because the agent does not know
that it does not know. The only reliable fix is to make the time part of the
input it cannot skip. This script is a Claude Code ``UserPromptSubmit`` hook: its
stdout becomes context on every turn, so the current time, the declared goal and
the remaining window arrive whether or not anybody thought to ask.

WHY A HOOK AND NOT A BACKGROUND PROCESS
---------------------------------------
A background ticker in tmux is visible to the HUMAN. Nothing it prints reaches
the model, which only ever sees tool results and hook output. Both are useful and
they are different jobs: ``shift_ticker.py`` is the pane a person watches, this
is the line the agent reads. Building only the ticker would have felt like a fix
and changed nothing.

Deliberately silent when no shift is declared beyond the bare time: an unasked-for
reminder on every turn is noise, and noise is how a signal gets ignored.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from daedalus import shift as shift_mod
except Exception:  # pragma: no cover - a hook must never break the turn
    print("[clock unavailable]")
    raise SystemExit(0)


def main() -> int:
    try:
        s = shift_mod.load(Path(__file__).resolve().parents[1])
        line = s.render()
        if s.goal and s.expired:
            # The one case worth raising a voice about: the declared window has
            # passed. Reported, never enforced -- the decision is the operator's.
            line += "  <- the declared window has passed; report and confirm before continuing"
        print(line)
    except Exception:
        print("[clock unavailable]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
