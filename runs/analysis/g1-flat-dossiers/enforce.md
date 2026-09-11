# daedalus/enforce.py

## 1. Size and shape

119 lines (`daedalus/enforce.py:1-119`). 0 classes, 5 top-level functions
(`_block`, `_replace_or_append`, `_enforce_file`, `enforce_repo`, `main`).
Module-level state: two string constants, `BEGIN`/`END` marker comments
(`enforce.py:12-13`), used to delimit an idempotent managed block inside
`AGENTS.md`/`CLAUDE.md`. No module-level singletons or registries. No
module-level side effects at import — no file reads, env reads, or network
calls happen until `enforce_repo()` or `main()` is actually called; the two
`daedalus.budget` / `daedalus.spine.effect_boundary` imports at
`enforce.py:107-108` are themselves deferred to inside `main()`, so importing
`daedalus.enforce` alone touches nothing effectful. The real side effects
(`Path.write_text`, `Path.mkdir`) live inside `_enforce_file` and
`enforce_repo`, both of which are called functions, not import-time code.

## 2. What it does

`daedalus/enforce.py` writes (or idempotently rewrites, via a
`BEGIN`/`END`-delimited block) a fixed "Daedalus Enforcement" instruction
section into a target repository's `AGENTS.md` and `CLAUDE.md`, telling
Claude/Codex to route delegated work through the harness file bus instead of
direct agent-to-agent messaging. It also writes a `.agentenv/enforcement.json`
state file recording that enforcement is active, the bound project, and the
timestamp. Its CLI entrypoint (`main()`, `enforce.py:101-115`) parses
`--repo-root`/`--project`, resolves the repo root, and — before performing any
write — calls `daedalus.spine.effect_boundary.begin_effect("cli.enforce", ...)`
guarded by `daedalus.budget.process_guard_boundary_decision()`.

## 3. Who imports it (MEASURED)

**TOTAL: 6** importers across the git-tracked tree (bare `git grep`,
restricted to `*.py`), all forms searched: `from .enforce import`, `from
daedalus.enforce import`, `from daedalus import enforce`, `import
daedalus.enforce`, `from . import enforce`, plus the bare runtime string
`"daedalus.enforce"` / `daedalus.enforce:`.

Per-layer breakdown: flat (daedalus/) 2, tests 4, kernel/spine/twin/runtimes/
orchestration/interfaces 0.

Full list, each marked MODULE-LEVEL or DEFERRED (verified by reading the
surrounding function body, not just the grep hit):

| File:line | Form | Scope |
| --- | --- | --- |
| `daedalus/cli.py:1220` | `from .enforce import main as m; m()` | **DEFERRED** — inside the `cmd == "enforce"` branch of the CLI dispatcher function, not module scope. |
| `daedalus/core.py:968` | `from .enforce import enforce_repo` | **DEFERRED** — inside `enforce_harness()`, a called function, not module scope. |
| `tests/test_cli_effect_boundary.py:38` | `from daedalus.enforce import main` | **DEFERRED** — inside `test_enforce_refuses_fail_closed_without_the_contract`. |
| `tests/test_cli_effect_boundary.py:50` | `from daedalus.enforce import main` | **DEFERRED** — inside `test_enforce_runs_on_the_valid_chain`. |
| `tests/test_cli_effect_boundary.py:642` | `from daedalus.enforce import main` | **DEFERRED** — inside `test_the_valid_chain_mints_a_real_process_guard_decision`. |
| `tests/test_comms.py:19` | `from daedalus.enforce import BEGIN, END, enforce_repo` | **MODULE-LEVEL** — top of `tests/test_comms.py`, outside any function. |

5 of 6 edges are DEFERRED (function-scope); only the one test-file import is
module-level. This matches the independent AST cross-check given in the task
brief exactly (6 total, 2 flat + 4 tests, 5/6 deferred).

Runtime-string registration: `daedalus/spine/effect_boundary.py:593,597`
registers `target="daedalus.enforce:main"` and
`anchors=(GuardAnchor("daedalus.enforce:main", "begin_effect"),)` inside the
`EntrypointSpec` with `id="cli.enforce"` (`effect_boundary.py:591-599`). This
is not a Python import edge but it is a load-bearing dynamic reference: the
effect boundary's central-start machinery resolves and re-imports
`daedalus.enforce:main` by string at entrypoint-dispatch time, independent of
the static `git grep` importer count above.

