# G0-EVD-08E — Canonical exact-head evidence-index wire

## Purpose

Refuse alternate untrusted JSON or Python mapping representations that would
otherwise normalize into the same `GateEvidenceIndex` identity.

`GateEvidenceIndex.from_dict` is intentionally useful for already typed internal
values and canonicalizes requirement arrays, retained record order and nested
provenance. The supported untrusted wire boundary must be stricter: after shape
validation it reconstructs the index and requires the submitted mapping to equal
`index.to_dict()` exactly.

This packet is stacked on the current Gate-0 runtime-authorization line. It does
not collect evidence, authenticate a collector, issue a release receipt, change
an effectful entrypoint, merge, promote or close Gate 0.

## Boundary

`parse_gate_evidence_index` now performs:

1. object and recursive array/object shape checks;
2. reconstruction through the existing canonical contract;
3. complete submitted-wire equality against `GateEvidenceIndex.to_dict()`.

`load_gate_evidence_index` continues to add strict UTF-8 JSON parsing and
recursive duplicate-key refusal before calling that parser.

The equality check rejects, among other cases:

- reordered required review perspectives;
- reordered retained evidence records;
- reordered nested provenance inputs;
- Python tuples presented as an alternate array wire;
- any other parseable representation normalized by nested contracts.

This does not change the canonical evidence digest or internal constructor.

## Adversarial evidence

Focused tests retain the existing string-as-array, malformed nested record,
duplicate-key and non-object refusals, and add:

- exact mapping and file round trips;
- top-level requirement reordering;
- nested provenance input reordering;
- tuple/list wire substitution;
- reordered review records through the file loader;
- an executable source counter-review pinning reconstruction and complete wire equality.

A bounded mutation removes only the complete-wire equality check. The focused
behavioral and counter-review suites must kill it, and source restoration must
remain byte exact.

## Remaining adjacent boundary

`EvidenceTrustBundle` is separately signed and its direct parser has its own
canonical-wire review surface. That surface is intentionally not folded into
this packet; it remains a later small dependent hardening batch rather than a
combined evidence rewrite.

## External blocker

GitHub Actions issue #67 currently causes hosted jobs to terminate before Step 1
with no logs or artifacts. Such runs establish no code, mutation, package,
Python-version or platform verdict.

## Gate state

- Iron Plan: aligned by scope; exact-head execution required
- Active gate: Gate 0
- Promotion: not requested
- Gate closure: not claimed
