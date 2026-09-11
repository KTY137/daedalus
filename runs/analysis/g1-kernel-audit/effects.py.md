# daedalus/kernel/effects.py  (1024 lines)

Base 54f09753. Static read-only.

## OWNED-FLAG

Per the shared brief, this file "just received a fix" from another running
packet — flagged rather than deep-audited. One-line observations only, no
full case-building; any of these may already be stale.

- OWNED-FLAG — `_initialize` (:568-631) and the other five sqlite
  `connect`/`close` sites in this file (:631, :700, :729, :858, :935/948) all
  now follow the `conn = self._connect(); try: ...; finally: conn.close()`
  shape, consistent with the fixed reference pattern the brief cites — looks
  correctly and uniformly applied across the file, not just at the one
  documented site.
- OWNED-FLAG — `_parse_utc` (:223-230) catches only `ValueError`, not
  `AttributeError`, on `datetime.fromisoformat(value.replace(...))`; a
  sibling copy in `runtime_effects.py:78-83` (this audit's other slice) does
  catch `AttributeError` too. Worth a second look for whether a non-string
  value can ever reach this function unvalidated — I did not find a reachable
  call site in my own slice, so this is not asserted as exploitable.
- OWNED-FLAG — `_secret_bytes`/`_signature` (:243-253) are duplicated
  (not imported) into both `effect_recovery.py:205-217` and
  `runtime_effects.py:86-96` in this audit's slice; worth deciding whether
  this file should become the single importable source now that a fix just
  touched it.
- OWNED-FLAG — module docstring "the lease layer is deliberately inert with
  respect to real effects" (:3) and "refuses to issue leases for rows that
  are not already marked `CENTRAL`" (:8) were read but not independently
  re-verified against the registry-membership check code path; left for the
  packet currently owning this file.
- OWNED-FLAG — did not enumerate this file's own Axis 2 effect-surface table
  (subprocess/network/fs-write/env sites) or Axis 4 identifier-to-path chains
  in depth; the six sqlite connect sites above are the only Axis-3-relevant
  sites I looked at, specifically because they are the pattern the brief
  named as the reference case.

## What I did not cover

Everything else — full docstring sweep, effect-registry cross-reference,
Axis 4 validator-chain tracing, and Axis 5 dead/duplicate analysis for this
file were intentionally skipped per the brief's instruction to flag rather
than deep-audit an actively-owned file. See the other four dossiers in this
slice (`effect_recovery.py.md`, `effect_replay.py.md`, `runtime_effects.py.md`,
`runtime_effect_replay.py.md`) for where this file's exports are consumed and
what those dossiers had to trust about it.
