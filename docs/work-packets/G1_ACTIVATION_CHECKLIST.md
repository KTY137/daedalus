# G1 Activation Checklist — from rehearsal to authoritative run

Status: `BACKLOG` — a precise gap list, not an activation. Authoritative
Gate-1 activation remains blocked on Gate-0 closure (master plan §11, §12
Revision 3.3/3.4). Nothing in this document authorizes running the slice as
production.

Prepared 2026-08-17 on `grind/watchdog-mission2` from the rehearsal as it
exists at HEAD: `daedalus/ignition/runner.py`, `tests/ignition/` (green:
4 green-path + 5 fault tests), work packet `G1-WP-01_VOLTAGE_IGNITION.md`.

Iron Plan: ALIGNED · Iron Gate: 0 (preparation for 1) · touches: Gate-1
delivery criteria, invariants 1/3/5/6/7.

---

## 1. What the rehearsal already proves (do not re-litigate)

- Deterministic materialization of both WorkItems with exact-count rename
  preconditions (`materialize_voltage_rename`).
- Base and candidate compile into four complete planes; delta has additions
  and removals; behavior probe passes; EvidencePacket assembled with three
  deterministic evaluators (`fourfold.snapshot-binding`, `ignition-behavior`,
  `ignition-graph-delta`).
- Replay from identical inputs is digest-identical (candidate bundle,
  snapshot, delta, behavior, packet).
- Candidate revision is part of snapshot identity.
- OwnerApproval binds the exact candidate + packet; a mismatched expectation
  refuses; no approval is consumed, no promotion invoked.
- Fail-closed refusals (added 2026-08-17,
  `tests/ignition/test_voltage_ignition_faults.py`): restart over debris
  refuses and the fresh-root replay is digest-identical; nested/self candidate
  roots refuse without touching the source; a base whose cross-plane claims do
  not hold refuses at Twin compilation (layer 1); a compile-valid base that
  misses a rename site refuses at the precondition (layer 2); a source tree
  mutating mid-run trips the primary-tree digest tripwire.

## 2. Gaps between rehearsal and authoritative Gate-1 run

### 2.1 Mission spine (invariant 1)

- [ ] No `MissionContract` exists. The rehearsal hardcodes
  `mission_id="gate1-voltage-rename"` / `attempt_id="gate1-voltage-candidate"`
  and `attempt_contract_sha256 = sha({"attempt": "gate1-voltage"})` — a
  placeholder, not a persisted contract. Authoritative: Ikarus compiles one
  MissionContract; its digest, not a literal, binds the packet.
- [ ] The two WorkItems are module constants (`WORK_ITEMS`), not typed
  artifacts derived from the four planes. Authoritative: WorkItems are
  produced from the base Twin and persisted before any attempt starts.
- [ ] No events reach the canonical Event Store: no Attempt begin/complete via
  `AttemptLedger`, no intent record, no effect lease. The registry row for the
  attempt path (`kernel.attempt.*`, `python.attempt`) names the required
  migration: persisted EffectLease + runtime-conformance authority + sandbox
  capability.
- [ ] `policy_decision_sha256 = sha({"policy": "gate1-no-promotion"})` is a
  stand-in. Authoritative: a real policy decision artifact.

### 2.2 Base repository identity (invariants 2/6)

- [ ] Revisions are synthetic (`"1"*40`, `"2"*40`) and the "repository" is a
  test fixture tree. Authoritative: an exact resolved git revision of a real
  base checkout, and the candidate tree stored in content-addressed storage
  (the rehearsal computes bundle digests but stores nothing in CAS).
- [ ] `collected_at` is a caller-supplied constant. Authoritative: bound
  clock/provenance discipline (cf. runtime authorization clock packet).

### 2.3 Isolation (invariant 3)

- [ ] The candidate materializes via `shutil.copytree` in-process — no
  `IsolatedAttemptCoordinator.prepare`, no capability-bounded workspace, no
  containment preflight. The behavior probe `importlib.import_module`s
  candidate code INTO THE VERIFIER PROCESS (`_behavior`), which violates the
  evaluator/candidate separation the plan requires for authoritative runs:
  candidate code must not execute in the process that judges it.
