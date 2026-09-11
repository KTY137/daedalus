# daedalus/decompose.py

## 1. Size and shape

12 lines total (`wc -l daedalus/decompose.py` = 12). Zero classes, zero
function *definitions* — the whole body is one `from`-import statement
re-exporting six names, plus an `__all__` list:

```
daedalus/decompose.py:3   from .kairos.decompose import (
daedalus/decompose.py:4       _ask_model,
daedalus/decompose.py:5       _coerce_item,
daedalus/decompose.py:6       _fallback,
daedalus/decompose.py:7       _parse_subtasks,
daedalus/decompose.py:8       _user_prompt,
daedalus/decompose.py:9       decompose,
daedalus/decompose.py:10  )
daedalus/decompose.py:12  __all__ = ["decompose"]
```

No module-level state/singletons beyond the import binding itself. No
side effect executed at import time other than importing
`daedalus.kairos.decompose` (which its own docstring states is
"import-safe — no network I/O happens at import time, only inside the
call", `daedalus/kairos/decompose.py:12-13`). No file reads, env reads,
registry mutation, network, or path creation at import.

Notable: it re-exports four *private* (underscore-prefixed) names
(`_ask_model`, `_coerce_item`, `_fallback`, `_parse_subtasks`,
`_user_prompt`) in addition to the public `decompose`, but `__all__`
only advertises `decompose`. The private re-exports exist for import
but are not part of the declared public surface.

## 2. What it does

`daedalus/decompose.py` is a 12-line compatibility re-export module that
imports `decompose` (plus five underscore-prefixed helpers) from
`daedalus.kairos.decompose` and republishes them under the legacy
`daedalus.decompose` import path. It contains no logic of its own — it is
purely an alias/facade over the real implementation, which lives in
`daedalus/kairos/decompose.py` and turns one objective into a bounded list
of scoped subtasks (local-model primary path, deterministic per-path
fallback). Its own docstring states this directly: `"""Compatibility
wrapper for :mod:`daedalus.kairos.decompose`."""` (line 1).

## 3. Who imports it (MEASURED)

**TOTAL: 0 importers of `daedalus.decompose` anywhere in the git-tracked
tree**, in any import form (`from daedalus.decompose import`,
`from daedalus import decompose`, `import daedalus.decompose`,
`from .decompose import` at the `daedalus/` package level,
`from . import decompose`, `importlib.import_module("daedalus.decompose")`,
or the bare string `"daedalus.decompose"` as a runtime target).

Commands run (restricted to tracked files via `git grep`):

```
git grep -n -E "from daedalus\.decompose|from daedalus import[^;]*\bdecompose\b|import daedalus\.decompose|from \.decompose import|from \. import[^;]*\bdecompose\b|importlib\.import_module\([\"']daedalus\.decompose" -- "*.py"
git grep -n '"daedalus.decompose"' -- "*.py" "*.json" "*.md" "*.toml"
```

The only import-form hit anywhere is `daedalus/kairos/scheduler.py:454`
(`from .decompose import decompose`) — but this is a **relative import
inside the `daedalus/kairos/` package**, so `.decompose` there resolves
to `daedalus.kairos.decompose` (the real implementation), NOT
`daedalus.decompose` (this shim). It is a false-positive match on the
bare word `decompose`, not a shim caller. Cross-checked against
`daedalus/build.py:63`, which imports the real target directly:
`from .kairos.decompose import decompose`.

The bare-string form `"daedalus.decompose"` appears in exactly three
tracked non-code locations, none of them a runtime caller:
- `docs/architecture/shim-registry.json:20` — the shim's own registry
  entry (self-declaration, not a caller).
- `docs/inventory/2026-08-21/preruling/reachability.json:307` and
  `:16702` — a historical inventory snapshot (predates the shim
  registry's 2026-08-31 baseline) that already recorded
  `daedalus.decompose` as one of 101 modules with zero reachability
  from any entrypoint.

Per-layer breakdown: N/A (zero importers in any layer).

This is consistent with the AST census supplied in the task prompt (0
importers tree-wide) and with the already-established fact that real
consumers bypass the shim and import `daedalus.kairos.decompose` directly
(`daedalus/build.py:63`, `daedalus/kairos/scheduler.py:454`).

## 4. What it imports (MEASURED)

Exactly one target, module-level:

| Import | Line | Form | Target layer |
| --- | --- | --- | --- |
| `from .kairos.decompose import (_ask_model, _coerce_item, _fallback, _parse_subtasks, _user_prompt, decompose)` | `daedalus/decompose.py:3` | MODULE-LEVEL | `daedalus.kairos` — this is the module's own re-export target; `kairos` is an existing package (owner "orchestration" per shim-registry.json:21). |

No third-party imports. No stdlib imports beyond what `daedalus.kairos.decompose` itself pulls in transitively.

## 5. Proposed destination

**keep-flat-as-registered-shim** — do not move it, and "move" is not
even a well-formed answer for this file. Confidence: **high**.

Argument: `daedalus.decompose` is a REGISTERED SHIM
(`docs/architecture/shim-registry.json:20-27`, `import_path
daedalus.decompose`, `owner: orchestration`, `kind: module_reexport`,
`targets: ["daedalus.kairos.decompose"]`). A shim's import path *is* its
contract — the entire reason it exists is to keep the string
`daedalus.decompose` resolvable for any caller that has not migrated to
`daedalus.kairos.decompose`. Relocating the file to `daedalus/kairos/`
(where its target already lives), to `daedalus/orchestration/`, or
anywhere else would either delete that import path outright (breaking
the compatibility contract without going through the registry's own
removal criteria) or require yet another re-export shim at the new
location pointing back to `daedalus.kairos.decompose` — which is not a
"move," it is deleting the current shim and creating a materially
identical new one, with no measured benefit.

The two real answers for this file are only:
1. **keep-flat-as-registered-shim** (current state, until removal
   criteria are met) — recommended now, given the open item in
   §7 below.
2. **delete** — only once every named audit is satisfied per the
   registry's own removal criteria (see §7). Six of six named audits
   currently show PASS (zero callers), but "for one supported release"
   is UNVERIFIED (see §7) — this repository has no CHANGELOG or release
   cadence marker; `pyproject.toml:7` still reads `version = "0.1.3"`
   with no evidence of a version bump since the file was last touched
   (2026-07-28, commit `ccb17634`).

What would change my mind: an owner decision that "one supported
release" has elapsed (or that the concept does not apply to this
pre-1.0, continuously-deployed repo), which would make `delete` the
correct call under the registry's own stated criteria — but that is an
owner/registry-maintenance decision, not something this static audit can
resolve on its own.

There is no split-boundary question here — the file is a single
`import`/`__all__` statement, not two things fused.

## 6. Boundary-rule check after the move

There is no move (see §5), so (a)/(c)/(d) are evaluated against the
**current, flat** location as a sanity check, and (b) is evaluated as
written.

**(a) If moved to `daedalus.kairos` (the only plausible non-shim
destination, since that's where its target already lives): would any of
its own imports be refused?** No. `daedalus.kairos` is not a
`source_prefix` in any of the four import-boundaries.json rules
(`kernel-no-outer-layers`, `runtimes-no-gates`, `spine-no-outer-layers`,
`twin-no-outer-layers` all key off `daedalus.kernel`, `daedalus.runtimes`,
`daedalus.spine`, `daedalus.twin` respectively — `daedalus.kairos` is
unconstrained as a source). Its one import,
`.kairos.decompose` → `daedalus.kairos.decompose`, is an intra-package
edge and would not cross any forbidden-target check either, since no
rule names `daedalus.kairos` as a forbidden target for any source that
would house this file.

**(b) Does any current rule name this module by prefix?** No. Grepped
`docs/architecture/import-boundaries.json` for `decompose` — zero hits.
Neither `daedalus.decompose` nor `daedalus.kairos.decompose` appears in
any `source_prefixes`, `forbidden_target_prefixes`, or
`allowed_target_prefixes` list. Nothing breaks and nothing is silently
un-forbidden by any move of this file — the boundary contract is simply
silent on it in every direction.

**(c) If it lands in kernel/spine/twin: which flat imports would be
refused?** N/A — proposed destination is keep-flat-as-registered-shim,
not kernel/spine/twin, and there is no scenario in §5 that lands it
there (its only import target, `daedalus.kairos`, is itself outside all
three of those allowlists, e.g. `kernel-no-outer-layers` forbids
`daedalus.kairos` explicitly at `import-boundaries.json:30`). So this
file could never legally move into `daedalus.kernel`, `daedalus.spine`,
or `daedalus.twin` while still importing `daedalus.kairos.decompose` —
another concrete reason it stays flat/shim rather than being reassigned
to one of the three constrained layers.

**(d) Does any rule constrain `daedalus.interfaces` as a source?** No —
confirmed by inspection of all four rules in
`docs/architecture/import-boundaries.json`: none uses
`daedalus.interfaces` as a `source_prefixes` entry. This module is not a
candidate for an `interfaces/*` destination in any case (it has no CLI,
HTTP, bridge, or desktop surface — it re-exports a pure decomposition
function), so the "does an interfaces/* move launder a forbidden prefix"
question does not apply here.

## 7. Dead-code signals

Per-criterion table against the shim registry's own removal criteria
("Source, runtime-string, wheel, documentation, effect-registry, and
pickle audits show no caller for one supported release",
`docs/architecture/shim-registry.json:26`):

| # | Audit | Result | Evidence |
| --- | --- | --- | --- |
| 1 | Source | **PASS** (no caller) | `git grep` across all import forms tree-wide (§3) finds zero callers of `daedalus.decompose`; the one textual hit (`kairos/scheduler.py:454`) resolves to `daedalus.kairos.decompose`, not this shim. |
| 2 | Runtime-string | **PASS** (no caller) | `git grep '"daedalus.decompose"'` across `*.py`/`*.json`/`*.md`/`*.toml` finds only the shim registry's own self-declaration and two historical inventory-JSON snapshots (§3); zero registrations in `daedalus/spine/effect_boundary.py` (`git grep -n "decompose" -- daedalus/spine/effect_boundary.py` → no output) and zero `"daedalus.decompose:"` (colon-suffixed CLI-target form, per the `daedalus.arch_memory:main` pattern named in the task) anywhere tracked. |
| 3 | Documentation | **PASS** (no caller/promise) | `git grep -n -i "decompose" docs/ -- "*.md"` returns zero hits naming `daedalus.decompose` or promising it as a reader/entrypoint. (`daedalus.kairos.decompose` and generic "decomposition" prose are out of scope for this shim's own path.) |
| 4 | Wheel/packaging | **PASS**, with a caveat | `pyproject.toml` `[tool.setuptools.packages.find]` uses `include = ["daedalus*"]`, `exclude = ["tests*", "tools*"]` (lines ~78-80) and there is no `[project.scripts]` entry referencing `decompose` (`grep -n -i "decompose" pyproject.toml` → no output). The shim FILE itself still ships as part of the `daedalus*` wildcard (expected until actual deletion), but no co-shipped caller exists in the packaged tree. |
| 5 | Effect-registry | **PASS** (no caller) | `git grep -n "decompose" -- daedalus/spine/effect_boundary.py` → zero hits; no registered CLI/effect target names this shim. |
| 6 | Pickle | **PASS** (no reference found) | `git grep -rn "pickle.dumps\|pickle.loads\|\.pickle" -- "*.py" \| grep -i decompose` → zero hits. Searched the whole tracked tree for pickle-adjacent code co-occurring with "decompose"; found nothing. |

**Open item, UNVERIFIED**: the registry's phrase "for one supported
release" cannot be evaluated. This repository has no `CHANGELOG`, no
git tags found for release boundaries, and `pyproject.toml:7` shows a
single pre-1.0 `version = "0.1.3"` with no visible bump history tied to
this file (last touched 2026-07-28, commit `ccb17634`, while the shim
registry's own baseline revision is dated 2026-08-31). I cannot
determine from the tree alone whether a "supported release" boundary
has been crossed since the shim was established — that is an
owner/process judgment, not a fact this static audit can produce.

Also note: unlike sibling entries in the same registry (e.g.
`daedalus.budget`, `daedalus.providers`), this shim's own
`removal_criteria` text does **not** list a monkeypatch audit or an
executable-object audit — I evaluated exactly the six audits it names,
no more.

**Label: REGISTERED-SHIM.** Not CANDIDATE-DELETE: while every audit I
could execute shows PASS (zero callers), the shim's own stated
"one supported release" condition is unverifiable from repository state
alone, and deletion of a registered shim outside its own stated removal
criteria would itself be a drift the registry exists to prevent. What I
searched, exhaustively, for a "promised reader": every `*.md` under
`docs/`, `daedalus/spine/effect_boundary.py`, all `*.json`/`*.toml`
tracked files, and every Python import form tree-wide (commands listed
in §3 and this section). None names `daedalus.decompose` as an active
consumer target — only as a governed, currently-idle compatibility path.
