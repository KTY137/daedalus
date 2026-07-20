# Daedalus — Session Handoff (2026-07-20, session 2)

> Provenance tags: **[M]** measured this session, uncontended · **[I]** inherited from a
> prior doc, not re-verified · **[A]** assumed/projected, no run behind it. The whole reason
> this section exists is that last session cited its own earlier numbers as fact — so every
> number below says where it came from.

## TL;DR

A correctness + product-scope session. **11 commits on `checkpoint/2026-07-20-session`**
(`ff59963`..`d714128`), `main` untouched. Suite **511 passing [M]**, eval **100% recall /
78.7% compression [M]**. The through-line: the structural engine was shipping *confidently
wrong* answers on a real repo, and most of this session was making it honest.

The single most important thing to understand before continuing: **the crew is now
gate-structured** (`.claude/AGENT_PROTOCOL.md`), and the gates repeatedly caught defects the
happy path missed — including two of *my own* introductions. Trust the gates; when you skip
one, say so in the commit.

---

## 1. Git state (READ FIRST)

- Branch `checkpoint/2026-07-20-session`, tip **`d714128`**. `main` untouched.
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

**Slice egress gate (`d714128`) — the bootstrap blocker, now closed but UNVERIFIED by review.**
See §4.

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

## 4. NEXT TASK: get Cerberus to clear the egress gate, then bootstrap

The slice egress gate (`d714128`) closes the CRITICAL — plaintext secrets (`password =
"..."`, bearer tokens) no longer leak into a slice on any lane; I reproduced the leak and the
fix myself across all three slice paths, and `n_included=0` when a secret file is the focus.
**But per crew protocol a CRITICAL clears only when the REVIEWER clears it, not the author.**
Cerberus has not re-reviewed the fix.

**So: do NOT enable Daedalus-on-Daedalus distillation yet.** The steps, in order:

1. **Cerberus re-review** of `d714128` (agentType `cerberus`). If green, the last blocker is gone.
2. **Wire slice → Ikarus context**: `_claude()` currently runs from a neutral cwd and so has
   *no* project knowledge. Replace that with an on-demand distilled slice of the relevant
   files, now that it's gated. This IS the bootstrap. Measure cost-per-message before/after.
3. `agent_env` already has scope config (`projects/agent_env.json`, `center=["daedalus",
   "apps/web/src"]`) so a self-slice won't drag in `dist/` or tests.

## 5. Backlog (recommended order)

1. **Cerberus clears the gate → bootstrap** (§4).
2. **§4-original: scan out of the server process.** STILL OPEN. The scan is CPU-bound in a
   `ThreadingHTTPServer` thread and freezes the cockpit; measured 97% of one core, 20s
   request latency during the clone passes [M, session 1]. The per-file phase is already in a
   process pool; it's the *clone passes* that block. Honest budget ~1 week [A], not the ~1 day
   first claimed — the naive version silently loses Move-4 resolution (no exception, no failing
   test).
3. **`file_key` cache staleness (Fenrir, confirmed).** The disk-cache key hashes only
   `parse.py`; edits to `metrics.py`/`imports.py`/`clones.py` serve stale analysis. Fold a
   digest of all analysis modules into the key.
4. **Movement III (orchestration loop).** NOT before the above — it consumes the import graph
   (only just made honest) and edits+ships code (needs the gate cleared). The plan's own rule.
5. QML `qmldir` implicit imports (map still sparser than it could be); `resolve_internal`
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
