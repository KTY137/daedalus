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
  → second active-trust recheck
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

The runtime trust record is checked at issuance, grant, before the durable start
and again before an entrypoint receives `execute=true`. A lease cannot outlive
its runtime trust record. Quarantine, rotation, expiry, manifest substitution,
receipt substitution, revision substitution and envelope substitution therefore
fail closed. If the second check fails, the already-persisted start is closed as
`CANCELLED`; the caller never receives authority to perform the effect.

## Scope

This packet adds:

- `daedalus.kernel.runtime_effects.RuntimeBoundEffectLease`;
- strict canonical parsing plus
  `configs/schemas/runtime-bound-effect-lease-v1.schema.json`;
- authenticated issue and verify functions;
- `RuntimeBoundEffectAuthorization`, the explicit capability bundle intended for
  runtime-bearing production entrypoints;
- real SQLite trust-ledger and Effect-Lease-ledger integration tests;
- replay, stale-revision, signature, expiry, quarantine and post-start failure
  negatives;
- import-order and isolated-wheel checks.

## Adversarial review findings fixed

1. **Import cycle.** The first packaging draft re-exported the runtime authority
   from `daedalus.kernel.__init__`. Importing `daedalus.runtimes` first could then
   enter a cycle through runtime profiles and the partially initialized kernel.
   The re-export was removed. The stable path is
   `daedalus.kernel.runtime_effects`; CI checks both import orders.
2. **Caller-controlled security time.** The first capability API accepted
   `granted_at` and `started_at` from its consumer. A privileged but stale caller
   could attempt to backdate a trust or lease check. Grant and start now obtain
   their instants inside the boundary. Tests replace the private clock only for
   deterministic verification.
3. **Dangling durable start.** A trust loss between the pre-start check and the
   post-persistence check originally raised while leaving the execution in
   `STARTED`. The boundary now persists a deterministic `CANCELLED` terminal
   receipt before re-raising, and no external effect is authorized.

## Deliberate remaining boundaries

- No Claude, Codex or Ollama process is invoked here.
- No production runtime registry row is upgraded to `CENTRAL` in this packet.
- Existing provider entrypoints still require separate migration packets that
  change their public call boundary to accept `RuntimeBoundEffectAuthorization`.
- The generic non-runtime `EffectLease` API remains available. A runtime path is
  not considered migrated merely because it can construct an ordinary lease.
- Runtime trust and effect intent use separate SQLite authorities. This packet
  narrows the time-of-check boundary with a second check, but provider migration
  and the final fault campaign must still exercise revocation races explicitly.
- Live provider receipts, external trusted-envelope publication and integrity
  keys remain external operational inputs.
- No automatic promotion, merge, Gate-0 closure or Gate-1 activation occurs.

## Verification

The dedicated workflow runs Python 3.10 and 3.12 under two hash seeds, the
focused runtime-trust/effect-lease batch, `compileall`, schema parsing, and
isolated wheel import in both import orders. GitHub Actions is currently failing
repository jobs before creating Step 1 (`steps=null`, no logs); a green
exact-head claim must not be made until runners actually execute the workflow.

Iron Plan: **ALIGNED**  
Iron Gate: **0**  
Promotion: **not requested**
