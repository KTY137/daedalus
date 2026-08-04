# G0-RWI-20L — Strict Effect Execution Replay Integration

## Parent and controlled source integration

This packet is stacked on exact parent
`afb5715aa6bc8115e43ffb8c10b1dc68220f4198` from
`g0/repository-write-runtime-conformance-linear`.

It integrates the existing effect-replay work from draft PR #147 in a controlled
small batch instead of expanding or merging that parallel stack. The source
subject is branch `g0/effect-replay-projection-linear` at exact revision
`d99e50c75f37fbd135aa0359ae33408bef922343`. The source PR is not modified,
merged, or promoted. The port retains the read-only projection and adversarial
coverage while placing the capability behind the current repository-write
semantic stack for a later explicit join.

## Exact persisted projection

`inspect_effect_execution(authorization, execution)` accepts one exact
`NonRuntimeEffectAuthorization` and one exact `EffectExecutionRequest`. It:

- opens the selected Effect-Lease SQLite file with `mode=ro` and
  `PRAGMA query_only=ON`;
- requires exactly one persisted lease row and binds lease digest, ID, request,
  policy, registry, entrypoint, canonical lease bytes, issue time, and expiry;
- resolves the execution by execution ID or lease/idempotency identity and
  rejects contradictions or ambiguity;
- binds the exact request digest and canonical request bytes;
- strictly parses and validates the canonical start receipt, row digest, and
  start time;
- authenticates the signed historical lease at the retained start instant with
  the original request, policy, keyring, generation, and registry;
- distinguishes no start, a retained `STARTED` execution requiring
  reconciliation, and the three terminal states;
- refuses hidden terminal material on `STARTED` and missing material on a
  terminal row;
- strictly parses and binds terminal outcome, outputs, detail, chronology,
  canonical receipt bytes, and row digest/time;
- permits an authenticated historical terminal projection after a later
  administrative revocation without reviving effect authority.

The returned frozen snapshot exposes no grant, start, finish, revoke, provider,
process, repository-write, promotion, or automatic re-execution method.

## Strangler boundary

This packet intentionally does not yet claim repository-write Effect-Lease
semantic verification. The repository-write evidence currently contains a
retained terminal receipt reference, while this projection requires the exact
typed authorization and execution request needed to authenticate the persisted
ledger row. A dependent batch must define the explicit join and decision table:

- exact terminal execution: eligible for semantic projection;
- persisted lease without start: fail closed;
- `STARTED` without terminal: pending reconciliation and fail closed;
- missing, ambiguous, substituted, or stale subjects: fail closed;
- no state may trigger automatic re-execution.

That join must be bound to the revision/classification/evidence chain and remain
separate from OwnerApproval and promotion authority.

## Adversarial batch

Prepared behavior coverage includes persisted lease without start, pending
execution despite later kill-switch drift, terminal round-trip, post-terminal
revocation, wrong historical issuer key, cross-execution substitution,
noncanonical request bytes, coherently rehashed start-subject substitution,
detached start and terminal digests, terminal material hidden on `STARTED`, and
row/terminal outcome contradiction.

A separate AST/source counter-review checks read-only SQLite authority, absence
of writer or external-effect calls, the exact two-argument API, strict
start-before-historical-authentication ordering, terminal binding, and hidden
terminal rejection. Six bounded mutants attack request, start, historical
signature, state, outcome, and terminal-digest fences.

The current automation runtime has repository write and review access but no
executable private-repository checkout. No test result is inferred from source
inspection or an LLM assertion. Exact-head CI requests Ubuntu and Windows on
Python 3.10 and 3.12 with two hash seeds, predecessor regressions, mutation,
Iron Plan verification, full suite, package build, and isolated-wheel import.
GitHub Actions issue #67 continues to terminate hosted jobs before Step 1 with
no logs or artifacts; such zero-step runs are infrastructure observations only.

No merge, automatic promotion, OwnerApproval, effect transition, or Gate
transition is requested.
