# G0-RTC-06Q — Post-Provider Output-Evidence Failure Remains Unknown

## Finding and parent

This packet repairs repository issue #123 on a short-lived branch based on exact parent `bbb0aef26b5fb6c6abc746f5f322cc0235f39e21` from `g0/repository-write-effect-lease-replay-linear`.

The previous broker behavior called the external provider, received a normal return, and then persisted `FAILED` when the local `output_digests(value)` callback raised or returned malformed evidence. A normal provider return means the external effect may already be committed or acknowledged. Local evidence failure cannot prove that the external effect failed. Persisting `FAILED` removed the execution from the `STARTED` reconciliation path and made a duplicate external effect possible under a fresh execution identity.

## Narrow correction

After `invoke()` returns, failure to call or normalize `output_digests(value)` now raises `RuntimeProviderReconciliationRequired` without calling any terminal writer. The exact persisted execution remains `STARTED`.

The exception exposes only the entrypoint, runtime identity, exact start receipt, fixed phase and a digest of the local exception class. It does not retain the provider value and does not persist raw exception text. The exception grants no recovery, retry, provider or promotion authority.

A retry with the exact execution identity reaches the existing inert replay path before provider or output-evidence callbacks.

Completion goes through `reconcile_runtime_provider_unknown(...)`. That adapter authenticates the runtime-bound capability at the durable start instant and requires the exact central entrypoint, runtime identity, lease digest, execution ID, idempotency key, execution-request digest and source revision before delegating to the signed `ExternalEffectObservation` reconciliation operation. The adapter contains no provider callback and cannot execute or retry the external effect.

## Explicitly unchanged

This packet does not redefine provider exceptions before a normal return, runtime-trust-loss cancellation, terminal-fence behavior, provider invocation contracts, runtime manifests, entrypoint migration, promotion, OwnerApproval or Gate reporting. Those are separate axes and remain subject to their own findings and Work Packets.

## Adversarial batch

Prepared builder coverage proves:

- an output callback exception leaves no terminal call;
- empty and malformed digest material leave no terminal call;
- the typed error binds the exact start receipt and omits provider output;
- a real runtime-bound SQLite Effect Lease row remains `STARTED`;
- exact replay does not invoke the provider again;
- a signed external observation reconciles that same row to `COMPLETED`;
- foreign lease, execution, idempotency, request, runtime, entrypoint, capability-signature and source-revision bindings refuse before generic reconciliation;
- the external commitment count remains one.

Separate broker and recovery AST/source reviews reject terminal writer calls in the output-evidence handler, unsafe provider-value retention, raw exception-text materialization, replay ordering regressions, recovery authority in the exception, missing runtime binding dimensions, unauthenticated capability recovery and reintroduction of the old `FAILED` branch.

Eight bounded mutants restore the false `FAILED` terminal, bypass exact replay, retain a provider value, expose raw cause text, remove lease/idempotency/revision bindings and bypass runtime-capability authentication.

CI requests Ubuntu and Windows on Python 3.10 and 3.12, the affected runtime/effect/recovery suites, mutation, the full suite, package build and isolated-wheel import.

## Evidence status

The automation environment can mutate and review repository objects but cannot execute the exact private checkout. No model statement or source inspection is recorded as product evidence. GitHub Actions issue #67 still causes hosted jobs to terminate before Step 1 with no steps, logs or artifacts. Exact-head execution therefore remains pending.

Iron Plan: **ALIGNED**  
Iron Gate: **0**  
Promotion: **not requested**
