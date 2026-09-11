---
name: health-surface-contract
description: daedalus/health.py assess() fans 20 probes onto daemon threads — what `seconds` means, what the mutation table demands of a new guard, and what still has no test
metadata:
  type: project
---

`daedalus/health.py::assess()` fans its ~20 probes out over daemon threads
(`_fan_out`, capped at `_MAX_PROBE_WORKERS = 32`) and is reached from
`ThreadingHTTPServer` (`daedalus/interfaces/http/read.py`, `/api/health`), so
**two concurrent `assess()` calls are reachable** and nothing coalesces them.

What that costs, measured across the 2026-09-10/11 repair rounds:

- Shared reads (bench ssh round trip, product source walk) live in `Ctx.run`
  (`RunState`), single-flight per run. The WAITER is charged nothing; the
  WINNER is charged the whole shared walk, so `route.latent` swings 0.16-0.70 s
  between runs depending on who won the race against `wiring.islands`.
- `Report.seconds` is elapsed time minus wait-on-another-probe, but NOT minus
  contention: the row sum ran ~8% (2026-09-10) to ~18% (2026-09-11) above the
  same probes run serially. It is an upper bound on the work, never a duration.
- Probes are read-only, but the evidence is narrower than it looks:
  `ProbesDoNotMutate` covers **two** of the twenty (ledger, vector index). No
  test abandons a probe mid-flight; an abandoned probe's `git`/`ssh` children
  are not killed and outlive the read unless a console Ctrl-C hits the group.
- Every latency repair on this file has cost something in honesty of the rows.
  Check `seconds`, the caches, and any docstring citation first.

**Why:** the fan-out was introduced to cut `GET /api/health` from ~6.3 s to
~2.2 s (two probes dial the same dead local Ollama; a refused TCP connect costs
~2 s here). Each round of it introduced a new quiet failure — a cache that
stopped caching, a waiter billed for the winner, a worker exception that became
a `None` row and a `500` naming nothing.

**How to apply:** a new guard belongs in `tests/test_health_surface.py`'s
`GUARDS` table or it is not load-bearing; `python tests/test_health_surface.py
--prove-guards` must stay N/N. Trap when the mutation patches a **constant**
(e.g. the thread ceiling): capture the value at import in the test module, or
the assertion raises its own bar with the mutation and stays green.
`assertRaises` returns the exception with `.with_traceback(None)`, so use
try/except when the traceback is part of what you assert.

Related: [[crlf-text-pin-trap]] — `daedalus/health.py` and `daedalus/status.py`
are `-text`-pinned; verify `git show :<path> | tr -cd '\r' | wc -c` is 0 before
committing.
