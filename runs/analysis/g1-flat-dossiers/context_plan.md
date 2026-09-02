# daedalus/context_plan.py

## 1. Size and shape

624 lines (`wc -l daedalus/context_plan.py`).

- Classes: 4, all frozen dataclasses — `LexicalSeedResult` (context_plan.py:
  110-126), `LatentSeedResult` (245-284), `HybridSeedResult` (420-454),
  `ContextPlanningResult` (489-557). Each carries `to_dict()` (and
  `HybridSeedResult`/`ContextPlanningResult` carry computed `@property`
  helpers: `latent_applied`, `effective_latent_weight`, `answered`).
- Functions: 12 — `_canonical_json`(63), `_digest`(73), `_terms`(77),
  `_normalise_max`(86), `_symbol_names`(97), `lexical_seed_scores`(129),
  `_metadata_strings`(211), `_contains_explicit_path`(225),
  `latent_not_requested`(287), `latent_memory_seed_scores`(299),
  `fuse_seed_scores`(457), `plan_context`(560, the public entry point).
- Module-level state: constants only — `CONTEXT_PLAN_SCHEMA`,
  `LEXICAL_PROJECTOR_VERSION`, `LATENT_MAPPER_VERSION` (41-43),
  `LATENT_STATUS_*` string constants (49-51), two compiled regexes `_WORD`,
  `_CAMEL` (53-54), and a `frozenset` `_STOP` of stopwords (55-60). No
  singleton, no mutable registry, no cache dict.
- Import-time side effects: **none measured**. All six `daedalus.*` imports
  (see §4) are plain module-level bindings to other modules' names/classes;
  none of them execute I/O by themselves at `context_plan.py` import time
  (e.g. `VECTOR_DB_PATH` is a `Path` constant, not opened here). No file
  reads, env reads, network calls, or registry mutation happen merely by
  `import daedalus.context_plan`. (Whether importing `.memory` or
  `.providers.ollama` themselves have import-time effects is a question about
  those modules, out of scope for this file's own dossier.)

## 2. What it does

`plan_context()` builds a token-budgeted, evidence-bearing context plan for
one natural-language objective by combining a BM25 lexical seed computed over
the StructCore index's file paths and cached symbol names
(`lexical_seed_scores`) with an optional latent-memory seed drawn from
versioned event-vector projections that is only asked for when
`use_latent=True` and only counted when it can point back to an explicit file
path in the objective's evidence (`latent_memory_seed_scores`,
`_contains_explicit_path`). The two seed sources are fused by weighted
max-normalized scores (`fuse_seed_scores`) into one per-node score map, which
is handed to `structcore.dss.semantic_super_sample` together with the
`KnowledgeForest` and per-node token costs for deterministic graph propagation
and token-budget packing. Every stage of the computation — lexical query
terms and matches, the latent source's status/reason/candidate count, the
fusion weights actually applied, and the downstream DSS receipt — is
serialized into a canonical, SHA-256-stamped `ContextPlanningResult` so a
caller can distinguish "latent was never asked" from "latent was asked and
found nothing" and reproduce exactly the evidence that produced the selected
file set.

## 3. Who imports it (MEASURED)

Searched `daedalus/`, `tests/`, `tools/`, `runs/` (ad hoc experiment/AB
scripts), `docs/`, `.claude/` for all required forms. Distinguished real
module imports from mere textual mentions of the string "context_plan" —
several hits in `daedalus/structcore/{index,forest,dss}.py` and several
`tests/test_typegraph_*.py`/`tests/test_dss.py` lines are comments, docstring
prose, or references to `structcore.dss`'s **unrelated** `build_context_plan`
function / `ContextPlan` dataclass and its `.context_plan` attribute on
`DSSResult` — a same-named but different concept one layer down. Those are
excluded below as non-importers of this file.

**TOTAL real Python-import edges: 12**, across **11 distinct files** (one
file, `gui_catalogue.py`, imports it twice on two separate lines).

Per-layer breakdown:

- **flat (daedalus/, unclassified elsewhere), 3 files, 4 edges, all
  MODULE-LEVEL**:
  - `daedalus/web_api.py:35` — `from .context_plan import plan_context`.
  - `daedalus/gui_catalogue.py:109` — `from .context_plan import
    (LatentSeedResult, LexicalSeedResult, fuse_seed_scores,
    latent_not_requested, lexical_seed_scores)`.
  - `daedalus/gui_catalogue.py:119` — `from .context_plan import
    _normalise_max` (a second, deliberate import of a private helper;
    comment at gui_catalogue.py:120-123 explains it is intentional so there
    is exactly one max-normalization implementation).
