# G0-RPT-08D — Read-only exact-head release verification

## Purpose

Provide one operator-facing, deterministic verification path for a retained
Gate-0 release report. The command consumes previously assembled artifacts and
rechecks them against current repository state. It does not assemble evidence,
issue trust, authenticate an owner decision, merge, promote, or write a report.

This packet is stacked on `G0-RPT-08C`. It does not close Gate 0 and cannot
replace the external collector, human architecture/security review, live
runtime evidence, fault evidence, or owner closure decision required by the
adopted plan.

## Inputs

The verifier requires all of the following explicitly:

- canonical `Gate0ReleaseReport` JSON;
- canonical mechanical `GateReport` JSON;
- canonical `GateEvidenceIndex` JSON;
- canonical authenticated `EvidenceTrustBundle` JSON;
- repository root used to re-hash retained workflow definitions;
- current commit revision and current tree revision;
- expected collector identity and key identity;
- one explicit `WORKFLOW_ID=REPOSITORY_PATH` mapping for every retained workflow;
- the collector secret through a named environment variable;
- an optional timezone-aware verification instant.

No repository, ref, workflow path, secret, revision, or owner identity is
discovered from an ambient default.

## Contracts

`daedalus.gates.release_io` loads untrusted release JSON with:

- strict UTF-8 decoding;
- recursive duplicate-key refusal;
- exact contract shape and derived-field verification;
- exact canonical wire equality after parsing;
- no normalization of a noncanonical attacker-controlled representation.

`python -m daedalus.gates.release_cli` emits exactly one JSON result:

```json
{
  "contract_type": "daedalus-gate0-release-verification/1",
  "release_sha256": "...",
  "source_revision": "...",
  "source_tree_revision": "...",
  "trusted": false,
  "blockers": []
}
```

Exit status is `0` only for a current trusted release, `1` for a valid release
with verification blockers, and `2` for malformed or unusable inputs. Secrets
are never accepted as command-line values and are never included in output.

## Adversarial cases

The focused suite covers:

- duplicate keys at top and nested levels;
- unknown, missing, trailing, invalid-UTF-8 and non-object JSON;
- forged derived closure and blocker fields;
- normalized but noncanonical provenance ordering;
- absent and undersized collector secrets;
- stale commit revision and changed workflow bytes;
- duplicate and incorrect adopted workflow path mappings;
- naive timestamps;
- substituted trust bundles and mechanical reports;
- byte-for-byte proof that successful verification does not mutate the checked repository.

A separate executable counter-review checks that the CLI cannot assemble a
release, issue credentials, promote, merge, update refs, spawn processes, or
write files, and that current verification remains the only decision source.
This is model-generated review support, not human, security, or owner evidence.

## Mutation campaign

The bounded campaign first requires the unmodified focused suite to pass, then
applies isolated mutants for:

1. duplicate-key acceptance;
2. noncanonical-wire acceptance;
3. ignoring the selected secret environment variable;
4. ignoring adopted workflow paths;
5. successful exit with blockers;
6. a forged `trusted=true` result;
7. successful exit for malformed input.

Every mutant must be killed and all source bytes restored.

## Requested verification

Dedicated CI requests:

- Ubuntu and Windows;
- Python 3.10 and 3.12;
- `PYTHONHASHSEED=0` and `123456`;
- Iron Plan verification;
- compileall;
- parent release, malformed-input, stale-revision, bypass and counter-review tests;
- the bounded mutation campaign;
- repository full suite on Ubuntu/Python 3.12;
- isolated wheel import and CLI `--help` outside the checkout.

GitHub Actions issue #67 currently prevents any hosted job from reaching Step
1. Until that external condition is repaired, workflow conclusions are not
product evidence and this packet remains builder-prepared rather than verified.

## Non-goals

- no evidence collection;
- no collector or owner key issuance;
- no OwnerApproval construction;
- no release assembly;
- no repository write;
- no merge, promotion, branch movement, or automatic Gate closure.
