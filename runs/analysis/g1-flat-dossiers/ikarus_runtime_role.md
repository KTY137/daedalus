# `daedalus/ikarus_runtime_role.py`

Scoping note: every search below is restricted to `daedalus`, `tests`,
`tools` (via `git grep -- daedalus tests tools`, or `Grep path=`).
`.claude/worktrees/agent-*/` holds full copies of `daedalus/` and `tests/`
and was deliberately excluded to avoid double-counting importer sites.

## Identity

Absolute path: `C:/Users/Administrator/daedalus/daedalus/ikarus_runtime_role.py`
Line count: 395 (`wc -l`, confirmed 2026-09-02).
One sentence: an immutable, caller-local, duplicate-rejecting
`RuntimeRoleRegistry` of `(role, runtime_id)` structural bindings for the
Ikarus supervisor — a dispatch port that owns no process and performs no I/O.

## Importers (MEASURED)

Total unique importer sites found by this scope: **5** = 2 daedalus/ + 3
tests/ + 0 tools/, matching the lead's precomputed count exactly (0 deferred).

daedalus/ (2, both module-level):

- `daedalus/ikarus_oneshot.py:24` — `from .ikarus_runtime_role import RuntimeRoleSnapshot`
- `daedalus/ikarus_supervisor.py:54` — `from .ikarus_runtime_role import (` (imports `INPROCESS_RUNTIME_ID`, `RuntimeRoleRegistry`, `RuntimeRoleSnapshot`)

tests/ (3, all real imports):

- `tests/test_ikarus_oneshot.py:16` — `from daedalus.ikarus_runtime_role import ...`
- `tests/test_ikarus_runtime_role.py:15` — `from daedalus.ikarus_runtime_role import (  # noqa: E402`
- `tests/test_ikarus_tool_scope.py:12` — `from daedalus.ikarus_runtime_role import ...`

One further hit is NOT an importer: `tests/test_ikarus_runtime_role.py:984`
references the file as a string path (`root / "daedalus" / "ikarus_runtime_role.py"`)
for a source-boundary check, not an import; excluded from the count as the
lead's methodology implies.

**Dynamic/string references searched and found:** searched for
`importlib`/`__import__` combined with the module name, literal dotted
strings, and `pyproject.toml` `[project.scripts]`/console_scripts (only
`daedalus` and `daedalus-chip` entrypoints exist, neither names this module).
No dynamic or plugin-table reference found; `runtime_registry.RUNTIMES` is a
separate, unrelated CLI/API registry (see `runtime_registry.md`) and does not
reference this module.

## Imports (MEASURED)

**Module-level (file:line), stdlib only — 0 daedalus imports:**

- `hashlib` — line 22
- `json` — line 23
- `re` — line 24
- `dataclasses.dataclass, field` — line 25
- `types.MappingProxyType` — line 26
- `typing.Any, Iterable, Mapping` — line 27

**Deferred / function-scope: none.** Every import in this file is at module
top; no function or method contains an `import` statement. Total: 6
module-level stdlib imports, 0 daedalus.* imports (module-level or
deferred), 0 third-party imports.

## What it does

`RuntimeRoleBinding` is a frozen, validated, versioned `(role, runtime_id)`
descriptor whose `execution_mode` is either `fixture` (executable, namespaced
under `fixture.`/`fixture://`) or `source-only` (declared but not yet
executable, and required to carry a `refusal_reason`); `RuntimeRoleRegistry`
snapshots a caller-supplied set of these into an immutable, duplicate-free,
lookup-by-`(role, runtime_id)` structure that reconstructs and re-validates
every record rather than trusting a stored object. The module explicitly
disclaims being "another runtime, effect, policy, trust, provider, or tool
registry" and states only `fixture` bindings are executable as of work packet
G1-IKARUS-02, with real runtimes staying `source-only` until a later packet
supplies canonical broker authority. Size: 395 lines.

## Proposed destination

**Proposed: `orchestration`.**

