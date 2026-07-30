---
title: Type graph
type: spec
status: implemented
updated: 2026-07-30
---

# Type graph

Types as nodes, fields as their children, functions as edges between them:
`consumes` for a parameter, `produces` for a return. Extraction is static -- one
`ast.parse`, never `typing.get_type_hints`, which would execute imports.

Lives in [[code:daedalus/structcore/typegraph.py]], with extraction in
[[code:daedalus/structcore/parse.py]]. Off by default; `DAEDALUS_INDEX_TYPES=1`.

## Invariants

Six of them, from a Momus review, and the index publishes them as a checkable
`excluded_from` list. The two load-bearing ones: type nodes never enter
`all_units` -- 176 dataclasses would otherwise become one renamed-clone cluster
in the precise tier -- and they never enter the symbol resolver, where field
names like `path` and `name` would become fabricated call edges.

Related: [[Graph delta as fitness]], [[Data layer]].
