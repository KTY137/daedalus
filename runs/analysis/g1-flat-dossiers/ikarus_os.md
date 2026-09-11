# ikarus_os.py — flat-hierarchy classification dossier

Scope note: every search below was restricted to `daedalus`, `tests`, `tools`
explicitly (`git grep -- daedalus tests tools`, or `Grep path=`). This repo's
`.claude/worktrees/agent-*/` trees hold full copies of `daedalus/` and
`tests/`; a scan without that restriction double-counts importers against
those copies. Base commit: `851ff43cc63dd788d1da63a6f7fa44fcc6ed0291`.

## Identity

- Absolute path: `C:/Users/Administrator/daedalus/daedalus/ikarus_os.py`
- Line count: 2086 (`wc -l`)
- One sentence: it is the Ikarus assistant's deterministic intent
  router/classifier and vendor-neutral LLM-voice dispatcher — the module that
  turns a chat message into `(intent, act)`, answers `status`/`distill`
  locally, proposes confirm-gated `hand` tasks, and drives the `voice` shell
  across Ollama/Claude/Codex/DeepSeek.

## Importers (MEASURED)

Searched with `git grep -n -E "^\s*(from|import)\s+.*ikarus_os|import ikarus_os\b" -- daedalus tests tools`.

**daedalus/ (3 files, 3 import statements):**
- `daedalus/conversation_requests.py:20` — `from . import conversation, editor_context, ikarus_os` (flat, root `daedalus/`; product/orchestration-support module)
- `daedalus/interfaces/http/sse.py:8` — `from ... import conversation_requests, core, ikarus_os` (already lives under `daedalus.interfaces.http`)
- `daedalus/web_api.py:48` — `from . import ikarus_os` (flat, root `daedalus/`; HTTP entrypoint)

**tests/ (12 files, 22 import statements):**
- `tests/test_conversation_on_canonical_spine.py:328`
- `tests/test_egress_lane_by_host.py:137,155` (2)
- `tests/test_ikarus_act.py:11`
- `tests/test_ikarus_context.py:23`
- `tests/test_ikarus_llm_voice.py:3`
- `tests/test_ikarus_os.py:10`
- `tests/test_ikarus_os_boundary.py:300,316,341,352,372,392,406,422,445,461,487` (11, all function-scope `import daedalus.ikarus_os as ikarus_os`)
- `tests/test_ikarus_shells.py:18`
- `tests/test_ikarus_stream.py:13`
- `tests/test_uncapped_scope_usage.py:11`
- `tests/test_wires.py:38`

**tools/ : 0 importers.**

**Total: 15 distinct files, 25 import statements** (3 daedalus/ + 22 tests/).

**Dynamic/string references — searched and found:**
- `importlib`/`__import__` referencing `ikarus_os`: **none found** (`git grep -n -E "importlib.*ikarus_os|ikarus_os.*importlib|__import__\(.*ikarus_os"` — empty).
- Literal string `"daedalus.ikarus_os"`: **one hit**, `tests/contracts/test_spine_outer_ports.py:82`, inside the tuple `FORBIDDEN_PREFIXES` — this is the boundary-contract's own denylist mirror, not a live importer. It is direct evidence the destination question was already partly answered by the boundary rule itself (see below).
- `pyproject.toml`/`setup.py`/`setup.cfg` console_scripts naming `ikarus_os`: **none found**.
- `subprocess`/`python -m` invoking `ikarus_os`: **none found**.
- Total files (any mention, docstrings/comments included) under the scoped dirs: 34, vs. 15 files that actually import it — the remaining 19 are prose references (`daedalus/budget.py`, `daedalus/cli.py`, `daedalus/conversation.py`, `daedalus/health.py`, `daedalus/ikarus_act.py`, eval task fixtures, etc.) describing or targeting the module without importing it.

## Imports (MEASURED)

Measured with a small AST script (`.venv/Scripts/python.exe`) that walks the
module, classifies every `Import`/`ImportFrom` as module-level or
function/class-scope, and prints line + enclosing function. Script output
(abbreviated to the counts and the daedalus.* rows; full run showed 17
module-level and 43 deferred **statements**, 18 and 54 counting individual
imported *names* since several statements bind multiple names):

```
=== MODULE-LEVEL ===
81: from __future__ import annotations
83: import hashlib
84: import json
85: import os
86: import re
87: import subprocess
88: import tempfile
89: import time as _time
90: from collections import namedtuple
91: from itertools import count
92: from pathlib import Path
94: from . import core, ikarus_act
95: from .ikarus_act import ActDecision
96: from .projects import resolve_repo_root
97: from .providers._openai_compat import chat_completion
98: from .llm_client import IkarusLLMClient
99: from .limit_policy import ExecutionLimitPolicy

COUNT module_level_stmts=17 deferred_stmts=43
```

