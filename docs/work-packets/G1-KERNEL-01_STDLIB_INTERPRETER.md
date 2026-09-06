# G1-KERNEL-01 — Shared stdlib-only interpreter resolution

Packet ID: G1-KERNEL-01

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: `61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0`

Integration context: uncommitted tree on branch
`codex/ikarus-computer-assistant-20260905`

Dependencies: `G1-ARIADNE-03_WINDOWS_EVALUATOR_INTERPRETER` (stage 1)

Stage: 2 of the owner-directed 2026-09-05 loop.

## Primary acceptance claim

One kernel-owned resolution decides which interpreter runs a stdlib-only
contained payload on Windows, and both production callers (the Ariadne frozen
evaluator and the Genesis command gates) use it instead of private copies.
Frozen attempt identity keeps the vendor-neutral literal `python`; only the
argv handed to `command_gate` is resolved; the executed interpreter is
recorded path-free. The kernel gate itself executes and records exactly the
argv it is handed.

## Scope

This packet owns the stdlib-only interpreter helper and its two explicit
callers, path-free interpreter provenance, focused architecture counters and
tests. It does not alter `command_gate`, containment, pytest gate selection,
receipt verification, budgets, evaluator identity or promotion.

## Design critique before build (Momus, 2026-09-05)

The first stage-2 plan put the substitution inside `command_gate` /
`_contained_gate_child`. Momus killed that item with two pieces of evidence:

- `daedalus/kernel/attempt_execution.py:956`: the kernel's own pytest gate is
  `(sys.executable, "-m", "pytest", ...)`; the venv's base interpreter has no
  pytest and a different site-packages, so a kernel-wide argv rewrite would
  switch every Windows gate to a dependency set nobody chose.
- `daedalus/spine/bootstrap.py:282`: receipts are verified against the exact
  gate argv (`if argv != expected_argv`), and `tests/test_spine_attempt.py`
  asserts `verdict.command == argv`. Substituting inside the gate would either
  fail that check or make `GateResult.command` name an interpreter that did
  not run (a provenance lie under Invariant 7).

Narrowed form, built here: a call-site helper. The gate is untouched.

Momus also found that Genesis already carries a copy of the stage-1 helper
(`daedalus/orchestration/genesis/service.py:1277 _genesis_interpreter()`,
added in this dirty tree by the Codex packaging chat at 12:11) and that it
writes the resolved host path into `TaskSpec.gate_argv` (`service.py:1319
gate_argv=actual`), so Genesis attempt identity varies per host and the user
profile path reaches frozen-gate bindings via `bootstrap.py:633-641`, while
`service.py:1346` records `argv=displayed` in the observation. Ariadne keeps
the literal. That Genesis half is coordinated with Codex (see below).

## Recorded experiment: NUL stdin in containment (Odysseus, 2026-09-05)

The council's open dissent was whether containment should hand the child a
valid NUL stdin instead of swapping the interpreter. Executed as the same
`CreateProcessAsUserW` spawn, real containment helpers, changing one thing at
a time. Scripts and raw results retained under
`docs/evidence/G1-KERNEL-01_NUL_STDIN_EXPERIMENT/`.

| Arm | merged log bytes | exit | inherited handles | note |
| --- | --- | --- | --- | --- |
| A stub, `hStdInput` NULL (production) | `warning: Making stdin inheritable failed\nx\r\n` | 0 | 1 | job saw 2 processes (stub + interpreter) |
| B stub, `hStdInput` = allowlisted NUL handle | `x\r\n` | 0 | **2** | NUL granted `0x00120089` (FILE_GENERIC_READ incl. READ_CONTROL) vs the log's `0x00100084` |
| B2 stub, NUL in `hStdInput` but not on the allowlist | `warning: ...\nx\r\n` | 0 | 1 | the field alone changes nothing; the child must receive the handle |
| C base interpreter, `hStdInput` NULL (production) | `x\r\n` | 0 | 1 | job saw 1 process |
| D base interpreter, child opens `NUL` itself | `nul-ok\r\n` | 0 | 1 | a Low child needs no inherited NUL handle |

Reading: the NUL-stdin claim is confirmed as a symptom and refuted as a free
fix. It only works when the allowlist grows, which renegotiates
`inherited_handle_count == 1` (`tests/test_gate_containment.py:594,616`), the
load-bearing comment in `spawn_contained`, and the equality-checked access
mask. The warning is a property of the launcher stub, not of containment:
Arm C removes it with the unchanged boundary. No production file was touched
by the experiment.

## Contracts and behavior

- New `daedalus/kernel/interpreter.py`: `stdlib_interpreter()` (win32 →
  `sys._base_executable` when it is a file, else `sys.executable`; other
  platforms unchanged), `resolve_python_argv(argv)` (substitutes only a
  leading literal `python` or `sys.executable` and never inspects the
  following arguments, so `(sys.executable, "-m", "pytest")` would be
  rewritten too: the kernel pytest gate stays on the venv interpreter only
  because `pytest_gate_argv` never calls the helper (Codex review, room turn
  70); `git` and foreign interpreter paths pass through), `interpreter_provenance(path)`
  (implementation, version, platform, binary SHA-256; never a path). The
  module docstring states why this is not applied inside `command_gate`.
- `daedalus/ariadne/campaign.py`: the stage-1 private helpers are deleted and
  imported from the kernel module under their existing names; behaviour of
  the frozen evaluator spawn (`-I -S`, one resolution per campaign,
  observation schema `/2`) is unchanged.
