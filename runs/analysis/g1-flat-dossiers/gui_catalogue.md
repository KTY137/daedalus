# daedalus/gui_catalogue.py

## 1. Size and shape

1015 lines (`wc -l daedalus/gui_catalogue.py` = 1015). 8 classes, 11
top-level functions, 24 methods, 7 `@dataclass`-decorated classes
(`grep -c '^class '` = 8, `grep -c '^def '` = 11, `grep -c '^    def '`
= 24, `grep -c '@dataclass'` = 7):

- `class CatalogueError(ValueError)` — `:241`
- `@dataclass class PropSpec` — `:272` (a prop entry: `name`, `type`,
  `required`, `default`, `description`)
- `@dataclass class Provenance` — `:309` (`origin`, `url`, `retrieved`,
  `source_path`, `note`)
- `@dataclass class CatalogueEntry` — `:352` (the core record: name, kind,
  title, purpose, licence, provenance, props, dependencies, tags, etc.)
- `@dataclass class RejectedEntry` — `:473` (retained-refusal record)
- `@dataclass class Catalogue` — `:490` (the loaded corpus: `entries`,
  `rejected`, `sources`)
- `@dataclass class SearchHit` — `:842`
- `@dataclass class SearchResult` — `:848`
- top-level functions: `use_mode_for_licence`, `_string_tuple`,
  `_parse_props`, `_parse_provenance`, `parse_entry`, `load_catalogue`,
  `_search_key`, `_lexical`, `_latent`, `search`, `render_for_prompt`.

**Module-level state, MEASURED (not assumed — the task explicitly flagged
this file as a prime candidate for import-time reads and asked for
careful checking):**

Ran `awk` over every line matching module-scope (column-0) executable
syntax that is not a `class`/`def`/`import`/`from` statement or part of
the docstring. Result: **zero import-time file reads, zero import-time
`os.environ` reads, zero registry mutation, zero network calls, zero path
creation.** The only module-level executable statements are static literal
assignments:

- `__all__` (`:125-145`)
- `CATALOGUE_SCHEMA = "daedalus-gui-catalogue/1"` (`:150`)
- `CATALOGUE_DIR = "catalogue/gui"` (`:153`, a relative-path *string*, not
  a `Path` object — never resolved or touched at import)
- `ENTRY_KINDS: tuple[str, ...]` (`:161-176`, 7-element closed enum)
- `USE_MODES: tuple[str, ...]` (`:180-184`, 3-element closed enum)
- `LICENCE_USE_MODE: Mapping[str, str]` (`:195-225`, a 17-entry static
  licence→use-mode policy table — this is real, hand-maintained POLICY
  DATA embedded in code, not a side effect)
- `DERIVED_FIELDS: frozenset[str]` (`:231`)
- `REQUIRED_FIELDS: tuple[str, ...]` (`:234`)
- `_NAME_RE = re.compile(...)`, `_DATE_RE = re.compile(...)` (`:236-238`,
  CPU-only regex compilation, no I/O)
- `_ALLOWED_KEYS: frozenset` (`:608-611`)
- `_FENCE_OPEN`, `_FENCE_CLOSE` string constants (`:963-964`)

**Disconfirming the task's own hint:** `load_catalogue()` (the function
that actually performs `read_text()` on `catalogue/gui/*.json`, `:661`) is
never called at module scope — it is only ever called from a caller
(`daedalus/interfaces/http/read.py:203`, `tools/smoke_packaged_resources.py`,
tests). Measured, not assumed: this module does **no** file I/O, `.env`,
or environment reads at import time, unlike what the task's framing
suggested might be likely. The only import-time cost is building static
Python literals and compiling two small regexes.

## 2. What it does

