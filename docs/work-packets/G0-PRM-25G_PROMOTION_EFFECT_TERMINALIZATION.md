# G0-PRM-25G — Evidence-Bound Promotion Effect Terminalization Authority

## Scope

This packet introduces one explicit bookkeeping reconciliation authority for the sole transition that can remain after a durable promotion-execution terminal: the matching top-level Effect-Lease terminal.

The authority is deliberately narrower than the live `NonRuntimeEffectAuthorization` facade. It cannot grant a lease, persist a start, rerun promotion, invoke Git, open or mutate a worktree, issue or consume OwnerApproval, change a target ref, or authorize automatic replay. It may append one terminal row only when the strict dual read-only projection reports `EFFECT_TERMINAL_REQUIRED` for the exact `PromotionEffectCapability` and exact persisted promotion execution.

## Why a separate authority is required

Fresh successful effect completion correctly requires current unexpired authority. That rule prevents a stale capability from claiming new successful outputs. A different case exists after the external promotion already has a durable, validated promotion-execution receipt: a crash can occur before the top-level Effect-Lease terminal is written. Requiring the expired lease to become live again would make honest accounting impossible; bypassing or forging a terminal would be worse.

`terminalize_promotion_effect` therefore derives no new external authority. It recognizes an already terminal external effect and appends only the exact accounting terminal implied by durable evidence.

## Preconditions and write contract

Immediately before the single write, the strict reconciliation projection proves:

- the exact effect lease, execution request and start receipt are retained;
- the exact promotion authorization, start, terminal receipt and report are retained;
- the top-level effect start precedes the promotion start;
- promotion execution is terminal;
- no top-level effect terminal exists;
- the expected effect outcome, output digests and detail digest are deterministic.

The mapping remains:

- promotion `succeeded` → effect `COMPLETED`, outputs bound to promotion receipt and report digests, detail bound to the promotion receipt digest;
- promotion `refused` → effect `CANCELLED`, no outputs, detail bound to the promotion receipt digest;
- promotion `faulted` → effect `FAILED`, no outputs, detail bound to the promotion receipt digest.

After writing, the authority reruns the strict dual projection and requires `COMPLETE`. It also compares the returned writer receipt with the exact retained terminal. A substituted writer return, wrong competing terminal, reversed chronology, incomplete state, or non-idempotent race fails closed.

## Restart and concurrency behavior

A second call after exact completion returns the retained terminal with `replayed=true` and performs no write. If another reconciler wins the terminal write, only an exact `COMPLETE` reprojection converts the race to replay. Any other race remains an error.

All fresh, effect-only, and promotion-pending states refuse terminalization. No disposition enables automatic promotion execution.

## Adversarial batch

Prepared checks cover successful, refused and faulted mappings; exact replay; expired live-success authority; nonterminal refusal without mutation; exact concurrent replay; non-idempotent race refusal; wrong-terminal and writer-return substitution; malformed result contracts; preservation of the original approval-consumption digest; a separate source-level authority review; and nine bounded mutants.

The source review requires exactly one lower-level accounting `finish` call, strict projections before and after it, no grant or begin call, no Git/subprocess/worktree authority, no OwnerApproval reference, and only a narrow `EffectLeaseStateError` race handler.

## Remaining live boundary

This packet is not production wiring. A dependent packet must compose the live path so that the top-level effect start is durably persisted before the promotion-execution start and the terminalizer runs immediately after every promotion terminal. Fault injection must cover every cross-ledger crash window. Only after that composition, runtime/sandbox obligations, registry migration, full release-report closure and exact-head verification may the promotion row move from `local_guards` to `central`.

Exact-head execution remains pending because repository GitHub Actions issue #67 currently terminates jobs before Step 1. Zero-step runs are infrastructure observations only and are not verification evidence.

No merge, OwnerApproval, promotion, registry centralization, or Gate transition is requested.
