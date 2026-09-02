# daedalus/conversation.py

## 1. Size and shape

931 lines (`wc -l daedalus/conversation.py` = 931).

- 10 classes: 3 frozen dataclasses — `Turn` (conversation.py:240), `DispatchLink`
  (:264), `DispatchEvent` (:276) — and 6 exception classes —
  `ConversationError` (:172), `UnknownConversation` (:176), `UnknownTurn`
  (:180), `UnknownDispatch` (:184), `DuplicateDispatchRef` (:188),
  `ConflictingDispatchEvent` (:194) — plus the main facade class
  `ConversationStore` (:296).
- 13 module-level functions: `_now_iso` (:203), `default_db_path` (:207),
  `conversation_effect_key` (:222), `new_conversation_id` (:227),
  `_turn_from_intent` (:729), `_link_from_intent` (:743),
  `_dispatched_event` (:751), `_report_from_intent` (:765), `_narrate`
  (:777), `recent_turns_context` (:822), `_check_id` (:889), `_jsonable`
  (:896), `default_store` (:919).
- `ConversationStore` has 20 methods: `__init__` (:310),
  `_install_uniqueness_guards` (:348), `pragmas` (:384), `append_turn`
  (:389), `turns` (:428), `get_turn` (:449), `last_turn` (:459),
  `conversation_exists` (:468), `link_dispatch` (:479),
  `record_dispatch_event` (:547), `_dispatch_intent` (:616),
  `_report_intent_by_source_event` (:621), `dispatch_events` (:628),
  `dispatch_status` (:641), `open_dispatches` (:653),
  `_dispatch_summaries` (:669), `resume` (:683), `close` (:712),
  `__enter__` (:718), `__exit__` (:721).
- Module-level state: constant registries (`KIND_TURN`/`KIND_DISPATCH`/
  `KIND_REPORT`/`CONVERSATION_KINDS` at :150-153; `STATUS_ANSWERED`/
  `STATUS_PROPOSED`/`STATUS_ERROR`/`TURN_STATUSES` at :157-160;
  `LIFECYCLE_DISPATCHED`/`LIFECYCLE_REPORTED`/`DISPATCH_LIFECYCLE` at
  :167-169; `__all__` at :132-143) — all frozen, never reassigned. **One
  genuine module-level mutable singleton**: `_STORE_CACHE: dict[str,
  ConversationStore] = {}` and `_STORE_CACHE_LOCK = threading.Lock()`
  (:915-916), populated lazily inside `default_store()` (:919-931) — a
  process-wide cache of `ConversationStore` instances keyed by resolved spine
  path, guarded by the lock, mutated at first call rather than at import.
- No module-level side effects at import: no file I/O, no env var read, no
  network call, no DB connection opened at import time. `default_db_path()`
  only calls through to `daedalus.spine.ledger.default_db_path()` when
  invoked; the actual `SpineLedger`/SQLite connection is opened lazily inside
  `ConversationStore.__init__` (:310-346), itself only reached via
  `default_store()` or explicit construction.

## 2. What it does

