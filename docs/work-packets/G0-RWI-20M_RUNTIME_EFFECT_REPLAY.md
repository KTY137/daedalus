# G0-RWI-20M — Runtime-Bound Effect Execution Replay

## Parent and purpose

This packet is stacked on exact parent
`5ba80d79b0c2685a94af684cc17bca437e113a20` from
`g0/effect-replay-integration-linear`.

It composes the strict read-only persisted Effect-Lease projection with the
existing signed `RuntimeBoundEffectLease` authority. The result identifies one
exact missing, pending, or terminal runtime-bearing execution without granting,
starting, finishing, revoking, or automatically repeating an effect.

## Composed replay subject

`inspect_runtime_effect_execution(authorization, execution)`:

1. requires one exact `RuntimeBoundEffectAuthorization` and
   `EffectExecutionRequest`;
2. constructs a compatibility adapter carrying the exact inner EffectLease,
   request, policy decision, ledger, keyring, guards, and registry;
3. invokes the strict read-only persisted execution projection from the parent
   packet;
4. returns `None` when the exact runtime-bound lease exists but no durable start
   exists;
5. parses the retained start timestamp and verifies the signed runtime-bound
   capability at that instant using the retained Effect-Lease generation rather
   than mutable live generation state;
6. requires the runtime authority signature, exact runtime identity, exact
   manifest and receipt bindings, exact signed runtime-trust-record digest, and
   an authenticated current active trust record;
7. independently rechecks that the returned trust-record digest and runtime ID
   equal the signed capability;
8. returns a frozen snapshot containing the strict persisted execution state,
   authenticated runtime trust record, and canonical verification instant.

The projection exposes only `pending_reconciliation`. It has no method that can
execute, grant, begin, finish, revoke, quarantine, admit, promote, or mutate a
repository or trust ledger.

## Conservative trust-history boundary

The current `RuntimeTrustLedger` exposes an authenticated current record, not an
append-only authenticated transition history. Therefore a runtime capability
whose trust has later expired or been quarantined is deliberately refused even
when its Effect-Lease start is historically valid. Accepting such a capability
without historical trust evidence would be weaker than failing closed.

A later packet may add authenticated append-only runtime trust transitions and
then distinguish:

- active at start and still active now;
- active at start but later expired;
- active at start but later quarantined;
- never admitted or subject-substituted.

Until that authority exists, no claim of historical runtime trust replay is
made.

## Adversarial batch

Prepared behavior coverage includes persisted lease without start, pending and
terminal projections, live generation drift, wrong runtime-authority key,
quarantined trust, inner execution substitution, signed capability trust-digest
substitution, post-verifier trust-record and runtime-ID detachment, and strict
input types.

A separate AST/source review checks absence of writer/effect/callback authority,
the exact two-argument API, inner persisted replay before runtime verification,
retained start and generation use, exact adapter bindings, the non-executable
snapshot surface, and explicit documentation of the conservative trust-history
boundary. Six bounded mutants attack type, missing-state, live-generation,
runtime-authority, trust-digest, and runtime-identity fences.

The automation runtime has repository write and review access but no executable
private-repository checkout. No test result is inferred from source inspection
or an LLM assertion. Exact-head CI requests Ubuntu and Windows on Python 3.10
and 3.12 with two hash seeds, parent regressions, mutation, Iron Plan
verification, full suite, package build, and isolated-wheel import. GitHub
Actions issue #67 continues to terminate hosted jobs before Step 1 with no logs
or artifacts; such runs are infrastructure observations only.

## Remaining join

This packet does not yet bind repository-write `EFFECT_LEASE_RECEIPT` evidence
to the exact typed authorization, execution request, and replay snapshot. That
join must reject missing and `STARTED` executions, accept only an exact terminal
receipt, and mechanically prohibit automatic re-execution. Guard behavior,
Primary-Checkout disjointness, retirement, complete evidence authentication,
GateReport-v2 binding, and Gate closure remain open.

No merge, automatic promotion, OwnerApproval, runtime admission, effect
transition, or Gate transition is requested.
