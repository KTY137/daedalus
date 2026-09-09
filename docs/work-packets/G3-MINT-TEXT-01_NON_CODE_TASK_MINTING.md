# G3-MINT-TEXT-01 — mint data- and knowledge-plane tasks from real repository history

Packet ID: `G3-MINT-TEXT-01`
Artifact role: `primary`
Status: `built; A6 FAILED at 31 of a required 60; primary claim holds; not promoted`
Active gate: `1`
Classification: `ALIGNED`
Owner: `repository owner`
Base revision: `d2d4aa29585604b563fe6a4fb91d099b9cc4c63b`
Dependencies: `G3-BASE-01`
Master-plan authority: `Revision 13`
Promotion: not requested; automatic merge, promotion, and Gate transition are
forbidden. This packet supplies corpus, not a verdict, and opens no gate.

## Primary acceptance claim

**Gate 3's cross-plane comparison stops being confounded**, because its
data- and knowledge-plane tasks come from the same repository as its code
tasks instead of from a six-file fixture.

## Scope

In scope: `daedalus/eval/mint.py` (a third provenance path), its tests, and
the mint store.

Forbidden paths: `daedalus/spine/**`, `daedalus/kernel/**`, the plan, the
amendment chain, `AGENTS.md`, and — critically —
`mint.py`'s existing `independent_diff` path, whose docstring says a
contributor wanting richer labels "needs a THIRD provenance value, not a quiet
edit to this one."

## Contracts and behavior

**New provenance value: `independent_text_diff`.** Distinct from
`independent_diff` so no consumer can confuse a heading label with a symbol
label, and so the existing path's independence argument is untouched.

**Scope boundary — reused, not invented.** A changed file is eligible only if
no path component is in `structcore.index._IGNORE_DIRS` or dot-prefixed, and
it is not a generated artifact (`docs/work-packets/index.json`) nor under
`fixtures/` or `examples/`. The last exclusion is the point of the packet: the
project's own text, not a toy corpus.

**Labels are byte-diff derived and never transitive.** Knowledge labels are
Markdown headings present after and absent before. Data labels are top-level
JSON keys present after and absent before. Nothing is expanded through any
graph — the same prohibition the existing path carries.

**The cross-file rule is preserved.** `must_include` never contains a label
from the file chosen as `target`. This is what costs most of the yield and it
is kept anyway: a same-file label is recalled by construction.

**Independence is stronger here than for code, and that must not be
overstated.** The slicer does not walk documentation at all, so a doc label
cannot be reachable through the import graph. That removes the circularity
`independent_diff` was built against; it does **not** make doc labels
independent of the *commit message*, which is the query. That residual is
inherited from the existing corpus and is not fixed by this packet.

**Tier and confirmation unchanged.** Minted tasks land `tier: "quarantine"`
with `confirmations: 0` and are barred from any go/no-go number until
`confirm_task` has run `MINT_CONFIRM_THRESHOLD` (3) times.

## Acceptance matrix

| # | criterion | how it is checked |
| --- | --- | --- |
| A1 | the existing `independent_diff` path is byte-unchanged | `git diff` on its function bodies; existing mint tests green |
| A2 | minted tasks carry `label_provenance: "independent_text_diff"` and `tier: "quarantine"` | new tests |
| A3 | a label from the target file is never emitted | new test, both planes |
| A4 | out-of-scope files are recorded in `skipped_out_of_scope`, never silently dropped | new test with a `dist/` and a `fixtures/` path |
| A5 | `classify_task_plane` assigns the minted tasks to `data`/`knowledge` | new test through the real classifier |
| A6 | yield on this repository is **≥ 60** tasks over 400 first-parent commits | **FAILED — 31 measured (16 knowledge, 15 data).** The threshold is not moved. |
| A7 | every minted target exists in the repository root, none under `fixtures/`/`examples/` | assertion over the built set |
| A8 | the secret floor and junk-label filters apply to text labels too | new tests |

