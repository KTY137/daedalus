# G1-ARIADNE-07 — Council-driven hardening of the stage 3 to 6 packets

Packet ID: G1-ARIADNE-07

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: b59b2628ad6ed85a8b5e729a12c58512543e2e73

Working-tree context: isolated worktree `.claude/worktrees/stage3-failed-receipt`, branch `loop/stage3-failed-receipt`, stacked on commit 4630d07c

Dependencies: `G1-ARIADNE-04_FAILED_RECEIPT_ON_FIRST_CALL`, `G1-ARIADNE-05_WORKING_TREE_BASE_BINDING`, `G1-ARIADNE-06_NAMED_REFUSALS`

Stage: 12 of the owner-directed 2026-09-05 loop; the first stage after the owner lifted the budget, reviewed live by two vendors.

## Primary acceptance claim

The live cross-vendor council over the stage 3 to 6 code diff (Codex and Claude, two rounds, 24 checkable claims, all with deterministic checks) is answered in code and tests: a refusal or conflict raised inside an arm is never returned as a failed receipt, the base binding is a required input of every failed receipt, a missing repository root is a typed refusal before any observation, target-path admission precedes the revision shape check, and eleven discriminating tests pin the council's runtime checks (terminal state after a failed first call, reconciliation failure still raising, the reachable receipt-equality conflict branch, HEAD binding errors on either observation, the ABA move, nested POSIX target paths, index-independent fresh bindings, replay after working-tree drift).

## Council record

Bus: `runs/council/council-20260905T134012Z-1eb0b866.jsonl` in this worktree, chain intact. Quorum 2 of 2 seats (OpenAI via codex-cli 0.153.0 through the shim, Anthropic via claude CLI), two distinct weight families; Google and the bench Ollama were not seated. Convened through the registered `cli.council` door under the owner's `unbounded_execution` policy; both seats were priced into the worktree ledger (estimates 2.00 and 3.00 USD). Advisory only.

Dissents, by author (the falsifier is the Anthropic seat in round 1; the security seat is Anthropic in round 2; the maintainer seat is OpenAI in round 2):

