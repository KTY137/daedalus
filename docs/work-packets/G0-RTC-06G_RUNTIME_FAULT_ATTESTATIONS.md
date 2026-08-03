# G0-RTC-06G — Runtime fault observation attestations

## Objective

Authenticate runtime-fault observation records before they are admitted into
the trusted digest set used by the runtime fault-matrix verifier.

This packet is stacked on `G0-RTC-06F`. It does not execute a fault, create raw
evidence, provision a production key, call a live provider, close the runtime
matrix, or close Gate 0.

## Authority boundary

A `RuntimeFaultObservation` remains an untrusted canonical record. A separate
`RuntimeFaultAttestation` binds:

- the exact complete observation-record digest;
- canonical catalog digest and scenario ID;
- exact source revision;
- observation authority class;
- external issuer and key identity;
- a nonce; and
- a bounded issue/expiry window.

The signature is HMAC-SHA256 using caller-supplied key material of at least 32
bytes. No key is loaded from repository configuration or persisted by this
packet.

## Issuer policy

Verification receives two external inputs:

1. a keyring keyed by `(issuer_id, key_id)`; and
2. an issuer-to-authority policy.

An issuer authorized for deterministic fixture CI cannot attest Linux-host or
live-runtime evidence. Unknown issuers, unknown keys, malformed authority
policies, weak keys, signature mismatch and cross-authority use fail closed.

The caller is responsible for protecting those external inputs. A candidate
that supplies its own key or expands its own issuer policy has not crossed this
boundary and cannot produce trusted Gate evidence.

## Matrix assembly

`verify_attested_runtime_fault_matrix`:

1. rejects duplicate attestation IDs, duplicate issuer/key/nonces and multiple
   attestations for one scenario;
2. locates the exact observation retained by the matrix;
3. verifies catalog, scenario, observation digest, source revision, authority,
   issuer policy, signature and validity window;
4. derives the trusted observation-record digest set; and
5. delegates completeness, status and observed-outcome checks to the canonical
   runtime fault-matrix verifier.

A missing attestation remains an `untrusted-observation` blocker. A valid
attestation for a failed, blocked or outcome-mismatched observation does not
convert it into success.

Attestations are evidence authentication records, not one-use effect
capabilities. Reuse for the exact same observation, catalog and revision within
the validity window is allowed. Cross-revision or repackaged reuse fails because
the complete observation digest and revision are signed.

## Adversarial coverage

The focused tests request coverage for:

- exact round trip and signature verification;
- candidate-controlled signing keys;
- unknown and weak keys;
- signature tampering;
- cross-authority issuer use;
- foreign catalog, scenario, observation and source revision;
- future, expired and overlong attestations;
- duplicate IDs, nonces and per-scenario attestations;
- attestations targeting observations absent from the matrix;
- missing attestations;
- valid attestations over failed/blocked observations; and
- valid attestations over a passing record with the wrong observed terminal
  outcome.

## Verification contract

The dedicated workflow requests:

- Python 3.10 and 3.12;
- `PYTHONHASHSEED=0` and `123456`;
- Iron Plan verification and compile-all;
- attestation and canonical catalog contract tests; and
- an isolated wheel import smoke.

Exact-head CI remains subject to the repository-wide zero-step Actions blocker.
A job with `steps=null` and no logs is infrastructure evidence only.

## Deliberate remaining blockers

- Production issuer keys and issuer-authority policy are not provisioned.
- No GitHub/host/live evidence collector signs observation records yet.
- Raw evidence availability and authenticity remain collector responsibilities.
- Linux-host and live-runtime scenarios remain unexecuted.
- Provider public entrypoints remain non-central.
- Gate 0 remains open.

Iron Plan: **ALIGNED**  
Active gate: **Gate 0**  
Promotion: **not requested**
