# G2-PREP-GP01 — Bounded GraphProposal and deterministic verification

## Purpose

This non-authoritative Gate-2 preparation packet introduces the canonical
proposal boundary required by the adopted Fourfold plan:

```text
model output -> GraphProposal hypothesis -> deterministic verification
```

A proposal is not a graph mutation, accepted fact, materialized source tree,
publication request or promotion capability. Gate 0 remains the active
authoritative gate, and this packet does not start Gate 2 authoritatively.

## Canonical proposal identity

`GraphProposal` binds:

- one exact base `FourfoldSnapshot` digest and source revision;
- one objective;
- exact model, runtime and context-capsule manifest digests;
- a positive integer cost budget;
- one explicit `GraphWritableScope`;
- a sorted, unique set of typed `GraphOperation` records;
- exact provenance over every retained authority and operation digest.

The initial deliberately small operation vocabulary is:

- `add_binding`;
- `remove_binding`;
- `rename_concept`;
- `replace_relation`.

Every operation retains evidence digests. Binding removal and relation
replacement additionally bind the exact existing `CrossPlaneBinding` digest and
its semantic endpoints. Proposal construction establishes canonical identity
only; it does not prove that an evidence digest is authentic or sufficient.

## Writable scope

`GraphWritableScope` enumerates the exact planes, nodes and relation vocabulary
that a proposal may touch, together with explicit operation-family booleans.
There is no wildcard scope. The verifier rejects missing endpoints, out-of-scope
nodes or planes, disallowed relation vocabulary, no-op replacement, existing
binding collisions and conflicting operations.

## Deterministic verification

`verify_graph_proposal()` consumes caller-supplied verified evidence identities,
relation policy, verifier identity and verifier-policy digest. It emits one
sorted accepted/rejected `OperationDecision` per proposed operation and a
canonical `ProposalVerificationReport`.

It checks:

- exact base snapshot identity and source revision;
- operation evidence membership in the externally verified evidence set;
- source/target membership in the bounded scope and current snapshot;
- relation policy and scope vocabulary;
- exact binding digest plus endpoint/relation identity;
- duplicate existing or replacement bindings;
- removal/replacement conflicts and node conflicts.

Accepted operations remain unapplied. The module has no materializer,
publication, promotion, repository-write or snapshot-construction authority.
Downstream code must separately materialize a candidate, rebuild the Fourfold
Twin from the candidate source tree and compare the rebuilt result.

## Independent counter-review findings fixed

### Report-owned verifier authority

The first revalidation API recomputed a report using `verifier_id` and policy
digest taken from the report being checked. A self-consistent report could
therefore choose its own verifier authority. The consumer must now provide
`expected_verifier_id` and `expected_verifier_policy_sha256` independently.
Unexpected authority is refused before recomputation.

### Nested wire normalization

Canonical constructors sort provenance and evidence arrays. Calling a
constructor directly is useful for trusted in-process construction, but an
untrusted wire could otherwise reorder nested arrays and be normalized into the
same object. The public proposal and report parsers now reconstruct and compare
the complete input mapping against the canonical `to_dict()` representation.
Normalization is refused.

These are model-assisted counter-review findings, not independent human review,
owner approval or Gate evidence.

## Adversarial verification requested

Builder and separate review tests cover:

- all four operation families without snapshot mutation;
- canonical round-trip and unknown-field refusal;
- reordered operations and nested provenance arrays;
- stale snapshot/revision;
- absent verified evidence;
- narrowed relation policy;
- node/plane scope escape;
- binding-digest substitution;
- mutually conflicting operations;
- forged decision reports;
- report-owned verifier identity or policy;
- model prose that claims certainty without verified evidence;
- source review forbidding application, publication and promotion calls.

The bounded mutation campaign attacks six seams:

1. stale base-snapshot refusal;
2. evidence membership;
3. source-node scope;
4. binding digest identity;
5. consumer-owned verifier identity;
6. strict proposal-wire comparison.

Each mutation runs only after a green focused baseline, must be killed by the
focused tests, and the source file must be restored byte-exactly.

Dedicated CI requests Ubuntu and Windows, Python 3.10 and 3.12, two hash seeds,
Iron Plan verification, compile-all, Fourfold parent tests, builder and review
tests, mutation execution, the repository full suite and an isolated-wheel
import.

## Deliberate remaining boundary

This packet does not provide:

- proposal application or graph mutation;
- candidate source materialization;
- Graph Delta or RoundTripReport;
- a trusted evidence resolver or signature authority;
- general repository compiler coverage;
- compiler/SCIP semantic frontends;
- authoritative Gate-2 publication or closure.

Those remain separate sequential Work Packets. In particular, an accepted
proposal must never be treated as the rebuilt candidate Twin.

## External verification blocker

GitHub Actions issue #67 remains active: hosted jobs terminate before Step 1
with no step records or logs. Such runs cannot establish a product verdict. This
packet remains draft until exact-head commands execute.

## Gate state

- Active authoritative gate: Gate 0
- Gate-2 status: preparation only
- Promotion: not requested
- Gate closure: not claimed
