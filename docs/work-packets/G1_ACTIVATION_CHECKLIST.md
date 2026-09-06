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

- [x] No `MissionContract` exists. The rehearsal hardcodes
  `mission_id="gate1-voltage-rename"` / `attempt_id="gate1-voltage-candidate"`
  and `attempt_contract_sha256 = sha({"attempt": "gate1-voltage"})` — a
  placeholder, not a persisted contract. Authoritative: Ikarus compiles one
  MissionContract; its digest, not a literal, binds the packet.
  *(measured 2026-09-06: receipt `mission_sha256=cd75e464...`, per-attempt `attempt_contract_sha256` `9e05e232...`/`ae62d8ca...`; minted by `mission_contract_for_build_session`; node `tests/test_ignition_gate1.py::test_every_attempt_records_the_criterion_it_declared_and_the_command_that_ran`. Full measurement: `docs/evidence/G1-RENOVATION-01_RESIDUAL_20260906.md`.)*
- [x] The two WorkItems are module constants (`WORK_ITEMS`), not typed
  artifacts derived from the four planes. Authoritative: WorkItems are
  produced from the base Twin and persisted before any attempt starts.
  *(measured 2026-09-06: `gate1.plan_work_items` derives both from `fourfold.json`; receipt `work_item_ids=[wi-000-c41495030c8f, wi-001-c8c563f2c0da]`; node `tests/test_ignition_gate1.py::test_replay_of_two_identical_runs_is_clean`.)*
- [x] No events reach the canonical Event Store: no Attempt begin/complete via
  `AttemptLedger`, no intent record, no effect lease. The registry row for the
  attempt path (`kernel.attempt.*`, `python.attempt`) names the required
  migration: persisted EffectLease + runtime-conformance authority + sandbox
  capability.
  *(measured 2026-09-06: receipt `attempts[].lease_id` + `lease_outcome=COMPLETED`, `lease_error=null`; `acquire_attempt_lease(..., contained=True, intent_ledger_path_resolver=...)`; registry row `cli.ignition` `wiring=CENTRAL`.)*
- [x] `policy_decision_sha256 = sha({"policy": "gate1-no-promotion"})` is a
  stand-in. Authoritative: a real policy decision artifact.
  *(measured 2026-09-06: receipt `attempts[].policy_decision_sha256` `7446e1e0...` vs `818c9e58...`, `policy_verdict=allow`, read from `contracts.policy.digest`.)*

### 2.2 Base repository identity (invariants 2/6)

- [x] Revisions are synthetic (`"1"*40`, `"2"*40`) and the "repository" is a
  test fixture tree. Authoritative: an exact resolved git revision of a real
  base checkout, and the candidate tree stored in content-addressed storage
  (the rehearsal computes bundle digests but stores nothing in CAS).
  *(measured 2026-09-06: receipt `base_revision=ebd198e9...` resolved by `git rev-parse` under `FROZEN_GIT_ENV`; `source_trees.base_locator`/`candidate_locator` in `SourceTreeStore`. RESIDUAL: the subject is still the fixture tree, and the legacy `run_voltage_ignition` path still uses `"1"*40`/`"2"*40`.)*
- [ ] `collected_at` is a caller-supplied constant. Authoritative: bound
  clock/provenance discipline (cf. runtime authorization clock packet).
  *(measured 2026-09-06: the constant is gone — `gate1._now()`, receipt `collected_at=2026-09-06T07:01:01Z` — but it is a direct process clock, not an injected clock port, so this row stays OPEN.)*

### 2.3 Isolation (invariant 3)

- [ ] The candidate materializes via `shutil.copytree` in-process — no
  `IsolatedAttemptCoordinator.prepare`, no capability-bounded workspace, no
  containment preflight. The behavior probe `importlib.import_module`s
  candidate code INTO THE VERIFIER PROCESS (`_behavior`), which violates the
  evaluator/candidate separation the plan requires for authoritative runs:
  candidate code must not execute in the process that judges it.
  *(measured 2026-09-06: the isolation half IS closed — attempts run in `TaskAttempt`/`GitWorktreeManager` worktrees with `Policy(write_allow=task.paths)` and gates run as subprocess pytest. The in-process import is UNCHANGED: `daedalus/ignition/runner.py:138-157` `_behavior` does `importlib.import_module("ignition_app")`, called from `gate1.py:1068`; its output is packet item `gate1-behavior`. Row stays OPEN on that half.)*
- [x] No write-root/egress/spend bounds are enforced around the attempt; the
  ignition path is not an inventoried effect entrypoint (acceptable for a
  test-invoked rehearsal; not for an authoritative run).
  *(measured 2026-09-06: `daedalus/spine/effect_boundary.py:2857` `EntrypointSpec(id="cli.ignition", wiring=CENTRAL, effects=FILESYSTEM_WRITE|PROCESS_SPAWN|PROCESS_CONTROL)`; `__main__.main` calls `begin_effect` before `argparse`; per-attempt write fence via `Policy(write_allow=...)`.)*

### 2.4 EvidencePacket evidence base (invariants 4/7)

Gate-1 text requires "tests, schema checks, and link checks" as evaluators.
Today's packet carries none of the three:

