# ADR-003: Mission API as Trust Boundary

## Status
Proposed; not implemented as a security boundary

## Context
Agents need a way to receive tasks and submit results without compromising the host system.

## Decision
The Mission API (`web_api.py`) is one ingress, not the sole ingress. CLI,
provider, file, and subprocess paths also exist. A future trust-boundary design
must inventory and authenticate every ingress and route mutations through one
policy-enforced execution service.

## Consequences
The current HTTP API does not, by itself, provide this guarantee.
