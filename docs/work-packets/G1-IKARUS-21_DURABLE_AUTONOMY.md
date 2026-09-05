# G1-IKARUS-21 — Durable bounded computer autonomy

Packet ID: G1-IKARUS-21
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner
Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
Dependencies: G1-IKARUS-20, canonical scheduler, spine, CAS, computer policy and mission loop
Plan revision 12, SHA-256
`126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`.
Status: implemented; independent code review complete; final combined regression pending.

## Primary acceptance claim

Explicit owner queueing, finite recurrence and durable cancellation use the
existing canonical schedule mechanism. A retained successful occurrence may
admit its deterministic successor; uncertain or failed effects never retry.

## Scope

Owned implementation: `daedalus/orchestration/ikarus/computer_schedule.py`,
`tests/test_ikarus_computer_schedule_autonomy.py` and this packet. Root owns
commands and Kairos wiring; the kernel reviewer owns mission-loop changes.
Current release fences, including disabled path IO, remain in force.

## Contracts and behavior

Recurrence is explicitly bounded to 2–1000 occurrences and intervals from
60 seconds through 365 days. Every occurrence retains the original policy and
execution-limit digests, and expires 24 hours after its due time. The next due
time follows retained completion by one interval, avoiding catch-up bursts.
Canonical continuation intents allow metadata recovery after a crash without
repeating any claimed external effect. Cancellation of any occurrence applies
to the entire finite series and reaches the running mission's callback.

## Acceptance matrix

| Check | Acceptance |
| --- | --- |
| Admission | Explicit owner command, bounded recurrence, timezone-aware due time and secret refusal before retention |
| Queue | Immediate due time uses the same canonical spec, admission and claim path |
| Identity | Stable finite-series identities and duplicate-safe canonical CAS/intent writes |
| Continuation | At least one independently observed terminal tool result; failed, interrupted, unverified input and empty model-finish reports stop recurrence |
| Timing | No overlap, one effectful mission per tick, next due at least one interval after retained completion |
| Recovery | Completion/next-spec gaps recover metadata only; open effect claims never replay |
| Cancellation | Durable root-scoped series cancellation before dispatch and during the running callback |
| Scope | Frozen policy and limits, expiry and existing release fences remain effective |
| Truth | Delivery/continuation status does not become a verified general task-success claim |

## Migration and rollback

Existing one-shot specification identities remain unchanged. Recurrence adds
fields and intent kinds to the existing canonical store, with no second event
store or daemon. Disabling dispatch stops new work while preserving all
specifications, cancellation requests and negative terminal evidence. Cancelling
any occurrence requests cancellation of its entire series, including a running
mission. A committed request cannot undo a previously observed host effect.

## Evidence, expected failures and review

Baseline: the existing 17 scheduler tests passed in 40.80 seconds, including
the release-disabled file-effect check. The first expanded imported snapshot
returned 46 passed and 1 failed in 373.33 seconds: the old concurrency fixture
placed its two-thread barrier inside the newly serialized claim path. With
root authorization, that one legacy test now places the race before reservation;
the assertion still requires exactly one invocation and one new completion.

The next focused snapshot returned 16 passed and 1 failed in 116.96 seconds.
The passing cases included a finite recurring chain using the actual service,
canonical leases, CAS and terminal evidence with a private fixture adapter.
The failure was negative-input fixture setup invoking two different operations
under the same attempt; the kernel correctly refused lease identity reuse.
The fixture now invokes its chosen tool once. These negative measurements are
retained; final validation must use the final source and fixtures.

Independent vision review found and repaired stale OCR tool names, insufficient
terminal-evidence binding, missing claim/report occurrence binding, canceled
pending-row retention and a stale dispatcher read racing cancellation. The
implementation now calls the existing kernel terminal-chain reader and binds
its exact output CAS, policy, mission, attempt and start/terminal receipts.
No second receipt verifier or effect authority was added. Independent code
review closed after those repairs. A preceding independent 13-case measurement
passed in 163.85 seconds, including two finite local Chromium occurrences with
two distinct missions and two GET requests; its final expanded rerun is pending.

Interruption after a committed effect claim remains reconciliation-required
and prevents other scheduled claims for that root until reconciled. No claimed
external effect is retried. An interruption after durable cancellation but
before pending-row cleanup still prevents execution; that canceled row may
remain in unresolved reads until cancellation is repeated. Normal cancellation
closes unclaimed pending rows. General task success is never inferred from a
model finish message. No personal policy, task or desktop interaction was enabled.

Final parent integration on 2026-09-05 completed with **355 passed and 34
subtests passed in 490.55 seconds**, including the final 14 independent review
cases, both scheduler suites, loop/history, runtime/browser/policy, watcher,
conversation/LLM, ledger and the two effect-inventory/conformance checks.
`docs/evidence/ikarus-autonomy-final-regression.xml` retains all 389 JUnit
records with zero failures, errors or skips. The command, environment, source
hashes and limits are in `docs/evidence/ikarus-autonomy-validation.json`.
This final-source measurement includes the cancellation race and canonical
terminal-chain fixes and supersedes the pending rerun above. Real Chromium
was exercised only against loopback fixture pages with a deterministic planner;
no live-model effectiveness, native desktop workflow or packaged build claim
is made. Plan revision 12 and the existing release path-I/O fences are unchanged.