## 4. What it imports (MEASURED)

MODULE-LEVEL:
- `daedalus.config` — `enforce.py:8` (`from .config import init_repo`), target layer **foundation** (declared FOUNDATION).
- `daedalus.projects` — `enforce.py:9` (`from .projects import resolve_repo_root`), target layer **flat/unclassified** (not in the declared FOUNDATION list, not in the SCC-owned list; an ordinary flat `daedalus/` module).

DEFERRED (both inside `main()`, `enforce.py:107-108`):
- `daedalus.budget` — `enforce.py:107` (`from daedalus.budget import process_guard_boundary_decision`), target layer **foundation** (declared FOUNDATION; also a registered effect/compatibility facade per `shim-registry.json`, but the import itself targets the flat `daedalus.budget` name).
- `daedalus.spine.effect_boundary` — `enforce.py:108` (`from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect`), target layer **spine**.

Third-party: none. Stdlib only: `argparse`, `json`, `datetime`, `pathlib`.

## 5. Proposed destination

**interfaces/cli.** Confidence: **medium-high**.

Argument from measured edges: `enforce.py` is not a policy decider — see
section 2 and the verdict below — it is an effectful **CLI command
implementation**. It has its own `argparse` parser and `main()` entrypoint
(`enforce.py:101-115`), is registered in `effect_boundary.py` with
`surface=Surface.CLI` (`effect_boundary.py:591-600`), and is dispatched from
`daedalus/cli.py`'s `cmd == "enforce"` branch (`cli.py:1219-1220`) exactly
like every other CLI subcommand in that file. Its own imports are a foundation
pair (`config`, `budget`) plus one flat helper (`projects`) plus a deferred
call into `daedalus.spine.effect_boundary` to *consume* the boundary gate —
it does not implement the gate itself. That shape (thin CLI parser + delegate
to a shared foundation/spine service for policy, then perform the write) is
the interfaces/cli pattern, not a kernel/spine primitive.

What would change my mind: if a future packet demonstrates that `enforce.py`
needs to be callable from non-CLI surfaces (e.g. directly from an HTTP
handler or from another kernel/spine module) with the same guarantees, it
would argue for extracting `enforce_repo()` (the effectful core, minus
`argparse`) into a shared service module consumed by both a CLI adapter and
other surfaces — i.e., a split between a thin `interfaces/cli` wrapper
(`main()`, argument parsing) and a lower orchestration/foundation-level
`enforce_repo()`. Nothing measured today shows a second surface calling
`enforce_repo()` directly except `daedalus/core.py:968`'s `enforce_harness()`,
which is itself dispatched only from CLI/API surfaces per its own name — not
enough evidence to force the split now.

## 6. Boundary-rule check after the move

(a) Moved to `interfaces/cli`: would any of its own imports be REFUSED? **No.**
None of the four authoritative rules (`kernel-no-outer-layers`,
`spine-no-outer-layers`, `twin-no-outer-layers`, `runtimes-no-gates`) names
`daedalus.interfaces` as a `source_prefix` — only `daedalus.kernel`,
`daedalus.spine`, `daedalus.twin`, `daedalus.runtimes` are constrained
sources. So none of `enforce.py`'s imports (`config`, `projects`, `budget`,
`spine.effect_boundary`) would be mechanically refused for landing under
`daedalus.interfaces.cli`.

(b) Does any CURRENT rule name this module by prefix? **No.** `daedalus.enforce`
does not appear as a `forbidden_target_prefix` or `allowed_target_prefix` in
any of the four rules. Nothing breaks and nothing is silently un-forbidden by
the move, because the module was never named.

