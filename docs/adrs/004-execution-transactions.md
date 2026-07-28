# ADR-004: Execution Transactions

## Status
Proposed; worktree prototype only

## Context
LLM-generated code and commands are inherently untrusted and must be verified before being permanently applied to the host repository.

## Decision
All agent mutations should eventually occur inside a transaction with a
declared base revision, policy, resource limits, captured events, validation
receipt, and explicit promotion. A Git worktree provides change isolation but
is not a host-security sandbox.

## Consequences
The current shadow-worktree prototype reduces accidental workspace edits. It
does not yet prevent hostile host commands or define a production promotion
path, and Nemesis is not implemented.
