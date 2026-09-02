# ikarus_act.py

## Identity
`C:/Users/Administrator/daedalus/daedalus/ikarus_act.py` — 346 lines
(`wc -l`, matches the packet brief). One sentence: a pure, IO-free, stdlib-only predicate
module answering exactly one question — "may this message reach a
tool-bearing executor" — deliberately decoupled from `ikarus_os.classify`'s
routing question.

## Importers (MEASURED)
Scoped to `daedalus/`, `tests/`, `tools/` explicitly (three separate `Grep`
calls with `path=`), because `.claude/worktrees/agent-*/` holds full repo
copies that would double-count every hit.

daedalus/ (2 sites, both in one file):
- `daedalus/ikarus_os.py:94` — `from . import core, ikarus_act` (module-level)
- `daedalus/ikarus_os.py:95` — `from .ikarus_act import ActDecision` (module-level)

tests/ (3 sites):
- `tests/test_ikarus_act.py:11` — `from daedalus import ikarus_act, ikarus_os`
- `tests/test_ikarus_act.py:12` — `from daedalus.ikarus_act import may_act`
- `tests/test_ikarus_shells.py:19` — `from daedalus.ikarus_act import ActDecision, may_act`

tools/ (0 sites) — grep returned no matches under `tools/`.

Total: 5 unique importer sites (2 daedalus + 3 tests + 0 tools). Matches the
lead's precomputed count exactly; no disagreement.

Dynamic/string references: searched `daedalus/`, `tests/`, `tools/` for the
literal dotted string `"daedalus.ikarus_act"` / `'daedalus.ikarus_act'`
(covers `importlib.import_module`, `__import__`, and any string-embedded
reference) — zero matches anywhere. Also checked `pyproject.toml`
`[project.scripts]` (line 77) — no entry named `ikarus_act`. No dynamic or
console-script reference exists.

## Imports (MEASURED)
Module-level (file:line):
- `ikarus_act.py:82` — `import re` (stdlib)
- `ikarus_act.py:83` — `from dataclasses import dataclass` (stdlib)

Deferred/function-scope: none — no import statement appears inside any
function body in this file.

daedalus.* imports: 0. stdlib: 2 (`re`, `dataclasses`). Third-party: 0.

## What it does
Implements `may_act()`, a narrow-allow/wide-suspect capability gate that
requires a leading English/German imperative act verb with no interrogative
marker, plus a separate `pending_offer`/confirmation path for a bare "yes"
that only clears the previous turn's named `act_offer` objective. It
deliberately never calls or depends on `ikarus_os.classify`, carrying
`classify`'s label only as a reporting-only `intent` field on `ActDecision`.
It takes no IO, no model call, and no store — a caller-supplied
conversation state is the only input, so an unavailable store fails toward
"more restrictive," never less. Size: 347 lines.

## Proposed destination
`daedalus.orchestration` (co-located with `ikarus_os`, its sole daedalus/
importer). Argument: zero daedalus imports means this module is not
kernel/spine/twin/runtimes-adjacent by any measured edge; its only production
consumer is `ikarus_os.py`, which the boundary contract's own
`spine-no-outer-layers` rationale already names by literal prefix
(`daedalus.ikarus_os`) as living outside the spine — i.e. the repository's
own rule authors already treat this family as an outer/orchestration-layer
concern. Placing `ikarus_act` next to its only caller keeps one canonical
location for the capability-gate/classify pair the module's own docstring
insists must never merge.

Counter-argument: a capability gate that decides whether a message may reach
"a tool-bearing executor" sounds trust-boundary-adjacent enough to belong near
`kernel` or `spine`, not `orchestration`. It loses: `may_act` returns an
in-memory `ActDecision` dataclass and enforces nothing — it has zero
`daedalus.kernel`/`daedalus.spine` imports and no lease, effect, or policy
object anywhere in it. The actual effect boundary (EffectLeaseRequest /
broker) is enforced downstream by `ikarus_effect_bridge` and
`daedalus.runtimes.broker`, not here. Elevating a stdlib-only string
heuristic to `kernel` would also be directly refused by
`kernel-no-outer-layers`' own allowlist the moment it imported anything from
`ikarus_os` or the orchestration layer it exists to gate — so `orchestration`
is not just convenient, it is the only destination consistent with what this
module actually touches.

## Family note
Imports none of the other four `ikarus_*` siblings (0 imports, checked
against its own import list above). Is imported by none of the other four
either — `ikarus_chat.py`, `ikarus_effect_bridge.py`, `ikarus_oneshot.py`,
`ikarus_tool_scope.py` were all read in full for this packet and none
references `ikarus_act`. Its only family-adjacent edge is external to this
five-module set: `ikarus_os.py:94-95` (outside the studied five, per the
peer's separate measurement that `ikarus_os` imports only `ikarus_act` and
`ikarus_chat`). Hub/peer/leaf: **leaf** — no intra-five edges in or out.
Vote: SEVERAL destinations (see synthesis below) — under either option this
module goes to `daedalus.orchestration`, specifically alongside `ikarus_chat`
and `ikarus_os` (the "conversational intent" cluster), not alongside the
`ikarus_oneshot`/`ikarus_tool_scope`/`ikarus_effect_bridge` cluster.

