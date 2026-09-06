# G1-OPS-06 — Integrating the 2026-09-05 loop branch onto the integration branch

Packet ID: G1-OPS-06

Artifact role: primary

Active gate: 1

Classification: ALIGNED

Owner: repository owner

Base revision: 5a13dbf9

Dependencies: A2 commits 27d27a7b..5a13dbf9; loop/stage3-failed-receipt 04fde78b

Working-tree context: primary checkout, branch `codex/ikarus-computer-assistant-20260905`,
shared with live peer sessions (apps/web, src-tauri, the Amendment-013 file set,
`tools/index_work_packets.py`, both work-packet-index schema copies). No peer path
was staged, reverted or stashed at any point.

## Scope

In scope: merging the 2026-09-05 owner loop (stages 3–15b) and its ten lane
packets into `codex/ikarus-computer-assistant-20260905`; resolving the merge
conflicts; verifying that both sides' contracts and test files survive; the
Work Packet document and the post-merge full-suite receipt.

Integrated packets: `G1-ARIADNE-04` (failed receipt on first call), `G1-ARIADNE-05`
(working-tree base binding), `G1-ARIADNE-06` (named refusals), `G1-ARIADNE-07`
(council hardening), `G1-ARIADNE-08` (git object reader), `G1-ARIADNE-09` (CLI
exit-code contract), `G1-KERNEL-02` (cancellable provider calls), `G1-IKARUS-26`
(computer loop measured live), `G1-IKARUS-29` (loop progress and pre-effect
timeout), `G1-IKARUS-30` (desktop vision live), `G1-IKARUS-31` (planner native
route and cancel), `G1-SELF-00`/`G1-SELF-01` (self-Renovation rehearsals),
`G1-HW-01` (KiCad read-only inspection), `G1-EDA-HOST-STATUS-01`/`-02` (chip
design on this host, emitted Vivado/Vitis Tcl), `G1-GENESIS-REHEARSAL-01`,
`G1-TESTS-01` (shell voice test isolation).

Forbidden and untouched: `docs/IKARUS_ARIADNE_MASTER_PLAN.md`, its amendment
chain, `docs/AMENDMENT_PROPOSAL_013_HARDWARE_TARGETS_AND_SELF_RENOVATION.md`,
`AGENTS.md`, `CLAUDE.md`, `.agentenv/`, `tools/index_work_packets.py`, both
`work-packet-index-v1.schema.json` copies, `apps/web/**`, `apps/web/src-tauri/**`,
`tools/package_desktop_local.ps1`. No promotion, no push, no PR, no worktree
removal.

## Primary acceptance claim

The 41 loop commits are on the integration branch as a non-fast-forward merge
that preserves every packet commit, both sides of every contested contract keep
their behaviour and their tests, and no peer-lane file was staged, reverted or
lost.

## The two-release-commit finding

The v0.1.6 release commit exists **twice** as two sibling commits off the same
parent `61cd1f3e`, with the same subject and different trees:

| | commit | tree | time | carried by |
| --- | --- | --- | --- | --- |
| ours | `585b7ea4` | `c2360ce9` | 14:51 | integration branch, release branches, lanes 2/5/6 |
| theirs | `b59b2628` | `f3772e76` | 13:54 | `loop/stage3-failed-receipt`, lanes 1/3/4/7/8/9/10/11 |

The two trees differ in exactly ten files (+43/−119): `.gitattributes`,
`daedalus/council/vendors.py`, `docs/work-packets/G1-ARIADNE-03_WINDOWS_EVALUATOR_INTERPRETER.md`,
`experiments/forest_v2/README.md`, `experiments/forest_v2/s02_types/test_external_corpora.py`,
`experiments/forest_v2/s07_bm25/test_bm25_index.py`, `tests/kernel/test_source_tree_store_review.py`,
`tests/test_council_vendors.py`, `tests/test_ikarus_autonomy_review.py`,
`tests/test_write_surface_coverage.py`.

Because that release commit is a squash of 456 files / +80 322 that *first
introduced* every Ikarus-computer, Ariadne-campaign and council-loop module,
merging `loop/stage3-failed-receipt` directly resolved against the pre-release
base `61cd1f3e`, where none of those paths exist. Measured with
`git merge-tree --write-tree`: **31 conflicted files, roughly 15 of them
`add/add` with no ancestor text**, i.e. whole-file hand reconciliation of the
fence, the computer policy, the Ariadne campaign kernel and five test modules.

The remedy was to restore the true base. In a scratch worktree
(`.claude/worktrees/stage3-reparent`) the 41 loop commits were replayed with
`git rebase --onto 585b7ea4 b59b2628` onto branch **`loop/stage3-on-585b7ea4`**
(`79475cb5`), the replayed twin. The rebase finished with **zero conflicts**.
`loop/stage3-failed-receipt` (`04fde78b`) was **not rewritten** and remains the
retained history; the only tree difference between the two tips is the ten-file
release delta above, in the direction of adopting `585b7ea4`'s content.

No replayed commit touches any of the ten delta files except `.gitattributes`
(three commits, merged as a union). In particular **no loop commit touches
`daedalus/council/` at all** — "G1-ARIADNE-07 council hardening" names the
council *reviewing* the Ariadne campaign and edits
`daedalus/ariadne/campaign.py`, not the council package. The A2 work in
`daedalus/council/vendors.py` and `tests/test_council_vendors.py` therefore
survives untouched rather than needing a both-sides reconciliation.

