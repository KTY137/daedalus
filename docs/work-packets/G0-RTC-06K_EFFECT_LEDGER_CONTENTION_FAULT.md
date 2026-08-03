# G0-RTC-06K — Effect-ledger lock contention fault

## Objective

Execute the canonical `runtime.effect-ledger.lock-contention` Linux-host fault
against the real persisted `EffectLeaseLedger.begin()` transaction and prove
that a writer lock held past the configured fixture busy timeout refuses the
effect before any provider work or durable start receipt exists.

This packet is based on `g0/linux-process-fault-executors`. It is independent of
the sandbox-unavailable sibling, changes no production entrypoint, creates no
runtime trust, merges nothing, promotes nothing and does not close Gate 0.

## Boundary under test

The fixture creates one valid central entrypoint, exact EffectScope,
PolicyDecision, signed EffectLease and persisted lease grant. It then:

1. opens a second SQLite connection to the same effect ledger;
2. acquires `BEGIN IMMEDIATE`, verifies that the connection is in a transaction,
   and retains that writer lock;
3. calls the inherited production `EffectLeaseLedger.begin()` logic through a
   test-only subclass whose only behavioral change is a bounded 125 ms SQLite
   busy timeout;
4. releases the external lock only after begin has returned or raised;
5. queries the durable ledger after lock release.

The shortened timeout is a host-fixture control, not a new production authority.
The test subclass may override only `__init__` and `_connect`; grant, begin,
replay, scope, signature, registry, start-receipt and persistence behavior remain
the production methods. Its connection setup closes the descriptor if a SQLite
PRAGMA fails before the inherited transaction begins.

## Pass criteria

The observation is `passed/refused-before-start` only when all are true:

- `blocker.in_transaction` proves the external writer lock was active before the
  effect start was attempted;
- a real `sqlite3.OperationalError` is classified as SQLite BUSY/LOCKED by base
  numeric error code, including extended SQLite codes, or by the Python-3.10
  compatibility fallback;
- the elapsed interval reaches at least busy timeout minus a bounded 25 ms clock
  tolerance and remains below five seconds;
- the provider dispatch sentinel remains false;
- no row exists for the attempted execution ID after the writer lock is
  released;
- the exact catalog scenario, executor locator and expected outcome match;
- the executor implementation digest binds both fixture bytes and the exact
  production `daedalus/kernel/effects.py` bytes.

An unrecognized OperationalError, inactive writer transaction, successful begin,
persisted execution row, provider-dispatch sentinel, premature return or
excessive delay fails the fault.

## Evidence discipline

Raw evidence retains:

- canonical scenario and executor digests;
- effect-ledger source digest;
- database-path digest, never the plaintext temporary path;
- active-writer-lock flag, configured busy timeout and elapsed milliseconds;
- exception module/type and numeric SQLite error code when available;
- provider-dispatch sentinel and durable execution-row count.

The SQLite exception message is used only for Python 3.10 BUSY/LOCKED
classification when no numeric code is exposed and is never retained. Published
summary material hard-codes `trusted=false`, `attested=false` and
`gate_closure_claimed=false`. External RuntimeFaultAttestation is still required
before this observation may contribute to the trusted Gate-0 fault digest set.

## Adversarial review

The independent counter-review requires:

- no subprocess, shell or provider effect in the fixture;
- the bounded subclass overrides only connection creation and timeout;
- the real inherited `ledger.begin()` method is called;
- the writer transaction is `BEGIN IMMEDIATE` and is proven active;
- only `sqlite3.OperationalError` is treated as the expected injected fault;
- no broad `Exception` or `BaseException` laundering;
- no plaintext database path or SQLite exception text in evidence;
- exact catalog and production-source binding;
- candidate-controlled summaries cannot claim trust, attestation or gate closure.

Targeted mutations include removing the writer lock, releasing it before begin,
accepting any exception, reducing the elapsed threshold, setting the provider
sentinel after a failed begin, ignoring a persisted execution row, removing the
source digest, or publishing the database path/message.

## Requested verification

The dedicated workflow requests:

- Ubuntu and Windows contract jobs;
- Python 3.10 and 3.12;
- hash seeds 0 and 123456;
- Iron Plan and compileall;
- the original EffectLease suite;
- deterministic host-fault and independent AST/evidence review tests;
- exact-head retained untrusted Linux-host evidence;
- full repository pytest on Ubuntu/Python 3.12;
- isolated wheel build/install/import outside the checkout.

A workflow with no recorded first step or logs is infrastructure evidence only.
Exact-head execution remains blocked while issue #67 persists.

## Deliberate remaining blockers

- the production ledger still exposes a fixed 30-second timeout and raw SQLite
  OperationalError; this packet proves the refusal invariant but does not create
  a second production contention exception authority;
- runtime-trust-ledger contention remains a separate scenario;
- external host-attestation authority and protected-CAS publication are absent;
- the cumulative fault digest and exact-head Gate-0 release report remain open.

Iron Plan: **ALIGNED by scope; exact-head execution blocked by #67**  
Active gate: **Gate 0**  
Promotion: **not requested**
