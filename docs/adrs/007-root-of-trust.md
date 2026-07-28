# ADR-007: Root-of-Trust

## Status
Proposed; not enforced

## Context
In a self-modifying or evolutionary AgentOS, the system must not be allowed to disable its own safety constraints or replace its evaluators.

## Decision
The following components are intended to form a future Root-of-Trust:
*   Cerberus Policy Engine (security rules).
*   Nemesis Verifier (acceptance criteria).
*   The Execution Transaction boundary.
*   The Emergency Stop / Kill-Switch.

## Consequences
Names and source layout do not create immutability. Acceptance requires an
external enforcement boundary, signed policy/evaluator identities, promotion
tests, and a kill switch that the candidate process cannot modify.
