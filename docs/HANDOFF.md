# Daedalus — Session Handoff (2026-07-20, session 2)

> Provenance tags: **[M]** measured this session, uncontended · **[I]** inherited from a
> prior doc, not re-verified · **[A]** assumed/projected, no run behind it. The whole reason
> this section exists is that last session cited its own earlier numbers as fact — so every
> number below says where it came from.

## 0. Session 3 addendum (2026-07-21) — the Code Evolution foundation sprint — READ FIRST

Phase 0/1 of the code-evolution thesis landed as ONE sprint, currently **uncommitted** on
`checkpoint/2026-07-20-session`. Six workstreams: honest token denominator (tokenizer-exact,
cache-keyed by tokenizer identity), Safety-Class Reachability Router (the fence now asks the
import graph; three fail-open holes closed during build), UI/chat wires (BYOK badge, gated
picker, codex/deepseek brains on the untrusted lane, review-before-apply), `.dctx` certified
context receipts (deterministic SHA, offline verify, anti-tautology `label_provenance`),
the decontaminated eval oracle (per-provenance recall, A/B/C arms incl. BM25, per-task
ratchet `--gate`), and independent label minting + git temporal coupling.

Adversarial pass over the sprint: 18 raw findings → **14 confirmed** by 3-skeptic panels
(3 CRITICAL, 5 HIGH) → **all repaired and regression-tested same-sprint**; 4 refuted.
Cerberus egress review: **zero CRITICALs**. Fence-defect detail + the one known residual
(empty-paths codex sandbox) in §4c.

