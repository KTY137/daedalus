# Owner decisions 2026-09-06 — one sheet, one answer round

Source: `docs/superpowers/plans/2026-09-06-daedalus-forward-plan.md`, Task A4.
Owner instruction 2026-09-06 08:41: „mach weiter mach wie du meinst nimm die most
advanced general option“. Session 5856b0a1 read that as: apply the recommended
default of every **reversible** row and keep the constitutional or irreversible
rows open. Every applied default is listed here so the owner can reverse it with
one line. Nothing here edits the plan, the amendment chain, the ledger or evidence.

Iron Plan: ALIGNED (docs-only). Iron Gate: 1.

| # | Decision | Recommendation | Status 2026-09-06 08:50 |
| --- | --- | --- | --- |
| 1 | Accept Amendment 013 (hardware targets, self-Renovation leakage rule) as drafted in `docs/AMENDMENT_PROPOSAL_013_HARDWARE_TARGETS_AND_SELF_RENOVATION.md`? | Yes, exactly as drafted; without it D3, F1, F2 stay EXPERIMENT without a product path | **OPEN — owner only.** Plan §16 requires explicit approval of the exact diff plus `DAEDALUS_IRON_PLAN_AMENDMENT=<sha256>`; a general „mach wie du meinst“ is not that approval |
| 2 | Six GLB scenes (7,777,244 bytes) are owner-confirmed (G1-UI-15). Carrier form: committed bytes, or build step / release asset from the `.blend` sources? | Build step / release asset from the next release on; until then committed bytes with `*.glb binary` in `.gitattributes` and the manifest digest checked against the byte-pin census | **Default applied:** committed bytes + `*.glb binary`. Executed by the UI lane that owns `apps/web`, not by this session |
| 3 | `tools/package_desktop_local.ps1`: register as a maintainer door (registry row + test that parses the stage list) or remove? | Register; strike „creates no runtime entrypoint“ from `docs/LOCAL_DESKTOP_PACKAGE.md` | **Default applied:** register. Executed by the packaging lane that owns the file |
| 4 | PR #313 (Gardener) and #314 (Tensor-GPU): continue, rebase onto A3, or close? | #313 rebase after A3 and take over its five Twin pins (already pinned on this branch); #314 stays an EXPERIMENT draft | **Default applied:** rebase #313 after A3; #314 untouched |
| 5 | Remove the lane worktrees under `.claude/worktrees/lane*` after A3? | Yes; keep the `loop/lane*` branches | **Default applied:** after A3, worktrees removed, branches kept |
| 6 | Delete the 125 archived remote branches (kit `docs/recovery/cleanup_2026-08-23/README.md`)? | Yes | **OPEN — owner only.** Irreversible, external to this tree; the harness refused the mass deletion on 2026-08-23 for the same reason |
| 7 | Second Renovation subject for B4/E3: which foreign repository (MIT/BSD/Apache, < 5k LOC, has py + md + csv/json-schema)? | Candidate 1 of the three named in the B4 brief after a license check | **Default applied:** candidate 1; the B4 brief records license text digest, revision and temporal cutoff before any use |
| 8 | Orphaned budget-ledger reservation `688f434b…` (USD 3.00 worst-case, dead pid, killed council run 2026-09-05): owner releases it, or a registered reap door closes dead-pid reservations after a grace period? | Reap door as its own packet (effect-registry row, repeatable, never a hand edit of `runs/budget/ledger.json`) | **OPEN.** The reservation stays open until the reap-door packet lands or the owner releases it; the ledger is never edited by hand |
| 9 | Widen `docrefs.DOC_GLOBS` to docstrings under `daedalus/` (SELF-01 backlog; a new autonomous edit surface for D3)? | Yes, as a gate subject only, never as a write right | **Default applied: no** (the conservative default; reopen with D3) |
| 10 | May the owner choose `codex_cli` (or another remote vendor) as the **computer planner** via `planner_provider` + `allow_remote_context`? This is an **egress decision**: observation text from `browser.read` (later `file.read`, `document.read`, OCR) leaves the host. Measured: measure-09 reached `finish` this way (59.7 s, 4 calls); the local 7B never did (0/10, G1-IKARUS-34); n=1, four-way confounded | Allow only with (a) a visible remote-context warning in configuration and cockpit **before the first mission**, (b) a pinned test that every observation passes `secret_floor_rule` before entering the remote prompt, explicitly on the Codex path, (c) no silent default switch; widening = transient §4.1 confirmation. A ~9 GB CPU-only local model only after a tokens/s measurement | **Default applied: allow under (a)(b)(c).** The Codex flat-rate and the 2026-09-05 cost authorization already cover the spend; the egress warning line already exists in mission reports (G1-IKARUS-33). C2 (G1-IKARUS-36) runs both arms; nothing switches silently |
| 11 | Should the desktop app own a File-Bridge watcher so schedules, queue and series run without a terminal? Today autonomy runs only while `python -m daedalus.file_bridge watch --repo-root <folder>` runs for exactly that folder; v0.1.6 deliberately left it out (G1-IKARUS-20); no watcher ticks on this box (G1-IKARUS-35) | Yes, as its own effectful packet G1-IKARUS-41 (registry row, kill-switch binding, visible watcher status in the cockpit, heartbeat bound to the authority root), after C8 | **Default applied: yes, G1-IKARUS-41 after C8.** Until then the chat keeps saying honestly that no watcher runs |