## Migration and rollback

No migration: minted tasks are additive and land in quarantine, so
`filter_primary_tasks` excludes them from any primary-tier number until
confirmed. A tree that never runs the new mint sees `all_tasks()` unchanged.

Rollback is `git revert` plus deleting the mint-store entries the run wrote;
nothing else persists, and no existing task, tier or provenance value changes.

## Evidence, expected failures and review

**Feasibility, measured before building** `[MEASURED 2026-09-09]`, 400
first-parent commits on this repository:

| stage | knowledge | data |
| --- | ---: | ---: |
| commits yielding new headings / keys | 74 | 56 |
| surviving the scope boundary | 73 | 56 |
| **surviving the cross-file rule (≥2 in-scope files)** | **40** | **45** |

Only one candidate was lost to scope (a `.quarantine/` path). The cross-file
rule is what costs the yield: **114 of 400 commits change exactly one
in-scope knowledge file** and can never produce a cross-file task.

**Expected yield ≈ 85 tasks**, against the **4** non-code tasks that exist
today — all from the repository the 27 code tasks come from.

**Expected failure modes.**

1. Heading text is not a stable label: a renamed section reads as one deletion
   plus one addition, so a doc reorganisation mints noise. Mitigation is the
   quarantine tier and the confirmation threshold, not a cleverer differ.
2. JSON top-level keys are a thin signal — mean 1.1 new keys per qualifying
   commit. Data tasks may be dominated by single-label sets, which is weak but
   honest; a nested-key walk would be the wrong fix because it re-introduces
   the transitivity this module forbids.
3. `docs/` in this repository is unusually large and unusually
   machine-written. Yield here is **not** evidence of yield elsewhere, and this
   packet claims nothing about other repositories.

**OUTCOME [MEASURED 2026-09-09, after the build].**

| # | result |
| --- | --- |
| A1 existing `independent_diff` untouched | **pass** — appended only; its tests green |
| A2 provenance and quarantine tier | **pass** |
| A3 no label from the target file | **pass** |
| A4 out-of-scope recorded, not dropped | **pass** |
| A5 `classify_task_plane` agrees | **pass** — both planes, through the real classifier |
| **A6 yield ≥ 60** | **FAIL — 31** |
| A7 targets exist, none from fixtures | **pass**, after the fix A7 itself forced |
| A8 secret floor applies to text | **pass** |

**A6 failed and the threshold stays where it was frozen.** The 60 came from a
feasibility probe that counted commits changing ≥2 in-scope files of a type
(85). The implementation requires more than that: two files each carrying a
*new* label, and a non-empty cross-file set after subtracting the anchor's own
labels. Those conditions cost roughly half. **My estimate measured a looser
condition than the code enforces**, which is exactly the error a pre-registered
threshold exists to expose.

**A7 earned its place.** It caught a target that no longer exists — a
content-addressed store locator under `runs/`, machine-written run output that
should never have been in scope. The symptom was a deleted file; the cause was
a scope boundary that excluded `dist/` but not execution output.
`_GENERATED_TEXT_ROOTS` now excludes `runs/`, which cost 4 further tasks
(35 → 31) and was worth it.

**Does the primary claim survive a failed A6?** Yes, and the distinction
matters. The claim is that Gate 3's non-code tasks stop coming from a
different corpus than its code tasks. That is about **source**, not count: 31
tasks from the repository replace a dependence on 4 from a six-file fixture.
The confound is removed. What 31 does not settle is **power** — that was
always a separate obligation and it remains open.

**Review questions.**

1. Is a Markdown heading the right label unit, or should it be a section body
   digest? Headings are what a reader searches for; bodies are what a
   retriever returns.
2. Does adding ~85 non-code tasks against 27 code tasks skew the corpus the
   other way, and does the tier gate handle that or merely postpone it?
3. The four `artifact_parsed` fixture tasks stay in the corpus. Should they be
   retired once repository-derived ones exist, or retained as a declared
   second population?
