# Many languages, and the chain a physics analysis actually is

2026-07-30 · owner direction: the graph must work for Python, C, C++, Rust, ROOT, Verilog,
Fortran, Java, JavaScript, Ruby, **LaTeX** — *"alles was man braucht um die ganze HEP-Analyse
der Teilchenphysik zu analysieren"* — and dataflow/inference combined with the AST graph is
what he believes breaks the code-evolution wall.

Status: DESIGN. Momus round outstanding. Nothing here is built.

## The reframing this document exists for

A high-energy-physics analysis is not a codebase. It is a **chain that ends in a claim**:

```
paper.tex  "the efficiency is 98.2%"     ← the claim a human will be held to
  └ \includegraphics{fig/eff_vs_v.pdf}
      └ plot_eff.py                       reads output/selected.root
          └ analysis.cpp  (ROOT/C++)      applies a selection, writes selected.root
              └ raw/run0421.root          taken with
                  └ config/iseg.json      HV settings, and read out by
                      └ readout.v         detector firmware
```

Nobody can follow that chain today. Every hop crosses a language boundary, and every link is
a **convention** — a path spelled inside a string literal — rather than a declaration. That is
why a plot in a thesis can silently stop matching the code that made it.

**The important consequence:** most links in that chain are *not* type edges. They are
**artifact edges** — string literal to file. And a path literal is a path literal in C++, in
Python, in LaTeX and in a Makefile. So the layer that closes the HEP chain is cheaper than
type inference, works in **every** language on the list, and reuses machinery this repo
already has: `markdown.py`'s refuse-to-guess link resolution.

That inverts the priority. Type inference is the deep answer to a narrow question. Artifact
provenance is the shallow answer to the question the domain actually asks.

## Three tiers, and what each one honestly costs

### Tier 0 — artifact provenance. Universal, cheap, every language on the list.

Extract path-shaped string literals and resolve them against the real file set. Same rule as
document links: **a literal that does not resolve to a file that exists is DROPPED and
COUNTED, never bound to a near-match.**

