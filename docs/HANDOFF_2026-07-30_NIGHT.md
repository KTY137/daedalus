# Handoff — night of 29/30 July 2026

Written at 10:30 on 30 July for whoever picks this up next. Everything below was
measured during the shift; nothing is inherited or assumed. Where a number has a
command that regenerates it, the command is given — after tonight, a number
without one is treated as no number.

Full record: [NIGHT_SHIFT_2026-07-30.md](research/NIGHT_SHIFT_2026-07-30.md).
Wiki entry point: `docs/wiki/night-shift-2026-07-30.md`.

---

## 0. Read this first: what can actually be lost

**The lab work lives in a session-scoped temp directory.**

```
C:/Users/nukei/AppData/Local/Temp/claude/c--Users-nukei-Desktop-agent-env/
    d3328700-1c36-4894-8ddc-e71ce0502118/scratchpad/lab      [experiment/deepseek-lab]
```

A new session gets a different scratchpad path and that directory may be swept.
It holds, uncommitted, five modules that import and expose real APIs:

| file | size | what it is |
|---|---|---|
| `daedalus/eval/preserve.py` | 370 lines | semantics-preserving transform generator — the missing **specificity arm** for a project with no history |
| `daedalus/eval/type_ceiling.py` | 2.8k | first attempt at the type-layer ceiling experiment |
| `daedalus/structcore/latex.py` | 3.8k | tier-0 LaTeX extractor (`\input`, `\includegraphics`, bib) |
| `daedalus/wiki/queries.py` | 4.3k | `find_documented_but_unimplemented`, `find_undocumented_code`, `find_orphan_pages` |
| `daedalus/observe/tracer.py` | 6.7k | runtime shape tracer (`shape.py` finally gets a caller) |

Plus `tests/test_wiki_vault.py` and `tests/test_wiki_links.py`, which extend
`vault.py` with refusals for drive-relative paths, unicode normalisation collapse
and tilde segments.

**None of it is reviewed and none of it should be merged unread** — it came from
the wave that also destroyed three modules. But losing it costs a night.
Committing it on its own branch costs a minute.

The main checkout has **104 uncommitted files, 54 of them untracked**, including
the three gate fixes and their 25 tests. All verified; none durable.

---

## 1. Do these in this order

**1. Rescue the lab branch.** Commit in the worktree, or `git bundle` it out of
the temp directory. Order matters only in that everything else can wait and this
cannot.

**2. Commit the main checkout.** The night's work is verified and green
(`pytest tests -q -k "deepseek or provider or offload or egress or budget"` →
456 passed; `-k "mutat or graph_delta or eval"` → 263 passed).

**3. Close the Ollama gap — see §2. It is a regression I introduced tonight.**

**4. Then, and only then, the ignition.** The gate binds its receipt to HEAD, so
running it before the commits means the receipt is stale the moment they land.

---

## 2. The gap I opened tonight, and the framework question it answers

Two new guards went into `daedalus/providers/deepseek.py` and **not** into
`ollama.py`:

| write-path guard | `deepseek.py` | `ollama.py` |
|---|---|---|
| elision markers | ✓ | ✓ |
| truncation (<50% of original) | ✓ | ✓ |
| **content substitution** (`_substitution_reason`) | ✓ | **✗** |
| **invented first-party imports** (`_unresolved_first_party_imports`) | ✓ | **✗** |

The external, untrusted, paid lane is now strictly safer than the local, free,
default one. The two failures measured tonight — writing one file's content into
another, and importing modules that do not exist — are wide open on Ollama.

This happened within hours, which is the argument for the framework better than
any architectural reasoning: **the guards are per-provider copies, and when one
improves the others silently fall behind.**

### Proposed shape (discussed, not built, awaiting a decision)

```
daedalus/lanes/checks.py
    Check = (rel, original, proposed, repo_root, policy) -> refusal | ""
    BASELINE = (parses, not_truncated, no_elision, not_substituted, imports_resolve)
    run_checks(...)   # cheapest first, first refusal wins, fail-closed
```

