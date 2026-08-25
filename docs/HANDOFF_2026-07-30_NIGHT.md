# Handoff — night of 29/30 July 2026 (closed)

Condensed 2026-08-25 [MEASURED: only referents left are `docs/archive/TODO_2026-07-30_SESSION.md`,
an experiment fixture, and the auto-generated architecture map — nothing live points here].
Full narrative record: [NIGHT_SHIFT_2026-07-30.md](research/NIGHT_SHIFT_2026-07-30.md).
Wiki entry point: `docs/wiki/night-shift-2026-07-30.md`.

All open items below were closed by the day shift or the 30/31 July follow-up; this page
keeps the outcomes, not the hour-by-hour narrative.

## What happened, in order

1. **Lab worktree rescued.** Five uncommitted modules in a session-scoped temp dir
   (`daedalus/eval/preserve.py`, `type_ceiling.py`, `structcore/latex.py`,
   `wiki/queries.py`, `observe/tracer.py`) committed unreviewed as `a31d004` on
   `experiment/deepseek-lab`.
2. **Main checkout committed.** 104 uncommitted files (54 untracked) landed in ~10
   coherent commits, `73ad0f0..2b08861`.
3. **Ollama write-guard gap closed**, commit `8c7bc0c`: `daedalus/lanes/checks.py`
   built the shared `run_checks()` baseline (parses, not-truncated, no-elision,
   not-substituted, imports-resolve); both `deepseek.py` and `ollama.py` now call
   it, closing the gap where DeepSeek had content-substitution and invented-import
   guards that Ollama lacked. `tests/test_lanes_checks.py`: 29 passed.
4. **Graph brief wired**, same commit: `daedalus/lanes/graph_brief.py` (symbols/imports,
   function-body-only edges marked) injected into both provider write loops
   (`render_brief(` at `deepseek.py:361`, `ollama.py:775`). Mitigates three named
   hallucination cases; not re-measured end-to-end against a fresh fan-out.
5. **Snapshot leak fixed**, commit `fe634b5`: `offload._repo_snapshot` walked with
   `rglob`, whose skip set missed gitignored trees, so `.captures/` (captured Edge
   profile data) leaked credential-shaped paths into snapshots. Fixed to use
   `git ls-files --cached --others --exclude-standard`; 0 credential-shaped paths
   after the fix (reproduced independently).
6. **JSON escape + summary-default repair**, commit `f6c9470`: lossless escape repair
   in the shared report parser, and `coerce_report` no longer refusing an
   evidence-bearing answer that omitted a summary. 126/126 passing across the
   affected suites. Corrected attribution (re-read from raw blocked answers): of
   15 addressable blocks, 14 were the missing-summary refusal and 1 was the escape
   defect; 4 further blocks were correct `sensitivity.py` egress refusals, not bugs.
7. **Labeled-property-graph projection added**, commit `3088037`:
   `daedalus/structcore/lpg.py`, a pure read-only projection of the Forest onto the
   LPG model (GQL/SQL-PGQ/Neo4j/CPG-compatible), wired into the structcore CLI as
   `--lpg`. 11/11 tests pass. Node/edge counts are a property of an exact tree
   state, not of `daedalus/` in the abstract — quote counts only with the commit
   that produced them (`forest_sha256` pins reproducibility; verified deterministic
   under a held-still tree).
8. **Fan-out refusal accounting fixed**, commit `1e9d5dd`: `ok` used to mean "the
   transport produced answers", so an all-refused unit counted as success and
   `resume` served it forever without retry. Now `ok` requires evidence-bearing
   answers, refusals count separately under `blocked`, and an all-blocked unit is
   retried. 27 passed, 4 subtests.

## Verified findings worth keeping (negative evidence, still true of that vintage)

- A syntax gate cannot distinguish code from plausible-looking code — both measured
  destructions (a module replaced by its own test file; tests importing modules
  that don't exist) were valid Python; `compileall` passed both.
- Docstrings claiming guarantees the code didn't have, found in four places:
  `spine/bootstrap.py` ("never writes the primary checkout" — it does, via
  `refresh_sources()`), `loop.py` ("no write path" — the ledger defaults to
  `<repo_root>/runs/loop/`), the atomic-publish family (several modules claiming
  atomic publish while omitting the Windows `os.replace` retry that
  `killswitch._atomic_write` documents), `sensitivity.load_policy` ("never weaken
  the baseline" — doesn't hold for project-only `allow_exceptions`).
- 8 DeepSeek refuters found 0 findings on a task where two ~40-line AST functions
  caught 3/3 destructions and 4/7 hallucinated test files at 0 false positives —
  **later found confounded**: `build_prompt` forbade chain-of-thought while
  demonstrating an empty `"risks": []` answer. Re-run with `system_override`
  before citing the 0-findings number again. The AST-checks result is unaffected.
- Static checking has a measured ceiling: of 7 agent-written test files, 3 failed
  on statically-catchable errors, 4 failed on wrong assumptions only execution
  catches.
- Refuted at the time (kept so they don't get re-scheduled): `memory/embeddings.py`
  *does* implement `search_report`/`record_journal_watermark`; `containment.JobLimits`
  and `worktree.remove_tree_no_follow` *are* defined; `containment._log_as_hex` /
  `_verify_job_config` never existed anywhere in the repo; "budget accounting stops
  under concurrency" was a fan-out script bypassing `install_process_guard()`, not
  a `budget.py` defect; `loop.py` *does* depend on `core.get_governance` (`:1039`
  at the time).

## Calibration lessons (the durable part)

- A syntax gate is not a behavior gate — only execution catches wrong assumptions.
- Express a restriction as a capability (`high_risk_paths`), never as a prose
  instruction to an agent — the prose brief achieved nothing.
- A plausible pattern is not a mechanism — cheapest to just run the two-line
  experiment that distinguishes them.
- A document that cites a measurement with no date silently becomes false. Three
  of that session's four stale claims were exactly this shape.
- Agents that never see the graph hallucinate imports a symbol manifest would have
  prevented, at a measured cost of ~6.5k characters for the whole `daedalus/`
  package.
- Pairing a second *model* as a refuter roughly doubles cost and lowers detection
  vs. a deterministic check; a second model earns its keep only on "does this do
  what was asked", where the repo's rule already requires a different model
  family from the generator.

## Receipts (that session, not current)

12 mutations planted, 12 killed, 0 survived, whole-suite scope, at `fe634b58`;
`proven=False` because HEAD moved before the receipt could bind. A prior run failed
`baseline_red` on a stale-detector calibration test (fixed in `65e2878`). The
open question that session left behind — whether freshness should be
ancestor-with-no-relevant-diff instead of equality, so a receipt survives HEAD
moving during a multi-hour run — was deliberately left for someone other than the
person who wrote the measurement it would validate.
