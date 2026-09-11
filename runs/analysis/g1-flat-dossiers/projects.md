# daedalus/projects.py

## Identity

`C:/Users/Administrator/daedalus/daedalus/projects.py`, 424 lines. The
project registry: a JSON-row-per-project store under `projects/*.json`,
providing atomic register/load/list/rewrite and canonical-root resolution.

## Importers (MEASURED)

Scope: searched `daedalus`, `tests`, `tools` only (git-tracked trees), via
regex import-statement grep (`from \.+projects`, `from daedalus.projects`,
`from daedalus import ...projects...`, `import daedalus.projects`), not the
generic substring `projects` (which also matches the `projects/` data
directory, docstring prose, and unrelated locals such as
`langgraph_adapter.py`'s `projects` parameter — all excluded below).
`.claude/worktrees/agent-*/` copies were not searched.

**daedalus/ — 29 sites** (matches the lead's AST count exactly):

| file | lines | deferred? |
|---|---|---|
| bootstrap_prompt.py | 8 | no |
| config.py | 284 | yes (inside a function) |
| cli.py | 113, 178, 225, 282, 366, 457, 1023 (7 sites) | yes, all 7 (each inside a CLI-subcommand handler) |
| control_plane.py | 15 | no |
| desktop_runtime.py | 38 | no |
| enforce.py | 9 | no |
| editor_context.py | 26 | no |
| core.py | 16 | no |
| file_bridge.py | 23 | no |
| ikarus_chat.py | 14 | no |
| hierarchy.py | 7 | no |
| ikarus_os.py | 96 | no |
| eval/tasks.py | 90 | no |
| kairos/scheduler.py | 161 | yes (inside a function) |
| kairos/orchestrate.py | 10 | no |
| interfaces/http/read.py | 450 | yes (inside a function) |
| interfaces/http/effects.py | 24 | no |
| status.py | 49 | no |
| web_api.py | 37, 72, 93, 119 (4 sites) | 37 module-level; 72/93/119 deferred |
| token_monitor.py | 34 | no |

Sum = 1+1+7+1+1+1+1+1+1+1+1+1+1+1+1+1+1+1+4+1 = **29**, of which **13 are
deferred** (config.py:284, cli.py×7, kairos/scheduler.py:161,
interfaces/http/read.py:450, web_api.py×3) — matches the lead's 29/13 exactly.

Deferred reason, spot-checked: every deferred site sits inside a lazily-run
CLI-subcommand handler (`cli.py`) or a request/scheduler handler
(`web_api.py`, `interfaces/http/read.py`, `kairos/scheduler.py`,
`config.py`) — consistent with keeping module import cost off the hot path
of `daedalus/__init__` / process startup, not cycle-avoidance (nothing in
`projects.py` imports back up into any of these callers — its own imports
are only `.atomic`).

**tests/ — 9 sites** (matches the lead's count exactly):
`test_agent_env.py:10`, `test_cascade.py:9`, `test_codex_provider.py:26`,
`test_desktop_runtime.py:17`, `test_editor_context.py:9`,
`test_ide_project_authorization.py:9`, `test_project_registration.py:17`,
`test_project_row_rewrite.py:25`, `test_registry_shadowing.py:39`.

Note: `test_project_registration.py:29` and `test_project_row_rewrite.py:37`
also textually match `from daedalus import projects` / `... hierarchy,
projects` but are **not** real AST-level imports of this file — both sit
inside a `r"""..."""` triple-quoted string constant
(`_PROCESS_REGISTRATION_RACER` / `_PROCESS_ROW_REWRITE_RACER`) that is a
*subprocess script body*, spawned as a child Python process, not parsed as
an import by this file's own AST. Verified by reading both files: the string
literal opens at `test_project_registration.py:23` and
`test_project_row_rewrite.py:31` respectively and contains its own nested
`from daedalus import projects` as script text. This is exactly why the
lead's AST-based count (9) is lower than a naive textual grep (11) — no
disagreement with the lead once this is accounted for.

**tools/ — 0 sites.** Confirmed by grep; matches the lead.

Dynamic/string references: searched for `importlib`, `__import__`, and
`python -m` / console-script references naming `projects` — none found.
`pyproject.toml [project.scripts]` defines only `daedalus =
"daedalus.cli:main"` and `daedalus-chip = "daedalus.chip_design.cli:main"`;
neither names `projects` directly (it is reached transitively through
`cli.py`'s deferred imports above).

## Imports (MEASURED)

Module-level (all in `daedalus/projects.py:1-18`): stdlib
`hashlib, json, ntpath, os, posixpath, re, unicodedata, pathlib
(Path/PurePosixPath/PureWindowsPath), typing (Any, Callable)`; one
daedalus import — `.atomic` (`ExclusiveFileLock, FileLockUnavailable,
publish_bytes_once, write_text_atomic`), line 13-18.

Deferred/function-scope: **none**. Every import in this file is at module
top. daedalus.* count: 1 module-level (`atomic`), 0 deferred. Third-party:
0. Matches the lead's outbound profile (`projects -> {atomic}; 0
third-party; 0 deferred`) exactly.

## What it does

Implements a lock-serialized, content-addressed JSON project registry
(`projects/<name>.json`) with canonical-root identity so the same directory
can never be registered twice under different names. Provides
`register_project`, `load_project`, `list_projects`,
`rewrite_project_team`, and `resolve_registered_project_root` /
`resolve_repo_root` as the sole authorization seam that turns a registry row
into a filesystem path for effectful callers. 424 lines.

## Proposed destination

**foundation.**

Argument: widest-used module in this half (29 daedalus/ call sites, second
only to true primitives) and its only daedalus dependency is `.atomic`,
itself already foundation — textbook leaf shape: broadly depended-upon,
depends on nothing but a lower foundation module. It is stateful (owns the
`projects/` directory and a file lock) but so is `storage`, already in the
foundation set.

Counter-argument: it is a *registry with an authorization seam*
(`resolve_registered_project_root` is explicitly documented as "the
authorization seam for callers which are about to expose a checkout to an
effectful local service"), which smells more like `spine` or `kernel`
(policy-adjacent) than an inert leaf utility. This loses because the module
performs no policy decision itself — it only resolves a name to a path and
refuses ambiguous/foreign/stale rows; the actual authorization decision
(what that path may be used for) is made by every one of its 29 callers,
not here. That is exactly the foundation/leaf shape: mechanism, not policy.

## Boundary-rule verdict after the move

Assuming `daedalus.projects` moved to `daedalus.foundation.projects` (or
stayed flat — the caveat below applies either way once it is under
`foundation.`):

- **kernel-no-outer-layers** (source `daedalus.kernel`): (b) direction —
  CLEAN, vacuous: no file under `daedalus/kernel` imports `projects` today
  (spot-checked: grep for the five names under `daedalus/kernel` = 0
  matches; also consistent with the lead's 142-file flat-import-set finding,
  which does not include `projects`). (a) direction — N/A, `projects` is not
  proposed as a kernel/spine/twin/runtimes source, so this rule's
  `source_prefixes` never apply to it.
- **runtimes-no-gates** (source `daedalus.runtimes`): (b) CLEAN, vacuous
  (same check, 0 matches under `daedalus/runtimes`). (a) N/A.
- **spine-no-outer-layers** (source `daedalus.spine`): (b) CLEAN, vacuous
  (0 matches under `daedalus/spine`). (a) N/A.
- **twin-no-outer-layers** (source `daedalus.twin`): (b) CLEAN, vacuous (0
  matches under `daedalus/twin`). (a) N/A.

One-line verdict: **CLEAN** (vacuous in both directions; not a rule source).

Foundation caveat: `projects` imports only `.atomic`, which stays reachable
under `daedalus.foundation.atomic` or flat — either way this does not create
a kernel/spine dependency problem for `projects` itself, since (as shown
above) no kernel/spine/twin/runtimes file imports `projects` today. If a
future kernel/spine file *did* start importing `daedalus.foundation.projects`,
it would be refused (kernel/spine allowlists name only the flat leaf names
atomic/budget/config/limit_policy/primary_tree/sensitivity/storage, not a
`foundation.*` prefix) — worth remembering for whoever wires the first such
caller, but it does not block moving `projects` today.

## Dead-code signals

None — 29 daedalus/ call sites plus 9 test sites is the opposite of a dead
module; it is the busiest importer graph of the five assigned here.

## Confidence

High. Import counts reconcile exactly with the lead's AST numbers once the
two embedded-subprocess-string false positives are excluded (verified by
reading both source files), outbound imports were read directly from the
file (no daedalus imports besides `.atomic`, matching the lead's profile),
and the kernel/spine/twin/runtimes vacuous-clean claim was independently
spot-checked with a direct grep rather than taken purely on trust.
