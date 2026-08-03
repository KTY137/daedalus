# G0-EVD-08F — Canonical signed trust-bundle wire

## Purpose

Refuse alternate untrusted representations of one signed
`EvidenceTrustBundle` while preserving the existing package and direct-module
import names during the Gate-0 strangler migration.

The internal contract constructor intentionally sorts workflow anchors,
trusted-digest arrays and provenance inputs. That is useful for already typed
values but unsafe as the final signed-wire boundary: a differently ordered input
could normalize into the same object and signature identity.

This packet is stacked on `G0-EVD-08E`. It does not issue or authenticate a real
collector bundle, collect evidence, issue a release receipt, alter an effectful
entrypoint, merge, promote or close Gate 0.

## Strict boundary

`daedalus.gates.trust_bundle_io` provides the supported untrusted parser and
loader:

1. require an object and nested provenance object;
2. reconstruct `EvidenceTrustBundle` through the existing contract;
3. require complete submitted-wire equality with `bundle.to_dict()`;
4. for files, require strict UTF-8 JSON and reject duplicate keys recursively.

The boundary refuses reordered signed digest arrays, reordered provenance
inputs, tuple/list substitution and any other representation changed by nested
canonical constructors.

## Compatibility strangler

The historical names remain import-compatible:

- `daedalus.gates.parse_evidence_trust_bundle`;
- `daedalus.gates.load_evidence_trust_bundle`;
- `daedalus.gates.trust_bundle.parse_evidence_trust_bundle`;
- `daedalus.gates.trust_bundle.load_evidence_trust_bundle`.

Package initialization installs the strict functions onto the existing
`trust_bundle` module attributes. This is an explicit temporary strangler
adapter: existing callers keep their import paths while the permissive direct
wire behavior is no longer reachable through normal package import.

The contract, signature algorithm, verifier and bundle digest are unchanged.
A later file-tree cleanup may move the strict implementation into the authority
module after all compatibility callers are inventoried; that cleanup is not
combined with this security patch.

## Adversarial evidence

Focused tests cover:

- exact canonical mapping and file round trips;
- reordered signed review-evidence digests;
- reordered signed provenance input digests;
- tuple/list substitution;
- recursive duplicate keys;
- identity of package and direct-module compatibility functions;
- an executable source counter-review pinning reconstruction, complete wire
  equality and both compatibility assignments.

The bounded mutation campaign applies three isolated regressions after a green
baseline:

1. remove complete trust-bundle wire equality;
2. leave the direct-module parser on its permissive implementation;
3. leave the direct-module loader on its permissive implementation.

Every mutant must be killed and all source bytes restored.

## Evidence boundary

These tests prove only that selected source paths refuse the targeted malformed
representations when executed. They do not authenticate a collector, establish
human architecture/security review, provide OwnerApproval, or constitute an
operational Gate release.

## External blocker

GitHub Actions issue #67 currently causes hosted jobs to terminate before Step 1
with no logs or artifacts. Such runs establish no code, mutation, package,
Python-version or platform verdict.

## Gate state

- Iron Plan: aligned by scope; exact-head execution required
- Active gate: Gate 0
- Promotion: not requested
- Gate closure: not claimed