(c) **Mandatory analysis — if it lands in kernel/spine/twin instead:** enumerate
every flat module `enforce.py` imports that would be REFUSED for staying flat.
`enforce.py` imports **`daedalus.projects`** at module level (`enforce.py:9`).
`daedalus.projects` is a flat, non-FOUNDATION module — it is absent from
both `kernel-no-outer-layers`' `allowed_target_prefixes` (`atomic, budget,
config, limit_policy, primary_tree, sensitivity, spine, storage, twin`) and
`spine-no-outer-layers`' `allowed_target_prefixes` (`atomic, budget, config,
kernel, limit_policy, mapping, sensitivity, structcore`). If `enforce.py`
moved into `daedalus.kernel` or `daedalus.spine`, its own
`from .projects import resolve_repo_root` edge would become a REFUSED edge
under either rule's allowlist — `daedalus.projects` grants no permission by
omission. Widening either allowlist to admit `daedalus.projects` is exactly
the kind of allowlist growth `tests/test_architecture_boundaries.py::
test_the_allowlists_cannot_grow_quietly` exists to price: it pins allowlist
membership exactly, so admitting `daedalus.projects` requires a reviewed diff
of that pin test, not a silent edit. This is the concrete cost that makes
`interfaces/cli` (unconstrained as a source) the cheaper, correct landing
versus kernel/spine (constrained, and currently refusing this module's own
`projects` dependency).

(d) `daedalus.interfaces` as SOURCE is unconstrained by any current rule — true
here too, as in (a). Does an `interfaces/*` move launder a forbidden prefix
behind an unconstrained one? For `enforce.py` specifically: **no laundering
risk from this module's own imports**, because none of `enforce.py`'s targets
(`config`, `projects`, `budget`, `spine.effect_boundary`) are on any rule's
forbidden list in the first place — there is nothing forbidden here to
launder. The general laundering risk described in the `spine-no-outer-layers`
rationale (a kernel/spine module reaching a forbidden prefix indirectly by
importing an unconstrained `daedalus.interfaces.*` module that itself imports
the forbidden prefix) is a real, documented pattern for *other* modules
(the `daedalus.schemas` facade case cited in that rule's own rationale text),
but `enforce.py` does not sit downstream of any kernel/spine/twin-forbidden
target, so it does not create a new instance of that risk.

(e) N/A — proposed destination is `interfaces/cli`, not `orchestration`.

## 7. Dead-code signals

Not low/zero-importer — 6 measured importers, 1 module-level, 5 deferred, plus
a live dynamic re-registration by string in `effect_boundary.py`. This module
is clearly wired and exercised (three dedicated test functions in
`tests/test_cli_effect_boundary.py` covering both the fail-closed-without-
contract path and the valid chain, plus `tests/test_comms.py`'s
`test_enforce_repo_appends_managed_blocks`). Searched: all import forms above,
`git grep` for the bare string `"daedalus.enforce"` and `daedalus.enforce:`
(hit only in `effect_boundary.py`'s own registration, which is the promised
dynamic reader), git log (`bcc0feaf` "feat(g0): port the central-wiring
mission -- 58 doors gained real gates, 12 remain with reasons" is the commit
that wired `enforce.py`'s `main()` to call `begin_effect`; `46a4d45b` is the
file's origin as part of the `agent_env` → `daedalus` rebrand). No consumer
was removed since.

**Label: LIVE.**

**Policy-decider-vs-effect-gate verdict (the load-bearing question):**
`enforce.py` is an **effect GATE (CLI entrypoint), not a policy DECIDER**, and
it is not part of the same "safety fence" module class as
`daedalus/sensitivity.py`. Evidence: `sensitivity.py` exposes ~15 pure
decision functions (`secret_floor_rule`, `slice_egress_rule`,
`path_write_blocked`, `write_intent_blocked`, `protected_artifact_reason`,
`mentions_protected_path`, etc. — `sensitivity.py:477,755,800,1143,1165,1213`)
that *other* modules call **before** performing an effect, to obtain a
refusal reason or boolean; `sensitivity.py` itself performs no effects and is
declared FOUNDATION, sitting on both the kernel and spine allowlists so any
layer can consult it. `enforce.py` does the opposite: it is the thing being
gated. It performs the actual filesystem writes (`_enforce_file`,
`enforce_repo`, `enforce.py:71-98`) and, in its own `main()`, calls
`daedalus.spine.effect_boundary.begin_effect(...)` (`enforce.py:110-114`) to
*consume* the central gate before writing — it does not supply a decision
function for other modules to call. It belongs at the effect boundary as a
guarded CLI entrypoint (interfaces/cli), the same category as the other
`Surface.CLI` `EntrypointSpec` rows in `effect_boundary.py` (e.g. `cli.loop`,
`cli.gui_lint`, `cli.runbook` immediately alongside it, `effect_boundary.py:
563-620`), not alongside `sensitivity.py` in foundation/kernel.