- **flat, SCC-owned (`health`, do not classify, record edge only), 1 file, 2
  edges**:
  - `daedalus/health.py:1580` — `from . import context_plan` — **DEFERRED**
    (inside `_p_latent`, a health probe function that reads
    `context_plan.fuse_seed_scores`'s default `latent_weight` to check the
    weight describes a live source).
  - `daedalus/health.py:1744` — bare string `"daedalus.context_plan"` inside
    the module-level `CAPABILITY_MODULES` tuple (health.py:1730-1745) —
    **MODULE-LEVEL string, not an import statement**. This is health.py's own
    "capability island" watchlist (`_p_islands` probe, health.py:1831-1863):
    it re-derives production importers by regex over the whole tree at
    runtime and would report `daedalus.context_plan` as an "island" (zero
    production callers) if the edges above ever disappeared. Today it will
    **not** flag it as an island: `production_importers()`
    (health.py:1794-1828) matches `web_api.py`, `gui_catalogue.py`, and
    `interfaces/http/read.py` below by the same "leaf in path / leaf in
    import list" regex forms this dossier used. This is corroborating,
    independently-computed evidence that the module is wired, not a
    dead-code signal.
- **existing package `interfaces/http`, 1 file, 1 edge, MODULE-LEVEL**:
  - `daedalus/interfaces/http/read.py:19` — `from ...context_plan import
    plan_context`.
- **tests/, 5 files, 5 edges**:
  - `tests/test_context_plan.py:5` — MODULE-LEVEL, `from
    daedalus.context_plan import (...)`.
  - `tests/test_context_plan_latent.py:15-16` — MODULE-LEVEL, `import
    daedalus.context_plan as context_plan` plus a `from daedalus.context_plan
    import (...)`.
  - `tests/test_typegraph_regression.py:68` — MODULE-LEVEL, `from
    daedalus.context_plan import _symbol_names, lexical_seed_scores`.
  - `tests/test_markdown_nodes.py:864` — **DEFERRED**, `from
    daedalus.context_plan import plan_context` inside a test method.
  - `tests/test_projection_worker.py:346` — **DEFERRED**, `from
    daedalus.context_plan import latent_memory_seed_scores` inside a test
    method.
- **runs/ (ad hoc, outside daedalus/tests/tools/apps), 1 file, 1 edge**:
  - `runs/ab/run_arm.py:71` — **DEFERRED**, `from daedalus.context_plan
    import plan_context  # type: ignore`, inside `distilled_context()`; an
    A/B experiment script comparing a "distilled context" arm against a
    baseline, hardcoded to a `C:\Users\nukei\Desktop\PnP_App` path — not part
    of the product or its test suite.

Non-importer mentions excluded (verified by reading, not counted above):
`daedalus/structcore/index.py:130,900`, `daedalus/structcore/forest.py:299`,
`daedalus/structcore/dss.py` (multiple — these define `build_context_plan`/
`ContextPlan`, a same-named different construct), `daedalus/memory/
projection_worker.py:56` (docstring prose), `daedalus/runtimes/execution/
budget_process.py:291` (comment), `tests/test_dss.py`,
`tests/test_typegraph_forest.py`, `tests/test_typegraph_fixture.py`,
`tests/test_typegraph_index.py`, `tests/test_gui_catalogue.py`,
`tools/system_check.py:314` (dict-key access on a JSON payload, not an
import), `tools/self_test.py:221` (writes to the file path in a sandbox
fixture, not an import), `tools/gate_discrimination.py:608` (docstring
prose).

## 4. What it imports (MEASURED)

All 6 `daedalus.*` import statements are **MODULE-LEVEL** (context_plan.py:
28-38). No third-party imports anywhere in the file (only stdlib:
`collections.Counter`, `dataclasses`, `hashlib`, `json`, `math`, `re`,
`pathlib.Path`, `typing`).

- **existing package `memory` (2 edges)**:
  - context_plan.py:28 — `from .memory import VECTOR_DB_PATH`.
  - context_plan.py:29-34 — `from .memory.embeddings import (EMBED_MODEL,
    EmbeddingBackend, EventVectorStore, ProjectionFilter)`.
- **existing package `providers` (1 edge)**:
  - context_plan.py:35 — `from .providers.ollama import DEFAULT_HOST` (a
    constant only — no live Ollama call is made from this file).
