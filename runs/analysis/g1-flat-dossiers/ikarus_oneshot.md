## Identity

`C:/Users/Administrator/daedalus/daedalus/ikarus_oneshot.py` — 352 lines
(`wc -l`, matches the packet brief). One sentence: an effect-free module that
builds an immutable, structurally-single-turn `OneShotRequest` and binds it to
already-existing canonical `RuntimeManifest`/`RuntimeConformanceReceipt`
evidence, without calling a model, opening a network connection, or granting
a tool.

## Importers (MEASURED)

Scoped to `daedalus/`, `tests/`, `tools/` explicitly (separate `Grep` calls
with `path=`), to avoid double-counting `.claude/worktrees/agent-*/` copies.

daedalus/ (3 sites):
- `daedalus/ikarus_effect_bridge.py:21` — `from .ikarus_oneshot import
  OneShotRequest, OneShotRuntimeEvidenceBinding` — module-level.
- `daedalus/ikarus_tool_scope.py:24` — `from .ikarus_oneshot import
  OneShotRequest, OneShotRuntimeEvidenceBinding` — module-level.
- `daedalus/orchestration/missions/one_shot.py:20` — `from
  daedalus.ikarus_oneshot import (` (start of a multi-line import) —
  module-level.

tests/ (4 sites):
- `tests/orchestration/test_ikarus_mission_integration.py:20` — `from
  daedalus.ikarus_oneshot import OneShotRuntimeRefused` — module-level.
- `tests/test_ikarus_effect_bridge.py:17` — `from daedalus.ikarus_oneshot
  import OneShotRequest` — module-level.
- `tests/test_ikarus_oneshot.py:10` — `from daedalus.ikarus_oneshot import (`
  — module-level (its own dedicated test file; line 251 in the same file is a
  `Path` string reference to the source file, not an import, and was not
  counted).
- `tests/test_ikarus_tool_scope.py:11` — `from daedalus.ikarus_oneshot import
  OneShotRequest, bind_oneshot_runtime_evidence` — module-level.

tools/ (0 sites) — no matches.

Total: 7 unique importer sites (3 daedalus + 4 tests + 0 tools). Matches the
lead's precomputed count exactly; no disagreement.

Dynamic/string references: searched for the literal dotted string
`"daedalus.ikarus_oneshot"` / `'daedalus.ikarus_oneshot'` across `daedalus/`,
`tests/`, `tools/` — zero matches beyond the ordinary `import` statements
already counted above. `pyproject.toml` `[project.scripts]` (line 77) has no
entry named `ikarus_oneshot`. No dynamic or console-script reference exists.

## Imports (MEASURED)

Module-level (file:line):
- `ikarus_oneshot.py:19` — `import re` (stdlib)
- `ikarus_oneshot.py:20` — `from dataclasses import dataclass` (stdlib)
- `ikarus_oneshot.py:21` — `from datetime import datetime, timedelta`
  (stdlib)
- `ikarus_oneshot.py:22` — `from typing import Any` (stdlib)
- `ikarus_oneshot.py:24` — `from .ikarus_runtime_role import
  RuntimeRoleSnapshot` → `daedalus.ikarus_runtime_role`
- `ikarus_oneshot.py:25` — `from .kernel.runtime_conformance import
  RuntimeConformanceError, verify_current_conformance` →
  `daedalus.kernel.runtime_conformance`
- `ikarus_oneshot.py:26` — `from .schemas import ResourceBudget,
  RuntimeConformanceReceipt, RuntimeManifest` → `daedalus.schemas`
- `ikarus_oneshot.py:27` — `from .spine.envelope import canonical_sha` →
  `daedalus.spine.envelope`

Deferred/function-scope: none.

daedalus.* imports: 4 (`ikarus_runtime_role`, `kernel.runtime_conformance`,
`schemas`, `spine.envelope`). stdlib: 4 (`re`, `dataclasses`, `datetime`,
`typing`). Third-party: 0.

