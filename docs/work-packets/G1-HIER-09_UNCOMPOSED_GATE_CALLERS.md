# G1-HIER-09 - Uncomposed gate callers

## Frozen packet metadata

- Packet ID: G1-HIER-09
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: 39039b7fbc8e5bee8b5d40eba6d065b32637db77
- Dependencies: G1-HIER-03B, G1-HIER-03D, G1-GATE-01
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

Every caller of the registered `spine.attempt` gate doors reaches them through
the single composition root `daedalus.orchestration.execution.attempts`, which
injects the `ScratchCleanupPort`. The thirteen `AttemptPortMissing` failures left
by G1-HIER-03D pass because the callers were migrated, not because the port
became optional, and a scored instrument now detects the next such caller
without a 41-minute suite run.

## Scope

- `tools/bootstrap_receipt.py`: `run_single` imports `command_gate`,
  `compose_task_attempt` and `run_attempt` from the composition root instead of
  the bare door.
- `tests/test_gate_containment.py`: nine gate invocations move to the composed
  gate; the door's signature assertion stays on the door and gains the composed
  callable.
- `tests/test_killswitch.py`: two gate invocations move to the composed gate.
- `tests/contracts/test_uncomposed_gate_callers.py`: new scored instrument.
- Out of scope, deliberately, and named here rather than silently widened:
  the `workspace_port` obligation on `TaskAttempt`/`run_attempt`, which has two
  further un-migrated callers measured below; the registered doors' signatures,
  targets, anchors and effects; the Effect Registry digest; the `spine.attempt`
  facade's refusal logic; any change to `ScratchCleanupPort` itself.

## Contracts and behavior

Nothing in the kernel, the doors, or the registry changes. This packet moves
callers onto an existing root and adds one read-only instrument.

- `kernel.attempt_execution._command_gate` keeps `scratch_cleanup` as a
  required keyword-only port with no default, and keeps the
  `if not callable(scratch_cleanup)` refusal.
- `spine.attempt.command_gate` and `spine.attempt.pytest_gate` keep refusing an
  uncomposed call with `AttemptPortMissing` before `begin_effect` and before
  any process creation. The refusal is the contract, not the bug.
- `orchestration.execution.attempts` remains the only shipped module that binds
  `remove_tree_no_follow` into a gate door. The new instrument asserts that set
  is exactly one element, so a second binder is a test failure rather than a
  second authority over candidate scratch cleanup.
- `tools/bootstrap_receipt.py::run_single` previously refused on **two**
  distinct ports: `workspace_port` on every invocation, and additionally
  `scratch_cleanup` when `--gate-command` was passed. Routing its three names
  through the composition root closes both; `_composed_kwargs` derives the
  workspace port from the `repo_root` the tool already supplies. The tool's
  receipt shape, ledger, lease acquisition order, artifact deposit and
  primary-checkout fingerprinting are untouched.
- The two migrated test modules drive the same registered door, the same kernel
  `_command_gate`, and the same real subprocess trees. The only difference is
  the injected port, which is what production supplies. `_contained_gate_child`
  monkeypatching still reaches the kernel through the `_AttemptFacade`
  `__setattr__` forward, so the spawn seam is unchanged.

### Three explicitly refused shortcuts

Each of these would have turned honest reds green while widening the
hole the ports packets opened deliberately:

1. **A working default for `scratch_cleanup`.** It converts a required port
   into an optional one and re-opens the hole for every future caller. Stated
   precisely, because the two layers spell the requirement differently:
   `kernel.attempt_execution._command_gate` takes it keyword-only with **no
   default at all**, while the `spine.attempt` doors carry
   `ScratchCleanupPort | None = None` — a sentinel that exists solely to drive
   the `if not callable(...)` refusal, not a usable fallback. Binding a real
   callable at either layer is the shortcut being refused.
2. **Skipping cleanup when the port is absent.** That is a silent degradation
   of an effect boundary, which the master plan forbids outright.
3. **Weakening or xfailing any of them.** They were correct. They were
   measuring an uncomposed path that production does not take.

## Acceptance matrix

