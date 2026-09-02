# daedalus/kernel/policy/ledger.py  (1459 lines)

Base 54f09753. Static read-only. Auditor: parent (W4 slice, subagent cap hit).

## What the file is for

The money path. Owns the period budget ledger (a JSON file replaced atomically
under a cross-process lock), the `_BudgetLock` primitive, `SpendEnvelope`
(a second, tighter per-lease ceiling), and the reservation/close accounting that
`price_call` estimates feed.

## Axis 1 — docstring truth

**This is the most honest file I audited, and the finding worth recording is
that its strongest claims are true.** Two examples, both load-bearing:

### `_BudgetLock` — a deliberate inversion, stated and implemented

`:240-256`:

> "…same primitives as ``runs/council/room.py::_RoomLock``… with ONE DELIBERATE
> INVERSION. ``_RoomLock`` degrades to a NO-OP when the lock cannot be taken, on
> the reasoning that 'losing serialisation is bad, losing the human's message is
> worse'. **For money that reasoning runs backwards.** Two processes that both
> read 'remaining: $0.50' and both spend it have spent $1.00 against a $0.50
> ceiling… So an unobtainable lock here RAISES `BudgetUnavailable`, which the
> caller must treat as a refusal."

Verified — both failure paths raise, neither degrades:

- cannot open the lock file → `raise BudgetUnavailable(...)` at `:269-272`
  ("refusing to spend without serialisation");
