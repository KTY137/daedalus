# G1-IKARUS-17 — General computer assistant amendment

Packet ID: G1-IKARUS-17
Artifact role: primary
Active gate: 1
Classification: AMENDMENT
Owner: repository owner
Base revision: 61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0
Dependencies: explicit owner approval of amendment proposal 012 on 2026-09-05
Status: adoption, builder verification and independent review complete.
Base plan: revision 11 / version 2.2.0, SHA-256
`711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`.
Dependency: explicit owner reply `ja implmenetierer` on 2026-09-05 to the
request to approve `docs/AMENDMENT_PROPOSAL_012_GENERAL_COMPUTER_ASSISTANT.md`.

## Primary acceptance claim

Adopt exactly the proposed revision-12 product scope and preserve a truthful,
append-only record of the actual base, owner approval, and historical gap.
This packet grants no runtime capability and establishes no computer-control
or Hermes-parity claim.

## Scope

Permitted paths are the master plan, its amendment JSONL, proposal 012, this
packet, and `docs/evidence/G1-IKARUS-17_AMENDMENT_VALIDATION.json`.
AGENTS.md, runtime code, tests, policy, and unrelated working-tree changes are
excluded. No commit, merge, promotion, or live computer effects belong here.

## Contracts and behavior

The accepted amendment changes the plan's general-assistant product scope,
not runtime authorization. The append-only amendment record binds the exact
base and result plan bytes and preserves the known historical gap. Runtime
capabilities remain subject to the dependent implementation packets and
canonical policy, evidence and promotion contracts.

## Acceptance matrix

| Check | Acceptance |
| --- | --- |
| Base identity | Current plan bytes equal proposal's full SHA-256 and retained Git revision-11 blob |
| Exact change | Only proposal's metadata, mode list, section 7.2, Gate-1 heading/paragraph and revision-12 decision note change |
| Record integrity | Existing ledger bytes unchanged; exactly one accepted revision-12 record appended; canonical record hash and previous-record link verify |
| Actual lineage | Record base binds measured revision 11; missing revision-11 ledger record remains explicit; no fabricated historic approval |
| Instruction preservation | AGENTS.md SHA-256 unchanged |
| Policy verification | Existing sensitivity policy pin suite passes; retired mechanical plan guard is not restored |
| Fault checks | Wrong base hash, mutated new record and changed preceding ledger bytes are detected by the verification procedure |
| Independent review | Separate reviewer checks exact scope, hashes, historical-gap honesty and no runtime authority grant |

## Baseline and retained negative evidence

All ten existing record hashes verify using UTF-8 JSON with sorted keys,
`ensure_ascii=False`, separators `(',', ':')`, excluding `record_sha256`.
The pre-edit ledger SHA-256 is
`26480bfaf1aa69b67a0ec75da262f66c4f179481c38e27bc54b3dd646a51f102`.
Its final record is sequence 10 / revision 10 with record hash
`6aba56d180a938b67829863c902b1ed7206f9abe3e5bf460e38eae5457973636`.
AGENTS.md SHA-256 is
`3ca6b4be45e5e39efcbf38823611dd6dca0ba7afc095a372500f9a4c499c6194`.

Revision 11's exact current bytes are retained at Git commit
`d9655df2412e9a87762c15ed84b6bcc62f2d9c83`. That owner-authored commit is
explicitly a NON-PROMOTABLE recovery checkpoint, not independent evidence of
the referenced amendment approval. The plan itself asserts exact owner
approval, but no independent approval reference or proposal 011 was found in
the inspected docs and Git history. A retrospective accepted revision-11
record would therefore invent evidence. Revision 12 links to the actual last
record and names this gap instead; the gap is not reported as repaired.

## Migration and rollback

The implementation packets reuse the kernel and activate each capability only
after its own real adapter matrix passes. The plan remains at Gate 1. Existing
software contracts, four-plane priors, promotion rules and policy boundaries
remain binding. Constitutional rollback requires a new approved amendment.

Review must distinguish the valid new record chain link from the retained
historical plan-lineage discontinuity. A passing hash check does not prove an
unrecorded approval. A governance adoption does not prove runtime behavior.

## Evidence, expected failures and review

Applied the approved metadata, mode bullet, section 7.2, Gate-1 changes and
revision-12 decision note. The new plan SHA-256 is
`126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb`.
The one appended record is sequence 11 / result revision 12, SHA-256
`6d1c0d6f3a7d5986be1f5d7d13cb6f1a1199e165aae0f0735ae2857f4c9289a7`.
The amendment mutation process set `DAEDALUS_IRON_PLAN_AMENDMENT` to the full
measured base SHA-256 before writing the plan and ledger.

An inverse of the exact eleven plan substitutions recovered the original
revision-11 bytes before mutation. Post-write verification checked all eleven
record hashes and previous-record links, the original ledger prefix digest,
the plan/result digest, and unchanged AGENTS.md. In-memory mutation comparisons
detected a wrong base hash, changed record result revision and changed original
ledger prefix. These checks measure data integrity, not a security boundary.

`python -m pytest -q tests/test_sensitivity_default_policy_pins.py tests/test_docs_reference_check.py`
completed with **19 passed, 78 subtests passed in 26.21 seconds**. No new runtime
test or runtime success claim belongs to this documentation packet. The retired
mechanical plan guard remains absent. Default `git diff --check` flags the
preserved Markdown two-space hard break on modified metadata line 9;
`git -c core.whitespace=-blank-at-eol diff --check -- docs/IKARUS_ARIADNE_MASTER_PLAN.md docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`
passes.

All results and the explicit historical gap are retained in
`docs/evidence/G1-IKARUS-17_AMENDMENT_VALIDATION.json`. Independent review is
complete: root reviewer on 2026-09-05 inspected the exact diff, unchanged
invariants, explicit historical gap and single appended record and accepted
the governance parent for dependent implementation. No merge or promotion has
been performed.

Reproduce the base identity with
`git show d9655df2412e9a87762c15ed84b6bcc62f2d9c83:docs/IKARUS_ARIADNE_MASTER_PLAN.md`
and SHA-256 of its raw bytes. To reproduce the ledger checks, parse each JSONL
record, remove only `record_sha256`, serialize with the canonical JSON settings
listed under Baseline, and compare SHA-256 and each `previous_record_sha256`.
Hash the prefix of `original_ledger_byte_length` bytes from the evidence JSON
and compare `base_ledger_sha256`; compare the complete plan file to the final
record's `result_plan_sha256`. Result revision 12 intentionally has sequence 11.