**Module-level split:** 11 stdlib/`__future__` statements (`hashlib`, `json`,
`os`, `re`, `subprocess`, `tempfile`, `time`, `collections.namedtuple`,
`itertools.count`, `pathlib.Path`, `__future__.annotations`) vs. 6 statements
naming 6 distinct `daedalus.*` targets: `core`, `ikarus_act` (imported twice,
lines 94 and 95), `projects`, `providers._openai_compat`, `llm_client`,
`limit_policy`. Zero third-party (non-stdlib, non-daedalus) module-level
imports.

**Deferred (function-scope), full list with enclosing function:**

```
271: [ask]                  from .budget import process_guard_boundary_decision
272: [ask]                  from .spine.effect_boundary import REGISTRY_BY_ID, begin_effect
330: [_prior_turn]          from . import conversation
430: [_turn_status]         from . import conversation
457: [_persist_turn]        from . import conversation
485: [_status]              from .file_bridge import bridge_status
498: [_distill]             from .structcore.index import cached_index
499: [_distill]             from .structcore.report import structure_summary
500: [_distill]             from .structcore.slice import semantic_slice
679: [_hand_state]          from . import health
686: [_hand_state]          from collections import namedtuple as _nt      (stdlib)
828: [_design]               from . import ikarus_chat
865: [_conversation_context] from . import conversation
916: [_project_context]      from .structcore.index import cached_index
917: [_project_context]      from .structcore.slice import semantic_slice
1114:[_llm]                  from .providers.ollama import DEFAULT_MODEL
1126:[_llm]                  from .providers.ollama import DEFAULT_MODEL
1143:[_llm]                  from .providers.deepseek import DEFAULT_MODEL
1158:[_llm]                  from .runtime_registry import resolve_runtime_command
1185:[_local_lane]           from .providers.ollama import DEFAULT_HOST
1186:[_local_lane]           from .sensitivity import lane_for_host
1275:[_deny_receipt]         from .spine.effect_boundary import registry_sha256
1304:[_spend_decision]       from .spine.effect_boundary import GuardDecision
1307:[_spend_decision]       from . import budget
1379:[_egress_decision]      from .spine.effect_boundary import GuardDecision
1382:[_egress_decision]      from .providers.ollama import ollama_endpoint_admission
1387:[_egress_decision]      from .sensitivity import lane_for_host
1429:[_provider_start]       from .spine.effect_boundary import EffectBoundaryError, begin_effect
1472:[_ollama]               from .providers.ollama import DEFAULT_HOST, ollama_http_base_url, warm_model_async
1499:[_ollama_cli]           from .providers.ollama import DEFAULT_HOST
1500:[_ollama_cli]           from .runtime_registry import resolve_runtime_command, runtime_subprocess_env
1532:[_deepseek]             from .providers.deepseek import DEFAULT_BASE_URL
1580:[_claude]               from .runtime_registry import resolve_runtime_command, runtime_subprocess_env
1613:[_codex]                from .runtime_registry import resolve_runtime_command, runtime_subprocess_env
1741:[_ask_stream_inner]     from .budget import process_guard_boundary_decision
1742:[_ask_stream_inner]     from .spine.effect_boundary import REGISTRY_BY_ID, begin_effect
1815:[_ask_stream_inner]     from .providers.ollama import DEFAULT_MODEL
1841:[_ask_stream_inner]     from .providers.deepseek import DEFAULT_MODEL
1948:[_ollama_stream]        from .providers._openai_compat import chat_stream
1949:[_ollama_stream]        from .providers.ollama import DEFAULT_HOST, ollama_http_base_url, warm_model_async
1976:[_deepseek_stream]      from .providers._openai_compat import chat_stream
1977:[_deepseek_stream]      from .providers.deepseek import DEFAULT_BASE_URL
2003:[_claude_stream]        from .runtime_registry import resolve_runtime_command, runtime_subprocess_env
```

**Deferred split:** 42 `daedalus.*` statements vs. 1 stdlib (`collections.namedtuple`
at line 686). Distinct deferred `daedalus.*` targets and their statement
counts: `providers.ollama` (8), `spine.effect_boundary` (6), `runtime_registry`
(5), `providers.deepseek` (4), `conversation` (4), `budget` (3), `structcore.index`
(2), `structcore.slice` (2), `sensitivity` (2), `providers._openai_compat` (2),
`file_bridge` (1), `health` (1), `ikarus_chat` (1), `structcore.report` (1).

**Overall: 60 total import statements** (17 module-level + 43 deferred), of
which 48 target `daedalus.*` and 12 target stdlib; **zero** third-party
(non-stdlib) imports anywhere in the file.

## What it does

