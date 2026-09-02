## Identity

`C:/Users/Administrator/daedalus/daedalus/ikarus_tool_scope.py` — 201 lines
(`wc -l`, matches the packet brief). One sentence: a pure projection over
four already-existing subjects (the immutable one-shot request, its runtime-
evidence binding, the canonical `RuntimeManifest`, and the canonical
`PolicyDecision`) that computes an explicit, fail-closed per-call tool set
without owning a second tool registry or executing anything.

## Importers (MEASURED)

Scoped to `daedalus/`, `tests/`, `tools/` explicitly (separate `Grep` calls
with `path=`), to avoid double-counting `.claude/worktrees/agent-*/` copies.

daedalus/ (2 sites):
- `daedalus/ikarus_effect_bridge.py:22` — `from .ikarus_tool_scope import
  IkarusToolScopeProjection` — module-level.
- `daedalus/orchestration/missions/one_shot.py:25` — `from
  daedalus.ikarus_tool_scope import IkarusToolScopeProjection` —
  module-level.

tests/ (2 sites):
- `tests/test_ikarus_effect_bridge.py:18` — `from daedalus.ikarus_tool_scope
  import project_oneshot_tool_scope` — module-level (line 26 in the same file
  is a `Path` string reference to `tests/test_ikarus_tool_scope.py`, not an
  import of the source module, and was not counted).
- `tests/test_ikarus_tool_scope.py:17` — `from daedalus.ikarus_tool_scope
  import (` — module-level, its own dedicated test file (line 311 in the same
  file is a `Path` string reference to the source file, not an import, and
  was not counted).

tools/ (0 sites) — no matches.

Total: 4 unique importer sites (2 daedalus + 2 tests + 0 tools). Matches the
lead's precomputed count exactly; no disagreement.

Dynamic/string references: searched for the literal dotted string
`"daedalus.ikarus_tool_scope"` / `'daedalus.ikarus_tool_scope'` across
`daedalus/`, `tests/`, `tools/` — zero matches beyond the ordinary `import`
statements already counted above. `pyproject.toml` `[project.scripts]`
(line 77) has no entry named `ikarus_tool_scope`. No dynamic or
console-script reference exists.

## Imports (MEASURED)

Module-level (file:line):
- `ikarus_tool_scope.py:20` — `import re` (stdlib)
- `ikarus_tool_scope.py:21` — `from dataclasses import dataclass` (stdlib)
- `ikarus_tool_scope.py:22` — `from typing import Any, Iterable` (stdlib)
- `ikarus_tool_scope.py:24` — `from .ikarus_oneshot import OneShotRequest,
  OneShotRuntimeEvidenceBinding` → `daedalus.ikarus_oneshot`
- `ikarus_tool_scope.py:25` — `from .schemas import PolicyDecision,
  RuntimeManifest` → `daedalus.schemas`
- `ikarus_tool_scope.py:26` — `from .spine.envelope import canonical_sha` →
  `daedalus.spine.envelope`

Deferred/function-scope: none.

daedalus.* imports: 3 (`ikarus_oneshot`, `schemas`, `spine.envelope`).
stdlib: 3 (`re`, `dataclasses`, `typing`). Third-party: 0.

## What it does

`project_oneshot_tool_scope()` validates that the request, runtime-evidence
binding, manifest, and an `allow`-verdict `PolicyDecision` are all exact types
bound to the same request digest, then intersects caller-`requested_tools`
against `manifest.declared_tools` and `policy.effect_scope.tools`, refusing
(`IkarusToolScopeRefused`) closed on any tool absent from either set, any
wildcard token (`*`, `all`, `any`, ...), or a tool-capable manifest lacking
`tool_events`. There is no fallback to runtime defaults, user config, plugins,
or MCP discovery — empty `requested_tools` means no tools even when runtime
and policy both expose more. Size: 201 lines.

## Proposed destination

`daedalus.orchestration` (alongside `ikarus_oneshot` and
`ikarus_effect_bridge`, and next to `orchestration/missions/one_shot.py`,
which imports it directly at line 25). Argument: this module is a pure
projection/authorization-*narrowing* function, not an authorization source —
it reads an already-decided `PolicyDecision` and an already-bound
`OneShotRequest`/evidence pair and can only narrow, never grant. Its own
daedalus imports (`ikarus_oneshot`, `schemas`, `spine.envelope`) mirror
exactly the pattern of its sibling `ikarus_oneshot` (reads canonical
evidence, writes nothing back), and its two production importers
(`ikarus_effect_bridge`, `orchestration/missions/one_shot.py`) are both
already orchestration-layer. Co-locating it there keeps the "effect" cluster
(`ikarus_oneshot` → `ikarus_tool_scope` → `ikarus_effect_bridge`) as one
artifact-adjacent group.

