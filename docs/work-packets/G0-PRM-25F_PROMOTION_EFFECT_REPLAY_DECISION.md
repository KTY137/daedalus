# G0-PRM-25F — Cross-ledger Promotion Effect Replay Decision

## Scope and parent

This Work Packet is stacked directly on the strict Effect-Lease replay
projection:

- parent branch: `g0/effect-replay-projection-linear`;
- parent revision: `d99e50c75f37fbd135aa0359ae33408bef922343`;
- parent draft PR: `#147`.

It joins the two existing read-only projections into one explicit decision table.
It does not write either ledger, start or finish an Effect Lease, reconcile a
pending execution, call the live Kairos seam or grant promotion authority.

## Cross-ledger state table

The decision layer recognizes these safe outcomes:

| Effect execution | Promotion execution | Decision |
|---|---|---|
| absent | absent | `fresh` |
| absent | pending or terminal | refuse contradiction |
| `STARTED` | absent or pending | `pending_reconciliation` |
| `STARTED` | terminal | `reconcile_effect_terminal` with exact expected outcome |
| `COMPLETED` | succeeded or refused terminal | `replay_promotion_report` |
| `FAILED` | faulted terminal | `replay_promotion_report` |
| `FAILED` or `CANCELLED` | absent | `replay_effect_terminal_without_report` |
| terminal | pending | refuse contradiction |
| `COMPLETED` | absent | refuse missing report |
| terminal outcome not matching promotion outcome | terminal | refuse contradiction |

Promotion outcomes map to top-level Effect-Lease outcomes as follows:

- `succeeded` → `COMPLETED`;
- `refused` → `COMPLETED`, because the bounded call completed and returned a
  verified refusal report without repository promotion;
- `faulted` → `FAILED`.

Only `fresh` exposes `permits_fresh_execution=true`, and that state requires
both durable starts to be absent. No pending state permits automatic
re-execution.

## Cross-ledger bindings

When both starts exist, the promotion start must not precede the top-level
Effect-Lease start. A retained promotion terminal under a still-started Effect
Lease yields only a deterministic reconciliation decision containing:

- the exact expected top-level outcome derived from the verified promotion
  outcome;
- exactly one expected output digest: the canonical promotion report digest;
- exactly one expected detail digest: the canonical promotion execution receipt
  digest.

A terminal top-level Effect Lease may replay the promotion report only when its
state, output and detail bindings match those values exactly and it finishes no
earlier than the promotion execution terminal. The promotion projection already
binds that report to candidate, EvidencePacket, approval consumption, source
revision, target ref, target HEAD, primary-checkout invariance and terminal
outcome.

## Authority separation

`PromotionEffectReplayDecision` is immutable and contains no execute, begin,
finish, reconcile or promote method. The module calls only:

- `inspect_effect_execution()`;
- `inspect_promotion_execution()`.

It imports no SQLite writer, Git, worktree, Docker, provider, sandbox, policy or
live-promotion implementation.

## Adversarial batch

Builder and counter-review tests cover:

- the sole fresh state;
- promotion without a top-level effect start;
- effect-only and dual-pending states;
- terminal promotion awaiting deterministic effect terminalization;
- exact succeeded, refused and faulted outcome mapping;
- exact terminal report replay for `COMPLETED` and `FAILED` states;
- effect-outcome substitution;
- failed effect without a promotion report;
- completed effect without a report;
- terminal effect hiding a pending promotion;
- substituted report output and promotion-receipt detail digests;
- reversed start chronology;
- source-level absence of writer/effect authority;
- no second fresh-return site;
- exact outcome-state requirement before report replay.

The bounded mutation runner attacks absent-effect contradiction, start order,
pending re-execution, output binding, detail binding and faulted-outcome mapping.

## Honest migration state

The live Kairos seam is still unchanged and the canonical promotion row remains
`local_guards`. A dependent Work Packet must consume this decision at the live
boundary:

1. `fresh`: durably start the exact Effect Lease before entering the existing
   promotion lifecycle;
2. `pending_reconciliation`: return a fail-closed reconciliation response and do
   not invoke promotion;
3. `reconcile_effect_terminal`: write only the exact deterministic top-level
   terminal derived from retained promotion evidence;
4. `replay_promotion_report`: return retained report material without calling
   promotion;
5. `replay_effect_terminal_without_report`: return a bounded terminal refusal
   without fabricating a promotion report.

No automatic merge, promotion, OwnerApproval issuance or Gate transition is
requested.

## Verification boundary

Exact-head focused, malformed-state, mutation, full-suite, platform and
isolated-wheel execution is requested by the dedicated workflow. GitHub Actions
issue `#67` remains an external infrastructure blocker while jobs terminate
before Step 1 with no logs or artifacts. Zero-step runs are not product or Gate
evidence.