With the corrected base the conflict set collapsed from 31 files to **one**.

## Acceptance matrix

| Check | Result |
| --- | --- |
| rebase `--onto 585b7ea4 b59b2628`, 41 commits | 0 conflicts; `loop/stage3-on-585b7ea4` = `79475cb5` |
| `loop/stage3-failed-receipt` unchanged | `04fde78b`, not rewritten |
| merge base after re-parent | `585b7ea4` (was `61cd1f3e`) |
| conflict set after re-parent | 1 file (`tests/runtimes/test_computer_service.py`), was 31 |
| conflict resolution keeps both sides | 26 top-level defs, 0 duplicates, 21 tests |
| `.gitattributes` union | 456 ours + 8 theirs = 464; 0 lines lost from either side |
| staged set ⊆ loop-branch change set | 172 staged, 0 paths outside |
| peer files staged | 0 (33 peer paths unstaged throughout) |
| computer + loop suites | 176 passed |
| council + `tests/runtimes` + `tests/kernel` | 2589 passed, 57 skipped, 22 xfailed |
| ariadne + ignition bundle + byte pins | see Evidence |
| registry / census | see Evidence |
| post-merge full suite | see Evidence |

## Conflict resolution

`tests/runtimes/test_computer_service.py` — **both sides kept**, markers removed,
no other edit. Ours contributes `_record_terminal_outcomes`, the Cerberus F1/F2/F3
tests (post-dispatch refusal never reported as no-effect, replacement-fence claim
and enforcement sharing one source, failure records persisting adapter recovery
paths), the handle-anchored scope assertion and the Odysseus O-1 call-time
release-constant test. Theirs contributes
`test_release_locked_tools_are_reported_unavailable_not_silently_dropped`
(G1-IKARUS-26, stage 13). The two blocks define disjoint names.

Auto-merged, verified by inspection rather than assumed:

- `daedalus/runtimes/computer.py` — ours keeps the call-time `_release_policy.*`
  reads (lines 75/79/86/195/214), `dispatched`, `provably_no_effect`,
  `_store_failure_record` and `filesystem_scope_kind`; theirs adds
  `_release_unavailable_reason` and the `unavailable[tool] = reason` reporting in
  `capabilities()`, plus the `limit_policy.enforces("wall_time")` pre-effect check
  from G1-IKARUS-29/31.
- `daedalus/council/vendors.py`, `daedalus/council/session.py` — clean; theirs
  makes no council edits, so A2's G1-COUNCIL-02 stands.
- `docs/FOURFOLD_V2_EXECUTION_PLAN.md`, `docs/IKARUS_COMPUTER.md` — clean merge;
  ours has no edits in the loop status section.
- `docs/work-packets/index.json` — taken from the loop branch verbatim.

## Deferred: the work-packet index re-render

`docs/work-packets/index.json` is **not** re-rendered in this packet. Ruling of
the Amendment-013 lane (`daedalus-b4`, 2026-09-06): the index render must run
only **after the owner's Amendment-013 commit**, otherwise the index would report
master plan revision 13 before the plan itself does. `tools/index_work_packets.py`
and both schema copies are that lane's uncommitted work and were left untouched.

Consequence, recorded rather than papered over: adding this document makes the
index census move (`tracked_files` 348 → 349 and the packet-id totals), so
`tests/contracts/test_work_packet_index.py` will need its moving-census values
re-measured in the same commit that re-renders the index. That test is already
red in this working tree for a peer reason independent of this merge — measured
with both the committed and the peer's working-tree copy of the tool:

```text
IndexError: Master Plan authority drifted from Revision 12:
04e8cbf9441134e22b97fe1cb5e7ebcbcfedac64cda2f3e4e5086d82bb628639
```

i.e. the checker sees the amendment lane's uncommitted revision-13 plan. Nothing
in this merge can make it green, and nothing in this merge made it red.

## Evidence

Interpreter `.venv/Scripts/python.exe -m pytest -q --color=no -p no:cacheprovider`,
Windows 11, CPython 3.13.14, host under concurrent load (counts are evidence,
timings are not).

EVIDENCE_PLACEHOLDER

### Retained observations

- The scratch worktree `.claude/worktrees/stage3-reparent` shows 13 modified
  files under `docs/evidence/G1-IKARUS-30_DESKTOP_VISION_LIVE/`. This is a pure
  `core.autocrlf` checkout artefact of the rebase, not content: `git ls-files
  --eol` reports `i/lf w/crlf attr/-text` for every one, and the diff is
  2938 insertions against 2938 deletions. The primary checkout's copies are
  `i/lf w/lf attr/-text`, and the committed blobs are LF. Nothing was committed
  in that worktree.
- `.gitattributes` gains two directory-scoped evidence pins from the loop branch
  (`docs/evidence/G1-IKARUS-26_COMPUTER_LOOP_LIVE/** -text` and
  `docs/evidence/G1-IKARUS-30_DESKTOP_VISION_LIVE/** -text`). They pin evidence
  directories whose `MANIFEST.json` digests are over committed LF bytes; they do
  not replace any per-file Gate-1 bundle pin.
- No worktree was removed; the ten lane branches and their worktrees are intact.
