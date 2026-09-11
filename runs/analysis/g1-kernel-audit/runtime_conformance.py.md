# daedalus/kernel/runtime_conformance.py  (182 lines)

Base 54f09753. Static read-only.

## What the file is for

Assembles and persists content-addressed "recorded conformance" evidence:
`assemble_recorded_conformance` turns a caller-supplied dict of
`RecordedObservation`s (exactly one per name in `RUNTIME_CONFORMANCE_CHECKS`)
into a canonical `RuntimeConformanceReceipt`; `persist_conformance_receipt`
writes that receipt to a digest-named file, refusing a same-name
different-content collision; `verify_current_conformance` rejects a receipt
that's bound to another manifest/revision, failed, from the future, or older
than `max_age`.

## Axis 1 — docstring truth

This is the axis the brief specifically flagged for this file: "does any
docstring claim live-runtime coverage that the code only satisfies with
fixtures?"

### CONFIRMED
None — the opposite of an overclaim. See below.

### PLAUSIBLE
None.

### Checked and honest
- Module docstring (`:1-7`): "This harness does not trust a runtime manifest's
  declarations. A caller must supply one recorded observation for **every**
  vendor-neutral fixture check." — the word "fixture" is used explicitly,
  scoping the whole module to OFFLINE FIXTURE evidence rather than claiming
  live coverage. Confirmed by the code: `assemble_recorded_conformance`
  requires `set(observations) == set(RUNTIME_CONFORMANCE_CHECKS)` exactly
  (`:71-77`, `RuntimeConformanceError` on missing or extra), so "every... check"
  is enforced by an exact-set comparison, not just claimed in prose.
- `assemble_recorded_conformance` docstring (`:70`): "Assemble an **exact**,
  content-addressed **offline fixture** receipt." — again says "offline
  fixture", not "live" — matches the master plan's Revision-3 §2 distinction
  between offline-fixture proof and live receipts, and states it rather than
  eliding it.
- Full word-list grep of this file for `authenticated|verified|verifies|
  always|guaranteed|never|enforced|cannot|impossible|all |every|only` returns
  exactly two hits: `:4` "every vendor-neutral fixture check" (checked above,
  true) and `:138` `"only an exact RuntimeConformanceReceipt can be
  persisted"` — confirmed by the `isinstance(receipt, RuntimeConformanceReceipt)`
  guard immediately above it (`:136-139`) that raises before any write.
  No instance of these words is used to imply live-runtime authority.
- `persist_conformance_receipt` docstring (`:129-135`): "a reader can refuse
  any persisted byte that no longer hashes to its own name... Same-content
  writes are idempotent; a same-name different-content write is a collision
  and is refused instead of overwritten." — confirmed at `:143-150`: filename
  is `receipt.digest`; if it exists, bytes are compared and a mismatch raises
  `RuntimeConformanceError("content-addressed receipt collision")` rather than
  overwriting; identical bytes are a silent no-op. Same pattern independently
  confirmed in `_store_artifact` (`:46-56`) for individual observation
  artifacts.
- `verify_current_conformance` docstring (`:154-161`): "Reject failed, stale,
  future or differently bound runtime evidence." — confirmed exhaustively:
  manifest-digest mismatch (`:162-163`), source-revision mismatch
  (`:164-165`), `status != "passed"` (`:166-167`), `finished > instant`
  ("from the future", `:169-171`), and `instant - finished > max_age`
  ("stale", `:172-173`) are each checked and each raises
  `RuntimeConformanceError`. No fifth case is silently accepted.

## Axis 2 — effect surface

| site (file:line) | effect | registry row | covered? |
|---|---|---|---|
| `root.mkdir(parents=True, exist_ok=True)` `:49` (`_store_artifact`) | FILESYSTEM_WRITE | none named for this module | not covered by a `daedalus.kernel...` row |
| `path.write_bytes(raw)` `:55` (`_store_artifact`) | FILESYSTEM_WRITE | none named | not covered |
| `directory.mkdir(parents=True, exist_ok=True)` `:142` (`persist_conformance_receipt`) | FILESYSTEM_WRITE | none named | not covered |
| `path.write_bytes(raw)` `:150` (`persist_conformance_receipt`) | FILESYSTEM_WRITE | none named | not covered |
| `path.exists()` / `path.read_bytes()` `:51-52,144-145` | filesystem read | none named | not covered |