- [ ] No write-root/egress/spend bounds are enforced around the attempt; the
  ignition path is not an inventoried effect entrypoint (acceptable for a
  test-invoked rehearsal; not for an authoritative run).

### 2.4 EvidencePacket evidence base (invariants 4/7)

Gate-1 text requires "tests, schema checks, and link checks" as evaluators.
Today's packet carries none of the three:

- [ ] No test-run evaluator (the fixture app has no executed test suite; the
  behavior probe is a single in-process parse).
- [ ] No schema-check evaluator (the schema file is renamed and claim-bound,
  but no JSON-Schema validation of `data/events.csv` rows is recorded as
  evidence).
- [ ] No link-check evaluator (wiki/knowledge links are claim-bound at
  compile; no independent link checker emits an EvidenceItem).
- [ ] All items claim `assurance="deterministic"`, `verdict="passed"` by
  construction (`_item` hardcodes both); a failing evaluator raises instead of
  producing a failed EvidenceItem, so a "failed evidence packet" state exists
  nowhere. Authoritative runs must be able to RETAIN negative evidence
  (invariant 7), not only refuse.
- [ ] Revision-3.2 evidence inputs: content-addressed runtime-conformance
  observations and the restrictive sandbox policy are required Gate-0
  evidence; the rehearsal packet references neither.

### 2.5 Restart/replay (Gate-1 criterion "restart/replay works")

Proven: refusal over debris + digest-identical replay from a fresh root;
mid-run source mutation detected (see §1).

Still unproven:

- [ ] Resume from the event spine: no Attempt events exist, so "restart"
  currently means "run again from scratch". Authoritative restart = crash
  after Attempt-begin, restart process, replay to a consistent state with the
  same attempt identity and no duplicated effects.
- [ ] Crash INSIDE materialization (between `_replace` calls) is only
  indirectly covered: the debris-refusal test simulates the aftermath, but no
  fault injection kills the run mid-write and asserts the invariant "partial
  candidate is never evaluable".
- [ ] Concurrent double-start on the same candidate root (two processes) —
  the exists-check is not atomic (TOCTOU between `candidate.exists()` and
  `copytree`); harmless for a test fixture, a real race for an authoritative
  workspace. The attempt-workspace path already owns this concern; the
  checklist item is: route ignition through it.

### 2.6 Approval and sealing (invariant 5)

- [ ] The rehearsal issues and verifies an OwnerApproval but never exercises
  the one-use consumption path against the sealed `promote_candidates`
  entrypoint with this packet (correct for the rehearsal — Revision 3.3
  forbids consuming an approval for production promotion from it). The
  activation item is a full non-promoting dry-run against the REAL
  authorization stack (nomination receipt, freshly resolved target revision,
  refusal-before-lock ordering), not the schema-level bind/verify pair alone.

## 3. Activation preconditions outside this slice

Per Revision 3.4, in order:

1. Gate-0 closure: remaining effectful-entrypoint migration to central wiring
   (78 `gate0.not_central` gaps at HEAD), live runtime receipts, complete
   fault matrix, independent architecture + security review, explicit owner
   closure decision.
2. Owner decisions currently pending (see
   `docs/GATE0_OWNER_DECISIONS_20260817.md`): guard fixture after amendment
   005, v3-scanner identity, blob-pin re-pin, CENTRAL predicate + K1–K13
   rebase. None of these may be preempted by this checklist.

## 4. Suggested order once unblocked

1. MissionContract + typed WorkItems from the base Twin (2.1) — pure artifact
   work, no new effects.
2. Route materialization through the isolated attempt lifecycle (2.3) and the
   Event Store (2.1), gaining authoritative restart semantics (2.5) for free.
3. Add the three missing evaluator families incl. failed-evidence retention
   (2.4).
4. Real base revision + CAS storage of the candidate bundle (2.2).
5. Non-promoting dry-run against the sealed authorization stack (2.6).

Evidence for this document: `pytest tests/ignition/ -q` → 9 passed in 4.60s
(4 pre-existing green-path + 5 new fault tests); runner source read at HEAD;
registry state measured via `check_conformance` (0 blockers, 78 not-central
gaps).
