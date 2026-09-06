# G1-RENOVATION-01 — Gate-1 Renovation residual, measured against HEAD

Packet: `G1-RENOVATION-01_RESIDUAL_MEASUREMENT` (evidence-only). Delegate: Atalanta.
Date: 2026-09-06. Base: `585b7ea4e141332928ad6c9578b9c9997e55f247`
(branch `codex/ikarus-computer-assistant-20260905`; tree dirty in unrelated
lanes — `daedalus/ignition/**` and `tests/ignition/**` are clean at HEAD,
`git status --porcelain` on those paths returned empty).

Iron Plan: ALIGNED · Iron Gate: 1 · Scope: measurement only. Nothing under
`daedalus/`, `tests/` or `runs/` was edited by hand. `runs/ignition/` was
written by `python -m daedalus.ignition` itself (registered effect door
`cli.ignition`).

Interpreter: `.venv/Scripts/python.exe` (CPython 3.13, uv-managed).
Host state: **under load** — 12 python processes, ~79 % average CPU at start
(a full-suite baseline was running concurrently). **No wall-clock number in
this document is a performance measurement.**

---

## 1. What was run

```
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --color=no \
    tests/ignition tests/test_ignition_gate1.py tests/test_ignition_bundle.py --co
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider --color=no \
    tests/ignition tests/test_ignition_gate1.py tests/test_ignition_bundle.py
.venv/Scripts/python.exe -m daedalus.ignition        (three consecutive runs)
```

### 1.1 Suite — raw tail

```
........................................................................ [ 69%]
................................                                         [100%]
============================== warnings summary ===============================
tests/test_ignition_gate1.py: 6 warnings
tests/test_ignition_bundle.py: 7 warnings
  C:\Users\nukei\AppData\Roaming\uv\python\cpython-3.13-windows-x86_64-none\Lib\shutil.py:1267: DeprecationWarning: Python 3.14 will, by default, filter extracted tar archives and reject files or modify their metadata. Use the filter argument to control this behavior.
    tarobj.extractall(extract_dir, filter=filter)

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
104 passed, 13 warnings in 872.00s (0:14:31)

[exited with code 0]
```

`104 passed` [MEASURED 2026-09-06, pytest tests/ignition tests/test_ignition_gate1.py
tests/test_ignition_bundle.py]. Split: `tests/ignition` 10 nodes,
`tests/test_ignition_gate1.py` 34 nodes, `tests/test_ignition_bundle.py` 60 nodes
[MEASURED 2026-09-06, `--co`]. The `872.00s` is **load-contaminated and is not a
timing claim**; it is quoted only because it is part of the raw tail.

### 1.2 `python -m daedalus.ignition` — three runs

| Run | exit | `blockers` | `replay.is_replay` | `replay.replay_demonstrated` |
| --- | --- | --- | --- | --- |
| 1 (07:46Z… `collected_at` `2026-09-06T06:46:35Z`) | 1 | 1 | true | false |
| 2 (`collected_at` `2026-09-06T07:01:01Z`) | 0 | 0 | true | false |
| 3 | 0 | 0 | true | **true** |

Run 1 raw blocker:

```
"blockers": [
  "the previous receipt was produced by a different evaluator bundle (6f6326038841); two runs are a replay only under one bundle"
]
```

The predecessor on disk was from `2026-08-30T11:00:00Z` under evaluator bundle
`6f6326038841…`; HEAD's bundle is `7b4a683460450873131b26e5981582741ff737d82af125b21c5aca1008aee2be`.
The blocker is **evaluator-bundle drift against a stale receipt, not a slice
failure** [MEASURED 2026-09-06].

Run 3 replay block (raw):

```
is_replay = True
replay_demonstrated = True
previous_run_complete = True
same_evaluator_bundle = True
same_fixture = True
criterion_changed_since_previous = False
packet_sha256_stable = False
mission_sha256_stable = None
base_revision_stable = True
candidate_revision_stable = True
graph_delta_stable = True
check_reports_stable = True
mission_id_stable = True
work_item_ids_stable = True
evidence_status per attempt: ['passed', 'passed']
lease outcomes: ['COMPLETED', 'COMPLETED']
```

