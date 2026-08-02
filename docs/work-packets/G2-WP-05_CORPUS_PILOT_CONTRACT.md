# G2-WP-05 — Corpus Pilot Contract

## Purpose

Introduce a deterministic, repository-bound contract for the small Gate-2 polyglot corpus pilot without claiming that a license declaration is already a completed legal review.

## Scope

- canonical `daedalus-corpus-manifest/1` parsing and digesting;
- exact 40-hex Git revision pins;
- HTTPS GitHub clone identities;
- canonical, repository-contained include prefixes and license paths;
- explicit language-family declarations;
- explicit `declared`, `reviewed`, or `rejected` license-review state;
- content-addressed review evidence required before an entry may become `reviewed`;
- deterministic blockers while any entry remains unreviewed;
- CI verification that each pinned Git object resolves exactly and its declared license file exists;
- Python 3.10/3.12, hash-seed, malformed-input, stale-revision, packaging, and isolated-import checks.

## Pilot repositories

The initial manifest retains the already-used pinned polyglot probes for Apache Arrow, CERN ROOT, Spring Framework, and Tokio. The manifest is deliberately `closed_for_gate2=false`: repository identity and license-file presence are machine-verifiable, but an owner/legal review has not been fabricated.

## Threats covered

- symbolic branches or shortened revisions replacing exact object IDs;
- repository URL substitution;
- duplicate repository identities;
- path traversal in sparse-checkout or license fields;
- noncanonical manifest repackaging;
- stale or missing observed revisions;
- silently marking a license as reviewed without content-addressed evidence;
- hash-order-dependent manifest identity.

## Deliberate boundary

This packet does not create trusted semantic claims for the external repositories. Existing polyglot extraction remains `partial` wherever type, data, knowledge, or cross-plane semantics are incomplete. It does not close Gate 2, begin Gate 3, consume approval, merge a stack, or promote a candidate.
