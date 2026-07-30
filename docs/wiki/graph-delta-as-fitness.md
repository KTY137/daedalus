---
title: Graph delta as fitness
type: finding
status: verified
updated: 2026-07-30
---

# Graph delta as fitness

Measured 30 July against the seeded-defect corpus in
[[code:tools/gate_discrimination.py]] and 516 changed functions of real history.

## Numbers

Sensitivity: 7 of 12 real defects move the graph. Specificity, per function: pure
deletion fires on 4 of 413 real functions (1.0%) and catches 6 of 12 defects.
Likelihood ratio about 50.

## Two mistakes the run caught in itself

The first pass reported 10 of 12, and every detection contained the tokens SEEDED
and DEFECT -- the corpus's own marker comments. The measurement was detecting its
own label. Both arms are still reported, because the gap is the artefact.

Set semantics also hid the deletion of a call that still occurred elsewhere in the
same function. Multisets fixed it.

## The ceiling

A legitimate fix that deletes a check and a seeded defect that deletes a check
produce the same delta. Removing a `startswith` in the write-allow policy was a
fix; removing a `fullmatch` in the picker was a defect. Structure cannot tell them
apart -- only intent can. So: evidence for ranking, never a gate.

Related: [[Type graph]], [[Agents hold no state]].