Every write path calls `run_checks` instead of hand-rolling a sequence. A
provider may **add** checks; it may never skip the baseline. Small, because the
pieces exist — they need lifting out of `deepseek.py`, not writing.

Note the deliberate duplication already documented in `deepseek.py`:
`_ELISION_MARKERS` is kept as that module's own tuple because it is *a claim
about what an external model emits*. That reasoning is sound and should survive
the refactor — the baseline is shared, per-lane claims stay per-lane.

### On pairing agents with a "micro-Nemesis"

Measured tonight, and it settles the question:

- **8 DeepSeek refuters → 0 findings.** Several thousand seconds, nothing usable.
  (Partly because `writable=True` hard-coded `risks: []` — now fixed with a
  `notes` side channel — but they also wrote instead of reviewing.)
- **Two AST functions of ~40 lines → 3/3 destructions caught, 4/7 hallucinated
  test files caught, 0 false positives across 336 real files**, deterministic,
  microseconds.

A micro-Nemesis as a second *model* is the expensive version of what just failed.
As a *deterministic check* it is what worked. Pair agents and you double the cost
and lower the detection rate.

**Where a second model does earn its keep:** the one question no function can
answer — *does the change do what was asked?* There the repo's existing rule
applies: a different model family from the generator, or the distribution is
grading itself.

### On the "second shell"

Static checking has a measured ceiling. Of seven agent-written test files, **3
failed on statically-catchable errors** (invented modules) and **4 failed on
wrong assumptions about real behaviour** — only execution catches those.

Executing agent-written code is exactly what this repo refuses on principle. The
resolution is not a new shell but the containment that exists
(`spine/containment.py`, Windows Job Objects), as tiers:

| tier | cost | catches |
|---|---|---|
| 0 — AST checks | µs | substitution, invented imports, parse failure |
| 1 — import in the sandbox | ~1 s | load errors, circular imports |
| 2 — the affected test file only | ~10 s | wrong assumptions |
| 3 — full suite / the gate | minutes | everything else |

**Tiers 0–2 are thermometers. Only tier 3 promotes.** Losing that distinction is
how `compileall` ended up acting as a gate tonight, and it passed a file that had
destroyed a module.

---

## 3. The ignition

**The blocker is gone.** The sandbox baseline is GREEN:

```
[baseline OK] 12 mutation(s) queued (0 pre-excluded by coverage), gate_paths=WHOLE SUITE
  [ok  ] worktree_moved_checkout_unguarded (deletes-outside-the-worktree)
```

The run was cut off by session teardown after the first mutation, so the receipt
is **still the one from 29 July**, measured at `a5fc7ce`, while HEAD is `7a5fb07`.

Two things that cost hours tonight, so they do not cost them again:

- **Use `--head-only`.** It exists precisely for a working tree being
  concurrently edited, which this one is. Without it the gate carries the
  uncommitted diff and cannot produce an interpretable baseline.
- **The earlier `baseline_red` was a TIMEOUT, not red tests.** `pytest exit None`
  means the subprocess never returned. `DEFAULT_TIMEOUT_S` is 900; the suite runs
  in ~105 s idle but blew past 900 under a hundred concurrent agents. Run the
  gate on a quiet machine, or raise `--timeout`.

Budget roughly **two hours uninterrupted**: 12 mutations, each a full suite run.

```
python -u tools/gate_discrimination.py --dry-run        # 12/12 anchors, ~2 min
python -u tools/gate_discrimination.py --head-only      # the real thing
```

---

## 4. Verified findings worth acting on

Confirmed by reading the code, not by an agent asserting it.

**Highest severity, and NOT yet verified by me — check before acting:**
`offload._repo_snapshot` walks the repo root with `rglob` and its skip set misses
gitignored trees. `.captures/` **does exist** in this checkout (a size check timed
out, which is itself informative) and is said to contain Edge profile data
including `Login Data` and `Cookies`. If true, `result["wrote"]` — labelled
GROUND TRUTH and used to arm the test gate — can name files no agent touched.
Proposed fix: snapshot `git ls-files`, not `rglob`. `tools/mutation_score.py`
already knew about `.captures`; the knowledge never reached the gate.

