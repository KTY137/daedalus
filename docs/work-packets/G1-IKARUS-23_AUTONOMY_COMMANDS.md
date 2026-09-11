# G1-IKARUS-23 - Autonomous task controls and inspection

Packet ID: G1-IKARUS-23
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner
Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
Dependencies: reviewed G1-IKARUS-20; G1-IKARUS-21 and G1-IKARUS-22; plan revision 12

## Primary acceptance claim

Explicit chat commands can enqueue, repeat and cancel canonical computer jobs,
and inspect root-scoped mission progress without granting additional tools.

## Scope

Computer conversation command handlers, the existing Kairos facade, a read-only
computer-history projection, optional bounded pagination in the existing ledger
reader, runtime cancellation checkpoints, command help, focused tests and docs.
No change to plan, release fences, candidate containment, user configuration,
personal jobs, promotion, or unrelated staged and unstaged changes.

## Contracts and behavior

History reads validate declared authority, canonical payload digests and CAS
bytes. A partial page is explicitly partial; an open intent is pending or
interrupted, not proof that a worker is live. Legacy unscoped rows do not gain
an invented authority. No separate state store or daemon is introduced.
Cancellation checks reach the existing adapter checkpoints. A checkpoint is
cooperative and cannot retract an already completed effect.

## Acceptance matrix

Verify real spine/CAS reads, two-root isolation, malformed/missing evidence,
terminal versus open state, bounded pagination, absent-ledger read purity,
explicit command routing, callback cancellation and native checkpoint refusal.
Validate queue/repeat/cancel integration with the independently reviewed schedule
helper. No real user desktop input or external submission is required.

## Migration and rollback

New mission/step rows include explicit authority_root. Historical rows remain
retained and are reported as unscoped on exact lookup. Ledger pagination is
optional and leaves existing scheduler/recovery queries complete by default.
Rollback removes these command/projection additions while retaining evidence
and cancellation history; no historical events are rewritten.

## Evidence, expected failures and review

Baseline: 70 loop/schedule/service/watcher tests passed in 64.41 s on Python
3.13. Current release disables pathname file tools and skill loading; those
capabilities remain disabled. Independent review found cancellation was not
passed to adapter checkpoints; this packet supplies that missing connection.
Root owns integration; vision independently reviews authority and projection.
Final measured results are appended after verification.

The history/review/runtime matrix first passed 53 cases in 32.53 seconds
(`docs/evidence/ikarus-autonomy-history-review.xml`), then 54 cases in 245.72
seconds after terminal evidence gained canonical mission/attempt/policy binding
(`docs/evidence/ikarus-autonomy-runtime-binding.xml`). These overlap with the
final run and are not additive evidence counts.

Final integration on 2026-09-05: **355 passed and 34 subtests passed in 490.55
seconds** on Python 3.13. The matrix includes all final planning, loop, history,
scheduling and independent review cases, runtime/browser/policy, watcher,
conversation/LLM, ledger, effect inventory and new-door conformance checks.
`docs/evidence/ikarus-autonomy-final-regression.xml` retains 389 JUnit records,
zero failures, errors or skips. The exact command, environment and source
digests are retained in `docs/evidence/ikarus-autonomy-validation.json`.
Before publication, machine-local host and absolute path identities in the
JUnit/validation documents were replaced by explicit neutral tokens; test
records, outcomes, timing and the recorded post-redaction digest are unchanged.

The independent browser tests use actual Chromium and loopback fixture pages:
cancellation during navigation sends exactly one GET, keeps the started effect
for reconciliation and rejects replay; a finite series performs two occurrences
with distinct missions and exactly two GETs, never early or after its end.
No paid provider, real-model comparison, user desktop input, personal policy or
job mutation, rebuilt installer, or native desktop workflow was exercised.

Automatic dispatch still requires the existing running watcher (or explicit
`run-due`). A durable cancellation is cooperative. An interrupted host claim
can block other jobs for the same root until reconciled; cancellation committed
before a cleanup interruption still blocks execution but may leave a pending
row visible until cancellation is repeated. These limits are retained in packet
21 and the user guide. File-path tools, path-based vision and skill loading
remain release-disabled. No extra effect authority or store was introduced.

Classification remains **ALIGNED** with revision 12. The master-plan digest is
`126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`.
No plan, amendment chain or agent instructions were edited by this work.