`packet_sha256_stable` and `mission_sha256_stable` are deliberately outside
`REPLAY_REQUIRED_STABLE` (`daedalus/ignition/gate1.py:1505-1516`: evidence items
bind raw evaluator output and pytest prints its own duration; the mission digest
is clock-bound), so `replay_demonstrated` is true without them.

Receipt: `runs/ignition/mission-gate1-voltage-ignition/receipt.json`
(`schema: daedalus-gate1-ignition-receipt/1`).

Selected receipt facts [MEASURED 2026-09-06, run 3 unless noted]:

- `mission_id` `mission-gate1-voltage-ignition`, `mission_sha256`
  `cd75e464d221ce423dec25d66f51df494e8e8a8b9837c6b0c16037b7cdd21be1` (run 1).
- `work_item_ids` `["wi-000-c41495030c8f", "wi-001-c8c563f2c0da"]`.
- `mission_source_revision` / `replay.base_revision`
  `ebd198e90563554297ec644d2318496b52977ed5` — a real 40-hex git revision.
- `source_trees.base_locator` / `candidate_locator`
  `artifact-locator:sha256:42d41a5b…` / `artifact-locator:sha256:4f0f7e2e…`,
  `store_root` `runs/ignition/mission-gate1-voltage-ignition/source-trees`.
- `check_kinds` `["link", "pytest", "schema"]`; the packet carries 7
  `EvidenceItem`s, all `verdict: passed`, all `assurance: deterministic`.
- `promotion` = `{"auto_merge": false, "owner_approval": "not requested",
  "status": "nominated, not promoted"}`.
- Both attempts: `lease_outcome COMPLETED`, `lease_error null`,
  `policy_verdict allow`, distinct `policy_decision_sha256`
  (`7446e1e0…`, `818c9e58…`), distinct `attempt_contract_sha256`.
- `cost.wall_clock_s` 82.8 / 61.4 — **load-contaminated, not a timing claim.**

---

## 2. Row table

Rows are the checkboxes of `docs/work-packets/G1_ACTIVATION_CHECKLIST.md` §2.1–§2.6,
in document order.

