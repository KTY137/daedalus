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

> **UPDATE, day shift, 30 July — this section is now moot.** The lab worktree
> was committed unreviewed as `a31d004` on `experiment/deepseek-lab` (MEASURED:
> `git log --all --oneline | grep a31d004` finds it). The main checkout's 104
> files landed in ~10 coherent commits, `73ad0f0`..`2b08861`. Nothing described
> above can still be lost. See the addendum (§8) for what followed.

---

## 1. Do these in this order

**1. Rescue the lab branch.** Commit in the worktree, or `git bundle` it out of
the temp directory. Order matters only in that everything else can wait and this
cannot.

> **DONE, day shift, 30 July.** Committed as `a31d004`, "wip(lab): rescue the
> deepseek-lab worktree -- UNREVIEWED", on `experiment/deepseek-lab`. Still
> unreviewed by design — durability was the only goal.

**2. Commit the main checkout.** The night's work is verified and green
(`pytest tests -q -k "deepseek or provider or offload or egress or budget"` →
456 passed; `-k "mutat or graph_delta or eval"` → 263 passed).

> **DONE, day shift, 30 July.** ~10 commits, `73ad0f0`..`2b08861` (providers,
> structcore/typegraph, wiki, eval/mutate+graph_delta, spine/loop, harness
> tools, gui, the handoff doc itself, chore). The 456/263 pass counts above are
> INHERITED from last night's entry, not re-run today.

**3. Close the Ollama gap — see §2. It is a regression I introduced tonight.**

> **DONE, day shift, 30 July**, commit `8c7bc0c`. See §2's update box.

**4. Then, and only then, the ignition.** The gate binds its receipt to HEAD, so
running it before the commits means the receipt is stale the moment they land.

> **Still true, and sharper now.** HEAD has moved twice more since this doc's
> `7a5fb07` reference point (through `8c7bc0c`, `d27c659`, to `fe634b5`
> MEASURED via `git rev-parse HEAD`). Any receipt bound to an earlier HEAD is
> stale by construction. Step 4 (§3, `--head-only`) has **not been run today** —
> still open.

---

## 2. The gap I opened tonight, and the framework question it answers

