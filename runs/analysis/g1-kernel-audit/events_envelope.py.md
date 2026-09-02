# daedalus/kernel/events/envelope.py  (860 lines)

Base 54f09753. Static read-only. Auditor: parent (W3 slice, subagent cap hit).

## What the file is for

Canonical JSON serialisation (`canonical_json`, `canonical_sha`), the in-toto
statement wrapper, and the trace-id correlation machinery (`trace_context`,
`adopt_trace`, `current_trace_id`, `stamp`). It also carries a large inventory of
which producers in the tree have been converted to carry a trace id and which
have not, with a stated reason per row.

## Axis 1 — docstring truth

### Checked and TRUE — this module actively refuses to overclaim

- `:59-61` — "**it is JSON.** Wrapping a payload in a statement verifies
  nothing, signs nothing and proves nothing." This is a module warning against
  mistaking the in-toto *shape* for a *guarantee*. It is exactly the correction
  the audit exists to make, written by the module about itself. Verified against
  `statement()`/`is_statement()`: no signature, no verification, pure dict
  construction.
- `:310-316` `current_trace_id` — "**This never mints.**" Verified: `:317-321`
  reads the ContextVar, falls back to `os.environ`, returns `env or None`. No
  id generation on any path. The accompanying reasoning is the best statement of
  the instrument-trust problem in the tree: auto-minting "would be 100%
  populated, and the join would return exactly one row every time — a
  correlation id that correlates nothing, **while LOOKING healthy**."
- `:392` `adopt_trace` — "**Never mints.**" Verified: `:405` `with _scope(trace_id,
  export_env) as tid` passes the caller's value straight through; the minting
  call `new_trace_id()` appears only in `trace_context` at `:379`.
- `:338-342` `_scope` — "Restoration is unconditional and covers the exception
  path." Verified: the restore block is in a `finally` (`:354-360`), and it
  restores both the ContextVar (`:355`) and the environment (`:356-360`),
  distinguishing "was absent" from "was present" via `had_env` (`:343`).
- `:180` — a self-correcting note that a previous count in this very docstring
  "had been wrong for some time". A module that records its own past
  documentation error is the opposite of the overclaim pattern.

### PLAUSIBLE — the env half of `_scope` is not concurrency-safe, and `export_env` defaults to True

`_scope` (`:334-360`) maintains **two** bindings with different concurrency
semantics:

- `_TRACE_VAR` is a `contextvars.ContextVar` — correct under threads and async,
  as `:304-306` says.
- `os.environ[TRACE_ID_ENV]` is **process-global** (`:345-351` set, `:356-360`
  restore).

With two concurrent `trace_context` scopes in different threads (and
`export_env` defaults to `True` at `:376` and `:390`), the interleaving
set-A / set-B / restore-A / restore-B leaves `DAEDALUS_TRACE_ID` holding A's
value after A has exited, or B's value restored to A's. Any `subprocess` spawned
in that window inherits the wrong trace id, and `current_trace_id()` falls back
to the environment (`:320`) whenever the ContextVar is unset — so a thread
without its own binding can read another thread's id.

The consequence is precisely the failure the module argues is the worst one:
`:338-342` says "a leaked trace id is worse than no trace at all: it would
silently glue the NEXT run's records onto this one's, producing a join that looks
complete and is wrong." The restore logic prevents that **sequentially** but not
**concurrently**.

I am filing this PLAUSIBLE rather than CONFIRMED because I did not establish that
two `trace_context` scopes actually run concurrently in-process today — that
requires tracing the callers, which spans modules outside this slice. The code
defect (a process-global mutated under a per-context abstraction) is visible in
the file; the reachability is not proven here. The docstring at `:304-306` is
careful to scope "correct under threads and async" to the ContextVar step only,
so this is a gap in the mechanism, not a false statement.

## Axis 2 — effect surface

| site | effect | registry row | covered |
| --- | --- | --- | --- |
| `:320` `os.environ.get(TRACE_ID_ENV)` | env read | none | no |
| `:343` `TRACE_ID_ENV in os.environ`, `:344` `os.environ.get` | env read | none | no |
| `:347` `os.environ[TRACE_ID_ENV] = ...` | **env write** | none | no |
| `:351` / `:360` `os.environ.pop(...)` | **env write** | none | no |
| `:358` `os.environ[TRACE_ID_ENV] = prior_env or ""` | **env write** | none | no |

No filesystem writes, no subprocess spawn, no network in this module.

The environment *writes* are the notable entry: `Effect` (`effect_boundary.py:43-51`)
has no `ENVIRONMENT_MUTATION` member, so process-environment mutation is not a
modellable effect in the registry at all. That is an inventory-model gap rather
than a defect in this file — the mutation here is deliberate, documented
(`:380` "``export_env`` also sets ``DAEDALUS_TRACE_ID`` so children inherit it"),
and restored in a `finally`. Worth surfacing because the environment is the
channel by which state crosses the `subprocess` boundary that the registry *does*
model (`Effect.PROCESS_SPAWN`).

## Axis 3 — unreleased resources

Clean. The only acquire/release pair is `_scope`'s ContextVar token plus the
environment snapshot, and both are restored in a `finally` (`:354-360`).
`_TRACE_VAR.reset(token)` is called unconditionally at `:355` before the
conditional env restore, so an exception in the env restore still leaves the
ContextVar correct.

`bind_trace_id` (`:324-331`) returns a reset token and does **not** restore —
but that is the documented escape hatch ("for a caller whose run does not fit a
`with` block"), and the docstring steers callers to `trace_context` first. Not a
finding.

## Axis 4 — validator gaps (W4 class)

No `_identifier` use, no path construction. `canonical_json` (`:246-259`) raises
on non-JSON-serialisable values rather than coercing, which is the correct
fail-closed posture for a function whose output feeds `canonical_sha` and every
stored digest.

One note for the canonicalisation question W1 is chasing: `canonical_json` is
described at `:246` as "The single serialisation used for **every** stored blob
and **every** digest." That universal is the kind W1 should enumerate against
`contracts/canonical.py`, which imports it (`canonical.py:18`). Handing off.

## Axis 5 — dead / duplicate

The `CONVERTED_PRODUCERS` / `UNCONVERTED_PRODUCERS` tables (`:638-840`) are an
in-code inventory of trace-id adoption with a per-row justification. This is a
**producer/consumer seam artefact worth flagging positively**: it is the rare
case where an unwired path is documented as unwired *with its cost*, rather than
silently absent. `:666` explicitly labels the second table "Producers NOT wired,
each with the reason it is affordable to defer."

I did not verify that those tables still match the tree — the module itself
records at `:180` that a previous count in this docstring drifted. Re-verifying
the two tables against the current tree is worthwhile follow-up work but is a
separate mechanical task, and I am not claiming either way.

## What I did not cover

- Whether `CONVERTED_PRODUCERS`/`UNCONVERTED_PRODUCERS` are currently accurate.
- Whether two `trace_context` scopes run concurrently in-process (the
  reachability half of the PLAUSIBLE finding above).
