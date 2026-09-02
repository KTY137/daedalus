# `daedalus/llm_client.py`

Scoping note: every search below is restricted to `daedalus`, `tests`,
`tools` (via `git grep -- daedalus tests tools`, or `Grep path=`).
`.claude/worktrees/agent-*/` holds full copies of `daedalus/` and `tests/`
and was deliberately excluded to avoid double-counting importer sites.

## Identity

Absolute path: `C:/Users/Administrator/daedalus/daedalus/llm_client.py`
Line count: 251 (`wc -l`, confirmed 2026-09-02).
One sentence: `IkarusLLMClient` is the vendor-neutral model-selection and
call-retry policy for Ikarus's chat surface — it decides *which* provider to
use and *how many times* to retry, but never opens a transport itself.

## Importers (MEASURED)

Total unique importer sites found by this scope: **3** = 1 daedalus/ + 2
tests/ + 0 tools/, matching the lead's precomputed count exactly; **0
deferred**, also matching.

daedalus/ (1, module-level):

- `daedalus/ikarus_os.py:98` — `from .llm_client import IkarusLLMClient`

tests/ (2, both module-level real imports):

- `tests/test_ikarus_llm_voice.py:5` — `from daedalus.llm_client import LLMSelection`
- `tests/test_llm_client.py:3` — `from daedalus.llm_client import IkarusLLMClient, LLMRequest, LLMResponse, LLMUnavailable`

(`tests/test_ikarus_llm_voice.py:15` is a test function name containing the
string "llm_client", not an import; excluded.)

**Dynamic/string references searched and found:** searched
`importlib`/`__import__` combined with the module name, literal dotted
strings, and `pyproject.toml` console_scripts (only `daedalus` and
`daedalus-chip`, neither names this module). No dynamic import or
plugin/registry-table reference to this module exists in scope; it is
consumed exactly once in production, by direct class instantiation in
`ikarus_os.py`.

## Imports (MEASURED)

**Module-level (file:line):**

stdlib (4):
- `os` — line 16
- `itertools.count` — line 17
- `dataclasses.dataclass, field` — line 18
- `typing.Any, Callable, Iterable, Mapping, Sequence` — line 19

daedalus.* (1):
- `daedalus/limit_policy.py` — line 21, `from .limit_policy import
  ExecutionLimitPolicy, load_from_env as load_limit_policy`

**Deferred / function-scope (file:line + enclosing function):**

daedalus.* (1):
- line 181, `from .runtime_registry import cached_runtime_status`, inside
  `_probe(self, provider: str)` (def at line 172).

No third-party imports anywhere. Total: 2 daedalus.* imports (1 module-level
+ 1 deferred), 4 stdlib module-level imports, 0 deferred stdlib, 0
third-party.

## What it does

`IkarusLLMClient.resolve()` walks a configurable provider preference order
(`claude_code_cli`, `ollama_http`, `codex_cli`, `ollama_cli`, `deepseek` by
default) probing each via `runtime_registry.cached_runtime_status` (or an
injected `status_probe`) until one reports available, honoring an explicit
override, an env-configured default, or an explicit `deterministic`
selection with no automatic fallback into it; `complete()` then runs a
caller-supplied, effect-guarded `invoke` callable under this client's
timeout/retry policy (bounded by `ExecutionLimitPolicy`, defaulting to zero
hidden paid retries) without itself opening any socket or process. The
module's own docstring self-classifies as `Iron Plan: ALIGNED` — "the
vendor-neutral runtime contract required by master-plan §7" — and states
model selection "never grants file, tool, policy, evaluator, or promotion
authority." Size: 251 lines.

## Proposed destination

**Proposed: `orchestration`.**

