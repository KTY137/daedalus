# daedalus/claude_bridge.py

## 1. Size and shape

529 lines (`daedalus/claude_bridge.py:1-530`).

- 0 classes, 7 functions: `build_prompt` (57), `_extract_json` (111),
  `_blocked_report_from_wrapper` (132), `_canonical_digest` (156),
  `_invoke_claude_payload` (166), `ask_claude` (434), `main` (502).
- No module-level state, no singletons. Module-level constant:
  `REPORT_SCHEMA` dict (38-54), a static JSON-schema literal — no I/O, no
  mutation.
- No module-level side effects at import time: no file reads, no env reads,
  no registry mutation, no network. `argparse`/`hashlib`/`json`/`subprocess`
  are imported but never invoked at module scope. The `if __name__ ==
  "__main__": main()` guard (518-521) only fires on direct execution, and
  `main()` itself is explicitly a fail-closed stub that calls
  `parser.error(...)` and performs no external effect
  (`claude_bridge.py:502-515`, comment at 519-520 confirms this is
  intentional).
- `_invoke_claude_payload` (166-431) is the one function that performs a
  real effect (`subprocess.run(cmd, ...)` at 323-332) — it is explicitly
  documented as having "no closure, defaults, or mutable module globals"
  (167-172) so that its identity as an "authenticated executable object"
  cannot be redirected by rebinding a module name.

## 2. What it does

The module builds a Claude CLI prompt/report-schema pair (`build_prompt`,
`REPORT_SCHEMA`) and a private, closure-free subprocess executor
(`_invoke_claude_payload`) that spawns `claude -p ... --output-format json`,
validates the returned structured report, and hashes prompt/report for
provenance. Its public `ask_claude` no longer runs anything itself: it
raises `ClaudeProviderAuthorizationRequired` unless the caller supplies a
full set of runtime-broker authorization objects, then does a deferred
import of `.providers.claude_cli.ClaudeCLIProvider` and delegates to
`ClaudeCLIProvider().run(...)` (`claude_bridge.py:434-499`). The module's own
docstring (1-9) states it is now "a broker-only public execution path" kept
"import-compatible" while requiring the same runtime/effect authority as the
new provider instead of ambient process authority.

## 3. Who imports it (MEASURED)

Searched `daedalus/`, `tests/`, `tools/`, `apps/`, `docs/`, `.claude/` for
all required import forms plus the bare strings `"daedalus.claude_bridge"`
and `"daedalus/claude_bridge.py"` (this module is deliberately referenced by
dotted-path *string*, not just `import`, because it is pinned as an
authenticated executable-object locator — see §7).

TOTAL importer files with an actual Python `import`/`from` statement: **9**,
all under `tests/`, **zero in `daedalus/` production code**.

- `tests/providers/test_claude_runtime_broker.py:25` — `import
  daedalus.claude_bridge as bridge` — MODULE-LEVEL.
- `tests/runtimes/test_claude_provider_strangler_architecture.py:11` —
  `import daedalus.claude_bridge as bridge` — MODULE-LEVEL.
- `tests/test_agent_env.py:4` — `from daedalus.claude_bridge import
  _blocked_report_from_wrapper, _extract_json, build_prompt` —
  MODULE-LEVEL.
- `tests/test_dynamic.py:111,154,186,227,272,390,419,447` — `patch(
  "daedalus.claude_bridge.ask_claude", ...)` — all **DEFERRED** (inside test
  methods; `unittest.mock.patch` string targets, not `import` statements,
  but each resolves and binds the live attribute at test-run time).
- `tests/providers/test_claude_bypass_inventory.py:10,66` — references the
  bare path string `Path("claude_bridge.py")` as an allowed subprocess-owner
  identity, not a Python import.
- `tests/test_budget.py:934`, `tests/test_spend_coverage.py` (multiple
  lines), `tests/test_effect_boundary.py:527,555,557`,
  `tests/test_registry_new_doors.py:157`,
  `tests/test_registry_retired_rows.py:269` — all reference the bare string
  `"daedalus/claude_bridge.py"` / `"daedalus.claude_bridge:..."` inside
  inventories/comments, not an `import`.

Production `daedalus/` mentions found (all comments/docstrings, **not
imports**, confirmed by reading each site):

- `daedalus/core.py:1344` — docstring: `_ask_claude_report` "deliberately
  does not import or invoke `claude_bridge.ask_claude`" (confirmed by
  reading `core.py:1339-1354` — no import present).
