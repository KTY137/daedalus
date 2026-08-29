# Fourfold/Tensor Gardener Campaign — cutoff 2026-09-29

This campaign is the bounded operator setup for the repository-owner direction
recorded in issue #239. It reuses the existing canonical Daedalus loop and the
existing Windows scheduler in `tools/continuous_daedalus.ps1`. It does not
create an immortal chat, a second autonomous worker, a second scheduler, a
second promotion path, or a new source of truth.

## Exact time boundary

Every activation determines the current date in `Europe/Berlin` before it can
launch a candidate.

- Through **2026-09-28**, one bounded activation may run.
- At **2026-09-29 00:00 Europe/Berlin**, a distinct final trigger runs.
- On or after **2026-09-29**, `tools/gardener_campaign.py` never invokes
  `daedalus.loop`; it stops the canonical kill switch and writes a final
  operator report outside the checkout.
- The repetition horizon ends at the same Berlin instant, so the installed task
  has no later work trigger. It may remain registered as inert history until an
  operator runs `Uninstall`.

The PowerShell scheduler converts Berlin midnight through Windows time-zone ID
`W. Europe Standard Time` to the host's local trigger time. The Python guard
checks the date independently using `Europe/Berlin` on every activation.

The final report inventories the exact Masterplan identity, checkout revision,
working-tree state, local and remote branch refs, and linked worktrees. It does
not invent a benchmark win or Gate transition.

## Operator-state location

The guard does not create `runs/gardener` or any other campaign-specific file
inside the Primary Checkout. Bounded stdout/stderr, waiting status, and the
final diagnostic report are operator state rather than Gate evidence and live
under:

```text
Windows: %LOCALAPPDATA%\Daedalus\gardener\fourfold-tensor-gardener-20260929\
Linux:   ${XDG_STATE_HOME:-~/.local/state}/daedalus/gardener/fourfold-tensor-gardener-20260929/
```

`DAEDALUS_GARDENER_STATE_ROOT` may select another existing or creatable operator
state parent. The guard refuses a selected location that overlaps the checkout.
The canonical loop continues to retain its own existing ledgers and candidate
evidence through the normal Daedalus path.

## What one activation runs

The scheduled action enters through the date/queue guard:

```powershell
python tools/gardener_campaign.py run `
  --repo-root <this checkout> `
  --campaign docs/campaigns/FOURFOLD_TENSOR_GARDENER_20260929.json
```

When work is still admissible, that guard invokes exactly one existing
canonical loop process, bounded to:

```text
--max-iterations 3
--max-wall-clock-s 1500
--max-spend-usd 1.00
--max-attempts-per-candidate 1
--queue-limit 25
--json --arm
```

The actual iteration count is lowered when fewer than three unattempted task
definitions remain. The Task Scheduler interval is six hours and the overlap
policy is `IgnoreNew`. It runs as the current interactive user at `Limited` run
level. A sticky human kill-switch stop remains authoritative; scheduled runs
never use `--force`.

## Cross-activation convergence

The repo-local queue is not replayed forever. The guard reads the existing Spine
attempt memory exposed by the canonical picker. Once a current task definition
has a retained attempt, that exact definition is no longer dispatched by later
campaign polls. When every current ready definition has been attempted, the
guard writes `waiting-owner.json` to the checkout-disjoint operator state and
performs no candidate execution.

Work resumes only after the owner integrates or rejects the candidates and
updates the revision-bound queue. Changing a task definition or its candidate
base creates a new auditable definition; the scheduler does not invent follow-up
work on its own.

## Curated work only

`.agentenv/work-queue.json` is the only enabled picker source for this campaign.
Map, inventory, evaluation and hotspot inference are disabled so a stale or
unrelated measurement cannot redirect the scheduled writer.

The current queue is bound to one exact candidate-base revision. That revision
already contains the narrow write policy but has `work_queue.enabled=false`, so
candidate worktrees cannot recursively schedule campaign tasks. A later control
commit enables the queue and points back to that frozen candidate base.

The queue contains:

- four independent ready packets: Fourfold contract gardening, the minimal
  tensor contract, the benchmark evidence contract, and a read-only
  branch/worktree reintegration plan;
- two blocked dependent packets: tensor projection after the tensor contract is
  owner-integrated, and gardening metrics after the canonical evolution package
  is owner-integrated.

Each ready task has one stable ID, explicit authority references, an exact
target-path set, a bounded gate command, and a priority inside the curated
work-queue band.

The write policy admits only:

- `daedalus/twin/`;
- `daedalus/evolution/`;
- `tests/`;
- `docs/`;
- `README.md`.

It does **not** admit `daedalus.spine`, budget, policy, runtime authority,
promotion, `.agentenv`, `.github`, or the adopted Masterplan. External provider
lanes remain advisory-only because `external_write_lanes` is still empty.

## Gardener discipline

The queue instructions apply the responsibility-led structure from the derived
Fourfold execution plan:

- canonical trust/runtime state stays in `daedalus.kernel` and
  `daedalus.runtimes`;
- scheduling stays in `daedalus.orchestration`;
- Fourfold, Forest, compiler, graph/tensor views and round trips converge in
  `daedalus.twin`;
- non-promoting search, benchmarks, corpus/motif experiments and retained
  negative evidence converge in `daedalus.evolution`.

This campaign only writes the latter two destinations. Broader migration needs
its own reviewed Work Packet and policy decision.

For every candidate, prefer in this order:

1. delete dead or duplicated code;
2. consolidate duplicate contracts or predicates;
3. move one responsibility to its canonical destination;
4. wire an existing isolated capability into one canonical caller;
5. add a thin compatibility import with an explicit removal condition;
6. add new implementation only when the existing tree cannot express the
   required invariant.

A tensor kernel is an internal typed computational view over a revision-bound
Forest/Project Twin. It is not a fifth semantic plane, another public product,
or a competing graph authority.

## Branches, PRs and worktrees

The campaign may inspect branch/worktree topology and produce a proposed
integration packet. It does not automatically merge, rebase, force-update,
delete, close, or promote refs.

Safe reintegration requires:

1. classify each ref as active candidate, required dependency, contained
   evidence, historical evidence, experiment, superseded, or unknown;
2. verify commit and unique-blob containment;
3. port unique value in a small Work Packet onto the canonical line;
4. run exact-head tests and review;
5. obtain the owner-controlled merge/promotion decision;
6. delete a branch only after the evidence and dependencies survive elsewhere.

This is the Masterplan-compatible meaning of “reintegrate all worktrees and
branches”: no useful work is silently lost, but an unattended process does not
merge unreviewed siblings into the primary checkout.

## Benchmarks and claim boundary

“Beats CrewAI” and “beats AlphaEvolve” remain research targets. The campaign may
build benchmark contracts and produce measurements, but a superiority claim
requires frozen tasks, equal budgets, repeated seeds, declared models/hardware,
uncertainty, failures, ablations, and held-out generalization.

For AlphaEvolve, distinguish:

- a directly comparable public artifact score;
- a transparent AlphaEvolve-like proxy;
- a non-comparable architectural discussion.

These evidence classes may not be combined into a broad win claim.

## Installation on the owner Windows machine

Opening or merging the PR does **not** install a task on a PC. From the intended
Daedalus checkout:

```powershell
$Campaign = 'docs/campaigns/FOURFOLD_TENSOR_GARDENER_20260929.json'
$Task = 'FourfoldTensorGardener20260929'

powershell -ExecutionPolicy Bypass -File tools/continuous_daedalus.ps1 `
  Install `
  -CampaignFile $Campaign `
  -ScheduledTaskName $Task
```

A prior sticky stop causes installation to refuse. A deliberate re-arm is
visible and must be requested explicitly:

```powershell
powershell -ExecutionPolicy Bypass -File tools/continuous_daedalus.ps1 `
  Install `
  -CampaignFile $Campaign `
  -ScheduledTaskName $Task `
  -ForceRearm
```

Operations use the same campaign and task identity:

```powershell
powershell -File tools/continuous_daedalus.ps1 Status -CampaignFile $Campaign -ScheduledTaskName $Task
powershell -File tools/continuous_daedalus.ps1 RunOnce -CampaignFile $Campaign -ScheduledTaskName $Task
powershell -File tools/continuous_daedalus.ps1 Start -CampaignFile $Campaign -ScheduledTaskName $Task
powershell -File tools/continuous_daedalus.ps1 Stop -CampaignFile $Campaign -ScheduledTaskName $Task
powershell -File tools/continuous_daedalus.ps1 Arm -CampaignFile $Campaign -ScheduledTaskName $Task -ForceRearm
powershell -File tools/continuous_daedalus.ps1 Uninstall -CampaignFile $Campaign -ScheduledTaskName $Task
```

The task runs only while the PC is on and the current user has an interactive
session. It stores no Windows password and does not run as SYSTEM or admin.

## Verification status

The branch contains focused static/contract tests, but opening this packet does
not execute them. Required local checks are:

```powershell
python -m py_compile tools/gardener_campaign.py tests/test_gardener_campaign.py
python -m pytest -q `
  tests/test_gardener_campaign.py `
  tests/test_continuous_daedalus_scheduler.py `
  tests/test_picker_work_queue.py
python tools/gardener_campaign.py status
```

On Windows, additionally reproduce install/status/run-once/start/overlap/stop,
re-arm, final-trigger behavior, and uninstall. GitHub Actions issue #67 remains
an external exact-head evidence blocker; zero-step jobs are neither green
evidence nor product-failure evidence.

Iron Plan: **ALIGNED**  
Iron Gate: **1 active; Gate-2 work remains bounded/preparatory**  
Automatic merge/promotion: **disabled**