| # | Checklist row | State | Proof (node id / receipt field / source) |
| --- | --- | --- | --- |
| 2.1-a | No `MissionContract`; hardcoded mission/attempt ids; placeholder `attempt_contract_sha256` | **CLOSED** | receipt `mission_sha256=cd75e464…`, `mission_source_revision=ebd198e9…`, per-attempt `attempt_contract_sha256` (`9e05e232…`, `ae62d8ca…`); `gate1.py:300-301` mints via `mission_contract_for_build_session` over a real `BuildSession`; `tests/test_ignition_gate1.py::test_every_attempt_records_the_criterion_it_declared_and_the_command_that_ran` |
| 2.1-b | WorkItems are module constants `WORK_ITEMS`, not derived from the planes | **CLOSED** | `gate1.py:187-256` `plan_work_items(..., manifest_name="fourfold.json")` — "THE PLANES DECIDE THE SPLIT"; receipt `work_item_ids` are `derive_work_item_id` digests; `tests/test_ignition_gate1.py::test_replay_of_two_identical_runs_is_clean` (`work_item_ids_stable`) |
| 2.1-c | No events reach the spine: no Attempt begin/complete, no intent record, no effect lease | **CLOSED** | receipt `attempts[].lease_id`/`lease_outcome=COMPLETED`/`lease_error=null`; `gate1.py:906-940` `acquire_attempt_lease(..., contained=True, subject_root=repo, worktree_root=attempt._manager.worktree_root, intent_ledger_path_resolver=spine_picker.resolve_spine_db_path)`; registry row `daedalus/spine/effect_boundary.py:2857` `cli.ignition`, `wiring=CENTRAL`, `migration="complete for the cli.ignition entrypoint"` |
| 2.1-d | `policy_decision_sha256` is a stand-in | **CLOSED** | receipt `attempts[0].policy_decision_sha256=7446e1e0…` ≠ `attempts[1]=818c9e58…`, `policy_verdict=allow`; `gate1.py:1775-1776` reads `contracts.policy.digest`/`.verdict` |
| 2.2-a | Synthetic revisions `"1"*40`/`"2"*40`; no CAS storage | **CLOSED for the shipped path** | `gate1.py:341-368` `prepare_ignition_repo` → `git rev-parse HEAD` under `FROZEN_GIT_ENV` + `core.autocrlf=false`; receipt `base_revision=ebd198e9…`; `source_trees.*_locator` + `SourceTreeStore`; `tests/test_ignition_gate1.py::test_the_fixture_is_byte_identical_in_every_checkout`. **Residual:** the subject is still `tests/fixtures/ignition/voltage`, not a real base checkout; the legacy `run_voltage_ignition` path still uses `"1"*40`/`"2"*40` (`tests/ignition/test_voltage_ignition.py:19-20`) |
| 2.2-b | `collected_at` is a caller-supplied constant; needs bound clock/provenance | **OPEN (partial)** | constant is gone: `gate1.py:697-698` `_now()` = `datetime.now(timezone.utc)`, `gate1.py:725` `collected_at = collected_at or _now()`; receipt `collected_at=2026-09-06T07:01:01Z`. **Still a direct process clock — no injected clock port**, so the "runtime authorization clock" discipline the row names is unmet |
| 2.3-a | `shutil.copytree` in-process, no isolated coordinator; behavior probe imports candidate code INTO the verifier process | **OPEN (isolation half closed)** | Closed half: attempts run in `TaskAttempt` git worktrees via `GitWorktreeManager` with `Policy(write_allow=task.paths)` and `contained=True` (`gate1.py:918-940`); gates execute as `subprocess` pytest (receipt `attempts[].gate_command`). **Open half — unchanged at HEAD:** `daedalus/ignition/runner.py:138-157` `_behavior` does `sys.path.insert(0, source); importlib.import_module("ignition_app")`, called from `gate1.py:1068` `candidate_behavior(candidate_root)` in the verifier process; its output becomes packet item `gate1-behavior` |
| 2.3-b | No write-root/egress/spend bounds; not an inventoried effect entrypoint | **CLOSED** | `daedalus/spine/effect_boundary.py:2857-2881` `EntrypointSpec(id="cli.ignition", wiring=CENTRAL, effects=(FILESYSTEM_WRITE, PROCESS_SPAWN, PROCESS_CONTROL), guard_contracts=("budget.process_guard",), anchors=(GuardAnchor("daedalus.ignition.__main__:main","begin_effect"),))`; `daedalus/ignition/__main__.py` calls `begin_effect` **before** `argparse`; per-attempt write fence via `Policy(write_allow=…)` |
| 2.4-a | No test-run evaluator | **CLOSED** | receipt `checks.pytest.evaluator=ignition-pytest-composed` passed; packet item `gate1-check-pytest`; per-attempt `gate_command` runs real node ids (`tests/test_event_field.py::…`); `tests/test_ignition_gate1.py::test_every_rewritten_subject_is_read_by_some_evaluator` |
| 2.4-b | No schema-check evaluator | **CLOSED** | receipt `checks.schema.evaluator=ignition-schema-check`; packet item `gate1-check-schema`; `tests/test_ignition_gate1.py::test_the_data_knowledge_gate_still_fails_a_half_renamed_schema` |
| 2.4-c | No link-check evaluator | **CLOSED** | receipt `checks.link.evaluator=ignition-link-check`; packet item `gate1-check-links`; node `tests/test_event_field.py::test_wiki_links_resolve` in `attempts[1].gate_command` |
| 2.4-d | Verdicts hardcoded; a failing evaluator raises instead of producing a failed item; no "failed packet" state | **OPEN (partial)** | Closed half: `gate1.py:630` `verdict="passed" if report.passed else "failed"`; a failing gate is measured, not asserted (`tests/test_ignition_gate1.py::test_the_data_knowledge_gate_still_fails_a_half_renamed_schema` asserts `sink["schema"].passed is False` and `result.passed is False`). **Open half:** no run RETAINS a failed packet — `gate1.py:971-983` turns a non-ok attempt into a `blockers` entry and the slice stops; every `evaluation_status` assertion in the three suites is `"passed"` (`tests/test_ignition_gate1.py:252,432`, `tests/ignition/test_voltage_ignition.py:44`); no node produces `evaluation_status == "failed"` |
| 2.4-e | Revision-3.2 inputs: content-addressed runtime-conformance observations + restrictive sandbox policy | **OPEN (partial)** | Closed half: `evaluator_bundle_artifact` is content-addressed and retrievable (`digest 7b4a6834…`, `path bundle/evaluator-bundle-7b4a6834….json`), and the fixture conformance suite is digest-pinned (`discrimination.before_state.conformance_test_sha256=d2c96a98…`). **Open half:** that is the *fixture* suite, not live runtime-adapter conformance receipts; and `grep -rn "sandbox" daedalus/ignition/ tests/ignition/ tests/test_ignition_gate1.py tests/test_ignition_bundle.py` returns **nothing** — no sandbox policy is referenced by the packet |
| 2.5-a | Resume from the event spine (crash after Attempt-begin, same attempt identity, no duplicated effects) | **OPEN** | Attempt events now exist (2.1-c), so "restart = run again from scratch" is no longer the whole story — but same-identity resume is **impossible by construction** today: receipt `replay.note` states "attempt ids carry a per-run nonce by construction (the branch name IS the effect key) and are expected to differ between runs" (`gate1.py:2146-2149`, `effect_key=attempt.branch` at `gate1.py:911`). No node covers crash-after-begin resume |
| 2.5-b | Crash inside materialization (already `[x]`, 2026-08-18) | **CLOSED, coverage does not transfer** | `tests/ignition/test_voltage_ignition_faults.py::test_crash_between_rename_writes_leaves_no_evaluable_candidate` still passes. **But** it monkeypatches `daedalus.ignition.runner._replace` and drives `run_voltage_ignition`; `grep -n "run_voltage_ignition\|materialize_voltage_rename" daedalus/ignition/gate1.py` returns **nothing** — the shipped command does not use that materializer |
| 2.5-c | Concurrent double-start on one candidate root (TOCTOU) | **OPEN — but no longer blocked** | `grep -rn "concurrent\|double_start\|TOCTOU\|parallel" tests/ignition/ tests/test_ignition_gate1.py tests/test_ignition_bundle.py` returns **nothing**: zero coverage. The 2026-08-18 assessment ("not machine-doable ahead of order — requires an `AttemptContract` and a CAS `StoredSourceTree`, i.e. §4 steps 1–2") is **refuted**: both now exist (per-attempt `attempt_contract_sha256`; `SourceTreeStore`/`StoredSourceTree` in `gate1.py:86`, receipt `source_trees`) |
| 2.6-a | One-use approval consumption against the sealed `promote_candidates` stack (full non-promoting dry-run) | **OPEN** | receipt `promotion.owner_approval="not requested"`, `status="nominated, not promoted"`; `gate1.py` module docstring: "imports nothing from `daedalus.kernel.promotion`"; `tests/test_ignition_gate1.py::test_promotion_status_is_never_promoted` and `:372` assert no promote-named call. `tests/ignition/test_voltage_ignition.py::test_gate1_owner_approval_binds_exact_candidate_and_evidence` is still the schema-level bind/verify pair, on the legacy runner |