> **UPDATE, day shift, 30 July — the table below is no longer accurate.**
> Commit `8c7bc0c` built `daedalus/lanes/checks.py` (the "proposed shape,
> discussed, not built" from the box further down) and both
> `providers/deepseek.py` and `providers/ollama.py` now call the shared
> `run_checks()` — MEASURED by grep: `run_checks(` appears at
> `deepseek.py:404` and `ollama.py:1094`. `deepseek.py` keeps
> `_substitution_reason` / `_unresolved_first_party_imports` as thin
> delegating wrappers per the commit message. Both columns in the table are
> now ✓. tests/test_lanes_checks.py pins this: 29 passed (MEASURED,
> `python -m pytest tests/test_lanes_checks.py -q`, includes
> `test_lane_cannot_disable_baseline_by_construction`).

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

> **UPDATE, day shift, 30 July — this is now built,** as `8c7bc0c`, matching
> the sketch below closely (`Check = (WriteAttempt, CheckPolicy) -> refusal |
> ""`, cheapest-first, fail-closed on a raising check). `daedalus/lanes/`
> holds `checks.py`, `graph_brief.py` (see §7's update) and `__init__.py`.

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

**CONFOUNDED COMPARISON (audit 2026-07-30):** The "8 DeepSeek refuters → 0 findings"
result above rests on a confounded measurement. Today's audit (`tools/audit_swarm.py`,
committed 65e2878) found the cause: `build_prompt` prepends an instruction forbidding
chain-of-thought and appends a worked example showing `"risks": []` as empty. Every
defect worth finding is a multi-step COMPARISON, and the highest-authority message in
the request forbade the scratchpad while demonstrating the empty answer. A later
fan-out over 169 modules returned 2 findings from 715 answers for the same reason.
**Before citing this result, re-run it with `system_override` to bind a corrected
system message** (now available on `DeepSeekProvider.run`).

The AST-checks result below (3/3 destructions, 0 false positives across 336 files)
is unaffected and remains MEASURED.

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
  means the subprocess never returned. `DEFAULT_TIMEOUT_S` is 900. The suite
  duration is **MEASURED 2026-07-30 at 765.47 s (12:45), full suite idle, HEAD
  93f1ce3** — not the ~105 s previously cited. Run the gate on a quiet machine,
  or raise `--timeout`.

**DURATION — MEASURED, not inherited.** This morning (task be876lplf):
baseline green, then mutation 1 at 11:15–11:36 (21 min), mutation 2 at 11:53,
i.e. ~18 minutes per mutation. Budget **~3.6 hours for twelve** mutations, not the
two hours initially budgeted.

**CORRECTION:** Earlier this document attributed the ~18 min per mutation to a
factor-of-ten mystery — ~105 s baseline under thermal throttle. The full suite
actually runs in **765.47 s (12:45)** on this box at idle (MEASURED 2026-07-30,
HEAD 93f1ce3). The honest arithmetic is: 12m45s of tests + ~5 min sandbox
overhead per mutation = ~18 min observed. There is no factor-of-ten mystery. The
hardware *is* slow (`Intel(R) Core(TM) i7-10510U CPU @ 1.80GHz`, 4 physical
cores, 15 W laptop part) and a faster machine helps proportionally, but the
causal story was wrong. The 105 s baseline was stale (INHERITED from an earlier
handoff, no longer valid). A kill rate is comparable across machines; a duration
is not. MEASURED 2026-07-30.

**Before running the gate on any machine, use the host preflight:**

```
python -m tools.gate_host_preflight              # human report, exit 0 = fit
python -m tools.gate_host_preflight --json       # emit the host block
```

Exit 0 means every required check passed. The preflight will also report why an
optional check (tree_sitter_language_pack, lizard) is missing and how that lowers
precision — it does not fail the run. One check is the precision guard of last
resort: **UPDATED 2026-07-30** — The evolution runner uses `sys.executable, "-m",
"pytest"` with `cwd=candidate.worktree_path` (since 2026-07-29), which ensures the
candidate's code wins by sys.path ordering. Commit e822561 added
`daedalus/eval/provenance.py`, which VERIFIES this ordering before evaluation
runs (not relying on sys.path alone), and voids the evaluation (score -1.0) if
provenance fails — see `tools/gate_host_preflight.py`:0.

**The `--coverage-guided` flag is opt-in, not default.** A run reporting `0
pre-excluded by coverage` was simply not asked to exclude anything — it is not a
sign the mechanism is broken. It is a coverage-based mutant filter that only runs
if passed:

```
python -u tools/gate_discrimination.py --dry-run                     # 12/12 anchors, ~2 min
python -u tools/gate_discrimination.py --head-only                   # the real thing
python -u tools/gate_discrimination.py --head-only --coverage-guided # with filtering
```

**The receipt now carries a host block.** `write_receipt()` stamps the output of
`gate_host_preflight.collect_host()` into every receipt, binding kill rate and
duration to the machine that produced them. Fail-soft by construction: an
unavailable host block records why and the receipt still writes. A receipt that
cannot name which machine measured it invites exactly the error of comparing
durations across hosts.

### Planned offload — not yet done

The owner has a second machine with a Ryzen 9000-series X3D (desktop part, 3D
V-Cache). ESTIMATE: 5–10× on this workload (ASSUMED, not measured). Two caveats:
the GPU is irrelevant to the gate (pytest + subprocess + disk, not GPU); the
"RTX env-var drift" bug is already on the project's bug list, so the environment
must be verified with `gate_host_preflight` before a receipt is produced there.

---

## 4. Verified findings worth acting on

Confirmed by reading the code, not by an agent asserting it.

**Highest severity — VERIFIED and FIXED, day shift, 30 July, commit `fe634b5`.**
`offload._repo_snapshot` walked the repo root with `rglob`, whose skip set
missed gitignored trees. `.captures/` does exist in this checkout and does
hold captured Edge profile data. MEASURED (commit message, reproduced
independently today): 2 credential-shaped paths (`Login Data`,
`Network/Cookies`) were in the snapshot before the fix, **0 after** —
confirmed by running
`python -c "from daedalus.offload import _repo_snapshot; print(len([k for k in _repo_snapshot('.') if 'Login Data' in k or 'Cookies' in k]))"`
from the repo root, which prints `0`. Fix: `_tracked_rels()` now asks
`git ls-files --cached --others --exclude-standard` instead of walking with a
skip set; the walk survives only as a fallback for when git can't answer, with
`.captures` added to its skip set too. `tools/mutation_score.py` already
excluded `.captures`; that knowledge now also reaches the gate.

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
- `tools/agent_findings.py` (removed 2026-08-23) — new; consolidates fan-out results by target file.
- `daedalus/crew_hook.py` (replaced by daedalus/hooks/, 2026-08-23) — new; the ≥4-parallel-agents hook, registered in
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
- **A document that cites a measurement and carries no date silently becomes
  false.** Three of today's four stale claims were exactly this shape: a ~105 s
  baseline inherited without context, a confounded fan-out result cited without
  qualification, an ADR that named a measurement without dating it. Fourth
  instance: a mutation's `incident` field predicted `read_inlined_context_inverted_skip`
  would SURVIVE, citing FITNESS_SIGNAL.md 4.1; it was KILLED because
  `tests/test_inlined_context_enforcement.py` landed 2026-07-29 (d5a25d1) *after*
  that measurement. The prediction was mechanically sound; the measurement was
  stale before it was written down. This is not a theory — this is a standing bug
  in the handoff discipline: numbers need dates.
- **The agents never see the graph.** No provider module references `structcore`,
  `build_index`, `typegraph` or `forest`. Context is `read_inlined_context` —
  raw file bytes, nothing else. All three measured hallucinations would have been
  prevented by a symbol manifest costing **6,479 characters** for the whole
  `daedalus/` package (114 for `gui/`, 302 for `wiki/`). That is the cheapest
  open improvement in this document and it is the same defect class as everything
  else: built, measured, and never connected to the consumer.

---

## 8. Addendum — day shift, 30 July

New work on top of the night's, not a correction to §6, which still describes
what shipped overnight. All on `checkpoint/2026-07-20-session`, all still
ahead of origin, nothing pushed. HEAD is `fe634b5` (MEASURED,
`git rev-parse HEAD`).

1. `a31d004` — lab worktree committed unreviewed on `experiment/deepseek-lab`.
   §0 and §1 step 1 close (see update boxes above).
2. `73ad0f0`..`2b08861` (~10 commits) — the main checkout's 104 uncommitted
   files committed in coherent groups. §1 step 2 closes.
3. `8c7bc0c` — `daedalus/lanes/checks.py`, the shared write-lane baseline
   from §2's "proposed, not built" box. Both providers now call
   `run_checks()`. §1 step 3 and §2's gap close. 29/29 tests pass
   (MEASURED, `tests/test_lanes_checks.py`).
4. `8c7bc0c` also — `daedalus/lanes/graph_brief.py` connected to both
   provider write loops. §7's "cheapest open improvement" closes, with the
   scope caveat in §7's update box: no fresh fan-out re-measurement exists.
5. `d27c659` — `tests/test_graph_brief.py`, 18/18 passing (MEASURED).
6. `fe634b5` — `offload._repo_snapshot` fixed to use `git ls-files` instead
   of `rglob`. §4's highest-severity finding closes: VERIFIED and FIXED,
   0 credential-shaped paths after the fix (MEASURED, reproduced
   independently, see §4's update box).

**Still open, unchanged from last night:**

- §3, the ignition itself (`python -u tools/gate_discrimination.py
  --head-only`), has **not** been run today. HEAD has moved twice since the
  night's `7a5fb07` reference point (now `fe634b5`) — the receipt-binds-to-
  HEAD ordering note in §1 is more relevant now, not less.
- §2's `docref_gate` hardening, and any other proposal mentioned but not
  built above, stays open.
- §5 (refuted claims) is unchanged and still holds — nothing there was
  re-examined today.

> **UPDATE, day shift, 30 July — connected, commit `8c7bc0c`.**
> `daedalus/lanes/graph_brief.py` (a threefold structural brief: symbols /
> imports, with function-body-only edges marked `*` / documents) is now
> injected into both provider write loops — MEASURED by grep: `render_brief(`
> at `deepseek.py:361` and `ollama.py:775`. `tests/test_graph_brief.py`
> (added `d27c659`) passes 18/18 (MEASURED,
> `python -m pytest tests/test_graph_brief.py -q`).
>
> Scope honestly: this is a mitigation for the three specific hallucinations
> named above (`daedalus.linting`/`daedalus.gui.lint`,
> `ShiftManager`/`Shift`, `daedalus.wiki_vault`/`daedalus.wiki.vault`) and for
> the substitution failure mode in §2 — it has **not** been re-measured
> end-to-end against a fresh fan-out. There is no new held-out-detection or
> false-positive number for the brief itself; the only honest number today is
> the unit-test pass count above, not a claim about downstream hallucination
> rate.

---

## 9. Night shift follow-up — 30/31 July, nine commits landed

Nine commits, `22ffbf9..1e9d5dd`. The first five landed during the gate run on
30 July, fixing structural defects found by focused review; four more landed on
31 July (`f6c9470`, `32ddb4f`, `3088037`, `1e9d5dd`). These close work from §2
and §4 of the TODO, with measurements.

Every entry below names the commit that made it true. Numbers are stamped
**[MEASURED]** (re-run while writing this section, command given),
**[INHERITED]** (from the commit message or an earlier document, not re-run —
the source is named) or **[ASSUMED]**. The 31 July entries were re-measured at
HEAD `1e9d5dd`; the 30 July entries are inherited from the commits that wrote
them and were not re-run.

### 22ffbf9 — pytest ANSI escape bug fix (2026-07-30, 23:24)

**fix(eval): a coloured PASS was being read as never having run**

MEASURED at HEAD 7064c3b: pytest honoured FORCE_COLOR=3 (environment export), so verbose
progress lines carried ANSI escapes. The parser matched node outcomes with a regex that
assumed clean output. Every node came back `not_run` on both base and reference runs,
seed candidates were dropped as "not proof of fix", and six end-to-end tests failed.

This module decides whether a candidate fix is real. **Test suite went 74 passed / 6 failed
→ 80 passed / 22 subtests (MEASURED 2026-07-30).** Blast radius: per-node attribution only.
Promotion gate unaffected (uses returncode).

Fixed at both ends:
- argv now passes `--color=no`
- parser strips CSI escapes before matching

### 85f067a — MCP trust gate evasion fixes (2026-07-30, 23:25)

**fix(vet): a launcher can no longer hide behind the way it is spelled**

Four evasion findings, all closed. Live instance: this repo's `.mcp.json` context7 entry.

1. Remote-fetch evaders: `npx.cmd`, absolute paths, `cmd /c npx`, `uv tool run`. FIX: match
   normalized names (basename, .exe/.cmd/.bat stripped) over ALL args, not args[:1].
2. Unpinned versions: bare `npx -y pkg` was considered pinned. FIX: treat "no version", dist-tags,
   caret/tilde/wildcard as unpinned; scoped packages (leading @) stay correct.
3. Remote server URLs: unreachable from any rule. FIX: URL now reaches host check.
4. Inert allowances: rule named `net.python_http` (REVIEW, not BLOCK) was silently ignored.
   FIX: report allowances that cannot fire.

**MEASURED 2026-07-30: Tests 41 → 69 passing. 31-case evasion matrix, 0 failures.
context7 now caught by "no version" rule.**

### f0392fc — Provider report and docstring fixes (2026-07-30, 23:25)

**fix(providers): evidence survives a report the schema did not expect**

Three fixes:

1. `coerce_report` rebuilt from fixed key set, destroying unexpected keys. Example: a model
   answering under `findings` or `claims` had that evidence destroyed, returning a schema-valid
   empty report. MEASURED: ~250 answers lost in fan-out. FIX: preserve unknown keys in
   `handoff.unexpected_keys` (verified: 5000 chars survive).

2. `status` defaulted to `needs_review` with no record. MEASURED: constant across 715 answers,
   zero bits carried. FIX: new `status_was_defaulted` flag records the fact.

3. Two docstrings describing behaviour the code does not have:
   - `providers/base.py:48` said changes move to `handoff.suggestions` (false);
     line 55 writes `suggested_files` (true).
   - `fallback.py:20` said "when Claude is missing or blocked" but line 21
     handles Claude present and succeeding.

**MEASURED 2026-07-30: both docstrings corrected, unknown keys now preserved intact.**

### f54d9cb — Funnel pathspec consolidation (2026-07-30, 23:25)

**feat(funnel): one pathspec was only ever enough because nothing needed two**

Documentation and cleanup; no test surface change.

### 51fe781 — Promotion gate decision recorded (2026-07-30, 23:26)

**docs(gate0): the promotion approval has no trust root, written down as such**

Three findings:

1. **runs/audit_swarm/ deliberately retained.** Constitution §7 requires keeping negative
   experimental evidence. The 715-answer fan-out returning 2 findings is itself the learning
   (failed hypothesis: cheap model + system prompt forbidding scratchpad). Recipe digest in
   task id solved the "serve forever" problem; deletion would lose evidence.

2. **Promotion trust root decision.** Owner chose option B (GIT-SIGNED TAG) with option A
   (detached signature) as upgrade path. Regeneration VOIDS an approval.
   See docs/GATE0_SEALED_OWNER_APPROVAL.md §4-5.

3. **New open items documented in TODO §2.8:**
   - Workflow guard false positive: substring-matches in commit messages
   - Trailer format discovery: Iron-Plan (governed commits) vs Iron Plan (prose handoff)

### f6c9470 — JSON escape repair in the shared report parser (2026-07-31, 13:16)

**fix(providers): a backslash no longer costs the whole answer**

Two fixes to the one parser all three non-agentic lanes share: a lossless,
lookbehind-guarded repair for the escapes JSON forbids, recorded as
`handoff.harness_repairs`; and `coerce_report` no longer refusing an
evidence-bearing answer that omitted a summary, recorded as
`summary_was_defaulted` (both symbols verified present — `_report.py:162`,
`deepseek.py:573`).

**[MEASURED] by me, 2026-07-31, at HEAD 1e9d5dd:** 13 new regression tests in
`tests/test_providers_report.py` (counted from the commit diff — these are the
shared helpers' first in-suite coverage), and
`python3 -m pytest tests/test_providers_report.py tests/test_codex_provider.py
tests/test_deepseek_substitution_guard.py tests/test_deepseek_write_toggle.py
tests/test_ollama_native.py tests/test_ollama_rescue_reason.py -q`
→ **126 passed, 12 subtests passed in 43.11 s**. The 126 figure reproduces.

**CORRECTION — the headline fix is not the one that was doing the damage.**
The earlier version of this entry read "scan 5/100, research 8/15, review 6/6
blocked with *Invalid \escape*", attributing every block to the escape defect.
That attribution is wrong. Reading the reason out of each blocked answer in
`runs/funnel/claims123/**/*51fe781*.json` (**[MEASURED] 2026-07-31**) gives:

| tier | egress refusal | missing summary | `Invalid \escape` | blocked |
|---|---|---|---|---|
| scan | 4 | 1 | 0 | 5 of 100 |
| research | 0 | 8 | 0 | 8 of 15 |
| review | 0 | 5 | 1 | 6 of 6 |
| **total** | **4** | **14** | **1** | **19** |

So of the 15 blocks this commit could address, **14 were the missing-summary
refusal and exactly 1 was the escape defect**. The remaining 4 are
`sensitivity.py` refusing to send the file off the machine — correct behaviour,
not a defect, and they are still blocked today because they are supposed to be.

The re-run confirms the corrected reading from the other side: across 122
answers of the 3088037 re-run, `handoff.harness_repairs` fired **0 times** while
`summary_was_defaulted` fired **31 times** (28 scan, 1 research, 2 review). The
escape repair's only evidence remains its 13 unit tests — this run never
exercised it. See TODO §2.1 for the full before/after.

### 32ddb4f — the multigraph verdict and this chronicle's catch-up (2026-07-31, 13:17)

**docs: the multigraph verdict, the refined gate path, and the chronicle catch-up**

Answers the owner's question — are the data graph and the code graph the same
AST graph — in
`docs/research/MULTIGRAPH_VERDICT_AND_REFINED_GATE_PLAN_2026-07-31.md` (227
lines, new). Only the code plane is the AST projection; the type plane is a
different graph over the same source; the data plane's members often have no
AST node at all, which is why the Gate 1 ignition slice has to cross Python,
Markdown and CSV to mean anything. The knowledge plane connects by
proposed-then-verified cross-plane edges, never by node merging.

The load-bearing number in that note — **53.6% pair-adjacency under naive
merging** — is **[INHERITED]** from `forest`'s own measurement as cited in the
commit message. I did not re-run it and this document should not be read as
having confirmed it.

Docs-only otherwise: no test surface changed. The commit also retains the
claims123 funnel spec (`funnels/claims123/funnel.json`, 66 lines) and its run
artifacts deliberately, as the constitution's §7 negative-evidence rule
requires — those artifacts are what made the correction above provable.

### 3088037 — the labeled-property-graph projection (2026-07-31, 13:26)

**feat(structcore): the property-graph projection the forest already implied**

`daedalus/structcore/lpg.py` (162 lines, new): a pure, deterministic,
read-only projection of the Forest onto the labeled-property-graph model that
GQL, SQL/PGQ, Neo4j import and CPG tooling speak. Deliberately not a graph
database — a mutable store would reintroduce the partial-graph-state problem
that invariant 6 (atomic revisions) exists to close, and would drift into being
a parallel source of truth. Wired into the existing structcore CLI as `--lpg`
rather than left as an island.

Three mapping decisions carry the honesty, each regression-locked: a clone
group of N members becomes ONE reified hyperedge node plus N memberships, never
N*(N-1)/2 pairwise edges the index does not assert; an undirected edge is ONE
relationship carrying `directed=false`, not a mirrored pair that doubles every
degree count; labels are node kinds as the forest asserts them, and an unknown
kind gets no plane at all.

**[MEASURED] by me, 2026-07-31:** `python3 -m pytest tests/test_structcore_lpg.py
-q` → **11 passed in 1.22 s**. Reproduces.

**The live-fire counts do NOT reproduce, and that is correct behaviour.** The
commit records 174 files → 2,714 nodes / 114 hyperedges / 4,171 relationships.
Re-running `python3 -m daedalus.structcore daedalus --documents --types --lpg
<path>` today gave 175 files → 2,721 / 110 / 4,195, then 2,723 / 112 / 4,186
minutes later. The cause is not nondeterminism: other agents were committing to
`daedalus/` during the measurement (`spine/promotion_approval.py` untracked,
`tools/vet.py` modified, HEAD moving 3088037 → 1e9d5dd mid-run).

I checked rather than assumed. Holding the tree still and isolating the two
stages — build the index once, project it twice; then build the index twice —
gives **PROJECTION DETERMINISTIC: True** and **INDEX DETERMINISTIC: True**
(identical `forest_sha256`, node and relationship digests; **[MEASURED]**
2026-07-31, probe retained at
`C:\Users\nukei\.claude\jobs\6520e1ed\tmp\det_probe.py`). So the commit's
"digest-stable across rebuilds" claim holds.

**The calibration worth keeping: an absolute node count is not a property of
`daedalus/`, it is a property of an exact tree state.** Only `forest_sha256`
makes such a number checkable, which is precisely why the projection binds one.
Quote these counts only with the commit that produced them.

### 1e9d5dd — the fan-out no longer audits a refusal (2026-07-31, 13:37)

**fix(lanes): a refusal is no longer audited, and no longer immortal**

**This closes the two items the previous version of this section listed as
still open.** They landed at 13:37 today, after the briefing that called them
"in progress" was written — recorded here because a handoff is the most
invisible inherited context there is.

Both defects were one sentence apart in `daedalus/lanes/fanout.py` (+45 lines):

1. `ok` meant "the transport produced answers", so the claims123 review tier —
   6 of 6 units refused — reported `ok=6`. `ok` now means at least one answer
   carries evidence, and refusals are counted apart under a new `blocked` key
   in the progress line, the summary and both refusal-path summaries, so the
   three outcomes are disjoint.
2. `resume` served any persisted result with a non-empty `answers` array
   without reading what the answers said, so an all-refused unit was served
   forever and never retried. An all-blocked result is now retried; a partially
   blocked one is still served, because partial evidence is evidence.

A report that is not a dict deliberately does not count as a refusal — a
refusal that cannot be read is not one that can be proven.

**[MEASURED] by me, 2026-07-31:** `python3 -m pytest tests/test_lanes_fanout.py
-q` → **27 passed, 4 subtests passed in 30.87 s**, including the four new
regression tests. Reproduces the commit's claim exactly.

---

## 10. Receipt facts

**Receipt #1 (2026-07-30, night shift):** 12 planted, 12 killed, 0 survived,
whole-suite scope, at `fe634b58`. `host: None` (the host-stamping commit
`4524079` landed after that run started). `proven=False` because HEAD moved
before the receipt could bind.

**Receipt #2 (2026-07-30, early morning):** FAILED with `baseline_red -- baseline
pytest exit 1`. Root cause: `daedalus/atomic.py` change blinded the name-based
producer detector in `tests/test_envelope_coverage.py` — a CALIBRATION test that
correctly refused to trust its own green results rather than silently passing a
broken detection. Fixed in 65e2878 (same commit that addressed the confounded
measurement in §2).

**Receipt #3 (2026-07-30, ongoing):** Running now against `aa37c6e`.

**Operational finding:** On a 3.6-hour measurement in a productive session
(mutations taking 12–21 min each on a slow box), an equality-based freshness
check makes the receipt unattainable in principle — HEAD will move during
execution, invalidating its own binding. Three honest options:

1. Hold the machine still while the measurement finishes (impractical in a shared
   environment).
2. Move the measurement to a faster box where the 3.6-hour budget is plausible
   (not available today).
3. Change freshness semantics from equality to ancestor-with-no-relevant-diff
   (deliberately NOT done today, because its first effect would be to validate
   my own receipt against HEAD movement, which is a conflict of interest).

The third option should be revisited by someone who did not write that
measurement, and only after logging why it was considered and rejected.
