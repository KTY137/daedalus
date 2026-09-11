# daedalus/metrics.py

## Identity

`C:/Users/Administrator/daedalus/daedalus/metrics.py`, 99 lines. The
silent-escalation alarm: an append-only JSONL log of every offload routing
outcome (offloaded / escalated / would-offload), plus a `summary()` that
computes the fallback rate and trips an alarm when offloadable work keeps
escaping to Claude.

## Importers (MEASURED)

Scope: `daedalus`, `tests`, `tools` only; `.claude/worktrees/agent-*/`
excluded. **Namespace-collision warning, MEASURED**: a naive substring/word
grep for `metrics` produces false positives, because two *other*,
unrelated `metrics.py` modules exist in this tree —
`daedalus/structcore/metrics.py` and `daedalus/wiki/metrics.py`
(`Glob daedalus/**/metrics.py` → three files). `daedalus/structcore/index.py:51`
(`from .metrics import lizard_available`) and
`daedalus/structcore/perfile.py:24` (`from .metrics import file_metrics`)
resolve to `daedalus.structcore.metrics`, not this file — their `.`
is the `structcore` package. `daedalus/wiki/__main__.py:115`
(`from . import metrics`) similarly resolves to `daedalus.wiki.metrics`.
All three were excluded after confirming the relative-import package
context; none is a true importer of `daedalus/metrics.py`. This is the same
species of scope trap the task called out for `.claude/worktrees/`, just
inside the tracked tree via package-relative-import ambiguity rather than a
duplicated checkout — worth flagging since a naive grep-based importer
count for `metrics` would silently overcount by 3.

**daedalus/ — 3 sites** (matches the lead's count exactly, once the above
false positives are excluded): `daedalus/cli.py:1153`
(`from .metrics import main as m; m()`, inside `elif cmd == "metrics":`,
**deferred**), `daedalus/core.py:14` (`from . import metrics`, module
level — `core.py` is itself top-level `daedalus/`, so this correctly
resolves to `daedalus.metrics`), `daedalus/offload.py:28`
(`from . import metrics`, module level, same top-level-package
justification).

