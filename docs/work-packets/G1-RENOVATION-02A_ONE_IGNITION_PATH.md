# G1-RENOVATION-02A — One ignition path instead of two

Packet ID: G1-RENOVATION-02A
Artifact role: primary
Active gate: 1
Classification: ALIGNED
Owner: repository owner
Base revision: 585b7ea4e141332928ad6c9578b9c9997e55f247
Dependencies: G1-RENOVATION-01 (measurement), G1-WP-01
Plan revision 12, SHA-256
`126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`.
Status: implemented on `g1/renovation-02a`, builder-verified, awaiting
independent review (plan §10 step 5).

## Primary acceptance claim

The Gate-1 Renovation clause has exactly one implementation, and the
fail-closed fault matrix proves that one. Every node in `tests/ignition/`
drives `daedalus.ignition.gate1.run_gate1_ignition` — the function
`python -m daedalus.ignition` calls — or a named seam of `gate1.py`;
`run_voltage_ignition` and `materialize_voltage_rename` no longer exist; and
the door's exit code and its receipt's `replay.replay_demonstrated` say the
same thing.

## Why

`G1-RENOVATION-01` measured, on 2026-09-06 at this base revision, that:

1. **Two implementations, one clause.** `daedalus/ignition/runner.py`
   (`run_voltage_ignition`, `materialize_voltage_rename`, synthetic `"1"*40`
   revisions) was the 2026-08 rehearsal; `daedalus/ignition/gate1.py`
   (`run_gate1_ignition`) is what ships. All 10 nodes of `tests/ignition/` —
   the whole fail-closed matrix `docs/work-packets/G1_ACTIVATION_CHECKLIST.md`
   §1 cites as settled — exercised the rehearsal. Plan §13 forbids a second
   implementation truth; `AGENTS.md` §3 prefers deletion and consolidation.
2. **Exit code 0 did not mean the replay was demonstrated.** Run 2 of three
   consecutive door runs exited 0 with `blockers: []` while
   `replay.replay_demonstrated` was `false`, because run 1 had ended in
   blockers. `previous_run_complete` was a conjunct of `replay_demonstrated`
   and of nothing else, so nothing turned it into a blocker and nothing
   reached the exit code a CI job reads.

## Scope