- [x] No test-run evaluator (the fixture app has no executed test suite; the
  behavior probe is a single in-process parse).
  *(measured 2026-09-06: receipt `checks.pytest.evaluator=ignition-pytest-composed`, packet item `gate1-check-pytest`; the attempts' `gate_command` runs real node ids.)*
- [x] No schema-check evaluator (the schema file is renamed and claim-bound,
  but no JSON-Schema validation of `data/events.csv` rows is recorded as
  evidence).
  *(measured 2026-09-06: receipt `checks.schema.evaluator=ignition-schema-check`, packet item `gate1-check-schema`; node `tests/test_ignition_gate1.py::test_the_data_knowledge_gate_still_fails_a_half_renamed_schema`.)*
- [x] No link-check evaluator (wiki/knowledge links are claim-bound at
  compile; no independent link checker emits an EvidenceItem).
  *(measured 2026-09-06: receipt `checks.link.evaluator=ignition-link-check`, packet item `gate1-check-links`; `tests/test_event_field.py::test_wiki_links_resolve` in `attempts[1].gate_command`.)*
- [ ] All items claim `assurance="deterministic"`, `verdict="passed"` by
  construction (`_item` hardcodes both); a failing evaluator raises instead of
  producing a failed EvidenceItem, so a "failed evidence packet" state exists
  nowhere. Authoritative runs must be able to RETAIN negative evidence
  (invariant 7), not only refuse.
  *(measured 2026-09-06: the verdict is derived now — `gate1.py:630` `verdict="passed" if report.passed else "failed"` — and a failing gate is measured, not asserted. But no run RETAINS a failed packet: `gate1.py:971-983` turns a non-ok attempt into a `blockers` entry and stops, and every `evaluation_status` assertion in the three suites is `"passed"`. Row stays OPEN.)*
- [ ] Revision-3.2 evidence inputs: content-addressed runtime-conformance
  observations and the restrictive sandbox policy are required Gate-0
  evidence; the rehearsal packet references neither.
  *(measured 2026-09-06: the evaluator bundle IS content-addressed and retrievable — receipt `evaluator_bundle_artifact.digest=7b4a6834...` — and the fixture conformance suite is digest-pinned. But that is not live runtime-adapter conformance, and `grep -rn sandbox` over `daedalus/ignition/` and its three suites returns nothing. Row stays OPEN.)*

### 2.5 Restart/replay (Gate-1 criterion "restart/replay works")

Proven: refusal over debris + digest-identical replay from a fresh root;
mid-run source mutation detected (see §1).

Still unproven:

- [ ] Resume from the event spine: no Attempt events exist, so "restart"
  currently means "run again from scratch". Authoritative restart = crash
  after Attempt-begin, restart process, replay to a consistent state with the
  same attempt identity and no duplicated effects.
  *(measured 2026-09-06: attempt events DO exist now, so "no Attempt events" is stale — but same-identity resume is impossible by construction: receipt `replay.note` says attempt ids carry a per-run nonce because the branch name IS the effect key (`effect_key=attempt.branch`, `gate1.py:911`). No node covers crash-after-begin resume. Row stays OPEN.)*
- [x] Crash INSIDE materialization (between `_replace` calls): covered
  2026-08-18 by
  `tests/ignition/test_voltage_ignition_faults.py::test_crash_between_rename_writes_leaves_no_evaluable_candidate`
  — kills the run after the third of six rename writes, asserts the mixed
  tree is refused on restart, the source stays byte-identical, and the
  fresh-root replay is digest-identical.
  *(measured 2026-09-06: the node still passes inside `104 passed`, but it monkeypatches `daedalus.ignition.runner._replace` and drives `run_voltage_ignition`; `gate1.py` uses neither `run_voltage_ignition` nor `materialize_voltage_rename`, so this coverage does NOT transfer to the shipped `python -m daedalus.ignition` path.)*
- [ ] Concurrent double-start on the same candidate root (two processes) —
  the exists-check is not atomic (TOCTOU between `candidate.exists()` and
  `copytree`); harmless for a test fixture, a real race for an authoritative
  workspace. The attempt-workspace path already owns this concern; the
  checklist item is: route ignition through it.
  *Assessed 2026-08-18: not machine-doable ahead of order — 
  `IsolatedAttemptCoordinator.prepare` requires an `AttemptContract` and a
  CAS `StoredSourceTree`, i.e. §4 steps 1–2. Routing now would mean
  inventing placeholder contracts, which §2.1 exists to eliminate.*
  *(measured 2026-09-06: still zero coverage — no concurrency/TOCTOU node in `tests/ignition`, `tests/test_ignition_gate1.py` or `tests/test_ignition_bundle.py`. The 2026-08-18 assessment below is REFUTED: §4 steps 1-2 are done — every attempt carries a real `AttemptContract` and the run stores `StoredSourceTree`s in `SourceTreeStore`, so routing no longer requires placeholder contracts.)*

### 2.6 Approval and sealing (invariant 5)

- [ ] The rehearsal issues and verifies an OwnerApproval but never exercises
  the one-use consumption path against the sealed `promote_candidates`
  entrypoint with this packet (correct for the rehearsal — Revision 3.3
  forbids consuming an approval for production promotion from it). The
  activation item is a full non-promoting dry-run against the REAL
  authorization stack (nomination receipt, freshly resolved target revision,
  refusal-before-lock ordering), not the schema-level bind/verify pair alone.
  *(measured 2026-09-06: unchanged — receipt `promotion.owner_approval="not requested"`, `status="nominated, not promoted"`; `gate1.py` imports nothing from `daedalus.kernel.promotion`; node `tests/test_ignition_gate1.py::test_promotion_status_is_never_promoted`. Row stays OPEN.)*

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
