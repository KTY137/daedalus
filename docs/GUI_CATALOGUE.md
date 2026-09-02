# GUI_CATALOGUE — component discovery as DATA

*Written 2026-07-29 against the rule set by `docs/ABSORPTION.md`,
`docs/adrs/002-hermes-upstream.md` and `docs/adrs/017-assistant-upstream.md`:*

> **Absorb formats and ideas. Do not absorb runtimes.**

The brief was: bring reactbits.dev-style component discovery into Daedalus, so
it can build GUIs from a catalogue rather than inventing components from
scratch. This document reports what the ecosystem actually offers, under which
licences, and what was built.

**The headline finding changes the brief.** React Bits — the library the idea
started from — is **not MIT**. It ships *"MIT + Commons Clause License
Condition v1.0"*, which forbids redistributing the components. Its source
cannot be copied into this repository. Neither can Aceternity's. That is not a
footnote; it is the reason this catalogue has a refusal path, and it is why
`use_mode` is computed in code from the licence rather than read from a file.

## Provenance of every claim

Same convention as `docs/ABSORPTION.md`, for the same reason.

- **MEASURED** — a command was run on this box on 2026-07-29 and its output is
  reported.
- **FETCHED** — read off a named URL on 2026-07-29. **Every FETCHED licence is
  a snapshot and must be re-checked before anyone acts on it.** Licences change;
  Origin UI's split and Tremor's acquisition are both in living memory.
- **UNVERIFIED** — stated and marked, never smoothed over.

---

## 1. What is actually out there

Four distribution shapes, and they have completely different cost profiles:

| shape | what you get | what it costs |
| --- | --- | --- |
| **copy-in** | source pasted into your repo, which you then own | zero runtime dependency; a licence question every time |
| **npm package** | a versioned dependency | a real dependency; usually no licence question |
| **hosted registry** | JSON served over HTTP, often with source embedded | nothing until you fetch; fetching is how you accidentally vendor |
| **marketplace** | community uploads behind a platform's ToS | the platform's licence is not the components' licence |

### The table

All licences FETCHED on 2026-07-29 by reading the project's own `LICENSE` file
or licence page. `use_mode` is what `daedalus/orchestration/gui_catalogue.py` derives.

| project | shape | licence (FETCHED) | manifest | runtime dep | `use_mode` |
| --- | --- | --- | --- | --- | --- |
| **shadcn/ui** | copy-in | **MIT** | **`registry.json` + published JSON Schema** | none | `copy_in` |
| **React Bits** | copy-in | **MIT + Commons Clause** (GitHub: `NOASSERTION`) | none official | none | **`reference_only`** |
| **Aceternity UI** | copy-in / paid | **custom "Aceternity License"** | live shadcn-format registry | `motion` | **`reference_only`** |
| **Magic UI** | copy-in | **MIT** | `registry.json`, shadcn format | `motion` per item | `copy_in` |
| **Radix Primitives** | npm | **MIT** | n/a | **yes** | `copy_in` |
| **Base UI** | npm | **MIT** | n/a | **yes** | `copy_in` |
| **Headless UI** | npm | **MIT** | n/a | **yes** | `copy_in` |
| **Ark UI** | npm | **MIT** | n/a | **yes** | `copy_in` |
| **Tremor** | both | **Apache-2.0** | via shadcn ecosystem | `@tremor/react` | `copy_in` |
| **MUI** | npm | **MIT core**; MUI X Pro/Premium **commercial EULA** | n/a | **yes** | `copy_in` (core only) |
| **Mantine / Chakra / Ant Design** | npm | **MIT** | n/a | **yes** | `copy_in` |
| **Origin UI** | copy-in | **AGPL-3.0** default, MIT carve-out for 2 dirs | redirect only (UNVERIFIED) | UNVERIFIED | **`reciprocal`** |
| **Motion Primitives / Cult UI / Kibo UI / Park UI** | copy-in | **MIT** | shadcn-format | varies | `copy_in` |
| **Skiper UI** | copy-in | **UNVERIFIED — no LICENSE located** | shadcn-format | varies | **`reference_only`** |
| **21st.dev** | marketplace | platform MIT; **component content proprietary** | API + MCP | per component | **`reference_only`** |

### The three traps, stated plainly

These are the entries that justify the whole design.