In scope: `daedalus/ignition/runner.py` (delete the rehearsal entrypoint and
its materializer; keep the three measurements `gate1` imports),
`daedalus/ignition/__init__.py` (stop re-exporting the deleted names),
`daedalus/ignition/gate1.py` (`_replay_blockers` gains the
`previous_run_complete` and unconditional criterion-change conjuncts;
`write_receipt` records `execution_blockers`), `tests/ignition/conftest.py`
(new; the shared door fixtures), `tests/ignition/test_voltage_ignition.py`,
`tests/ignition/test_voltage_ignition_faults.py` (ported row by row),
`tests/test_ignition_gate1.py` (the conjunct's failing tests),
`docs/work-packets/G1_ACTIVATION_CHECKLIST.md` and this packet.

NOT in scope after all, and blocked rather than forced: a refreshed
`runs/ignition/mission-gate1-voltage-ignition/` receipt store. See A10.

Forbidden and untouched: the master plan, the amendment chain, `AGENTS.md`,
`CLAUDE.md`, `.agentenv/`, `daedalus/spine/effect_boundary.py` (no new effect
row — `cli.ignition` already exists and is unchanged),
`daedalus/kernel/**`, `daedalus/twin/**`, `daedalus/ignition/checks.py`,
`daedalus/ignition/bundle.py`, `.gitattributes` (the census is already
complete for this closure — verified, not assumed), and
`docs/work-packets/index.json`.

Explicitly NOT fixed here, and recorded instead: the behaviour probe imports
candidate code into the verifier process (`runner.py` `candidate_behavior`,
called from `gate1.py:1068`). Moving it out of process changes what the
packet's `gate1-behavior` evidence item means and belongs in its own packet.
Recorded as OPEN row F4 in the activation checklist §2.3.

## Contracts and behavior

Deleted (no external caller — measured, see "Migration and rollback"):

- `daedalus.ignition.runner.run_voltage_ignition`
- `daedalus.ignition.runner.materialize_voltage_rename`
- `daedalus.ignition.runner.IgnitionResult`, `IgnitionWorkItem`, `WORK_ITEMS`
  and the private helpers `_replace`, `_old_symbol_occurrences`, `_item`
- the re-exports of all of the above from `daedalus.ignition`

Retained unchanged: `IgnitionError`, `IgnitionGraphDelta`, `tree_digest`,
`candidate_behavior`, `fourfold_graph_delta` — the three measurements
`gate1.py` imports plus the exception it raises. `daedalus/ignition/runner.py`
keeps its filename because `daedalus/ignition/bundle.py:70` names it as an
evaluator module by path and `.gitattributes:207` pins it; renaming it would
move the evaluator bundle digest for no measured gain.

Changed behavior, one function and one field:

- `_replay_blockers(replay)` returns a blocker when `previous_run_complete` is
  not `True`, and when `criterion_changed_since_previous` is true regardless of
  whether any identity field also moved. Both were already conjuncts of
  `replay_demonstrated`; neither reached the exit code.
- `write_receipt` writes a new top-level receipt field `execution_blockers`:
  the run's own blocker list, recorded before the replay comparison appends its
  derivative ones. `previous_run_complete` reads it, falling back to `blockers`
  for predecessors written before the field existed. The receipt schema string
  is unchanged (`daedalus-gate1-ignition-receipt/1`): the field is additive and
  nothing pins the receipt's key set.

Unchanged: the effect registry row `cli.ignition`, the `run_gate1_ignition`
signature, the mission/attempt/lease/evidence contracts, promotion status, and
every check evaluator.

## Acceptance matrix

| # | Claim | How it is proved | Result |
| --- | --- | --- | --- |
| A1 | No test in `tests/ignition/` calls the rehearsal | `grep -rn "run_voltage_ignition\|materialize_voltage_rename" daedalus tests` returns prose only | green |
| A2 | The rehearsal entrypoint does not exist | `daedalus/ignition/runner.py` exports `IgnitionError`, `IgnitionGraphDelta`, `tree_digest`, `candidate_behavior`, `fourfold_graph_delta` and nothing else | green |
| A3 | The fault matrix still has 10 rows, one per fault | `pytest tests/ignition --co -q` → 10 | green |
| A4 | Exit 0 implies `replay_demonstrated` for a replay run | `tests/test_ignition_gate1.py::test_exit_zero_implies_replay_demonstrated` (RED before the fix with B1's exact assertion) | green |
| A5 | An incomplete predecessor is a blocker | `::test_a_predecessor_that_did_not_complete_is_not_a_replay`, `::test_a_predecessor_whose_completeness_was_not_measured_is_not_a_pass` | green |
| A6 | A criterion change is refused even with every identity stable | `::test_a_criterion_change_is_refused_even_when_every_identity_matched` | green |
| A7 | The blocker chain recovers: run 3 after a blocked run 2 is a replay | third `write_receipt` in `::test_exit_zero_implies_replay_demonstrated` | green |
| A8 | Each ported refusal row is discriminating | guard disabled in `gate1.py`, node goes red, guard restored (F1, F4 rows) | green |
| A9 | Byte-pin census unchanged and complete | `pytest tests/test_ignition_bundle_gitattributes.py tests/test_byte_pin_eol_durability.py` | green |
| A10 | The committed receipt demonstrates the replay | `runs/ignition/mission-gate1-voltage-ignition/receipt.json` | **BLOCKED on an owner action** — see below |

### The ported rows

| Row | Was (rehearsal) | Now (door) |
| --- | --- | --- |
| green path | `run_voltage_ignition` return values | `run_gate1_ignition` + CAS artifact identity + the composed tree |
| replay identity | in-memory bundle digests | CAS sha256, snapshot, delta, and `replay_demonstrated` |
| owner approval | binds `"1"*40` and an in-memory digest | binds the resolved git base revision and the CAS artifact |
| candidate revision identity | caller-supplied argument varied | derived digest, read back by materializing the stored tree |
| restart over debris | `materialize_voltage_rename` exists-check | `prepare_ignition_repo` + `compose_candidate` exists-checks |
| nested candidate root | refused before the first write | detected by the fixture-digest tripwire AFTER the run (OPEN row F5) |
| tampered base claims | base Twin compile refuses | unchanged mechanism, reached through the door |
| rename precondition | exact-count `_replace` | `plan_work_items` + `rename_operator` refusals |
| mid-run source mutation | `_tree_digest` before/after | `gate1.py:727` vs `gate1.py:1280` tripwire |
| crash between writes | kill after the 3rd of 6 writes | kill the 2nd work item's operator; `compose_candidate` refuses the empty patch |

### A10 — why the receipt was not refreshed

`python -m daedalus.ignition` was run once from this worktree. It exited 1, and
the first blocker is not about the slice:

```
work item wi-000-c41495030c8f could not lease: the kill switch for the
installation control root is engaged (kill switch engaged: no permit file: the
loop is not armed [C:\Users\nukei\.daedalus\control\232f43bed32a\killswitch])
```

The door derives its control root from the checkout it runs in
(`daedalus/spine/killswitch.py` `control_root`). The main checkout's permit is
armed; this worktree's control root, created for this packet, has **no permit
file and no `.stopped` marker** — it has never been initialized
[MEASURED 2026-09-06, `default_switch_path` for both roots]. Every attempt is
therefore refused a lease, the composed candidate is the unrenamed base tree,
and the remaining blockers all follow from that.

Arming a kill switch is granting permission to perform effects on the owner's
machine. Invariant 8 names the kill switch as a boundary enforced at effect
boundaries, and no instruction reaching an implementation agent is the owner's
consent, so the packet **stopped here instead of arming it**. The tracked
receipt store was restored to its committed state (`git checkout -- runs/`,
`git clean -fd runs/ignition/`) so the branch carries no receipt claiming a
Gate-1 result nobody produced; the refused receipt's content is retained in the
task report.

To finish A10, an operator arms this worktree's control root and runs the door
three times — drift, incomplete predecessor, replay. That is the sequence
`G1-RENOVATION-01` §3 finding 3 already documents, now one run longer because
run 2 correctly refuses:

```
python -c "from pathlib import Path; from daedalus.spine.killswitch import KillSwitch, default_switch_path; KillSwitch(default_switch_path(Path.cwd())).arm()"
python -m daedalus.ignition   # exit 1: evaluator-bundle drift vs the 2026-08-30 receipt
python -m daedalus.ignition   # exit 1: predecessor incomplete  <- new, and correct
python -m daedalus.ignition   # exit 0: replay_demonstrated true, blockers []
git add runs/ignition && git commit
```

The `execution_blockers` field WAS exercised by the real door in that run and is
present in the receipt it wrote, so the new receipt shape is not unverified —
only a green receipt is missing.

## Migration and rollback

Migration: none for callers — nothing outside `daedalus/ignition/` imported the
deleted names [MEASURED]. Receipts written before this packet carry no
`execution_blockers`; `write_receipt` falls back to their concatenated
`blockers`, which errs toward "the predecessor was incomplete" and never toward
a replay claim nobody earned.

Rollback: `git revert` the packet's commits. The deleted rehearsal is at
`585b7ea4:daedalus/ignition/runner.py`.

## Evidence, expected failures and review

- The door now exits 1 one more time than before after any evaluator-bundle
  change: run 1 blocks on drift, run 2 blocks on the incomplete predecessor,
  run 3 is the replay. That is the honest cost of making the exit code mean
  what the receipt says, and it matches what `G1-RENOVATION-01` §3 finding 3
  already documented about bundle drift.
- OPEN row F4 (candidate import into the verifier process) and OPEN row F5
  (the isolation refusal is late and dirty) are named in the checklist, not
  closed.
- The ported matrix is slower: it needs two completed door runs plus three
  faulted ones. They are shared through session-scoped fixtures in
  `tests/ignition/conftest.py`; measuring the cost is not possible on this
  host today (it is under load), so no timing is claimed.

### Review questions

1. Is `execution_blockers` the right place to draw the line between a run's own
   failure and a failed replay comparison, or should the receipt schema version
   move for it?
2. Row F5: should `run_gate1_ignition` refuse a `workspace` inside
   `fixture_root` up front, or is the tripwire enough for a door whose only
   caller is `__main__`?
3. The ported nested-workspace row asserts a WEAKER property than the
   rehearsal's did. Is naming it as OPEN row F5 sufficient, or does the
   checklist §1 claim need to be withdrawn rather than qualified?

### The commands

See `.superpowers/sdd/2026-09-06-daedalus-forward-plan/task-B2a-report.md` for
the per-row RED/GREEN transcript. Commands, all from the isolated worktree
`.claude/worktrees/b2a-one-ignition-path` with its own `uv` interpreter:

```
.venv/Scripts/python.exe -m pytest -q --color=no -p no:cacheprovider \
    tests/ignition tests/test_ignition_gate1.py tests/test_ignition_bundle.py \
    tests/test_ignition_bundle_gitattributes.py tests/test_byte_pin_eol_durability.py
```

133 nodes green: 108 in the three ignition suites (up from the 104 baseline by
exactly the four nodes of the conjunct fix), plus the 25 byte-pin nodes. The
door run is A10 above.

Iron Plan: ALIGNED · Iron Gate: 1 · touches invariants 1 (one kernel), 3
(isolation), 6 (atomic revisions), 7 (provenance); plan §13 "no second
implementation truth"; `AGENTS.md` §3 "prefer deletion and consolidation".
