# `daedalus/ikarus_runtime_events.py`

Scoping note: every search below is restricted to `daedalus`, `tests`, `tools`
(via `git grep -- daedalus tests tools`, or `Grep path=`). `.claude/worktrees/agent-*/`
holds full copies of `daedalus/` and `tests/` and was deliberately excluded to
avoid double-counting importer sites.

## Identity

Absolute path: `C:/Users/Administrator/daedalus/daedalus/ikarus_runtime_events.py`
Line count: 393 (`wc -l`, confirmed 2026-09-02).
One sentence: an in-memory, per-run, thread-safe `RuntimeEventProjector` that
binds a runtime `call_id` to a declared `plan_entry_id`, records tool
start/finish/cancel callbacks as an immutable, digest-stable projection, and
performs no I/O of any kind.

## Importers (MEASURED)

Total unique importer sites found by this scope: **1**, all in `tests/`,
matching the lead's precomputed count exactly (1 total = 0 daedalus/ + 1
tests/ + 0 tools/; 0 deferred).

- `tests/test_ikarus_runtime_events.py:8` — `from daedalus.ikarus_runtime_events import (` (real import, module scope; imports `RUNTIME_EVENT_PROJECTION_SCHEMA`, `RuntimeEventProjector`, `RuntimeToolPlanEntry`, `RuntimeEventProjectionError` per the block starting there).

One further hit is NOT an importer: `tests/test_ikarus_runtime_events.py:224`
reads the module's own source text (`Path("daedalus/ikarus_runtime_events.py").read_text(...)`)
for a source-level boundary assertion (no subprocess/network/DB/filesystem
authority in the file) — a string path reference, not an import, and it is
excluded from the count.

No `daedalus/` file and no `tools/` file imports this module anywhere,
module-level or deferred.

**Dynamic/string references searched and found:** searched for
`importlib`/`__import__` combined with the module name, literal dotted
strings `"daedalus.ikarus_runtime_events"` / `"ikarus_runtime_events"`, and
`pyproject.toml` for `[project.scripts]` / `console_scripts` entries. `grep -n
"console_scripts\|\[project.scripts\]" -A 20 pyproject.toml` shows exactly two
entries (`daedalus = "daedalus.cli:main"`, `daedalus-chip =
"daedalus.chip_design.cli:main"`) — neither names this module. No
`importlib.import_module`, `__import__`, or literal dotted-string reference to
this module exists anywhere in `daedalus/`, `tests/`, or `tools/`. There is no
registry/plugin-discovery table (checked `RUNTIMES` in `runtime_registry.py`
and the harness-key lookup in `ikarus_runtime_role.py`; neither names this
module). Conclusion: the only path to this code is the direct test import.

## Imports (MEASURED)

**Module-level (file:line), stdlib only — 0 daedalus imports:**

- `hashlib.py` — line 16
- `json` — line 17
- `re` — line 18
- `threading` — line 19
- `dataclasses.dataclass` — line 20
- `typing.Any, Sequence` — line 21

(`from __future__ import annotations` at line 14 is a compiler directive, not
counted as an import target.)

**Deferred / function-scope: none.** Every import in this file is at module
top; no function or method contains an `import` statement. Total: 6
module-level stdlib imports, 0 daedalus.* imports (module-level or deferred),
0 third-party imports.

## What it does

`RuntimeEventProjector` binds one runtime `call_id` to exactly one declared
`plan_entry_id` at `start()`, resolves `finish()` calls only through that
bound `call_id` (never falling back to tool name), and on `cancel()` freezes
every unfinished plan row as `cancelled` without dropping it; the whole state
is exposed only as an immutable, SHA-256-digest-stable `RuntimeEventProjection`
snapshot. It is explicitly declared not to be an agent loop, event store, tool
registry, provider, scheduler, or policy authority, and it opens no file,
socket, or subprocess. Size: 393 lines.

## Proposed destination

**Proposed: `orchestration`.**

The module is Ikarus-family orchestration substance by design and by its own
work-packet doc (`docs/work-packets/G1-IKARUS-03_RUNTIME_EVENT_PROJECTION.md`):
it is one packet in the same G1-IKARUS sequence that produced
`ikarus_runtime_role.py` (G1-IKARUS-02, packet-sequence sibling, proposed
destination `orchestration` in the companion dossier) and `ikarus_oneshot.py`
(G1-IKARUS-04). The packet doc's own "Deferred integration" section names the
future consumer as an adapter sitting "behind `daedalus.runtimes.broker.run_runtime_provider(...)`"
— i.e. even the packet's own plan treats this as orchestration-side
projection state that a *runtimes*-layer adapter will one day *read from*, not
code that itself belongs inside `daedalus.runtimes`.

This is a weaker argument than a measured import edge, and it is not the
module name deciding it: the module currently has **zero** production import
edges anywhere (daedalus/ or tools/), so there is no measured edge to anchor
a destination on at all. The destination argument here is packet-sequence and
conceptual adjacency to its sibling `ikarus_runtime_role`, stated honestly as
such, not as import evidence.

**Strongest counter-argument:** leave it where it is (flat, undestined) until
the deferred-integration packet lands, since a destination chosen today could
be wrong once a real consumer exists and reveals the actual layer boundary.
This loses only marginally: the module is provably effect-free, provably
independent of `daedalus.runtimes`, `daedalus.kernel`, `daedalus.spine`, and
`daedalus.twin` today (see Imports above — 0 daedalus imports of any kind),
and co-locating it with its packet-sibling `ikarus_runtime_role` in
`orchestration` costs nothing structurally: it does not import, and is not
imported by, anything that would make `orchestration` a wrong home. Moving it
now is reversible; leaving it flat only defers a decision that has no
evidence pointing anywhere else.