- **Falsifier r1:** `_is_domain_failure` is only as narrow as the exception hierarchy; `AriadneRequestError` and `AriadneConflictError` subclass `AriadneCampaignError`, so a refusal raised inside the arm would be returned as a settled failed receipt. **Security r2:** the risk is misplaced, durability is unaffected because the return sits after commit and settlement. **Resolution:** both right on their axis; the predicate now excludes the two subclasses (verified: both subclass `AriadneCampaignError`), pinned by `test_request_and_conflict_errors_inside_an_arm_still_raise_on_the_first_call`.
- **Falsifier r1:** the `return` may skip outer handlers that settle the campaign. **Security r2 and maintainer r2:** contradicted by the code order (`_complete_failed_campaign_receipt` and settlement precede the return) and by the pre-diff replay behaviour; keep the different-id call as the runtime discriminator. **Resolution:** pinned by `test_failed_first_call_is_terminal_and_does_not_block_the_next_campaign` (replay identical, a second id runs) and `test_reconciliation_failure_after_the_failed_receipt_raises_instead_of_returning` (fault injection at the inner-terminal check raises, never returns a dict).
- **Falsifier r1:** the `to_dict() !=` conflict branch is never exercised. **Security r2:** possibly dead code if the receipt only carries the commit id. **Measured:** the head receipt carries `head_mode`, `head_ref`, `resolution_source`, digests, paths and sizes and no time field, so a ref switch that keeps the revision reaches the branch; pinned by `test_head_ref_change_with_the_same_revision_is_a_conflict` and, for binding errors on either observation, `test_head_binding_error_on_either_observation_is_a_conflict_before_state` (maintainer r2).
- **Falsifier r1:** the ABA move (X to Y to X during the read) is undetected. **Accepted as a limitation**, honest because the base is declared working-tree with `head_content_verified` false; pinned by `test_aba_head_move_during_the_read_stays_honest_in_the_binding`.
- **Falsifier r1:** the binding is only call-site discipline (`base_binding_sha256` defaulted to `None`). **Resolution:** parameter made required; all three call sites pass it (measured: 3 of 3).
- **Falsifier r1 / maintainer r2:** no test proved a failed receipt carries the binding, and an LF-hardcoded expectation would lie on Windows. **Resolution:** the failed-first-call test asserts the binding against bytes read from disk.
- **Falsifier r1:** OS separators in `target_path` would break cross-host digests. Pinned by `test_nested_target_path_is_posix_in_the_binding` (`src/sample.txt`).
- **Falsifier r1 / security r2:** non-ASCII target names and `.encode("ascii")`. **Measured:** `canonical_json` escapes non-ASCII (`é`), so the encoding cannot raise.
- **Falsifier r1 / security r2:** host paths in the kernel refusal message. **Measured:** the two facade messages are raised before any effect and can never become a blocker; the kernel message is an operator-local diagnostic returned in the loopback HTTP error body, not written to spine or CAS. Kept, recorded.
- **Falsifier r1 / security r2:** the pure-refusals-first claim was imprecise: `resolve(strict=True)` and the revision shape check ran before target admission, and a missing root was an untyped `FileNotFoundError` (pre-existing). **Resolution:** target admission now precedes the revision shape check; a missing or unsafe root is `AriadneRequestError("repo_root is unavailable or unsafe: ...")`; pinned by `test_missing_repo_root_is_a_typed_pre_observation_refusal`.
- **Falsifier r1 / security r2:** an unstubbed HTTP end-to-end test would only add value if the thin wrapper branched on `outcome`; it does not. Not added, recorded.
- **Falsifier r1 / maintainer r2:** replay determinism after a working-tree change and index-independence of fresh construction. **Measured and pinned:** `test_two_fresh_campaigns_bind_identically_across_a_staging_change`; `test_replay_after_the_working_tree_changed_returns_the_stored_receipt_unchanged` records a third honest outcome the council did not name: with drifted bytes the identical request is refused before any replay because the `before` fragment no longer occurs (the base bytes are part of the operation identity), and once the bytes are restored the stored receipt is served unchanged.

Convergence (an observation, not a vote): both seats agreed the returned failed receipt cannot be premature (commit and settlement precede the return) and that the message changes reach no retained artifact.

## Scope

In scope: `daedalus/ariadne/campaign.py` (`_is_domain_failure`, the failed-receipt builder signature, the admission order and the typed root refusal) and `tests/test_ariadne_campaign_v0.py`. Out of scope: the HEAD verifier, the kernel lifecycle, HTTP, the workbench.

## Contracts and behavior

- `_is_domain_failure`: `LoopHalted`, `AriadneRequestError`, `AriadneConflictError` and every foreign exception keep raising; only other `AriadneCampaignError` verdicts return the committed failed receipt.
- `_complete_failed_campaign_receipt(..., base_binding_sha256: str, ...)`: required.
- `run_campaign` order: `_admit_target_path` (pure) -> revision shape check (pure) -> `Path(repo_root).resolve(strict=True)` wrapped as `AriadneRequestError` -> HEAD observation -> target read -> HEAD observation.

## Acceptance matrix

| Check | Result (2026-09-05, worktree) |
| --- | --- |
| eleven council-derived tests before the code change | 4 failed, 7 passed |
| after the change | 11 passed (35.0 s) |
| council facts checked: hierarchy (both subclasses), call sites (3 of 3), `canonical_json` ASCII escaping, no time field in the head receipt | all as recorded above |
| stage suites (campaign, HTTP Ariadne, producer census, CLI boundary) | 147 passed (176.7 s), 0 failed |

## Migration and rollback

Rollback restores the wider predicate, the optional binding parameter and the previous admission order, and drops the eleven tests. Retained receipts are unaffected.

## Evidence, expected failures, and review

The council transcript is retained in this worktree; the falsifier's HTTP end-to-end request and the CRLF caveat are recorded as not adopted with the reason. Nothing merged or promoted.

Iron Plan: **ALIGNED**

Iron Gate: **1**

Automatic merge/promotion: **forbidden**