**Docstrings that promise what the code does not do.** The pattern is worth
knowing: three of the four worst cases have the guarantee at the top of the file
and its own correct qualification in a comment further down.

- `spine/bootstrap.py` — "IT NEVER WRITES THE PRIMARY CHECKOUT"; `refresh_sources()`
  runs `python -m daedalus.cli map` with `cwd=repo_root` and rewrites
  `docs/architecture-state.json`, then verifies the write happened.
- `loop.py` — "There is no code path from this module to a write in `repo_root`";
  the ledger defaults to `<repo_root>/runs/loop/`. Standing evidence: an
  untracked `runs/loop/` with ten files.
- **The atomic-publish family**, including code I wrote last night:
  `arch_memory.save`, `shift._write_atomic`, `file_bridge._write_json_atomic`,
  `loop.LoopLedger.save` all claim atomic publish and all omit the Windows
  `os.replace` retry that `killswitch._atomic_write` documents as MEASURED and
  `budget._store` implements. `arch_memory.save` names the exact concurrent-reader
  scenario that breaks it, then does the bare replace.
- `sensitivity.load_policy` — "a project can extend, but never weaken, the
  baseline" does not hold for `allow_exceptions`, which is project-only and
  checked *before* the deny list. The unconditional secret floor still catches
  credential shapes, so this narrows the gate rather than removing it.
- `eval/harness.eval_task_tier1` — "NEVER RAISES" catches only `(ValueError, OSError)`;
  `task["repo"]` is an unguarded subscript.

**Structural, from the census synthesis:**

- **The import graph is 38% invisible.** 202 of 526 internal edges exist only
  inside function bodies. Counting them, there is a 13-module strongly-connected
  core (`core`, `offload`, `health`, `status`, `doctor`, `file_bridge`,
  `benchmark`, `kairos/scheduler`, `kairos/gated_writes`, `spine/attempt`,
  `spine/bootstrap`, `spine/picker`, `eval/correctness`). Any tool reading only
  top-level imports sees ~60% of the truth.
- **`budget.py`'s own `SPEND_SITES` names eight spend-capable functions in files
  under `runs/`** — real Python with its own entrypoints, outside the import
  graph, in processes where `install_process_guard()` is never called. The guard
  installs in exactly three places: `cli.py`, `loop.py`, `claude_bridge.py`.
- **The loop's queue is 90% suppressed**: `build_queue()` returns 2 candidates,
  18 withheld on staleness (11 map, 7 inventory). Upstream of the gate receipt.
- **The freshness stamp is unsatisfiable.** Commit `7a5fb07` changed only
  `FEATURE_INVENTORY.json` and by landing invalidated its own stamp. Fix:
  ancestor-with-no-relevant-diff instead of equality. **This will bite during
  step 1.2 above.**
- `build/lib/daedalus/` holds 142 untracked stale copies of the package. Every
  naive grep double-counts them; filter with `grep -v build/lib`.

---

## 5. Do NOT schedule these — they were checked and are false

Kept explicitly, because a refuted claim that stays in a document gets
re-discovered and re-scheduled.

- ~~`memory/embeddings.py` does not implement `search_report` /
  `record_journal_watermark`~~ — both exist (`:1402`, `:963`). Only
  `ingest_report` is genuinely absent.
- ~~`containment.JobLimits` and `worktree.remove_tree_no_follow` are in `__all__`
  but undefined~~ — both exist. An AST sweep of all 81 modules with `__all__`
  found **zero** real defects. My own static checker also produced two false
  positives on the same class.
- ~~`containment._log_as_hex` / `_verify_job_config`~~ — these names have **zero
  occurrences anywhere in the repo**. One was carried as CONFIRMED in
  `EXTERNAL_FINDINGS.md`.
