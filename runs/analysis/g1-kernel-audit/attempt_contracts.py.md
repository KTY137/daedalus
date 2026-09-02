# daedalus/kernel/attempt_contracts.py  (352 lines)

Base 54f09753. Static read-only. Auditor: parent (W6 slice, subagent cap hit).

## What the file is for

Defines the frozen dataclasses for one Attempt lifecycle — `AttemptStartRecord`,
`AttemptTerminalReceipt`, `AttemptCompletion`, `AttemptBeginResult`,
`PreparedAttempt` — plus the exception hierarchy and a handful of module-private
helpers (`_workspace_relative_path`, `_is_same_or_within`, `_effect_key`,
`_strict_json`, `_path_identity`). It validates and binds; it performs no I/O.

## Axis 1 — docstring truth

### Checked and honest

- `:104` "Durable intent to materialize and execute one exact Attempt once."
  The "once" is not enforced here but by the unique index in
  `attempt_ledger.py:99-104`; the record itself does bind exactly its inputs
  (`:147-158`), so the claim is not made false by this file.
- `:168` / `:258` `same_subject` — "Compare replay identity while retaining the
  first persisted timestamp." Verified: both tuples at `:169-185` and `:259-279`
  omit the timestamp field (`started_at` / `completed_at`) and include every
  other field. Enumerated, correct.
- `:41` `AttemptBindingMismatch` and `:45` `AttemptReplay` docstrings match the
  sites that raise them in `attempt_ledger.py`.

### No findings

No `always` / `guaranteed` / `authenticated` / `never` claims in this module.
The docstrings are terse and describe structure rather than promising
properties. This is the honest end of the spectrum.

## Axis 2 — effect surface

No effect sites. The module imports `os` (`:5`) and `json` (`:4`); `os` is used
only for `os.path.normcase` in `_path_identity` (`:63`) and `json` only for
`json.loads` in `_strict_json` (`:94`). No writes, no spawns, no network, no
`os.environ` read. Correctly absent from the Effect Registry.

## Axis 3 — unreleased resources

None. The module acquires no connections, handles, locks, or temp objects.

## Axis 4 — validator gaps (W4 class)

This is the file the W4 report's F-W4-01 chain runs through, and my measurement
**partially refutes that finding**. See the detailed writeup in
`attempt_workspace.py.md`; the part that belongs here:

### CONFIRMED — the `..` traversal is blocked in this file, at `:135`

`_workspace_relative_path` (`:67-68`) interpolates the weakly-validated
`attempt.attempt_id` into a path string:

```python
return f"attempts/{attempt.attempt_id}-{attempt.digest[:16]}"
```

That string is untrusted at this point. But it is passed to
`AttemptLedger.begin(workspace_relative_path=...)`, which constructs
`AttemptStartRecord`, whose `__post_init__` runs at `:135`:

```python
relative = _repo_path(self.workspace_relative_path, "workspace_relative_path")
if relative == "." or not relative.startswith("attempts/"):
    raise ValueError("workspace_relative_path must be below attempts/")
```

`_repo_path` (contracts/canonical.py:124) rejects any `..` part. Measured with
`.venv/Scripts/python.exe`: `PurePosixPath('attempts/x/../../../tmp/e-d').parts`
== `('attempts','x','..','..','..','tmp','e-d')`, so `any(part == "..")` is True
and the constructor raises. This happens **before** the `joinpath` in
`attempt_workspace.py:247` (see that dossier for the ordering proof).

So `_workspace_relative_path` is a weak-validator-into-path site, but it is
guarded downstream. Reporting it as an unguarded traversal would be wrong.

### CONFIRMED — recorded path and constructed path are produced by different code

`AttemptStartRecord.workspace_relative_path` stores the **normalized** result of
`_repo_path` (`:135-138`), while `attempt_workspace.py:247` builds the actual
filesystem path by splitting the **raw** f-string from `:68`. `PurePosixPath`
normalization is not the identity: measured, `'attempts/x/./y-d'` normalizes to
`'attempts/x/y-d'` and `'attempts//x-d'` to `'attempts/x-d'`. `_ID_RE` permits
both `.` and `/` in an `attempt_id`, so both inputs are constructible.

Impact is low — the two strings resolve to the same filesystem location, so this
is a provenance-fidelity defect (the ledger records a path string that is not
byte-identical to the one the code used), not an escape. Fixing it is a
one-liner: use `begin.start.workspace_relative_path` at `attempt_workspace.py:247`.

### `_effect_key` (`:71-72`)

Re-validates through `_identifier` and prefixes with `"attempt-lifecycle:"`.
The result is used as a SQL bound parameter (`attempt_ledger.py:150`, `:290`),
never as a path. Not a finding.

## Axis 5 — dead / duplicate

- `_path_identity` (`:62-64`) — **zero callers.** Grep run:
  `grep -rn "_path_identity" --include=*.py daedalus/ tests/ scripts/ tools/`
  (copy dirs excluded). It returns 80 lines, but every one of them belongs to a
  *different* function of the same or a similar name; `attempt_contracts.py:62`
  is the sole occurrence of this definition and has no call site in `daedalus/`,
  `tests/`, `scripts/`, or `tools/`. It is also absent from `__all__`
  (`:341-352`), and its docstring promises no reader.

  The live equivalent is `_workspace_root_identity` (`attempt_workspace.py:29-53`,
  3 call sites), which additionally binds `st_dev`/`st_ino`. Both use a
  `daedalus-attempt-workspace...` schema, so `_path_identity` is the **weaker
  superseded twin**. Per the brief, zero callers is a finding, not a verdict:
  the argument for deleting it is that a weaker path-identity helper sitting one
  import away from the strong one invites the wrong call, not merely that it is
  currently unused.

- **Duplicate family (repo-wide, beyond this file).** The same grep enumerates
  **five independent implementations of "path identity"**, each with its own
  normalization and follow/no-follow semantics:
  1. `daedalus/kernel/attempt_contracts.py:62` `_path_identity` — `resolve()` +
     `normcase`, follows links. Zero callers.
  2. `daedalus/kairos/worktree.py:234` `_path_identity` — `os.lstat`-based,
     deliberately **no-follow** (see its own comment at `:842` recording that an
     earlier `os.stat` version followed a junction).
  3. `daedalus/runtimes/provider_target_receipt_retention_completed_evidence.py:144`
     `_path_identity` — returns a dict, different contract entirely.
  4. `daedalus/chip_design/manifest.py:115` `canonical_path_identity` —
     `abspath`→`realpath`→strip `\\?\`→`normcase`; the most-used one (~40 call
     sites across `chip_design/`).
  5. `daedalus/spine/killswitch.py:581` `_literal_path_identity`.

  Constitution §5 asks for one canonical path per responsibility. Five
  path-identity functions with differing symlink semantics is the kind of
  divergence that produces a containment bug at whichever site picked the
  weakest one. Filed as a structural Axis-5 observation, **PLAUSIBLE** as a
  defect (I did not prove any specific site picked the wrong one) — but the
  count itself is CONFIRMED and enumerated above.
- `_is_same_or_within` (`:75-76`) — used, see `attempt_workspace.py.md`.

## What I did not cover

Whether `attempt_execution.py` constructs these records on a second path — that
file is owned by the running chip-refusal packet and was flagged, not audited.
