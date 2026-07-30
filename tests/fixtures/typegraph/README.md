# `tests/fixtures/typegraph/` — the adversarial fixture repo for the type/data-structure graph

A frozen, synthetic Python repository. Every file encodes ONE hazard, named in
the filename, so a failing test points at the hazard instead of at "the fixture".
The corpus is consumed by `tests/test_typegraph_fixture.py` (the tripwires that
must pass BEFORE and AFTER the type layer exists) and by every later stage of
the type-graph lane.

Reviewed plan: `docs/research/TYPE_GRAPH_AND_KNOWLEDGE_SPACE_PLAN.md`, section
**NON-GOALS / INVARIANTEN**. The six invariants are referred to below as I1–I6.

## Why synthetic, and why frozen

The plan's regression thermometer requires that three facts stay byte-identical
across the feature: the `duplication` block, `resolver.defs_by_file`, and the
lexical seed. Pinning those against `daedalus/` itself does not work — that tree
moves on every commit (and moved *during* this lane, edited by a second agent
system), so a captured snapshot would go red for reasons unrelated to the
feature and would then get "fixed" by re-capturing, which destroys the tripwire
silently. This tree does not move, so a red line means the CODE changed.

Two deliberate properties of the corpus:

* **Every function is at most three lines.** That is below `min_loc=4` (exact +
  renamed clone passes) and below `min_loc=6` (near-miss pass), and no six
  consecutive normalised lines repeat across two files, so the window pass finds
  nothing either. The measured `duplication` block is therefore **completely
  empty** — which makes it the most sensitive I1 tripwire available: one
  `ClassDef` reaching `all_units` turns `[]` into a renamed-clone cluster,
  because the corpus contains a four-field dataclass pair on purpose.
* **Every internal import resolves.** `import_edges` is non-empty and captured,
  so the cross-module and ambiguity cases exercise real resolution rather than
  the "external import" fallback.

## The files