## Boundary-rule verdict after the move
- `kernel-no-outer-layers` (source `daedalus.kernel`): (b) vacuously CLEAN —
  attributed to the lead's AST measurement that no file under
  `daedalus/kernel` imports any of the five modules at any scope. (a) this
  module has zero `daedalus.*` imports, so even hypothetically landed under
  `daedalus.kernel` nothing it imports would hit the forbidden
  (`daedalus.schemas`, `daedalus.orchestration`, …) or fail-outside-allowlist
  set. CLEAN both directions.
- `runtimes-no-gates` (source `daedalus.runtimes`): (b) vacuously CLEAN, same
  attribution. (a) zero daedalus imports means no `daedalus.gates` import to
  refuse. CLEAN.
- `spine-no-outer-layers` (source `daedalus.spine`): (b) vacuously CLEAN,
  same attribution. (a) zero daedalus imports; nothing to refuse against the
  spine allowlist (`atomic, budget, config, kernel, limit_policy, mapping,
  sensitivity, structcore`) or its forbidden list (which explicitly names
  `daedalus.ikarus` and `daedalus.ikarus_os` by name — this module is neither).
  CLEAN.
- `twin-no-outer-layers` (source `daedalus.twin`): (b) vacuously CLEAN, same
  attribution. (a) zero daedalus imports; CLEAN.

One-line verdict: **CLEAN** (all four rules, both directions — this module is
not a rule source in the proposed `orchestration` destination, and even
hypothetically it has nothing to refuse).

## Dead-code signals
Not zero importers (5 measured), so this is a finding-not-a-verdict note only
in the negative sense — it is clearly live. Docstring opening line: `"""ikarus_act — MAY this message reach a tool-bearing executor?` — it explicitly
promises a reader (`ikarus_os` calling `may_act` before a Hand ever sees a
message) and even documents the divergence case against `classify` by name.
Chasing one hop: `ikarus_os.py:344` — `return ikarus_act.may_act(message,
intent, _prior_turn(conversation_id))` inside what reads as a live
message-handling path (not a test fixture or comment), and `ikarus_os.py:820`
comments that the `act_offer` block is "Read back by ikarus_act.pending_offer
on the NEXT turn" — consistent, load-bearing use, not dead wiring.

## Confidence
High. Every importer site was read in context (not just grepped), the
zero-daedalus-import claim was verified against the full file read, and the
dynamic-reference search covered the exact dotted string with no hits. Would
raise further only with a runtime trace proving `ikarus_os._design`/`classify`
paths are actually invoked in production (out of scope for a read-only static
dossier).

## Family synthesis (batch-level)

Measured intra-family edges across all five modules in this batch (source →
target, file:line):

- `ikarus_effect_bridge.py:21` → `ikarus_oneshot` (`from .ikarus_oneshot
  import OneShotRequest, OneShotRuntimeEvidenceBinding`)
- `ikarus_effect_bridge.py:22` → `ikarus_tool_scope` (`from .ikarus_tool_scope
  import IkarusToolScopeProjection`)
- `ikarus_tool_scope.py:24` → `ikarus_oneshot` (`from .ikarus_oneshot import
  OneShotRequest, OneShotRuntimeEvidenceBinding`)

No other pair among the five has an edge in either direction:
`ikarus_act` ↔ any of the other four: none. `ikarus_chat` ↔ any of the other
four: none (confirmed by reading `ikarus_chat.py`'s full import list — only
`agents_registry, control_plane, core, hierarchy, projects`, none of which is
an `ikarus_*` sibling). `ikarus_oneshot` → `ikarus_act`/`ikarus_chat`/
`ikarus_effect_bridge`: none (`ikarus_oneshot.py` imports only
`ikarus_runtime_role`, `.kernel.runtime_conformance`, `.schemas`,
`.spine.envelope`).

This produces exactly two disjoint clusters inside the studied five:

- **Cluster "intent"**: `{ikarus_act, ikarus_chat}` — zero edges between
  them, but both are consumed only by `ikarus_os` (outside this five,
  confirmed at `ikarus_os.py:94-95` and `:828`), never by anything in
  Cluster "effect".
- **Cluster "effect"**: `{ikarus_oneshot, ikarus_tool_scope,
  ikarus_effect_bridge}` — internally connected (2 edges into
  `ikarus_oneshot`, 1 edge `effect_bridge → tool_scope`), and all three are
  consumed together by exactly one production site,
  `daedalus/orchestration/missions/one_shot.py:15,20,25`.

Verdict: **SEVERAL destinations, not one package.** This matches and extends
the peer's `ikarus_os` finding (which showed `ikarus_os` disconnected from six
of the eight other siblings): among the five modules measured here, there are
zero cross-cluster edges, and each cluster has a distinct, non-overlapping set
of real callers (`ikarus_os` for Cluster "intent" vs.
`orchestration/missions/one_shot.py` for Cluster "effect"). Both clusters
still measure as `daedalus.orchestration`-shaped (product/mission logic, not
kernel/spine/twin/runtimes — see each module's own destination section), so
the split is a **sub-package split within orchestration**, not a split across
top-level layers: e.g. `daedalus.orchestration.ikarus_chat` (act+chat, next to
`ikarus_os`) versus `daedalus.orchestration.missions` (oneshot+tool_scope+
effect_bridge, next to the one file that already imports all three). Treating
all nine `ikarus_*` names plus `daedalus/ikarus.py` as one flat package would
paper over a real seam that the import graph already draws for free.