`daedalus/gui_catalogue.py` defines and loads a schema for a GUI-component
catalogue (`CatalogueEntry`/`Provenance`/`PropSpec`), refusing at
construction, parse, and load time any entry missing a licence or
provenance, or one that tries to declare its own `use_mode` (a value
always DERIVED in code from `LICENCE_USE_MODE`, never trusted from a
file). It ranks catalogue entries against a plain-language build objective
by delegating lexical scoring to the repo's one BM25 implementation
(`daedalus.context_plan.lexical_seed_scores`), optional latent scoring to
the repo's one embedding store (`daedalus.memory.embeddings.EventVectorStore`),
and fusion to `daedalus.context_plan.fuse_seed_scores` — the module's own
docstring is explicit that it implements zero ranking arithmetic of its
own (`:59-83`). It renders selected entries into a fenced, notice-prefixed
prompt block via `render_for_prompt()`, the one path by which this
untrusted third-party text can ever reach a model, reusing
`daedalus.council.vendors.PROMPT_DATA_NOTICE` rather than duplicating it.

## 3. Who imports it (MEASURED)

**TOTAL: 4 importers**, all git-tracked. Commands run:

```
rg -n 'daedalus\.gui_catalogue\b|from \.gui_catalogue import|from \.\.gui_catalogue import|from \. import gui_catalogue\b|from \.\.\. import gui_catalogue\b' --glob '*.py'
rg -n 'gui_catalogue' tests/*.py
```

| Importer | Line | Form | MODULE-LEVEL / DEFERRED | Layer |
| --- | --- | --- | --- | --- |
| `daedalus/interfaces/http/read.py` | `:201` | `from ... import gui_catalogue` (used at `:203,208`) | **DEFERRED** — inside the `elif path == "/api/catalogue":` branch of `do_GET`, deliberately lazy so the lexical-only path stays importable without the vector-store machinery, per an in-line comment | `daedalus.interfaces.http` |
| `tools/smoke_packaged_resources.py` | `:37` | `from daedalus.gui_catalogue import load_catalogue` | DEFERRED | tools/ |
| `tests/test_gui_catalogue.py` | `:39` | `from daedalus import gui_catalogue as gc` | MODULE-LEVEL, TEST-ONLY | tests/ |
| `tests/test_packaged_resources.py` | `:9` | `from daedalus import agents_registry, categories, config, gui_catalogue, router` | MODULE-LEVEL, TEST-ONLY | tests/ |

Matches the task's own AST census (4: `interfaces/http/read.py:201`
DEFERRED, tests 2, `tools/smoke_packaged_resources.py:37` DEFERRED).
`tests/test_web_api_catalogue.py` also references `gui_catalogue`
extensively (its own docstring: `":gui_catalogue.py`` was reachable from
nothing but its own test. This pins the one route that reads it..."`,
`:1-5`) but does so via `daedalus.web_api.DaedalusHandler`
end-to-end/behavioral testing rather than a direct `gui_catalogue` import
— it asserts, via AST inspection of the live source
(`test_web_api_catalogue.py:242-257`), that exactly one
`gui_catalogue.search` call site exists in `read.py`, which is corroborating
evidence for the "one deliberate reader" design, not a fifth import edge.

## 4. What it imports (MEASURED)

**Module-level (4 edges, all `daedalus.*`, all within package via relative
import):**

| Target | Line | Layer (current/likely) |
| --- | --- | --- |
| `.context_plan` (`LatentSeedResult`, `LexicalSeedResult`, `fuse_seed_scores`, `latent_not_requested`, `lexical_seed_scores`) | `:109-115` | flat `daedalus/` (context-ranking; likely orchestration-bound) |
| `.context_plan._normalise_max` (private, deliberately imported rather than re-implemented) | `:119` | flat `daedalus/` |
| `.council.vendors.PROMPT_DATA_NOTICE` | `:122` | `daedalus.council` (package) |
| `.resources.iter_builtin_files` | `:123` | `daedalus.resources` (package) |

**Deferred (3 edges):**

