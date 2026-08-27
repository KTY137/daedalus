# Work Packet G1-LEASE-01 — the ignition slice crosses its own effect boundary

**Status:** DONE 2026-08-27 (`16cf061d` implementation, `ea286622` three-run
receipt). Owner decision on the control root: **Option A** (installation
checkout as authority), taken 2026-08-27. **Classification:** `ALIGNED`.
**Active gate:** 0 (Gate-1 rehearsal per master-plan Revision 3 item 3).
**Base revision:** `4f71c020`. **Owner:** repository owner.
**Written:** 2026-08-26, with every precondition measured rather than assumed.

## Closure evidence `[MEASURED 2026-08-27]`

Acceptance matrix, all six rows: `pytest tests/test_ignition_gate1.py` →
64 passed, including four new lease tests. Three consecutive
`python -m daedalus.ignition` runs → `replay_demonstrated: true`,
`previous_run_complete: true`, `same_evaluator_bundle: true`, `blockers: []`;
both attempts `lease_outcome: "COMPLETED"`, `lease_error: null`; the operator
control root's write-evidence store holds `lease-terminal/*.json` naming each
execution (25 records after three runs); `promotion: "nominated, not promoted"`.
Found while wiring and left for its owner (out of packet scope): `path_write_blocked`
matches `write_allow` entries verbatim while normalising the candidate path, so
an unnormalised entry confines its own path OUT — failing toward refusal. The
slice pre-normalises its entries; `sensitivity.py` was not touched.

## The gap, in the module's own words

`daedalus/ignition/gate1.py:21-33` states it plainly: each attempt is a
`TaskAttempt` that "does NOT yet cross the `python.attempt` effect boundary
... `attempt_lease=None` here (the pre-lease behaviour), so none of the four
contracts that `acquire_attempt_lease` runs -- intent ledger check, worktree
containment, write fence over the declared target paths, process spend net --
execute for this slice."

And it names the consequence: **`wi-001` writes `fourfold.json`, its own scope
declaration, with no independent write fence.** That is the same defect
recorded on 2026-08-24 as "the candidate supplies its own judge", reached here
through the ignition path.

It also names the fix and the reason nothing catches it today: "handing line
~793 a real lease and asserting a non-null `lease_id` in
`tests/test_ignition_gate1.py`, which today contains no lease assertion at all
-- nothing goes red if the slice never leases."

## Preconditions -- MEASURED 2026-08-26 at `4f71c020`, not assumed

The two things that would have blocked this a week ago are both gone:

```text
KillSwitch(repo_root=<checkout>).read_state()  ->  running=True, reason="armed"
issuable_row("python.attempt")                 ->  spec present, refusals=()
```

`python.attempt` is one of six issuable rows and declares
`provider.write_policy`, without which `issuer.effect_bounds` would refuse its
two write effects. The wall recorded in the B5 handoff -- "exactly one row can
hold a lease" -- no longer applies to this row.

Downstream, the consumer half now exists: `4f71c020` wired
`WaveOffloadLease.retain_terminal_record`, so a leased attempt that terminalises
publishes a `lease-terminal` record. **This packet is what makes the ignition
slice produce one through the product** rather than only through
`tests/kernel/test_attempt_lease.py`.

## The one design question that must be decided BEFORE code

**Which control root does the slice's lease live under?**

`acquire_attempt_lease(repo_root=...)` derives the control root, the effect-lease
ledger, the issuer key and the write-evidence store from `repo_root`. The slice
runs its attempts against a scratch candidate workspace, not the primary
checkout. So:

* **Option A -- the primary checkout's control root.** The lease, its ledger row
  and its terminal record land beside every other lease this repository issues,
  which is what makes the record *evidence*. Cost: the slice stops being
  "read-only with respect to the repository except for the receipt directory"
  (its own docstring) -- it now writes the effect-lease ledger and the
  write-evidence store, both outside the checkout but shared.
* **Option B -- a per-run control root under the scratch workspace.** Keeps the
  slice hermetic and its docstring true. Cost: a fresh issuer key per run, a
  fresh write-evidence store per run, and a terminal record nobody will ever
  read -- evidence that is thrown away is not evidence.