It is a facade that gives the Ikarus assistant's chat turns a durable,
resumable identity by writing three typed intent kinds
(`conversation.turn`, `conversation.dispatch`, `conversation.dispatch.report`)
as facts onto the single canonical event spine (`daedalus.spine.ledger.SpineLedger`), rather than owning any database or file of its own — the
module used to open a private SQLite file and was consolidated onto the spine
(see the module's own "WHY THE FOURTH LOG IS GONE" section, :33-58). It
exposes `ConversationStore` for appending/reading turns, linking dispatched
work back to the turn that caused it, recording honest dispatch-outcome
reports, and reconstructing a closed-vocabulary "what was I doing" narrative
(`resume`) purely from durable rows. It explicitly refuses to be an
orchestration decision engine: it writes nothing as an open/resolvable
intent, so nothing it records ever appears in the spine's crash-recovery
worklist, and `open_dispatches`/`resume` are read-only displays that "may
never redo work because it appears here" (module docstring, :60-66).

## 3. Who imports it (MEASURED)

Searched `daedalus/`, `tests/`, `tools/`, `apps/`, `docs/`, `.claude/` for
`conversation` as an import token, distinguishing the target module
(`daedalus/conversation.py`, i.e. `from . import conversation` /
`from daedalus import conversation` / `import daedalus.conversation`) from
the **unrelated** sibling module `daedalus/interfaces/bridge/conversation.py`
(imported as `from ...interfaces.bridge import conversation as bridge_conversation` / `from . import conversation` inside
`daedalus/interfaces/bridge/__init__.py`) and from the plain English word
"conversation" appearing in unrelated docstrings/kwargs
(`daedalus/kernel/events/envelope.py`, `daedalus/interfaces/http/sse.py`,
`daedalus/integrations/hermes/worker.py` — none of these three actually
imports `daedalus.conversation`; see below).

**TOTAL: 4 production files + 6 test files = 10 files import
`daedalus.conversation`.** No non-Python importer found (no console_script,
no dynamic string reference, no `.ts` contract naming it directly — the
frontend only sees `conversation_id` as an opaque HTTP field).

Production, by layer:

- `daedalus/conversation_requests.py:20` — `from . import conversation, editor_context, ikarus_os` — **MODULE-LEVEL**. Layer: flat, unclassified in
  this packet. Heaviest structural consumer: re-exports/uses
  `conversation.conversation_effect_key`, `conversation.default_db_path`,
  `conversation.default_store`, `conversation.PRESENT`/`DEGRADED`/`UNKNOWN`,
  `conversation.STATUS_PROPOSED` (file-wide). Its own docstring (:1-11) states
  "Final chat turns continue to be persisted by `daedalus.ikarus_os` through
  `daedalus.conversation`" — i.e. it explicitly names `ikarus_os` as the real
  writer and itself as a request-lifecycle layer on top.
- `daedalus/ikarus_os.py` — **DEFERRED**, 4 call sites, all `from . import conversation` inside function bodies: `_prior_turn` (:330),
  `_turn_status_for_envelope` (:430), `_persist_turn` (:457),
  `_conversation_context` (:865). Layer: flat, unclassified in this packet,
  but named by the master plan §7 as part of "Ikarus... the persistent
  assistant and orchestration layer." This is the module's design center: its
  own docstring (:5-11) names `ikarus_os.ask()`/`ask_stream()` as "the
  assistant seam" this module exists to make resumable.
- `daedalus/web_api.py` — **DEFERRED**, 2 call sites, both `from . import conversation as conv` inside functions: `_conversation_view` (:863, GET
  `/api/conversations/<id>` handler) and `_conversation_dispatch_for_task`
  (:908). Layer: flat legacy HTTP host / `interfaces/http` split.
- `daedalus/file_bridge.py` — **DEFERRED**, 2 call sites, both `from . import conversation` inside functions: `_conversation_report_fields` (:517),
  `_project_report_to_conversation` (:539). Layer: **SCC-owned** (`file_bridge`
  is one of the 11 declared SCC modules — do not classify, only record this
  edge). Note `file_bridge.py:16` also imports
  `from .interfaces.bridge import conversation as bridge_conversation` at
  MODULE-LEVEL — that is the *other*, sibling `conversation.py`
  (`daedalus/interfaces/bridge/conversation.py`), not this module; do not
  conflate the two edges.

Test files (package = `tests/`), all confirmed by reading each import line:

- `tests/test_bridge_restart.py:43` — `from daedalus import conversation as conversation_mod` — MODULE-LEVEL.
- `tests/test_conversation_on_canonical_spine.py:36` — `from daedalus import conversation as conv` — MODULE-LEVEL. This is the module's dedicated test
  file (also asserts, at :423, that no module still opens the retired
  `runs/ikarus/conversations.sqlite3` file).
- `tests/test_conversation_requests.py:8-9` — `from daedalus import conversation` and `from daedalus import conversation_requests as requests` —
  both MODULE-LEVEL.
- `tests/test_ikarus_shells.py:365` — `from daedalus import conversation` —
  **DEFERRED**, inside a test method.
- `tests/contracts/test_observation_state_hierarchy.py:9` —
  `import daedalus.conversation as conversation` — MODULE-LEVEL. This test
  (:33-48) specifically asserts `conversation.OUTCOME_STATES is
  observations.OBSERVATION_STATES` and that every health-vocabulary name
  re-exported by `conversation` is the identical object from
  `daedalus.kernel.contracts.observations` — i.e. it pins the exact
  kernel-contract dependency named in §4 below.
- `tests/test_web_api.py:11-19` — part of
  `from daedalus import (control_plane, conversation as conversation_mod, file_bridge, hierarchy, ikarus_chat, runtime_registry, web_api)` —
  MODULE-LEVEL. (This file also imports `control_plane`; see that dossier.)

Non-importers ruled out by reading the actual line, not just the grep hit:

- `daedalus/kernel/events/envelope.py:810` — the string `"daedalus/conversation.py"` appears only as a dict key in a documentation catalog of
  "why this module is NOT a run record," with the value explaining
  "it produces no records of its own any more... this module inherits the
  join instead of needing its own conversion." This is a cross-reference
  *about* the module, not an import of it — but it is corroborating evidence
  for §2/§5: the kernel's own event-conversion inventory already treats
  `conversation.py` as outside the kernel's run-record contract set.
- `daedalus/interfaces/http/sse.py:8` imports `conversation_requests`, not
  `conversation`; its `conversation_id` hits are an opaque query-string field.
- `daedalus/interfaces/bridge/__init__.py:3` imports the sibling
  `daedalus/interfaces/bridge/conversation.py`, a different file.
- `daedalus/integrations/hermes/worker.py:181,225` use the bare word
  "conversation" as a dict/attribute-name guess (`"run_conversation"`,
  `"conversation"` among `("messages", "conversation", "history")|`), unrelated
  to this module.

## 4. What it imports (MEASURED)

All MODULE-LEVEL (no deferred/`TYPE_CHECKING`/try-guarded imports in this
file). Third-party: stdlib only (`json`, `sqlite3`, `threading`, `uuid`,
`dataclasses`, `datetime`, `pathlib`, `typing`).

- `from .kernel.contracts.observations import (ABSENT, DEGRADED, OBSERVATION_STATES as OUTCOME_STATES, PRESENT, UNKNOWN, WORKING)` —
  conversation.py:116-123. Target: **kernel** (`daedalus.kernel.contracts.observations`). Re-exported verbatim (not re-declared) so a
  dispatch's `outcome_state` can never drift from the repo's one closed
  health vocabulary (module docstring :68-82; pinned by
  `tests/contracts/test_observation_state_hierarchy.py`).
- `from .spine.durability import open_gate0_spine_writer` — conversation.py:124.
  Target: **spine**. The sanctioned Gate-0 writer factory; used at
  `ConversationStore.__init__` (:341) to open the writable ledger.
- `from .spine.ledger import (DEFAULT_BUSY_TIMEOUT_MS, Intent, SpineLedger, default_db_path as spine_db_path)` — conversation.py:125-130. Target:
  **spine**.

That is the module's entire `daedalus.*` dependency surface: two targets,
both already-privileged layers (`kernel.contracts`, `spine`), nothing from
`orchestration`, `runtimes`, `providers`, `gates`, `eval`, `chip_design`, or
any other flat/product module.

## 5. Proposed destination

**orchestration**, confidence **medium** — this is the load-bearing,
genuinely close call the task asked me to measure rather than assume.

What was measured, per the task's explicit instruction ("measure whether it
stores durable state and who reads it"):

- It **does** store durable state: every `append_turn`/`link_dispatch`/
  `record_dispatch_event` call is `self.spine.record_fact(...)` — a
  synchronously committed, WAL-durable row on the canonical event store
  opened through the Gate-0 writer factory (:341), not an in-memory or
  best-effort write.
- Who reads it, traced concretely rather than assumed:
  - `ikarus_os._prior_turn` (:313-335) feeds `_prior_turn(conversation_id)`
    into `ikarus_act.may_act(message, intent, _prior_turn(...))` at
    `_decide` (:337-344) — i.e., the **stored turn state changes whether a
    subsequent message is allowed to act** (the confirm/deny flow for a
    previously proposed action). That is a real orchestration-relevant read,
    not mere display.
  - `ikarus_os._conversation_context` (:858-874) feeds prior turns and
    observed dispatch reports back into the model's prompt via
    `recent_turns_context`, when a caller opts in with `conversation_id` —
    again read by the orchestration/assistant core to shape what happens
    next, not by a UI-only consumer.
  - `web_api._conversation_view` (:855-884) is the one purely-display reader:
    it serves `GET /api/conversations/<id>` for UI resume/scrollback with no
    decision attached.
  - `file_bridge.py` only *writes* reports into it (projecting a terminal
    bridge outcome as a fact); it does not read conversation state to decide
    anything.
- Against that: the module's own docstring is emphatic, in language that
  echoes `AGENTS.md`'s forbidden-direction list almost exactly, that it
  "still refuses to be" orchestration state (:60-66): "Chat is an interface,
  not orchestration state. Nothing here decides anything... the rows here are
  attribution and narrative only." Read literally, that is the module
  asserting an `interfaces/*` identity for itself.

Reconciling those two measurements: the module's *own code* never decides
anything (true, and correctly so — it stays a narrative/attribution layer,
which is exactly what keeps it from being the forbidden "chat transcripts as
orchestration state" anti-pattern in `AGENTS.md`). But the *state it durably
stores* is read by `ikarus_os` — the master plan's own "persistent assistant
and orchestration layer" (§7) — to gate whether an action executes and to
shape the model's next prompt. Its heaviest structural consumers
(`ikarus_os`, `conversation_requests`) are both orchestration/assistant-core
modules, not thin interface shells; only `web_api`'s single read site is
purely interface-flavored, and `file_bridge` only writes. I read "durable
memory the orchestration core depends on for its next decision" as closer to
`orchestration` than to any single `interfaces/*` subtype, and the module's
only two `daedalus.*` dependencies (`kernel.contracts`, `spine`) place no
constraint against that (§6).

What would change my mind: if the hierarchy lead classifies `ikarus_os.py`
itself as `interfaces` rather than `orchestration` (it is not in either of my
two assigned modules, and I did not classify it), the strongest argument
above weakens considerably and `interfaces/http` becomes the better fit,
since 3 of 4 production importers (`web_api`, `file_bridge`,
`conversation_requests`) are then all interface-layer. I flag this as the
single fact most likely to flip my answer.

The module is not fused / does not need a split: `Turn`/`DispatchLink`/
`DispatchEvent` and their read/write paths are one coherent
"turn+dispatch+report on the canonical spine" responsibility, structurally
mirroring `daedalus/kernel/attempt_ledger.py` (the facade the module's own
docstring says it is "shaped after," :14-17) but deliberately excluded from
kernel because turn/dispatch/report are not among the master plan's
invariant-1 canonical kernel objects (Mission, Attempt, Evidence, Campaign).

## 6. Boundary-rule check after the move

Read `docs/architecture/import-boundaries.json`. Four rules, sourced from
`daedalus.kernel`, `daedalus.runtimes`, `daedalus.spine`, `daedalus.twin`
respectively — none sourced from `daedalus.orchestration` or
`daedalus.interfaces.*`.

(a) If `conversation.py` moves to `daedalus/orchestration/...`, would its own
imports be refused? **No.** No rule constrains what `daedalus.orchestration`
may import. Its only two `daedalus.*` targets, `daedalus.kernel.contracts.observations` and `daedalus.spine.*`, are not on any
forbidden list for any source in this file (they are in fact explicitly
*allowed* targets for `daedalus.kernel` itself, under `kernel-no-outer-layers`'s `allowed_target_prefixes`, which includes `spine`; and
`spine-no-outer-layers`'s own `allowed_target_prefixes` includes `kernel`).
Nothing about the move creates a refusal.

(b) Does any CURRENT rule name this module by prefix? Not `conversation`
specifically. But `spine-no-outer-layers` already forbids the prefixes
`daedalus.orchestration`, `daedalus.web_api`, `daedalus.file_bridge`,
`daedalus.ikarus_os`, and `daedalus.ikarus` (among others) as targets FROM
`daedalus.spine`. That rule constrains what spine may import, not what may
import `conversation.py`, so it is not directly triggered by this module's
move — but it is strong corroborating context: the same rule set already
treats `ikarus_os`, `file_bridge`, and `web_api` (three of this module's four
production importers) as outer-layer/product code the spine must stay below,
which is consistent with `conversation.py` — a thin facade the spine-adjacent
side of that same relationship — living in `orchestration` rather than in
`spine` itself alongside its own dependency.

(c) N/A — proposed destination is `orchestration`, not `kernel`/`spine`/
`twin`, so those three allowlists do not constrain this module's own
imports. (For completeness, if this module were hypothetically placed in
`spine`, both of its targets — `kernel` and its own package — are on
`spine-no-outer-layers`'s allowlist, so it would pass that check too; I am
not proposing that destination because `conversation.py` is a
domain-specific chat facade, not generic spine infrastructure, and no
production importer is a spine module.)

(d) **Highest-value check.** Does any kernel/spine/twin module currently
import `daedalus.conversation`, such that moving it into `orchestration`
(a target every one of those three rules already forbids by prefix) turns a
currently-green edge into a violation? **Measured: no.**
`grep -r conversation daedalus/kernel daedalus/spine daedalus/twin` found
exactly 3 files with a hit — `daedalus/kernel/events/ledger.py:748-752`,
`daedalus/kernel/events/envelope.py:810`, and
`daedalus/kernel/contracts/observations.py:3,5` — and reading each line
(§3) confirms all three are prose/comment/catalog mentions of the *concept*
"conversation," not a single `import` statement naming
`daedalus.conversation`. There is no currently-green kernel/spine/twin edge
into this module to break. The move is clean by this check, symmetrically
with `control_plane.py`.

## 7. Dead-code signals

Not applicable — **LIVE**. Measured 4 distinct production files importing it
(§3: `conversation_requests.py` module-level; `ikarus_os.py`, `web_api.py`,
`file_bridge.py` deferred but real, all reached from live request paths), a
dedicated regression test (`tests/test_conversation_on_canonical_spine.py`,
which also positively asserts the *retired* predecessor store is gone), and
5 more test files exercising it end-to-end
(`test_web_api.py`, `test_bridge_restart.py`, `test_conversation_requests.py`,
`test_ikarus_shells.py`, `tests/contracts/test_observation_state_hierarchy.py`). The module's own docstring additionally documents its
provenance (consolidated from a prior private SQLite store, commits
`83e41fcc`/`b3bf4364`/`151b8d18` per `git log --follow`) and its promised
readers by name (`ikarus_os.py`, `file_bridge.process_request`,
`daedalus.health`) — all of which were confirmed as real, present-day
importers or documented-and-verified cross-references above.
