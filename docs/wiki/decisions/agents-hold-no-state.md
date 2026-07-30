---
title: Agents hold no state
type: adr
status: proposed
updated: 2026-07-30
---

# Agents hold no state

Do not make project agents persistent. Make the knowledge persistent.

A static per-project agent accumulates state in its context, and that state is
invisible, unverifiable and drifts. That is context drift with a friendlier name. A
vault every agent reads and writes is the same state, but inspectable, versioned and
correctable by a human.

Consequence: this wiki is load-bearing rather than decorative, and the
knowledge-management thesis and the code-evolution thesis become one thesis.

Related: [[Knowledge layer]], [[Graph delta as fitness]].