This is the strongest measured argument among the five dossier modules: its
only two production importers, `daedalus/ikarus_oneshot.py` (a "Stateless
one-shot request port for Ikarus", per its own docstring) and
`daedalus/ikarus_supervisor.py` ("The Ikarus supervisor: one mission, one
shared state ledger, role attempts", explicitly citing master-plan §7
artifact-first orchestration coordination), are both Ikarus orchestration-tier
modules by their own stated purpose. `ikarus_supervisor.py`'s other
`daedalus.*` imports are `.build`, `.limit_policy`, `.schemas`, and
`.spine.attempt` — orchestration composing kernel/spine primitives, not the
other way around.

The task brief flags a peer-worker claim that `ikarus_supervisor` imports
this module — confirmed directly at `daedalus/ikarus_supervisor.py:54`.

The name suggests `daedalus.runtimes` ("runtime role"), but **the name does
not decide it**: the lead's AST sweep found zero files under
`daedalus/runtimes/` importing this module at any scope, confirmed
independently here (`git grep` over `daedalus/runtimes daedalus/kernel
daedalus/spine daedalus/twin` for all five module names returns only one
unrelated comment hit in `daedalus/kernel/contracts/canonical.py:2427`, about
`runtime_registry`, not this module). The measured edges point at
orchestration-tier consumers, not the runtimes layer.

**Strongest counter-argument:** `RuntimeRoleBinding.harness_key` and the
`INPROCESS_RUNTIME_ID`/`fixture.`-namespace machinery exist specifically to
gate eventual admission of *real* runtimes (Claude/Codex/Ollama CLIs) through
"the canonical broker" — conceptually adjacent to `daedalus.runtimes.broker`.
This loses today because the measured import graph shows zero edges to or
from `daedalus/runtimes/`; the module's own docstring is explicit that "a
real runtime is represented as `source-only` until a later packet connects
its exact admitted manifest ... through the canonical broker" — i.e. it
governs orchestration-side *dispatch*, and the broker/runtimes-side admission
is deliberately a separate, not-yet-built concern.

## Boundary-rule verdict after the move

Four rules by id (`kernel-no-outer-layers`, `runtimes-no-gates`,
`spine-no-outer-layers`, `twin-no-outer-layers`), both directions:

- **(b) inbound:** VACUOUSLY CLEAN, attributed to the lead's AST sweep: no
  file under `daedalus/kernel`, `daedalus/spine`, `daedalus/twin`,
  `daedalus/runtimes` imports any of the five dossier modules at any AST
  scope, and the complete flat-module import set of those 142 layer-files is
  `{budget, sensitivity, structcore, limit_policy, primary_tree, config,
  storage, atomic, mapping, offload, providers, resources}` —
  `ikarus_runtime_role` is not in it. Independently reconfirmed: this
  module's only two production importers (`ikarus_oneshot.py`,
  `ikarus_supervisor.py`) are themselves orchestration-tier files, not
  kernel/spine/twin/runtimes.
- **(a) outbound / `daedalus.gates` check:** this module imports **nothing**
  from `daedalus` at all (0 daedalus.* imports, see Imports above). It
  cannot import `daedalus.gates` at any scope. Grep confirms directly:
  `git grep -n "daedalus.gates\|from \.gates\|from \.\.gates\|import gates"
  -- daedalus/ikarus_runtime_role.py` returns no matches. If hypothetically
  moved into `daedalus.runtimes`, rule `runtimes-no-gates` would still pass:
  **CLEAN**.
- Because the proposed destination is `orchestration`, which is not a
  `source_prefixes` entry for any of the four rules
  (`docs/architecture/import-boundaries.json`), none of the four rules binds
  this module as a source after the move.

**One-line verdict: N-A-not-a-rule-source (destination `orchestration`); the
hypothetical `daedalus.runtimes` landing would also be CLEAN (no
`daedalus.gates` import at any scope).**

## Dead-code signals

Not near-zero: 5 measured importer sites (2 production, 3 test), well above
the near-orphan threshold that makes this section load-bearing for
`ikarus_runtime_events`. Docstring, quoted from lines 1–19, states plainly
what the module is and is not:

> "Immutable runtime-role bindings for the Ikarus supervisor. This is a
> dispatch port, not another runtime, effect, policy, trust, provider, or
> tool registry. ... Only `fixture` bindings are executable in work packet
> G1-IKARUS-02. A real runtime is represented as `source-only` until a later
> packet connects its exact admitted manifest, effect lease, observation
> authority and executable target through the canonical broker."

This promises exactly the reader it has: `ikarus_supervisor` (the harness)
and `ikarus_oneshot` (the stateless request port), both confirmed live,
production, non-test consumers. Chasing one hop on those two importers: both
are themselves imported elsewhere in `daedalus/` (`ikarus_supervisor` is the
subject of work packet `G1-IKARUS-01-supervisor-slice.md`;
`ikarus_oneshot` of `G1-IKARUS-04_STATELESS_ONESHOT_PORT.md`), so the chain
is live rather than a dead branch.

**Two disconnected Ikarus clusters.** `daedalus/` holds nine `ikarus_*`
modules: `ikarus_act.py`, `ikarus_chat.py`, `ikarus_effect_bridge.py`,
`ikarus_oneshot.py`, `ikarus_os.py`, `ikarus_runtime_events.py`,
`ikarus_runtime_role.py`, `ikarus_supervisor.py`, `ikarus_tool_scope.py`.
Measured here: only `ikarus_oneshot.py` and `ikarus_supervisor.py` import
`ikarus_runtime_role` at daedalus/ scope. `ikarus_os.py` (the older
chat/voice runtime — see `llm_client.md`, which it imports) does **not**
import this module, and neither does `ikarus_chat.py`, `ikarus_act.py`,
`ikarus_effect_bridge.py`, or `ikarus_tool_scope.py` at production scope
(only `tests/test_ikarus_tool_scope.py` imports it, directly, not via
`daedalus/ikarus_tool_scope.py`). This module therefore **anchors the newer
G1-IKARUS-01/02/03/04 supervisor+oneshot cluster** (shared-ledger, typed
dispatch, source-only-until-admitted runtime posture), which is currently
disconnected at the import level from the older `ikarus_os`/`ikarus_chat`
voice/chat cluster that predates the supervisor work packets.

## Confidence

**High.** The importer count, the daedalus-vs-test split, the 0-deferred
figure, and the 0-daedalus-imports-out figure all match the lead's
precomputed numbers exactly and were independently re-derived by direct
grep. The two-cluster claim is grounded in a full enumeration of all nine
`ikarus_*` files and their direct import relationships to this module, not
inference from naming.