**Verified by the session author, not inherited from agents [M]:** pytest **700 passed / 0
failed**; `python -m daedalus.eval` prints the per-provenance breakdown and reports
**100% recall / 79.2% compression on the `hand_reachable` primary tier, explicitly labelled
PARTIALLY SELF-GRADED** (that labelling is the sprint's real deliverable — the old headline
quoted the same 100% as if independent); `--gate` ratchet **PASS** (exit 0);
`whole_repo_tokens` for agent_env is now a measured **381,265** (tiktoken/cl100k_base, tree
grown by the sprint's own ~2.5k new lines), no longer `total_chars//4`. The standing rule in
§4d (eval gate stays ADVISORY) is unchanged and load-bearing.

**THE FIRST INDEPENDENT NUMBER (same day, after the flywheel hardening below): quarantine
tier recall = 61.7% [M]** over 18 tasks minted from 20 real commits (2 skipped, reasons
stated). Suite **718/0 [M]**, primary tier unchanged, gate PASS. The first seeding also
CAUGHT ITS OWN POISONING — out-of-scope dist targets, same-file-label tautology, and one
unindexable task that crashed the whole oracle — all fixed same-day (`df0daee`): labels are
now scope-gated + cross-file-only, and a bad task becomes an ERRORED row (errored primary
fails the gate; errored quarantine is reported-only). **Miss triage [M, author-scripted
against import_edges]: of 129 missed labels — 57% = secret-floor fail-closed focus files
(four security-test files whose planted credential fixtures trip the unconditional floor;
the fence working as designed, colliding with the eval), 19% = genuine co-change coupling
with NO static import edge (the temporal class), 25% = cross-language labels (TS symbols
co-committed with .py targets) + parser junk (`if`, `<anonymous>`), and 0% =
edge-but-dropped.** Read that last one again: **the slicer dropped NOTHING it could
structurally see.** Excluding the fence-artifact tasks, structural recall ≈ 79% [M-derived],
and the entire remaining gap is coupling the import graph cannot express. Follow-ups this
implies, in order: (1) minter filters junk/cross-language label names and classifies
floor-tripping targets as `focus_withheld` instead of scoring them as misses; (2) the
temporal co-change tier becomes a slice ENRICHMENT experiment (add co-change neighbours,
measure recall gain vs compression cost on both axes); (3) only then wire slice→offload.

## TL;DR

A correctness + product-scope session. **14 commits on `checkpoint/2026-07-20-session`**
(`ff59963`..`95f00d2`; including the secret-floor CRITICAL fix, this doc update, and the
completed bootstrap), `main` untouched. Suite **549 passing [M, session 2]**, eval **100% recall /
78.7% compression [M, session 2 — under the chars/4 denominator then in use; re-measured 79.2% in
session 3 under the tokenizer-exact denominator, see §0]**.
The through-line: the structural engine was shipping *confidently wrong* answers on a real
repo, and most of this session was making it honest. The **bootstrap is now SHIPPED and
Cerberus-CLEARED** (egress review complete on the slice gate after six bypass classes were
closed; Ikarus chat brains now answer with gated project knowledge).

The single most important thing to understand before continuing: **the crew is now
gate-structured** (`.claude/AGENT_PROTOCOL.md`), and the gates repeatedly caught defects the
happy path missed — including two of *my own* introductions. Trust the gates; when you skip
one, say so in the commit.

---

## 1. Git state (READ FIRST)

- Branch `checkpoint/2026-07-20-session`, tip **`95f00d2`** (bootstrap: project-aware chat brains via gated slice). `main` untouched.
- Working tree is clean except regenerated `apps/web/dist/assets/*` (build output; harmless).
- Nothing stashed. Scratch worktrees removed. **Do not `git stash` a shared checkout while
  any agent runs** — it left the tree un-importable earlier this session. Use `git worktree`.

## 2. What shipped this session (11 commits, each verified by me not the agents)

**Project scope — the biggest single win.** `center` + `.daedalusignore` + `@tests` preset
(`daedalus/structcore/ignore.py`, `projects/*.json`, docs/PROJECT_SCOPE.md). A project
declares which subtree IS the code; the rest is *shell* — still parsed and resolvable as an
import target, but withheld from metrics and not expanded through by the slicer.

- project_tct `center=["TCT_app"]`, `ignore=["@tests"]`: **6,798 → 187 core files [M]**,
  wall **171s → ~22s [M]**, and hotspots stopped ranking vendored Printrun/Cython/wxPython
  and started ranking the actual app. **93% of the old duplication report was noise. [M]**
- Surfaced in the Structure panel (banner) so the shrink is never silent.

**Code map was 87% disconnected — fixed.** `_py_dotted` named Python modules from the repo
root, but a center IS the package root, so `from controller.x import ...` never matched and
nearly every internal edge was dropped. Now per-importer naming views (`index.py`).

- **42 → 478 edges, 162 → 50 isolated nodes (of 187) [M]**, `truncated` now honest.
- Momus (design gate) blocked the naive "just strip the prefix" fix — it would have widened
  a global table and *manufactured false edges*. The views approach avoids that.

**C/C++ + slice coverage (the "Odin/Adam" round).** S1: `_ts_name` now names C/C++ functions
(1/21 → 21/21 shapes [M]); Type-3 deliberately **held off for C/C++** because the generic
abstraction collapses their types to `ID` and *fabricates* clusters (Momus caught this on
paper; measured 5 unrelated C fns chaining at sim 0.853). S2: the distilled slice now expands
for non-Python targets via `import_edges` (0 → 28/32 files get a neighborhood [M]).

**Fabricated-clone fix.** `_strip_comments_generic` was string-literal-blind: `send("V //
500")` and `send("V // 50")` hashed identically, and `/*` in a string deleted whole function
bodies. Now a per-language string-aware scanner. Exposure was **66 of 6,798 files [M]** (not
the 499 a first bad measurement claimed, nor Fenrir's 889).

**Clone-pass memo.** Shared exact/abstract fingerprints across the three passes. **1.08× on
the full repo [M]** — NOT the ~2.4× projected [A]. Kept because it's free and removes a real
double-normalize, but "Python was never optimized" does not carry the weight it was given.

**Chat: streaming + persistence.** Wired `/api/ikarus/stream` (was dead) with a live bubble;
`es.close()` on final is load-bearing (EventSource reconnect re-spends). Transcript now
survives tab switches via sessionStorage. Chat cwd fix: `_claude()`/`_claude_stream()` run
from a neutral dir so they don't reload the repo's CLAUDE.md every message (~30% latency [M],
big token saving [I]).

**Slice egress gate — the bootstrap blocker, now CLEARED.** Commit `d714128` was NOT gate-cleared
in round 1 (Cerberus re-review found plaintext-secret CRITICAL still leaking: value-shape rule
used `\b...\b` + bare quotes, missing underscore-glued names like `DB_PASSWORD`, string prefixes,
triple quotes, short values, annotated assignment, quoted-key dict forms). Minos rewrote the
rule closing six bypass classes; Cerberus cleared it round 2 (`0360964`). See §4 for residual
limits + product backlog item.

**Crew redesign.** See §3.

## 3. The crew (`.claude/AGENT_PROTOCOL.md`, `.claude/agents/`)

Redesigned on Odin (NorthStar) + Adam (project_tct). Three tiers; **four adversarial gates**:
**Momus** (design critique on paper, pre-code) → **Týr**/`test-dev` (testability) →
**Nemesis**/`qa-critic` (attacks the RUNNING result; a break you didn't run doesn't count) →
**Cerberus** (security/egress; **CRITICAL blocks, no override**) → **Metron**/`vigil` (gate
suite). Minos owns the fence, Cerberus reviews it. Always-on haiku: **argus, hermes,
mnemosyne** (chronicler + provenance), **metron**.

Names are one coherent Cretan/Greek cycle now. `qa-critic` moved **fable → opus** because all
three Nemesis agents in one round died on a Fable quota limit — a gate that can't run is
worse than none.

**Two things the gates caught that I'd otherwise have shipped:** the code-map false-edge risk
(Momus), and the plaintext-secret leak in my own gate (Cerberus). **Two things a gate agent
got WRONG:** Metron reported "fix not applied" by querying the cached server instead of a
fresh process; and Metron called the leaky gate "tight and correct". **Always re-verify a
gate agent's measurement yourself, in a fresh process.**

## 4. COMPLETED: Ikarus bootstrap (wire slice → context)

**The bootstrap is SHIPPED and Cerberus-CLEARED** (commit `95f00d2`). Ikarus's chat brains
now answer with gated project knowledge.

**What it does:** `_claude()` now runs from a neutral cwd AND receives an on-demand distilled
slice of files the user names (via the freshly-gated slice layer). Both Claude (egress to
BYOK provider, gated) and local Ollama (no network egress, floor-gated) run with
`lane="trusted"` (secret floor ON, default-deny OFF → recall preserved). The slice REPLACES
the old 25,666-tok in-repo context baseline, never re-pays that cost. The bootstrap blocked
on two things: (1) the slice egress gate had to PASS Cerberus (done via commit `0360964`,
six plaintext-secret bypass classes closed), and (2) `_project_context` had to be wired
safely into `ikarus_os.py`.

**Verification [M]:** pytest **549 passed** (+23 new: `test_ikarus_context.py`, slice degrade
tests); eval **100% recall / 78.7% compression [M, session 2 — chars/4 denominator; the session-3
sprint replaced that denominator with a tokenizer-exact one, under which the same corpus measures
79.2%]** (slice refactor byte-identical, no symbol lost); no-file chat and deterministic intents
(status/distill/design/enqueue) are behaviorally identical; planted secrets
(glued/annotated/dict-key) never in the assembled prompt across module/focus/symbol paths.
Cerberus CLEARED the egress path.

**Residual limits, non-blocking (Cerberus ledger, for general-product hardening):**
- Keep `_project_context` OFF any untrusted lane. Metadata-disclosure safety (withheld
  breadcrumb tells the model "secret of kind X at path Y", path + rule-kind only, never
  value) rests on hardcoded `lane="trusted"`. Invariant to guard.
- R2-residual floor gaps are now a LIVE wire-reachable path: a focus `.py` file whose only
  secret is in an R2-residual shape (subscript `cfg["k"]="..."`, split-across-lines,
  >60-char-annotation) egresses its body when the user names it. Narrow (code `.py` only;
  config `.yaml`/`.env` not indexed), value-shape classes still caught; adjudicated
  ACCEPTABLE for the Daedalus-on-Daedalus case, but keep on the ledger for third-party
  distillation hardening.

---

## 4b. NEXT TASK: the "Code Evolution" foundation sprint

**Full plan (written, approved direction):**
`C:\Users\nukei\.claude\plans\remember-what-we-want-humble-lightning.md`.

**Direction (agreed with Kaya 2026-07-20):** Daedalus becomes an **evolutionary engine for
code** — a *genome* (certified context artifact), a *trustworthy fitness function*
(decontaminated eval), and *safe selection* (a graph-gated edit loop). Two READ-ONLY audits
this session — a 22-agent subsystem map + an 18-agent novelty tournament — independently
converged on the same reframe, each finding cross-checked against the code by me:

**Three verified findings that set the priority:**

1. **The moat is unwired from the mutate path [M].** `daedalus/offload.py` imports *zero*
   `structcore`; `semantic_slice` feeds chat (the bootstrap) but never the edit loop.
2. **The eval headline is partly self-graded [M].** `daedalus/eval/tasks.py` docstring: labels
   were "verified reachable by running `semantic_slice`" — so "100% recall" is partly a
   tautology. Fix = independent-oracle labels (git co-change + gate-verified diff-touched symbols).
3. **VERIFIED LIVE SAFETY GAP [M].** `sensitivity.change_risk()` (sensitivity.py:350) and
   `path_write_blocked()` (:366) substring-match only the LITERAL edited path against the fence —
   neither asks the import graph. A leaf `utils/clamp.py` transitively imported by
   `controller/hv_interlock.py` gets risk=`low` → the free Ollama lane may write it. *The graph
   knows; the fence doesn't ask.*

**The sprint = Phase 0/1 of the plan — prove + connect the foundation BEFORE building the loop on it:**

1. **`.dctx` certified context artifact** (new `daedalus/dctx.py`): content-addressed receipt
   `{commit, manifest, per-symbol hashes, egress verdict, recall, label_provenance}`, deterministic
   SHA, offline verify predicate. Additive/fail-closed. **NON-NEGOTIABLE:** `label_provenance` must
   distinguish independent-oracle labels from the assembly walk, else recall is tautological.
2. **Honest decontaminated eval oracle + flywheel:** `eval/harness.py` A/B/C (distilled vs concat
   with a *real* tokenizer vs BM25/embedding-RAG) on a held-out set; new `eval/mint.py` minting
   labels from landed diffs (`offload.py:196` disk_changed seam) + git co-change into a QUARANTINE
   tier; a counterfactual-regression ratchet. Start the decontaminated-label long pole day one.
   **GUARDRAIL:** an unvalidated metric NEVER gates autonomy — advisory first.
3. **Safety-Class Reachability Router (~1 day):** BFS `import_edges_reverse` ∩
   `high_risk_path_substrings` in `structcore/graph.py`; pre-check in
   `provider_router.select_provider` BEFORE `change_risk`; graded, over-escalate-never-under,
   dominance fallback. Closes finding #3.
4. **Cheap footgun wires:** BYOK badge (`getEnvStatus`), provider-status picker gating +
   `codex_cli`/`deepseek` branches in `ikarus_os._llm` (:360) (kill the silent brain degrade),
   `getDraft(id)` review-before-apply panel.

**Horizon (Phase 2–4, only after the foundation holds):** wire `semantic_slice → offload`
(Movement III MVP, now correctly sequenced AFTER the oracle proves the slice); **Panel of Rivals**
(cross-vendor candidates, the *gate* judges not a model); **Repo Physician** (hotspot → gated draft);
**Clone-Propagated-Fix**; **Context-as-a-Service MCP** (Cursor/Claude-Code/Copilot become *consumers*
of verifiable context); **Cockpit-as-Proof-Surface** (distillation x-ray + collapse + health morph).

*The old "two paths" are absorbed: the js-tokens over-block + a distillation consent surface stay in
the backlog (§5); Movement III becomes Phase 2, resequenced after the eval oracle.*

## 4c. What this sprint did NOT do (Horizon, still pending)

The foundation sprint completed Phase 0/1 as designed. These remain open:

- **Wire `semantic_slice` into `offload.py`** — the distilled slice now feeds chat (Ikarus) but
  not yet the edit loop. The loop remains routed on raw change-risk path-matching.
- **The closed edit loop** (Movement III MVP) — minting, persistence, and reload all exist
  (`eval/mint.py` store + `--mint-commit`/`--confirm-mint` CLI + `harness.all_tasks()`), but the
  flywheel's live seam is still open: `offload.py` never calls `mint_task_from_landed_edit` after
  a landed write, so minted tasks only enter the corpus by hand today.
- **Panel of Rivals** — cross-vendor candidate selection where the gate (not a model) judges which
  provider answered best, remains phase 2.
- **Repo Physician** — hotspot-to-draft automation remains phase 2.
- **Context-as-a-Service MCP** — third-party tools (Cursor, Claude-Code, Copilot) becoming
  consumers of verifiable distilled context remains phase 3.

Fence-defect status, stated precisely: the adversarial review panel (not Cerberus — Cerberus's
egress review returned **zero CRITICALs**) confirmed three CRITICALs against the new reachability
fence, and **all three were fixed and regression-tested in the same sprint**: (1) the dominance
stand-down could hand an itself-fenced top-level file to the local write lane — closed at the
source by root-anchoring the path-fence match (`sensitivity._fence_norm`; `tests/test_fence_anchoring.py`);
(2) the agentic ollama write tool could write outside the declared paths with no fence consult —
closed by a post-write blast-radius fence over the verified `disk_changed` diff in `offload.py`
(`tests/test_repair_blast_radius_write.py`); (3) the forced codex bridge lane granted writable
without ever calling the fence — closed in `core.py` by consulting the reachability pre-check
before granting write. One residual is genuinely open and known: an **empty-paths codex task**
runs in a repo-wide `workspace-write` sandbox whose individual writes cannot be intercepted
per-file; keep codex off empty-paths write work until that lane gets its own post-write gate.

## 4d. Advisory guardrail on the eval gate

The new `run_gate` (eval/harness.py:635) and any health-delta metric MUST remain **ADVISORY only**
and NEVER gate autonomous action until independently validated to predict task success on real work.
The underlying data (hand_reachable labels) is partly self-graded; the machinery is honest but the
labels themselves are not independent. Do not upgrade the gate to a blocking gate without:
1. An independent label source (minted diffs, temporal churn, or a human-reviewed held-out set)
2. A live validation round showing gate decisions correlate with task success/rollback rates
3. Explicit sign-off from the risk/security review that the policy applies to your actual deployment

## 5. Backlog (recommended order)

1. ✅ **Bootstrap: wire slice → Ikarus context.** SHIPPED + Cerberus-CLEARED (commit
   `95f00d2`). Chat brains now project-aware via gated slice, both lanes trusted, 549 pass /
   eval 100%·78.7% [M, session 2]. See §4 for residual ledger and hardening priorities.

2. **Scan out of the server process.** STILL OPEN. The scan is CPU-bound in a
   `ThreadingHTTPServer` thread and freezes the cockpit; measured 97% of one core, 20s
   request latency during the clone passes [M, session 1]. The per-file phase is already in a
   process pool; it's the *clone passes* that block. Honest budget ~1 week [A], not the ~1 day
   first claimed — the naive version silently loses Move-4 resolution (no exception, no failing
   test).

3. **`file_key` cache staleness (Fenrir, confirmed).** The disk-cache key hashes only
   `parse.py`; edits to `metrics.py`/`imports.py`/`clones.py` serve stale analysis. Fold a
   digest of all analysis modules into the key.

4. **General-product egress-consent surface + hardening** (Path A from §4b). Three items:
   - Value-entropy or whole-keyword anchoring to fix `js-tokens`/`jsonwebtoken` over-block
   - Disclosure wording for R2-residual limits when distilling third-party source
   - One-time "Claude will see your distilled project source" consent surface before Ikarus
     first file-named turn. Keep the Cerberus invariants (§4) visible to future gate rounds.
   Honest budget ~3–5 days [A].

5. **Movement III (orchestration loop, Path B from §4b).** Newly unblocked (import graph
   honest, gate cleared). Wire the loop that reads import-dependency frontier and suggests
   next steps. NOT before #4 — the plan's own rule. Honest budget ~1 week [A].

6. QML `qmldir` implicit imports (map still sparser than it could be); `resolve_internal`
   prefers lexicographically-first candidate (often wrong); Rust parity (see §7).

## 6. Gotchas (hard-won, do not relearn)

- **Measure uncontended, or the number is wrong not slow.** This session: 1.47× was really
  0.99× (23 agent procs running); 171s was really 86.5s; 499 files was really 66. Check the
  python process count before any timing.
- **Any script calling `build_index` needs `if __name__ == "__main__":` AND must be a real
  file, not `python - <<`.** Windows spawns pool workers that re-import `__main__`; via stdin
  that path is `<stdin>` → `OSError 22`. Hit this three ways in one session.
- **A gate/measurement against the running server reads a CACHED index.** Measure in a fresh
  process. Bump `ignore.SCOPE_ALGO_SALT` when the index *contents* change under an unchanged
  center, or warm caches serve the old graph.
- **PowerShell 5.1: no `2>&1` on a native exe** (wraps stderr as a terminating error);
  workflow script files must have **no `\r`** (permission dialog rejects them as control chars).
- **`sensitivity._compile` silently drops any regex >200 chars.** A safety pattern that's too
  long vanishes with no error. `_compile_labeled` now asserts against it for the floor; other
  callers are still exposed.
- BYOK, additive endpoints, `/api/dashboard` frozen by `test_ui_contract` — all still hold.
  `test_ui_contract` is load-flaky (starts its own server); re-run quiet before believing a fail.

## 7. Rust engine — the claim that needs correcting in memory

`memory/daedalus-agentos-moonshot.md` records the pivot rationale as "10–100× faster [I]".
**Measured this session: Rust ~2.1× [I, handoff] / ~1.3× like-for-like [M] / SLOWER on the
full repo (216s vs 171s) [M]** doing less work. The **Tauri/bundling** rationale stands and
is the honest reason to finish it; the speed claim does not. Also: `structcore-rs` has no
safety gate, no scope awareness, is 13 languages behind, has its own copy of the S1 naming bug
(`parse.rs`), and is invoked by zero Python code paths. **This memory should be corrected** —
it's still steering decisions on a false number. (User asked twice about "backend in Rust";
the audit's answer was "right destination, wrong next step — the measured defect is a
concurrency failure the GIL causes, which is a process boundary, language-neutral").

## 8. Pointers

- Plan: `C:\Users\nukei\.claude\plans\ast-driven-distillation-harness-modular-sprout.md`
- Memory: `daedalus-agentos-moonshot.md`, `crew-delegates-protocol.md` (updated),
  `daedalus-validation-status.md`
- Scope: docs/PROJECT_SCOPE.md · Engine parity gap: docs/ENGINE_PARITY.md