| Claim or refusal | Evidence | Expected |
|---|---|---|
| The eleven pass honestly | `tests/test_gate_containment.py` + `tests/test_killswitch.py` | 72 passed, 0 failed |
| The unlisted twelfth and thirteenth | `tests/test_bootstrap_receipt.py` | 2 failed -> 1 failed; the survivor's cause changed |
| Port stays required | source of `kernel/attempt_execution.py:1054,1095` | keyword-only, no default, refusal intact |
| Door still refuses uncomposed | `tests/orchestration/test_attempt_composition_hierarchy.py`, `tests/test_cli_effect_boundary.py` | `AttemptPortMissing` still raised |
| No uncomposed shipped caller | `tests/contracts/test_uncomposed_gate_callers.py` | zero findings over 460 tracked files |
| Instrument can go red | planted-source tests + scan of the pre-fix committed blob | flags `bootstrap_receipt.py:506` |
| One composition root | binder-set assertion in the same file | exactly `orchestration/execution/attempts.py` |
| Effect authority unchanged | `registry_sha256()` | `ac02027836...396211ec` |
| Gate profile | `tools/run_gate_checks.py g1` | 122 passed, 1 skipped (115 + the 7 new) |
| Import census unchanged | `tests/contracts/test_import_scc_hierarchy.py` | unchanged; no `.py` added under `daedalus/` |
| Full suite | `pytest tests/ -q -p no:randomly` | pre-existing failures 38 -> 26 |

## Migration and rollback

No persistent-data, ledger, CAS, artifact, evidence, receipt, branch, policy or
runtime migration. No schema, no stored locator and no registry row changes.

Rollback is reverting this commit: the callers return to the bare door and the
twelve return to red. Rollback does not require restoring a default port,
because none was introduced.

`tools/bootstrap_receipt.py` is the only behavioral change reaching an operator.
Before this packet every `run_single` invocation raised `AttemptPortMissing`.
After it, the unleased path runs; the `--leased` path gets further and then
refuses cleanly on the unrelated intent-ledger resolver port described below,
reporting `lease_refused` through the normal receipt path rather than raising.
There is no configuration to migrate and no output shape that changes, because
the previous behavior was a hard refusal in every case.

## Evidence expected failures and review

### Retained negative evidence: why thirteen loud reds survived ten commits

This is the finding worth keeping, and it is not "the tests were quiet". They
were as loud as a test can be — an uncaught exception, thirteen times, with the
exact port name in the message.

