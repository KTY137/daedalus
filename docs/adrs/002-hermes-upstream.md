# ADR-002: Hermes as Ikarus Upstream

## Status
Rejected after implementation audit (2026-07-28)

## Context
Developing a full conversational AI framework (Agent Loop, Sessions, SQLite/FTS5 Memory, Skills, Plugins) from scratch is error-prone and redundant.

## Decision
No upstream integration was present. The code labeled Hermes was an independent,
unauthenticated WebSocket server that bypassed the scheduler and duplicated
event types. It was removed.

## Consequences
An upstream may be reconsidered through a new ADR only after the exact project,
version, license, threat model, integration seam, and replacement cost are
documented and verified.
