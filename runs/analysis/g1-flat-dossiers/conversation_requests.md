# daedalus/conversation_requests.py

## 1. Size and shape

451 lines (`daedalus/conversation_requests.py:1-451`, blank last line).

Classes: 4
- `ConversationRequestError(RuntimeError)` (:30), `UnknownConversationRequest` (:34),
  `ConflictingConversationRequest` (:38) -- exception hierarchy.
- `_Runtime` (:43) -- a `@dataclass` holding one in-flight request's process-local
  state (cancel `Event`, `Condition`, event buffer, worker `Thread`, live stream
  handle).
- `ConversationRequestManager` (:81) -- the module's one real class, 13 methods
  (`__init__`, `_install_uniqueness_guards`, `_intent`, `_runtime_for`,
  `_existing_by_key`, `create`, `_append_event`, `_resolve_cancellations`, `_run`,
  `status`, `events`, `cancel`, `_cancel_projection`, `_cancellation_status`).

Free functions: 4 -- `_client_key` (:55), `_check_client_id` (:59),
`_lane_for_context` (:67), `default_manager` (:433), `new_client_request_id` (:443)
(five, correcting the count).

Module-level state / singletons:
- `_MANAGERS: dict[str, ConversationRequestManager] = {}` (:429) and
  `_MANAGERS_LOCK = threading.Lock()` (:430) -- a process-global registry of one
  manager per resolved DB path, populated lazily by `default_manager()` (:433-440).
- `ConversationRequestManager` itself owns further per-instance mutable state:
  `self._runtime: dict[int, _Runtime] = {}` (:92) guarded by `self._lock` (:91),
  i.e. an in-process registry of live generation runs keyed by intent id. This is
  explicitly documented as a "process-local runtime" projection (module docstring
  :8-10) that does not survive a restart.

Module-level side effects at import: none observed. No file reads, no env reads,
no registry mutation, no network, no path creation execute at import time --
`_MANAGERS`/`_MANAGERS_LOCK` are empty containers, and `_install_uniqueness_guards`
(:95-111, which issues real `CREATE UNIQUE INDEX` DDL against the spine) only runs
inside `ConversationRequestManager.__init__` (:93), i.e. when a manager is
constructed, not at import.

## 2. What it does

`ConversationRequestManager` records one durable `Intent` on the canonical spine
before starting provider work, so a reconnecting client observes the same
in-flight or terminal request instead of triggering it twice (`create`, :129-178,
keyed by `effect_key = "<conversation_id>:<client_request_id>"`, with a partial
unique index installed at `__init__` time to enforce that idempotency at the
database level, :95-111). A background worker thread (`_run`, :205-290) drives
`ikarus_os.ask_stream` (via `self.stream_factory`, defaulted at :90), optionally
resolves a bounded context capsule through `editor_context.materialize_capsule`
(:216-221) picked by `_lane_for_context`'s fail-closed provider-to-lane mapping
(:67-78), appends every streamed event to an in-memory buffer consumers can poll
or long-poll (`events`, :321-341), and marks the spine intent completed or failed
exactly once while racing user-initiated cancellation, which is itself modeled as
its own idempotent, effect-keyed spine intent (`cancel`, :343-408).

## 3. Who imports it (MEASURED)

Command used: `Grep pattern="conversation_requests" path=daedalus/` plus targeted
re-checks of `apps/`, `.claude/`, `scripts/` (0 hits in all three) and manual
reads of every hit's import block to classify module-level vs. deferred.

TOTAL: 5 importers (4 production, 1 test). Zero hits in `apps/`, `scripts/`,
`.claude/`, `tools/`. No dynamic (`importlib.import_module`, bare-string) reference
found anywhere in the tree.

Per-layer breakdown:
- `daedalus/interfaces/http/` (existing package, declared interfaces layer): 3
  importers -- `sse.py`, `read.py`, `effects.py`.
- flat (unclassified, legacy web facade): 1 importer -- `daedalus/web_api.py`.
- tests: 1 importer.

Full list, all MODULE-LEVEL (plain top-of-file `from ... import (...)` blocks;
none is inside a function, `try`, or `TYPE_CHECKING`):

- `daedalus/web_api.py:27` -- `from . import (..., conversation_requests, ...)`
  inside the module's top import block (:22-33). MODULE-LEVEL.
- `daedalus/interfaces/http/sse.py:8` -- `from ... import conversation_requests,
  core, ikarus_os`. MODULE-LEVEL.
- `daedalus/interfaces/http/read.py:12` -- `from ... import (..., 
  conversation_requests, ...)` (:9-17). MODULE-LEVEL.
- `daedalus/interfaces/http/effects.py:15` -- `from ... import (...,
  conversation_requests, ...)` (:11-23). MODULE-LEVEL.
- `tests/test_conversation_requests.py:9` -- `from daedalus import
  conversation_requests as requests`. MODULE-LEVEL.

