## Identity

`C:/Users/Administrator/daedalus/daedalus/ikarus_effect_bridge.py` — 351
lines (`wc -l`, matches the packet brief). One sentence: a pure translation
layer that projects an already-bounded Ikarus one-shot request and its
policy-projected tool scope into the canonical `EffectLeaseRequest` /
`EffectExecutionRequest` wire types, without itself issuing policy decisions,
leases, or provider calls.

## Importers (MEASURED)

Scoped to `daedalus/`, `tests/`, `tools/` explicitly (separate `Grep` calls
with `path=`), to avoid double-counting `.claude/worktrees/agent-*/` copies.

daedalus/ (1 site):
- `daedalus/orchestration/missions/one_shot.py:15` — `from
  daedalus.ikarus_effect_bridge import (` (start of a multi-line import) —
  module-level.

tests/ (2 sites):
- `tests/orchestration/test_ikarus_mission_integration.py:15` — `from
  daedalus.ikarus_effect_bridge import (` — module-level.
- `tests/test_ikarus_effect_bridge.py:12` — `from daedalus.ikarus_effect_bridge
  import (` — module-level (its own dedicated test file; line 339 in the same
  file is a `Path` string reference to the source file for a doc/self-check,
  not an import, and was not counted).

tools/ (0 sites) — no matches.

Total: 3 unique importer sites (1 daedalus + 2 tests + 0 tools). Matches the
lead's precomputed count exactly; no disagreement.

Dynamic/string references: searched for the literal dotted string
`"daedalus.ikarus_effect_bridge"` / `'daedalus.ikarus_effect_bridge'` across
`daedalus/`, `tests/`, `tools/` — zero matches beyond the ordinary `import`
statements already counted above. `pyproject.toml` `[project.scripts]`
(line 77) has no entry named `ikarus_effect_bridge`. No dynamic or
console-script reference exists.

## Imports (MEASURED)

Module-level (file:line):
- `ikarus_effect_bridge.py:18` — `from datetime import datetime, timezone`
  (stdlib)
- `ikarus_effect_bridge.py:19` — `from typing import Iterable` (stdlib)
- `ikarus_effect_bridge.py:21` — `from .ikarus_oneshot import OneShotRequest,
  OneShotRuntimeEvidenceBinding` → `daedalus.ikarus_oneshot`
- `ikarus_effect_bridge.py:22` — `from .ikarus_tool_scope import
  IkarusToolScopeProjection` → `daedalus.ikarus_tool_scope`
- `ikarus_effect_bridge.py:23` — `from .kernel.contracts import
  EffectLeaseRequest` → `daedalus.kernel.contracts`
- `ikarus_effect_bridge.py:24` — `from .kernel.effects import
  EffectExecutionRequest` → `daedalus.kernel.effects`
- `ikarus_effect_bridge.py:25` — `from .schemas import ContractProvenance,
  EffectScope` → `daedalus.schemas`
- `ikarus_effect_bridge.py:26` — `from .spine.effect_boundary import Effect`
  → `daedalus.spine.effect_boundary`

Deferred/function-scope: none.

daedalus.* imports: 6 (`ikarus_oneshot`, `ikarus_tool_scope`,
`kernel.contracts`, `kernel.effects`, `schemas`, `spine.effect_boundary`).
stdlib: 2 (`datetime`, `typing`). Third-party: 0.

## What it does

Two builder functions, `build_oneshot_effect_lease_request` and
`build_oneshot_effect_execution_request`, cross-check that the supplied
`OneShotRequest`, `OneShotRuntimeEvidenceBinding` and
`IkarusToolScopeProjection` are exact types bound to the same digests, then
construct a canonical `EffectScope`/`EffectLeaseRequest`/
`EffectExecutionRequest`, refusing (`IkarusEffectBridgeRefused`) on any
subject mismatch, missing scope-implied effect, or attempt to broaden scope
between lease and execution. It never calls a provider, issues a lease, or
grants a tool — the module docstring states the normal runtime lease issuer
and `daedalus.runtimes.broker` remain the only execution authority. Size:
351 lines.

## Proposed destination

`daedalus.orchestration` (specifically alongside
`orchestration/missions/one_shot.py`, its sole production importer, which
already imports this module plus `ikarus_oneshot` and `ikarus_tool_scope`
together). Argument: this module imports `daedalus.kernel.contracts` and
`daedalus.kernel.effects` to *produce wire objects the kernel consumes*, but
it does not itself decide policy, issue leases, or execute effects — its own
docstring frames it explicitly as removing "an architectural gap rather than
create another control plane." Its only production caller already lives in
`daedalus/orchestration/missions/`, and its own daedalus imports
(`ikarus_oneshot`, `ikarus_tool_scope`, `schemas`) are themselves
orchestration/product-shaped, not kernel-internal. The task brief specifically
asked whether this is a kernel-adjacent effect bridge or a transport
(`interfaces.bridge`) bridge: it is neither transport (zero imports of
anything under `daedalus.interfaces`, zero networking/IPC/file-bridge code)
nor kernel itself (see Boundary-rule verdict — landing it in `daedalus.kernel`
would get 3 of its 6 daedalus imports REFUSED by the kernel rule's own
allowlist). It is an orchestration-side adapter that speaks kernel wire
formats, which is exactly the shape `daedalus.orchestration` already holds
for `orchestration/missions/one_shot.py`.