Counter-argument: since this module directly consumes a canonical
`PolicyDecision` and is the last authority deciding what tool set an effect
request will carry, it might belong in `daedalus.kernel` next to policy
enforcement rather than in orchestration. It loses on measured evidence:
placed hypothetically in `daedalus.kernel`, its own import of
`daedalus.ikarus_oneshot` would be REFUSED (not on the kernel allowlist) and
its import of `daedalus.schemas` would be REFUSED (explicitly forbidden for
kernel) — see Boundary-rule verdict below. The module's own docstring is
explicit that "Nothing here executes a tool, resolves a plugin, reads ambient
configuration, or broadens policy" — it is a read-only projection consumed by
an orchestration-side bridge, not a policy engine itself; the actual policy
decision (`PolicyDecision`) is produced upstream and only checked here.

## Family note

Imports one sibling from this batch: `ikarus_oneshot`
(`ikarus_tool_scope.py:24`). Is imported by one sibling from this batch:
`ikarus_effect_bridge` (`ikarus_effect_bridge.py:22`). Hub/peer/leaf:
**peer** (one inbound edge from `ikarus_effect_bridge`, one outbound edge to
`ikarus_oneshot` — a middle link, not a hub or a leaf). Vote: SEVERAL
destinations — see the synthesis in `ikarus_act.md`. This module sits in the
middle of the "effect" cluster's chain (`ikarus_effect_bridge` →
`ikarus_tool_scope` → `ikarus_oneshot`), disjoint from the "intent" cluster
(`ikarus_act`, `ikarus_chat`); under either the ONE-package or SEVERAL option
this module co-locates with `ikarus_oneshot`/`ikarus_effect_bridge`, never
with `ikarus_act`/`ikarus_chat`.

## Boundary-rule verdict after the move

- `kernel-no-outer-layers` (source `daedalus.kernel`): (b) vacuously CLEAN —
  attributed to the lead's AST measurement that no file under
  `daedalus/kernel` imports any of the five modules at any scope. (a) if this
  module hypothetically landed under `daedalus.kernel`: `.ikarus_oneshot`
  (line 24) would be REFUSED (not on the kernel allowlist `atomic, budget,
  config, limit_policy, offload, primary_tree, sensitivity, spine, storage,
  twin`); `.schemas` (line 25) would be REFUSED (explicitly on
  `forbidden_target_prefixes`); `.spine.envelope` (line 26) would be ALLOWED
  (`spine` is on the kernel allowlist).
- `runtimes-no-gates` (source `daedalus.runtimes`): (b) vacuously CLEAN, same
  attribution. (a) forbidden target is `daedalus.gates` only; none of this
  module's three daedalus imports touch `daedalus.gates`. CLEAN even
  hypothetically.
- `spine-no-outer-layers` (source `daedalus.spine`): (b) vacuously CLEAN,
  same attribution. (a) hypothetically landed in spine: `.ikarus_oneshot`
  REFUSED (not on the spine allowlist `atomic, budget, config, kernel,
  limit_policy, mapping, sensitivity, structcore`); `.schemas` REFUSED
  (forbidden); `.spine.envelope` ALLOWED (own prefix).
- `twin-no-outer-layers` (source `daedalus.twin`): (b) vacuously CLEAN, same
  attribution. (a) hypothetically landed in twin: `.ikarus_oneshot` REFUSED
  (not on the twin allowlist `kernel, spine, structcore`); `.schemas` REFUSED
  (forbidden); `.spine.envelope` ALLOWED (`spine` on allowlist).

One-line verdict: **N-A-not-a-rule-source** in the proposed
`daedalus.orchestration` destination; hypothetically **REFUSED**
(`daedalus.ikarus_oneshot`, `daedalus.schemas`) in kernel/spine/twin, CLEAN in
runtimes.

## Dead-code signals

Not zero importers (4 measured). Module docstring opens: `"""Policy-bound
tool projection for Ikarus one-shot requests.` and explains its purpose
directly: Daedalus "does not let Ikarus, a runtime adapter, or a provider own
a second tool registry or authorization layer." It promises a reader that
needs an explicit, non-ambient tool set for one call. Chasing one hop:
`daedalus/ikarus_effect_bridge.py` uses
`tool_scope.enabled_tools`/`tool_scope.digest`/`tool_scope.request_sha256`
throughout its own cross-checking logic (e.g. lines 72-90, 170, 320, 335) —
a real, load-bearing consumer, not a stub reference — and
`orchestration/missions/one_shot.py:25` imports it directly for the same
mission-construction path already confirmed live for `ikarus_oneshot`.

## Confidence

High. All import/importer sites were read in file context, the boundary-rule
hypotheticals were checked line-by-line against
`docs/architecture/import-boundaries.json` and
`tools/architecture_boundaries.py:253-299`'s exact refusal logic, and the
dynamic-reference search covered the exact dotted string with zero hits (two
false-positive path-string grep hits in `tests/test_ikarus_effect_bridge.py`
and `tests/test_ikarus_tool_scope.py` were checked and excluded — they name
the test file, not an import). Would raise further only by running
`tools/architecture_boundaries.py` against a real post-move tree instead of a
hand-traced hypothetical.