| Language | What carries an artifact edge |
|---|---|
| LaTeX | `\input`, `\include`, `\includegraphics`, `\bibliography`, `\addplot table{...}` |
| Python | `open()`, `uproot.open()`, `pd.read_*`, `np.load`, `Path(...)` literals |
| C++/ROOT | `TFile::Open`, `TChain::Add`, `#include`, `gSystem->Load` |
| Fortran | `OPEN(UNIT=…, FILE=…)`, `INCLUDE` |
| Verilog | `$readmemh`, `` `include `` |
| Make/CMake | targets and prerequisites — the ground truth of what produces what |
| shell | redirects and argument paths |

Node kinds: `artifact` (a file that is neither code nor document — a `.root`, a `.pdf`, a
`.csv`). Relations: `reads`, `writes`, `includes`, `figures`. Direction matters and is often
recoverable: a Makefile rule states producer and product outright.

**Why this is the highest-value tier:** it is the only one that answers *"is the number in the
paper still the number the code produces?"* — and that question is already this repo's
signature move. The docref scan hunts prose making claims about code that does not exist;
extended to `.tex`, the same lane hunts **papers making claims about analyses that changed.**
Same gate, same evidence shape, new corpus.

### Tier 1 — declaration-level types. Needs a tree-sitter grammar per language.

What is being built now for Python: types as nodes, fields as children, functions as
`consumes`/`produces` edges — from **declarations only**, no execution. Extending it means
adding class/field/signature vocabulary to `LanguageSpec`, which is a schema change, so it is
per-language work with per-language coverage.

Honest per-language notes:

* **C/C++/ROOT** — declarations are readable, but resolution needs the preprocessor. Without
  `compile_commands.json` a header-heavy tree gives *plausible* types, not correct ones.
* **Verilog** — "type" means net kind, bit width and signedness. That is a different type
  system, not a sparse version of ours. Model ports and widths or model nothing; do not
  pretend `logic [7:0]` is a nominal type.
* **Fortran** — grammar exists, tooling does not. Tier 0 and tier 1 only, forever, probably.
* **LaTeX** — has no types. It is a document, and it already has a home: the document node
  kind, with `\label`/`\ref` as an internal anchor graph and `\cite` as an external one.

### Tier 2 — real inference. Off the shelf, per language, optional.

**This is the answer to "must work for many languages": do not write N type inferencers.
Consume SCIP from N maintained indexers.** SCIP is Sourcegraph's protobuf index format;
every indexer emits the same schema, with `SymbolInformation.relationships` carrying
`is_implementation` / `is_type_definition` and occurrences carrying roles
(Definition / Reference / WriteAccess).

Verified 2026-07-30 by querying the GitHub API — all active, all pushed within the last month:

| Indexer | Status | Last push | Note |
|---|---|---|---|
| `scip-python` | active, 94★ | 2026-07-29 | built on **Pyright** — infers unannotated returns |
| `scip-java` | active, 130★ | 2026-07-28 | moved to the `scip-code` org |
| `scip-clang` | active, 91★ | 2026-07-25 | **C/C++, therefore ROOT** — needs `compile_commands.json` |
| `scip-typescript` | active, 105★ | 2026-07-24 | JS and TS |
| `scip-go` | active, 69★ | 2026-07-21 | — |
| `scip-ruby` | active, 21★ | 2026-07-03 | Sorbet-based |
| `scip-rust` | active, 10★ | 2026-07-02 | 10 stars — treat as immature |
| Fortran / Verilog / LaTeX | **none exist** | — | tier 0 + tier 1 only; report `not_supported` |

So the multi-language story is real for Python, C/C++, TS/JS, Java, Go and Ruby, weak for
Rust, and absent for Fortran, Verilog and LaTeX. **That asymmetry must be reported per
language, never averaged into one coverage number** — the same rule that already forbids a
numeric zero where we did not look.

ROOT has a third path worth noting: it carries **runtime reflection** (`TClass`,
`TDataMember`), so a generated dictionary already knows every data member of every class. That
is more precise than any static pass — and it requires ROOT installed and dictionaries built,
so it is an enrichment, never a dependency.

## Does dataflow break the wall? The honest position

The owner's claim: dataflow plus the AST graph is what gets through the code-evolution
ceiling. It is plausible, and there are two specific places where it is more than plausible:

1. **Blast radius.** Evolution is mutate → gate → promote. Without dataflow, "what does this
   change reach" is guessed from name matching. With it, it is bounded — which both shrinks
   the test set a gate must run and exposes semantic conflicts between agents editing
   different files that feed the same structure.
2. **The named blindness.** Untyped `dict` payloads carry most of the real data structure in
   this repo — `structcore`'s own index travels as a `dict`. Declaration-level typing is blind
   exactly there. Inference is not.

And the reason to stay sceptical is this repo's own history. **Lane A2** was an equally
plausible structural hypothesis — files that change together reveal coupling the import graph
cannot see. `eval/ceiling.py` measured its hard upper bound before anything was built:
**2.3% clean against 14.0% leaky**, and the gap between the two arms *was* the
self-prediction artifact. The lane was closed on that number. ADR-015 records that the same
discipline applies to any replacement.

So the rule is not "don't build it". The rule is **measure the ceiling first, for the price of
a query instead of a build.** For this claim the measurement is:

> Over the minted corpus, for every missed `must_include` label: is the label's defining
> symbol reachable from the task's focus through **type or dataflow edges but NOT** through
> the existing import and call edges? Backtest-clean — derive the edges from the tree as of
> `minted_at_sha^`, never from the commit being predicted.

That number is the hard upper bound on what the layer can add to recall. If it comes back
near 2.3%, the layer is not a recall feature and the claim has to move to **precision**
(fewer fabricated edges), which is a different measurement with a different corpus.

There is also a cheap intermediate that captures most of blindness #2 without a compiler:
**mine `x["literal_key"]` accesses into inferred pseudo-fields**, stamped
`provenance=mined`. Already in the type-graph plan as pitfall 3. It should be measured before
a Pyright sidecar is built, because it is days of work against weeks.

## The behavioural axis — abstract AND executed

Owner: *"quasi ein scan der ganzen datenstruktur abstrakt als auch ausgeführt, um das
behavioural mitintegriert zu haben."* Correct, and it is a third axis, not a deeper tier:

* **abstract** — what the code *declares* (tier 1) and what a checker can *prove* (tier 2)
* **behavioural** — what actually *happened* on a real run

### Where behavioural data comes from without building a debugger

Every source below already exists; none needs a new runtime.

| Source | What it observes | Cost |
|---|---|---|
| `coverage.py` | which units actually executed | ~free — the suite already runs |
| runtime type recording (MonkeyType / `pyannotate` pattern, `sys.monitoring` on 3.12+) | the **actual** argument and return types, including **real dict keys** | a traced test run |
| process artifact recording | the files a job actually opened and wrote | a wrapper around the job |
| ROOT's own file logging + `TClass` reflection | opened files; every data member of every class | ROOT installed |

The second row is the one that matters most, because it dissolves the blindness named above:
a declaration cannot tell you what is inside an untyped `dict`, and **a single observed
instance can.** For `structcore`'s own index — the most important data structure in this repo
and a bare `dict` — one traced test run would produce its real key set.

### The invariant that keeps this out of the index

**Indexing must never execute what it indexes.** That is not a preference; `tools/vet.py`
was written this week on exactly that rule ("you do not run untrusted code to decide whether
to trust it"), and `structcore` is a static pass by construction.

So the behavioural layer is a **separate, opt-in, isolated lane** that *feeds* the graph
with observed edges — it is never part of `build_index`. It runs only on trees the operator
owns, inside the worktree isolation the write path already uses, and it is off by default.
A foreign repository gets tier 0 and tier 1 and nothing else, ever.

### Every edge carries how it was learned

The forest already keeps `evidence` on every edge. The behavioural layer extends that
vocabulary rather than adding a schema:

```
provenance = declared   | the annotation says so
             inferred   | a checker proved it (scip-*)
             mined      | a literal key access implies it            (heuristic)
             observed   | a real run did it   + run_id + input set   (a SAMPLE)
