# G1-IKARUS-KITCHEN-02 - Preserve kitchen evidence on continuation

- Classification: ALIGNED, Gate 1; Masterplan invariants 2, 3, 4 and 7.
- Base: `c4a147969fcad94e5481c48ff48cb6b22efee9c0` on
  `g1/ikarus-ignition-20260912`; plan SHA-256
  `04e8cbf9441134e22b97fe1cb5e7ebcbcfedac64cda2f3e4e5086d82bb628639`.
- Owner request: continue the interrupted Copilot ignition session, including
  the existing approximately 50-repository Ariadne feed.
- One axis: correctness and retention of the existing kitchen's evidence.
- Parent KITCHEN-01 is frozen as a documented blocker: its own order database
  and direct builder/toolchain execution do not establish canonical Mission,
  EffectLease, source CAS or EvidencePacket admission. This repair does not
  activate that path as a verified production capability or close a gate.

## Scope frozen before implementation

In scope: `daedalus/orchestration/ikarus/kitchen/` and focused kitchen tests;
this packet and a continuation evidence report. Preserve the live corpus,
previous candidate/evidence files and untracked project registration.
No plan/instruction changes, merge, promotion, new external model spending,
corpus expansion, or new scheduler/store. Live inspection may read the corpus
and exercise the existing local demo in a separate browser session.

## Baseline and acceptance

Baseline on 2026-09-12: kitchen, Sous-Chef, import SCC and HTTP strangler suites
give **77 passed in 13.61 seconds**. Independent review reproduced failures
that this green suite misses.

1. Replaying an existing order never deletes its candidate or replaces its
   evidence/result; project contexts cannot consume each other's result.
2. A toolchain with no required verification, including optional-only failing
   lint, cannot be green. Repairs cannot replace the selected verifier with
   a weaker manifest; retained evidence includes failed rounds.
3. Self-renovation checks both sides of Git renames and rejects protected
   source removals before checks/nomination. Failed Git inspection refuses.
4. Generated candidate content is excluded from default corpus motif retrieval;
   source revision metadata may not attribute dirty bytes to a clean Git HEAD.
5. Run focused regressions plus affected legacy contracts, independently review
   the resulting diff, and verify retained corpus counts and real browser
   behavior separately from model/build reports.

Budget: local deterministic tests and bounded read-only corpus/browser probes;
no provider calls or repository downloads. Results retain revision, commands,
failures and limitations. Rollback is reverting this packet's source diff;
never erase previous runtime state. This packet expires at this continuation's
handoff; additional architecture/runtime admission is a separate packet.

## Measured result

Implemented on the continuation branch, without modifying live corpus or order
databases. Detailed evidence and residual blockers are in
`docs/IKARUS_COPILOT_CONTINUATION_20260912.md` and
`docs/evidence/G1-IKARUS-KITCHEN-02/`.

- Existing kitchen/HTTP/import/shell/OS contracts plus new retention, corpus and
  verifier regressions: 195 passed, 1 skipped, 37 subtests passed (24.88s).
- Final Sous-Chef changes plus retention/verifier and entrypoint-registry
  contracts: 69 passed (18.16s). These suites overlap; do not sum as unique tests.
- Independent reviewer: no additional introduced blocker; six selected
  adversarial reproductions passed separately. One host-dependent symlink test
  is skipped because this Windows account cannot create the fixture.
- Three retrieval probes against a read-only copy of the real 64-entry index
  return without generated candidate hits; 3.08-3.16s/query. The live database's
  SHA-256 is unchanged. This is execution evidence, not a retrieval-quality win.

Renovation uses a strict frozen evaluator inventory. New tests/configuration
proposed by the model are deferred and recorded rather than executed. This is
an explicit limitation, not proof of arbitrary evaluator dependency isolation.
Use CLI `--request-id ID` for idempotent delivery or `--new-request` for a
deliberate fresh build/feed after a failure or source change. CLI `--async`
refuses before accepting work because the short-lived process cannot own a
durable background worker.

Historical browser failures prompted a separate bounded repair experiment,
`G1-IKARUS-KITCHEN-DEMO-01`; that repair does not establish kitchen runtime
admission. Source CAS, canonical Missions/leases/cancellation and independent
product acceptance remain KITCHEN-01 blockers. System CI still must execute
against this continuation's new commit; old PR checks cover only c4a14796.

## Subsequent owner integration instruction

The owner subsequently requested ignition on `main` and further work there.
That instruction authorizes merging the reviewed branch and supersedes this
packet's initial no-merge scope. It does not amend the Master Plan, promote a
candidate or establish the missing kitchen runtime contracts.

On the primary `main` checkout, the transitive evaluator closure exposed twelve
missing explicit Git byte-preservation declarations. Added only those `-text`
entries and retained exact committed source bytes. Bundle and attribute tests:
38 passed in 140.73s, with seven Python tar-extraction warnings. The pre-fix
attribute result (2 failed, 6 passed) remains recorded in the continuation log.