1. **React Bits — "MIT" is a prefix, not the licence.** FETCHED,
   `raw.githubusercontent.com/DavidHDev/react-bits/main/LICENSE.md`:
   > "MIT + Commons Clause License Condition v1.0 — Copyright (c) 2026 David
   > Haz … You may use this Software, including for any commercial purpose,
   > **so long as you do not sell, sublicense, or redistribute the components
   > themselves** — whether alone, in a bundle, or as a ported version."

   MEASURED: `gh api repos/DavidHDev/react-bits/license` returns
   `{"key":"other","spdx":"NOASSERTION"}` — GitHub's own detector refuses to
   call it MIT. A reader who pattern-matched the first three characters would
   have copied source whose licence forbids redistributing it.
   Also FETCHED: there is **no official registry.json and no official MCP
   server**; the MCP servers on npm are third-party wrappers unaffiliated with
   the author. And the npm package literally named `react-bits` is an
   **unrelated project** by a different author.

2. **Aceternity UI — fetchable is not licensed.** FETCHED,
   `ui.aceternity.com/licence`: permits building and selling end products,
   prohibits *"re-distributing the Item or source files."* Its registry is live
   and unauthenticated — MEASURED, `ui.aceternity.com/registry/wobble-card.json`
   returns full `.tsx` source with no auth. The CLI working is not permission.

3. **21st.dev — the permissive badge is on the neighbouring artifact.** The
   platform repos are MIT; FETCHED, `21st.dev/terms` states component *"code,
   content, and materials … are the sole and exclusive property of their
   respective authors and 21st Labs Inc."* MIT covers the tooling, not the
   marketplace content.

A fourth, softer one: **MUI** is MIT at the core and **commercial** for MUI X
Pro/Premium — mixed licensing inside one brand name.

### shadcn's registry: the format worth absorbing

This is the interesting case the brief flagged, and it holds up. FETCHED:

- `https://ui.shadcn.com/schema/registry.json` and
  `https://ui.shadcn.com/schema/registry-item.json` — real, published JSON
  Schema (draft-07), HTTP 200.
- `type` is a **12-value closed enum**: `registry:lib`, `registry:block`,
  `registry:component`, `registry:ui`, `registry:hook`, `registry:theme`,
  `registry:page`, `registry:file`, `registry:style`, `registry:base`,
  `registry:font`, `registry:item`.
- `https://ui.shadcn.com/r/index.json` — public, no auth, **62 items**, all
  `registry:ui`, **metadata only, no source**.
- `https://ui.shadcn.com/r/styles/new-york-v4/button.json` — the per-item URL,
  and it **embeds the complete `.tsx` source in `files[].content`**.
- `https://ui.shadcn.com/r/registries.json` — a directory of **253** registries
  speaking this schema. The closest thing to a neutral cross-library index, and
  it is not neutral: it indexes only shadcn-format registries, so Radix, MUI,
  Chakra, Mantine, AntD, React Bits, Origin UI and 21st.dev are all absent. **No
  index spanning both npm libraries and copy-in registries exists.**
- Licence: FETCHED, `LICENSE.md` is verbatim MIT, one repo-root file covering
  docs, CLI and the component source served in `files[].content`.

**Two things its schema provably lacks**, both verified by reading the schema
text itself:

- **No props/API field anywhere.** The closest thing is `meta.links.*.api`, a
  **URL to a third party's prose docs** (Base UI's, Radix's, React Aria's).
  Prop information is not machine-readable in the manifest at all — you either
  follow a link or parse the TypeScript yourself.
- **No licence and no provenance field.** For a first-party registry that is
  fine. For a catalogue that mixes fifteen upstreams with four different
  licence postures, it is the whole problem.

**So: adopt the field vocabulary, add the two missing fields, and do not fetch
the per-item URLs** — because `files[].content` is exactly how vendoring
happens by accident.

### Recommendation held back for a human, as instructed

shadcn/ui's registry JSON is MIT and its index is public and unauthenticated.
On the evidence above, **ingesting `r/index.json` metadata (names, types,
descriptions, dependencies — never `files[].content`) would be licence-clean.**
That is a real option and it would add ~62 well-described entries cheaply.

**It is not done here and I am not deciding it.** Two reasons, both worth a
human's attention: (i) it is still a third party's prose entering this repo in
bulk, which is a maintenance and re-verification commitment, not a one-time
copy; and (ii) the honest granularity question below is unresolved. The
evidence is on this page; the decision is not mine to take at 4am.

---

## 2. The schema