### Notes
No row in `daedalus/spine/effect_boundary.py` targets
`daedalus.kernel.runtime_conformance....` — consistent with the brief's
measured fact (only 4 rows target `daedalus.kernel....`, none of them this
file). This module's actual production callers are
`daedalus/runtimes/profiles.py`, `daedalus/runtimes/live_probe_drivers.py`,
`daedalus/ikarus_oneshot.py`, and `daedalus/gates/runtime_conformance_binding.py`
(all outside `daedalus/kernel/` and outside my assigned slice) — a covering
row plausibly exists under one of those non-kernel targets, but I did not
trace `effect_boundary.py` for a row naming any of them; that check belongs to
whichever worker owns those files or the registry itself.

## Axis 3 — unreleased resources

No findings. `Path.write_bytes`/`Path.read_bytes`/`Path.exists` are one-shot
operations that open, do the I/O, and close internally — there is no
long-lived handle for this module to leak. No sqlite, no tempfile, no lock,
no subprocess, no socket anywhere in the file.

## Axis 4 — validator gaps (W4 class)

No findings. The only path construction in this file is:
- `_store_artifact`: `path = root / f"{digest}.json"` (`:50`) where `digest =
  canonical_sha(dict(payload))` (`:48`) — a computed sha256 hex digest, never
  caller-supplied text, and never passed through `_identifier` or any
  weak-regex validator at all.
- `persist_conformance_receipt`: `path = directory / f"{receipt.digest}.json"`
  (`:143`) — same pattern, `receipt.digest` is a computed content digest.

`manifest.digest`, `receipt_id`, and `trace_id` are accepted as parameters but
never used to build a path — `receipt_id` becomes a `RuntimeConformanceReceipt`
field only (`:107`), not a filename (the filename is always the *receipt's*
digest, computed independently, not the caller-supplied `receipt_id`). Checked
and confirmed not a finding, matching the brief's "used only as a dict key or
logged is not a finding" guidance — here it's a dataclass field, same class of
non-finding.

## Axis 5 — dead / duplicate

No findings. `assemble_recorded_conformance` / `persist_conformance_receipt` /
`verify_current_conformance` all have real production callers. Exact grep run:
`grep -rln "assemble_recorded_conformance\|persist_conformance_receipt\|
verify_current_conformance\|RecordedObservation(" --include=*.py daedalus/`
found `daedalus/runtimes/profiles.py`, `daedalus/runtimes/live_probe_drivers.py`,
`daedalus/ikarus_oneshot.py`, `daedalus/gates/runtime_conformance_binding.py`,
plus this file and `daedalus/kernel/__init__.py` (the lazy-module re-export,
confirmed: `runtime_conformance` is listed in `_LAZY_MODULES`,
`daedalus/kernel/__init__.py:175`). No duplicate implementation of the
content-addressed collision-refusal pattern found elsewhere in my slice (the
identical pattern appears twice *within* this file — `_store_artifact:51-53`
and `persist_conformance_receipt:144-147` — which is intentional repetition of
one small idiom, not two competing implementations of a shared concern; I
would not file this as a duplicate finding).

## OWNED-FLAG

Not applicable — this file is not `offload_lease.py`, the flagged
`attempt_execution.py` string-evidence sites, or `effects.py`.

## What I did not cover

Did not read `daedalus.kernel.contracts.runtime`
(`RUNTIME_CONFORMANCE_CHECKS`, `ConformanceCheck`, `RuntimeConformanceReceipt`,
`RuntimeManifest`) internals beyond confirming the imported names' usage shape
in this file. Did not read `daedalus/runtimes/live_probe_drivers.py` (the
module whose name most directly suggests it produces the *live* counterpart
this file's docstring distinguishes itself from) to confirm the live/offline
split holds symmetrically on that side — that module is outside my assigned
slice. Did not trace `daedalus/gates/runtime_conformance_binding.py`'s use of
`verify_current_conformance` for correctness, only that it is a real caller.