- cannot acquire within `timeout_s` → closes the handle and
  `raise BudgetUnavailable(...)` at `:290-294` ("Refusing rather than spending
  unserialised").

There is no code path that proceeds without the lock. The docstring also
explains *why the lock file is separate from the ledger file* (`:254-256`: on
Windows you cannot replace a file another handle holds open) — a real
platform constraint, correctly stated.

### `SpendEnvelope` — names the exact boundary of its own coverage

`:488-496`:

> "ATTRIBUTION — and its exact boundary. A reservation is charged to this
> envelope when the reserving process is the one that opened it (same pid) or
> when the envelope's id is in ``DAEDALUS_BUDGET_ENVELOPE``… **It does NOT cover
> a child spawned with a scrubbed environment from a different pid, and it
> cannot: this module has no way to observe a spend it never sees.**"

That is the correct, complete statement of the limitation — a spend brake covers
only the metered path — written by the module about itself rather than
discovered by an auditor. `:459-467` similarly documents the *historical* gap it
was built to close (an Effect Lease's `max_cost_microusd` was compared claim-to-
claim in `effects.py` and never subtracted, so "a wave leased for $0.25 could
spend $4.99 without one refusal").

### Checked and honest

- `:517-521` "CLOSED ON EVERY EXIT INCLUDING A RAISE." Verified: `__exit__`
  (`:530-538`) calls `self.close(...)` unconditionally after restoring the
  environment, with a reason distinguishing normal exit from
  `f"scope raised {exc[0].__name__}"`.
- `:117-121` — the comment explaining that `ExceededCeiling` defaults its
  "which ceiling refused" field to `None` so existing raise sites are unchanged,
  rather than "reporting the day's cap for a wave that never came near it."
  Precision about not misattributing a refusal.

**No overclaims found in this module.**

## Axis 2 — effect surface

| site | effect | registry row | covered |
| --- | --- | --- | --- |
| `:266` `self.path.parent.mkdir(parents=True, exist_ok=True)` | FILESYSTEM_WRITE | none | no |
| `:267` `open(self.path, "a+b")` (lock file) | FILESYSTEM_WRITE | none | no |
| `:977-981` `tmp.write_text(...)` + `os.replace(tmp, self.path)` | FILESYSTEM_WRITE | none | no |
| `:527` `os.environ[ENV_ENVELOPE] = ...`, `:532/:534` restore | **env write** | none | no |
| `:523`, `:543`, `:577`, `:592`, `:607`, `:641`, `:702`, `:725` `os.environ.get(...)` | env read | none | no |

Env vars this module reads: `DAEDALUS_BUDGET_LEDGER` (`:34`),
`DAEDALUS_BUDGET_PERIOD` (`:37`), `DAEDALUS_BUDGET_ENVELOPE` (`:42`), and
`DAEDALUS_EXECUTION_LIMIT_POLICY` (`:702`).

None of the 4 kernel Effect Registry rows (`effect_boundary.py:350, 372, 394,
2304`, all declaring only `Effect.FILESYSTEM_WRITE`) covers this module. Note
`Effect` (`effect_boundary.py:43-51`) *does* have a `SPEND` member — so the
registry can model spend, and the module that owns spend has no row.

The ledger write at `:977-981` is properly atomic (temp file + `os.replace`) and
happens under `_BudgetLock`, so this is an inventory gap, not a correctness one.

## Axis 3 — unreleased resources

### PLAUSIBLE — `_BudgetLock.__enter__` leaks the lock file handle on a non-`OSError`

`:264-294`. The handle is opened at `:267` and every *expected* failure is
handled: the open is wrapped in `except OSError` (`:268-272`), and the acquire
loop catches `OSError` (`:279-280`) and closes the handle before raising on
timeout (`:284-288`).

The gap is `_acquire` (`:296-309`), which does:

```python
self._fh.seek(0)
if os.name == "nt":
    import msvcrt          # :301
    msvcrt.locking(...)
else:
    import fcntl           # :306
    fcntl.flock(...)
```

`import msvcrt` / `import fcntl` raise `ImportError`, not `OSError`.
`self._fh.seek(0)` raises `ValueError` on a closed file. Neither is caught by
the `except OSError` at `:279`, so the exception propagates out of `__enter__` —
and because `__enter__` raised, `__exit__` never runs, so `self._fh` stays open
and is closed only by the garbage collector.

Applying this audit's own standard (read the callee before writing CONFIRMED):
I read `_acquire` and the two stdlib calls, and the exception types are right,
but the probability is low — `msvcrt` on Windows and `fcntl` on POSIX are
stdlib and present. So this is a genuine unguarded-acquisition shape on an
unlikely path, filed **PLAUSIBLE**. The fix is one line: `except Exception` in
place of `except OSError` around the acquire loop, or a `try/finally` around the
whole `__enter__` body.

Contrast with the CONFIRMED leak found elsewhere (`events/ledger.py:338-343`),
where the module's own `[MEASURED]` note proves the failure path fires in 14/40
runs. That one matters; this one is hygiene.

### Checked and clean

`__exit__` (`:305-323`) releases the OS lock and closes the handle, each in its
own `try/except OSError: pass`, so a failure to unlock still closes and a
failure to close still nulls the handle. Correct for a release path.

## Axis 4 — validator gaps (W4 class)

No `_identifier` use. Two env-controlled paths:

- `ENV_LEDGER` → `os.environ.get(ENV_LEDGER) or DEFAULT_LEDGER_PATH` (`:641`) —
  an unvalidated env-controlled filesystem path. Operator-controlled, not
  candidate-reachable, so outside the W4 threat class.
- `ENV_ENVELOPE` (`:543`) is parsed into a set of id strings and only ever
  compared for membership (`_env_envelope_ids`), never used to build a path.

## Axis 5 — dead / duplicate

Not assessed in depth — at 1459 lines this file needed prioritising, and I spent
the budget on Axes 1–3 where the money-path risk concentrates. The
`_BudgetLock` / `runs/council/room.py::_RoomLock` relationship is a deliberate
*divergent* reimplementation (documented at `:240-252`), not an accidental
duplicate: same primitives, deliberately opposite failure posture. That is the
correct way to have two similar things.

## What I did not cover

- Axis 5 systematically (see above).
- The reservation/close accounting arithmetic (`:640-1000`+) — whether holds,
  draws and releases actually balance. That is a correctness question needing
  either tests or careful line-by-line reading of ~350 lines, and this audit is
  static and time-boxed. **It is the highest-value unaudited area in my
  slice**, because the honesty of the docstrings does not by itself prove the
  arithmetic.