| File | Hazard it encodes |
|---|---|
| `dataclass_field_count_collision.py` | **I1** — dataclasses with 2, 4 and 4 fields. `QuadAlpha` and `QuadBeta` differ only in field NAMES, so under the Type-2 abstraction they share one fingerprint. `renamed_clusters` has no threshold and no `max_cluster` and is published in the PRECISE tier, so a class in `all_units` publishes them as full-confidence renamed clones. (Real shape in `daedalus/`: 176 dataclasses.) |
| `kind_zoo.py` | Declaration-shape coverage: `@dataclass`, plain class (annotated attribute + `self.x` assignment), `NamedTuple`, `TypedDict`, `Enum` (members are VALUES, not typed fields), `Protocol`. A stage that only understands `@dataclass` fails here, not somewhere that looks unrelated. Also declares `User`, the cross-module annotation target. |
| `name_collision_class_and_function.py` | **I2** — `class Foo` AND `def Foo` in one file, class first. `build_resolver` uses `setdefault` (first wins), so admitting classes rebinds `Foo` from callable code to a class body, here and in every importer. Legal Python; statically ambiguous. |
| `field_names_are_common_identifiers.py` | **I2** — fields named exactly `path`, `root`, `name`, `line`, `source`, `module`. None is in `graph._STOP` and all are longer than two chars, so `graph.identifiers` keeps them; `graph.callees` resolves EVERY identifier token in a body, so these become fabricated CALL edges in `slice_text`. `describe()` mentions three of them in its body to make the fabrication observable. Second order: `context_plan._symbol_names` reads `defs_by_file` wholesale into the BM25 corpus. |
| `union_shapes.py` | Union normalisation (Pitfall-Policy 1): `Optional[Alpha]`, `Alpha | None` (PEP 604), `Union[Alpha, Beta]`, `Optional[Union[Alpha, Beta]]`. One `union_id` per annotation, `Optional` stripped, `None` never a node, nesting must not multiply members. Deliberately has NO `__future__` import so these are real ast expression nodes. |
| `generic_containers.py` | Generics (Pitfall-Policy 2 / TYGAR): `list[Item]`, `dict[str, Item]`, `Mapping[str, list[Item]]`, `list[tuple[str, Item]]` — three annotations, ONE nominal element type. No node per instantiation. `Mapping` is also one of the measured hub types behind **I6**. |
| `future_annotations_forward_ref.py` | **PEP 563 is the normal case.** `from __future__ import annotations` makes every annotation a string in the ast, so a `ast.Name`-only extractor finds nothing and reports zero rather than an error. Also: a self-reference (`Node \| None` inside `Node`), a forward ref to `Later` defined BELOW its use, and an explicitly quoted `"Later"` (a string inside a string). Resolution must run against the finished per-file table, never incrementally. |
| `cross_module_annotation.py` | The POSITIVE control for **I5**: `User` (flat sibling) and `Ticket` (nested package) are each declared by exactly one imported module, so both MUST produce an edge. I5 forbids guessing, not resolving — a stage that refuses everything non-local would pass the ambiguity tests and still be useless. |
| `pkg_nested/__init__.py`, `pkg_nested/inner_types.py` | A nested package, so at least one fixture import is dotted (`pkg_nested.inner_types`) and exercises the multi-segment path in `_PyNaming` / `resolve_python_imports`. `__init__.py` also pins the "file that defines nothing gets no `defs_by_file` bucket" case. |
| `result_alpha.py`, `result_beta.py` | Two unrelated classes both named `Result`, with different fields. `result_alpha` sorts first, which is exactly why a resolver that walks sorted imports and takes the first hit binds to it deterministically — and wrongly half the time. |
| `ambiguous_result_try_import.py` | **I5a** — `Result` bound by `try: from result_alpha … except ImportError: from result_beta …`. Which one is meant is a property of the environment, not of the source: genuinely undecidable. Required behaviour: NO EDGE, counted into `types.coverage.ambiguous`. Deterministic ≠ correct — the naive implementation emits a stably reproducible FALSE edge in every process. |
| `ambiguous_result_star_import.py` | **I5b** — the same ambiguity through star imports. No name binding exists in the file's own text, so there is not even a `Result` token in an import statement to anchor on. Kept alongside I5a because the two fail an implementation at different points: I5a fails an import-binding reader, I5b fails a graph-walking resolver. |
| `unresolvable_annotations.py` | The three ways an annotation carries no usable type: `Any` (resolvable and says nothing — must be counted SEPARATELY from unresolved, or the coverage number lies in one direction), an unannotated function (the honest gap; inference is the optional scip-python sidecar's job), and `NoSuchTypeAnywhere` (declared nowhere, imported from nowhere → NO EDGE, counted; never minted as a node for being mentioned). Also present inside a container: `list[NoSuchTypeAnywhere]`. |
| `protocol_structural_match.py` | Structural match ≠ inheritance: `FileEmitter` implements every member of `Emitter` and inherits from nothing; `DeclaredEmitter` says so explicitly. A matcher that emits `inherits` without `structural=True` erases the difference between a declared contract and a name coincidence — and `emit`/`flush` make coincidence the normal case. Also pins the `defs_by_file` name collapse: six method definitions, two keys. |

## Rules for anyone extending this corpus

1. **Keep every function under four lines.** The empty `duplication` baseline is
   the I1 tripwire; a longer function can create a legitimate cluster and blunt
   it. If you need a long function, say so in `DUPLICATION_BASELINE` and explain
   why in the same commit.
2. **Python only.** Stufe 1 is Python only (the tree-sitter `LanguageSpec` has
   no class/field vocabulary), and `types.coverage` must report `not_supported`
   per language rather than a numeric zero. Adding a `.c` or `.ts` file here
   also changes `near_excluded_languages` in the captured baseline.
3. **Update `tests/test_typegraph_fixture.py` in the same commit.** Its literals
   (`FIXTURE_MODULES`, `UNITS_BASELINE`, `DEFS_BASELINE`, `IMPORT_EDGES_BASELINE`)
   were CAPTURED from a run of the unmodified code, never typed by hand. Re-capture
   deliberately and say what moved; a silent re-capture deletes the tripwire.
4. **No imports of anything real.** Nothing here may import `daedalus`, and
   nothing here is ever imported by a test — the files are read as TEXT. That is
   what keeps `typing.get_type_hints` (which executes imports: an egress/safety
   violation in this codebase) permanently unnecessary.
