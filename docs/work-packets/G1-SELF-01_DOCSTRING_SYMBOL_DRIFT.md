# G1-SELF-01 — Self-Renovation, second target: Ariadne nominates a repair of a docstring Daedalus's own resolver calls broken

Packet ID: G1-SELF-01

Artifact role: primary

Classification: `EXPERIMENT`

Active gate: Gate 1

Owner: repository owner

Base revision: cfe8d34b8ef1438156e6fa3e6982f5a30d91696f

Working-tree context: executed from the isolated worktree branch
`loop/lane8-self-renovation` (created from `loop/stage3-failed-receipt`) against
a scratch `git clone` of the repository at the base revision, with a fresh
control root outside the repository.

Dependencies: `G1-SELF-00_SELF_RENOVATION_REHEARSAL`,
`G1-ARIADNE-01_CANONICAL_CAMPAIGN_REHEARSAL`,
`G1-ARIADNE-03_WINDOWS_EVALUATOR_INTERPRETER`,
`G1-ARIADNE-05_WORKING_TREE_BASE_BINDING`

Stage: the follow-up G1-SELF-00 asked for. Stage 5 found exactly one refuted
claim in the tree and it lived in `CLAUDE.md`, which §16 protects, so the
rehearsal could not show the loop working on ordinary, unprotected source. This
packet finds a second target that is not protected, and repeats the campaign.