## What it does

`OneShotRequest` is a frozen dataclass with structural single-turn/single-
attempt validation (`budget.max_attempts` in `{None, 1}`, positive
`max_tokens`/`max_wall_time_s`) and an empty `tool_scope` on its
canonical-hash `subject()`. `bind_oneshot_runtime_evidence()` cross-checks a
request against an exact `RuntimeRoleSnapshot`/`RuntimeManifest` and calls
`kernel.runtime_conformance.verify_current_conformance` before returning an
`OneShotRuntimeEvidenceBinding`, refusing (`OneShotRuntimeRefused`) on any
identity mismatch or stale/failed conformance. Real provider execution is
explicitly deferred elsewhere: the docstring states it "still has to pass
through `daedalus.runtimes.broker`." Size: 352 lines.

## Proposed destination

`daedalus.orchestration` (alongside `ikarus_effect_bridge` and
`ikarus_tool_scope`, and next to `orchestration/missions/one_shot.py`, which
imports all three together). Argument: this is the base contract type the
"effect" cluster shares — both `ikarus_effect_bridge` and `ikarus_tool_scope`
import it, and its own only production importer beyond those two is
`orchestration/missions/one_shot.py`. Its daedalus imports
(`ikarus_runtime_role`, `kernel.runtime_conformance`, `schemas`,
`spine.envelope`) read kernel/spine evidence but never write to it and never
construct a kernel effect object — this module produces `OneShotRequest`/
`OneShotRuntimeEvidenceBinding`, not `EffectLeaseRequest`. Locating it with
its two daedalus/ dependents keeps the "one-shot" family artifact-adjacent.

Counter-argument: this module's structural invariants (single attempt, empty
tool scope, conformance verification against canonical runtime evidence) read
like a policy/kernel-adjacent contract that could belong in `daedalus.kernel`
next to `runtime_conformance`, since it directly gates on
`verify_current_conformance`. It loses on measured evidence: if this module
landed in `daedalus.kernel`, its own imports of `daedalus.ikarus_runtime_role`
and `daedalus.schemas` would both be REFUSED (see Boundary-rule verdict) —
`daedalus.schemas` is explicitly forbidden for kernel, and
`ikarus_runtime_role` is absent from the kernel allowlist. The module's own
docstring is explicit that it deliberately avoids becoming "a second runtime
authority" and defers real execution to `daedalus.runtimes.broker` — it is
Ikarus-side request construction, not kernel policy, and the import-boundary
contract agrees by refusing it the moment it is hypothetically placed there.

## Family note

Imports one sibling from this batch: none directly of the studied five — its
only `ikarus_*` import is `ikarus_runtime_role`, which is OUTSIDE this batch's
five modules (it is a ninth sibling in the wider `ikarus_*` family per the
task brief, not one of `{ikarus_act, ikarus_chat, ikarus_effect_bridge,
ikarus_oneshot, ikarus_tool_scope}`). Within the five studied here, it imports
none of `ikarus_act`/`ikarus_chat`/`ikarus_effect_bridge`/`ikarus_tool_scope`.
Is imported by two siblings: `ikarus_effect_bridge`
(`ikarus_effect_bridge.py:21`) and `ikarus_tool_scope`
(`ikarus_tool_scope.py:24`). Hub/peer/leaf: **hub** within the five (2 inbound
edges, 0 outbound edges to any of the other four) — it is the shared base
contract both `ikarus_effect_bridge` and `ikarus_tool_scope` depend on. Vote:
SEVERAL destinations — see the synthesis in `ikarus_act.md`. This module
anchors the "effect" cluster (`ikarus_oneshot`, `ikarus_tool_scope`,
`ikarus_effect_bridge`), disjoint from the "intent" cluster (`ikarus_act`,
`ikarus_chat`); under either the ONE-package or SEVERAL option this module
co-locates with `ikarus_effect_bridge`/`ikarus_tool_scope`, never with
`ikarus_act`/`ikarus_chat`.

