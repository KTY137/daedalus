# Build vocabulary reconciliation — `daedalus/build.py` vs. the canonical chain

Date: 2026-08-22 · Gate 0 · Invariant 1 (one kernel) and Invariant 7 (provenance)
Classification: ALIGNED (wiring an existing module onto the existing contract;
no new subsystem, no new contract class, no rename).

## The gap

Master plan §7 fixes one chain:

    MissionContract -> WorkItems -> Attempts -> Artifacts -> EvidencePacket

`daedalus/build.py` carries a second decomposition vocabulary —
`BuildSession` / `Wave` / `BuildTask` — and `daedalus/loop.py` drives real
builds through it. Until the two are bound, a wave receipt names work that no
mission claims, and the loop's `EffectBounds.mission_id` (`run_id`) is a third
spelling of "mission" beside `mission_contract_for_candidate`'s
`mission-<task_id>`.

## The mapping

| build.py noun | canonical chain | binding |
| --- | --- | --- |
| `BuildSession` | ONE `MissionContract` run | `BuildSession.mission_id` |
| `Wave` | an ordered batch of WorkItems | `Wave.index` (ordering only) |
| `BuildTask` | ONE WorkItem | `BuildTask.work_item_id` |
| a dispatched task | Attempt | existing `AttemptContract` (`mission_id` + `task_id`) |
| `WaveResult` / `BuildRunReport` | wave receipt | `result["work_item"]` stamp |

There is **no new `WorkItem` contract**. `MissionContract` already owns work
item identity as `work_item_ids: tuple[str, ...]` (schemas.py:526), so the
WorkItem *is* an id under a mission — exactly the shape the kernel already
validates. Adding a `WorkItem` dataclass would have been a second contract for
the thing the mission already names.

`MissionContract.work_item_ids` is **sorted and duplicate-rejecting**
(`_sorted_strings(..., identifiers=True)`). Order therefore cannot live in the
mission; wave order lives in `Wave.index` plus the task's position, which is
what the ordinal in the derived id records. Zero-padding makes the sorted
tuple read back in plan order for the first 1000 items — a readability
nicety, not a guarantee.

## Identity derivation

`daedalus.schemas.derive_work_item_id(mission_id, ordinal=..., identity=...)`
returns `wi-<ordinal:03d>-<12 hex of canonical_sha>`:

* **deterministic** — same mission, same plan, same ids;
* **unique** — the ordinal is the session-flat task index, so two tasks with
  identical objectives still get distinct ids (and a duplicate would be
  refused by `MissionContract` anyway, loudly);
* **content-bound** — the digest covers mission id, ordinal, objective, agent
  and declared paths, so a re-plan that changes the text changes the id and a
  receipt naming `wi-002-<digest>` proves *which* text was worked (Invariant 7).

A different wave chunking (different `max_workers`) shifts ordinals and
therefore ids. That is deliberate: a different plan is a different set of work
items, not the same items renumbered.

`BuildSession.mission_id`, when not supplied, is derived as
`mission-<slug>[-<created>]` — the `mission-` prefix that
`mission_contract_for_candidate` already uses. Two builds of the same feature
within the same second would collide; the caller supplies an explicit
`mission_id` when that matters (the loop does, via its `run_id`).

## What stays, what is deleted, what is deferred

**Stays as an internal module** (plan §3 permits it: "existing components may
survive as internal modules"). `build.py` is planning state around the
harness — decomposition, routing, wave sizing, frontier/local assignment. None
of that is expressible as a MissionContract field and none of it is a second
control plane: it never runs an effect, never stores an event, never promotes.
Its nouns become *views* of the canonical ones rather than rivals to them.

**Deleted:** nothing. There is no duplicate contract to remove — the second
vocabulary was unbound, not competing. Deleting `BuildSession` would delete
the wave/routing information the kernel contracts do not carry.

**Deferred (hunks reported, not applied — other lanes own these files):**

1. `daedalus/build_exec.py` — `WaveResult`/`BuildRunReport` gain `mission_id`;
   `_task_dicts` carries `work_item_id`; the dry-run and refusal branches stamp
   `result["work_item"]` (the landed/bounced branch already gets it through
   `BuildTask.mark`); `_acquire_wave_lease` prefers `session.mission_id` over
   `bounds.mission_id`.
2. `daedalus/loop.py` — `_session_for` passes `mission_id=self.run_id` so the
   lease's mission and the session's mission are one string, not two.
3. `tests/test_kernel_contracts_have_producers.py` — that census declares
   exactly which producers have no live caller.
   `mission_contract_for_build_session` is one until hunk 1 lands, so it needs
   an `UNCALLED_PRODUCERS` entry. (No existing test goes red without it; the
   list is iterated by declared name and MissionContract already had a
   producer. This is an honesty entry, not a repair.)
4. `daedalus/spine/picker.py` — a picked candidate's `MissionContract` and the
   loop's session mission are still minted independently; converging them is a
   Gate-1 item, not this one.

The exact diffs are in the lane's scratchpad:
`heracles-vocab-deferred-hunks.md`.

## Kill criterion

**If the mapping needs a field `MissionContract` cannot express without a
second contract, stop and report.** Verdict: **not fired.** Every element of
the mapping landed on existing fields — `mission_id`, `work_item_ids`,
`AttemptContract.mission_id`/`task_id`. The build-only attributes (agent,
category, lane, tier, builder, frontier, wave index) were *not* pushed into
the mission: they are routing hints, not mission semantics, and forcing them
into the contract would have been the second contract this criterion forbids.
They stay on `BuildTask`, reachable from the receipt through the work item id.

The criterion would fire if a future requirement demanded that the mission
itself carry wave ordering or per-item lane policy. At that point the honest
move is an amendment to `MissionContract`, not a `BuildWorkItem` class.

## Evidence

`tests/test_build_vocabulary.py` — determinism and uniqueness of derived ids,
mission-id agreement between the session and an `AttemptContract` produced
during the build, the wave-receipt stamp, and a structural guard that
`build.py` defines no second mission/attempt/evidence noun.
