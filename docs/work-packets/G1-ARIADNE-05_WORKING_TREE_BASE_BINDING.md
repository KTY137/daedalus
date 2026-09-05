# G1-ARIADNE-05 — The campaign base is a working-tree base, and the receipt says so

Packet ID: G1-ARIADNE-05

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: b59b2628ad6ed85a8b5e729a12c58512543e2e73

Working-tree context: isolated worktree `.claude/worktrees/stage3-failed-receipt`, branch `loop/stage3-failed-receipt`, stacked on G1-ARIADNE-04 (commit 9d37ff0d)

Dependencies: `G1-ARIADNE-01_CANONICAL_CAMPAIGN_REHEARSAL`, `G1-ARIADNE-04_FAILED_RECEIPT_ON_FIRST_CALL`

Stage: 4 of the owner-directed 2026-09-05 loop.

## Primary acceptance claim

An Ariadne campaign receipt no longer implies that its base bytes are the target's content at `source_revision`. The base is declared for what it is, the working-tree file content-addressed in the source-tree CAS, through a typed binding that is a provenance input of every receipt (nominated or failed), and the base tree's origin string names the working tree. The read/verify race between the target read and the HEAD verification is closed by a double observation. Nothing is refused for being dirty, and no git binary or Git object reader is introduced.

## Reproduced negative baseline (measured 2026-09-05)

- Odysseus (G1-ARIADNE-02 review): `run_campaign` verified `source_revision` against the real HEAD but read the target from the working tree; a dirty target was bound to a commit id (`origin="ariadne.controlled-repair.scoped-base"` asserted a scoped base *of the revision*). Invariant 7 (provenance) was violated by a claim, not by the bytes: the base is content-addressed and reproducible from CAS.
- Momus (design critique before build): the target read at `campaign.py:1089` preceded the HEAD verification at `:1093`, so a commit or checkout between the two bound bytes of revision X to a receipt labelled Y with nothing detecting it.
- Options attacked and rejected with evidence (Momus): refusing on a raw byte compare against HEAD or the index lies under git line-ending filters on Windows (`.gitattributes` is live in this repository); an index-match field is not a function of the campaign identity (`operation_sha`) and would make a replayed receipt false after `git add`; a browser opt-in flag is forbidden by G1-ARIADNE-02; adding fields to the head receipt breaks its strict `to_dict()` verification; a second `EvidenceItem` breaks `len(packet.items) == 1`.
- Five new real-git tests before the change: 4 failed, 1 passed (the untracked target already ran; nothing recorded what its base was).

## Scope

In scope: `daedalus/ariadne/campaign.py` only (ordering, the binding blob, the origin string, receipt inputs), plus tests. Out of scope: any refusal of dirty targets, `git` subprocesses, a Git object reader, kernel contracts, the HTTP facade, the workbench. HEAD-content verification stays a separate packet that flips `head_content_verified` to true and must use git itself (`git --no-optional-locks diff --quiet HEAD -- <path>`), never a raw byte compare.

## Contracts and behavior

- Ordering: `_admit_target_path` (pure: shape and mandatory-ignored-root refusals, no filesystem, no `.git`) -> `_verify_head` (first observation) -> `_safe_target` (read) -> `_verify_head` again; a differing HEAD receipt is `AriadneConflictError("source_revision conflict: repository HEAD changed while the target was read")` before any campaign state exists. The first cut put the HEAD observation before the pure admission and turned five existing pre-read refusal tests red (fixtures without `.git`); the split restores refusal-before-observation for path problems, and the target-typing test now verifies HEAD the way the other unit tests do.
- Binding blob `daedalus-ariadne-base-tree-binding/1`: `{schema, campaign_id, source_revision, target_path, base_file_sha256, base_source: "working-tree", head_content_verified: false}`, stored in the source-tree CAS next to the base tree; its SHA-256 is a provenance input of the nominated receipt and of every failed receipt (`_complete_failed_campaign_receipt(base_binding_sha256=...)` at all three call sites). It is a function of the campaign identity only (no index, no timestamps), so replay serves a receipt whose binding is still true.
- Base tree origin: `ariadne.controlled-repair.working-tree-base` (was `...scoped-base`). This changes ExperimentSpec/contract digests for new campaigns only; `operation_sha` and replay-by-identity are untouched.
- Existing schema-filtered scans (`_OUTER_EFFECT_BINDING_SCHEMA`) skip the new schema; `_MAX_RECEIPT_PROVENANCE_INPUTS` has room.

## Acceptance matrix

| Check | Result (2026-09-05, worktree) |
| --- | --- |
| five real-git tests before the change (clean, dirty+untracked, index-independence, CRLF `text=auto`, HEAD moving during the read) | 4 failed, 1 passed |
| same five after the change | 5 passed (30.9 s) |
| first full stage run: the HEAD observation preceded the pure path admission | 5 failed (existing pre-read refusal tests), 138 passed |
| after the admission split: the five refusal tests + the five new + the stage-3 pair | 11 passed (19.9 s) |
| stage suites (campaign, HTTP Ariadne, producer census, CLI boundary, registry new doors) after the split | 143 passed (94.8 s), 0 failed |

## Migration and rollback

Rollback restores the single-observation order, the `scoped-base` origin and drops the binding from the receipt inputs. Retained receipts are unaffected; new receipts carry one more provenance input.

## Evidence, expected failures, and review

Momus's critique is the design record (rejected options with file:line). Codex review requested as a free room turn; Codex's answer to the room question of 14:16 (turn 80) is pending. Not merged, not promoted.

Iron Plan: **ALIGNED**

Iron Gate: **1**

Automatic merge/promotion: **forbidden**