## Boundary-rule verdict after the move

- `kernel-no-outer-layers` (source `daedalus.kernel`): (b) vacuously CLEAN —
  attributed to the lead's AST measurement that no file under
  `daedalus/kernel` imports any of the five modules at any scope. (a) if this
  module hypothetically landed under `daedalus.kernel`: `.ikarus_runtime_role`
  (line 24) would be REFUSED (not on the kernel allowlist `atomic, budget,
  config, limit_policy, offload, primary_tree, sensitivity, spine, storage,
  twin`); `.schemas` (line 26) would be REFUSED (explicitly on
  `forbidden_target_prefixes`); `.kernel.runtime_conformance` (line 25) would
  be ALLOWED (own source prefix); `.spine.envelope` (line 27) would be
  ALLOWED (`spine` is on the kernel allowlist).
- `runtimes-no-gates` (source `daedalus.runtimes`): (b) vacuously CLEAN, same
  attribution. (a) forbidden target is `daedalus.gates` only; none of this
  module's four daedalus imports touch `daedalus.gates`. CLEAN even
  hypothetically.
- `spine-no-outer-layers` (source `daedalus.spine`): (b) vacuously CLEAN,
  same attribution. (a) hypothetically landed in spine: `.ikarus_runtime_role`
  REFUSED (not on the spine allowlist `atomic, budget, config, kernel,
  limit_policy, mapping, sensitivity, structcore`); `.schemas` REFUSED
  (forbidden); `.kernel.runtime_conformance` ALLOWED (`kernel` on allowlist);
  `.spine.envelope` ALLOWED (own prefix).
- `twin-no-outer-layers` (source `daedalus.twin`): (b) vacuously CLEAN, same
  attribution. (a) hypothetically landed in twin: `.ikarus_runtime_role`
  REFUSED (not on the twin allowlist `kernel, spine, structcore`); `.schemas`
  REFUSED (forbidden); `.kernel.runtime_conformance` ALLOWED (`kernel` on
  allowlist); `.spine.envelope` ALLOWED (`spine` on allowlist).

One-line verdict: **N-A-not-a-rule-source** in the proposed
`daedalus.orchestration` destination; hypothetically **REFUSED**
(`daedalus.ikarus_runtime_role`, `daedalus.schemas`) in kernel/spine/twin,
CLEAN in runtimes.

## Dead-code signals

Not zero importers (7 measured — the highest of the five). Module docstring
opens: `"""Stateless one-shot request port for Ikarus.` and states its reason
for existing: to keep Hermes's one-shot invariant "bound to Daedalus'
existing runtime identity, budget and conformance contracts instead of adding
a session database, mutable template registry, provider client, or second
runtime authority." It promises readers that need a bounded, tool-less
one-shot call. Chasing one hop: `daedalus/orchestration/missions/one_shot.py`
imports from this module at line 20 alongside
`daedalus.kernel.contracts.EffectLeaseRequest` and
`daedalus.schemas.MissionContract` in the same file — a real mission-execution
module, not a stub. `ikarus_effect_bridge.py` and `ikarus_tool_scope.py` also
both actively call into its exported types (`OneShotRequest`,
`OneShotRuntimeEvidenceBinding`) inside their own live cross-checking logic
(e.g. `ikarus_effect_bridge.py:77-83`), confirming live, load-bearing use one
hop out.

## Confidence

High. All import/importer sites were read in file context, the boundary-rule
hypotheticals were checked line-by-line against
`docs/architecture/import-boundaries.json` and
`tools/architecture_boundaries.py:253-299`'s exact refusal logic, and the
dynamic-reference search covered the exact dotted string with zero hits.
Would raise further only by running `tools/architecture_boundaries.py`
against a real post-move tree instead of a hand-traced hypothetical.