`catalogue/gui/*.json`. A superset of shadcn's `registry-item`, minus the
payload, plus the two fields that make an entry *choosable* and *accountable*.

The block below is the retired `glass/GlassSheet` entry, quoted from history as
a shape illustration because it exercises every field at once. **It is not a
live locator**: commit `e133e09b` deleted `apps/web/src/components/glass/` with
the Classic app, and G1-UI-04 removed the entry. Read it for the schema, not for
the path.

```json
{
  "name": "glass/GlassSheet",
  "kind": "layout",
  "title": "GlassSheet",
  "purpose": "A full glass overlay that slides up over the main content...",
  "licence": "Apache-2.0",
  "licence_url": "https://github.com/KTY137/daedalus/blob/main/LICENSE",
  "provenance": {
    "origin": "daedalus (this repository)",
    "url": "https://github.com/KTY137/daedalus",
    "retrieved": "2026-07-29",
    "source_path": "apps/web/src/components/glass/GlassSheet.tsx"
  },
  "props": [
    {"name": "open", "type": "boolean", "required": true},
    {"name": "onClose", "type": "() => void", "required": true}
  ],
  "dependencies": ["react", "framer-motion", "lucide-react"],
  "catalogue_dependencies": ["motion/tokens"],
  "tags": ["sheet", "overlay", "modal", "dialog", "scrim"],
  "usage": "<GlassSheet open={x} title=\"Code map\" onClose={close}>…</GlassSheet>",
  "notes": "Stays MOUNTED when closed… does NOT trap focus."
}
```

### What each field is for

| field | why a model needs it |
| --- | --- |
| `name` | stable identity; how `catalogue_dependencies` resolve |
| `kind` | closed vocabulary: `component`, `layout`, `primitive`, `hook`, `token`, `style`, `library` |
| `title` | the human name |
| `purpose` | **plain language, and the main thing search matches.** "What is this for", not "what is this called" |
| `props` | name, type, required, default, description — the field shadcn has no equivalent of |
| `dependencies` | npm packages this would ADD. A builder must see the cost |
| `catalogue_dependencies` | sibling entries; unresolved ones are reported, never guessed |
| `usage` | a minimal snippet, so choosing and using are one step |
| `licence` + `provenance` | **mandatory.** See below |
| `tags`, `notes` | search surface, and the honest caveats (`GlassSheet` does not trap focus) |

### The three properties that make it safe

**1. No licence or no provenance ⇒ unusable.** Enforced at three layers:
the `CatalogueEntry` constructor (protects code that builds entries directly),
`parse_entry` (protects the file path), and `load_catalogue`'s quarantine
(protects a caller who loads a directory and iterates it). A quarantined entry
is not merely hidden from a listing — it is **unrankable and unrenderable**,
because `search` only ever sees `catalogue.entries` and rejected records never
enter that tuple.

**2. `use_mode` is DERIVED, never declared.** It is computed from the licence
identifier by `LICENCE_USE_MODE`, a table in *code*. An entry file that carries
`use_mode`, `vendorable` or `usable` is **refused**, not ignored — a third
party does not get to grant itself permission by writing a key into JSON this
repo reads. Three modes:

- `copy_in` — permissive OSI; source may be copied, notice preserved.
- `reciprocal` — copyleft; copying attaches obligations, so **a human decides**
  and `vendorable` is False. Origin UI sits here deliberately.
- `reference_only` — restricted, non-OSI, or licence unknown. **Never copy.**

**3. Default-deny on an unrecognised licence.** An identifier absent from the
table **raises**. It does not fall back to `reference_only`, because "nobody
checked" must surface as a refusal rather than be absorbed as a
conservative-looking default. And the table is keyed on the **whole**
identifier, so `"MIT + Commons Clause License Condition v1.0"` can never
substring-match its way to `MIT`.

There is one honest third state: an explicitly recorded `NOASSERTION` — *"we
looked and could not establish it"* — which loads and resolves to
`reference_only`. Skiper UI is shipped as the worked example. A **missing**
licence field is a refusal; a **recorded** unknown is a finding.

### What the schema deliberately cannot express

There is no `files` field and no `content` field. shadcn's "main payload" has
no home here, so vendoring a third party's source is not discouraged — it is
**unrepresentable**. A test asserts this against the raw JSON files, not
against parsed entries, so a field the parser ignores cannot smuggle a payload.

### The granularity decision, stated because it is arguable

