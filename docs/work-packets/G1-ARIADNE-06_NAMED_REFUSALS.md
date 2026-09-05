# G1-ARIADNE-06 — Two refusals name their cause and the remedy

Packet ID: G1-ARIADNE-06

Artifact role: primary

Classification: `ALIGNED`

Active gate: Gate 1

Owner: repository owner

Base revision: b59b2628ad6ed85a8b5e729a12c58512543e2e73

Working-tree context: isolated worktree `.claude/worktrees/stage3-failed-receipt`, branch `loop/stage3-failed-receipt`, stacked on G1-SELF-00 (commit 6a96a577)

Dependencies: `G1-SELF-00_SELF_RENOVATION_REHEARSAL`, `G1-ARIADNE-05_WORKING_TREE_BASE_BINDING`

Stage: 6 of the owner-directed 2026-09-05 loop.

## Primary acceptance claim

The two refusals measured during the self-Renovation rehearsal stay fail-closed and unchanged in behaviour, but their messages name the cause and the operator's remedy: a linked git worktree as subject is a deliberately unsupported layout (clone the repository or use its common checkout), and a spine database without its source-tree CAS names the repository-local spine versus control-root CAS split. No gate, contract, or receipt changes.

## Reproduced negative baseline (measured 2026-09-05)

- `self-renovation-01` against a linked worktree: `repository HEAD is unavailable or unsafe: Git metadata directory must be a real directory`. True, but it neither says "worktree" nor what to do.
- `self-renovation-02` against the main checkout with an override control root: `partial persisted Campaign state is unsafe`. True, but the operator cannot tell which half is missing or why.
- Momus rejected making the HEAD verifier follow the gitdir pointer (`tests/test_git_is_a_process_launcher.py:82` measured the pointer-rewrite attack; `tests/gates/test_repository_head_revision.py::test_worktree_gitfile_is_not_misrepresented_as_verified` pins the refusal on purpose; `RepositoryHeadRevisionReceipt.from_dict` requires the exact key set, so a receipt field would invalidate every retained receipt). The gate module is untouched here.
- Two new tests before the change: 2 failed.

## Scope

In scope: `daedalus/ariadne/campaign.py::_verify_head` (facade message only, plus `_is_gitdir_pointer_file`), `daedalus/kernel/campaigns.py::lookup_campaign_read_only` (message only), two tests. Out of scope: any change to `daedalus/gates/repository/head_revision.py` or its pinned messages, any support for worktree subjects, any change to when a refusal happens.

## Contracts and behavior

- `_verify_head`: on `RepositoryHeadRevisionShapeError`, if `.git` is a regular file whose first bytes are `gitdir:`, the `AriadneRequestError` message keeps the gate text and appends: "the subject is a linked git worktree (.git is a gitdir pointer file), a deliberately unsupported subject layout: clone the repository or use its common checkout". The pointer is never read beyond its first seven bytes and never followed.
- `lookup_campaign_read_only`: the `CampaignLifecycleError` still starts with `partial persisted Campaign state is unsafe`, followed by the spine path, the missing CAS path, and the sentence explaining the repository-local spine versus control-root CAS split and the `DAEDALUS_KILLSWITCH` override that produces it.
- Both refusal points, classes and timings are unchanged: before any campaign state in the first case, after the outer lease in the second (that ordering is the kernel's; not changed here).

## Acceptance matrix

| Check | Result (2026-09-05, worktree) |
| --- | --- |
| new tests before the change | 2 failed |
| new tests + pre-read refusal tests + HEAD race test after the change | 8 passed |
| stage suites (`test_ariadne_campaign_v0.py`, `test_http_ariadne.py`, `test_kernel_contracts_have_producers.py`, `tests/gates/test_repository_head_revision.py`, `tests/test_git_is_a_process_launcher.py`) | 113 passed, 2 skipped (symlink cases on Windows), 0 failed (94.2 s) |

## Migration and rollback

Message-only; rollback restores the two strings and drops the helper and tests. Retained evidence is unaffected.

## Evidence, expected failures, and review

Codex review requested as a free room turn together with stage 5. The gate test that pins `must be a real directory` stays green by construction (the facade appends, the gate text remains).

Iron Plan: **ALIGNED**

Iron Gate: **1**

Automatic merge/promotion: **forbidden**
