# Daedalus — Session Handoff (2026-07-20, session 2)

> Provenance tags: **[M]** measured this session, uncontended · **[I]** inherited from a
> prior doc, not re-verified · **[A]** assumed/projected, no run behind it. The whole reason
> this section exists is that last session cited its own earlier numbers as fact — so every
> number below says where it came from.

## TL;DR

A correctness + product-scope session. **14 commits on `checkpoint/2026-07-20-session`**
(`ff59963`..`95f00d2`; including the secret-floor CRITICAL fix, this doc update, and the
completed bootstrap), `main` untouched. Suite **549 passing [M]**, eval **100% recall / 78.7% compression [M]**.
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
tests); eval **100% recall / 78.7% compression** (slice refactor byte-identical, no symbol
lost); no-file chat and deterministic intents (status/distill/design/enqueue) are
behaviorally identical; planted secrets (glued/annotated/dict-key) never in the assembled
prompt across module/focus/symbol paths. Cerberus CLEARED the egress path.

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

## 4b. NEXT TASK: pick from two unblocked paths

**Path A: General-product egress-consent surface + hardening (HIGH-non-blocking for
arbitrary JS/TS repo distillation).** The slice gate now guards Daedalus-on-Daedalus
(CLEARED), but third-party repo distillation needs three fixes: (1) the broadened `\w*`
sub-token match over-blocks npm names `js-tokens`/`jsonwebtoken` in lockfiles (not
import-graph nodes; needs value-entropy or whole-keyword anchoring); (2) the R2-residual
gaps (above) are narrow but need disclosure when distilling source the user hasn't audited;
(3) add a one-time "Claude will see your distilled project source" consent surface before
first Ikarus chat with a file-named turn. Fold in the two Cerberus invariants above.
Honest budget: ~3–5 days [A].

**Path B: Movement III (orchestration loop, newly unblocked).** The plan's own rule says it
must not precede the above — it consumes the import graph (just made honest in this session)
and edits+ships code (gate just cleared). Wire the orchestration loop that reads the
import-dependency frontier and suggests next steps. Honest budget: ~1 week [A]. This is the
capstone for "Daedalus understands Daedalus code"; after this, shift to hardening
third-party distillation + the Ikarus UX layer.

## 5. Backlog (recommended order)

1. ✅ **Bootstrap: wire slice → Ikarus context.** SHIPPED + Cerberus-CLEARED (commit
   `95f00d2`). Chat brains now project-aware via gated slice, both lanes trusted, 549 pass /
   eval 100%·78.7%. See §4 for residual ledger and hardening priorities.

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
