# G0-PRM-25G — Deterministic Promotion Effect Terminal Reconciliation

## Scope and parent

This Work Packet is stacked directly on the cross-ledger replay decision:

- parent branch: `g0/promotion-effect-replay-decision-linear`;
- parent revision: `7051cafb309467fefc8766ba8b5fd94af5467ae0`;
- parent draft PR: `#149`.

It closes one narrow crash window only: the exact top-level Effect Lease was
started, the exact promotion execution already reached a strict persisted
terminal, and the process stopped before writing the top-level terminal.

It does not wire the live Kairos seam, start an Effect Lease, invoke promotion,
open a worktree, run Git, issue OwnerApproval or centralize any registry row.

## Deterministic reconciliation

`reconcile_promotion_effect_terminal()` accepts only the exact
`PromotionEffectCapability` and selected canonical `PromotionExecutionLedger`.
It recomputes the strict cross-ledger decision before any write.

The only writable decision is `reconcile_effect_terminal`. Outcome and receipt
material are not caller parameters. They are derived solely from the retained
promotion completion:

- succeeded promotion → `COMPLETED` Effect Lease;
- refused promotion → `COMPLETED` Effect Lease with the verified refusal report;
- faulted promotion → `FAILED` Effect Lease;
- output digest → canonical promotion report digest;
- detail digest → canonical promotion execution receipt digest;
- terminal time → canonical persisted promotion completion time.

Using the promotion completion time makes the terminal receipt byte-deterministic
across process restarts and concurrent exact reconciliation attempts.

## Historical authority boundary

The strict read projections already prove that:

- the Effect Lease was signed, scoped and valid at its retained start instant;
- the exact effect start predates the exact promotion start;
- the promotion completion binds candidate, EvidencePacket, source revision,
  target ref, live target HEAD, approval consumption and primary-checkout
  invariance;
- the expected top-level outcome, report digest and receipt digest are exact.

Reconciliation therefore writes accounting only through the canonical
`EffectLeaseLedger.finish()` state transition. It deliberately does not call the
live-authority facade, because expiry or later administrative revocation must
not erase the terminal truth of an external effect that already happened. No
new effect authority is recovered: the function has no begin, execute, promote,
Git, worktree, Docker or provider path.

## Restart and concurrency behavior

- An already exact `replay_promotion_report` state returns the retained terminal
  with `changed=false` and performs no write.
- A `fresh`, absent-promotion, or pending-promotion state is refused and remains
  non-executable.
- An exact concurrent terminalization is re-read and returned with
  `changed=false`.
- A concurrent contradictory terminal is rejected after strict reinspection.
- Every successful write is immediately re-read through both strict projections;
  the returned result must equal the exact persisted terminal.

## Adversarial batch

Builder and independent source-review tests cover:

- succeeded, refused and faulted outcome mapping;
- exact report and promotion-receipt digest binding;
- deterministic terminal time;
- exact second replay;
- later lease revocation;
- fresh and pending-state refusal;
- exact concurrent terminalization;
- contradictory concurrent terminalization;
- absence of effect-start, promotion, Git, Docker and worktree calls;
- no caller-controlled time, outcome, output or detail;
- no execution or promotion method on the result object.

The bounded mutation runner attacks state refusal, faulted-outcome mapping,
report output, promotion-receipt detail, deterministic time and post-write exact
reinspection.

## Honest migration state

The live `promote_candidates` seam remains unchanged and the canonical promotion
row remains `local_guards`. A dependent packet must install an outer strangler
adapter that:

1. inspects the cross-ledger decision before any live effect;
2. durably starts a fresh exact Effect Lease before entering the existing
   promotion lifecycle;
3. returns pending reconciliation without invoking promotion;
4. calls this reconciler only for an exact retained promotion terminal;
5. replays retained report material without invoking promotion;
6. terminalizes pre-promotion failures without fabricating a promotion report.

No merge, automatic promotion, OwnerApproval issuance or Gate transition is
requested.

## Verification boundary

Exact-head focused, malformed-state, mutation, full-suite, platform and
isolated-wheel execution is requested by the dedicated workflow. GitHub Actions
issue `#67` remains an external infrastructure blocker while jobs terminate
before Step 1 with no logs or artifacts. Zero-step runs are not product or Gate
evidence.