## Boundary-rule verdict after the move

Four rules by id (`kernel-no-outer-layers`, `runtimes-no-gates`,
`spine-no-outer-layers`, `twin-no-outer-layers`), both directions:

- **(b) inbound — any kernel/spine/twin/runtimes file importing this
  module:** VACUOUSLY CLEAN, attributed to the lead's AST sweep over all 1143
  tracked `.py` files: no file under `daedalus/kernel`, `daedalus/spine`,
  `daedalus/twin`, `daedalus/runtimes` imports any of the five dossier
  modules at any AST scope, and the complete set of flat-module imports those
  142 layer-files make is `{budget, sensitivity, structcore, limit_policy,
  primary_tree, config, storage, atomic, mapping, offload, providers,
  resources}` — `ikarus_runtime_events` is not in it. Independently
  reconfirmed here: this module's only importer is a test file, so it cannot
  appear in that layer-file import set by construction.
- **(a) outbound / `daedalus.gates` check:** this module imports **nothing**
  from `daedalus` at all (see Imports above — 0 daedalus.*, module-level or
  deferred). It therefore cannot import `daedalus.gates` at any scope. Grep
  confirms directly: `git grep -n "daedalus.gates\|from \.gates\|from
  \.\.gates\|import gates" -- daedalus/ikarus_runtime_events.py` returns no
  matches. If this module were hypothetically moved into `daedalus.runtimes`,
  rule `runtimes-no-gates` (denylist-only, forbids `daedalus.gates`) would
  still pass: **CLEAN**.
- Because the proposed destination is `orchestration`, which is not a
  `source_prefixes` entry for any of the four rules
  (`docs/architecture/import-boundaries.json`), none of the four rules binds
  this module as a *source* after the move; its own imports remain
  unconstrained by this contract.

**One-line verdict: N-A-not-a-rule-source (destination `orchestration`); the
hypothetical `daedalus.runtimes` landing would also be CLEAN (no
`daedalus.gates` import at any scope).**

## Dead-code signals

Zero-to-near-zero importers is a **finding**, not a verdict, and here it is
the main event.

Docstring, quoted in full from lines 1–13:

> "Loss-aware, provider-neutral runtime callback projection for Ikarus.
>
> This is a deliberately small adaptation of a Hermes/ACP motif: callbacks
> from parallel tool calls need explicit correlation, and cancellation must
> not make unfinished plan entries disappear. It is not an agent loop, event
> store, tool registry, provider, scheduler, or policy authority.
>
> Adapters bind a runtime `call_id` to an exact declared `plan_entry_id` at
> start. Terminal callbacks are resolved only through that call id; tool
> names are never a fallback identity. The projector stores only SHA-256
> observation digests, not arbitrary provider output, and freezes all
> unfinished entries as `cancelled` when the run is cancelled."

This explicitly **promises a reader that does not exist yet**: "Adapters
bind a runtime `call_id`..." describes a producer role (a runtime adapter
emitting `start`/`finish`/`cancel` calls) that is not implemented anywhere in
`daedalus/`. Chasing one hop: the module's own work packet,
`docs/work-packets/G1-IKARUS-03_RUNTIME_EVENT_PROJECTION.md`, is explicit and
current-dated (2026-08-30, status "IMPLEMENTED / DRAFT INTEGRATION"):

> "A later small packet may connect this projector to an actually admitted
> runtime adapter only after that adapter is behind
> `daedalus.runtimes.broker.run_runtime_provider(...)` with its exact
> `RuntimeBoundEffectAuthorization`, `EffectExecutionRequest`,
> provider-observation authority, isolated workspace/container boundary and
> content-addressed output evidence."

Grep confirms no production code today constructs a `RuntimeEventProjector`,
references `plan_entry_id`, `tool_started`, or `RuntimeEventProjection`
outside this file and its dedicated test (`git grep -n "projector\|
tool_started\|plan_entry_id\|RuntimeEventProjection" -- daedalus/*.py`
returns only one unrelated hit, `ikarus_supervisor.py:375`, a comment about a
*different* concept — "a disposable projector restarted" refers to the
ledger, not this module). The sibling packet G1-IKARUS-02 (`ikarus_runtime_role`)
*did* get wired into two live production consumers
(`ikarus_oneshot.py`, `ikarus_supervisor.py`) within the same packet sequence;
this one has not yet, by explicit design deferral, not by neglect.

**Verdict: unwired seam, not rot.** The module has a complete, adversarially
tested contract (12 tests per the packet doc; confirmed live at
`tests/test_ikarus_runtime_events.py`, 1 real importer measured here), a
named future consumer, and an explicit non-goal list ruling out scope creep
in the interim. It is dead in the sense that nothing calls it in production
today, but it is not abandoned or superseded — it is a half of a documented,
sequenced two-sided seam whose other half (the runtime adapter behind
`daedalus.runtimes.broker`) has not landed yet.

## Confidence

**High** for the importer count, the import list, and the "no daedalus.gates"
answer — all directly grepped and cross-checked against the lead's
precomputed numbers, which matched exactly. **Medium** for the destination
argument specifically, since it rests on packet-sequence adjacency rather
than a measured import edge (there is none to measure). Confidence would rise
to high once the deferred-integration packet lands and creates a real import
edge from its consumer to this module, settling the layer question with
evidence instead of inference.
