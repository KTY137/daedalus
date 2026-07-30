---
title: Observation layer
type: spec
status: implemented
updated: 2026-07-30
---

# Observation layer

What a debug console shows, recorded as data: `ndarray float64 (1000, 3)
C-contiguous`. Shape, never value -- a value can be gigabytes, can be a secret, and
the graph does not want it.

Lives in [[code:daedalus/observe/shape.py]], deliberately outside `structcore`,
because a live object means the program ran and indexing must never execute what it
indexes.

It dissolves a named blindness: structcore's own index travels as a bare `dict`, so
the most important data structure in the tree is invisible to any
declaration-level pass. One observed instance names its twenty real keys.

An observation is a sample, not a proof. Related: [[Type graph]].
