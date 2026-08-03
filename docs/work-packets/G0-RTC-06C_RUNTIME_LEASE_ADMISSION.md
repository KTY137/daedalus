# G0-RTC-06C — Runtime Trust → Effect Lease Admission

## Objective

Prevent a runtime-bearing production entrypoint from treating a declared
manifest or a locally constructed conformance receipt as sufficient authority.
The entrypoint-facing capability must bind one signed `EffectLease` to one exact,
authenticated, persisted and currently active `RuntimeTrustRecord`.

## Authority chain

```text
externally trusted live RuntimeConformanceEnvelope
  → RuntimeTrustLedger admission + HMAC-authenticated active record
  → signed RuntimeBoundEffectLease
  → persisted EffectLease grant
  → active-trust recheck
  → persisted effect start receipt
  → caller may perform the external effect
```

`RuntimeBoundEffectLease` binds:

- the complete signed `EffectLease` digest;
- exact runtime ID;
- exact trusted envelope digest;
- exact HMAC-verified runtime-trust record digest;
- exact runtime manifest and conformance receipt digests;
- exact source revision;
- the lease issue and expiry bounds;
- an external runtime-lease authority key;
- canonical provenance containing every referenced digest.

The runtime trust record is checked at issuance, grant and immediately before an
entrypoint receives `execute=true`. A lease cannot outlive its runtime trust
record. Quarantine, rotation, expiry, manifest substitution, receipt
substitution, revision substitution and envelope substitution therefore fail
closed.

## Scope

This packet adds:

- `daedalus.kernel.runtime_effects.RuntimeBoundEffectLease`;
- authenticated issue and verify functions;
- `RuntimeBoundEffectAuthorization`, the explicit capability bundle intended for
  runtime-bearing production entrypoints;
- real SQLite trust-ledger and Effect-Lease-ledger integration tests;
- replay, stale-revision, signature, expiry and quarantine negatives;
- import-order and isolated-wheel checks.

## Adversarial review finding fixed

The first packaging draft re-exported the runtime authority from
`daedalus.kernel.__init__`. Importing `daedalus.runtimes` first could then create
a cycle through runtime profiles and the partially initialized kernel package.
The re-export was removed. The stable public path for this packet is the direct
module `daedalus.kernel.runtime_effects`; CI checks both import orders.

## Deliberate remaining boundaries

- No Claude, Codex or Ollama process is invoked here.
- No production runtime registry row is upgraded to `CENTRAL` in this packet.
- Existing provider entrypoints still require separate migration packets that
  change their public call boundary to accept `RuntimeBoundEffectAuthorization`.
- The generic non-runtime `EffectLease` API remains available. A runtime path is
  not considered migrated merely because it can construct an ordinary lease.
- Live provider receipts, external trusted-envelope publication and integrity
  keys remain external operational inputs.
- No automatic promotion, merge, Gate-0 closure or Gate-1 activation occurs.

## Verification

The dedicated workflow runs Python 3.10 and 3.12 under two hash seeds, the
focused runtime-trust/effect-lease batch, `compileall`, and isolated wheel import
in both import orders. GitHub Actions has recently failed before creating Step 1
for this repository; a green exact-head claim must not be made until runners
actually execute the workflow.

Iron Plan: **ALIGNED**  
Iron Gate: **0**  
Promotion: **not requested**
