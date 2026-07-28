# ADR-005: Task Groups (Agent Crews)

## Status
Proposed; not implemented

## Context
Complex missions require multiple specialized agents (e.g., Architect, Builder, Reviewer) working in tandem.

## Decision
We may introduce `TaskGroup` after Kairos has a real dependency graph and
artifact contract. A TaskGroup would define a controlled agent crew with:
*   Pre-defined dependencies (e.g., Builder waits for Architect).
*   Artifact-based communication (no free-form chatter).
*   A shared isolated workspace.
*   Unified Cerberus policy scope.

## Consequences
This is a design hypothesis. It requires evaluation against single-agent and
simple pipeline baselines before acceptance.
