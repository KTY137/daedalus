# daedalus/preservation.py

## Identity

`C:/Users/Administrator/daedalus/daedalus/preservation.py`, 632 lines. A
pure, offline fact-preservation tripwire for prose (`.md`/`.rst`/`.txt`)
rewrites: extracts fact-bearing artefacts (code spans, links, paths,
numbers, emphasis, technical terms) from a before/after text pair and
reports which ones vanished.

## Importers (MEASURED)

Scope: `daedalus`, `tests`, `tools` only (git-tracked); `.claude/worktrees/agent-*/`
excluded. Searched `from \.+preservation`, `from daedalus.preservation`,
`from daedalus import ...preservation...`, `import daedalus.preservation`
across the whole repo (module name has no collision with a nested
`preservation.py`, confirmed by `Glob daedalus/**/preservation.py` = only
`daedalus/preservation.py`).

**daedalus/ — 1 site**: `daedalus/verifier.py:23`
`from .preservation import check_preservation, is_prose_path` — module
level, not deferred.

**tests/ — 1 site**: `tests/test_preservation.py:19`
`from daedalus.preservation import (` — module level.

**tools/ — 0 sites.**

Total = 2, 0 deferred. Matches the lead's precomputed count
(`preservation 2 total = 1 daedalus/ + 1 tests/ + 0 tools/; 0 deferred`)
exactly — no disagreement.

Dynamic/string references: no `importlib`, `__import__`, console-script, or
`python -m` reference to `preservation` found anywhere in the scoped tree.

## Imports (MEASURED)

Module-level: stdlib only — `re`, `dataclasses (dataclass, field)`. No
daedalus imports at all, no third-party, no deferred imports (the whole
632-line file has zero function-local `import` statements — confirmed by
reading the file in full). Matches the lead's outbound profile
(`preservation -> {} (NO daedalus imports at all); 0 third-party; 0
deferred`) exactly. The module's own docstring makes the same claim
explicitly: "This module is pure and offline: two strings in, findings
out. It performs no I/O, spawns nothing, and reaches no network or model."

## What it does

Projects markdown into a markup-stripped, whitespace-collapsed comparison
space, extracts seven classes of fact-bearing artefact (inline code,
fences, links, paths, table cells, emphasis, technical terms) plus numbers
and headings from the before-text, and reports every one that did not
survive into the after-text as `LOST` (the only blocking severity) or one
of five softer, non-blocking severities. It is deliberately a
one-directional deletion detector, not a correctness or meaning checker —
its own docstring runs to ~150 lines enumerating exactly what it cannot
catch. 632 lines (of which roughly the first third, lines 1-146, is the
docstring).

## Proposed destination

**foundation.**

Argument: zero daedalus imports of any kind, explicitly self-described and
verified-by-reading as pure/offline (two strings in, findings out — no I/O,
no subprocess, no model call). That is a stronger foundation claim than
most of the current foundation set (e.g. `atomic` does real filesystem
I/O; `preservation` does none). Small, single-purpose, freestanding
algorithm library — the textbook shape for a leaf.

Counter-argument (strongest): it has exactly **one** daedalus/ importer
(`verifier.py`) for exactly **one** purpose (the prose branch of the
offload-cascade's quality gate), so "foundation" implies a generality this
module has never been asked to provide — it could equally be read as a
private submodule of `verifier`/orchestration rather than a shared leaf.
This loses on the letter of the steer's own definition: foundation "today
means the leaf-utility set" by dependency shape, not by import-count
breadth, and the task explicitly says peer workers already classified
single/few-consumer modules (`skills`, `text_integrity`) as foundation, so
low fan-in does not disqualify it. Colocating it with `verifier` under
orchestration would also entangle a zero-dependency pure function library
with a module that reaches into `runtimes`/`spine`, which is the wrong
direction — `preservation` should be *easier* to depend on than `verifier`,
not bundled with its heavier import surface.

## Boundary-rule verdict after the move

- **kernel-no-outer-layers**: (b) CLEAN, vacuous — 0 matches for
  `preservation` under `daedalus/kernel` (spot-checked directly). (a) N/A —
  not a rule source.
- **runtimes-no-gates**: (b) CLEAN, vacuous (0 matches under
  `daedalus/runtimes`). (a) N/A.
- **spine-no-outer-layers**: (b) CLEAN, vacuous (0 matches under
  `daedalus/spine`). (a) N/A.
- **twin-no-outer-layers**: (b) CLEAN, vacuous (0 matches under
  `daedalus/twin`). (a) N/A — and moot regardless, since `preservation`
  imports nothing at all, so it could never trip a denylist/allowlist
  refusal wherever it landed.

One-line verdict: **CLEAN** (vacuous; not a rule source; imports nothing
that could ever be refused).

Foundation caveat: moving `preservation` to `daedalus.foundation.preservation`
takes it off the kernel/spine flat-name allowlists — but this only matters
if a kernel/spine file ever imports it directly, and none does today (its
sole importer, `verifier`, is itself not in kernel/spine/twin/runtimes).
Since `preservation` imports nothing, the foundation move creates no new
*outbound* refusal either. Flagged for the future packet that decides
`verifier`'s own destination, since if `verifier` ever lands in kernel/spine
it would need `daedalus.foundation.preservation` added to that layer's
allowlist — a fact worth recording now rather than rediscovering later.

## Dead-code signals

**Main event for this module.** Zero importers would be a finding; one
importer is a *near-miss* of one, so the question the steer poses —
"is `verifier` itself live?" — is decisive.

Chased one hop: `daedalus/verifier.py` is imported by `daedalus/offload.py:32`
(`from .verifier import (DEFAULT_TEST_TIMEOUT_S, VerifyResult, ...`),
module-level, not deferred. `offload.py` is itself demonstrably live: it is
imported module-level by `daedalus/core.py:?` (via `from . import metrics`
neighbor evidence) and, more directly, `daedalus/cli.py` wires the
`daedalus selftest` and offload-adjacent commands through it (see
`selftest.py`'s own `from .offload import offload` at line 126), and 15+
test files exercise it directly (`test_cascade.py`, `test_fake_offload.py`,
`test_hardening.py`, `test_offload_*` — a whole test-file family named
after it). `verifier.py`'s own docstring states its purpose plainly: "Before
a local-model result is *accepted*, it must pass cheap deterministic
checks. This is what turns risk-tier routing into a real FrugalGPT
cascade..." — a promised reader (the offload cascade) that does in fact
read it.

Conclusion: `preservation` + `verifier` are **not** a dead island.
`preservation` is load-bearing: it is the fact-preservation check
`verifier._prose_check` runs on every prose (`.md`) write in the local-model
offload write lane, and that lane is live and tested.

## Confidence

High. Importer/import counts match the lead's precomputed numbers exactly
(2 total, 0 deferred); purity claim was verified by reading the entire
632-line file rather than trusting the docstring; the one-hop liveness
chase (`verifier` → `offload` → `cli.py`/tests) was confirmed with direct
greps, not inferred from naming alone.
