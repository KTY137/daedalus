# G0-RTC-06D — Runtime Provider Broker

## Objective

Compose the persisted runtime-trust and Effect-Lease authorities into one
provider-neutral execution boundary without yet claiming that Claude, Codex or
Ollama public entrypoints have been migrated.

```text
externally trusted runtime evidence
  → authenticated RuntimeTrustRecord
  → signed RuntimeBoundEffectLease
  → persisted exact lease grant
  → persisted effect start receipt
  → provider callable
  → post-call runtime-trust recheck
  → mandatory content-addressed output evidence
  → final pre-terminal runtime-trust recheck
  → persisted terminal receipt
```

## Implemented boundary

`daedalus.runtimes.broker.run_runtime_provider()` requires:

- one exact provider entrypoint identifier;
- a `RuntimeBoundEffectAuthorization` bound to the same entrypoint and runtime;
- one narrowed `EffectExecutionRequest`;
- a zero-argument provider callable;
- a deterministic extractor producing at least one content-addressed output digest.

Before any provider code runs, the broker verifies that the authorization's
request, signed lease, registry row and runtime identity all agree and that the
row is already `CENTRAL`. It then persists the exact lease grant and start
receipt. Exact execution replay is inert and cannot invoke the provider or
output-evidence extractor twice.

Provider exceptions are persisted as `FAILED`; `KeyboardInterrupt`,
`SystemExit` and `GeneratorExit` are persisted as `CANCELLED`. Exception text is
not copied into the receipt; only a deterministic digest of the phase and
exception class is retained.

After a successful provider return, the broker rechecks runtime trust. If the
runtime expired or was quarantined during the call, output is withheld and the
execution is persisted as `CANCELLED`. Output evidence is mandatory, lowercase
SHA-256, non-empty and duplicate-free. Malformed or missing output evidence is
persisted as `FAILED`.

The broker performs a second trust check immediately before writing the
`COMPLETED` terminal. This prevents a runtime rotation or expiry during evidence
materialization from winning a completion race. A successful value is returned
only after a `COMPLETED` receipt containing the output identities is durable.

## Adversarial review findings fixed

1. **Unbound successful output.** The first draft allowed a completed invocation
   with no output digests. Output evidence is now mandatory and non-empty.
2. **Evidence-window expiry race.** The first draft checked trust only before
   output-evidence extraction. A second check now occurs immediately before the
   terminal completion receipt.

## Adversarial coverage

The focused tests exercise:

1. request/lease entrypoint substitution;
2. non-central registry rows;
3. runtime-identity substitution;
4. replay causing no second invocation or evidence extraction;
5. provider failure and cancellation;
6. quarantine or expiry immediately after provider return;
7. quarantine or expiry after evidence extraction;
8. missing, malformed and duplicate output digests;
9. terminal-receipt persistence failure.

## Deliberate remaining blockers

This packet does not change any Claude, Codex or Ollama public call signature and
does not upgrade their registry rows. The broker is an execution primitive, not
proof that direct provider bypasses are gone. Subsequent small migration packets
must move each public provider entrypoint behind this broker, update its callers,
prove no direct effectful path remains, and only then change that exact registry
row to `CENTRAL`.

A provider callback can still internally perform more than one effect or capture
ambient authority. Provider-specific wrappers, sandboxing and fault tests must
narrow that callback before a production migration is accepted.

No live provider process is invoked. External live receipts, provider secrets,
egress credentials, runtime authority keys and the GitHub-hosted runner remain
operational inputs. The current repository Actions jobs are failing before Step
1 with no steps or logs; no exact-head green claim is made until a runner
actually executes this branch.

No merge, promotion, Gate-0 closure or Gate-1 activation is requested.

Iron Plan: **ALIGNED**  
Iron Gate: **0**  
Promotion: **not requested**