- `daedalus/providers/claude_cli.py:14` — docstring only; confirmed by
  reading the full file's imports (`claude_cli.py:20-58`) that it does
  **not** import `claude_bridge` — this is asserted as a hard invariant by
  `tests/runtimes/test_claude_provider_strangler_architecture.py::
  test_provider_has_no_bridge_import_or_dynamic_locator`.
- `daedalus/runtimes/execution/budget_process.py:477` — a data-literal entry
  in the `BILLABLE_SITES` inventory tuple (`{"file":
  "daedalus/claude_bridge.py", "func": "ask_claude", ...}`), an audit
  record, not a Python import.
- `daedalus/kernel/events/envelope.py:780,785`,
  `daedalus/providers/codex_cli.py:68`,
  `daedalus/runtimes/admission/authorization.py:12`,
  `daedalus/spine/effect_boundary.py:1890,2146` — all prose
  comments/docstrings referencing the module by name, no import.

Per-layer breakdown: production `daedalus/` importers with a real import
edge = **0**. Test importers = 9 files (all under `tests/`).

Vendored/duplicate copies excluded from the count above (build artifacts /
other-agent worktrees, not distinct source): `apps/web/src-tauri/backend/
_internal/daedalus/providers/claude_cli.py:23` and its `target/{debug,
release}` mirrors DO contain a real `from ..claude_bridge import
_invoke_claude_payload` — this is a stale bundled snapshot of an **older**
version of `providers/claude_cli.py` that predates the strangler split; the
current tracked `daedalus/providers/claude_cli.py` in this working tree has
no such import (verified by reading it in full, §4). Some `.claude/
worktrees/agent-*` copies (`agent-a73944f451e5de589`, `agent-
ad4bf55b04697eefc`, `agent-aff19b618da1d4584`) also still have `daedalus/
core.py:14: from .claude_bridge import ask_claude` and `providers/
claude_cli.py:23: from ..claude_bridge import _invoke_claude_payload` — i.e.
those sibling worktrees are on an older revision than this tree's `main
@74008fab`, where the bypass had not yet been removed. This is reported as
context, not counted as a current importer of *this* tree.

## 4. What it imports (MEASURED)

From `daedalus/claude_bridge.py:18-22` (module-level) and `434-463`+
`460-463` (deferred, inside `ask_claude`):

- `.fallback` (`fallback_decision`) — `claude_bridge.py:18` — MODULE-LEVEL.
  `fallback.py` is flat/unclassified.
- `.limit_policy` (`ExecutionLimitPolicy`, `LimitPolicyError`) —
  `claude_bridge.py:19` — MODULE-LEVEL. `limit_policy` is **foundation**
  (already declared).
- `.router` (`route_task`) — `claude_bridge.py:20` — MODULE-LEVEL.
  `router.py` is flat/unclassified.
- `.runtimes.contracts.provider_report` (`REPORT_KEYS`, `validate_report`) —
  `claude_bridge.py:21` — MODULE-LEVEL. `runtimes` is an existing package
  (target layer `runtimes`).
- `.runtimes.providers.token_policy` (`MAX_SUMMARY_CHARS`,
  `STATIC_PROMPT_PREFIX`, `trim_paths`) — `claude_bridge.py:22-26` —
  MODULE-LEVEL. Target layer `runtimes`.
- `.kernel.effects` (`EffectExecutionRequest`),
  `.kernel.runtime_effects` (`RuntimeBoundEffectAuthorization`) —
  `claude_bridge.py:29-30` — **DEFERRED** (under `if TYPE_CHECKING:`,
  28-35), target layer `kernel`.
- `.runtimes.contracts.claude` (`ClaudeWorkspaceGrant`),
  `.runtimes.provider_observation` (`ProviderObservationAuthority`,
  `ProviderObservationBindingLedger`) — `claude_bridge.py:31-35` —
  **DEFERRED** (same `TYPE_CHECKING` block), target layer `runtimes`.
- `.providers.claude_cli` (`ClaudeCLIProvider`,
  `ClaudeProviderAuthorizationRequired`) — `claude_bridge.py:460-463` —
  **DEFERRED** (inside `ask_claude`'s function body — this is the load-
  bearing edge that the strangler test
  `test_tracked_import_graph_breaks_the_claude_cross_domain_scc` (`tests/
  runtimes/test_claude_provider_strangler_architecture.py:113-121`) asserts
  is reachable one-way: `bridge -> claude_cli` reachable,
  `claude_cli -> bridge` not reachable). `providers` is an existing package,
  not one of the 8 named target layers in this exercise (closest is
  `runtimes`).

Third-party: none beyond stdlib (`argparse`, `hashlib`, `json`,
`subprocess`, `typing`).

No SCC-owned module is imported by `claude_bridge.py`.

## 5. Proposed destination

**runtimes**. Confidence: **medium**, with an explicit caveat that a naive
directory move breaks pinned identity (see below and §7).

`daedalus/interfaces/bridge/` was checked per the packet's instruction and
is **not** an equivalent — it is the file-bridge/headless-dispatch package
(`cli`, `conversation`, `dispatch`, `journal`, `projection`, `queue`,
`watcher`; `daedalus/interfaces/bridge/__init__.py:1` docstring: "File-
bridge implementation owners behind the stable legacy facade") — an
unrelated concept from Claude-CLI invocation despite the shared word
"bridge". `daedalus/providers/` **is** the relevant existing sibling:
`daedalus/providers/claude_cli.py` is the measured, live, canonical Claude
adapter — `claude_bridge.py` is **not** the live invocation path; it is the
**stale/legacy twin**, now reduced to (a) a backward-compatible `ask_claude`
shim that itself delegates to `providers.claude_cli.ClaudeCLIProvider.run`
(§2, §4), and (b) the pinned source location of `_invoke_claude_payload`,
which the runtime-broker's executable-object registry treats as an
authenticated code-object identity by exact `module:qualname` string
(`daedalus.claude_bridge:_invoke_claude_payload`, asserted at
`tests/runtimes/test_claude_provider_strangler_architecture.py:187-202`).
`daedalus.providers.claude_cli:ClaudeCLIProvider.run` is the registered
`EntrypointSpec.target` for `provider.claude`
(`daedalus/spine/effect_boundary.py:965`), not `claude_bridge`.

Given `providers` is an existing package but not one of the 8 offered
target-layer names, and `claude_bridge.py`'s remaining functional role
(subprocess execution of an external CLI vendor, gated by the runtime
broker) matches the `runtimes` bucket's purpose (siblings
`runtimes/contracts/claude.py`, `runtimes/providers/token_policy.py`,
`runtimes/provider_executable_object_registry.py` are all already there),
`runtimes` is the best-fit of the 8 options. This is **not** a
"move the file today" recommendation without a companion migration: moving
`daedalus/claude_bridge.py` to e.g. `daedalus/runtimes/claude_bridge.py`
changes `_invoke_claude_payload.__module__` from `daedalus.claude_bridge` to
`daedalus.runtimes.claude_bridge`, which would (1) fail
`test_authenticated_executable_object_source_locators_do_not_move`
(pins the exact string `"daedalus.claude_bridge:_invoke_claude_payload"`),
and (2) invalidate any *persisted* `ProviderExecutablePreAdmissionReceipt`/
`invoke_target` string minted against the old locator, since
`provider_executable_object_registry.py:2332`
(`_repository_source_path(self._repository_root, invoke_target)`) resolves
the dotted path back to a file on disk for AST/hash verification.

Evidence that would change my mind: whoever owns the `G1-RUNTIME-PROVIDER-01
_CLAUDE_CONTRACT_STRANGLER` work packet
(`docs/work-packets/G1-RUNTIME-PROVIDER-01_CLAUDE_CONTRACT_STRANGLER.md`)
may have a planned terminal state where `claude_bridge.py` is deleted
outright once the "caller injection" half of the strangler migration lands
(effect_boundary.py:993-999 names this as the deliberately-standing
activation blocker, MEASURED 2026-08-18: zero production callers mint a
`RuntimeBoundEffectAuthorization` yet) — if that packet is closer to landing
than this hierarchy sweep, `delete` (after migrating the pinned locator)
may be the more honest destination than `runtimes`.

## 6. Boundary-rule check after the move

(a) Would `claude_bridge.py`'s own imports be refused under `runtimes`? No
rule in `import-boundaries.json` has `source_prefixes` containing
`daedalus.runtimes` in a way that forbids its own further outbound imports
except `runtimes-no-gates` (forbids `daedalus.gates` only) — `claude_bridge.
py` imports no `daedalus.gates` anything, so nothing is refused. Its
deferred `.providers.claude_cli` edge (§4) is untouched by any rule (no rule
constrains `daedalus.runtimes -> daedalus.providers`).

(b) Does any current rule name `claude_bridge`/`daedalus.claude_bridge` by
prefix? No — confirmed by reading the full `import-boundaries.json`; none of
the 4 rules' `forbidden_target_prefixes`/`allowed_target_prefixes` mention
`claude_bridge`. Nothing breaks or unblocks specifically for this module's
own name; the two rules that matter for its *outgoing* edges
(`kernel-no-outer-layers`, `runtimes-no-gates`) are keyed by `daedalus.
kernel`/`daedalus.runtimes` as sources, and moving the file into
`daedalus.runtimes.*` makes `runtimes-no-gates` apply to it going forward
(currently N/A since it's flat).

(c) N/A for the proposed `runtimes` destination (not kernel/spine/twin, so
no allowlist enumeration applies). If forced into `kernel`/`spine`/`twin`
instead: ALL of its `daedalus.*` edges would be refused except the
`TYPE_CHECKING`-only `kernel.effects`/`kernel.runtime_effects` (allowed
under `spine-no-outer-layers`'s allowlist, which includes `kernel`, and
`twin-no-outer-layers`'s allowlist, which also includes `kernel`) — but
`.fallback`, `.router`, `.runtimes.contracts.provider_report`,
`.runtimes.providers.token_policy`, `.runtimes.provider_observation`, and
the deferred `.providers.claude_cli` are not in any of the three
allowlists, so 6 of its 8 distinct import targets would be refused.

## 7. Dead-code signals

Importers with a real Python import statement in `daedalus/` production
code = **0** (§3). This is a FINDING, not a verdict, per this repository's
own burn history — investigated further:

- **Promised reader found in the docstring/tests, not "used by X" prose,
  but as an explicit pinned identity requirement.** The module's own
  docstring (`claude_bridge.py:1-9`) states its `ask_claude` "remains
  import-compatible" and requires "the same runtime/effect authority...
  instead of invoking from ambient process authority" — i.e. it is
  deliberately kept reachable via the *exact same dotted path* for callers
  that supply broker authorization, not deleted.
- `tests/runtimes/test_claude_provider_strangler_architecture.py` is an
  entire test module dedicated to pinning this exact strangler-migration
  state: `test_tracked_import_graph_breaks_the_claude_cross_domain_scc`
  asserts `claude_bridge -> claude_cli` is reachable and the reverse is not;
  `test_authenticated_executable_object_source_locators_do_not_move` asserts
  `_invoke_claude_payload.__module__ == "daedalus.claude_bridge"` by
  literal string; `test_registered_effect_door_and_digest_are_exactly_
  unchanged` pins `REGISTRY_SHA256` against the current `EntrypointSpec`
  registry state.
- `daedalus/spine/effect_boundary.py:981-999` (the `provider.claude`
  `EntrypointSpec.notes`) names, in prose, the exact two-part condition
  under which this row's `Wiring.INVENTORY_ONLY` status would flip to
  active: "(1) caller injection — some production caller actually mints a
  `RuntimeBoundEffectAuthorization`... MEASURED 2026-08-18: zero such [...]".
  This is the promised reader: a not-yet-written production caller.
- `daedalus/runtimes/execution/budget_process.py:477` keeps
  `"daedalus/claude_bridge.py"` / `"ask_claude"` in the audited
  `BILLABLE_SITES` inventory tuple as a real (if currently unreachable)
  billable subprocess site — the spend-coverage tests
  (`tests/test_spend_coverage.py`) treat it as a tracked hole, not a
  deletable stub.
- Bare-string search for `"claude_bridge"` and `"daedalus.claude_bridge"` as
  a dynamic-import/registry key (§3) turns up exactly this pinned-locator
  usage pattern across 6 test files plus the `budget_process.py` inventory
  entry — no additional dynamic dispatch found.
- Git history: added 2026-07-05 (`1f5f6706 feat: add claude structured
  report bridge`), 9 total commits touching the file; the strangler-split
  commit that removed `providers/claude_cli.py`'s import of it (visible by
  contrast with the stale `apps/web/src-tauri/.../providers/claude_cli.py`
  bundled copy and the older `.claude/worktrees/agent-a73944f...` /
  `agent-ad4bf55b...` / `agent-aff19b618...` copies, which still have
  `daedalus/core.py:14: from .claude_bridge import ask_claude`) is recent
  relative to those artifacts — consistent with an in-progress, not
  abandoned, migration.

Label: **UNWIRED-WITH-PROMISED-READER**. Not CANDIDATE-DELETE: the promised
reader (a production caller minting `RuntimeBoundEffectAuthorization` for
`provider.claude`) is named explicitly in `effect_boundary.py` and pinned by
a dedicated test module; deleting or silently relocating the file today
would either violate the strangler test suite's identity pins or, if the
tests were updated in lock-step, would still need to migrate any
already-persisted `invoke_target` strings — outside this dossier's read-only
scope to verify further.
