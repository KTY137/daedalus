# daedalus/agents_registry.py

## 1. Size and shape

129 lines (`wc -l`). 0 classes, 9 top-level functions: `_write_dir_for`
(`agents_registry.py:33`), `role_path` (40), `validate_role` (44),
`normalize_role` (69), `list_roles` (84), `get_role` (88), `create_role`
(92), `update_role` (104), `delete_role` (121).

Module-level state: `MODEL_TIERS = ("opus", "sonnet", "haiku")`
(`agents_registry.py:24`); `_NAME_RE = re.compile(...)` (line 25 — this
executes `re.compile` at import time, a CPU cost but not I/O); `_RESERVED_ROLE_NAMES
= {"categories"}` (line 29); `_LIST_FIELDS = ("owns", "triggers",
"must_read")` (line 30). No mutable singleton, no cache decorator.

Module-level side effects at import time: **none**. No file reads, no env
reads, no path creation, no registry mutation happen at module scope — every
filesystem write (`path.write_text`, `path.unlink`, `path.parent.mkdir`) is
inside `create_role`/`update_role`/`delete_role`, called explicitly by a
caller, never at import.

## 2. What it does

It is runtime CRUD for agent-role definitions — the same JSON shape that
`router.load_agents` reads — so Ikarus, the CLI, or the GUI can mint or edit
crew roles without any other code change, since routing always re-reads
through `load_agents`. Every write always lands under
`<repo_root>/.agentenv/agents/<name>.json`, a per-repo override
(`_write_dir_for`, `agents_registry.py:33-37`); it explicitly refuses to
write when no `repo_root` is given and never mutates the shipped
`templates/agents/` defaults. `validate_role`/`normalize_role` enforce a
fail-closed schema (lowercase-slug name, one of three model tiers, boolean
`external_ok`, string-list fields, non-empty `output_schema`) before any
write, and `update_role` merges a patch over the current role — which may
itself be a read-only shipped template — and republishes it as a per-repo
override rather than editing the template in place.

## 3. Who imports it (MEASURED)

Search covered `from daedalus.agents_registry import`, `from daedalus import
agents_registry`, `import daedalus.agents_registry`, `from .agents_registry
import`, `from . import agents_registry` / `from .. import agents_registry`,
`importlib.import_module("daedalus.agents_registry")`, and the bare string
`"daedalus.agents_registry"`, across daedalus/, tests/, tools/, apps/, docs/,
.claude/. All hits found were real Python imports; no dynamic-string-only
references, no doc/comment-only mentions.

**TOTAL real importer edges: 10** — 6 under `daedalus/`, 4 under `tests/`.

| Importer | Layer | Form |
| --- | --- | --- |
| `daedalus/categories.py:22` (`from .agents_registry import MODEL_TIERS`) | flat | MODULE-LEVEL |
| `daedalus/cli.py:365` (`from . import agents_registry as reg`) | interfaces/cli (flat today) | DEFERRED — inside `_agents()` |
| `daedalus/ikarus_chat.py:13` (`from . import agents_registry, control_plane, core, hierarchy`) | flat | MODULE-LEVEL |
| `daedalus/interfaces/http/effects.py:11-12` (`from ... import (agents_registry, ...)`) | interfaces/http | MODULE-LEVEL |
| `daedalus/kairos/scheduler.py:466` (`from .. import agents_registry as reg`) | kairos (existing package, orchestration-adjacent) | DEFERRED — inside `WaveExecutor.configure()` |
| `daedalus/web_api.py:22-24` (`from . import (accelerators, agents_registry, ...)`) | flat, functions as interfaces/http host | MODULE-LEVEL |
| `tests/test_bridge_restart.py:649` (`from daedalus import agents_registry, core`) | tests | DEFERRED — inside a test function |
| `tests/test_agents_registry.py:4` (`from daedalus import agents_registry as reg`) | tests | MODULE-LEVEL |
| `tests/test_packaged_resources.py:9` (`from daedalus import agents_registry, categories, config, gui_catalogue, router`) | tests | MODULE-LEVEL |
| `tests/test_web_api.py:400` (`from daedalus import agents_registry`) | tests | DEFERRED — inside a test method |

## 4. What it imports (MEASURED)

Exactly one `daedalus.*` import: `from .router import load_agents`
(`agents_registry.py:22`), MODULE-LEVEL. `router.py` is a flat module
(`daedalus/router.py`), not in the declared-FOUNDATION list and not one of
the 11 SCC-owned modules; it resolves agent-role JSON files (shipped
templates plus per-repo override) that routing consumes. Third-party: none.
Stdlib only otherwise: `json`, `re`, `pathlib.Path`, `typing.Any`.

## 5. Proposed destination

**orchestration** — confidence medium.

Measured callers put this module squarely in the "who works" question the
master plan assigns to the orchestration layer (`docs/IKARUS_ARIADNE_MASTER_PLAN.md`
§7: "The orchestration layer answers who works, with which runtime..."):
`daedalus/kairos/scheduler.py`'s `WaveExecutor.configure()` mints/edits roles
at dispatch time, `daedalus/ikarus_chat.py` (Ikarus's chat/orchestration
surface) imports it module-level, and the CLI/HTTP importers are thin
transport wrappers around the same CRUD. Its single internal dependency,
`daedalus.router` (section 4), is itself a routing-table loader consumed by
scheduling — reinforcing that this module's home is next to routing/dispatch
logic, not inside canonical kernel/spine/twin infrastructure.

The competing case for **interfaces** is weak: none of the module's own code
does HTTP/CLI transport — it is pure filesystem CRUD that interfaces call
into, not an interface itself. What would change my mind: if the hierarchy
packet defines "orchestration" narrowly as mission/attempt/dispatch state
machinery only (excluding role-definition storage), this module would read
better as a `foundation`-style config-store utility instead — its own
dependency footprint (one flat import, no internal state) would support
that just as well.

## 6. Boundary-rule check after the move

(a) If moved to **orchestration**: no rule in
`docs/architecture/import-boundaries.json` names `orchestration` as a
`source_prefixes` entry, so none of the four rules apply to it directly in
that location — nothing is refused by a *source*-side rule. (Note:
`daedalus.orchestration` is a *forbidden target* in `kernel-no-outer-layers`,
`spine-no-outer-layers`, and `twin-no-outer-layers` — see 6c.)

(b) No rule names `daedalus.agents_registry` by prefix anywhere. Moving it
under a package does not change any current rule's text.

(c) If it landed in **kernel**, **spine**, or **twin** instead (all three
are ALLOWLISTS per the packet's own rationale text), its one real import —
`daedalus.router` — is **REFUSED** in all three: `router` appears in none of
the kernel allowlist (`atomic, budget, config, limit_policy, offload,
primary_tree, sensitivity, spine, storage, twin`), the spine allowlist
(`atomic, budget, config, kernel, limit_policy, mapping, sensitivity,
structcore`), or the twin allowlist (`kernel, spine, structcore`). This is
concrete evidence against placing `agents_registry` in any of those three
layers: its only dependency is a flat, unclassified module none of them
permit.

## 7. Dead-code signals

Not applicable — importer count is 10, not 0, with 6 production
(non-test) importer edges spanning CLI, HTTP effects, chat, and the
scheduler. Also reachable as a `daedalus` console-script subcommand:
`pyproject.toml:78` (`daedalus = "daedalus.cli:main"`) and
`daedalus/cli.py:359-365` dispatch `daedalus agents` to this module.
**Label: LIVE.**
