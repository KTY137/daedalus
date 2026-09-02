# daedalus/verifier.py

## Identity

`C:/Users/Administrator/daedalus/daedalus/verifier.py`, 508 lines. The
offload cascade's acceptance gate: runs cheap deterministic checks (schema
validity, `py_compile`, lint, JSON/YAML parse, JS/HTML sanity, the prose
fact-preservation tripwire, and optionally the project test suite) on a
local model's write before it is accepted, and reports `pass` /
`fail` / `inconclusive`.

## Importers (MEASURED)

Scope: `daedalus`, `tests`, `tools` only; `.claude/worktrees/agent-*/`
excluded. Searched `from \.+verifier`, `from daedalus.verifier`,
`from daedalus import ...verifier...`, `import daedalus.verifier` — module
name has no nested-package collision (`Glob daedalus/**/verifier.py` =
only `daedalus/verifier.py`).

**daedalus/ — 1 site**: `daedalus/offload.py:32`
`from .verifier import (DEFAULT_TEST_TIMEOUT_S, VerifyResult, ...` —
module level, not deferred.

**tests/ — 9 sites** (statement-level; matches the lead's count exactly):
`test_cascade.py:6` (`from daedalus import metrics, semantic_route,
verifier`), `test_era1_robustness.py:21`, `test_fake_offload.py:17`,
`test_hardening.py:22` (`from daedalus import file_bridge, memory, metrics,
verifier`), `test_prose_gate.py:12` and `:14` (two statements, same file),
`test_verify_gate.py:6`, `test_verify_test_budget.py:35` and `:38` (two
statements, same file). 7 unique files, 9 import statements — the lead's
"9 total" counts statements, consistent with how the daedalus/-side count
(29) for `projects` also counted statements rather than files.

**tools/ — 0 sites.** Confirmed by grep.

Total = 1 + 9 + 0 = 10, 0 deferred — matches the lead's precomputed count
(`verifier 10 total = 1 daedalus/ + 9 tests/ + 0 tools/; 0 deferred`)
exactly.

Dynamic/string references: no `importlib`, `__import__`, console-script, or
`python -m` reference to `verifier` found in the scoped tree.

## Imports (MEASURED)

Module-level (lines 13-24): stdlib `json, shlex, subprocess, sys,
dataclasses (dataclass, field), pathlib.Path`; daedalus —
`.limit_policy.ExecutionLimitPolicy` (line 22), `.preservation
(check_preservation, is_prose_path)` (line 23),
`.runtimes.contracts.provider_report.validate_report` (line 24). Three
distinct daedalus top-level targets: `limit_policy`, `preservation`,
`runtimes`.

Deferred/function-scope: one daedalus import —
`from .spine.docrefs import scan, verify_fixes`, `verifier.py:322`, inside
`_prose_check`. Third-party, deferred: `pyflakes` (`verifier.py:136`,
inside `_lint_py`, wrapped in `try/except ImportError`), `yaml`
(`verifier.py:202`, inside `_config_check`, also optional). Stdlib,
deferred: `shutil` (`_lint_py:130`, `_js_check:153`), `os` (`verify:482`),
`re` (`_html_check:172`).

Matches the lead's outbound profile (`verifier -> {limit_policy,
preservation, runtimes, spine}; 3rd-party: pyflakes, yaml; 1 deferred`)
exactly — the "1 deferred" is the `.spine.docrefs` daedalus import; `spine`
only appears via that one deferred site, never at module level.

## What it does

Dispatches per-changed-file checks by extension (`.py` → compile+lint,
`.json`/`.yaml` → parse, `.js` → node syntax check, `.html` → truncation
tripwire, prose → `preservation.check_preservation` against a caller-supplied
before-image) plus an optional project-test-suite run under a budget, and
folds every check's `ok` into one accept/reject/inconclusive verdict
(`VerifyResult`). It explicitly distinguishes a real failure from a
never-reached verdict (timeout/error/unknown) so routing metrics do not
blame the local model for a budget shortfall. 508 lines.

## Proposed destination

**orchestration.**

Argument: its one and only production caller, `daedalus/offload.py`, is the
local-model routing/dispatch cascade — an orchestration concern by
definition (it decides whether a candidate local-model output is accepted
or escalated). `verifier` is not a runtime I/O adapter itself; it *judges*
the output of one (reading `.runtimes.contracts.provider_report`'s schema,
not calling a provider). It also reaches into `.spine.docrefs` for a
narrow, deferred reconciliation with the docref gate — again a
cross-cutting orchestration decision (whether a "lost" fact is actually an
intentional, independently-proven docref fix), not infrastructure.

Strongest counter-argument: it directly imports
`daedalus.runtimes.contracts.provider_report`, which could argue for
`runtimes` instead, since that is where the schema it validates against
lives. This loses because `verifier` does not implement or adapt any
runtime/provider transport — it only imports one shared *contract* type to
validate an already-produced report, which is exactly the kind of
one-directional "runtimes → orchestration" contract dependency the layer
split is meant to allow (orchestration is free to depend on runtimes;
runtimes must not depend on gates). Placing the judge of a cascade inside
the layer that implements the cascade's transports would also fight the
existing `runtimes-no-gates` precedent of keeping decision/gate logic
structurally separate from provider-facing code.

## Boundary-rule verdict after the move

Direction (b), all four rules: **CLEAN, vacuous** — spot-checked directly,
0 matches for `verifier` under `daedalus/kernel`, `daedalus/spine`,
`daedalus/twin`, `daedalus/runtimes`.

Direction (a) — if `verifier` hypothetically landed in a rule-source layer
itself, using its measured imports (`limit_policy`, `preservation`,
`runtimes.contracts.provider_report` module-level; `spine.docrefs`
deferred):

- **kernel-no-outer-layers** (source `daedalus.kernel`; denylist includes
  `daedalus.runtimes`; allowlist = atomic/budget/config/limit_policy/
  primary_tree/sensitivity/spine/storage/twin, per
  `docs/architecture/import-boundaries.json:26-46`): **REFUSED** —
  `daedalus.runtimes.contracts.provider_report` at `daedalus/verifier.py:24`
  (ground 1, denylist hit on `daedalus.runtimes`). `daedalus.preservation`
  would *also* be refused (ground 2 — not on the allowlist), at
  `daedalus/verifier.py:23`. `limit_policy` (line 22) and the deferred
  `spine.docrefs` (line 322) would both be allowed.
- **runtimes-no-gates** (source `daedalus.runtimes`; denylist =
  `daedalus.gates` only, empty allowlist): does `verifier` import
  `daedalus.gates` at any scope? **No** — confirmed by reading the whole
  file; none of its imports (`limit_policy`, `preservation`, `runtimes`,
  `spine.docrefs`, stdlib, `pyflakes`, `yaml`) touch `daedalus.gates`.
  **CLEAN** if it hypothetically landed here.
- **spine-no-outer-layers** (source `daedalus.spine`; denylist includes
  `daedalus.runtimes` and `daedalus.offload`; allowlist = atomic/budget/
  config/kernel/limit_policy/mapping/sensitivity/structcore, per
  `import-boundaries.json:67-98`): **REFUSED** — `daedalus.runtimes.contracts
  .provider_report` at `verifier.py:24` (ground 1). `daedalus.preservation`
  also refused (ground 2, off-allowlist) at `verifier.py:23`.
- **twin-no-outer-layers** (source `daedalus.twin`; denylist includes
  `daedalus.runtimes`; allowlist = kernel/spine/structcore, per
  `import-boundaries.json:107-121`): **REFUSED** — same
  `daedalus.runtimes.contracts.provider_report` hit at `verifier.py:24`
  (ground 1), plus `daedalus.preservation` refused (ground 2).

`daedalus.gates` is not imported at any scope. **One-line verdict:
REFUSED (kernel, spine, twin — all via `daedalus.runtimes` at
verifier.py:24, and secondarily `daedalus.preservation` at verifier.py:23);
CLEAN for runtimes-no-gates.** This confirms and names precisely the
concrete finding the lead handed down: `daedalus.runtimes` is forbidden for
kernel/spine/twin, and `verifier` imports it at module level, so it could
never land in any of those three layers without a refusal.

## Dead-code signals

Not dead. `verifier.py` has one daedalus/ importer (`offload.py`) but that
importer is itself demonstrably live: `offload.py` is the module
`daedalus/selftest.py:126` imports to run its real Ollama round-trip, is
wired into `daedalus/cli.py`, and has a dedicated family of ~10 test files
(`test_offload_*`, `test_fake_offload.py`, `test_hardening.py`, etc.) plus
5 tests that import `verifier` directly to exercise its gate logic in
isolation (`test_era1_robustness.py`, `test_fake_offload.py`,
`test_prose_gate.py`, `test_verify_gate.py`, `test_verify_test_budget.py`).
The 9-of-10 tests-vs-production-importer ratio the steer flags is explained
by this: `verifier` is a pure decision function with many boundary
conditions (schema, syntax, lint, JSON/YAML, JS, HTML, prose, timeout,
inconclusive-vs-fail routing) each worth its own test, fed by exactly one
production call site — high test/caller ratio is a property of a
well-covered pure function, not a liveness signal in either direction here.
It is not part of `daedalus/eval/` (that package's `ceiling.py` only
mentions "verifier.py<->providers/ollama.py coupling" in prose commentary
about label-boundary design, never imports `daedalus.verifier`) — this is
the offload cascade's own quality gate, not the benchmark/eval harness, and
not `sensitivity.py`/`enforce.py`'s write-policy fence either (verifier
never imports either of those).

## Confidence

High. Importer/import counts match the lead's precomputed numbers exactly;
the module-identity question (offload-cascade gate vs. `daedalus/eval/` vs.
safety fence) was settled by direct evidence (its one caller, its own
imports, and a targeted check that `eval/ceiling.py` never imports it); the
boundary-refusal claim was derived from the actual JSON rule text
(`import-boundaries.json:26-121`), not assumed from the task's summary.
