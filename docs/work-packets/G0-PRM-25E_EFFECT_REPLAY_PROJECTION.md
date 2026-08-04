# G0-PRM-25E — Strict Effect Execution Replay Projection

## Scope and parent

This Work Packet is stacked directly on the read-only promotion replay packet:

- parent branch: `g0/promotion-replay-projection-linear`;
- parent revision: `bbbd2a9d325a5a5d4286dba980161fc8bfe5fd11`;
- parent draft PR: `#146`.

It adds one strict read-only projection over the existing persisted
`EffectLeaseLedger`. It does not alter the writer, issue a lease, grant an
effect, start an execution, terminalize an execution or call promotion.

## Why a second projection is required

The canonical Effect-Lease start boundary correctly returns `execute=false` on
an exact replay. The retained `LeasedEffectStartReceipt` alone cannot tell the
caller whether the execution is:

1. still `STARTED` and requires reconciliation;
2. `COMPLETED` with exact retained outputs;
3. `FAILED`; or
4. `CANCELLED`.

Calling the writer-shaped start operation again is intentionally inert and does
not expose the terminal receipt. Restart composition therefore needs an
independent read path that cannot create or transition state.

## Strict persistence boundary

`inspect_effect_execution()` accepts only one exact
`NonRuntimeEffectAuthorization` and one exact `EffectExecutionRequest`. It:

- opens the selected database with SQLite `mode=ro` and `query_only=ON`;
- requires exactly one persisted lease row by both digest and lease identity;
- binds persisted lease digest, ID, request, policy, registry, entrypoint, exact
  JSON bytes, issue time and expiry to the supplied authorization;
- resolves by execution ID or lease/idempotency identity and refuses any
  contradiction or multiplicity;
- binds exact execution request digest and canonical JSON;
- strictly parses the start receipt with duplicate-key, field-set, identifier,
  digest, canonical-time and canonical-round-trip checks;
- binds the row start digest and start time;
- authenticates the signed lease at the retained start instant using the exact
  request, policy, keyring, generation and registry;
- requires `STARTED` rows to contain no terminal material;
- requires terminal rows to contain complete terminal material;
- strictly parses output digests, detail digest, outcome, terminal time and
  receipt digest;
- binds the terminal to the exact start and row state and enforces causal time.

Historical inspection deliberately does not consult the current kill-switch
reader and does not revive a stale or revoked lease. The returned object contains
no method or flag that permits execution. A terminal retained before later
administrative revocation remains readable as historical evidence.

## Authority separation

The module contains no `INSERT`, `UPDATE`, `DELETE`, `BEGIN IMMEDIATE`, writer
connection, grant, start, finish, revoke, provider, Git, Docker, worktree or
promotion call. It does not create a missing database or missing execution.

## Adversarial batch

Builder and counter-review tests cover:

- persisted lease without a start;
- pending and terminal replay;
- current kill-switch drift without historical re-execution authority;
- later lease revocation;
- wrong historical signing key;
- cross-execution and idempotency substitution;
- duplicate/noncanonical request JSON;
- coherently rehashed start-subject substitution;
- detached row start digest;
- terminal material hidden on a `STARTED` row;
- row/terminal outcome contradiction;
- detached row terminal digest;
- monkeypatched writer connection bypass;
- source-level absence of write or external-effect authority;
- ordering of strict binding, historical authentication and state release.

The bounded mutation runner attacks request bytes, start digest, historical
signature authentication, hidden terminal material, outcome binding and
terminal digest.

## Honest migration state

The effect and promotion replay projections remain separate and the live Kairos
seam is unchanged. A dependent Work Packet must join them into one explicit
cross-ledger decision table and then wire fresh start and deterministic terminal
reconciliation before any registry row can become `central`.

No automatic re-execution, merge, promotion, OwnerApproval issuance or Gate
transition is requested.

## Verification boundary

Exact-head focused, malformed-input, mutation, full-suite, platform and
isolated-wheel execution is requested by the dedicated workflow. GitHub Actions
issue `#67` remains an external infrastructure blocker while jobs terminate
before Step 1 with no logs or artifacts. Zero-step runs are not product or Gate
evidence.