`ikarus_os.py` runs `classify()` exactly once per request to derive one
`(intent, act)` pair, then routes it through exactly one of three capability
shells — `deterministic` (local `status`/`distill`/`design`, no spend, no
egress), `hand` (proposes a confirm-gated task via the file bridge, never
executes one itself), or `voice` (a tool-free LLM chat turn across
Ollama/Claude-CLI/Codex-CLI/DeepSeek, gated by `spine.effect_boundary`
`begin_effect`/`GuardDecision` egress and spend checks before any provider
call). It owns both the synchronous `ask()` entrypoint and the streaming
`ask_stream()`/`_ask_stream_inner()` path, and every branch stamps which
shell answered so that fact is recorded rather than inferred. Size: 2086
lines, the largest module in this dossier batch.

## Proposed destination

**`daedalus.orchestration`**

Argument, from measured evidence: the module has zero third-party
dependencies and is entirely composed of stdlib plus `daedalus.*` glue; its
`daedalus.*` imports are overwhelmingly provider dispatch (`providers.ollama`,
`providers.deepseek`, `providers._openai_compat`, `runtime_registry` — 19 of
48 daedalus-target statements) and effect-boundary consumption
(`spine.effect_boundary`, `budget`, `sensitivity` — 11 statements), i.e. it
*calls into* the kernel/spine trust boundary and the provider layer rather
than implementing either. That shape — classify intent, pick a runtime,
enforce policy before dispatch, never itself own policy/evidence/ledger state
— is exactly what the master plan (§7) assigns to Ikarus's orchestration
layer. It is imported by only 3 non-test files, none of which are
kernel/spine/twin/runtime modules, and it imports only two `ikarus_*`
siblings (`ikarus_act`, `ikarus_chat`), both of which are themselves
orchestration-shaped capability/dispatch helpers, not kernel primitives. The
boundary contract's own authors independently reached the same conclusion:
`spine-no-outer-layers` already forbids `daedalus.ikarus_os` by name (see
below), grouping it with `daedalus.orchestration`, `daedalus.web_api`,
`daedalus.file_bridge` — the outer, product-facing layer.

Strongest counter-argument: two of its three non-test importers
(`daedalus/web_api.py`, `daedalus/interfaces/http/sse.py`) are HTTP interface
entrypoints, and `sse.py` already lives under `daedalus/interfaces/http/`,
which could argue for `daedalus.interfaces.http` as the destination instead —
"the code that answers HTTP requests belongs with the HTTP interface." This
loses: `ikarus_os` itself contains no request/response/route code (no
Flask/FastAPI/Starlette symbols anywhere in the 2086 lines), is imported
identically by a non-HTTP root module (`conversation_requests.py`) and by 12
test files that exercise it directly with no HTTP layer involved, and its own
docstring frames it as "the assistant seam" reused across shells/interfaces —
i.e. it is transport-agnostic dispatch logic that an HTTP handler *calls*,
not an HTTP handler itself. Interfaces should depend on orchestration, not
contain it.

## Family note

`ikarus_os` imports exactly two `ikarus_*` siblings: `ikarus_act` (module-level,
lines 94–95, plus three in-body call sites at lines 228, 344, 601 via the
already-imported name) and `ikarus_chat` (deferred, line 828, inside `_design`
only). It imports no other family member (checked `ikarus_effect_bridge`,
`ikarus_oneshot`, `ikarus_runtime_events`, `ikarus_runtime_role`,
`ikarus_supervisor`, `ikarus_tool_scope`, and the flat `daedalus/ikarus.py` —
none appear). In the reverse direction, none of those eight sibling files
import `ikarus_os` back (`git grep -n "ikarus_os" -- daedalus/ikarus_act.py
daedalus/ikarus_chat.py daedalus/ikarus_effect_bridge.py
daedalus/ikarus_oneshot.py daedalus/ikarus_runtime_events.py
daedalus/ikarus_runtime_role.py daedalus/ikarus_supervisor.py
daedalus/ikarus_tool_scope.py daedalus/ikarus.py` — the only `ikarus_act.py`
hits are docstring/comment prose naming `ikarus_os`, not imports). So within
the family, `ikarus_os` is a one-directional caller of a two-member subset
(`ikarus_act`, `ikarus_chat`) and is imported by zero family members — it is
a **leaf from the family's own perspective, but the consumer/hub relative to
`ikarus_act`/`ikarus_chat`** (those two exist to be called by it and have no
other family importer measured in this scope). My vote: the `ikarus_*` family
is **not** one tightly-coupled package today — the 9 files split into at
least two clusters with no measured cross-imports between them
(`ikarus_os`+`ikarus_act`+`ikarus_chat` vs. the unconnected
`ikarus_effect_bridge`/`ikarus_oneshot`/`ikarus_runtime_events`/
`ikarus_runtime_role`/`ikarus_supervisor`/`ikarus_tool_scope`, which this
module never touches). Under a single-package option, `ikarus_os` would be
the package's dispatch entrypoint; under a several-destinations option, it
goes to `daedalus.orchestration` specifically (with `ikarus_act`/`ikarus_chat`
following it as its direct dependencies), while the unconnected siblings are
each a separate classification question this dossier does not resolve.

