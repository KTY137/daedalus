# ADR-009: Ariadne Forest Evolution Engine

## Status

Proposed; name accepted, engine not yet implemented

## Context

Daedalus needs a stable name for the evolutionary subsystem that will replace
the current Best-of-N test runner. `ForestEvolve` describes the mechanism but
does not distinguish a product role from an implementation command.

## Decision

The subsystem is named **Ariadne — the Daedalus Forest Evolution Engine**.

- **Ikarus** is the user-facing, JARVIS-like assistant.
- **Kairos** compiles and schedules missions.
- **Ariadne** selects parents and inspirations, proposes candidate
  transactions, and maintains evolutionary search state.
- **The Grove** is Ariadne's append-only Quality-Diversity candidate archive.
- **Nemesis** evaluates candidates independently.
- **Daedalus** owns the root of trust and promotion boundary.

`forest-evolve` may be used as a descriptive CLI command or protocol verb.
Ariadne does not execute arbitrary processes directly and does not control its
own frozen evaluators.

## Consequences

The name does not establish an AlphaEvolve-level capability. Ariadne may be
called implemented only after persistent lineage, external versioned
evaluators, multi-objective selection, repeated feedback, budget accounting,
and transactional promotion exist. Claims of superiority require
equal-budget, multi-seed held-out comparisons against Best-of-N and an
AlphaEvolve-style archive/island baseline.
