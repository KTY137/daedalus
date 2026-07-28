# ADR-006: Memory Separation

## Status
Proposed; operational event log partially implemented

## Context
The system currently mixes operational task logging with long-term conversational memory.

## Decision
We strictly separate memory into two domains:
*   **Ikarus Personal Memory**: Conversational history, user preferences, and semantic context. No backing system is selected by this ADR.
*   **Daedalus Operational Memory**: Append-only normalized event records, execution proofs, and audit logs.

## Consequences
The JSONL operational log and optional derived vector index are a first step.
They are not yet tamper-evident. Personal-memory consent, retention, deletion,
and access policies remain unspecified.