This is not a naming-driven call; the module's own docstring is explicit
textual self-classification as master-plan §7 orchestration substance: "the
orchestration layer answers who works, with which runtime... through one
vendor-neutral runtime contract" is exactly the shape §7 of the master plan
describes for Ikarus. Its single production importer,
`daedalus/ikarus_os.py`, is the orchestration-tier chat/voice runtime module
(the older Ikarus cluster — see the "two disconnected clusters" finding in
`ikarus_runtime_role.md`); its sole `daedalus.*` deferred dependency is
`runtime_registry` (also proposed for `orchestration`, see
`runtime_registry.md`), and its sole module-level `daedalus.*` dependency is
`limit_policy` (a flat foundation-tier budget/policy primitive already in the
lead's measured `{budget, sensitivity, structcore, limit_policy,
primary_tree, config, storage, atomic, mapping, offload, providers,
resources}` set that kernel/spine/twin/runtimes layer-files freely import —
i.e. a dependency this module can keep regardless of which layer it lands
in).

**Strongest counter-argument:** the module is a "vendor-neutral runtime
contract" and could instead be argued into `daedalus.runtimes`, alongside
provider execution. This loses on the same measured-edge basis as the other
four modules: zero files under `daedalus/runtimes/` import this module (lead's
AST sweep, independently reconfirmed via `git grep` over
`daedalus/runtimes daedalus/kernel daedalus/spine daedalus/twin`, no hit for
`llm_client` at all), and the module's own docstring draws the line itself —
"this client makes the chat default useful... it deliberately owns
*selection and call policy*, not effects: the actual transports remain in
`daedalus.ikarus_os`, behind the existing provider effect boundary." Model
selection policy is explicitly *not* the runtime/effect layer by the
module's own stated architecture, which matches the measured absence of any
`daedalus.runtimes` edge.

## Boundary-rule verdict after the move

Four rules by id (`kernel-no-outer-layers`, `runtimes-no-gates`,
`spine-no-outer-layers`, `twin-no-outer-layers`), both directions:

- **(b) inbound:** VACUOUSLY CLEAN, attributed to the lead's AST sweep: no
  file under `daedalus/kernel`, `daedalus/spine`, `daedalus/twin`,
  `daedalus/runtimes` imports any of the five dossier modules at any AST
  scope, and the complete flat-module import set of those 142 layer-files is
  `{budget, sensitivity, structcore, limit_policy, primary_tree, config,
  storage, atomic, mapping, offload, providers, resources}` —
  `llm_client` is not in it (though its own dependency `limit_policy` is).
  Independently reconfirmed: this module's only importer,
  `ikarus_os.py`, is not under kernel/spine/twin/runtimes.
- **(a) outbound / `daedalus.gates` check:** this module's only daedalus.*
  imports are `.limit_policy` (module-level) and `.runtime_registry`
  (deferred) — never `daedalus.gates`. Grep confirms directly: `git grep -n
  "daedalus.gates\|from \.gates\|from \.\.gates\|import gates" --
  daedalus/llm_client.py` returns no matches. If hypothetically moved into
  `daedalus.runtimes`, rule `runtimes-no-gates` would still pass: **CLEAN**.
- Because the proposed destination is `orchestration`, which is not a
  `source_prefixes` entry for any of the four rules
  (`docs/architecture/import-boundaries.json`), none of the four rules binds
  this module as a source after the move.

**One-line verdict: N-A-not-a-rule-source (destination `orchestration`); the
hypothetical `daedalus.runtimes` landing would also be CLEAN (no
`daedalus.gates` import at any scope).**

## Dead-code signals

Not dead: 3 measured importer sites (1 production, 2 test), each a real,
non-trivial consumer; 0 near-zero-importer concern here. The docstring
(quoted from lines 1–13) is explicit about scope and boundary:

> "Vendor-neutral language-model client policy for Ikarus. Iron Plan:
> ALIGNED — this is the vendor-neutral runtime contract required by
> master-plan §7. It deliberately owns *selection and call policy*, not
> effects: the actual transports remain in `daedalus.ikarus_os`, behind the
> existing provider effect boundary. A model is a speaking/proposal surface;
> selecting it never grants file, tool, policy, evaluator, or promotion
> authority."

The docstring names its one intended reader by module path —
`daedalus.ikarus_os` — and that is exactly the one production importer
measured above (`daedalus/ikarus_os.py:98`). Chasing one hop: `ikarus_os.py`
is itself a large, actively-tested production module (confirmed live via its
own 5 deferred `runtime_registry` import sites measured in
`runtime_registry.md`, and its own substantial test coverage referenced
across `tests/test_ikarus_stream.py`, `tests/test_ikarus_context.py`, etc.).
No rot signal: docstring promise and measured importer match exactly, one
for one.

## Confidence

**High.** The 3/1/2/0 counts match the lead's precomputed figures exactly
and were independently re-derived by direct grep, including confirming the
single deferred `runtime_registry` import at line 181 inside `_probe`. The
destination argument rests on the module's own explicit textual
self-classification (master-plan §7, orchestration) plus its single
measured production importer, not on inference from its name.