**Recommendation: A**, with the docstring corrected in the same commit, because
the whole point of the record is that it accumulates where a reader looks. But
this changes what the slice touches, so it is an owner call, and the packet does
not start until it is made.

## Scope

**In scope (exact paths):**
- `daedalus/ignition/gate1.py` -- acquire the lease, hand it to `TaskAttempt`,
  project the lease fields into the receipt row builder (~1577) and the receipt
  attempt projection (~1739).
- `tests/test_ignition_gate1.py` -- the lease assertions.

**Forbidden:** `daedalus/kernel/offload_lease.py`, `daedalus/spine/attempt.py`,
the registry, the evaluator bundle, the fixture, and the conformance criterion.
If the slice needs any of those to change, the packet is wrong and stops.

## Implementation notes gathered while specifying

1. **The branch name IS the effect key** (`offload_lease.acquire_attempt_lease`
   requires `effect_key` for exactly this reason), and `TaskAttempt` derives
   `self.branch` in `__init__`. So the order is: construct the attempt, acquire
   with `effect_key=attempt.branch` and `attempt_id=attempt.branch`, then hand
   the lease over. `TaskAttempt.__init__` takes `attempt_lease=` as a public
   keyword; prefer restructuring to use it over assigning `_attempt_lease` the
   way the unit tests do.
2. **The lease may precede the intent.** `TaskAttempt.run()` records the intent
   itself at its step 2; `test_no_ledger_no_lease_but_the_lease_may_precede_the_intent`
   pins that this order is allowed. No pre-seeding needed.
3. **`positions` is pinned to 1** by `acquire_attempt_lease`: one attempt is one
   execution identity, and a retry is a NEW attempt with a NEW effect key.
4. **`writable_paths` must be the work item's declared target paths**, which is
   the whole point -- `wi-001` declaring `fourfold.json` then writing it is what
   the fence is supposed to bound.
5. **A refused lease must fail the work item loudly**, not fall back to
   `attempt_lease=None`. A silent fallback would reproduce today's state while
   the receipt claimed a boundary.

## Acceptance matrix

| # | Claim | How it is checked | Must fail when |
| --- | --- | --- | --- |
| 1 | every ignition attempt holds a lease | receipt `attempts[*].lease_id` is non-null | the lease is not handed over (today's state) |
| 2 | the lease terminalises | `attempts[*].lease_outcome == "COMPLETED"` for a clean item | `finish_effect` is skipped |
| 3 | a terminal record reaches the store | a `lease-terminal/*.json` naming each execution id | `retain_terminal_record` is removed |
| 4 | the fence is real | revert the fence and let `wi-001` write outside its declared paths -> the attempt is refused | the write policy is widened to the candidate root |
| 5 | a refused lease is a blocker | inject a denial -> the work item lands in `blockers`, not in a silent unleased run | the fallback is silent |
| 6 | the slice still replays | third consecutive run reports `replay_demonstrated: true`, `blockers: []` | lease ids leak into the packet digest |

Claim 6 is the one most likely to bite: attempt ids already carry a per-run
nonce and are deliberately excluded from the stability set
(`REPLAY_REQUIRED_STABLE`). A lease id is per-run too, so it must land in the
receipt WITHOUT entering `graph_delta`, `check_reports`, or anything the
replay comparison requires to be stable.

## Baseline to reproduce first

```text
python -m daedalus.ignition --workspace <scratch>      # three consecutive runs
```

MEASURED 2026-08-26 at `4f71c020`, third run:
`replay_demonstrated: true`, `blockers: []`,
`packet_sha256: 216f946c...`, `promotion: "nominated, not promoted"`.
The write-evidence store at that revision holds NO `lease-terminal` directory,
and `lease_id` appears nowhere in the receipt tree -- which is the absence this
packet closes.

Iron Plan: ALIGNED
Iron Gate: 0
Evidence: the preconditions and baseline above, each re-runnable from this tree.
