# G2-INGEST-02 — a fail-closed bug fixed, and the TOLERANT design killed by its own gate

`[MEASURED 2026-09-09 on origin/main 094f3567]`
Classification: `ALIGNED` (bug fix) + retained negative evidence.
Packet: `docs/work-packets/G2-INGEST-02_PARTIAL_PLANE_ADMISSION.md`.

## What shipped

**One bug fix.** `compile_reference_project` failed with a bare `KeyError`
instead of `ReferenceCompileError` whenever a declared Markdown page linked to a
`.md` file that exists on disk but is not declared in the manifest.

Reproduced on **unmodified** `daedalus/` at `cb16d7f0`:

```
PRISTINE MAIN RAISES KeyError: 'knowledge:doc:B.md'
```

`_markdown` (`_reference_inventory.py:159`) emits a `links_to` edge for every
`.md` target it finds; the link check at `:207` accepts an undeclared target as
long as `resolve_regular_file` finds it on disk. The edge then points at a node
that was never built, and the `node_plane` lookup fails.

This is a **fail-closed violation**, which is why it is worth fixing on its own:
`ReferenceCompileError` is the module's documented failure type, so a caller
that guarded compilation with `except ReferenceCompileError` was silently not
protected. The fix refuses explicitly, naming the link that must be declared or
removed. Three regression tests cover the refusal, the error type, and the
compiling case.

## What was built and then withdrawn

The packet's actual GOAL — an opt-in `AdmissionPolicy.TOLERANT` that excludes
defective files and emits `partial`/`absent` planes — **was implemented,
verified working, and then removed before commit.** It is recorded here rather
than silently dropped, per `AGENTS.md` §4.

It worked. STRICT stayed byte-identical to the baseline; TOLERANT produced
`knowledge=partial` with a structured reason
(`daedalus-plane-exclusion/1 excluded=1 declared=2 dropped_edges=1 digest=… paths=B.md`).
It was withdrawn because an independent design review, plus the measurements it
demanded, showed it does not do the thing it exists for.

### Why it was withdrawn — three measured reasons

**1. Every TOLERANT Twin is inert.** Two independent consumers hard-refuse any
non-`complete` plane:

| consumer | behaviour |
| --- | --- |
| `twin/relation_compiler.py:193` `_require_complete_endpoint_planes` | raises `ValueError` |
| `kernel/fourfold_evidence.py:592` | records `incomplete_planes:` mismatch |

That refusal is **correct** — the system should not treat a partial Twin as a
verified one. But it means a `partial` producer has no consumer, so wiring one
in trades a contract with no producer for a producer with no consumer.

**2. The type plane is a *dataclass* plane, and admission was never the
blocker.** `_python` (`_reference_inventory.py:60`) extracts a type node only
from a module-level class carrying a `dataclass` decorator. Measured against the
two pinned repositories:

| | classes | `@dataclass` | annotation sites | type nodes emitted | coverage |
| --- | ---: | ---: | ---: | ---: | ---: |
| black | 391 | 16 | 3 175 | 108 | **3.40 %** |
| fastapi | 821 | 16 | 5 878 | 94 | **1.60 %** |

A repository whose files all parse would get a type plane marked **`complete`**
over 1.6–3.4 % of its actual type information. Plane status tracks *file
coverage*, not *extraction coverage*, so TOLERANT would have made the compiler
admit real repositories while labelling that gap `complete` — a worse honesty
failure than the refusals it was removing.

**3. The data vocabulary, not admission, is what excludes fastapi.** Of
fastapi's `.json` files, **0 of 0** exist; of black's, 1 of 1 survives `_schema`.
`_schema` (`:113`) requires `type == "object"` with non-empty `properties`, so
ordinary repository JSON is rejected as a matter of course. No admission policy
changes this. If unblocking fastapi is the goal, the vocabulary is the packet
and admission is not.

### The fourth reason, which is a scoping finding

The packet's acceptance row A9 (compile `black` under TOLERANT) was
**unreachable from the start** and I had not noticed:
`_reference_claims.py:36` — `if not claims_value: raise ReferenceCompileError`.
An auto-derived manifest has `claims: []` by construction, so a claims-free
repository cannot compile in *any* admission mode.

Relaxing that rule would produce a four-plane snapshot with **zero** cross-plane
bindings. `contracts.py` permits `bindings=()`, and `fourfold_evidence.py:592`
gates only on plane status — so such an object would publish as
`assurance="deterministic", verdict="passed"`, byte-indistinguishable from a
fully verified Twin except by counting bindings, which no consumer does.

That object is precisely the **"four separate indices"** configuration that plan
§11 lists as a Gate-3 *baseline to beat* and §14 lists as a *kill criterion*.
Ingesting a corpus of them would not build Twin coverage; it would build the
null baseline while labelling it coverage. Honest labelling would require a
top-level "no cross-plane verification attempted" discriminator in
`twin/contracts.py` — a file this packet explicitly forbids itself from
touching. **The goal was mis-scoped, not merely hard.**

`_reference_claims.py:36` is therefore left exactly as it is.

## One thing the review confirmed rather than refuted

The safety property holds **by construction**: `verify_claims` tests membership
against the file tuples it is handed (`:56`, `:101`) and against inventory
existence (`:60/:70/:76/:83/:107`), with no `continue` and no default-swallow.
Passing reduced lists makes a claim about an excluded file **refuse**. Exclusion
narrows what can be proven; it never lowers the bar for proving it. That was the
one design property I was most worried about, and it was never in danger.

## Verification

| check | result |
| --- | --- |
| `tests/twin/` | **385 passed, 3 skipped** (382 + 3 new) |
| `tests/twin/ tests/contracts/ tests/gates/ tests/ignition/` | **1 481 passed, 78 skipped, 28 subtests, 0 failed** |
| snapshot identity | all four digests unchanged for both manifested projects vs `runs-baseline.json`, recorded before implementation |

## What this does not claim

- Gate 2 is not closer to closing. A bug fix and a withdrawal are not a corpus.
- The 3.40 % / 1.60 % figures measure *this compiler's* type extraction against
  a naive annotation-site count. They are a coverage ratio, not a statement that
  a better extractor would reach 100 %.
- No claim that TOLERANT is wrong in principle. It is unshippable **here**,
  because its output has no consumer and its goal needs a contract change that
  is out of scope.