**Nomination is not promotion.** Nothing here was applied, merged, promoted or
pushed. The candidate exists only as content-addressed bytes in a scratch CAS.
The owner decides whether the repair is ever made, by hand, in a separate
change. Master plan invariant 5 and AGENTS.md ("No automatic merge or
promotion") are the reason this packet ends at a receipt.

## Primary acceptance claim

The canonical Ariadne controlled-repair campaign, run unchanged through the
registered `cli.ariadne_campaign` door against a clone of Daedalus itself, can
nominate a candidate that removes a defect in Daedalus's own source which the
repository's **own resolver** independently calls broken — with three arms
under equal budgets, a subject that stays byte-identical, an independent frozen
gate that separates the repair from both controls, and no promotion.

The defect is not chosen by taste. `daedalus/spine/docrefs.py` already defines
this exact class ("a reference in the documentation to a code symbol that does
not exist") and already fixes the false-positive filter that makes it
judgeable: a reference is judged only when THE MODULE EXISTS AND THE SYMBOL
DOES NOT. This target satisfies that filter, and the gate that proves it calls
`docrefs.resolve_reference` rather than a rule invented for this packet.

## Experiment record (plan section 15)

- **Spec**: the frozen `ExperimentSpec`/`CampaignContract` of G1-ARIADNE-01 —
  three arms (no-change baseline, deliberate negative control, exact-text
  repair), one attempt per arm, metric `exact_match`, selection
  `best-passed-trial`. `experiment_spec_sha256`
  `184fc87a7f4283898d4755f83ca3c1af419f5cf50c18f5563d858aa9755965e1`;
  `campaign_contract_sha256`
  `807ca410587d37f3e9cf605d12706400256aaba285f769dcdfd41032e8701236`.
- **Scope**: one file, `daedalus/build.py`; one exact-text replacement of a
  764-byte, 13-line fragment of its module docstring — the minimal contiguous
  span covering both references to `daedalus.kairos.scheduler.Ikarus`, a class
  that `daedalus/kairos/scheduler.py` does not define. `before` occurs exactly
  once in the frozen target (the campaign refuses otherwise).
- **Budget**: `timeout_s=60` per arm, configured identically across arms
  (`configured_budget_sha256` `508b0a0c43aa025d5fa3b326466c4e582d81a0aa09fb8373e04b3a84aa3468a3`
  for all three). Realized for the whole campaign: `cost_microusd 0`,
  `input_tokens 0`, `output_tokens 0`, `wall_time_ms 1167`
  (arms 524 / 359 / 284 ms). No model, no vendor, no network.
- **Evaluator**: the frozen exact-match SHA-256 evaluator built into
  `daedalus/ariadne/campaign.py` (`EVALUATOR_SHA256`), executed under Windows
  containment with the base interpreter (G1-ARIADNE-03). The candidate never
  sees it.
- **Independent gate**: `gate_docstring_symbol_refs.py`, frozen in the evidence
  directory, applying `docrefs.resolve_reference` to the target's first-party
  Sphinx references. Read-only: `ast` only, no import of inspected code, no
  spawn, no write.
- **Expiry**: 15 minutes after the frozen campaign timestamp (Ariadne-01
  protocol). The receipt is retained past expiry as evidence, not as authority.
- **Isolation**: subject = `git clone` at the base revision under a scratch
  directory outside the repository; control root = a fresh scratch
  `DAEDALUS_KILLSWITCH` root, armed before the run. The shared checkout, its
  control root and its spine database were not touched.
- **Promotion**: forbidden. The nomination is retained evidence for the owner.

## Scope

In scope: read-only search of the tree at the base revision for a target;
executing the existing production path against a clone; retaining the receipt,
the three-arm evidence, the control-root artifacts and the full rejection
record. Docs only.

Out of scope, and not done: any edit to `daedalus/` or `tests/` in any working
tree; any application of the candidate; any merge, promotion, push or
`OwnerApproval`; any change to the master plan, its amendment chain,
`AGENTS.md`, `CLAUDE.md` or anything under `.agentenv` — the candidate does not
touch them either, and its single target path is `daedalus/build.py`.

Explicitly **not** claimed: that Daedalus "improves itself". What is measured is
that one bounded, deterministic, model-free repair of one docstring in one file
was nominated under owner control. Two docstring references is the size of the
result.

## Contracts and behavior

No contract changes. No new module, no new gate registered in the tree, no
effect-boundary row added. The campaign ran through the unchanged chain:

`cli.ariadne_campaign` door (`daedalus/ariadne/__main__.py`, `begin_effect`
before argument parsing) -> `python.ariadne_campaign` outer EffectLease ->
`python.attempt` lease per arm -> source-tree CAS -> frozen evaluator
observations with interpreter provenance (schema `/2`) -> working-tree base
binding (G1-ARIADNE-05, HEAD verified before and after the target read) ->
canonical `CampaignReceipt` and `NominationReceipt`
(`receipt_profile controlled-repair-v1`).

The frozen gate is an evidence artifact under `docs/evidence/`, not an
entrypoint: it is not registered, not imported by the tree, and has no `main()`
that writes, spawns or reaches the network.

## Acceptance matrix

| Check | Result |
| --- | --- |
| campaign outcome | `nominated`, selected arm `repair`, `selected_seed` 2, `selection_mode` `best-passed-trial` |
| nomination receipt sha256 | `b1d17310a382defb999dcdb4f3af49c8b94a5588e40859946b8ef347db28322f` |
| nominated candidate tree sha256 | `81d0390463e8a0d1c741dbe0835ed0c2b733e734d65b92bd1ec398003e42db8b` |
| base source tree sha256 | `5744722af8fc88299fb482aac9f58d580a4a13d0967a14cf202ebcb9bf69b878` |
| three arms, independent verdicts | baseline `failed` (`exact-match-failed`), negative control `failed` (`exact-match-failed`), repair `passed` (`exact_match` 1) |
| both controls produced negative outcomes | `["baseline:frozen-evaluator-rejected", "negative-control:frozen-evaluator-rejected"]` |
| budget equality | `configured_equal` true, `realized_usage_recorded` true, `within_budget` true; one budget digest across all three arms |
| realized cost | `cost_microusd` 0, tokens 0, `wall_time_ms` 1167 |
| **independent gate discriminates** | exit **1** on base, baseline and negative-control CAS bytes; exit **0** on the repair |
| the fix does not lower the denominator | `n_resolving` 11 -> 13, `n_broken` 2 -> 0 (`docrefs`' stated anti-gaming invariant) |
| baseline arm is byte-identical to base | verified from the CAS |
| subject untouched after the campaign | `git status --porcelain` empty; HEAD still `cfe8d34b…` |
| candidate identity content-addressed and diffable | `candidate.diff`, `negative-control.diff`, `source-cas-inventory.json` (30 objects) |
| no promotion, apply, merge or push | none performed; the clone, the shared tree and its control root are unchanged |
| no user-profile path in retained evidence | leak scan over the evidence directory returns nothing |
| protected artifacts untouched by the candidate | single target path `daedalus/build.py` |

## Migration and rollback

Nothing to roll back in the repository: this packet adds documentation and
evidence only, and changed no code. The scratch clone and control root are
session-temporary and can be deleted without consequence. Deleting the evidence
directory removes the rehearsal record only.

If the owner decides the nominated repair should land, it is an ordinary
owner-made edit of two docstring lines in `daedalus/build.py`; `candidate.diff`
is the exact content. That decision is outside this packet.

## Evidence, expected failures, and review

Retained under `docs/evidence/G1-SELF-01_DOCSTRING_SYMBOL_DRIFT/`: the
sanitized `CampaignReceipt`; the base-versus-repair and base-versus-negative-
control diffs materialized from the CAS; the exact frozen `before`/`after`
fragments; the frozen gate and its verdict on all four trees; the 16
control-root effect-evidence records with an index carrying the digests of
their unsanitized bytes; the source-CAS inventory; the invocation record; and
`rejected-candidates.md`, which names every candidate considered and why it was
refused.

**Retained negative and neutral evidence**

1. **Six rejected targets, kept in full.** In particular two stale references to
   removed guard files (`daedalus/lanes/checks.py:132`,
   `daedalus/sensitivity.py:215`) were refused *because* they sit inside dated
   `MEASURED` blocks: correcting a dated measurement so it matches today's tree
   destroys the record instead of repairing it. A seventh candidate
   (`daedalus/status.py:90`, "The six counters" over an eight-key dict) was
   refused as not deterministically refuted — `print_counters` emits exactly six
   lines, so the sentence may be true, and a campaign must not nominate a repair
   to a sentence that may be true.
2. **The repository's own gate cannot see this defect class in code.**
   `docrefs.DOC_GLOBS` is `("docs/**/*.md", "README.md")`. A docstring is prose
   too, and the defect repaired here lived in one. Widening the corpus would
   create a new autonomous-edit surface over `daedalus/`, which the `docrefs`
   module docstring names as the day-one failure mode, so it is recorded as a
   `BACKLOG` observation for the owner and deliberately not attempted.
3. **The 80 broken references the existing gate does report** (3050 resolving,
   655 files scanned) were rejected wholesale as campaign targets: most are
   dated work packets and research notes describing a past or refused state,
   and at least one (`docs/STATUS.md:66-67`) is a genuine false positive where
   the reference names JSON keys of `.agentenv/agentenv.json` and a repair would
   turn accurate prose into a falsehood.
4. **Search is not claimed exhaustive.** One parallel read-only scout was lost
   to a session restart before reporting; dead branches were not searched
   systematically because a hand-picked one would not carry a frozen
   discriminating gate.

**Expected failure kept**: the linked-worktree subject refusal that G1-SELF-00
recorded still holds at this revision and is why the subject is a clone rather
than the lane worktree. Nothing in this packet attempts to loosen it.

Independent review not yet performed; this packet is offered for it. Codex was
not convened for this lane.

Iron Plan: **EXPERIMENT** (frozen spec, bounded, isolated, independently
evaluated, negative evidence retained, no production promotion)

Iron Gate: **1**

Evidence: `docs/evidence/G1-SELF-01_DOCSTRING_SYMBOL_DRIFT/` — campaign
`self-renovation-04` `nominated`; frozen gate exit 1/1/1/0 across base,
baseline, negative control, repair.

Automatic merge/promotion: **forbidden**. The owner decides.
