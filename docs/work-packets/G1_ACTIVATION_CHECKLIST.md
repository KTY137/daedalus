# G1 Activation Checklist — from rehearsal to authoritative run

Status: `BACKLOG` — a precise gap list, not an activation. Nothing in this
document authorizes running the slice as production. The Gate-0 precondition
this document was written under is OVERTAKEN: Gate 0 was closed by scoped
owner decision on 2026-08-26 (master plan Revision 8,
`docs/GATE0_CLOSURE_DECISION_20260826.md`). See §3.

Prepared 2026-08-17 on `grind/watchdog-mission2` from the rehearsal as it
existed then: `daedalus/ignition/runner.py`, `tests/ignition/` (green:
4 green-path + 5 fault tests), work packet `G1-WP-01_VOLTAGE_IGNITION.md`.

Revised 2026-09-06 by `G1-RENOVATION-02A_ONE_IGNITION_PATH`. §1 had been
measuring the wrong module since at least 2026-08-30: it described
`run_voltage_ignition`, the in-process rehearsal, while `python -m
daedalus.ignition` runs `daedalus/ignition/gate1.py::run_gate1_ignition`
[MEASURED 2026-09-06, `G1-RENOVATION-01`, `grep -n run_voltage_ignition
daedalus/ignition/gate1.py` → empty]. Every row below now names the path it is
asserted about.

Iron Plan: ALIGNED · Iron Gate: 1 · touches: Gate-1 delivery criteria,
invariants 1/3/5/6/7.

---

## 1. What the SHIPPED path proves (do not re-litigate)

The subject of every row here is `run_gate1_ignition` — the function
`python -m daedalus.ignition` calls — asserted by `tests/ignition/`
(10 nodes: 4 green-path/identity + 6 fail-closed).

- Deterministic materialization of both WorkItems through the attempt spine:
  one `rename_operator` per `TaskAttempt`, each refusing a declared path that
  does not carry the retired symbol, and `compose_candidate` building the
  candidate by APPLYING the attempts' own patches.
- Base and candidate compile into four complete planes; delta has additions
  and removals; behavior probe passes; one EvidencePacket carrying the
  Fourfold binding, behavior, graph-delta, attempt-binding and the three
  Gate-1 check evaluators (pytest, schema, link).
- Replay from identical inputs is digest-identical in the candidate's CAS
  artifact sha256, its Twin snapshot digest, and the graph delta, and since
  2026-09-06 the receipt's `replay.replay_demonstrated` and the door's exit
  code say the same thing. NOT in the post-run candidate directory: the
  evaluators run pytest inside the tree they judge and leave `__pycache__` and
  `.pytest_cache` in it, so the CAS artifact captured at composition — not the
  workspace afterwards — is the composed tree's identity
  [MEASURED 2026-09-06, `G1-RENOVATION-02A`].
- Candidate revision is part of snapshot identity — and the door DERIVES it
  from the composed tree instead of accepting it as an argument.
- OwnerApproval binds the exact candidate artifact + packet; a mismatched
  expectation refuses; no approval is consumed, no promotion invoked.
  (§2.6 stays open: this is still the schema-level bind/verify pair.)
- Fail-closed refusals (`tests/ignition/test_voltage_ignition_faults.py`,
  ported to the shipped door 2026-09-06): restart over debris refuses at
  `prepare_ignition_repo`/`compose_candidate` and the fresh-workspace replay
  is digest-identical; a base whose cross-plane claims do not hold refuses at
  Twin compilation (layer 1); a manifest whose code plane no longer carries
  the symbol refuses at `plan_work_items` (layer 2); a source tree mutating
  mid-run trips the fixture-digest tripwire; a crash between rename writes
  produces an empty patch that `compose_candidate` refuses, so no
  half-composed tree ever reaches the checks or the packet.
- **Not proven the way the rehearsal proved it:** a workspace nested inside
  the source is detected but not prevented — see the new OPEN row F5 in §2.3.

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

