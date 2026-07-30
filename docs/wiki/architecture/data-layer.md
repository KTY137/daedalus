---
title: Data layer
type: spec
status: partial
updated: 2026-07-30
---

# Data layer

Artefacts that move between programs: which script reads which `.root`, which
writes which figure, which paper includes it. A path literal is a path literal in
LaTeX, C++, Python and a Makefile alike, which is why this layer generalises where
the [[Type graph]] cannot.

Lives in [[code:daedalus/structcore/artifacts.py]].

The point is not the edge but the join: does the schema the code declares match the
schema the file carries? A renamed branch survives every test suite and then appears
in a thesis.