Counter-argument: the module's entire purpose is producing
`EffectLeaseRequest`/`EffectExecutionRequest` — the canonical kernel contract
types — which could argue it belongs inside `daedalus.kernel` next to the
contracts it targets, since it is functionally "the kernel's Ikarus-facing
constructor." It loses on measured evidence, not just principle: if this
module moved into `daedalus.kernel`, its own imports of
`daedalus.ikarus_oneshot`, `daedalus.ikarus_tool_scope`, and `daedalus.schemas`
would all be REFUSED by `kernel-no-outer-layers` (the first two are absent
from the kernel allowlist; `daedalus.schemas` is explicitly on the kernel
rule's `forbidden_target_prefixes` list). The rule's own rationale is that
kernel must not depend on outer-layer product/orchestration state — and this
module structurally *is* outer-layer state converted into kernel shape, not
kernel logic itself. Keeping it in `orchestration` avoids inventing a new
kernel-layer exception for imports the kernel rule was written to forbid.

## Family note

Imports two siblings from this batch: `ikarus_oneshot`
(`ikarus_effect_bridge.py:21`) and `ikarus_tool_scope`
(`ikarus_effect_bridge.py:22`). Is imported by none of the other four
siblings measured in this batch — confirmed by reading `ikarus_act.py`,
`ikarus_chat.py`, `ikarus_oneshot.py`, `ikarus_tool_scope.py` in full: none
references `ikarus_effect_bridge`. Hub/peer/leaf: **peer** (a downstream
consumer of `ikarus_oneshot`/`ikarus_tool_scope`, not a hub anything else
depends on within the five). Vote: SEVERAL destinations — see the synthesis
in `ikarus_act.md`. This module is the tightest-coupled member of the
"effect" cluster (`ikarus_oneshot`, `ikarus_tool_scope`,
`ikarus_effect_bridge`), which is disjoint from the "intent" cluster
(`ikarus_act`, `ikarus_chat`); under either the ONE-package or SEVERAL option
this module co-locates with `ikarus_oneshot`/`ikarus_tool_scope`, never with
`ikarus_act`/`ikarus_chat`.

## Boundary-rule verdict after the move

- `kernel-no-outer-layers` (source `daedalus.kernel`): (b) vacuously CLEAN —
  attributed to the lead's AST measurement that no file under
  `daedalus/kernel` imports any of the five modules at any scope. (a) if this
  module hypothetically landed under `daedalus.kernel`: `.ikarus_oneshot`
  (line 21) and `.ikarus_tool_scope` (line 22) would be REFUSED (neither on
  the kernel allowlist `atomic, budget, config, limit_policy, offload,
  primary_tree, sensitivity, spine, storage, twin`); `.schemas` (line 25)
  would be REFUSED (explicitly on `forbidden_target_prefixes`); `.kernel.contracts`
  (line 23) and `.kernel.effects` (line 24) would be ALLOWED (own source
  prefix); `.spine.effect_boundary` (line 26) would be ALLOWED (`spine` is on
  the kernel allowlist).
- `runtimes-no-gates` (source `daedalus.runtimes`): (b) vacuously CLEAN, same
  attribution. (a) forbidden target is `daedalus.gates` only; none of this
  module's six daedalus imports touch `daedalus.gates`. CLEAN even
  hypothetically.
- `spine-no-outer-layers` (source `daedalus.spine`): (b) vacuously CLEAN,
  same attribution. (a) hypothetically landed in spine: `.ikarus_oneshot` and
  `.ikarus_tool_scope` REFUSED (not on the spine allowlist `atomic, budget,
  config, kernel, limit_policy, mapping, sensitivity, structcore`); `.schemas`
  REFUSED (forbidden); `.kernel.contracts`/`.kernel.effects` ALLOWED (`kernel`
  is on the spine allowlist); `.spine.effect_boundary` ALLOWED (own prefix).
- `twin-no-outer-layers` (source `daedalus.twin`): (b) vacuously CLEAN, same
  attribution. (a) hypothetically landed in twin: `.ikarus_oneshot` and
  `.ikarus_tool_scope` REFUSED (not on the twin allowlist `kernel, spine,
  structcore`); `.schemas` REFUSED (forbidden); `.kernel.contracts`/
  `.kernel.effects` ALLOWED (`kernel` on allowlist); `.spine.effect_boundary`
  ALLOWED (`spine` on allowlist).

One-line verdict: **N-A-not-a-rule-source** in the proposed
`daedalus.orchestration` destination; hypothetically **REFUSED**
(`daedalus.ikarus_oneshot`, `daedalus.ikarus_tool_scope`, `daedalus.schemas`)
in kernel/spine/twin, CLEAN in runtimes.

## Dead-code signals

Not zero importers (3 measured). Module docstring opens: `"""Bridge Ikarus
one-shot intent into the canonical Daedalus effect kernel.` and states the
existence rationale explicitly ("The bridge exists to remove an architectural
gap rather than create another control plane"). It promises exactly one
reader class: whatever constructs `EffectLeaseRequest`/
`EffectExecutionRequest` for an Ikarus one-shot call. Chasing one hop:
`daedalus/orchestration/missions/one_shot.py` imports both builder functions
(`build_oneshot_effect_lease_request` implied by the `from
daedalus.ikarus_effect_bridge import (` block at line 15) alongside
`daedalus.kernel.contracts.EffectLeaseRequest` and
`daedalus.kernel.effects.EffectExecutionRequest` (lines 26-27 of that file) —
consistent, load-bearing use inside a real orchestration mission module, not
a stub or comment-only reference.

## Confidence

High. All import/importer sites were read in file context (not grep-only),
the boundary-rule hypotheticals were checked line-by-line against
`docs/architecture/import-boundaries.json`'s allowlists/denylists and
`tools/architecture_boundaries.py:253-299`'s exact refusal logic, and the
dynamic-reference search covered the exact dotted string with zero hits.
Would raise further only by running `tools/architecture_boundaries.py`
against a real post-move tree instead of a hand-traced hypothetical (out of
scope for a read-only dossier).