External entries are at **library** granularity, not per-component. Per-component
external entries would mean copying a third party's descriptions at scale and
re-verifying them as upstream changes — which is vendoring their catalogue one
field at a time. A library entry answers *"where would I look, and may I copy
from it"*, which is the question a builder actually has. **If the shadcn
ingestion above is ever approved, this decision should be revisited with it**,
because that is exactly the case where per-component entries become cheap and
licence-clean.

---

## 3. Search is borrowed, not rebuilt

A sixth ranking predicate beside BM25, DSS diffusion, cosine, `bm25()` and the
fusion weights would be the exact defect ADR-002 names. So `gui_catalogue.py`
contains **no ranking arithmetic at all** — a test enforces this by tokenising
the module and asserting that `k1`, `idf`, `math`, `cosine`, `sqrt`, `log`,
`dot` and `bm25` appear in **no identifier**.

| half | implementation | notes |
| --- | --- | --- |
| lexical | `context_plan.lexical_seed_scores` | the repo's Okapi BM25 (k1=1.2, b=0.75), called on a projection of the catalogue into the `{"modules": …}` shape it already accepts |
| latent | `memory.embeddings.EventVectorStore` | `nomic-embed-text`, 768-dim, same identity anchor, same drift refusal. **Opt-in, default OFF** |
| fusion | `context_plan.fuse_seed_scores` | unchanged, including `effective_latent_weight` |
| normalisation | `context_plan._normalise_max` | imported, not re-typed |

The projection is `_search_key`: an entry's searchable identity (name, kind,
tags, purpose, prop names) rendered as path-shaped segments. `context_plan._terms`
splits on every non-alphanumeric, so the `/` separators are cosmetic, and the
`×2` path weighting that function already applies falls **uniformly** on every
entry — which leaves the relative ranking exactly as BM25 computes it.

**Stated limit:** the lexical half sees the entry's own prose and nothing else,
and the latent half needs a populated vector index and a reachable embedder.
With `use_latent=False` (the default) this is keyword matching over curated
text — good, because the text is curated, and not a claim of semantic search.
`latent_not_requested()` keeps *"nobody asked"* distinguishable from *"asked
and found nothing"*, and a dead embedder degrades to the lexical answer with
`status="error"` rather than a silent zero.

MEASURED, offline, against the shipped catalogue. Re-run 2026-09-01, after
G1-UI-04 removed the twelve `glass/*` component entries:

```
'a modal overlay that slides over the page' -> ext/magic-ui         (1.000)
                                               ext/radix-primitives (0.979)
'chat message transcript'                   -> (no hit)
'status indicator dot'                      -> (no hit)
'charts and dashboard metrics'              -> ext/tremor           (1.000)
'animated marketing landing page'           -> ext/magic-ui         (1.000)
                                               ext/aceternity-ui    (0.851, reference_only)
'reduced motion preference'                 -> motion/useReducedMotionPref (1.000)
```

The two `(no hit)` lines are the cost of the retirement, printed rather than
dropped. They used to read `glass/ChatBubble (1.000)` and `glass/LiveDot
(1.000)`. Nothing in this repository answers those two queries any more, and
BM25 returning nothing is the right answer to a question the catalogue cannot
answer — better than promoting a loose external match into the gap. The
previous measurement, and the entries it ranked, are recoverable at
`e133e09b^`.

---

## 4. A catalogue entry is untrusted text

An entry describing a third party's component was written by that third party.
If it reaches a model prompt it is prompt injection with a filename.

`render_for_prompt` is the **only** path from a catalogue to a prompt, so the
notice cannot be skipped by a caller who forgot. Its shape is
`council/session.py`'s, not a new idiom:

1. session-authored instruction text first (`header`), so untrusted bytes never
   occupy an instruction position;
2. **`PROMPT_DATA_NOTICE`, imported from `council/vendors.py`** — the repo's one
   such notice. A test asserts the literal text does **not** appear in
   `gui_catalogue.py`, so a second copy cannot drift from the first. This repo's
   recorded lesson is that *"a fix that lives in one of two implementations is
   not a closed class."*
3. only then untrusted bytes, each inside a fence labelled with the entry's
   origin, licence and derived `use_mode`.

As `council/vendors.py` says in place: the mitigation is not a better
delimiter. It is that an injection attempt becomes a **finding**, and that
nothing reachable from here can act — this module has no network, no
subprocess, and no writer.

---

## 5. What was seeded

