# Continuous Daedalus on Windows

This is the supported operator setup for running Daedalus after the chat or
terminal that initiated the work has closed. It schedules the repository's
existing bounded loop rather than inventing a second autonomous worker.

## What the task does

The Windows task `\Daedalus\GateLoop` starts:

```powershell
python -m daedalus.orchestration.loop `
  --repo-root <this checkout> `
  --max-iterations 3 `
  --max-wall-clock-s 1500 `
  --max-spend-usd 1.00 `
  --max-attempts-per-candidate 1 `
  --queue-limit 25 `
  --json `
  --arm
```

The exact defaults are intentionally small. Each hourly activation may pick,
attempt, gate, and retain candidate artifacts. It cannot merge a branch,
promote a candidate, mint `OwnerApproval`, close a Gate, or convert missing
evidence into a pass. Those authority boundaries remain where the Master Plan
puts them.

Task Scheduler is configured with `IgnoreNew`, so a new activation is discarded
while an earlier one is still running. The task runs at `Limited` privilege in
the current user's interactive session. It therefore runs while the PC is on
and that user is logged in; the installer stores no Windows password.

## Install

From the repository root, while signed in as the non-built-in operator account
that will run the task:

```powershell
powershell -ExecutionPolicy Bypass -File tools/continuous_daedalus.ps1 Install
```

Custom bounds are explicit:

```powershell
powershell -ExecutionPolicy Bypass -File tools/continuous_daedalus.ps1 Install `
  -IntervalMinutes 60 `
  -MaxIterations 3 `
  -MaxWallClockSeconds 1500 `
  -MaxSpendUsd 1.00 `
  -MaxAttemptsPerCandidate 1
```

Installation arms the existing fail-closed kill switch without forcing it. If a
human previously stopped the loop, installation refuses. A deliberate override
requires the visible `-ForceRearm` argument; scheduled executions never contain
`--force`.

The built-in Windows `Administrator` account (RID 500) is deliberately
unsupported. Windows ignores `RunLevel=Limited` for that principal, so a task
whose metadata says `Limited` can still execute elevated; under a filtered UAC
token registration also fails with `0x80070005`. The installer refuses this
account before arming the kill switch or writing Task Scheduler state. Use a
non-built-in operator account. If that same account has a linked administrator
token and local policy requires one setup-time UAC confirmation, registration
does not change the task's `Interactive`, `Limited` runtime principal. Do not
enter credentials for a different administrator: that would change the
current-user principal. `Status` and `Stop` remain ordinary-shell operations.
This follows Microsoft's documented
[Task Scheduler UAC security contract](https://learn.microsoft.com/en-us/windows/win32/taskschd/security-contexts-for-running-tasks).

Any other registration failure leaves the kill switch `STOPPED`; an
armed-but-uninstalled partial state is not accepted.

## Operate

```powershell
# Task metadata, last result, next run, exact command, and kill-switch state
powershell -ExecutionPolicy Bypass -File tools/continuous_daedalus.ps1 Status

# Execute one bounded run now in the foreground
powershell -ExecutionPolicy Bypass -File tools/continuous_daedalus.ps1 RunOnce

# Ask Task Scheduler to start the installed task now
powershell -ExecutionPolicy Bypass -File tools/continuous_daedalus.ps1 Start

# Sticky human stop: terminates the task and blocks every later scheduled arm
powershell -ExecutionPolicy Bypass -File tools/continuous_daedalus.ps1 Stop

# Deliberately arm again after inspection
powershell -ExecutionPolicy Bypass -File tools/continuous_daedalus.ps1 Arm -ForceRearm

# Remove the task and leave the kill switch stopped
powershell -ExecutionPolicy Bypass -File tools/continuous_daedalus.ps1 Uninstall
```

The loop's durable records remain under `runs/loop/`, the Spine ledger, the
candidate artifact store, and the normal progress surfaces. The Task Scheduler
result is operational metadata; it is not test or Gate evidence.

## Gate 0 through Gate 2

“Work until Gate 2” is a delivery direction, not permission to skip the gate
sequence. The loop follows the repository picker and any enabled, revision-bound
work queue. It must finish Gate 0 work before Gate 1 activation, and Gate 1
before Gate 2 activation. Later experiments may remain available as evidence,
but they cannot retroactively close an earlier Gate.

The continuous task alone cannot complete the owner-controlled steps:

- merge or promotion decisions;
- exact-head independent architecture and security review;
- `OwnerApproval` or a Gate closure decision;
- restoration of GitHub Actions issue #67;
- acceptance of residual risk.

It can continue producing bounded, gated candidates while those decisions are
pending. Once a candidate is accepted, an owner-controlled promotion path must
handle it separately.

## Safety properties

- The scheduled action is the already registered `cli.loop` entrypoint.
- Every activation has finite iteration, time, spend, and convergence bounds.
- `IgnoreNew` prevents overlapping scheduled instances.
- `Interactive` plus `Limited` avoids SYSTEM/admin execution and password
  storage.
- The kill switch is sticky and scheduled runs cannot force-rearm it.
- The installer contains no Git merge, push, reset, promotion, or approval
  command.
- Uninstall stops the loop before removing the task.

A user can always stop the underlying mechanism directly:

```powershell
python -m daedalus.spine.killswitch stop "operator request"
```
