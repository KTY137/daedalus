# daedalus/kernel/attempt_clock.py  (59 lines)

Base 54f09753. Static read-only. Auditor: parent (W6 slice, subagent cap hit).

## What the file is for

`AttemptLifecycleClock` produces the timestamps that go into Attempt lifecycle
records, so that caller-supplied time can be ignored. It samples wall time once
at construction, advances it from `time.monotonic_ns`, clamps the projection
back to the live wall clock, then applies a caller-supplied `minimum` floor and
a last-observation floor.

## Axis 1 — docstring truth

This 59-line file carries the densest claim-per-line ratio in the slice.

### Checked and honest

- `:12` "Produce nondecreasing UTC timestamps **without accepting caller time**."
  The `minimum` parameter (`:42`) *is* caller-supplied, which looks like a
  contradiction — but it is used only as a **floor** (`:49-52`: `if current <=
  minimum_value: current = minimum_value + 1µs`), so it can only move an
  observation forward. It cannot be used to backdate. The docstring discloses it
  explicitly at `:15-18`. Honest, and the distinction is the right one.
- `:19-28` the clamp paragraph. It claims (a) the clamp "only ever moves an
  observation backwards toward the wall clock", and (b) "the `minimum` and
  last-observation floors are applied afterwards, so the anti-rollback guarantee
  above still wins." Verified against `now()` line by line: the clamp is
  `:47-48` (`if wall_now < current: current = wall_now` — strictly backwards
  only), the `minimum` floor is `:49-52`, the `_last` floor is `:53-54`. The
  ordering the docstring asserts is exactly the ordering in the code, and
  because `_last` is applied last the output is strictly increasing regardless
  of what the clamp did. **Claim (a) and (b) both hold.**
  This is a good example of the honest end of the spectrum: a subtle ordering
  property, stated precisely, and implemented in the stated order.
- `:14-15` "Wall time is sampled once when the trusted kernel object is
  constructed" — `:32-33`, exactly once, in `__init__`.

### PLAUSIBLE — "nondecreasing" is per-instance, and the docstring does not say so

`_last` (`:34`) and `_lock` (`:35`) are **instance** state. The monotonicity
guarantee therefore holds per `AttemptLifecycleClock` object, not per process,
per event store, or per attempt_id. The docstring's "Produce nondecreasing UTC
timestamps" is unscoped and reads as a global property.

Where this becomes reachable: `AttemptLedger.__init__` constructs a **fresh**
clock at `attempt_ledger.py:81`. So every `AttemptLedger` instance — and every
process restart — starts a new clock whose `_last` is reset to
`wall_anchor - 1µs` (`:34`). Two ledgers open on the same spine file in one
process, or one ledger after a restart, share no `_last`.

Consequences, traced:

- `complete` passes `minimum=start.started_at` (`attempt_ledger.py:350`), so a
  terminal timestamp is floored by its own persisted start. **Protected.**
- `begin` calls `self._clock.now()` with **no** `minimum`
  (`attempt_ledger.py:256`). So after a backwards host-wall-clock movement plus
  a restart, a new attempt's `started_at` can precede an already-persisted
  attempt's `started_at`.

Impact is low: the guard at `attempt_ledger.py:139-144` only compares a start
against its own Event-Store row's `created_ts`, and I found no invariant that
depends on cross-attempt start ordering. So this is a docstring-scope defect
with a real but currently harmless mechanism, filed **PLAUSIBLE**. The honest
fix is one word in the docstring ("per clock instance"), not new machinery.

## Axis 2 — effect surface

None. Imports are `threading`, `time`, `datetime` (`:4-6`). No filesystem, no
subprocess, no network, no `os.environ`. `datetime.now(timezone.utc)` (`:32`,
`:46`) is a clock read, not an effect. Correctly absent from the Effect Registry.

## Axis 3 — unreleased resources

Clean. The one resource is `self._lock`, acquired with `with self._lock:` at
`:43` covering the whole body of `now()`. `with` on a `threading.Lock` releases
on the exception path, and the only statement inside that can raise is
`self._parse(minimum)` (`:50`, via `_utc_timestamp` on a malformed string) —
which the `with` correctly covers. No leak.

Note this is the counter-example to the sqlite pattern: `with` on a `Lock` *does*
release, whereas `with` on a `sqlite3.Connection` does *not* close. Same keyword,
different contract — which is exactly why `effects.py::_initialize:576-588` had
to be written.

## Axis 4 — validator gaps (W4 class)

Not applicable — no identifiers, no path construction. The one validator used is
`_utc_timestamp` (`:39`), imported from `contracts/base`, applied to the
caller-supplied `minimum` before it is parsed. Correct: the untrusted string is
validated before `datetime.fromisoformat` sees it.

## Axis 5 — dead / duplicate

`AttemptLifecycleClock` — grep run:
`grep -rn "AttemptLifecycleClock" --include=*.py daedalus/ tests/ scripts/ tools/`
→ 14 hits. Production use is real: defined at `:11`, imported at
`attempt_ledger.py:29`, instantiated at `attempt_ledger.py:81`. Not dead.

No duplicate clock implementation found in the slice.

## What I did not cover

Whether other kernel subsystems (promotion, offload_lease) implement their own
monotonic clock rather than reusing this one — that spans W8/W9/W10 files.