- New `tests/test_kernel_interpreter.py`: resolution branches (win32 real /
  missing / absent base, linux, darwin), argv substitution rules,
  path-free provenance, and a discriminating witness that skips with a
  reason where no launcher stub exists and otherwise proves the resolved
  interpreter is not the stub and that `sys.executable` is.
- `tests/test_ariadne_campaign_v0.py`: the duplicated unit tests moved to the
  kernel test file; the unfaked integration test stays.
- Genesis (`service.py`): landed by Codex as co-author at 13:02 after the
  room exchange (`.room/room.md` turns 69-70): `_run_command` resolves with
  `resolve_python_argv(displayed)` (`service.py:1299`), keeps
  `gate_argv=displayed` (`:1309`), records `interpreter_provenance()` in the
  command observation under schema `daedalus-genesis-command-observation/2`
  (`:272`); `_genesis_interpreter()` is gone. Codex did not run the tests;
  the Genesis cohort result is recorded below.
- `tests/contracts/test_import_scc_hierarchy.py`: the moving census was
  re-measured as that file instructs: modules 470 -> 473, edges 1886 -> 1904
  on the shared tree at 13:22. Of that, this packet adds one module
  (`kernel/interpreter.py`) and five edges; the rest comes from concurrent
  packets writing the same tree (d5's tool door, the Codex packaging chat).
  The cycle claims (component count, maximum size, membership digest) are
  unchanged and pass.
- `daedalus/kernel/campaigns.py`: new typed `CampaignIdentityConflict`
  (same id, changed frozen material); the Ariadne facade maps it to
  `AriadneConflictError` so the HTTP facade answers 409 instead of 400.
  Corrupt or malformed retained state stays a 400 campaign error. Tests:
  facade test tightened to the conflict class; HTTP mapping case
  `reuse-conflict` -> 409. (Odysseus finding on G1-ARIADNE-02.)
- `daedalus/interfaces/http/effects.py::mutation_route_wired` and
  `daedalus/interfaces/desktop/projection.py`: `ariadne_campaign_live` is
  derived from the one route table (G1-ARIADNE-02 matrix item 7).
- `daedalus/council/session.py`, `daedalus/council/vendors.py`: live
  councils install the budget net first; refusals are `budget_exhausted`.
  Recorded in G1-ARIADNE-03 with the disclosure of today's unpriced calls.
- Codex review correction applied: the helper's `argv[0]`-only rule is now
  stated in its docstring and pinned by
  `test_resolve_python_argv_does_not_inspect_the_payload`, which also asserts
  `pytest_gate_argv([])[0] == sys.executable`.

Forbidden and untouched: `daedalus/kernel/attempt_execution.py`,
`daedalus/spine/containment.py`, `pytest_gate_argv`, receipts and their argv
verification, promotion.

## Evidence, expected failures, and review

### Stage 2b, scoped out as its own packet

`_council` in `daedalus/interfaces/cli/entry.py:564` never calls
`begin_effect` and no `cli.council` row exists in
`daedalus/spine/effect_boundary.py`. (Today's refusals were the exhausted
daily ceiling, correctly enforced by the guard; see G1-ARIADNE-03.) Registering
the door is ordinary registry work, not an amendment, but
`tests/test_registry_new_doors.py` derives the effect set both ways (an
undeclared sink fails, a declared effect without a justification fails as a
painted label): the row is `process_spawn, process_control, network_egress,
secrets, spend`, and a `spend` door needs a real reservation to pass the
guard. That is a Work Packet with a budget contract, not a footnote here.

## Acceptance matrix

| Check | Result |
| --- | --- |
| `tests/test_kernel_interpreter.py` before the module existed | collection error (red) |
| `tests/test_kernel_interpreter.py` after | 8 passed |
| Ariadne unfaked integration test after the refactor | 1 passed (10.3 s) |
| affected suites (kernel interpreter, Ariadne campaign + HTTP, architecture boundaries, gate-judges-candidate, spine attempt) | 120 passed (129.9 s) |
| `tests/test_kernel_interpreter.py` after the Codex correction | 9 passed |
| `tests/contracts/test_import_scc_hierarchy.py` after the census re-measure | 3 passed (41.8 s) |
| Genesis targeted cohort after the shared resolver switch | 66 passed; 24 HTTP cases deliberately deselected |
| Genesis fresh Chromium exact case | 1/1 passed in 40.909 s; all five gates passed without timeout or cancellation |
| Genesis cohort after the resolver switch, run by this session (contracts, lease, materializer, service, archive, HTTP, CLI, producer census) | 233 passed (237.7 s) |
| council suites after the budget-net change (livewire, vendors, session, bus) + SCC census | 154 passed, 3 passed |
| Ariadne HTTP conflict mapping + facade replay test after the conflict typing | 5 passed |
| desktop projection flag (effect owner, strangler architecture, HTTP Ariadne) | 91 passed |
| effect-boundary and containment suites | 118 passed, 5 failed at 13:16, all five on `tools.build_scene_environments:main` (d5's unregistered tool entrypoint; d5 registered it and reports 44 passed) |
| final regression at 13:32 over every file touched today (kernel interpreter, Ariadne campaign + HTTP, council livewire/vendors/session/bus, desktop effect owner, SCC census, registry new doors, effect boundary, producer census) | 332 passed (183.8 s), 0 failed |

## Migration and rollback

Existing observation schema `/1` records remain readable. Rollback removes the
two explicit call-site imports and the shared helper without changing the
kernel gate; retained experiment and failed-run evidence stays in place.

Iron Plan: **ALIGNED** (experiment recorded as `EXPERIMENT`, no production
change from it)

Iron Gate: **1**

Automatic merge/promotion: **forbidden**