- **existing package `structcore` (3 edges — the twin/spine-allowlisted
  package)**:
  - context_plan.py:36 — `from .structcore.dss import (DSSConfig, DSSResult,
    semantic_super_sample)`.
  - context_plan.py:37 — `from .structcore.forest import (KnowledgeForest,
    build_knowledge_forest)`.
  - context_plan.py:38 — `from .structcore.index import (cached_index,
    resolution_context)`.

No SCC-owned targets, no foundation targets, no kernel/spine/twin/runtimes/
orchestration package targets are imported by this file.

## 5. Proposed destination

**`orchestration`**.

Argument from measured edges:

- This file has **no kernel/spine/twin semantics** at all — it does not touch
  Mission, Attempt, Evidence, EffectLease, or promotion contracts, and
  nothing under `daedalus/kernel/` or `daedalus/spine/` imports it (§3: zero
  edges from those packages, either direction). It is a pure, read-only
  retrieval/ranking computation over already-built `KnowledgeForest`/
  `structcore` data plus an optional memory-projection lookup.
- Its role matches, almost by name, a concept the master plan itself names as
  orchestration's job: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` §7 has Ikarus
  "compile a minimal Context Capsule from verified project evidence" and §8
  step 4 of the Ariadne campaign loop is literally "Compile a minimal Context
  Capsule from verified project evidence" — that is exactly what
  `plan_context()` does: turn an objective plus verified Forest/memory
  evidence into a token-budgeted, receipted context selection. It is
  consumed by the CLI's `context` subcommand (`cli.py:281`, itself proposed
  for `interfaces/cli` — see the sibling dossier), by `web_api.py` and
  `interfaces/http/read.py` (the HTTP surface's `context`-planning route),
  and by `gui_catalogue.py` (documentation/reference generation) — i.e. by
  every interface that needs to hand a bounded, explainable context slice to
  an LLM call, which is an orchestration-layer responsibility, not a
  twin-layer one (twin defines/serves the Forest; this file is a *client* of
  the Forest).
- Boundary evidence rules out `twin` concretely (§6): if this file moved to
  `daedalus.twin`, its imports of `.memory` (2 edges) and `.providers.ollama`
  (1 edge) — 3 of its 6 total import edges — would be **refused** by
  `twin-no-outer-layers`'s allowlist (`kernel`, `spine`, `structcore` only).
  That is a hard, measured disqualification, not a style preference.

Confidence: **medium-high**. `orchestration` is not itself constrained by any
rule today (§6), so nothing *forces* this answer the way twin's allowlist
forces twin out — the choice between `orchestration` and leaving it as a
flat foundation-adjacent "retrieval service" module is partly architectural
taste. What would change my mind: if a future hierarchy packet introduces a
distinct "retrieval" or "twin-services" bucket sitting between `twin` and
`orchestration` (a plausible reading of §6's Latent Atlas material in the
master plan, which is explicitly a "hypothesis machine" distinct from both
the Forest and the mission orchestrator) — that bucket, if it existed, would
be a better fit than `orchestration` and I'd retarget there instead.

**Is this really two things fused?** Mildly. `lexical_seed_scores` +
`_terms`/`_symbol_names`/`_normalise_max` (a pure BM25 ranker over
`structcore` index data, no memory dependency) is cleanly separable from
`latent_memory_seed_scores` + `_metadata_strings`/`_contains_explicit_path`
(the `.memory`-dependent latent half) and `fuse_seed_scores` (the glue). If a
future packet wants `twin` to own pure lexical/BM25 ranking as a twin-native
query capability (it only needs `structcore`, which twin's allowlist
permits), the natural split boundary is exactly the existing
`LexicalSeedResult` vs. `LatentSeedResult` vs. `HybridSeedResult` dataclass
seam (context_plan.py:110, 245, 420) — `lexical_seed_scores` and its helpers
could move to `twin`, while `latent_memory_seed_scores`, `fuse_seed_scores`,
`plan_context`, and `ContextPlanningResult` (which needs both memory and the
DSS token-packing call) stay in `orchestration`. Not proposed as this
packet's answer — the whole file is one coherent, actively-tested unit today
(`tests/test_context_plan.py`, `tests/test_context_plan_latent.py`) — but
flagged because the seam already exists in the code, unforced.

## 6. Boundary-rule check after the move

Read `docs/architecture/import-boundaries.json`. Only `kernel`, `spine`,
`twin`, `runtimes` have rules; there is **no `orchestration`-sourced rule**
today.

**(a) Would any of context_plan.py's own imports be refused under
`orchestration`?** No — there is no rule with `source_prefixes` matching
`daedalus.orchestration`, so none of its 6 edges (`memory` x2, `providers`
x1, `structcore` x3) are refused.

For contrast, concretely quantifying why the other three constrained layers
were rejected:
- **`kernel`**: `kernel-no-outer-layers`'s allowlist is `atomic, budget,
  config, limit_policy, offload, primary_tree, sensitivity, spine, storage,
  twin` — `memory`, `providers`, and `structcore` are **all three absent**
  from that allowlist, so all 6 edges would be refused.
- **`spine`**: `spine-no-outer-layers`'s allowlist is `atomic, budget,
  config, kernel, limit_policy, mapping, sensitivity, structcore` — `memory`
  and `providers` are absent (3 edges refused: context_plan.py:28,29-34,35);
  `structcore` is present, so those 3 edges (36,37,38) would survive.
- **`twin`**: `twin-no-outer-layers`'s allowlist is `kernel, spine,
  structcore` — same result as spine: `memory`/`providers` edges (3 of 6)
  refused, `structcore` edges (3 of 6) survive. Named explicitly in §5 as the
  decisive disqualifier.

**(b) Does any current rule name this module by prefix?** No rule names
`daedalus.context_plan` directly. But moving it under `daedalus.orchestration`
has a real, if currently inert, consequence: `kernel-no-outer-layers`,
`spine-no-outer-layers`, and `twin-no-outer-layers` **all already forbid**
`daedalus.orchestration` as a target prefix. Today, with `context_plan.py`
flat, nothing in the rule set stops `daedalus.kernel`, `daedalus.spine`, or
`daedalus.twin` from importing `daedalus.context_plan` (no rule names it, so
by the allowlist logic in kernel/spine/twin it would simply be an
unenumerated flat module — refused too, actually, since kernel/spine/twin use
allowlists and flat `context_plan` isn't on any of the three allowlists
either; so this is a lateral move from "refused because unenumerated" to
"refused because `daedalus.orchestration` is explicitly forbidden," not a
tightening in practice). No live importer today is `kernel`/`spine`/`twin`
sourced (§3), so this is prospective bookkeeping, not an active fix.

**(c) Allowlist exposure if landed in kernel/spine/twin?** Covered
exhaustively in (a) above — not the proposed destination, included for
completeness per the packet's requirement.

**(d) `orchestration` as SOURCE is unconstrained — explicitly.** No rule in
`import-boundaries.json` restricts what `daedalus.orchestration.*` may
import. Moving `context_plan.py` there does **not** launder anything:
`memory` and `providers` were never forbidden targets for *any* rule's
source set at `context_plan.py`'s current flat position either (no rule
names flat `daedalus.context_plan` as a source at all today), so enforcement
exposure is unchanged before/after — neither position is, or was, blocked
from reaching `memory`/`providers`/`structcore`. The move is boundary-neutral
in the same sense §6(d) of the sibling `cli.md` dossier describes for
`interfaces/cli`.

## 7. Dead-code signals

Not dead. **LIVE**, with unusually strong corroboration.

- 4 distinct production files import it at module level outside tests
  (`web_api.py`, `gui_catalogue.py` ×2, `interfaces/http/read.py`), plus one
  SCC-owned production file (`health.py`, deferred).
- `daedalus/health.py`'s own `CAPABILITY_MODULES` watchlist
  (health.py:1730-1745) explicitly names `"daedalus.context_plan"` as a
  module the repo's *own* automated "capability island" health probe
  (`_p_islands`, health.py:1831) checks for zero-production-caller status at
  every `daedalus health` run — and, per the regex forms in
  `production_importers()` (health.py:1794-1828), it would currently report
  ≥3 production importers, i.e. **not** an island. This is independent,
  automated, already-running evidence, not something derived just for this
  dossier.
- Two dedicated test files exist and are non-trivial:
  `tests/test_context_plan.py`, `tests/test_context_plan_latent.py`, plus
  cross-cutting coverage from `tests/test_markdown_nodes.py`,
  `tests/test_projection_worker.py`, `tests/test_typegraph_regression.py`.
- `git log --diff-filter=A --format=%ad -- daedalus/context_plan.py` → first
  added 2026-07-28; `git log -- daedalus/context_plan.py` shows an active
  commit history through `374a915b fix(context): the receipt showed a weight
  for a source that never spoke`, i.e. bugs were still being fixed in it
  recently, not just left in place.
- The only non-product consumer found, `runs/ab/run_arm.py`, is a one-off A/B
  experiment script hardcoded to an unrelated local path
  (`C:\Users\nukei\Desktop\PnP_App`) — evidence the module is useful enough
  to be reached for outside the repo's own test/product tree, not evidence
  of dead code.

Label: **LIVE**.
