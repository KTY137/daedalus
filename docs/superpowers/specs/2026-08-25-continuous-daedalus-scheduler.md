# Continuous bounded Daedalus scheduler

- Work Packet ID: `G0-OPS-CONTINUOUS-LOOP-20260825`
- Classification: `ALIGNED`
- Active gate: Gate 0 — Canonical Kernel
- Base branch: `main`
- Delivery branch: `ops/continuous-daedalus-loop`
- Automatic merge or promotion: forbidden

## Problem

Chat-level tasks are not a durable worker. When the initiating chat closes,
there is no process left that can continue repository work. Daedalus already
contains the bounded `daedalus.loop` driver and the fail-closed kill switch, but
there was no small operator surface that installed that exact entrypoint as a
per-user Windows scheduled task.

## Chosen composition

The operator script registers one task, `\Daedalus\GateLoop`, whose action is
the existing command:

```text
python -m daedalus.loop --repo-root <checkout> --max-iterations 3
  --max-wall-clock-s 1500 --max-spend-usd 1.00
  --max-attempts-per-candidate 1 --queue-limit 25 --json --arm
```

No second loop, picker, budget ledger, candidate writer, promotion path, or kill
switch is introduced. Task Scheduler supplies repetition and `IgnoreNew`; the
existing loop supplies selection, containment, gates, receipts, convergence,
budgeting, and nomination-only behavior.

## Exact authority boundary

The scheduled action enters through `cli.loop`, which already begins at the
canonical effect boundary. The PowerShell file is an operator installation and
control helper; it does not become a candidate-facing implementation selector.
It invokes the centrally guarded kill-switch CLI for arm/stop operations.

The helper contains no command that merges, pushes, resets, promotes, issues
approval, or changes Gate state. Installation does not force-rearm a sticky
human stop unless the operator explicitly supplies `-ForceRearm`. The generated
scheduled argument string never includes `--force`.

## Frozen defaults

| dimension | default | reason |
| --- | ---: | --- |
| interval | 60 min | frequent progress without rapid restart pressure |
| iterations per activation | 3 | bounded work packet count |
| wall clock | 1500 s | finishes before the next normal activation |
| spend | USD 1.00 | one finite per-run ceiling |
| attempts per candidate | 1 | scheduled runs do not grind on one item |
| queue limit | 25 | bounded picker materialization |
| overlapping instances | `IgnoreNew` | no concurrent unattended loops |
| principal | current user, `Interactive`, `Limited` | no stored password, SYSTEM, or elevation |

Task Scheduler receives an execution-time limit five minutes larger than the
loop wall-clock limit. This permits the loop to emit final receipts and clean up
while still providing an operating-system backstop.

## Acceptance contract

1. The task action names `daedalus.loop` and every finite bound.
2. Scheduled arguments contain normal `--arm` but no `--force`.
3. `MultipleInstances` is `IgnoreNew`, never `Parallel`.
4. The principal is the current user with interactive logon and limited run
   level.
5. A 20-year finite trigger duration is used instead of an invalid
   `TimeSpan::MaxValue` XML representation.
6. `Stop` writes the sticky kill-switch state and stops the scheduled task.
7. `Uninstall` removes the task and leaves the loop stopped.
8. Static tests refuse repository-mutation, promotion, approval, and
   branch-protection bypass commands in the helper.
9. The documentation states that Gate closure and promotion remain
   owner-controlled and evidence-bound.

## Verification requested

- Python static contract tests in
  `tests/test_continuous_daedalus_scheduler.py`;
- PowerShell parser validation on Windows;
- installation/status/run-once/stop/restart/uninstall exercise on the owner
  machine;
- confirmation that a second activation is ignored while the first runs;
- confirmation that a sticky stop makes a later scheduled `--arm` exit without
  work;
- normal affected/full-suite/package checks when GitHub Actions issue #67 is
  restored.

Hosted Actions with `steps=null` or no logs remain infrastructure observations,
not verification. This packet does not claim that the Windows task has been
installed on the owner's computer merely because the installer exists in Git.

## Rollback

Run:

```powershell
powershell -ExecutionPolicy Bypass -File tools/continuous_daedalus.ps1 Uninstall
```

Then revert the branch commits. Uninstall deliberately leaves the kill switch
stopped, so rollback cannot cause an unattended restart.