- [x] The candidate materializes via `shutil.copytree` in-process — no
  `IsolatedAttemptCoordinator.prepare`, no capability-bounded workspace, no
  containment preflight. **Closed for the shipped path 2026-09-06:** each
  attempt runs in a `GitWorktreeManager` worktree under
  `Policy(write_allow=task.paths)` with `contained=True`, and the gates
  execute as `subprocess` pytest (`gate1.py:906-940`, receipt
  `attempts[].gate_command`). The two open halves are F4 and F5 below.
- [ ] **F4 — the behavior probe runs candidate code in the verifier process.**
  `daedalus/ignition/runner.py:138-157` `candidate_behavior` does
  `sys.path.insert(0, candidate/"src"); importlib.import_module("ignition_app")`
  and `gate1.py:1068` calls it, so the process that judges the candidate
  imports it. Its output becomes packet item `gate1-behavior`. This violates
  the evaluator/candidate separation the plan requires for authoritative runs.
  Deliberately NOT fixed by `G1-RENOVATION-02A` (that packet consolidates the
  two ignition paths; moving the probe out of process is a change to what the
  packet's evidence means and belongs in its own packet).
  [MEASURED 2026-09-06, `G1-RENOVATION-01` row 2.3-a]
- [ ] **F5 — the isolation refusal is late and dirty.** The rehearsal refused a
  candidate root nested inside the source BEFORE the first write
  (`candidate == source or source in candidate.parents`). `run_gate1_ignition`
  has no such precondition: it digests the fixture before (`gate1.py:727`) and
  after (`gate1.py:1280`) and raises `the fixture tree changed while the slice
  ran`. MEASURED 2026-09-06 with `workspace=fixture_root`: the run completes,
  writes `target/`, `candidate/`, `controls/` and `coverage/` into the source
  root, and only then refuses. Every declared file of the source survives
  byte-identical, so the tripwire is real — but a caller can make the door
  litter a tree it was told to treat as read-only. Pinned as measured by
  `tests/ignition/test_voltage_ignition_faults.py::test_a_workspace_nested_inside_the_source_is_refused`;
  closing the row means an up-front isolation precondition on `workspace`.
- [x] No write-root/egress/spend bounds are enforced around the attempt; the
  ignition path is not an inventoried effect entrypoint. **Closed:**
  `daedalus/spine/effect_boundary.py:2857` carries `cli.ignition`
  (`wiring=CENTRAL`, `guard_contracts=("budget.process_guard",)`), and
  `daedalus/ignition/__main__.py` calls `begin_effect` before `argparse`.
  [MEASURED 2026-09-06, `G1-RENOVATION-01` row 2.3-b]

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
- [x] Crash INSIDE materialization: covered 2026-08-18 by
  `tests/ignition/test_voltage_ignition_faults.py::test_crash_between_rename_writes_leaves_no_evaluable_candidate`
  — and, since 2026-09-06, covered ON THE SHIPPED PATH. The coverage did NOT
  transfer when the node drove `run_voltage_ignition`; it does now: the node
  kills the SECOND work item's `rename_operator`, and `compose_candidate`
  refuses the empty patch it produced (`gate1.py:543`), so the half-composed
  tree never reaches the Fourfold compile, the checks or the packet. The
  source stays byte-identical, restarting over the same workspace is refused,
  and the fresh-workspace restart replays digest-identically.
  [MEASURED 2026-09-06, `G1-RENOVATION-02A`]
- [ ] Concurrent double-start on the same workspace (two processes) — the
  exists-checks are not atomic (TOCTOU between `repo.exists()` and
  `shutil.copytree` in `prepare_ignition_repo`, and between
  `destination.exists()` and `destination.mkdir` in `compose_candidate`);
  harmless for a test fixture, a real race for an authoritative workspace.
  Zero coverage: `grep -rn "concurrent\|double_start\|TOCTOU\|parallel"` over
  the three ignition suites returns nothing.
  [MEASURED 2026-09-06, `G1-RENOVATION-01` row 2.5-c]
  ~~*Assessed 2026-08-18: not machine-doable ahead of order —
  `IsolatedAttemptCoordinator.prepare` requires an `AttemptContract` and a
  CAS `StoredSourceTree`, i.e. §4 steps 1–2.*~~ **Refuted 2026-09-06:** both
  exist now — the receipt carries a per-attempt `attempt_contract_sha256` and
  `source_trees.candidate_locator` addresses a `StoredSourceTree`. The row is
  open for want of a test, not for want of a contract.

### 2.6 Approval and sealing (invariant 5)

- [ ] The rehearsal issues and verifies an OwnerApproval but never exercises
  the one-use consumption path against the sealed `promote_candidates`
  entrypoint with this packet (correct for the rehearsal — Revision 3.3
  forbids consuming an approval for production promotion from it). The
  activation item is a full non-promoting dry-run against the REAL
  authorization stack (nomination receipt, freshly resolved target revision,
  refusal-before-lock ordering), not the schema-level bind/verify pair alone.

## 3. Activation preconditions outside this slice

**OVERTAKEN 2026-09-06 — read the paragraph before the list, not the list.**
Item 1 below names Gate-0 closure as a precondition. Gate 0 was closed as a
SCOPED owner decision on 2026-08-26 (master plan Revision 8,
`docs/GATE0_CLOSURE_DECISION_20260826.md`), and the active delivery gate has
been Gate 1 since. The closure carries four binding obligations forward
(caller-injection half two, no new effect path outside the canonical
contracts, the scoped rows stay reported, Docker host procurement stays an
open owner position); those, not "Gate-0 closure", are what remains. The
mechanical report deliberately still says `closed:false` while the scoped rows
are open — that is the instrument being honest, not a reopened gate.

Item 2's pending owner decisions were **not re-measured** by
`G1-RENOVATION-02A` (out of scope). Do not read the list below as current.

Per Revision 3.4, as written 2026-08-17:

1. ~~Gate-0 closure: remaining effectful-entrypoint migration to central
   wiring (78 `gate0.not_central` gaps at HEAD), live runtime receipts,
   complete fault matrix, independent architecture + security review, explicit
   owner closure decision.~~ — disposed 2026-08-26, see above.
2. Owner decisions pending as of 2026-08-17 (see
   `docs/GATE0_OWNER_DECISIONS_20260817.md`): guard fixture after amendment
   005, v3-scanner identity, blob-pin re-pin, CENTRAL predicate + K1–K13
   rebase. Status unmeasured at 2026-09-06. None of these may be preempted by
   this checklist.

## 4. Suggested order once unblocked

Steps 1, 2 and 4 as written 2026-08-17 are **done** — `run_gate1_ignition`
mints the MissionContract from a real `BuildSession`, derives both WorkItems
from the four-plane manifest, runs each attempt in a contained worktree behind
a lease, resolves a real git base revision under `FROZEN_GIT_ENV`, and stores
both trees in CAS [MEASURED 2026-09-06, `G1-RENOVATION-01` §2 rows 2.1-a…d,
2.2-a, 2.3-a/b]. What remains, in order:

1. Move the behavior probe out of the verifier process (§2.3 F4).
2. An up-front isolation precondition on `workspace` (§2.3 F5).
3. Retain a FAILED EvidencePacket instead of stopping at blockers (§2.4-d);
   no node today produces `evaluation_status == "failed"`.
4. Bind the clock instead of reading the process clock (§2.2-b), and supply
   the Revision-3.2 runtime-conformance/sandbox inputs (§2.4-e).
5. Resume from the spine with the same attempt identity (§2.5-a) and cover the
   concurrent double-start race (§2.5-c) — the 2026-08-18 "not machine-doable"
   assessment is refuted: `attempt_contract_sha256` and `StoredSourceTree`
   both exist now.
6. Non-promoting dry-run against the sealed authorization stack (§2.6).

Evidence for this document, 2026-09-06 (`G1-RENOVATION-02A`, base
`585b7ea4`): `pytest tests/ignition -q` → 10 passed, every node driving
`run_gate1_ignition` or a named seam of `daedalus/ignition/gate1.py`;
`grep -rn "run_voltage_ignition\|materialize_voltage_rename" daedalus tests`
returns only the deprecated shim and its own test. Superseded evidence
(2026-08-17): `pytest tests/ignition/ -q` → 9 passed, all against
`daedalus/ignition/runner.py`; registry state via `check_conformance`
(0 blockers, 78 not-central gaps), unmeasured since.
