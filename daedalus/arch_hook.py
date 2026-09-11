"""arch_hook.py — inject the compressed architecture into every turn.

Companion to ``shift_hook.py``: that one carries the clock, this one carries the
shape of the tree. Both exist because an agent cannot ask for what it does not
know it is missing.

Silent when no snapshot has been built, rather than printing an apology on every
turn: an unbuilt memory is a setup step, not news.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:
    from daedalus import arch_memory
    # DELTA, not the full block: see arch_memory.render_delta on why
    # repetition is what turns an available fact into an ignored one.
    text = arch_memory.render_delta(Path(__file__).resolve().parents[1])
    if text:
        print(text)
except Exception:
    pass  # a hook must never break the turn