| Target | Line | Reason for deferral | Layer |
| --- | --- | --- | --- |
| `.memory.VECTOR_DB_PATH` | `:775` | inside `_latent()`; keeps the lexical-only path importable with no vector DB present | `daedalus.memory` (package) |
| `.memory.embeddings.EMBED_MODEL, EventVectorStore` | `:776` | same function, same reason | `daedalus.memory` (package) |
| `.providers.ollama.DEFAULT_HOST` | `:924` | inside `search()`, only reached when `use_latent=True` | `daedalus.providers` (package) |

**Third-party:** none. **Stdlib:** `json`, `re`, `dataclasses`
(`dataclass`, `field`), `pathlib.Path`, `typing` (`Any`, `Iterable`,
`Mapping`, `Sequence`).

Grouped by target layer: 2 edges into flat `daedalus/context_plan`
(1 module-level function-group import + 1 private-name import, both at
the same line-range, both from the same module), 1 into
`daedalus.council`, 1 into `daedalus.resources`, 2 into `daedalus.memory`
(both deferred), 1 into `daedalus.providers` (deferred). Total 7 distinct
import statements naming 4 distinct target modules/packages, none of them
kernel/spine/twin/runtimes/foundation.

## 5. Proposed destination

**orchestration.** Confidence: **medium**.

This directly answers the established-fact framing: **`gui_catalogue.py`
is a data-and-search catalogue, not an `interfaces/http` concern** — the
HTTP route is one deliberately narrow, deferred, single caller wrapped
around a module whose own substance (a 1015-line schema, a hand-maintained
licence policy table, dataclass-based parsing/validation/refusal, and
BM25+embedding search composition) has nothing to do with HTTP semantics.
Argument from measured edges (§4): every one of its module-level and
deferred imports targets `context_plan` (LLM-context ranking),
`council.vendors` (multi-vendor LLM prompt-safety notice), `memory`
(embedding/RAG store), and `providers.ollama` (LLM provider client) — this
is exactly the same dependency neighborhood as the repo's other
LLM-facing product-intelligence code, which is the orchestration layer's
job description (per the master plan §7: "the orchestration layer answers
who works, with which runtime, context, capabilities"). It is not a
`daedalus/resources/`-style generic packaged-defaults resolver either: it
*consumes* `daedalus.resources.iter_builtin_files` (§4) rather than
duplicating or extending that role — `daedalus/resources/__init__.py`
(read in full) is a narrow, generic "packaged file with legacy-mirror
drift check" resolver used by many callers (`schemas/`, `agents/`,
`templates/`, `catalogue/gui/`); it owns *how bytes are found on disk*,
while `gui_catalogue.py` owns *what a GUI-component catalogue entry means,
how it is validated, and how it is ranked* — two different
responsibilities that happen to share one utility call. `daedalus/gui/`
(the other candidate the established facts flagged) is unrelated on
inspection: `git ls-files daedalus/gui/*.py` → only `__init__.py` and
`lint.py`, and `grep -rn "gui_catalogue\|catalogue" daedalus/gui/*.py` →
no output. Neither existing package already owns this module's role.

What would change my mind: if `context_plan.py`, `council/`, and
`memory/` are themselves later classified as something other than
`orchestration` (e.g. a dedicated "intelligence"/"retrieval" layer outside
the eight buckets given to this task), `gui_catalogue.py` should follow
them rather than sit in `orchestration` alone — its destination is
derivative of theirs, not independently argued. Confidence is medium
rather than high specifically because "orchestration" is a broad bucket
being asked to also hold scheduling/workflow logic (`kairos`,
`fallback.py` — see the sibling `fallback.md` dossier) as well as this
data-catalogue-plus-search-composition module; the two are related only
by both depending on non-foundation flat modules, not by any shared
runtime behavior.

