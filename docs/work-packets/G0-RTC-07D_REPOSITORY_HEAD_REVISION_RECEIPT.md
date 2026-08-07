# G0-RTC-07D — Repository HEAD Revision Receipt

## Exact parent

This packet starts from `47c631fd5dc0fde3c5fc7aaff1f0d47830f72263` on `g0/provider-executable-structure-receipt-r2-linear` and remains a separate short-lived Gate-0 branch.

## Purpose

The signed provider target and structural receipts retain a `source_revision`, but neither proves that the selected checkout currently has that revision at `HEAD`. This packet introduces a generic, process-free repository-HEAD verifier. It does not yet compose the two receipt families; that is a later small packet after both boundaries have exact-head evidence.

The verifier supports three conservative metadata shapes in a canonical checkout:

- detached `HEAD` containing an exact lowercase 40-hex revision;
- symbolic `HEAD` resolved through one exact loose ref;
- symbolic `HEAD` resolved through one exact row in `packed-refs`.

It reads all Git metadata through the shared race-aware repository source reader, performs two complete observations, and checks repository-root and `.git` directory identity across the operation. A loose-ref symlink is rejected rather than hidden by packed-ref fallback. Gitfile worktrees, nested symbolic refs, malformed refs, duplicate packed rows and changing observations refuse without a partial success claim.

## Authority boundary

The receipt proves only that the caller's expected revision matched a stable supported `HEAD` observation. It permanently records:

- `repository_head_verified=true`
- `commit_object_verified=false`
- `worktree_clean_verified=false`
- `process_spawned=false`
- `repository_mutated=false`

No `git` executable is invoked. The packet does not inspect a commit object, compare the whole worktree to a tree, import or execute provider code, authorize provider execution, begin an effect, issue OwnerApproval or PromotionReceipt, or change a Gate state.

The generic receipt is not itself proof that the provider structure receipt was revision-bound. A later composite verifier must reverify both receipts and require `structure_receipt.source_revision == head_receipt.expected_revision` before any guarded loader work.

## Adversarial batch

Prepared builder and counter-review coverage includes detached, loose and packed resolution; stale revision; malformed and multiline HEAD; forbidden ref forms; missing and duplicate refs; gitfile and symlink refusal; a between-observation race; detached retained fields; unsupported wire claims; strict integer shapes; independent AST review for process, network, write and effect authority; and ten bounded mutants targeting observation, comparison, symlink, uniqueness, claim and live-reverification fences.

CI requests Ubuntu and Windows, Python 3.10 and 3.12, two hash seeds, predecessor regressions, the full suite, package build and isolated-wheel import.

## Evidence state

Prepared tests, source review and LLM analysis are not hard evidence. GitHub Actions issue #67 still prevents jobs from reaching checkout or Step 1, including explicit reruns on the parent packet. This packet remains draft-only until exact-head execution exists.

No change targets `main` or `experimental`. No merge, automatic promotion, approval, issue closure or Gate transition is authorized.
