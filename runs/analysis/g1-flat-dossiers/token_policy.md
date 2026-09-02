# daedalus/token_policy.py

Scope note: all searches below are scoped to `daedalus/`, `tests/`, `tools/`
only (Grep `path=`). `.claude/worktrees/agent-*/` holds full duplicate copies
of `daedalus/` and `tests/` and was explicitly excluded to avoid double
counting.

## Identity

Absolute path: `C:/Users/Administrator/daedalus/daedalus/token_policy.py`.
29 lines. A pure compatibility re-export facade: its entire body is a
`from .runtimes.providers.token_policy import (...)` block plus a matching
`__all__`, docstringed as `"Compatibility facade for runtime-owned provider
token policy."`

## Registered shim (checked first, per the steer)

`docs/architecture/shim-registry.json` has an exact entry (lines 208-215):

```json
{
  "import_path": "daedalus.token_policy",
  "owner": "runtimes-providers",
  "targets": ["daedalus.runtimes.providers.token_policy"],
  "kind": "module_reexport",
  "removal_criteria": "Source, runtime-string, wheel, documentation, monkeypatch, and pickle audits show no remaining legacy token-policy import after one supported compatibility release."
}
```

This resolves the "shim, foundation leaf, or delete?" question directly: it
is a **registered `module_reexport` shim**, not an undocumented leaf or a
delete candidate needing discovery — the real implementation already lives
at `daedalus/runtimes/providers/token_policy.py`.

Removal-criteria check, halves verified vs. not:
- **Source audit — verified, and it FAILS the criterion.** I found 2
  daedalus/ and 4 tests/ live imports of the *old* `daedalus.token_policy`
  path (below), i.e. remaining legacy callers exist right now. The removal
  criterion ("no remaining legacy token-policy import") is **not met**.
- **Runtime-string, wheel, documentation, monkeypatch, pickle audits — NOT
  verified.** Out of scope for a grep-based dossier; I did not run a wheel
  build, a monkeypatch/pickle-identity probe, or a documentation sweep
  outside `docs/`. These are named explicitly as unverified rather than
  assumed clean.

Consistent with a peer worker's (`flat-dossiers-b`) independent finding on
the same registry entry, and with their comparison case `daedalus.orchestrate`
(also a registered shim, still blocked on 4 documented `python -m
daedalus.orchestrate` invocations) — `token_policy` is in the same "shim not
yet safe to delete" state, blocked on its own remaining source callers
rather than external invocations.

## Importers (MEASURED)

Total found: 6 sites (2 daedalus/ + 4 tests/ + 0 tools/), 0 deferred —
matches the lead's precomputed count exactly. All of these import the OLD
`daedalus.token_policy` path (i.e. the shim itself, not its target).

daedalus/ (2 sites, both module-level):
- `daedalus/providers/claude_cli.py:56` — `from ..token_policy import trim_paths`.
- `daedalus/kairos/orchestrate.py:13` — `from ..token_policy import MAX_TODO_CHARS, trim_paths, trim_text`.