**17 entries, 0 rejected, 0 unresolved dependencies** (MEASURED 2026-09-01).

It was 29 at seeding. G1-UI-04 removed twelve, and the paragraph below says
why in the place a reader will look.

### Ours — 2 entries, Apache-2.0, source in this repo

`motion/tokens` · `motion/useReducedMotionPref`

The motion vocabulary, and nothing else. Their values were **read at the
definition sites** under `apps/web/src/shared/ui/motion/`, not inferred, and
re-read there on 2026-09-01 when G1-UI-04 repointed both entries off the
`apps/web/src/motion/` re-export shims that `G1-UI-03` had kept alive *for this
catalogue's sake* (see the `shared-ui-source-facades` group in
`apps/web/src/app/hierarchy-shims.json`, whose removal criteria name exactly
this migration).

A test asserts every first-party entry's `source_path` **resolves to a file
that exists** — provenance naming a path that is not there is a claim, not a
receipt. That test is the one that caught what follows.

### What used to be here, and what it cost — 12 entries removed

Commit `e133e09b` (*"refactor(web): retire Classic app in G1-UI-02"*) deleted
all twelve sources under `apps/web/src/components/glass/`:

`glass/GlassPanel` · `glass/GlassCard` · `glass/GlassButton` ·
`glass/GlassSheet` · `glass/SegmentedControl` · `glass/Dock` · `glass/DockItem` ·
`glass/LiveRail` · `glass/RailCard` · `glass/LiveDot` · `glass/ChatBubble` ·
`glass/Composer`

The catalogue went on naming all twelve — each with a licence, a licence URL, a
provenance origin and a retrieval date — for ten commits, and
`daedalus/resources/catalogue/gui/glass.json` is a byte-identical packaged
copy, so the wheel shipped the claim too. None of the twelve has a successor:
zero references survive anywhere under `apps/web`, and no exported replacement
component exists in `src/shared/ui` or `src/features`. Several of the *roles*
survive as hand-written inline markup — the palette dialog in
`src/app/Cockpit.tsx`, the status dot written out separately in `StatusLine`,
`Decision` and `Settings` — which is a duplication finding, not a successor.

The entries and their `.tsx` sources are recoverable at `e133e09b^`. Their
caveats are part of that record: `GlassSheet` set `role="dialog"` and
`aria-modal` but **did not trap focus**; `LiveRail`'s collapse was deliberately
not animated; `ChatBubble` deliberately avoided `layout`; `GlassButton` and
`LiveDot` pulled in **no motion runtime**.

**Consequence, stated plainly: Daedalus has no first-party GUI component to
offer a build.** Every component-shaped answer this catalogue can now give
belongs to somebody else, by reference, under their licence and its derived
`use_mode`.

### Then external — 15 entries, by reference only

No third party's source is stored. Each carries name, URL, licence, purpose and
the caveat that matters. Three resolve to `reference_only`, one to `reciprocal`,
and the rest to `copy_in`.

The gaps are now larger than the two originally named. Data visualisation and a
focus-trapping modal were never covered first-party — `ext/tremor` (Apache-2.0)
and `ext/radix-primitives` (MIT) answer those, and both are npm dependencies, a
human's decision and not a build skill's. Since the retirement, **surface, card,
button, sheet, segmented control, navigation rail, status dot, chat bubble and
composer are gaps too**, and every candidate for them is external.

---

## 6. Red counts

Every guard was disabled **by actually editing the module**, the suite re-run,
and the file restored. Baseline: **48 passed, 0 failed.**

| guard | disabled by | RED |
| --- | --- | --- |
| G1 licence is required | drop the constructor check + `licence` from `REQUIRED_FIELDS` | **5** |
| G2 provenance is required | drop `REQUIRED_FIELDS` entry + `isinstance` check + `Provenance.__post_init__` body | **6** |
| G3 default-deny on unrecognised licence | `LICENCE_USE_MODE.get(key, 'copy_in')` | **2** |
| G4 an entry may not declare a derived field | `declared_derived = frozenset()` | **4** |
| G5 duplicate names rejected | `if False:` on the seen-name branch | **1** |
| G6 untrusted-data notice precedes bytes | delete the `PROMPT_DATA_NOTICE` append | **4** |
| G6b entries are fenced | blank both fence constants | **4** |
| G7 no second ranking predicate | add `import math` + a `cosine()` | **1** |
| G8 source cannot be vendored into the schema | add `"files"` to `_ALLOWED_KEYS` | **2** |
| G9 a first-party `source_path` must exist | repoint `LiveDot` at a missing file | **1** |
| G10 unknown keys refused | `unknown = set()` | **1** |

