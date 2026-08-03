# G0-WP-05 — Fault Matrix Foundation

## Purpose

Collect the existing fail-closed Gate-0 tests into one deterministic, machine-readable CI matrix without claiming that the complete host/runtime fault campaign is finished.

This packet is evidence orchestration only. It does not weaken a guard, change an effectful production path, consume an owner approval, promote a candidate, or mutate the primary checkout.

## Covered boundaries

The matrix executes the current negative and stale-state coverage for:

- authenticated OwnerApproval, expiry, replay and atomic consumption;
- persisted EffectLease issue, grant, start, replay, scope, concurrency and revocation;
- runtime-manifest completeness, failed observations and stale conformance receipts;
- Docker sandbox image pinning, non-root execution, offline networking, read-only mounts and shell refusal;
- sealed promotion binding to candidate batch, EvidencePacket, base revision and freshly resolved target HEAD;
- central effect-boundary registration, declared effects and guard-decision completeness;
- deterministic Gate-0 reporting and blocker monotonicity.

Each supported Python/hash-seed cell emits a JUnit XML artifact. Those reports are evidence inputs, not an LLM assertion and not by themselves a Gate-0 closure receipt.

## Determinism and packaging

CI runs Python 3.10 and 3.12 with `PYTHONHASHSEED=0` and `123456`. A separate job builds a wheel, installs it into an isolated virtual environment, changes to a foreign directory and imports the Gate-0 trust modules from the installed package.

## Remaining work

This packet does not yet provide:

- live Claude, Codex and Ollama runtime fault injection;
- Docker daemon, host crash, disk-full, process-kill or network-partition experiments;
- full effectful-entrypoint centralization;
- proof that no primary-checkout mutation is reachable through every legacy callable;
- independent architecture/security sign-off;
- an owner-approved Gate-0 closure decision.

These remain explicit blockers. Gate reporting must remain `closed=false` while any such blocker is present.

## Acceptance

- the four Python/hash-seed cells pass;
- every cell uploads a non-empty JUnit report;
- the isolated wheel imports all trust-boundary modules;
- no production registry row is upgraded by this packet;
- no merge or promotion is requested automatically.