tests/ (4 sites, all module-level):
- `tests/test_agent_env.py:14` — `from daedalus.token_policy import STATIC_PROMPT_PREFIX, trim_paths, trim_text`.
- `tests/runtimes/test_provider_helper_hierarchy.py:8` — `import daedalus.token_policy as legacy_tokens` (this test file explicitly asserts, at line 69, `test_legacy_token_policy_is_an_exact_reexport_facade`, that the shim's exported names are object-identical to the new module's — i.e. it is the packet's own regression guard for this facade staying an exact re-export).
- `tests/test_execution_limit_consumers.py:8` — `from daedalus.token_policy import trim_paths`.
- `tests/test_hardening.py:34` — `from daedalus.token_policy import MAX_PATHS_PER_REQUEST, trim_paths, trim_text`.

Not counted as importers (correctly excluded, verified by reading context):
- `daedalus/claude_bridge.py:22`, `daedalus/providers/codex_cli.py:50`,
  `daedalus/providers/_report.py:39` all import
  `..runtimes.providers.token_policy` directly — the NEW path, not the shim.
- `daedalus/runtimes/providers/reporting.py:13` imports `.token_policy`
  relative to its own package (`daedalus.runtimes.providers`), i.e. the new
  module, not the old shim.
- `daedalus/token_policy.py:3` is the shim's own body importing its target —
  not an external caller.
- `tests/test_slice_egress_gate.py:60` and
  `tests/test_slice_secret_value_shape.py:139,252` reference the path string
  `"token_policy.py"` / `"daedalus/token_policy.py"` inside literal lists
  passed to a checker, not an import.

tools/: 0 matches for `token_policy` anywhere under `tools/`.

Dynamic/string references searched: no `python -m daedalus.token_policy`
anywhere in the repo (it has no `__main__` guard — confirmed by reading the
full 29-line file). No `importlib`/`__import__` reference found. No
`pyproject.toml` console_scripts entry.

## Imports (MEASURED)

Module-level:
- `daedalus/token_policy.py:3` — `from .runtimes.providers.token_policy import (CHEAP_MODEL, DEFAULT_MODEL, ExecutionLimitPolicy, HIGH_RISK_MODEL, MAX_PATHS_PER_REQUEST, MAX_SUMMARY_CHARS, MAX_TODO_CHARS, STATIC_PROMPT_PREFIX, load_limit_policy, trim_paths, trim_text)` → `daedalus.runtimes`.

Deferred/function-scope: none — the entire file is a 29-line, module-level-
only re-export block.

Outbound profile: `{runtimes}`, 0 third-party, 0 deferred — matches the
lead's precomputed profile exactly.

## What it does

A 29-line pure re-export: it imports eleven names (model tier constants,
`ExecutionLimitPolicy`, size-limit constants, `load_limit_policy`,
`trim_paths`, `trim_text`) from `daedalus.runtimes.providers.token_policy`
and re-exports them under the legacy `daedalus.token_policy` name via a
matching `__all__`. It contains no logic of its own — no functions, no
classes, no conditionals. Its sole purpose is backward compatibility for
callers that have not yet migrated to the `daedalus.runtimes.providers`
path, as the shim registry's own `removal_criteria` states.

## Proposed destination

**delete** (scheduled, not yet executable).

Argument: the shim registry itself declares the intended end state —
`kind: "module_reexport"`, owner `runtimes-providers`, target already fully
implemented at `daedalus/runtimes/providers/token_policy.py`. There is no
new code to relocate; the file's entire value is temporary compatibility.
Filing it as `runtimes` (i.e. treating it as if it belongs there
permanently) would create a second, redundant re-export path sitting next to
the real module for no architectural reason — precisely what the master
plan's §5 "one canonical execution path" language and the shim registry's
own removal criteria argue against.

Strongest counter-argument: the removal criterion is **measurably not met
today** (6 live legacy-path importers found above), so classifying it
`delete` right now could read as premature — the 2 daedalus/ and 4 tests/
importers would break immediately if the file vanished. This does not change
the classification, because "delete" in this packet's destination taxonomy
is a scheduled-removal category, not "delete today" — the same reading a
peer worker applied to `daedalus.orchestrate` (also blocked on live callers,
also filed toward removal rather than a permanent home). The actionable
implication is: before this file is deleted, its 6 callers migrate to
`daedalus.runtimes.providers.token_policy` directly (a mechanical rename at
each of the 6 sites named above), and `tests/runtimes/test_provider_helper_hierarchy.py`'s
own facade-equivalence test is retired alongside it.

## Boundary-rule verdict after the move

`token_policy.py` currently sits at the flat `daedalus.` root, not under
`daedalus.kernel`/`daedalus.spine`/`daedalus.twin`/`daedalus.runtimes`, so it
is **N-A-not-a-rule-source** for direction (a) both today and under its
proposed `delete` destination (it never becomes a rule source; it ceases to
exist).

(b) reverse direction — **CLEAN**, per the lead's positive-controlled
measurement: no file under `daedalus/kernel`, `daedalus/spine`,
`daedalus/twin`, `daedalus/runtimes` imports any of the five packet modules
at any AST scope, and the complete flat-module import set of those 142
layer-files does not include `token_policy`. Attributed to the lead.

Hypothetical (a), if this file's single import had to survive under a
rule-source layer instead of being deleted: its only import,
`daedalus.runtimes`, is explicitly named in `forbidden_target_prefixes` for
**all three** of `kernel-no-outer-layers`, `spine-no-outer-layers`, and
`twin-no-outer-layers` — so it would be **REFUSED**
(`daedalus/token_policy.py:3`) under every one of them. It does not import
`daedalus.gates` at any scope, so `runtimes-no-gates` is N/A regardless.

One-line verdict: **N-A-not-a-rule-source** today (destination: delete,
pending caller migration); would be **REFUSED** (`daedalus.runtimes` line 3)
under kernel, spine, and twin alike — which is itself further evidence this
file's only sane fate is retirement, not relocation into a rule-bound layer.

## Dead-code signals

Not dead, but explicitly transitional. Zero importers would have been a
"genuinely retirable" signal per the packet's own worked comparison
(`mission_control`, zero importers, no `__main__` guard, cleaner delete
candidate) — this module has 6 live importers instead, so it sits on the
opposite side of that comparison: a registered shim that is *not yet* safe
to remove. Its docstring ("Compatibility facade for runtime-owned provider
token policy") explicitly promises nothing beyond re-export and names no
reader obligation of its own — the obligation lives on the *target* module
instead. Chased one hop on both daedalus/ importers:
`daedalus/providers/claude_cli.py:56` uses `trim_paths` inside a live
provider adapter, and `daedalus/kairos/orchestrate.py:13` uses
`MAX_TODO_CHARS`/`trim_paths`/`trim_text` inside the orchestration module a
peer worker already classified as part of the live `ikarus_*`/`kairos`
orchestration family — both are real, exercised call sites, not further
unwired layers.

## Confidence

High. Importer/import counts match the lead's precomputed numbers exactly
(6 total, 0 deferred; profile `{runtimes}`, 0 third-party), the shim-registry
entry is an exact, unambiguous match (also independently confirmed by peer
worker `flat-dossiers-b`), and the removal-criterion source-audit half was
directly falsified by measurement (6 remaining legacy importers). What would
raise it further: an actual wheel-import and pickle-identity audit, which is
out of scope for this grep-based pass and is named as unverified rather than
assumed.