**Split boundary, if this module were ever split:** it is coherent as one
file (schema + refusal + search + prompt-rendering, all about the same
catalogue), but if a split were ever wanted, the natural seam is between
(a) the schema/parsing/refusal machinery (`PropSpec`, `Provenance`,
`CatalogueEntry`, `RejectedEntry`, `Catalogue`, `parse_entry`,
`load_catalogue`, `LICENCE_USE_MODE`) — which has **zero** dependency on
`context_plan`/`memory`/`providers`/`council` and could live anywhere,
including alongside `daedalus.resources` — versus (b) the search/ranking
composition (`_search_key`, `_lexical`, `_latent`, `search`,
`SearchHit`/`SearchResult`) and prompt rendering (`render_for_prompt`,
which pulls in `council.vendors`) — which is the half that actually
belongs in orchestration. Not proposing this split; flagging it as the
measured fault line if the destination is ever revisited.

## 6. Boundary-rule check after the move

**(a) Moved to `orchestration`: would any of its own imports be refused?**
No rule sources `daedalus.orchestration` today — the four rules in
`docs/architecture/import-boundaries.json` only source `kernel`,
`runtimes`, `spine`, `twin` (confirmed by reading every rule's
`source_prefixes`). So none of `gui_catalogue.py`'s 7 import statements
(§4) would be evaluated by any current rule if the module's prefix became
`daedalus.orchestration.*`.

**(b) Does any CURRENT rule name this module by prefix?** No.
`daedalus.gui_catalogue` appears nowhere in any rule's `source_prefixes`,
`forbidden_target_prefixes`, or `allowed_target_prefixes` (confirmed by
reading the full `import-boundaries.json`, including the single
`baseline` entry, which names only `daedalus.offload`). No move changes
any rule's behavior today.

**(c) If it lands in kernel/spine/twin: enumeration.** Not the proposed
destination, but the task marks this section mandatory for the strongest
foundation candidate (`env.md`) and useful context here for contrast.
If `gui_catalogue.py` were hypothetically placed under any of the three:
- `kernel-no-outer-layers` allowlist (`atomic, budget, config,
  limit_policy, primary_tree, sensitivity, spine, storage, twin`): **all
  4 of its target modules would be REFUSED** — `daedalus.context_plan`,
  `daedalus.council`, `daedalus.resources`, `daedalus.memory`, and
  `daedalus.providers` (5 distinct prefixes across 7 import lines) are
  none of them in that list.
- `spine-no-outer-layers` allowlist (`atomic, budget, config, kernel,
  limit_policy, mapping, sensitivity, structcore`): same 5 prefixes, **all
  REFUSED** — none appear in this allowlist either, and `daedalus.memory`/
  `daedalus.providers` specifically are the kind of outer-layer target
  this rule's own rationale text calls out as exactly what it exists to
  keep out.
- `twin-no-outer-layers` allowlist (`kernel, spine, structcore`): same 5
  prefixes, **all REFUSED**.

Any of these placements would require widening the corresponding
allowlist by 5 entries, each a reviewed diff against
`tests/test_architecture_boundaries.py::test_the_allowlists_cannot_grow_quietly`
(`:344-386`) per rule touched — a real and substantial cost, which is
itself strong corroborating evidence *against* a kernel/spine/twin
placement and *for* orchestration (§5), where no such rule or pin exists
to violate.

**(d) Does any rule constrain `daedalus.interfaces` as a SOURCE?** No —
confirmed by reading all four rules; `daedalus.interfaces` never appears
as a `source_prefixes` entry. This is the crux of the "does an
`interfaces/*` move launder a forbidden prefix" question the task asks:
**today, no — there is nothing to launder, because no rule currently
governs any `daedalus.interfaces.*` module's own imports at all.** Placing
`gui_catalogue.py` under `daedalus.interfaces.http` would not violate any
present mechanical check, since `daedalus.context_plan`/`council`/
`memory`/`providers` are not in any *current* forbidden-target list for an
interfaces source (there is no interfaces source rule to have such a
list). But this is exactly why (a) that placement would be an
architectural misclassification even though it is not a *caught* one, and
(b) it is a live risk for a *future* interfaces boundary rule: if one is
added later (mirroring kernel/spine/twin, per this task's own target
layout naming `interfaces/{cli,http,bridge,desktop}` as a peer of
kernel/spine/twin), it would almost certainly need to forbid exactly the
orchestration-layer prefixes `gui_catalogue.py` currently imports
(`context_plan`, `memory`, `providers`, `council`) — at which point a
`gui_catalogue.py` that had been moved into `interfaces/http` would need
either a second migration or a widened interfaces allowlist, the same
kind of two-step churn the `foundation`-vs-`kernel/spine/twin` allowlist
argument in (c) is meant to avoid up front. Recommending `orchestration`
now avoids manufacturing that future migration.

