# G1-IKARUS-20 — Scheduled computer missions

Packet ID: G1-IKARUS-20
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner
Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
Dependencies: G1-IKARUS-17, G1-IKARUS-COMPUTER-01, G1-WP-IKARUS-COMPUTER-LOOP-01 and existing canonical scheduler, spine, CAS, policy and kill paths
Plan revision 12, SHA-256
`126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`.
Status: implementation, two independent reviews and focused regression complete.

## Primary acceptance claim

Explicit owner one-shot scheduled work is stored as canonical intents and CAS
specifications. The existing scheduler invokes at most one due mission per
tick for its exact authority root. No daemon, separate event store, loose JSON
job authority, promotion or model-owned scheduling grant is introduced.

## Scope

Scope: `daedalus/orchestration/ikarus/computer_schedule.py`, focused schedule
tests and this packet. Root owns registered effect rows; kernel reviewer owns
existing scheduler/watcher and explicit command integration. Root review also
authorized the additive `open_only` argument on the canonical
`SpineLedger.intents_matching_payload` reader to keep resolved history out of
automatic ticks; this changes neither the event schema nor its write behavior.

## Contracts and behavior

An owner-admitted job freezes its objective, due time, authority and policy
digests in canonical CAS. A unique canonical claim precedes dispatch through
the existing computer mission loop. Automatic dispatch requires the matching
File Bridge watcher to remain running; manual run-due uses the same path.
Interrupted open claims require reconciliation and are never blindly retried.

## Acceptance matrix

| Check | Acceptance |
| --- | --- |
| Admission | Explicit owner confirmation; timezone-aware exact due time; frozen objective, authority root and current policy digest |
| Identity | Canonical CAS spec and deterministic unique schedule intent; duplicate admission does not create a second job |
| Scope | List/dispatch restrict to the supplied authority root; missing/corrupt source does not become a fabricated job |
| Timing | No run before due; expiry is explicit due + 24 hours; at most one new mission per tick |
| Claim | Unique canonical claim commits before invocation; competing dispatcher does not execute twice |
| Recovery | Open interrupted claim is reconciliation-required; completed claim projects its retained terminal result without repeating effects |
| Refusal | Changed policy, expired job, cancellation or stopped switch produce no model/tool execution |
| Execution | Existing run_computer_task receives frozen mission ID and cancellation callback; its canonical leases remain effect authority |
| Truth | Scheduled/claimed/completed/blocked are delivery states, never verified task-success claims |

Baseline: computer missions retain canonical state, but no due-time helper or
watcher connection exists. A scheduler callback is integration infrastructure,
not an external exact-once execution guarantee. Unexpected interruption between
claim and terminal evidence requires visible reconciliation and is not retried.

## Migration and rollback

Rollback disables the watcher integration; stored jobs and claims remain
inspectable. Policy changes revoke pending scope and block execution. An owner
may submit a new job after inspecting a blocked/interrupted outcome.

## Evidence, expected failures and review

Implemented canonical CAS schedule specifications and admission receipts,
deterministic unique schedule and claim intents, read-only listing, one-mission
ticks, due + 24-hour expiry, policy and execution-limit fingerprints, and
non-repeating recovery. Secret-like objectives refuse before retention.

v0.1.6 release supersession: scheduling freezes policy but cannot reactivate a
release-disabled path tool. A scheduled authority containing only legacy file
grants returns unavailable before planner invocation, computer Mission, lease
or adapter, and creates no file. Lines below retain pre-fence scheduler
integration evidence only; they are not current file-capability acceptance.

The focused suite initially completed **14 passed in 4.96 seconds**. An added
end-to-end scheduled mission then reached the real canonical file adapter and
found that a full-hash mission ID overflowed the downstream 200-character
decision-ID bound. It refused with `decision_id must be no longer than 200
characters` and performed no file effect. The mission ID now uses a stable
128-bit prefix while authoritative schedule and CAS identities retain their
full SHA-256. The next **15 tests passed in 10.82 seconds**, including real
scheduled Mission/WorkItem/lease admission, scratch-file creation, independent
readback and canonical terminal receipts.

After objective-secret refusal and terminal-claim replay projection were added,
**16 tests passed in 13.31 seconds**. Cancellation, expiry, changed policy,
changed execution limits, stopped switch, duplicate scheduling, concurrent
dispatch, corrupted artifacts and interrupted claims were exercised. The
planner in the file-effect test was a deterministic fixture; no model-quality
claim is inferred.

Independent kernel and vision reviewers checked the unique claim, root filter,
frozen policy and limits, cancellation propagation, invalid-source reporting,
watcher serialization and recovery. Review repaired an unnecessary
reconciliation report when a competing dispatcher already had a terminal
claim. It also found that ticks read resolved history; the canonical reader
now filters that history before hydration, with a regression asserting that
old artifacts are not read on a tick. Tick read cost still scales with
unresolved jobs; no pending job is silently truncated or discarded.

Final focused regression command:
`python -m pytest -q tests/test_ikarus_computer_schedule.py tests/test_spine_ledger.py tests/interfaces/test_computer_configuration.py`
completed with **64 passed in 56.13 seconds**. This includes all 17 scheduling
tests, the existing canonical ledger suite and all 21 configuration tests.

The independently owned existing watcher integration invokes at most one new
mission after bridge requests and reports a busy heartbeat during execution.
It requires that watcher's exact authority root. No personal job or policy was
created during verification. Usage is recorded in
`docs/IKARUS_COMPUTER_CONFIGURATION.md` and `docs/IKARUS_COMPUTER.md`.
