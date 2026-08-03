# G0-RTC-06P — Unknown External Outcome Reconciliation

## Objective

Execute the canonical `runtime.effect.unknown-outcome-replay` Linux-host fault:
an external idempotent effect acknowledges durably, the worker process crashes
before terminal persistence, recovery queries the exact external idempotency key,
and the existing persisted execution is reconciled without performing the effect
a second time.

This packet adds an authenticated recovery contract and one explicit recovery
operation. It does not add a provider credential broker, trust root, attestation,
merge, promotion or Gate-closure claim.

## Recovery contract

`ExternalEffectObservation` is an HMAC-authenticated canonical record bound to:

- external provider ID;
- execution ID and idempotency key;
- exact persisted start-receipt digest;
- external acknowledgement digest;
- canonical output digests;
- exact source revision;
- observation time and issuer key;
- provenance over start, acknowledgement and outputs.

Only status `acknowledged` is accepted. Unknown issuer, tampering, future or
older-than-24-hour evidence, provider/execution/idempotency/start/scope/revision
mismatch, foreign origin/time/trace provenance, malformed fields or missing
evidence digests fail closed.

The verifier additionally binds the supplied start receipt back to the complete
`EffectExecutionRequest`: execution ID, idempotency key and request digest must
all match. A signed observation cannot be repacked around a narrower or wider
execution object.

## Reconciliation authority

`reconcile_unknown_effect()` first authenticates all observation and start
bindings. For a real persisted `STARTED` row it calls the existing
`EffectLeaseLedger.finish()` transaction with:

- outcome `COMPLETED`;
- the observation's output digests;
- the complete signed observation digest as terminal detail.

A concurrent or later replay reads the persisted terminal through a strict,
duplicate-rejecting, exact-field parser. It verifies canonical output ordering,
all identifiers/digests/timestamps, receipt digest, terminal index and state.
Only an exact terminal carrying the same start, outputs and observation digest
is returned with `reconciled=false`. `FAILED`, `CANCELLED`, foreign completion,
changed acknowledgement/output or corrupted terminal bytes cannot be rewritten.

## Host crash oracle

The Linux fixture creates distinct real effect-ledger and external-provider
SQLite files. It grants and starts one signed central Effect Lease, then launches
one child process. The child:

1. opens the external provider database with WAL, `synchronous=FULL` and bounded
   busy timeout;
2. proves the idempotency key is unused;
3. commits exactly one acknowledgement/output row under a primary-key
   constraint;
4. calls `os._exit(91)` after commit without touching the effect ledger.

The parent requires empty child stdout/stderr, return code 91, external row count
one and persisted effect state `STARTED`. It queries that row, issues the signed
observation, reconciles once, reconciles the identical observation again, then
replays the exact Effect Lease execution identity.

## Pass invariant

The observation passes as `unknown-reconciled` only when:

- catalog scenario, digest, authority, executor and expected outcome are exact;
- the child crashes only after the unique external acknowledgement is durable;
- effect state is still `STARTED` after the crash;
- external row count is exactly one before and after recovery;
- acknowledgement and output digests equal the queried external record;
- first reconciliation commits `COMPLETED` and reports `reconciled=true`;
- second reconciliation returns the byte-identical terminal with
  `reconciled=false`;
- terminal output is the exact external output digest and detail is the signed
  observation digest;
- exact Effect Lease replay returns `execute=false` and the original start
  receipt;
- no second child/provider effect is invoked;
- raw evidence contains no provider output and remains bounded.

## Evidence and counter-review

Implementation identity binds exact fixture, recovery module and production
effect-ledger bytes plus the crash code. Retained evidence contains source
identities, hashed temporary paths, child return/stdout/stderr digests, state and
row counts, acknowledgement/observation/terminal digests, reconciliation flags
and exact replay state. It excludes provider output, external payload, plaintext
paths, exception text, database contents, keys and secrets.

The independent review verifies commit-before-crash ordering, one child effect,
start-before-child and recovery-after-query ordering, exact HMAC bindings, strict
terminal parsing, real `EffectLeaseLedger.finish()`, one true and one replayed
reconciliation, immutable failed/cancelled outcomes, exact inert lease replay and
absence of trust laundering.

Focused mutations target child exit before commit, removal of idempotency
uniqueness, a second worker invocation, recovery before external query, signature
bypass, stale/revision/start-scope bypass, arbitrary terminal overwrite, changed
ack/output replay, permissive terminal parsing and active exact replay.

## Verification request and blocker

The dedicated workflow requests Ubuntu and Windows, Python 3.10 and 3.12, two
hash seeds, JSON-schema validation, Iron Plan, compile-all, focused Effect Lease,
recovery, host-runner, catalog and attestation suites, one retained real Linux
crash execution, full pytest and isolated-wheel imports.

GitHub Actions issue #67 remains an external exact-head blocker while jobs fail
before Step 1 with `steps=null` and no logs. Such runs cannot establish product,
package, platform, host-fault or Gate evidence.

Live-runtime expiry/drift evidence, protected-CAS publication, external host
attestation, remaining provider centralization and the exact-head cumulative
Gate-0 release report remain open.

Iron Plan: **ALIGNED by scope; exact-head execution required**  
Active gate: **Gate 0**  
Promotion: **not requested**
