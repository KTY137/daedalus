# ADR-010: Naming Namespaces

## Status

Accepted

## Decision date

2026-07-28 (user-approved)

## Context

ADR-001 and ADR-009 gave the product's components Greek names (Ikarus, Metron,
Cerberus, Nemesis, Ariadne). The Claude-side crew that *builds* the product
(`.claude/agents/`, ADR-independent) also uses Greek names, and the two sets
collide. Separately, the crew scribe delegate "hermes" collides with the
NousResearch Hermes agent repo (the upstream of ADR-002), and the plan term
"Hermes Transport" inherited that ambiguity. Names that mean two things poison
logs, receipts, and search.

## Decision

1. **Crew scribe rename.** The crew delegate **hermes** is renamed **kadmos**
   (`.claude/agents/kadmos.md`). "Hermes" is reserved for the NousResearch
   Hermes agent repo (ADR-002 upstream).
2. **Crew persona rename.** The `extension-dev` crew persona **Icarus** is
   renamed **Perdix**. "Ikarus" is reserved for the product's JARVIS-like
   shell (ADR-001).
3. **Deliberately shared names.** **Cerberus**, **Nemesis**, and **Talos**
   remain shared between crew and product. This is intentional, not a
   collision: the crew agent is the dev-time instance of the same gate role
   the runtime component plays. The actor-namespace rule below disambiguates
   them wherever it matters.
4. **Scheduler package rename.** The product scheduler package
   `daedalus/metron/` is renamed `daedalus/kairos/`. The crew sentinel
   **Metron** keeps its name.
5. **Plan term dropped.** "Hermes Transport" is dropped; the plan uses
   **Agent Shell / TransportRecord** instead.

### Actor-namespace rule

Durable logs and receipts must record actors fully namespaced:

- product actors as `daedalus.<name>` — e.g. `daedalus.nemesis`,
  `daedalus.cerberus`;
- crew actors as `crew.<name>` — e.g. `crew.nemesis`, `crew.kadmos`.

No `missions/events.py` (or successor event/receipt module) may define actor
identity before honoring this rule.

## Consequences

A bare Greek name in a durable record is now a defect, not a style choice.
The shared Cerberus/Nemesis/Talos names stay legible only as long as every
durable record carries its namespace; the rule above is the gate. The
`daedalus/metron/` → `daedalus/kairos/` package rename is executed separately
and is not made true by this ADR.

Executed 2026-07-28: `daedalus/metron/` → `daedalus/kairos/`, class
`MetronScheduler` → `KairosScheduler`; `daedalus/ikarus.py` keeps `Ikarus` and
`MetronScheduler` as aliases of `KairosScheduler`.