**11 of 11 guards go red when disabled.** Restored state re-verified: 48 passed,
0 failed.

One honest note on method: G2's first disable attempt produced an
`IndentationError`, not a red — deleting three `if/raise` blocks left an empty
function body, so the suite failed to *collect*. A collection error is not
evidence a guard works. It was redone with a syntactically valid disable
(`__post_init__` body replaced with `pass`) and produced 6 genuine failures.
Recorded because a red count from a broken patch is exactly the kind of number
this repo has been burned by.

---

## 7. The skill shape — described, NOT built

Another agent owns `SKILL.md` loading as a FORMAT (inert text, nothing
executed), per ADR-017 Candidate 2. This section specifies what a *"build a
GUI"* skill would look like on top of this catalogue. **No skill is
implemented here.**

### What it would be

A directory `.claude/skills/build-gui/` containing one `SKILL.md`: YAML
frontmatter (`name`, `description`) plus markdown instructions. Nothing else.

The body would say, roughly:

1. Turn the user's request into a one-sentence objective.
2. Call `gui_catalogue.search(catalogue, objective)`.
3. Render the top hits with `render_for_prompt`.
4. **Prefer entries where `is_first_party` is true** — already in this repo.
5. For anything else, check `use_mode` before writing a single line:
   `copy_in` may be adapted with its notice; `reciprocal` and `reference_only`
   may be **named and linked only**.
6. Read `motion/tokens` before animating anything; take numbers from it.
7. Report which entries were used, with their licences.

### What it must NOT be allowed to do

This is the load-bearing half, and every item maps to a rejection this repo has
already made.

- **It must not execute anything.** ADR-017's condition 2: the loader executes
  nothing from a skill directory, enforced structurally. A GUI skill has no
  reason to run a script, and `npx shadcn add` is precisely the command that
  turns "discovery" into "vendoring".
- **It must not add a dependency.** No npm install, no edit to
  `apps/web/package.json`. `ext/radix-primitives` and `ext/tremor` are real
  answers to real gaps and both are **human decisions**. A skill that can add a
  package is a skill that can add a supply chain.
- **It must not fetch.** No registry URL, no `r/index.json`, and above all no
  per-item URL — those embed source in `files[].content`. The catalogue is the
  only source of component knowledge; it is refreshed by a human with evidence.
- **It must not decide a licence question.** `use_mode` is derived in code. A
  skill may *read* it and must *obey* it. It may never conclude "this looks
  MIT" — that is the exact reasoning the React Bits licence defeats.
- **It must not carry a lane, provider or path-policy field.** ADR-017's
  condition 3, unchanged. Skill text is content, never authority.
  `sensitivity.lane_for_host` answers "where do the bytes go" from the host and
  nothing else, and a skill must not become a second input to that question.
- **It must not write outside the app's own source tree**, and must go through
  the existing write path and its guards rather than beside them.

The catalogue itself is what makes most of this cheap: a skill that cannot
fetch and cannot install has nothing to reach for **except** a curated local
index — so the safe path is also the only convenient one.

---

## 8. What would make this document wrong

Stated in advance so it can be checked rather than re-argued.

- **Every licence is a 2026-07-29 snapshot.** The four that decide something:
  React Bits (Commons Clause), Aceternity (custom), Origin UI (AGPL-3.0 with a
  carve-out), 21st.dev (proprietary content). Re-check before acting.
- **Skiper UI is `NOASSERTION` because I could not find a LICENSE file**, not
  because one does not exist. Someone who finds one should update the entry.
- **Origin UI is recorded at its repository default (AGPL-3.0)**, which is the
  conservative reading. The MIT carve-out for `apps/origin/` and `apps/ui/` is
  real; resolving which files it covers is a per-file question this catalogue
  deliberately does not answer.
- **The library-granularity decision for external entries is arguable**, and it
  is the thing to revisit first if shadcn ingestion is approved.
- **`meta.links.*.api` in shadcn's index means prop data is one fetch away** for
  62 components. That is a tempting shortcut and it is a third-party fetch; it
  is not taken here.
- **Nothing was installed and nothing was vendored.** No npm dependency, no pip
  dependency, no third-party source. `apps/web/package.json` is untouched.
