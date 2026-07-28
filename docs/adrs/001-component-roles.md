# ADR-001: Component Roles

## Status
Proposed; names partially implemented

## Context
The Daedalus AgentOS project originally conflated Ikarus (the conversational persona) and the internal task scheduler. As the architecture scales to support controlled agent crews and multi-provider execution, a clear separation of concerns is required.

## Decision
We enforce strict responsibilities for the core system components:
*   **Ikarus**: The Jarvis-like conversational persona (Voice, Memory, Skills, UI).
*   **Daedalus**: The trusted AgentOS kernel and execution environment.
*   **Kairos**: The task scheduler and orchestrator (formerly known internally as Ikarus, then Metron). The current scheduler is not a general DAG engine.
*   **Cerberus**: The Policy Engine and approval boundary.
*   **Nemesis**: The independent adversarial Verifier.

## Consequences
These names are the intended vocabulary. They do not imply that Cerberus,
Nemesis, or a DAG scheduler already exist. This ADR may become Accepted only
after each role has an executable contract and conformance tests.
