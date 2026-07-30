# SOTA survey: LLM-driven code evolution, verified against the source

Produced 2026-07-30 by a 79-agent web-grounded wave: 4 sub-questions × 2
independent search angles, then every named repo and paper checked against its
live URL by a separate agent, then synthesised.

**64 verified entries over 39 distinct projects. 35 CONFIRMED, 29
PARTLY_CONFIRMED, 0 REFUTED, 0 UNVERIFIABLE.** All metadata read 2026-07-30.

Zero entries were refuted — no researcher invented a repository — but
PARTLY_CONFIRMED almost always means *the headline held and a load-bearing
detail did not*. Those details are §2, and they are the reason this document
exists rather than a link list.

## 0. Method, and the defect it caught in itself

The first synthesis pass ran on **4 of 64 entries**. The evidence was passed into
the writer's prompt as `JSON.stringify(confirmed).slice(0, 22000)` and the array
was cut mid-record after entry four. The writer said so instead of padding, which
is the only reason it was recoverable, and the run was replayed from cache with a
map-reduce digest stage — 72 agents free, 7 paid.

Recording it because it is the same failure class the survey then found
everywhere: **a pipeline that reports on evidence it did not receive.** The fix
was not "be careful with the slice", it was to remove the truncation of evidence
entirely.

## 1. What is worth reading, ranked by what it unblocks

Ranked against ADR-015's preconditions, P1/P2 first, since that is the blocker.

| Project | URL | Licence | What to take | Moves |
|---|---|---|---|---|
| **kubernetes-sigs/agent-sandbox** | github.com/kubernetes-sigs/agent-sandbox | Apache-2.0 | The only actively developed candidate-isolation project in the survey. **v0.5.3, released 2026-07-23** — the v0.1.0 in its own install snippet is a placeholder, so anyone sizing this off the README is four minor versions behind | **P2** |
| **ShinkaEvolve** (Sakana AI) | github.com/SakanaAI/ShinkaEvolve | Apache-2.0 | The best available Grove blueprint: `shinka/database/dbase.py`. Also the only confirmed project with *configurable* isolation — `SlurmDockerJobConfig` / `SlurmCondaJobConfig` for cluster runs vs `shinka/launch/local.py` (`subprocess.Popen` + reader threads + deadline kill) locally. 1,307 stars, last push 2026-07-27 | **P8**, P2, P6, P4 |
| **funsearch** (DeepMind) | github.com/google-deepmind/funsearch | Apache-2.0 (code), CC-BY-4.0 (discovered functions) | `Sandbox.run(program, function_to_run, test_input, timeout_seconds)` shipped as a bare `NotImplementedError("Must provide a sandbox for executing untrusted code")`. DeepMind published the loop and **refused to publish it without declaring the sandbox a hard boundary.** Also `programs_database.py`: cluster key = `tuple(scores_per_test[k] for k in sorted(...))`. 1,094 stars, last commit 2024-02-05 — a frozen code drop | **P2** (as a contract), P4, P8 |
| **Darwin Gödel Machine** | github.com/jennyzzt/dgm | Apache-2.0 | A promotion boundary written as an executable predicate: `utils/evo_utils.py::is_compiled_self_improve` requires keys in `overall_performance`, at least one non-empty patch, and `total_evaluated >= num_swe_issues[0]` *"else it means that some didn't compile"*. 2,198 stars | **P7**, P8, P9 |
| **OpenEvolve** | github.com/algorithmicsuperintelligence/openevolve | Apache-2.0 | `process_parallel.py`'s timeout escalation (`config.evaluator.timeout + 30`, `terminate()` → `kill()`) and the `artifacts` side channel that feeds stderr / `build_warnings` / `llm_feedback` back into the next prompt. 6,820 stars, last push 2026-07-18. `github.com/codelion/openevolve` is the same repo renamed | P1, P4, P8 |

## 2. Where the README and the code disagree

This is the survey's real yield, and every line was read rather than inferred.

### Safety claims that are not implemented

- **`openai/human-eval`** — `exec(check_program, exec_globals)` is **LIVE on
  master** since commit 37c4dd6 (2025-01-17). The README *and* the inline comment
  both still say it is "deliberately commented out". Separately, the `setrlimit`
  memory-limit branch is **dead code**: `reliability_guard()` is called with no
  arguments. One of the most-cloned eval harnesses in the field executes model
  output while documenting the opposite.
- **`lumi-a/funsearch`** — `--sandbox-type ContainerSandbox` **does not exist at
  HEAD**. The README advertises a safety escape hatch the code no longer ships;
  the unsafe default is the only option. `ContainerSandbox` is real in upstream
  `jonppe/funsearch`, not here.