They survived because **nobody ran them**. The full suite is 9,722 items and
about 41 minutes, so every packet ran only its own subset, and
`tests/test_gate_containment.py`, `tests/test_killswitch.py` and
`tests/test_bootstrap_receipt.py` were in no packet's subset. `run_gate_checks
g1` did not reach them either. The defect was not detection; it was that the
only instrument that would have reported it cost 41 minutes, and so was run
rarely enough for thirteen failures to sit unnoticed.

The third caller, `tools/bootstrap_receipt.py`, was red for the same reason and
in the same way. An earlier draft of this document claimed it "failed silently,
because no test executes it at all". **That was wrong, and the correction is
the point of this paragraph.** `tests/test_bootstrap_receipt.py` does execute
`run_single`, and it was failing loudly with the same message — it was simply
not in the eleven anyone had clustered, and not in any packet's subset either.
The tempting story ("tests were missing") was more flattering than the measured
one ("the tests existed, were red, and were not run"). Only the second is true.

So all thirteen were loud. Loudness was never the missing ingredient. What was
missing is a check cheap enough to be run every time: the new instrument is
pure AST over tracked source, takes about four seconds, and sits in the `g1`
profile, so the next uncomposed caller is caught by a scored check rather than
by a suite nobody can afford to run per packet.

The instrument was verified capable of going red before being trusted: run
against the committed pre-fix blob of `tools/bootstrap_receipt.py` it returns
`[(506, 'command_gate')]`, the exact defect line; against the fixed working
copy it returns `[]`.

### Measured open items, not fixed here

The sibling `workspace_port` obligation on `TaskAttempt`/`run_attempt` has two
further un-migrated shipped callers. Both are outside this packet's axis and
are reported rather than folded in, because a packet changes one axis:

- `tools/operability_drill.py:412` constructs
  `TaskAttempt(TaskSpec(...), runner=..., repo_root=..., gate=...)` with no
  workspace port. It will raise `AttemptPortMissing`.
- `tools/system_check.py:463-475` builds a **generated source string** that
  imports `TaskAttempt` from `daedalus.spine.attempt` and constructs it without
  a workspace port. No AST scan of this repository can see it, because the call
  does not exist as syntax until the string is executed in a child interpreter.
  That second case is the more interesting one and deserves its own packet:
  a caller hidden in a string is invisible to every static instrument here.

`daedalus/spine/bootstrap.py` and `daedalus/spine/picker.py` were checked and
are correctly migrated: both refuse without an injected `attempt_ports_factory`
and pass `workspace_port`/`evaluator_port` explicitly.

### Expected failures, and a corrected count

The task that commissioned this packet named **eleven** failures with the
`AttemptPortMissing: scratch_cleanup` signature, in two files. Measured, the
signature covered **thirteen**, in three. The cluster missed
`tests/test_bootstrap_receipt.py`, which contributed two:

- `TheExternalTargetReceipt::test_external_attempt_binds_repo_storage_gate_and_ledger`
- `TheLeasedSingleAttempt::test_leased_single_run_terminalises_and_reports`

Both were verified to fail at the base revision with the identical message
(`command gate requires an injected scratch_cleanup port`, raised at
`daedalus/spine/attempt.py:82`) by running the file against the committed
`tools/bootstrap_receipt.py` with this packet's change stashed: `2 failed,
26 passed`. With the change applied: `1 failed, 27 passed`.

So twelve of the thirteen now pass. The full-suite arithmetic closes exactly:
38 pre-existing failures minus 12 fixed = **26 measured**, which is what the
suite reported. The predicted 27 assumed the cluster of eleven was complete.
The difference is one additional fixed test, not an unexplained drift.

The thirteenth, `TheLeasedSingleAttempt`, still fails — and this is the part
worth stating precisely, because a changed cause under an unchanged red is
easy to mistake for no progress. It no longer fails on `scratch_cleanup`. It
now fails further along the same lease path, on a **different un-composed
port**:

    spine.intent_ledger: no repository-confined intent-ledger path resolver
    port was composed; the lease is refused before any SQLite access

That is a third port, belonging to the `offload_lease`/intent-ledger packets,
not to the Attempt ports this packet closes. It is out of scope here and is
recorded as a prerequisite for whichever packet owns that resolver.

The remaining 25 failures are unrelated pre-existing reds. This packet neither
fixes nor hides them. Four of them fall inside this packet's verification
selection and were confirmed still failing at clean HEAD with every change
stashed, so none is attributable here:

- `tests/kernel/test_offload_lease_outer_ports.py::test_cold_kernel_import_loads_no_outer_implementation`
- `tests/kernel/test_runtime_terminal_capability.py::test_runtime_authorization_refuses_foreign_terminal_receipt_before_ledger`
- `tests/kernel/test_runtime_terminal_capability.py::test_runtime_authorization_delegates_own_terminal_receipt_exactly_once`
- `tests/orchestration/test_run_mission.py::test_migrated_surfaces_delegate_without_a_second_execution_path`

### Deliberate count movements

Two pinned counts move because this packet deliberately adds scored artifacts.
Neither is a regression and neither is folded into another total:

- `run_gate_checks g1`: 115 passed, 1 skipped -> 122 passed, 1 skipped. The
  delta is exactly the seven tests in the new instrument; the skip is unchanged.
  (The 115 is the base revision's own count. An earlier draft of this document
  said 114 -> 121, measured against `cbb55b9c`; the trunk was amended to
  `39039b7f`, which added `tests/contracts/test_suite_runs_in_a_virtual_environment.py`
  and moved the baseline by one. Re-measured rather than carried forward.)
- The Work Packet registry census moves by one document, and
  `tests/contracts/test_work_packet_index.py` is re-pinned accordingly with
  `G1-HIER-09` added to `expected_primary_ids`.

`tests/contracts/test_import_scc_hierarchy.py` does **not** move: its census
reads `git ls-files -- daedalus`, and this packet adds no module under
`daedalus/`.

### Review

Independent review must confirm that no default value was added to
`scratch_cleanup` anywhere in the chain, that the door's refusal is still
reachable and still tested, that the migrated tests still spawn real
subprocesses rather than mocking the gate, that the new instrument is not
vacuous, and that no second binder of the cleanup port was introduced.

No builder result promotes or merges this packet.
