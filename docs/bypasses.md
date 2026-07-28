# Known Bypasses and Security Gaps

Status: audited 2026-07-28. Cerberus, Nemesis, and a security-grade
execution-transaction boundary are proposed components, not current guarantees.
This document records concrete paths that a future enforcement design must
cover.

## 1. Multiple Network and Provider Paths

Network access is not centralized. Ollama/provider modules, runtime discovery,
semantic routing, embeddings, evaluation probes, and core health checks make
their own HTTP calls. Some of these are legitimate read-only probes, but no
single policy boundary can currently inventory or intercept them.

Remediation:

* classify each endpoint as discovery, inference, telemetry, or mutation;
* route inference and mutation through one capability-checked service;
* enforce egress at the process/container boundary, not by Python convention;
* emit a lossless transport record for each authorized call.

## 2. Filesystem and Process Access

`FileBridge` and `SubprocessAdapter` are useful interfaces, but Python code can
still call the filesystem, `subprocess`, or network APIs directly. A Git
worktree isolates changes from the primary checkout; it does not isolate the
host or secrets.

Remediation:

* define a mutation transaction and receipt;
* run untrusted agent commands inside an OS/container sandbox with explicit
  mounts, environment, network policy, time, memory, and process limits;
* keep policy and evaluator code outside the writable transaction;
* make promotion a separate, authenticated action.

## 3. State and Memory

Operational JSONL records are append-only by convention, not tamper-evident.
The optional vector database is a derived search index and must never become
the authoritative record. Personal-memory consent, retention, deletion, and
access control are not defined.

## 4. Scheduler and Persona Separation

The Kairos name (formerly Metron) has been separated from the Ikarus
compatibility/persona surface, but Kairos is not yet a general DAG scheduler and Ikarus has no selected
upstream framework. A future extraction should be contract-driven rather than
based on an unverified dependency.

## 5. `structcore-rs` Parity

The Rust implementation lags behind the Python reference for slicing,
tokenization, provenance, topology, and the Forest schema. It must either gain
fixture-level parity or remain explicitly experimental; platform packaging
must not silently select it as an equivalent backend.