```

`observed` is a **sample, not a proof**, and must be labelled as one. A branch that did not
execute is not a dead branch — it is a branch these inputs did not reach. Reporting observed
coverage as truth would be the same defect class as reporting a language's type coverage as
zero when nobody looked.

### The payoff is the contradiction, not the union

Merging static and behavioural gives one thing nothing else in this space gives: the graph can
report **where the code's claims and the code's behaviour disagree.**

| Disagreement | What it means | Who wants it |
|---|---|---|
| declared type never observed | dead path, or the annotation is wrong | the picker — a real candidate band |
| observed type absent from the declaration | **the annotation lies** | the fence, before trusting a signature |
| declared field never read | dead field, or a consumer nobody indexed | distillation |
| observed dict key with no declared field | the payload has undocumented shape | the type layer's own coverage |
| artifact written but never read | a dangling output — a plot nobody cites | HEP provenance |
| artifact read but produced by nothing indexed | an input from outside the tree | reproducibility |

Those last two are the HEP chain's failure modes stated as queries. **"A figure in the paper
whose producing script no longer writes that file"** is the same defect shape the docref lane
already hunts, and it is exactly what the owner is asking to catch.

This is also the honest answer to "is the type graph strong or a gimmick": on its own it is a
precision improvement of unmeasured size. **Fused with behavioural data it becomes a
contradiction detector**, and a contradiction is something the loop can act on without a human
deciding what matters. That is a stronger claim than "better slices" — and it is still a claim
that has to be measured before it is believed.

## Sequence this implies

1. **Tier 0 for LaTeX first.** Smallest, highest domain value, and it lands the
   paper→figure→script→data chain. It also extends an already-working lane (docref) to a new
   file type instead of inventing a subsystem.
2. **The ceiling measurement** for type/dataflow recall, backtest-clean.
3. **Dict-key mining**, if the ceiling justifies going after payloads at all.
4. **One SCIP consumer**, then one indexer at a time — `scip-python` first because it is the
   language the harness is written in and the corpus is here.
5. `scip-clang` for ROOT/C++, gated on whether the target trees carry
   `compile_commands.json`. Without it, do not claim C++ types.

Fortran and Verilog stay tier 0/1 and say so. Promising otherwise would be the same defect as
reporting a coverage zero for a language nobody looked at.