**Count: 10 of 17 rows CLOSED (9 newly measured closed + 1 pre-existing `[x]`), 7 OPEN.**

---

## 3. Findings the row table does not carry

1. **Two coexisting ignition implementations.** `daedalus/ignition/runner.py`
   (`run_voltage_ignition`, `materialize_voltage_rename`, synthetic revisions)
   is the 2026-08 rehearsal; `daedalus/ignition/gate1.py`
   (`run_gate1_ignition`, 2357 lines) is what `python -m daedalus.ignition`
   actually runs. `gate1` imports only `IgnitionError`, `IgnitionGraphDelta`,
   `candidate_behavior`, `fourfold_graph_delta`, `tree_digest` from the runner.
   All 10 nodes of `tests/ignition/` — including the entire fail-closed fault
   matrix the checklist §1 cites as settled — exercise the **rehearsal**, not the
   shipped path. The checklist was written against the runner and has been
   measuring the wrong module since at least 2026-08-30.
   [MEASURED 2026-09-06, `grep -n run_voltage_ignition daedalus/ignition/gate1.py` → empty]

2. **Exit code 0 does not mean replay was demonstrated.** Run 2 exited 0 with
   `blockers: []` while `replay_demonstrated` was `false`
   (`previous_run_complete: false`, because run 1 had a blocker).
   `_replay_blockers` (`gate1.py:1654-1690`) checks `same_fixture`,
   `same_evaluator_bundle` and `REPLAY_REQUIRED_STABLE`, but **not**
   `previous_run_complete` — which is a conjunct of `replay_demonstrated`
   (`gate1.py:2301-2312`) and of nothing else. A CI job that gates on the exit
   code would read run 2 as a demonstrated Gate-1 replay. Cheap fix: add the
   missing conjunct to `_replay_blockers`. [MEASURED 2026-09-06, runs 2 and 3]

