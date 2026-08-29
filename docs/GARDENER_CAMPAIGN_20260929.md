# Fourfold/Tensor Gardener Campaign — cutoff 2026-09-29

This campaign is the bounded operator setup for the repository-owner direction
recorded in issue #239. It reuses the existing canonical Daedalus loop and the
Masterplan's Work-Packet/evidence boundaries. It does not create an immortal
chat, a second autonomous worker, a second promotion path, or a new source of
truth.

## Exact time boundary

Every activation determines the current date in `Europe/Berlin` before it can
launch a candidate.

- Through **2026-09-28**, one bounded activation may run.
- At **2026-09-29 00:00 Europe/Berlin**, a separate final trigger runs.
- On or after **2026-09-29**, the runner never invokes `daedalus.loop`; it stops
  the canonical kill switch, disables its scheduled task, and writes
  `runs/gardener/fourfold-tensor-gardener-20260929/final.json`.

The final report inventories the exact Masterplan identity, checkout revision,
working-tree state, local and remote branch refs, and linked worktrees. It does
not invent a benchmark win or Gate transition.

## What one activation runs

```powershell
python -m daedalus.loop `
  --repo-root <this checkout> `
  --max-iterations 3 `
  --max-wall-clock-s 1500 `
  --max-spend-usd 1.00 `
  --max-attempts-per-candidate 1 `
  --queue-limit 25 `
  --json `
  --arm
```

The Task Scheduler interval is six hours and its overlap policy is `IgnoreNew`.
It runs as the current interactive user at `Limited` run level. A sticky human
kill-switch stop remains authoritative; scheduled runs never use `--force`.

Every activation retains bounded stdout/stderr and a machine-readable receipt
under `runs/gardener/fourfold-tensor-gardener-20260929/activations/`.

## Curated work only

`.agentenv/work-queue.json` is the only enabled picker source for this campaign.
Map, inventory, evaluation and hotspot inference are disabled so a stale or
unrelated measurement cannot redirect the scheduled writer.

The queue is bound to one exact candidate-base revision. Each ready task has:

- one stable task ID;
- explicit Masterplan/issue/Work-Packet authority references;
- an exact target-path set;
- a bounded gate command and timeout;
- a stated priority inside the work-queue band.

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
delete, or promote refs.

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
uncertainty, failures, ablations and held-out generalization.

For AlphaEvolve, distinguish:

- a directly comparable public artifact score;
- a transparent AlphaEvolve-like proxy;
- a non-comparable architectural discussion.

These evidence classes may not be combined into a broad win claim.

## Installation on the owner Windows machine

Opening or merging the PR does **not** install a task on a PC. From the intended
Daedalus checkout, run:

```powershell
python tools/gardener_campaign.py install
```

A prior sticky stop causes installation to refuse. A deliberate re-arm is
visible:

```powershell
python tools/gardener_campaign.py install --force-rearm
```

Operations:

```powershell
python tools/gardener_campaign.py status
python tools/gardener_campaign.py run-once
python tools/gardener_campaign.py start
python tools/gardener_campaign.py stop
python tools/gardener_campaign.py arm --force-rearm
python tools/gardener_campaign.py uninstall
```

The task runs only while the PC is on and the current user has an interactive
session. It stores no Windows password and does not run as SYSTEM or admin.

## Verification status

The branch contains focused static/contract tests, but opening this packet does
not execute them. Required local checks are:

```powershell
python -m py_compile tools/gardener_campaign.py tests/test_gardener_campaign.py
python -m pytest -q tests/test_gardener_campaign.py tests/test_picker_work_queue.py
python tools/gardener_campaign.py status
python tools/gardener_campaign.py run-once
```

On Windows, additionally reproduce install/status/start/overlap/stop/re-arm and
uninstall. GitHub Actions issue #67 remains an external exact-head evidence
blocker; zero-step jobs are neither green evidence nor product-failure evidence.

Iron Plan: **ALIGNED**  
Iron Gate: **1 active; Gate-2 work remains bounded/preparatory**  
Automatic merge/promotion: **disabled**
