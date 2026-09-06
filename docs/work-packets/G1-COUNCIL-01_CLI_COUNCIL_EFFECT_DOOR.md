# G1-COUNCIL-01 — `cli.council` as a registered effectful door

Packet ID: G1-COUNCIL-01

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: `61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0`

Working-tree context: branch `codex/ikarus-computer-assistant-20260905`

Dependencies: `G1-KERNEL-01_STDLIB_INTERPRETER` (stage 2, which scoped this
out as its own packet), `G1-ARIADNE-03_WINDOWS_EVALUATOR_INTERPRETER`

Stage: 2b of the owner-directed 2026-09-05 loop.

## Primary acceptance claim

`daedalus council` is a registered effectful entrypoint: it starts at the
central boundary before argument parsing, declares exactly the effects the
source-derived closure finds, and is priced by the process guard like every
other door. An unregistered effectful egress entrypoint (AGENTS.md review
rule) no longer exists for the council.

## Reproduced negative baseline (measured 2026-09-05)

- `_council` in `daedalus/interfaces/cli/entry.py:564` never called
  `begin_effect`; no `cli.council` row existed while `runs.council.room` and
  `runs.council.summarize` did (Argus recon; Momus critique of G1-KERNEL-01).
- The probe `test_council_refuses_fail_closed_without_the_contract` failed
  before the change with `DID NOT RAISE EffectStartRefused`, and the registry
  derivation reported `cli.council: no such row` and `does not call
  begin_effect`.
- Not the cause of the day's `transport_error` seats: those were the daily
  budget ceiling, correctly enforced (see G1-ARIADNE-03).

## Scope

In scope: one `EntrypointSpec` row, one `begin_effect` call as the first call
in `_council`, the registry derivation entry, one checked bridge, two CLI
probes, the registry digest pins. Out of scope: any change to council
dispatch, budgets, vendors, the room engine (owner tool), or a per-door
spend reservation (CLI doors use the process-guard net; the recon found no
per-door budget contract in this repository).

## Contracts and behavior

- `daedalus/spine/effect_boundary.py`: row `cli.council`, surface CLI,
  target `daedalus.interfaces.cli.entry:_council`, effects
  `filesystem_write, network_egress, process_spawn, process_control, spend`,
  guard contract `budget.process_guard`, wiring CENTRAL, anchor
  `begin_effect`.
- `daedalus/interfaces/cli/entry.py::_council`: `begin_effect("cli.council",
  REGISTRY_BY_ID["cli.council"].effects, (process_guard_boundary_decision(),))`
  is the first call, before `argparse`. `--dry-run` therefore also starts at
  the boundary: the start must be unconditional (no `--help`, parse error or
  later branch can reach an effect around it). A dry run still calls no
  model and writes nothing.
- `tests/test_registry_new_doors.py`: `cli.council` is a `STATIC_ONLY_ROWS`
  entry (function-level target the conservative scanner does not rediscover).
  `process_control` was demanded by the derivation (`ManagedProcess.__init__`
  reaches `kill`). `spend` is bridged: `session._dispatch_round` hands each
  seat to `threading.Thread(target=_call)` and the name-based closure does not
  follow a callable passed as an argument; `_call -> adapter.ask ->
  _CliAdapter._dispatch`, which `BILLABLE_SITES` lists. Part 3 of
  `test_the_bridges_are_checked_not_believed` asserts each of those facts and
  demands the bridge be deleted the day the closure follows the hop itself.
- `tests/test_cli_effect_boundary.py`: `test_council_refuses_fail_closed_without_the_contract`
  (no plan printed, nothing written) and `test_council_dry_run_runs_on_the_valid_chain`.
- Registry digest moved `5b1feaf1…` -> `7a8fc9442be4d1fff8f576fa951036788ef146c779c5c1145bce21f471f3c605`
  in 27 pin files with daedalus-d5's three commands; the dated comment in
  `tests/contracts/test_work_packet_index.py` names both new rows; the two
  historical digests under `docs/` are left as measurements.

Forbidden and untouched: council dispatch and vendors beyond G1-KERNEL-01,
`daedalus/budget.py`, `budget_process.py`, the room engine, promotion.

## Acceptance matrix

| Check | Result (2026-09-05) |
| --- | --- |
| probes and derivation before the row | red: `DID NOT RAISE`, `no such row`, `does not call begin_effect` |
| after row + `begin_effect`, first derivation | red: `spend` painted, `process_control` undeclared |
| after `process_control` + checked bridge: `test_registry_new_doors.py` + `test_cli_effect_boundary.py` | 66 passed |
| 27 registry pin files + `test_import_scc_hierarchy.py` (edge census re-measured 1904 -> 1905) | 234 passed, 5 subtests |
| `test_import_scc_hierarchy.py` + `test_work_packet_index.py` after the comment | 25 passed |
| live `daedalus council --dry-run --vendors anthropic,openai` through the installed CLI (`.venv/Scripts/daedalus.exe`) at 13:46 | exit 0, plan printed, both seats listed available, no model called |
| regression at 13:47 over registry new doors, effect boundary, CLI boundary, council livewire/vendors/session/bus, SCC census, work-packet index, producer census, kernel interpreter, HTTP Ariadne | 324 passed (179.5 s), 0 failed |

## Migration and rollback

Rollback deletes the row, the `begin_effect` block, the derivation entry, the
bridge and its part-3 check, and moves the pins back to `5b1feaf1…`. Retained
council transcripts under `runs/council/` are unaffected.

## Evidence, expected failures, and review

Expected failure kept: with the daily ceiling exhausted the registered door
now refuses vendor spawns through the guard as `budget_exhausted`, which is
the intended behaviour, not a regression. Codex review is requested as a
free room turn; no vendor call is made until the owner raises the budget.

Iron Plan: **ALIGNED**

Iron Gate: **1**

Automatic merge/promotion: **forbidden**
