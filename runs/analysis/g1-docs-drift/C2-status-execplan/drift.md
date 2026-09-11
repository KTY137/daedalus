# Docs drift audit — docs/STATUS.md + docs/FOURFOLD_V2_EXECUTION_PLAN.md

Scope: read-only. Repo `C:/Users/Administrator/daedalus`, measured at HEAD
`d17ea2fc` on branch `main` (the prompt named `54f09753`; `git rev-parse HEAD`
returned `d17ea2fc` — recorded as measured, not silently substituted).
No tracked file was modified. No test suite was run. Only
`.venv/Scripts/python.exe` was used for Python invocations plus one deliberate
bare-`python` failure demonstration.

Cluster: `docs/STATUS.md`, `docs/FOURFOLD_V2_EXECUTION_PLAN.md`.
Secondary/report-only: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` §4 invariant 8
(explicitly assigned for independent verification).

---

## CONFIRMED

### [CONFIRMED] STATUS.md hop-table item 3 names the wrong plan revision and the wrong active gate
- **File:line**: `docs/STATUS.md:42-44`, inside the "Five hops, and what each one
  is for" navigation list: *"`docs/IKARUS_ARIADNE_MASTER_PLAN.md` — the sole
  semantic authority: invariants, gates, priors, delivery order. Revision 7,
  version 1.2.3, active gate **Gate 0 — Canonical Kernel** [MEASURED: file
  header lines 4-9]."*
- **Claim**: A reader following the page's own "where to look" list would
  believe the master plan is Revision 7 / v1.2.3 and that Gate 0 is still the
  active gate.
- **Measured reality**: The plan at HEAD is Revision 11, version 2.2.0, active
  gate **Gate 1 — Renovation and owner-directed Genesis** (Gate 0 was closed,
  scoped, by amendment record 8 on 2026-08-26). This is not just stale
  relative to the tree — it contradicts the *same file's own header three
  lines above it* (`docs/STATUS.md:7-9`): "the sole semantic authority is
  Master Plan Revision 11 ... the active delivery gate is Gate 1".
- **Evidence command**: `git show HEAD:docs/IKARUS_ARIADNE_MASTER_PLAN.md | head -9`
  → `Revision: 11` / `Version: 2.2.0` / `Active delivery gate: Gate 1 —
  Renovation and owner-directed Genesis`. Cross-checked against
  `git show HEAD:docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`, record 8
  (`result_revision: 8`, `summary: "Scoped Gate-0 closure ... active delivery
  gate moves to Gate 1"`) and record 10 (`result_revision: 10`, latest).
- **Mitigating context**: the 2026-08-31 header rewrite (`git show 72f7e326 --
  docs/STATUS.md`) added a blanket disclaimer above this list: "The dated
  measurements and Gate-0 narrative below remain historical evidence from
  2026-08-25 ... they were not remeasured or rewritten." The disclosure is
  real but generic and sits above a five-item navigational list; item 3's own
  `[MEASURED: file header lines 4-9]` citation reads as a live, checkable fact
  about a file whose header a reader can trivially open and see disagrees.
- **Misleadingness**: HIGH. This is literally the sentence whose job is to
  tell a new reader "read the plan, here is its revision and active gate,"
  and it names both wrong.

### [CONFIRMED] STATUS.md amendment-chain record count is stale
- **File:line**: `docs/STATUS.md:45-46`: *"Its amendment chain is
  `docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl`, 7 records, sequence
  1..7, every `previous_record_sha256` matching its predecessor [MEASURED:
  parsed 2026-08-25]."*
- **Claim**: The amendment chain has 7 records.
- **Measured reality**: The chain has **10** records, sequence 1..10, at
  HEAD.
- **Evidence command**: `git show HEAD:docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl | wc -l`
  → `10`. Records 8, 9 and 10 (`result_revision` 8/9/10) postdate the quoted
  2026-08-25 measurement.
- **Misleadingness**: MEDIUM. Carries its own `[MEASURED 2026-08-25]` stamp
  and sits under the same header disclaimer as the previous finding, so a
  careful reader has a chance to notice it is dated — but the sentence itself
  makes no hedge ("has 7 records," not "had 7 records as of 2026-08-25").

### [CONFIRMED] FOURFOLD_V2_EXECUTION_PLAN.md's own Gate 0 section says "Gate 0 remains open," unmarked, after Gate 0 closed
- **File:line**: `docs/FOURFOLD_V2_EXECUTION_PLAN.md:67-70`, section heading
  `## Gate 0 — Canonical Kernel`: *"Gate 0 remains open. A revision-bound
  release report may set `closed=true` only when every machine criterion is
  satisfied at one exact head, including: ..."*