Call sites confirming actual use (not just imported-and-unused), all in the same
three `interfaces/http/` files: `sse.py:358,361`, `read.py:523-524`,
`effects.py:165,175,178,200,203,209,212` -- `default_manager()`, `.status()`,
`.create()`, `.cancel()` and the three exception classes are all consumed.

## 4. What it imports (MEASURED)

Command used: `Grep pattern="^from \.|^from daedalus|^import daedalus"
path=daedalus/conversation_requests.py` plus a full read of the file for deferred
imports (none found -- every import in this file is at module top, lines 14-21).

- `from . import conversation, editor_context, ikarus_os` -- `daedalus/
  conversation_requests.py:20`. MODULE-LEVEL. All three targets are flat,
  unclassified modules today:
  - `conversation` -- flat. Read directly (`daedalus/conversation.py:1-40`): its
    own docstring calls it "the chat seam's READ/WRITE FACADE over the canonical
    spine," built on `daedalus.spine.ledger` and `daedalus.spine.durability`
    (`conversation.py:124-125`). Best-guess layer: orchestration (chat/product
    surface over the spine), not spine itself -- it deliberately does not touch
    `daedalus.kernel`.
  - `editor_context` -- flat. Read directly (`daedalus/editor_context.py:1-28`):
    imports `daedalus.kernel.artifacts`, `daedalus.projects`, `daedalus.sensitivity`
    (foundation), `daedalus.spine.envelope`. Best-guess layer: orchestration
    (bounded context/capsule builder feeding generation, explicitly "owns no
    workflow authority").
  - `ikarus_os` -- flat. Its own docstring: `"ikarus_os — talk to your Agent OS."`
    (`daedalus/ikarus_os.py:1`). This is the literal Ikarus assistant seam the
    master plan describes in section 7. Best-guess layer: orchestration.
- `from .spine.ledger import STATE_COMPLETED, STATE_FAILED, STATE_INTENDED,
  Intent` -- `daedalus/conversation_requests.py:21`. MODULE-LEVEL. Target layer:
  spine (existing package).

Third-party imports: none. Everything else (`sqlite3`, `threading`, `uuid`,
`dataclasses`, `typing`) is stdlib.

`self.spine` (:89) is `self.store.spine`, i.e. reached transitively through
`conversation.default_store()` (:88) rather than imported directly -- the direct
import above is the only static spine edge.

## 5. Proposed destination

**orchestration**. Confidence: high.

Argument from measured edges: every module-level dependency this file has beyond
the spine (`conversation`, `editor_context`, `ikarus_os`) is a flat module whose
own content identifies it as orchestration-layer (the Ikarus assistant seam, its
chat facade, and its bounded context builder). Every importer is an
`interfaces/http` route file or the legacy `web_api.py` facade -- i.e. this module
is consumed BY the interfaces layer, not part of it; it sits between the HTTP
routes and the Ikarus engine, coordinating idempotent request lifecycle
(create/status/events/cancel) around `ikarus_os.ask_stream`. That is exactly the
mediating role the master plan assigns to "Ikarus... the persistent assistant and
orchestration layer" (plan section 7): it turns one HTTP-triggered intent into a
tracked `Attempt`-like run against the assistant engine, backed by the canonical
spine for idempotency. It is not spine itself (it only touches `spine.ledger` for
one typed record shape, doesn't define spine primitives) and not an interface (no
HTTP/CLI/desktop-specific code; `interfaces/http/*` wraps IT).

What would change my mind: if `conversation.py`, `editor_context.py`, and
`ikarus_os.py` are independently classified as something other than
orchestration (e.g. if `conversation.py` lands in `spine` as a facade extension),
this module should move with them, since its whole shape is "coordinate these
three." See section 6(d) for the specific hazard that would create.

## 6. Boundary-rule check after the move

(a) Would `daedalus.orchestration.conversation_requests`'s own imports be
refused by an `orchestration`-scoped rule? None of the four current rules in
`docs/architecture/import-boundaries.json` names `daedalus.orchestration` as a
*source* -- only as a *forbidden target* from `kernel`, `spine`, and `twin`. So
there is currently no allowlist/forbidden-list constraining what
`daedalus.orchestration.*` itself may import; moving this file there is not
refused by any existing rule as written. If a future `orchestration-*` source
rule is added, note for that packet: this file imports `daedalus.spine.ledger`
(module-level) and, transitively through `conversation`/`editor_context`,
`daedalus.spine.durability`, `daedalus.spine.envelope`, `daedalus.kernel.artifacts`
and `daedalus.projects` -- none of which the current kernel/spine/twin rules
forbid orchestration from reaching, but they would need to be on any new
orchestration allowlist.

(b) Does a current rule name this module by prefix? No. `conversation_requests`
does not appear as a `forbidden_target_prefixes` or `allowed_target_prefixes`
entry in any of the four rules. Nothing is unblocked or newly blocked by the bare
fact of moving it into a package -- unless the package name chosen is one of the
prefixes a rule already forbids. `daedalus.orchestration` specifically IS already
named as forbidden from `kernel`, `spine`, and `twin` (see (d)); landing this
file under that exact package name activates that existing prohibition against
it, which is the intended effect of classifying it as orchestration.

(c) N/A for this module's own placement -- orchestration is not one of
kernel/spine/twin, so no allowlist constrains ITS imports under the current
schema (see (a)). This does not exempt the modules it depends on: `conversation`,
`editor_context`, and `ikarus_os` remain flat, and if any of THEM were instead
placed in kernel/spine/twin, their own allowlist would then need to name
`daedalus.orchestration.conversation_requests` explicitly if they ever imported it
back -- they currently do not (see section on `conversation.py` below).

(d) Destination is orchestration, and kernel/spine/twin all forbid
`daedalus.orchestration` as a target. MEASURED: does any kernel/spine/twin module
currently import `daedalus.conversation_requests` (flat) today? `Grep pattern="
conversation_requests" path=daedalus/kernel` and `path=daedalus/spine` and
`path=daedalus/twin` each returned zero hits (verified as part of the full-tree
sweep in section 3 -- none of the five importers found is under `kernel/`,
`spine/`, or `twin/`). So moving this file under `daedalus.orchestration` today
does not turn any existing kernel/spine/twin importer into a violation, because
none exists. The risk is prospective, not present: if a future kernel/spine/twin
module ever imports this file (e.g. to read request status), that edge would
become an immediate rule violation the day this file lands in `orchestration`,
so that edge must route through `spine.ledger` directly rather than through this
module if it is ever needed from inside those layers.

Coupling with `conversation.py` (explicitly requested): **one-directional**,
`conversation_requests.py` -> `conversation.py`. `daedalus/
conversation_requests.py:20` imports `conversation` at MODULE level
(`from . import conversation, editor_context, ikarus_os`) and calls
`conversation.default_store()` (:88) and `conversation.ConversationStore` as a
type hint (:84). The reverse edge does not exist: `Grep pattern="
conversation_requests" path=daedalus/conversation.py` returned zero matches (no
module-level, no deferred, no string reference) -- confirmed by reading
`conversation.py`'s own import list (`daedalus/conversation.py:116,124-125`),
which names only `daedalus.kernel.contracts.observations`,
`daedalus.spine.durability`, `daedalus.spine.ledger`. `conversation.py` is a
lower-level facade over the spine; `conversation_requests.py` is a higher-level
coordinator built on top of it plus `ikarus_os` and `editor_context`. They are
NOT one unit requiring a forced joint move by import coupling alone -- but they
likely belong in the same target layer (orchestration) regardless, since
`conversation.py`'s own docstring positions it as the durable half of the exact
same "chat seam" `ikarus_os.py` (the assistant engine) defines the stateless half
of (`daedalus/conversation.py:3-10`).

## 7. Dead-code signals

Not applicable as a finding of absence: importers == 5, not 0, and three of the
five (`interfaces/http/sse.py`, `read.py`, `effects.py`) are live production HTTP
route handlers with real call sites (section 3), not merely imported. `web_api.py`
also has a real call path through those same `interfaces/http` modules it
composes. LIVE.

Searches run to confirm, per the required checklist even though importers > 0:
- Docstring/comments for a promised reader: module docstring (:1-11) itself names
  the reader relationship explicitly -- "Final chat turns continue to be persisted
  by `daedalus.ikarus_os` through `daedalus.conversation`" -- consistent with the
  measured `ikarus_os`/`conversation` coupling above.
- `pyproject.toml` console_scripts: `grep -n "scripts\|entry" pyproject.toml` ->
  only `[project.scripts]` with `daedalus = "daedalus.cli:main"` and
  `daedalus-chip = "daedalus.chip_design.cli:main"` (`pyproject.toml:77-79`); no
  direct entrypoint for this module, consistent with it being a library consumed
  by the HTTP interface rather than a CLI surface.
- Bare-string / dynamic reference grep: `Grep pattern="conversation_requests"`
  across `daedalus/`, `apps/`, `scripts/`, `.claude/`, `docs/` found only real
  imports (section 3) plus prose mentions in `docs/work-packets/G1-HIER-11_...`,
  `G1-RUNTIME-03_...`, and `G1-IFACE-HTTP-03_SSE_DELIVERY_OWNER.md` referencing
  this module and its test by name -- no CLI subcommand, no registry key.
- Git history: `git log --oneline -- daedalus/conversation_requests.py` shows
  exactly one commit touching this path, `151b8d18 chore(wip): freeze Gate-1
  dirty tree before hierarchy refactor` -- the file's substantive authorship
  predates the tracked history window available in this checkout (squashed into
  the freeze commit); no evidence of a prior consumer having been removed.

Label: **LIVE**.