**tests/ — 15 sites** (matches the lead's count exactly): all via
unambiguous absolute `from daedalus import metrics` / `from daedalus
import ..., metrics, ...` — `test_cascade.py:6`, `test_codex_provider.py:17`,
`test_drafts.py:14`, `test_era1_robustness.py:19`, `test_fake_offload.py:16`,
`test_hardening.py:22`, `test_offload_automint.py:36`,
`test_offload_slice_context.py:29`, `test_offload_unleased_planner.py:33`,
`test_offload_write_failclose.py:26`, `test_parallel_dispatch.py:17`,
`test_repair_blast_radius_write.py:32`, `test_semantic_route_wired.py:714`
(**deferred**, inside a function), `test_verify_test_budget.py:35`,
`test_write_guard_e2e.py:31`.

**tools/ — 0 sites.**

Total = 3 + 15 + 0 = 18, of which 2 are deferred
(`daedalus/cli.py:1153`, `tests/test_semantic_route_wired.py:714`) —
matches the lead's precomputed count (`metrics 18 total = 3 daedalus/ + 15
tests/ + 0 tools/; 2 deferred`) exactly, once the namespace-collision false
positives are excluded.

Dynamic/string references: no `importlib`, `__import__`, console-script, or
`python -m` reference to this `metrics` module found in the scoped tree
(the `daedalus metrics` CLI subcommand reaches it only via the ordinary
deferred import above, `cli.py:1153`).

## Imports (MEASURED)

Module-level (lines 12-18): stdlib only — `argparse, json, threading,
datetime (datetime, timezone), pathlib.Path`. No daedalus imports, no
third-party, and no deferred/function-scope imports anywhere in the file
(confirmed by reading the full 99 lines — every import is at module top).
Matches the lead's outbound profile (`metrics -> {} (NO daedalus imports at
all); 0 third-party; 0 deferred`) exactly.

## What it does

`record()` appends one JSON row (provider, action, owner, risk, eligible,
note, timestamp) to `memory/offload_metrics.local.jsonl` under a thread
lock (Windows append is not guaranteed atomic, per the module's own
comment); `summary()` reads the log back and computes offloadable/offloaded/
fell-back counts and a fallback rate, tripping `alarm` above a 50% fallback
rate once 5+ samples exist; `main()` is a small CLI printer for
`daedalus metrics`. 99 lines.

## Proposed destination

**foundation.**

Argument: zero daedalus imports (pure leaf by the same test as
`preservation`/`projects`), small (99 lines), and a self-contained
metering primitive — record + summarize + alarm over one append-only log —
consumed by three separate top-level production modules (`cli.py`,
`core.py`, `offload.py`) and 15 test files, none of which are structurally
coupled to it beyond "call `record()`" / "call `summary()`". That is the
same broadly-depended-upon-leaf shape the steer already accepted for
`projects` and that precedent (`skills`, `text_integrity`) already
establishes for foundation being domain-specific, not just generic-utility.

Counter-argument (strongest): it is not a generic reusable utility the way
`atomic`/`budget`/`storage` are — its entire vocabulary
(`provider`, `action=offloaded/escalate_to_claude/...`, "silent-escalation
alarm") is specific to the offload routing cascade, so it reads more like a
small orchestration-telemetry sidecar that happens to have no dependencies,
and could instead sit next to `offload` in `orchestration`. This loses on
the same dependency-shape argument the steer applies uniformly: destination
here is being decided by *what a module depends on and who depends on it*,
not by whether its vocabulary is domain-flavored — `sensitivity` and
`limit_policy` (already foundation) are just as domain-specific to policy
enforcement, and `metrics` is strictly *more* independent than either
(zero imports at all, vs. their internal cross-references). Splitting one
99-line, zero-dependency module across a layer boundary because of its
vocabulary rather than its coupling would be the inconsistent choice.

## Boundary-rule verdict after the move

Direction (b), all four rules: **CLEAN, vacuous** — spot-checked directly,
0 matches for `metrics` under `daedalus/kernel`, `daedalus/spine`,
`daedalus/twin`, `daedalus/runtimes` (and this check is itself
namespace-collision-safe: the same relative-import verification applied
above confirms none of those directories contains a competing `metrics.py`
that could produce a false "clean").

Direction (a): moot — `metrics.py` imports nothing at all (module-level or
deferred), so wherever it hypothetically landed, it has no outbound edges
that any of the four rules' denylist/allowlist machinery could ever refuse.
It does not import `daedalus.gates` (trivially true, since it imports no
daedalus module whatsoever).

One-line verdict: **CLEAN** (vacuous in direction (b); direction (a) is
structurally unreachable since the module has zero imports to refuse).

Foundation caveat: same as `preservation` and `projects` — moving to
`daedalus.foundation.metrics` takes it off the kernel/spine flat-name
allowlists, but this bites nothing today since no kernel/spine/twin/runtimes
file imports `metrics` (verified above), and it costs the move nothing on
`metrics`'s own outbound side since it imports nothing to begin with.

## Dead-code signals

Not applicable — not remotely dead. 3 daedalus/ production call sites
(`cli.py`, `core.py`, `offload.py`) plus 15 test files is a broad,
confirmed-live importer set; the module's own docstring names its purpose
plainly ("the most load-bearing practitioner warning
(docs/IMPROVEMENTS_RESEARCH.md): a broken verifier can quietly route ~90%
of traffic to the expensive model with no error and no alert...") and both
`core.py:395`/`core.py:899` (`metrics.summary()`, feeding a dashboard) and
`daedalus/cli.py:1153` (a documented `daedalus metrics` subcommand,
`cli.py:8`) are promised, confirmed readers.

## Confidence

High. Importer/import counts match the lead's precomputed numbers exactly
only *after* excluding a genuine grep false-positive from the
`daedalus/structcore/metrics.py` and `daedalus/wiki/metrics.py` namespace
collision — this was independently discovered (not hinted at in the task
brief) and confirmed by `Glob` plus reading each false-positive site's
surrounding package context, so it is measured, not assumed. Outbound
purity (zero imports) was confirmed by reading the entire 99-line file.