## How to reverse

Reply with the row number and the new answer. Rows 1, 6 and 8 need a positive
owner answer before anything moves; every other row moves on its default today
and is undone by a revert of the packet that applied it.

## Owner answers, 2026-09-06 08:48 (Kaya, in the review session, verbatim)

Context: at 08:42 the owner wrote in the review session "mach weiter mach wie du
meinst nimm die most advanced general option". The review session did not read
that sentence as a blanket answer; it put the four owner-only rows to the owner
as explicit questions with the recommendation as option 1. The owner chose:

| # | Question put | Owner answer (verbatim option label) |
| --- | --- | --- |
| 1 | Amendment 013 exactly as drafted? (§16 needs explicit approval of the record) | "Ja, exakt wie entworfen (Recommended)" |
| 10 | Codex (remote vendor) as computer planner, under the three conditions (visible warning line before the first mission, secret floor on every prompt, no silent switch)? | "Ja, mit den drei Bedingungen (Recommended)" |
| 11 | Desktop app owns a File-Bridge watcher, as its own packet G1-IKARUS-41? | "Ja, als eigenes Packet G1-IKARUS-41 (Recommended)" |
| 6 | Delete the 125 archived remote branches (irreversible, external)? | "Ja, löschen (Recommended)" |

Rows 2, 3, 4, 5, 7, 8 and 9 stay on the recommendation/default recorded above;
the owner's 08:42 sentence supports the recommendation where the row is an
implementation choice (row 8: reap door, not a hand edit).

What this does NOT do: row 1 is the owner's approval of the exact draft, it is
not the amendment itself. Appending the record to
`docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`, bumping the revision and
updating the plan is an owner-tagged §16 commit that names this approval as its
reference; nothing in the tree changes until that commit exists.

Status 2026-09-06 09:25: the amendment is PREPARED in the working tree and
verified (plan at revision 13 / version 2.4.0, digest
`04e8cbf9441134e22b97fe1cb5e7ebcbcfedac64cda2f3e4e5086d82bb628639`; chain record
sequence 12, record `300d8a6c…`, previous `6d1c0d6f…`, all 12 links re-verified;
`tools/index_work_packets.py` and both schema copies pinned; index re-rendered,
`tests/contracts/test_work_packet_index.py` 22 passed). The review session's
harness refused the `git commit`; the commit is the owner's to make. File set:
`docs/IKARUS_ARIADNE_MASTER_PLAN.md`,
`docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`,
`docs/AMENDMENT_PROPOSAL_013_HARDWARE_TARGETS_AND_SELF_RENOVATION.md`,
`tools/index_work_packets.py`, `configs/schemas/work-packet-index-v1.schema.json`,
`daedalus/resources/schemas/work-packet-index-v1.schema.json`,
`docs/work-packets/index.json`, this file. Nothing else belongs in that commit. Row 6 turned
out to need no action: MEASURED 2026-09-06 08:53 from the main checkout after
`git fetch --prune origin`, all 125 branches in
`docs/recovery/cleanup_2026-08-23/remote_branches_to_delete.txt` are already
absent on origin (0 of 125 present; origin holds 19 refs: `main`, the two PR
branches, and 16 newer lanes/experiments outside the kit's list). Nothing was
deleted by this session; the kit's push was never run here. Row 6 is closed as
"already done upstream, date unknown". Row 10 activates only when G1-IKARUS-43 lands with its three pinned
conditions; until then the planner stays local.