- ~~Budget accounting stops under concurrency~~ — **my error.** The fan-out
  scripts constructed the provider directly and never called
  `install_process_guard()`. Measured: without it 76→76 ledger entries, with it
  76→78. ~170 unpriced API calls before I noticed. `budget.py` is untouched and
  should stay so; it is on `high_risk_paths` and the design is deliberate.
- ~~`loop.py` does not depend on `core.get_governance`~~ — it does, at `:1039`.

---

## 6. What changed in the code tonight

All green, all tested, none committed.

- `providers/deepseek.py` — three fixes: the rewrite prompt now binds output to
  the target path; `_substitution_reason()` refuses a rewrite where fewer than
  half the top-level definitions survive; `_unresolved_first_party_imports()`
  refuses invented `daedalus.*` / `tools.*` / `tests.*` imports. Plus a `notes`
  side channel so a writable run can report at all.
- `tools/vet.py` — `mcp_spec_digest()`; MCP allowances now bind to the command,
  args and env **keys** rather than to a name. Values are excluded on purpose so
  a rotated token does not invalidate every pinned allowance.
- `eval/mutate.py` — the no-go filters now run. They were defined, documented as
  built, and called from nowhere. Refusals are published on
  `generate.last_filtered` (62 sites on the no-go function list, 3 in `__main__`).
- `eval/graph_delta.py` — `--held-out` and `--specificity` branches, so both
  headline numbers have a command. `held_out()` is new.
- `tools/agent_findings.py` — new; consolidates fan-out results by target file.
- `daedalus/crew_hook.py` — new; the ≥4-parallel-agents hook, registered in
  `~/.claude/settings.json`.
- `tests/test_deepseek_substitution_guard.py` — new, 25 tests.

### The corrected fitness numbers

| | published | reproducible |
|---|---|---|
| held-out detection | 75.3% | **95.3%** (286/300) |
| `change_constant` | 0/62 | **54/68** |
| false alarm, real commits | 0.9% / 0.7% | **0 of 38** |

```
python -m daedalus.eval.graph_delta . --held-out --count 300
python -m daedalus.eval.graph_delta . --specificity --limit 40
```

**This is not an improvement, it is a first honest measurement.** The old figures
came from throwaway scripts that no longer exist, so the gap cannot be
reconciled. Remaining blind spot: 14 of 68 `change_constant` mutants move no
layer.

---

## 7. Calibration to carry forward

- **A syntax gate cannot distinguish code from plausible-looking code.** Both
  measured failures — a module replaced by its own test file, and tests importing
  modules that do not exist — are valid Python. `compileall` passed all of them.
- **Express a restriction as a capability, never as an instruction.** The one
  control that held was `high_risk_paths` refusing `budget.py` to an external
  lane. The prose brief "do not edit the implementation" achieved nothing —
  partly because the harness gave the agents no way to comply.
- **Corroboration was unavailable and pretending otherwise would have been
  sorting noise.** 1,226 claims, largest agreement cluster **two**, because the
  fan-out gave nearly every agent a different file.
- **The cheap model is reliable about aggregate shape and unreliable about every
  specific claim.** Of 154 UNWIRED candidates, 147 were false — a 95.5% false
  positive rate — and the tag also missed `specificity` entirely.
- **A plausible pattern is not a mechanism.** "Concurrent → nothing recorded" was
  a correct observation, a plausible story and a wrong conclusion. The two-line
  experiment that distinguished them cost less than writing up the wrong one.
- **The agents never see the graph.** No provider module references `structcore`,
  `build_index`, `typegraph` or `forest`. Context is `read_inlined_context` —
  raw file bytes, nothing else. All three measured hallucinations would have been
  prevented by a symbol manifest costing **6,479 characters** for the whole
  `daedalus/` package (114 for `gui/`, 302 for `wiki/`). That is the cheapest
  open improvement in this document and it is the same defect class as everything
  else: built, measured, and never connected to the consumer.