- **`aisi-sandboxing`** — not a toolkit. **Zero lines of code**, two files
  (README + PDF), and the PDF contradicts itself on level numbering.
- **`METR/task-protected-scoring`** — the separation is **per-invocation, not a
  user boundary**: official scoring runs `runuser agent --group=protected
  --login`, i.e. as the agent user. `/protected` is never chmod'd by the package.

### A working-tree reset in the reference harness

**`SWE-bench`** — three findings that matter to anyone vendoring it:

- `START_TEST_OUTPUT` / `END_TEST_OUTPUT` markers are bash no-ops
  (`: 'START_TEST_OUTPUT'`) and are visible **only because `set -x` is on**. Drop
  xtrace and grading silently returns empty.
- The `if modified_files:` / `if new_files:` guards landed **2026-03-19**
  (#518/#539). Any fork or vendored copy older than that emits a bare
  `git checkout {base_commit}` that **resets the whole working tree** — literally
  this repo's own `deletes-outside-the-worktree` defect class.
- `PARTIAL` resolution status exists in code and is computed then discarded.

### Marketing without implementation

- **`OpenEvolve`** — "Automatic Pareto optimization" is README prose: a code
  search for `pareto` returns 2 hits, both comments, and there is no
  non-dominated sorting. Default `population_size` is **1000, not 500**.
  `enable_artifacts` is a Python dataclass field, **not a YAML key** — setting it
  in YAML is silently ignored.
- **`LLM4AD`** — **EoH-S is not implemented** (README citation only; a code
  search across all ~20 branches returns zero). "100+ tasks" is inflated 1.5–4×:
  66 `evaluation.py` task modules exist. 13 method directories, not 11.
- **`CodeMonkeys`** — the "~52% majority-voting" figure **appears nowhere in the
  paper**. Majority-voting-only exists solely as an unlabelled bar in Figure 6.
- **`gigaevo-core`** — no per-stage parallelism knob; a Stage's whole
  configurable surface is `timeout`, `_partial_` and class-level `cacheable`.
- **`mutmut`** — the opposite error: `mutmut export_cicd_stats` **does** exist
  (3.6.0, PR #460, 2026-01-23) and writes `mutants/mutmut-cicd-stats.json`. The
  "parse the TUI" workaround is refuted — it is undocumented, not absent.
  `junitxml` / `html` were **removed** in the 3.x rewrite.

### Licence traps — check before borrowing a line

- **`SRank-CodeRanker`** — **not MIT.** The README claims MIT and links a LICENSE
  that does not exist on the only branch (`/license` 404, `license: null`). Treat
  as all-rights-reserved. Venue is ACL **Findings** 2024.
- **`CodeRM`** — split: the GitHub repo is **unlicensed**; only the HF model and
  dataset are Apache-2.0. The project page's CC BY-SA 4.0 does not cover the
  harness.
- **`microsoft/CodeT`** — the reverse: the licence **is** present (per-subproject
  MIT) and isolation **is** implemented. An earlier pass concluded "no licence"
  from an absent *root* LICENSE and an unopened tree — a verification correcting
  a verification.

### Benchmark numbers that mean something other than they appear to

Anyone sizing a budget or quoting a score needs these footnotes.

| Benchmark | The correction |
|---|---|
| **SWE-Lancer** | "198 tasks" is the IC-SWE family only. The shipped dataset is **463** (198 `ic_swe` + 265 `swe_manager`) — a budget off by 2.3×. Repo renamed `openai/preparedness` → `openai/frontier-evals` |
| **Aider polyglot** | Docker is **mandated** by the README, not "commonly local". The headline is `pass_rate_2` after `--tries 2` **with test errors fed back**, not zero-shot. 225 exercises are **difficulty-filtered** from 697 (kept those solved by ≤3 of 7 models) |
| **terminal-bench** | The commonly cited URL is legacy TB1.x; TB 2.0/2.1 live in *different* repos. "84.7% ± 2.1" **was not a real leaderboard entry** — top of TB 2.1 is Claude Code + Fable 5 at 83.8% ± 1.2%. Verification is trajectory audit + LM judge, not re-execution |
| **SWE-bench Pro** | **Two** leaderboards (public 731, private 276). The 858-instance held-out set has no leaderboard **by design** and is not obtainable |
| **SWE-rebench** | The headline is the **mean over 5 runs**, not best pass@1. Per-run numbers are not published. 4 of 117 rows are external harnesses, not the fixed scaffold |
| **SWE-Gym** | Lite split is **230**, not the 234 the README says |
| **SWE-smith** | Not "arbitrary GitHub repos" — transformations "rely heavily on the Python specific `ast` library". Of 26k released trajectories only ~5,016 trained the model; README and paper disagree (52k/250+/26k vs 50k/128/5,016) |
| **SWE-bench/experiments** | `logs/`, `trajs/` and `all_preds.jsonl` were **removed 2025-10-01** and offloaded to public S3; 4,027 tracked paths, none matching. The README's "you need an AWS account" is stale — the downloader uses `signature_version=UNSIGNED` |

### Ranking signals (P4)

- **`CodeJudge`** — score polarity is **inverted** from the common description:
  1.0 = clean, 0.0 = fatal. "1,140 tasks" is BigCodeBench's own size, not the
  evaluated total. The graded severity taxonomy has correlation evidence on
  **one** dataset (CoNaLa).
- **`DGM`** — `keep_better` is a **no-regression gate with 0.1 slack**
  (`score >= original - eval_noise`), not strict improvement, and the shipped
  default is `keep_all`, so quality filtering is **opt-in**. The archive coverage
  check is a floor (`<`) despite its own docstring saying "matches".
- **`science-codeevolve`** — fitness is a **single scalar** chosen by
  `fitness_key`, not a vector. `eval_time` is a MAP-Elites feature axis; runtime
  and memory are kill conditions.
- **`SWE-ReX`** — does **not** append a unique sentinel per command. Completion is
  a pexpect prompt-prefix match (`SHELLPS1PREFIX`); `_UNIQUE_STRING` is a
  hardcoded constant used only in a bashlex-failure fallback the authors
  themselves call "brittle, so we don't do this by default".

## 3. P1/P2 — options for executing candidate code, cheapest first

Ordered by cost. Each says what it buys and what it does not.

**0. Assert the provenance.** After import, check every `daedalus.*` module's
`__file__` resolves under the candidate root; fail the *evaluation* if not.
OpenEvolve shows how easily this goes wrong: `evaluator.py` does
`sys.path.insert(0, eval_dir)`, and anything earlier on `sys.path` wins the import
silently. Cross-platform, no dependency. **Built 2026-07-30 as
`daedalus/eval/provenance.py`.** Buys nothing for P2.

**1. Separate OS process with a deadline.** OpenEvolve's ProcessPoolExecutor with
`timeout + 30` then `terminate()` → `kill()`; ShinkaEvolve's `Popen` with piped
logs and an `hh:mm:ss` deadline. Works on Windows today. Buys P1 properly *if*
launched with a clean cwd and a `PYTHONPATH` pointing only at the candidate.
Buys almost nothing for P2 — same user, same filesystem, inherited environment.

**2. Process-tree governor.** CodeEvolve's `ev.py`: `Popen` into a
`TemporaryDirectory`, plus a monitor thread walking
`psutil.Process.children(recursive=True)` enforcing wall-clock and memory, then
`kill_process_tree()` (`terminate()`, `wait_procs(0.5)`, `kill()` survivors).
**psutil is cross-platform, so on Windows this is an adoption, not a rewrite.**
Catches child leaks and fork bombs a single-PID kill misses. No filesystem or
network confinement.

**3. Windows Job Objects.** Composes with 1 and 2 and is the native answer for
memory caps, CPU caps, active-process limits and kill-on-handle-close. *Not
verified in this run:* the claim that `spine/containment.py` already uses them
came from the briefing, not from a read.

**4. Container per candidate.** The SWE-bench pattern (image per instance, patch
applied inside, tests run there). Strongest isolation, heaviest, and see §2 for
what its harness actually does.

## 4. What this survey did not establish

- **Nothing was refuted, which is itself a datum about the wave and not about the
  world.** An empty refuted list is evidence the researchers searched this time,
  not evidence the invented-repository failure mode is gone. This project measured
  three invented-but-plausible module names on 2026-07-30.
- **No cross-project claim about which isolation approach performs best.** The
  survey established what exists and what the code actually does. It did not
  benchmark any of it.
- **`spine/containment.py` was not read.** Every claim about this repo's existing
  Windows Job Object support is inherited from the task briefing.
- **No number here is a re-measurement.** Every figure is what a project
  publishes, dated, with its scope corrected where the scope was misstated.

## 5. The finding that matters most

The defect class is endemic. README says X, the code does Y; a safety property is
documented and absent; a marketing term has no implementation; a licence is
claimed and missing. Across 39 projects, in the reference harnesses the whole
field builds on.

This project has the same disease — the same day this survey ran, an audit here
found a byte-binding in the trust gate that was described in its own docstring as
working and was unreachable code, and a cycle detector that discarded direction.

The difference is not that Daedalus is clean. **It is that an adversarial reviewer
was pointed at it and allowed to report.** Nothing in this survey has that.