- **Claim**: A reader would believe Gate 0 is presently open and blocking,
  with a list of still-required criteria.
- **Measured reality**: Gate 0 was closed as a **scoped owner decision** on
  2026-08-26 (amendment record 8, `docs/GATE0_CLOSURE_DECISION_20260826.md`,
  committed at `657c8af5`, titled "Gate 0 sealed by scoped owner decision;
  Gate 1 is active"). The active gate has been Gate 1 since that date.
- **Evidence command**: `git log -1 --format="%h %ad %s" --date=short --
  docs/GATE0_CLOSURE_DECISION_20260826.md` → `657c8af5 2026-08-26 amend(gate-
  closure): Gate 0 sealed by scoped owner decision; Gate 1 is active`. Also
  `git show HEAD:docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl` record 8.
- **Why it's not just old**: the file's own header (lines 4-6) was updated on
  2026-08-31 (commit `72f7e326`) to say `Canonical authority: ... revision 11`
  and `Active gate: Gate 1`, and the "Status" line was reworded to admit "its
  dated Gate-0 and PR-chain sections below are historical." `git show 72f7e326
  -- docs/FOURFOLD_V2_EXECUTION_PLAN.md` shows that commit touched **only**
  the four header lines — the `## Gate 0 — Canonical Kernel` section body was
  not edited and carries no inline staleness marker, unlike the later section
  at line 127 which is explicitly headed `## Current Gate-0 execution boundary
  [SUPERSEDED, retained as history]`. The maintainer marked one Gate-0 section
  as history and left the other, more prominent one, saying "remains open"
  with no marker at all.
- **Misleadingness**: HIGH for a reader who opens the "Gate 0" section
  directly (e.g. from a table of contents or search) without reading the
  preceding "Status" line's generic disclaimer — it reads as a live blocking
  gate with a checklist of exit criteria, not as history.

### [CONFIRMED] `python tools/docs_reference_check.py`, as literally quoted, does not run
- **File:line**: `docs/STATUS.md:164`, pointer table: `| whether the docs
  still point at files that exist | python tools/docs_reference_check.py |`.
- **Claim**: Running `python tools/docs_reference_check.py` produces the
  doc-reference report.
- **Measured reality**: bare `python tools/docs_reference_check.py` fails
  immediately with no report. The repo-correct invocation (per this session's
  own operating instructions, matching the project's documented Hermes-venv
  hazard) is `.venv/Scripts/python.exe tools/docs_reference_check.py`, which
  runs successfully and reports "scanned 734 of 734 tracked markdown files"
  plus 2 dead references in current pages.
- **Evidence command**:
  `python tools/docs_reference_check.py` → `ERROR: Use \`uv run python
  tools/docs_reference_check.py\` instead of \`python tools/docs_reference_check.py\``
  (hard failure, no output).
  `.venv/Scripts/python.exe tools/docs_reference_check.py` → succeeds,
  prints `scanned 734 of 734 tracked markdown files` and a 2-dead-reference
  report.
- **Misleadingness**: MEDIUM. The specific failure mode observed here is a
  session-level shim rather than something intrinsic to the repository, but
  the outcome — the literally quoted command does not run in this checked-out
  environment and a different interpreter path is required — is exactly the
  class of drift criterion 1 asks for, and matches this project's documented
  Hermes-venv hazard for bare `python`.

---

## PLAUSIBLE

### [PLAUSIBLE] STATUS.md's `docs/` tracked-file count and `.github/workflows` counts are stale
- **File:line**: `docs/STATUS.md:170`: *"`docs/` holds 683 tracked files
  [MEASURED 2026-08-25, `git ls-files docs`]."* Also `docs/STATUS.md:140-156`,
  the "94 of 98 workflows called a deleted script" / "93 workflows... pinned
  to lane branch... exactly one workflow reaches main" passage.
- **Claim**: 683 tracked files under `docs/`; 98 total workflow files, 94 of
  them broken, 93 pinned to now-deleted lane branches, exactly 1 reaching
  `main`.
- **Measured reality**: `git ls-files docs | wc -l` → **875** today (not 683).
  `git ls-files .github/workflows | wc -l` → **109** today (not 98).
  `git grep -l "iron_plan_guard" -- .github/workflows | wc -l` → **0** — the
  dead-script step really was removed, consistent with the page's own
  "Removed 2026-08-25" note, so the qualitative claim (broken step is gone)
  still holds; only the raw counts are stale.
- **Evidence command**: as above. Marked PLAUSIBLE rather than CONFIRMED-as-
  misleading because both figures carry an explicit `[MEASURED 2026-08-25]`
  stamp and sit inside the section the 2026-08-31 header explicitly disclaims
  as "historical evidence ... not remeasured." Whether the 93-pinned/1-reaches-
  main breakdown still holds for the 11 new workflow files was not
  individually re-parsed (would require YAML-parsing 109 files, which the
  page itself did as a one-time exercise).
- **Misleadingness**: LOW — self-stamped and covered by the file-level
  disclaimer.

### [PLAUSIBLE] `docs/architecture-state.json` head/module counts have moved again
- **File:line**: `docs/STATUS.md:85-118`, the "architecture snapshot cannot
  currently be reproduced" section, citing `head = 94eb3515`, live counts
  `modules 1637, islands 78, unreached 115, unknown 29, doc_drift 35,
  test_only 42, shims 8` vs. snapshot `520, 68, 101, 26, 32, 36, 7`.
- **Claim**: the committed snapshot is stamped at head `94eb3515`.
- **Measured reality**: `git show HEAD:docs/architecture-state.json | grep
  '"head"'` → `"head": "d7e88b98ea089fc76ce39c3591114e3bcb105bd1"` — a
  different value than the one quoted on the page. The live vs. snapshot
  module/island/etc. counts were **not** independently re-measured here (that
  requires running `daedalus.cli map --check`, which builds a structcore
  index over the whole tree — expensive and explicitly out of proportion for
  a docs-only audit); the `--check` flag is confirmed to be a real, parsed
  argument (`daedalus/mapping/render.py:1571`,
  `ap.add_argument("--check", action="store_true", ...)`), so the *command*
  in the doc is not itself a dead claim, only the specific numbers quoted
  from a past run of it.
- **Misleadingness**: LOW — again inside the disclaimed historical section,
  and the page already surrounds these numbers with heavy hedging ("Do not
  copy numbers out of that JSON").

---

## REPORT-ONLY / AMENDMENT-REQUIRED (secondary file: master plan)

### [CONFIRMED, REPORT-ONLY] Master Plan §4 invariant 8's kill-switch claim is contradicted by a same-day measurement
- **File:line**: `docs/IKARUS_ARIADNE_MASTER_PLAN.md:129-131`, invariant 8:
  *"Egress, write roots, secrets, authorization, containment, evidence
  boundaries and a kill switch **are always enforced at effect boundaries**,
  not entrusted to prompts."*
- **Claim**: every effect boundary in the production system enforces the kill
  switch.
- **Measured reality (independently re-derived, not copied from the task
  prompt's own "87 of 104" figure)**: `runs/analysis/g1-security-sweep/W7-
  findings.md`, a same-tree, same-day inventory, enumerates **104** registered
  effect doors under a 6-effect definition and finds **8** with a
  DIRECT/PARTIAL-real, traced kill-switch check, **1** UNCLEAR
  (`web.mutations`), and **95** with **NONE** — including `tools.guarded_call`,
  every `tools.*` CLI door, every `runs.council.*`/`runs.ab.*` door,
  `python.promote_candidates` (owner-approval gated but not kill-switch
  gated), and the `worktree.*` doors (containment-gated, not kill-switch
  gated). Its own tally line: *"roughly 8% of registered effect doors have a
  traced, real kill-switch check on their path; the remaining ~92% reach
  their effect through `begin_effect` alone, which the kill switch never
  touches."* That is 96 of 104 (92%) without a real kill-switch path — the
  same order of magnitude as, though not byte-identical to, the "87 of 104"
  figure named in this task's calibration text (possibly a different count
  definition or an earlier pass by the same lane); both numbers refute the
  same invariant-8 sentence.
- **Evidence command**: `grep -n "87\|104\|kill.switch" runs/analysis/g1-
  security-sweep/W7-findings.md` (lines 60, 217-259); specifically line 251:
  `Total: **104 doors** (6-effect definition). **8 DIRECT/PARTIAL-real** ...
  **95 NONE**`.
- **Misleadingness**: HIGH for a reader relying on invariant 8 as an
  operational guarantee. **This finding is REPORT-ONLY.** The master plan
  changes only through the amendment protocol in its own §16; no edit is
  proposed here, and none should be made outside that protocol.

---

## Not investigated further (out of proportion for this pass)

- Full YAML re-parse of all 109 `.github/workflows/*.yml` files to update the
  "93 pinned / 1 reaches main" breakdown — the qualitative claim (dead script
  step removed) was verified; the exact counts were not.
- Live re-run of `daedalus.cli map --check` to refresh the module/island
  counts — the command and its `--check` flag are confirmed real and parsed;
  its output was not reproduced here.
- `gh issue view 67` (External execution blocker, `docs/FOURFOLD_V2_EXECUTION_
  PLAN.md:145`) — `gh` is not authenticated in this session
  (`gh issue view 67` → "please run: gh auth login"). Marked
  **UNVERIFIED-BY-DESIGN**, not refuted.
