# daedalus/kernel/authorization.py  (226 lines)

Base 54f09753. Static read-only.

## What the file is for

`NonRuntimeEffectAuthorization` — a stricter, additive capability facade over
the existing `daedalus.kernel.effects` lease/ledger machinery, for
entrypoints migrated during the "strangler" migration described in the module
docstring. It re-verifies the lease/policy/kill-switch binding fresh at every
material boundary (`verify`/`grant`/`begin_effect`/`finish_effect`) rather than
caching, and structurally refuses to represent runtime-bearing leases, forcing
callers with runtime evidence to use
`daedalus.kernel.runtime_effects.RuntimeBoundEffectAuthorization` instead.

## Axis 1 — docstring truth

### CONFIRMED
None.

### PLAUSIBLE
None.

### Checked and honest
- `:7-8` "It never issues leases, performs external effects or weakens the
  separate runtime-bound path." — **never issues leases**: no lease-minting
  code in this file; `grant()`/`begin_effect()`/`finish_effect()` all delegate
  to `self.effect_ledger.grant/begin/finish` (`:148-156,167-177,217-223`), an
  injected `EffectLeaseLedger` this class does not construct. **performs
  external effects**: this class itself calls no `subprocess`/filesystem/
  network primitive anywhere (see Axis 2). **weakens the runtime-bound path**:
  `__post_init__` (`:77-91`) raises `EffectLeaseBindingMismatch` if
  `self.lease.runtime_id` is set (`:78-81`) or if the request carries
  `runtime_manifest_sha256`/`runtime_conformance_sha256` (`:82-87`) — a
  runtime-bearing lease cannot be constructed into this class at all, so it
  cannot be weakened through it.
- `:53-55` "The facade owns every authoritative timestamp. Production callers
  cannot backdate grant, start, verification or terminalization" — confirmed:
  `_utc_now()` is called internally at every boundary (`verify` `:140`,
  `grant` `:145`, `begin_effect` `:164` and again `:183` post-start, `finish_effect`
  `:214,222`); no public method on this class accepts a caller-supplied
  timestamp parameter.
- `:55-57` "Kill-switch generation is read from an injected live authority for
  every boundary; a long-lived facade therefore cannot preserve an obsolete
  generation after revocation" — confirmed: `_read_kill_switch_generation()`
  (`:118-124`) is called fresh in `verify` (`:140`), `grant` (`:146`),
  `begin_effect` (`:165`, and again at `:184` specifically "to close the
  revocation window between the durable start commit and returning effect
  authority to the caller" per the inline comment `:180-181`), and
  `finish_effect` for the `COMPLETED` outcome (`:213-216`). No attribute caches
  the generation across calls — each call re-invokes the injected callable.
- `:158-194` `begin_effect`'s own comment "Close the revocation window between
  the durable start commit and returning effect authority" — confirmed: after
  `self.effect_ledger.begin(...)` durably commits the start receipt
  (`:167-177`), a second `_verify_at` is run (`:182-185`) and, if it raises,
  the just-started effect is immediately finished as `"cancelled"` with a
  fixed detail digest (`:186-193`) before the exception propagates — so a
  revocation landing in that window cannot leave a started-but-unaccounted
  effect.
- `:196-223` `finish_effect`'s docstring/comment: "Revocation must still allow
  FAILED/CANCELLED bookkeeping, but a successful terminal receipt... requires
  live authority" — confirmed: the live re-verify at `:212-216` is gated on
  `outcome.strip().upper() == "COMPLETED"` only; any other outcome string
  skips straight to `self.effect_ledger.finish(...)` (`:217-223`), matching
  the claim exactly.

## Axis 2 — effect surface

No direct effect sites in this file. No `subprocess.`/`os.system`/`Popen`,
no `socket`/`urllib`/`requests`/`httpx`, no `open(...)`/`Path.write_*`/`mkdir`/
`os.replace`/`shutil.*`/`sqlite3.connect`/`tempfile`, and no `os.environ`/
`os.getenv` anywhere in `authorization.py`. It is pure delegation to an
injected `effect_ledger` (`EffectLeaseLedger`, owned by `daedalus.kernel.effects`)
and an injected `kill_switch_generation_reader` callable — both of which
perform the actual effects elsewhere, out of this file's scope. No table rows;
no registry-coverage question arises for this file directly.

## Axis 3 — unreleased resources

No findings. No resource acquisition (no file handle, temp dir, lock, socket,
subprocess, or `os.open` fd) anywhere in this file.

## Axis 4 — validator gaps (W4 class)

No findings. No path, filename, sqlite path, git ref, or URL-segment
construction anywhere in this file; no `_identifier`/weak-regex validator is
imported or used here.

## Axis 5 — dead / duplicate

No findings. `NonRuntimeEffectAuthorization` has many real production callers.
Exact grep run: `grep -rln "NonRuntimeEffectAuthorization" --include=*.py daedalus/`
found 12 non-test production files, including
`daedalus/kernel/offload_lease.py`, `daedalus/kernel/effect_replay.py`,
`daedalus/kernel/runtime_effect_replay.py`,
`daedalus/chip_design/executor.py`,
`daedalus/chip_design/completion_publication.py`,
`daedalus/chip_design/publication_verifier.py`,
`daedalus/gates/repository_write_runtime_conformance.py`,
`daedalus/gates/repository_write_classification.py`,
`daedalus/gates/repository_write_effect_lease.py`, plus
`scripts/declare_write_surfaces.py`, alongside 9 test files
(`tests/kernel/test_effect_leases.py`, `tests/test_chip_eda_executor.py`,
`tests/test_chip_design.py`, etc.). Not dead code, and no duplicate
implementation of this facade's logic found elsewhere.

## OWNED-FLAG

Not applicable — this file is not `offload_lease.py`, the flagged
`attempt_execution.py` string-evidence sites, or `effects.py`. It does *use*
`daedalus.kernel.effects` (which is flagged OWNED — "just received a fix"), so
per the brief I flag rather than deep-audit that dependency: this file imports
`EffectExecutionRequest`, `EffectLeaseBindingMismatch`, `EffectLeaseLedger`,
`EffectStartResult`, `EffectTerminalReceipt`, `LeasedEffectStartReceipt`,
`verify_effect_lease` from `daedalus.kernel.effects` (`:20-28`) and delegates
all actual persistence/verification to them. I did not re-verify those
imported names' own internals since `effects.py` is owned by a different
running packet and any finding there may already be stale.

## What I did not cover

Did not audit `daedalus.kernel.effects` (`EffectLeaseLedger`,
`verify_effect_lease`) itself — flagged OWNED, see above. Did not audit
`daedalus.kernel.contracts` (`EffectLease`, `EffectLeaseRequest`) or
`daedalus.kernel.contracts.policy.PolicyDecision` internals — imported but out
of my assigned slice. Did not audit `daedalus.limit_policy.ExecutionLimitPolicy`
or `daedalus.spine.effect_boundary` (`REGISTRY_BY_ID`, `EntrypointSpec`,
`GuardDecision`) beyond confirming the import shape.