## 7. Dead-code signals

**LIVE**, and deliberately, narrowly so — not CANDIDATE-DELETE, not
UNWIRED. `daedalus/interfaces/http/read.py:162-208` wires
`GET /api/catalogue` directly to `gui_catalogue.load_catalogue()` and
`gui_catalogue.search()`, with an extensive in-line comment
(`:163-179`) stating this is "the one reader of that module outside its
test" and explaining the deliberate design choices (pure-read GET with no
`effect_boundary` row, `use_latent` hard-pinned False so the route never
opens the vector store, rejected entries riding along with accepted ones
so refusals stay visible). `tests/test_web_api_catalogue.py`'s own module
docstring independently corroborates this exact history: *"`gui_catalogue.py`
was reachable from nothing but its own test. This pins the one route that
reads it..."* (`:1-5`) — i.e. this route was added specifically to close
what had been a real UNWIRED gap, and the fix is dated (git-log-visible)
and tested by a dedicated `CatalogueRouteIsPureReadTest` plus an
AST-based single-call-site assertion (`test_web_api_catalogue.py:242-257`).
`tools/smoke_packaged_resources.py:37` exercises `load_catalogue()`
against the packaged-wheel resource path as a smoke check, and
`tests/test_packaged_resources.py` and `tests/test_gui_catalogue.py`
provide direct unit coverage.

What I searched for a promised reader beyond the measured callers, per the
task's §7 requirement (mostly to confirm there is no *broader* promised
surface than the one deliberate route, since the module's own docstring
explicitly disclaims wanting more callers):
- `pyproject.toml`: `grep -n -i "catalogue" pyproject.toml` → one hit,
  `"daedalus.resources" = [..., "catalogue/gui/*.json" (implied by the
  package-data glob for `catalogue/**`)]` under `[tool.setuptools.package-data]`
  — this packages the JSON *data* files `gui_catalogue.py` reads, not the
  module itself as a script; no `[project.scripts]` entry names
  `gui_catalogue`.
- `docs/architecture/shim-registry.json`: `grep -n "gui_catalogue"
  docs/architecture/shim-registry.json` → no output. Not a registered
  shim.
- `daedalus/spine/effect_boundary.py` registered CLI-target strings:
  `grep -n "daedalus\.gui_catalogue\|\"gui_catalogue\"\|'gui_catalogue'"
  daedalus/spine/effect_boundary.py` → no output. Consistent with the
  module's own design: it is meant to be reachable only through the one
  pure-read HTTP route, never as an independent CLI door or an
  effect-boundary-guarded write path (the module docstring is explicit:
  "It executes nothing and imports nothing new... no network, no
  subprocess, and no writer," `:56-57,98-99`).
- git log: `git log --follow --diff-filter=A --format="%H %ad %s" --
  daedalus/gui_catalogue.py | tail -3` and
  `git log --format="%H %ad %s" -3 -- daedalus/gui_catalogue.py` both
  show active, recent history consistent with an intentionally-scoped,
  currently-maintained module (not a leftover) — the module's own
  docstring cites specific dated evidence (`MEASURED 2026-07-29`) and
  named ADRs (`ADR-002`, `ADR-017`) as its design rationale, which is the
  opposite signature of an abandoned module.

**Label: LIVE.** The "thin edge" framing in the established facts is
correct about *reachability breadth* (one deliberate caller) but the
module is not thin in substance, and it is not a dead or orphaned path —
it is a large, self-contained, licence-aware data catalogue with exactly
the single production reader its own design intended.
