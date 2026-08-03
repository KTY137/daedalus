# G0-RTC-06O — Runtime trust writer-lock fault

## Objective

Close the production broker gap recorded in issue #71: a SQLite writer-lock failure while acquiring the terminal runtime-trust fence must not escape as a raw storage exception after provider execution. The broker must withhold the provider value, durably cancel the already-started effect execution, and expose only a typed trust-fence failure.

This packet is stacked on the selected linear Gate-0 fault line after the effect-ledger contention packet. It does not merge, promote, attest a host observation, or close Gate 0.

## Production change

`daedalus.runtimes.broker._finish_completed_under_runtime_fence()` now:

1. treats trust-ledger connection and `BEGIN IMMEDIATE` acquisition as one explicit boundary;
2. translates `sqlite3.Error` from that boundary into `RuntimeProviderTrustFenceError`;
3. retains the original SQLite exception only as the chained cause;
4. uses a constant public error message and never copies SQLite exception text into retained evidence;
5. safely handles the case where no connection was returned;
6. preserves the existing `run_runtime_provider()` path that routes every typed terminal-fence failure through `_cancel_for_trust_loss()` before re-raising.

The effect and trust ledgers remain separate SQLite authorities. No cross-database atomicity is claimed.

## Real contention regression

The focused regression uses:

- the production `RuntimeTrustLedger` schema and authenticated records;
- the production `RuntimeBoundEffectAuthorization`;
- the production `EffectLeaseLedger` grant, start, and terminal state transitions;
- one real second SQLite connection holding `BEGIN IMMEDIATE` on the trust ledger;
- a test-only trust-ledger subclass whose sole semantic change is a 125 ms busy timeout.

The provider and evidence callback are allowed to run before the terminal fence, matching the real failure window. The test passes only when:

- the broker raises `RuntimeProviderTrustFenceError`, not raw `sqlite3.OperationalError`;
- the original SQLite error remains the chained cause;
- the public error text contains no SQLite lock message;
- the provider result is not returned;
- the exact effect execution reaches durable `CANCELLED` state.

A second focused regression explicitly kills the mutation that removes the SQLite-to-trust-fence translation: that mutation restores a raw SQLite escape and fails the typed-exception assertion.

## Independent counter-review perspective

A separate AST-based review test checks the production source rather than reusing the builder oracle. It requires:

- exactly one `sqlite3.Error` acquisition handler;
- an explicit `RuntimeProviderTrustFenceError` raised with the original exception as `__cause__`;
- a constant, message-free public error;
- the broker-level catch to call `_cancel_for_trust_loss()` with phase `terminal-runtime-fence` and then re-raise;
- no `str`, `repr`, or f-string laundering of SQLite exception text in the acquisition handler.

This executable review is additional regression evidence, not an independent human approval or host attestation.

## Requested verification

The dedicated workflow requests:

- Ubuntu and Windows;
- Python 3.10 and 3.12;
- `PYTHONHASHSEED=0` and `123456`;
- Iron Plan verification and `compileall`;
- the new real-contention and counter-review tests;
- existing terminal-fence, broker, runtime-admission, trust-store, and Effect-Lease suites;
- full repository pytest on Ubuntu/Python 3.12;
- isolated wheel build, install, and broker import outside the checkout.

GitHub Actions issue #67 remains an external exact-head verification blocker while jobs fail before Step 1 with no steps or logs. No zero-step run is treated as product evidence, and this packet must remain draft until executable exact-head CI exists.

## Remaining boundary

This packet repairs and tests the production cancellation path. Publication of a canonical `runtime.trust-ledger.lock-contention` host-fault observation into protected CAS, external host attestation, remaining runtime scenarios, provider centralization, exact-head release reporting, independent security approval, and owner closure remain separate Gate-0 work.

Iron Plan: **ALIGNED by scope; exact-head execution required**  
Active gate: **Gate 0**  
Promotion: **not requested**
