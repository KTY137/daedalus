# ADR-008: Universal Agent Adapter Protocol

## Status
Experimental; transport core partially implemented

## Context
Daedalus needs to integrate agent CLIs and APIs without erasing provenance,
telemetry, or isolation boundaries.

## Decision
We implement an adapter and event-envelope boundary within `daedalus.adapters`.

* **Lossless transport first**: provider events are preserved in normalized
  `TransportRecord` envelopes before optional text or embedding projections.
* **Honest capabilities**: a profile advertises only operations verified against
  that runtime. Hidden-state access is always explicit and is not inferred from
  textual output.
* **Controlled launch**: the kernel supplies the working directory, prompt,
  timeout, and event sink.
* **Derived latent index**: embeddings are disposable retrieval projections;
  the original event stream remains authoritative.

## Consequences
The current subprocess implementation has verified Claude and Codex profiles
plus a generic runtime configuration. Arbitrary approval handshakes, resumable
interactive sessions, Ollama/Antigravity profiles, and internal hidden-state
transport are not implemented. A normalized text stream enables observation
and retrieval; it does not by itself constitute latent-space communication.
