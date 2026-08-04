# G0-RWI-20G — Authenticated Guard Implementation Manifest

## Parent and scope

This Work Packet is stacked on exact parent
`515299546278d8471b11e7608e8d9daf31d495fc` from
`g0/repository-write-source-anchor-semantics-linear`.

It introduces one additive, read-only authentication contract for a short-lived
manifest that maps each declared guard contract to an exact Daedalus Python
target and source digest. It does not inspect the repository tree, replay guard
behavior, alter the canonical effect registry, bind GateReport-v2, issue
OwnerApproval, merge, promote, or close Gate 0.

## Authenticated subject

The signed subject binds:

- manifest, authority, and key identities;
- exact source revision and repository-write classification digest;
- a non-empty canonical set of unique guard-contract records;
- each exact contract, implementation target, and implementation digest;
- canonical issuance and expiry timestamps with a maximum 24-hour lifetime.

The verifier resolves an externally provisioned authority key, authenticates the
HMAC-SHA256 signature, and only then compares expected authority, revision, and
classification bindings. Future, expired, substituted, unknown-key, malformed,
noncanonical, duplicate-key, non-finite, NUL-containing, BOM-prefixed, and
oversized manifests fail closed.

## Non-authority boundary

Manifest authentication is not guard semantic verification. This packet does not
prove that an implementation target exists, that its digest matches current
source bytes, that a guard executed, or that any effect is safe. The report is
therefore permanently open and asserts:

- `guard_manifest_authenticated=true`;
- `guard_contract_semantics_verified=false`;
- `semantic_receipts_verified=false`;
- `evidence_authenticated=false`;
- `gate_report_bound=false`;
- `closed=false`.

A dependent packet must join this manifest with the authenticated source-anchor
chain and semantically replay every guard-evidence object against exact current
source bytes.

## Adversarial batch

Prepared coverage includes deterministic issuance/parse/verify, strict record
shape and uniqueness, malformed and empty input, signature-first verification,
unknown and substituted keys, stale revision and classification, authority
substitution, future/expiry/TTL faults, signed entry substitution, strict
canonical wire handling, source-level authority review, and eight bounded
mutants.

An isolated compatibility harness executed the focused and source-review tests
with `27 passed` and killed all eight bounded mutants. This is preparatory
author-side evidence only. It is not exact-head repository, supported-platform,
packaging, independent-human, semantic-runtime, or Gate evidence.

Exact-head CI requests Ubuntu and Windows on Python 3.10 and 3.12 with two hash
seeds, predecessor regressions, mutation, Iron Plan verification, full suite,
package build, and isolated-wheel import. GitHub Actions issue #67 still prevents
hosted jobs from reaching Step 1; zero-step runs are infrastructure observations
only.

No merge, promotion, automatic action, OwnerApproval, or Gate transition is
requested.