3. **Evaluator-bundle drift silently invalidates the last receipt.** Any change
   inside the evaluator import closure (which includes
   `daedalus/kernel/offload_lease.py`, `daedalus/kernel/events/*`,
   `daedalus/kairos/worktree.py`, `daedalus/adapters/events.py`) moves the
   bundle digest and makes the next run a non-replay. Demonstrating replay
   therefore costs **two** runs after any such change, and three after a run
   that ended in blockers. This is correct behaviour, but it means a single
   `python -m daedalus.ignition` in CI can never be replay evidence.

4. **A named blocker has closed itself.** `gate1.py:1875-1897` describes an
   expected symptom — "each attempt's own EvidencePacket is `evaluation_status`
   'inconclusive' with an 'unverified' item". At HEAD both attempts measured
   `evidence_status: "passed"` with `evidence_assurance: ["deterministic"]` and
   `receipt.blocker` was `null` in all three runs. The `ATTEMPT_ASSURANCE_HUNK`
   scaffolding in `gate1.py` is currently dormant.

5. **`docs/work-packets/G1_ACTIVATION_CHECKLIST.md` §3 is stale.** It names
   "Gate-0 closure" and "78 `gate0.not_central` gaps" as activation
   preconditions. Gate 0 was closed by scoped owner decision on 2026-08-26
   (plan Revision 8). §3 was **not** re-measured by this packet — out of scope —
   but it must not be read as current.

---

## 4. Provenance

- `[MEASURED 2026-09-06]` — everything in §1 and every "Proof" cell that names a
  receipt field, a `--co` node id, or a grep result.
- `[INHERITED, G1-WP-01_VOLTAGE_IGNITION / G1_ACTIVATION_CHECKLIST 2026-08-17]` —
  the row texts themselves and the §1 "do not re-litigate" claims.
- `[ASSUMED]` — none load-bearing. The task brief's expectation (§2.1/§2.2/§2.3
  closed, §2.4/§2.5 open) was `[A]`; see §5.
- Not measured: POSIX behaviour (Windows host only); §3 activation
  preconditions; the full repository suite.

## 5. The brief's expectation versus the measurement

| Brief expected `[A]` | Measured |
| --- | --- |
| §2.1 closed | **confirmed** — all 4 rows closed |
| §2.2 closed (real git + `FROZEN_GIT_ENV`) | **partly refuted** — 2.2-a closed, 2.2-b (`collected_at` clock) still open |
| §2.3 closed (attempt boundary) | **partly refuted** — the effect-boundary row is closed, but the in-process candidate import is unchanged |
| §2.4 open (retained failed packet) | **confirmed**, and a second §2.4 row (Rev-3.2 sandbox/runtime-conformance inputs) is open too |
| §2.5 open (resume from spine, double-start race) | **confirmed**, with the 2026-08-18 "not machine-doable" assessment now refuted |