## Boundary-rule verdict after the move

**(a) As SOURCE** (would `daedalus.orchestration.ikarus_os`'s own imports be
refused by any rule?): **N-A-not-a-rule-source.** `daedalus.orchestration` is
not one of the four rule `source_prefixes` (`daedalus.kernel`,
`daedalus.runtimes`, `daedalus.spine`, `daedalus.twin`); per the contract's
own design (and the task brief), a module landing in `daedalus.orchestration`
or `daedalus.interfaces.*` is not a rule source, so none of the four rules
constrain what `ikarus_os` imports once moved there, regardless of its 48
`daedalus.*` import statements measured above.

**(b) As TARGET** (does any current importer live under
`daedalus.kernel`/`spine`/`twin`/`runtimes`, and would that importer's rule
refuse the new `daedalus.orchestration.ikarus_os` prefix?): checked all 3
non-test importers — `daedalus/conversation_requests.py` (root, flat),
`daedalus/interfaces/http/sse.py` (`daedalus.interfaces.http`),
`daedalus/web_api.py` (root, flat). **None sit under
kernel/spine/twin/runtimes today**, so none of the four rules currently fire
against any importer, before or after the move — no rule id applies.

**`spine-no-outer-layers` already names `daedalus.ikarus_os` explicitly** in
its `forbidden_target_prefixes` (alongside `daedalus.ikarus`,
`daedalus.orchestration`, `daedalus.web_api`, `daedalus.file_bridge`, etc.),
per `docs/architecture/import-boundaries.json` and confirmed live in
`tests/contracts/test_spine_outer_ports.py:82`'s `FORBIDDEN_PREFIXES` tuple.
Implication for the destination: this entry is already redundant coverage —
`daedalus.orchestration` is separately and independently forbidden in the
same list, so once `ikarus_os` moves under `daedalus.orchestration`, any
future `daedalus.spine` import of it is still caught by the pre-existing
`daedalus.orchestration` prefix even after the now-stale flat
`daedalus.ikarus_os` string is deleted from the rule. This is corroborating
evidence, not new risk: the rule's authors had already classified
`ikarus_os` as belonging to the same "outer layer" bucket that
`daedalus.orchestration` occupies, before this dossier was written.

**CLEAN** — (a) N-A-not-a-rule-source as source; (b) zero current importers
sit in a rule-source layer, so no rule is refused as target either. The one
relevant pre-existing rule entry (`spine-no-outer-layers` naming
`daedalus.ikarus_os`) becomes redundant-but-harmless after the move, already
covered by its sibling `daedalus.orchestration` entry.

## Dead-code signals

Not applicable in the strong sense — this is not zero/low-importer. **15
distinct files import it, 25 import statements, including 3 non-test
production call sites** (`conversation_requests.py`, `interfaces/http/sse.py`,
`web_api.py`) and 12 dedicated test files, one of which
(`tests/test_ikarus_os_boundary.py`) exists solely to exercise this module's
boundary behavior across 11 separate test functions. The module's own
docstring is explicit about being a promised, actively-read seam: *"WHAT THIS
IS. `daedalus/ikarus_os.py` is the assistant seam..."* is quoted back at it
from `daedalus/conversation.py:3`, and `daedalus/ikarus_act.py`'s docstring
names `daedalus.ikarus_os.classify` as the function whose output it consumes
(`:func:`daedalus.ikarus_os.classify` answers exactly one question`). It is
also a named eval target: `daedalus/eval/minted_tasks.json:125` and
`daedalus/eval/tasks.py:259` (`"target": "daedalus/ikarus_os.py::_distill"`)
reference it by path. Deletion would not be safe — it is the live entrypoint
`web_api.py` and `interfaces/http/sse.py` call for every chat/status/distill
request, and 22 test import statements would break immediately.

## Confidence

**High.** Importer and import enumeration are both exhaustive AST/grep sweeps
scoped correctly (verified the worktree double-count trap does not apply:
zero hits outside `daedalus`, `tests`, `tools`), the boundary-rule semantics
are read directly from `tools/architecture_boundaries.py:253-299` and the
contract JSON rather than inferred, and the family-coupling claim is a
negative result confirmed by grepping all 8 sibling files individually for
back-references. Confidence would rise only with clarity on where
`conversation_requests.py` itself lands (it is the one non-test, non-interface
importer and its own destination is out of scope here) and an owner decision
on whether the disconnected `ikarus_*` siblings (`ikarus_supervisor`,
`ikarus_effect_bridge`, etc.) are a second orchestration cluster or something
else entirely — both are genuinely open questions this single-module dossier
cannot resolve alone.
