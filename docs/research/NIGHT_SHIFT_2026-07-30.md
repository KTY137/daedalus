# Night shift, 30 July 2026 — 170 external agents, one real defect

This is the record of a single overnight run in which Daedalus was pointed at
itself: 170 DeepSeek agents reading, reviewing and writing against this
repository through the harness's own external lane, under its own egress fence.

The honest one-line summary is that the **reviews produced a lot of text and one
genuinely important result, and the important result did not come from a review
at all** — it came from letting ten agents *write*, in a worktree where being
wrong was survivable, and then measuring what they actually did.

Related: [[Feature backlog]], `docs/research/EXTERNAL_FINDINGS.md` (the raw
consolidated queue), `runs/eval/deepseek*/` (every report as JSON).

---

## 1. What was run

| Wave | Agents | Model | Rights | Outcome |
|---|---|---|---|---|
| Scan + research | 40 | `deepseek-chat` | read | 40/40 completed |
| Per-module audit + cross-module + research | 100 | `deepseek-v4-pro` | read | 100/100 completed |
| Lab experiments | 10 | `deepseek-v4-pro` | **read + write** | 5 new files, 5 modified, **3 destroyed** |
| Verification cascade (round 2) | 50 | `deepseek-v4-pro` | read | 50/50 completed |
| Synthesis (round 3) | 25 | `deepseek-v4-pro` | read | 25/25 completed |
| Implementation + refutation | 20 | `deepseek-v4-pro` | **read + write** | run with the fixed write path |

Totals across the read waves: **244 reports, 1,226 claims, 1,056 distinct
clusters.** Zero lane errors in the 40-agent wave; two `IncompleteRead` failures
in the 100.

Every call went through `DeepSeekProvider.run` with the loaded policy rather
than the raw API, so the egress fence — not the script — decided what left the
machine. Read agents ran `writable=False`. Research agents were given
`paths=[]`: they were asked what they already knew, so sending source would have
been exposure purchased for nothing.

---

## 2. The result that mattered: the write lane was silently destroying files

Ten agents were given write access inside an isolated git worktree on a
throwaway branch, with its own policy naming `external_write_lanes: ["deepseek"]`.
The real checkout's policy was untouched and still names none.

Five modules came back modified. **Three of them had been destroyed.**

| File | Reported | Actually contained |
|---|---|---|
| `daedalus/arch_memory.py` | `status: done` | the test module written *for* it |
| `daedalus/shift.py` | `status: done` | the test module written *for* it |
| `daedalus/eval/mutate.py` | `status: done` | the contents of `preserve.py` |
| `daedalus/wiki/links.py` | `status: done` | correct, additive |
| `daedalus/wiki/vault.py` | `status: done` | correct, additive |

`arch_memory.py` went from 12 top-level definitions to 0 surviving. `ArchMemory`,
`build`, `save`, `load`, `render`, `render_delta` — all gone, replaced by
`test_render_delta_first_call_shows_everything`. The module no longer imports.
And the test file that was supposed to test it contained a hand-written **mock**
of the class, with the comment *"we mock the class here"* — a test that tests
its own mock and would pass with the real module deleted.

### Why nothing caught it

This was a defect in **our** code, not a model quirk. The rewrite path sends one
request per file:

```
Change request: {objective}
FILE {rel} (current contents): {original}
```

When the objective names two files — *"write tests for shift.py in
tests/test_shift.py"* — the model answered the **request** rather than the
**file**. Asked to rewrite `daedalus/shift.py`, it returned the test module.

Both existing guards were blind by construction:

- the **truncation guard** compares size, and a substituted file is a normal
  size — the test module that replaced `shift.py` was in fact **39% larger**;
- the **elision-marker guard** looks for a model admitting it omitted something,
  and nothing was omitted. A complete, valid, well-formed file arrived. It was
  simply the wrong one.

The lab's own gate was `compileall`, which passed happily: a test module is
perfectly valid Python. That gate choice is documented in the lab policy as a
deliberate trade, and this run is the evidence for exactly what a syntax-only
gate cannot see.

### The fix, and how it was validated

Two changes to `daedalus/providers/deepseek.py`:

1. **Bind the output to the path.** The target file is now named *before* the
   change request as well as after it, and the system prompt states that a
   request may mention several files while exactly one is being rewritten.
2. **A symbol-survival guard** (`_substitution_reason`). For Python files with
   at least three top-level definitions, a rewrite in which fewer than half
   survive is refused as suspected content substitution, naming what
   disappeared. It also refuses a rewrite that fails to parse when the original
   parsed.

Validated four ways:

- **12 unit tests**, including a test asserting that the substitute is *larger*
  than the original — pinning the premise that the size guard could not have
  caught this.
- **Replay against the real failure corpus**: all three destroyed files refused
  (0%, 0%, 20% survival), both legitimate additive changes allowed. **5 of 5
  correct.**
- **235 existing provider, egress and offload tests** still pass.
- **A live A/B, which is the strongest of the four.** The 20-agent wave ran
  against the same worktree with the fixed provider, and agent `i04` was given
  the *same file pair that destroyed `mutate.py`* — `[eval/mutate.py,
  eval/preserve.py]`. This time `mutate.py` came back with **100% of its
  top-level definitions intact**, and `crew_hook.py` — also written alongside its
  own test module, the pattern that destroyed `shift.py` — kept 100% and gained
  a function. The replay proves the guard classifies correctly; this proves the
  prompt fix stops the failure from happening at all.

The wrecked files are archived under `runs/eval/deepseek_lab/wrecked/` so the
corpus survives the repair.

### What this says about the design

The isolation was not ceremony. Had these ten agents run against the real
checkout with the repository's own `write_allow`, three modules would have been
destroyed while every report said `done`. The worktree, the separate policy, and
the refusal to widen `external_write_lanes` in the real repo are the reason this
is a finding rather than an incident.

---

## 3. What the read waves were actually worth

### Corroboration turned out to be unavailable

The plan was to rank findings by agreement between independent agents. Measured
on the real corpus, **the largest group of agents saying the same thing was
two** — at similarity thresholds down to 0.30, near-duplicate detection barely
merged anything.

That is not a clustering bug. It follows from the fan-out: nearly every agent was
given a different file, so there was almost no opportunity for two to agree.
The consequence is worth stating plainly — **agreement cannot rank these
findings**, and confidence has to come from checking them, not counting them.
`tools/agent_findings.py` was rebuilt around that fact and now groups by target
file, reporting cross-model agreement only for files more than one model saw.

### The cascade is what made the reviews usable

The reduction cascade (owner's idea) is the part that converted volume into
signal — but only because each stage does a *different* job. Round 2 does not
summarise round 1; it receives the claims about one file **together with that
file's source** and labels each claim against the code.

| Verdict | Count |
|---|---|
| CONFIRMED | 74 |
| REFUTED | 21 |
| UNDECIDABLE | 264 |

Of the 95 claims that could be checked against source, **22% were refuted** —
including "budget `price_call` raises `NameError`" and "`containment` leaks
handles on job-assignment failure", both false, both the kind of plausible claim
that costs a real review to dismiss. The 264 undecidable are mostly research
agents, who had no source file by design.

**REFUTED is the verdict that earns the cascade its cost.** A summarisation
chain would have compressed those 21 false claims into confident prose.

The caveat that does not go away: the verifier is the same model family as the
claimant, which is the configuration this project treats as unsafe for a *gate*.
Nothing here promotes anything. CONFIRMED means "a second look at the actual
source agreed" — better than an unchecked claim, still short of a fact.

### Confirmed findings worth acting on

Ranked by blast radius, from the 74 confirmed:

- **`spine/cancel.py`** — a race between `Popen` and registration in `_LIVE`
  means `cancel_all_managed()` can miss a running process. Separately,
  `kill_tree` swallows `OSError` and still reports `killed=True`, so a failed
  kill is indistinguishable from a successful one.
- **`memory/embeddings.py`** — migration runs without retry, risking
  `SQLITE_BUSY` on concurrent opens. *(An earlier draft of this report also
  claimed `search_report`, `ingest_report` and `record_journal_watermark` were
  promised and unimplemented. **Corrected**: `search_report` and
  `record_journal_watermark` both exist; only `ingest_report` does not. A second
  synthesist caught the error before it became scheduled work — which is the
  cascade doing its job on my own report rather than on someone else's code.)*
- **`spine/picker.py`** — high-band starvation is possible when band gaps exceed
  `BAND_SPAN`, with no escalation mechanism.
- **`loop.py`** — `os.replace` on the ledger can raise `PermissionError` on
  Windows when a concurrent reader holds the file open. `LoopLedger.save` has no
  exception handling.
- **`spine/docrefs.py`** — suffix resolution without root anchoring can bind to
  the wrong module when two share a basename.
- **`structcore/typegraph.py`** — `PlainNaming.from_rels` returns an empty canon
  dict; structural protocol matching is a flagged heuristic that can produce
  false edges.

---

---

## 3b. The second hole: invented APIs, and 0 of 26 tests passing

With the substitution defect fixed, twenty agents were given real implementation
work. They wrote seven test modules against source files they had been handed.
The result, run mechanically rather than reviewed by another model:

| | |
|---|---|
| Tests that passed | **0** |
| Tests that failed | 25 |
| Files that would not even import | 3 |

Three imported things that do not exist: `daedalus.linting` (it is
`daedalus.gui.lint`), `ShiftManager` from `daedalus.shift` (the class is
`Shift`), and `daedalus.wiki_vault` (it is `daedalus.wiki.vault`). Every one is
valid Python, so `compileall` passed them all, and every one reported
`status: done`.

This is the same failure shape as the substitution: **a syntax gate cannot tell
the difference between code and plausible-looking code.**

### The fix: static first-party import resolution

`_unresolved_first_party_imports()` parses the written file and checks that
every `daedalus.*` / `tools.*` / `tests.*` module and imported name actually
exists in the tree.

Static on purpose. Importing the file to see whether its imports resolve would
execute module-level code from an untrusted lane — the one thing this repository
refuses to do to decide whether to trust something.

Conservative on purpose, and the calibration was measured rather than guessed:

- only first-party roots are judged, because a missing third-party package is an
  environment question;
- a missing name is reported only when the module has no star-import and no
  module-level `__getattr__`, either of which can legitimately provide a name
  static reading cannot see;
- `from daedalus import shift` binds a **submodule**, which no `__init__.py`
  names. The first version of the check did not know this and fired on **40 of
  223 real files** — a rate that would have made the gate useless and trained
  everyone to ignore it.

After the fix: **4 of the 7 agent-written test files refused** (all three that
would not import, plus one importing four names `wiki/links.py` does not
define), and **0 false positives across 336 real repository files**. The three
files it allows fail on wrong *assumptions* about real behaviour, which is a
different and legitimate class — this gate is not meant to catch a bad
assertion, only an invented API.

Eight further tests pin it, including the 336-file control as an assertion.

### What this settles about the external lane

Two measurements from the same night, pointing the same way:

- it produced **five substantive new modules** that import and expose real APIs
  — `preserve.py` (370 lines), `tracer.py`, `latex.py`, `queries.py`,
  `type_ceiling.py`;
- it produced **zero working tests**.

So the lane drafts well and verifies not at all. That is exactly the division of
labour this project already assumed — the LLM is the mutation operator, the
machine is the evaluator — but it is now measured on this repository rather than
inherited from the literature. **Use the external lane to draft; never to
verify.**

---

## 3c. The third hole: `writable=True` silently removes the reporting channel

Eight agents were sent to REFUTE what the other twelve had produced. Their brief
was explicit: *"You may WRITE, but only to ADD a failing test that demonstrates a
defect you actually found. Do not rewrite the implementation — a reviewer who
edits the thing under review destroys the evidence."*

**All eight rewrote the file they were reviewing. All eight returned zero
findings.** Not one risk, not one todo, across the whole wave.

My first reading was that they had disobeyed, and that the lesson was *express a
restriction as a capability, not an instruction*. That reading was wrong, and
the real explanation is worse. From `daedalus/providers/deepseek.py`:

```python
if self._writable:
    return {... "report": self._run_rewrite(...)}      # a completely separate branch
```

and inside `_run_rewrite`, the report is built as:

```python
"summary": summary[:600],        # mechanically generated from what was written
"files_changed": changed,
"risks": [],                     # hard-coded empty
"todos": [],                     # hard-coded empty
```

The rewrite path sends the file and parses the reply for exactly one key,
`{"content": ...}`. **There is no channel through which a writable agent can
report anything at all.** The eight reviewers were not ignoring their brief;
the harness had no way for them to follow it. Whatever prose they produced was
discarded before it reached the report.

So `writable=True` is not an added capability. It is a **mode switch that
replaces the advisory path**, and the caller loses the reporting channel without
being told. A caller who wants "review this, and add a failing test if you find
something" cannot express that today: the choice is prose-with-no-writes or
writes-with-no-prose.

That invalidates the entire refutation wave — eight agents, several thousand
seconds, and no possible value — and the error was mine for designing a wave
around a flag whose behaviour I had not read.

**The one control that did hold was a capability, not an instruction.** Agent
`v08` tried to write `daedalus/budget.py` and was refused: *"protected path
(device/vendor/secret/high-risk) — an external lane may not write here."*
`high_risk_paths` did exactly its job while the prose brief did nothing, which is
the original lesson intact — just demonstrated by the part that worked rather
than the part that failed.

The damage was contained: the substitution guard held, and `arch_memory.py` came
back at 100% symbol survival with a function added.

### The egress fence fired mid-write, correctly

Agent `i03` was asked to write `tests/test_observe_shape.py`. The fence refused
to put it on the wire: *"secret content: credential assigned a quoted literal
value"*. It was right. That file tests the promise that `observe/shape.py`
records shape and never value, so its fixture is
`{"api_key": "sk-live-do-not-leak", "host": "10.0.0.9"}` — deliberately shaped
like a credential, because that is the thing it must prove does not leak.

The consequence is worth naming: **a test that proves secrets do not leak can
never itself be edited by an external lane.** That is the correct trade and not
a defect, but it is a permanent hole in what this lane can maintain, and it will
recur for every fixture built out of realistic-looking secrets.

## 4. Two structural findings about the harness itself

### RETRACTED: "budget accounting stops under concurrency"

**This was my error, and it is worth keeping in the record rather than deleting.**

The observation was real: forty concurrent provider calls produced **zero**
entries in `runs/budget/ledger.json`, while earlier serial calls recorded
correctly. I wrote it up as a concurrency defect in `budget.py`, put it in this
report, and commissioned an agent to reproduce it.

Then I tested the mechanism instead of trusting the pattern:

| | ledger entries |
|---|---|
| provider call **without** `install_process_guard()` | 76 → **76** |
| provider call **with** `install_process_guard()` | 76 → **78** |

Nothing to do with concurrency. Budget accounting works by monkeypatching
`urllib.request.urlopen` process-wide, and the patch is installed at the product
entry points — `cli.py` and `claude_bridge.py`. My fan-out scripts constructed
`DeepSeekProvider` directly and never installed it. The serial calls that *did*
record went through the CLI.

The bug was in my scripts. It cost real, unpriced spend across roughly 170 API
calls before I noticed.

**The true finding, which is smaller and still worth having:** the ledger is
blind to any caller that constructs a provider directly, which is exactly what a
script, a test harness or a new integration naturally does. The repository
already knows this defect class — `tests/test_budget_is_installed.py` opens with
*"A guard that is not reached is not a guard, and it is worse than an absent one
because it reads as protection on the shelf."* Install-at-entry-point is a
deliberate, defensible design; the gap is that crossing the boundary is silent.

Deliberately **not** fixed tonight. `budget.py` is on `high_risk_paths`, the
design is intentional, and changing a fence module on the strength of a mistake I
had just made would be the wrong reflex. What was fixed is my own scripts.

**The method lesson is the one to keep:** a plausible pattern (`concurrent →
nothing recorded`) is not a mechanism. I had a correct observation, a plausible
story, and a wrong conclusion — and the only thing that separated them was
running the two-line experiment that could distinguish them.

### The write lane cannot touch the modules that need it most

`MAX_REWRITE_CHARS` is 24,000, and the rewrite path is whole-file only. Measured
against the tree, **107 of 149 modules fit** — but the four excluded ones are
precisely the ones with open work:

| Module | Size | Why it matters |
|---|---|---|
| `structcore/typegraph.py` | 53.1k | the type layer |
| `eval/graph_delta.py` | 28.6k | the fitness function |
| `structcore/artifacts.py` | 27.5k | the unwired data layer |
| `tools/vet.py` | 26.2k | the capability gate |

This is an argument for a patch-based write path, and independently an argument
for the distillation lane: a module too large for an external agent to rewrite is
also a module too large for a human to hold in their head.

---

## 5. What the ten lab agents produced that was real

Setting aside the three destructions, the wave did produce work worth reviewing:

- `daedalus/eval/preserve.py` (15.3k) — the semantics-preserving transformation
  generator, the **missing specificity arm** for a project with no git history.
  Without it a new project can measure detection but not false alarms. Written
  to the wrong file by its own agent, but the content exists and is under
  adversarial review in the 20-agent wave.
- `daedalus/eval/type_ceiling.py` (2.9k) — a first attempt at the type-layer
  ceiling experiment, which remains the one open question on whether the type
  graph earns its cost.
- `tests/test_wiki_vault.py`, `tests/test_wiki_links.py` — additive, correct,
  and they extend `vault.py` with refusals for drive-relative paths, unicode
  normalisation collapse and tilde segments.

None of it is merged. It sits on `experiment/deepseek-lab`, where merging is a
human `git merge` after reading the diff.

---

## 6. Method notes worth keeping

- **Generate half the targets from the tree, not from priors.** Sixty of the 100
  agents were assigned by module size, biggest first. The hand-picked forty
  audited what was already suspected; the generated sixty found `cancel.py` and
  `embeddings.py`, which nobody had thought to look at.
- **Ask a verifier to refute.** A verifier asked to confirm will. The 21
  refutations exist because round 2 was told that REFUTED is the most valuable
  verdict it can produce.
- **Give the verifier the source.** Round 2 works because it sees the file, not
  because it is a second opinion. A second opinion on a claim without the code
  is just a louder claim.
- **Measure the mechanism, not the report.** Every one of the three destroyed
  files reported `status: done`. The failure was only visible by diffing the
  worktree against the real checkout — that is, by checking the ground truth
  rather than the self-report.

---

---

## 6b. The census pipeline: 300 → 20 → 3

A second pipeline ran the same night, on the owner's design: 300 cheap agents
performing a structural census, 20 expensive agents reviewing it across files,
and 3 senior synthesists reading the result.

**Coverage was a property, not a claim.** 361 Python files were bin-packed into
exactly 300 bins — large modules alone, small ones sharing — so every file was
covered rather than the 300 largest being taken and 61 dropped silently. Output:
**3,002 symbols, 677 dependency facts, 621 stated guarantees, 155 unwired
candidates, 92 smells, 0 lane errors.**

### What the synthesis established

**The import graph is 38% invisible.** Of 526 internal non-test edges, 324 are
top-level and **202 exist only inside function bodies**. `cli.py` has 37 internal
dependencies and every one is deferred. Read only top-level imports — as most
tools do — and you see about 60% of the truth. Counting deferred imports, there
is a **13-module strongly-connected core** (`core`, `offload`, `health`,
`status`, `doctor`, `file_bridge`, `benchmark`, `kairos/scheduler`,
`kairos/gated_writes`, `spine/attempt`, `spine/bootstrap`, `spine/picker`,
`eval/correctness`). The deferral is deliberate and load-bearing; the consequence
is that "extract the spine" is a plan against a 13-node cycle.

**The fence is import-clean.** `sensitivity.py` imports nothing but stdlib;
`budget.py` imports only `.sensitivity`. No low-level module imports a
high-level one. Its exposure is process scope, not layering — which independently
corroborates the retraction above: `budget.py`'s own `SPEND_SITES` register names
**eight spend-capable functions in files under `runs/`**, real Python with its
own entrypoints, living in the artefact directory outside the import graph, in
processes where `install_process_guard()` is never called. The guard installs in
exactly three places: `cli.py`, `loop.py`, `claude_bridge.py`.

**A safety precondition whose producer is not part of the system.**
`runs/spine/gate_discrimination.json` is read by `spine/bootstrap.py` and made
the auto-promotion precondition by `config.py` — and written only by
`tools/gate_discrimination.py`, a script with zero importers that nothing
invokes. The gate that decides whether the loop may promote is manual by
construction.

**Overstated guarantees, verified by reading the code.** The pattern the claims
synthesist found is worth naming: *three of the four worst gaps have the file
containing both the overstated guarantee and its own correct qualification* —
the promise at the top, the truth in a comment further down.

- `spine/bootstrap.py` — docstring says "IT NEVER WRITES THE PRIMARY CHECKOUT";
  `refresh_sources()` runs `python -m daedalus.cli map` with `cwd=repo_root` and
  rewrites `docs/architecture-state.json`. The function then verifies the write
  happened.
- `loop.py` — "There is no code path from this module to a write in `repo_root`"
  is false; the ledger defaults to `<repo_root>/runs/loop/`. Standing evidence:
  an untracked `runs/loop/` with ten files in this working tree.
- **The atomic-publish family**, which includes code I wrote last night:
  `arch_memory.save`, `shift._write_atomic`, `file_bridge._write_json_atomic` and
  `loop.LoopLedger.save` all claim atomic publish, and all omit the Windows
  `os.replace` retry that `killswitch._atomic_write` documents as MEASURED and
  `budget._store` implements. `arch_memory.save` names the exact concurrent-reader
  scenario that breaks it and then does the bare replace.
- `sensitivity.load_policy` — "a project can extend, but never weaken, the
  baseline" does not hold for `allow_exceptions`, which is project-only and
  checked *before* the deny list. The unconditional secret floor still catches
  credential shapes, so this narrows the gate rather than removing it.
- `tools/vet.py` — `vet_mcp_server` called `apply_allowances` without
  `identity=`, leaving the byte-pin I added earlier that same night inert for MCP
  servers. **Fixed**: `mcp_spec_digest()` now binds an allowance to the command,
  arguments and environment KEYS. Values are deliberately excluded so a rotated
  token does not invalidate every pinned allowance and push operators back to
  unpinned ones.

**And it refuted things, including things marked CONFIRMED elsewhere.**
`containment.JobLimits` and `worktree.remove_tree_no_follow` both exist.
`containment._log_as_hex` and `containment._verify_job_config` — one of them
carried as CONFIRMED in `EXTERNAL_FINDINGS.md` — name functions with **zero
occurrences anywhere in the repository**. Budget's fail-closed behaviour, its
Windows retry, and both cross-process locks were all verified sound.

### One more measurement about cheap models

The census flagged `spine/containment.py` and `kairos/worktree.py` for listing
names in `__all__` they do not define. I wrote my own static checker to confirm
it; mine found two *different* modules. Then I imported all four and checked:
**every name exists. Zero real defects.** The cheap model was wrong, and so was
my own check.

The defect CLASS was worth looking at; not one specific instance survived
contact with the runtime. That is the calibration to carry forward — and it is
why the census's aggregate shape is trustworthy while none of its individual
claims are.

---

## 6c. The worst finding was about my own measurements

The priorities synthesist checked the fitness work from earlier in the session
against the code, and found two things that matter more than anything the
external agents said about anyone else's modules.

### The no-go filters were never called

`daedalus/eval/mutate.py` defines `SKIP_PATH_PARTS`, `SKIP_FUNCTIONS`,
`_is_display_constant`, `_looks_like_a_guard`, `_in_main_block` and
`covered_lines`. Each appeared **exactly once in the file — its own
definition.** `generate()` applied only `trivially_equivalent`.

They were documented as built, and presented as the lever that saves tokens by
never generating a pointless mutation. They were dead code. The corpus behind
the published figure was minted without them, including mutations on `__repr__`
bodies and log strings.

**Fixed and measured:** wiring them in refuses **62 sites** on the no-go function
list and 3 inside `__main__` blocks, and the refusal counts are now published on
`generate.last_filtered` — because a filter whose effect nobody can observe is
one refactor away from being a filter nobody calls, which is the state these
were found in.

### Neither headline number had a command

`specificity`, `commit_shas` and `measure_commit` are defined *below* the
`if __name__` block, and `main()` is defined *above* them. No committed command
could reach the specificity arm at all. The held-out figure had no runner either.
Both numbers came from throwaway scripts inside a session, and nobody —
including me — could regenerate them afterwards.

This repository's own doctrine is that a measurement without provenance is not a
measurement. Two of its headline numbers failed that test, and an external audit
of its own code is what caught it.

**Fixed:** `--specificity` and `--held-out` are now branches of `main()`, each
writing evidence to `runs/eval/`.

### The corrected numbers

Re-measured on the clean arm only, by committed command, with the filters live:

| | published | reproducible |
|---|---|---|
| held-out detection | 75.3% | **95.3%** (286/300) |
| `change_constant` | 0/62 | **54/68 (79%)** |
| false alarm, real commits | 0.9% / 0.7% | **0 of 38 commits** on pure-deletion |

```
python -m daedalus.eval.graph_delta . --held-out --count 300
python -m daedalus.eval.graph_delta . --specificity --limit 40
```

Per operator, everything except `change_constant` is at 100%: `drop_argument`
80/80, `drop_call` 16/16, `early_return` 68/68, `invert_condition` 37/37,
`weaken_comparison` 31/31. The remaining blind spot is **14 constants out of 68**
that change without moving any layer — narrow, real, and worth a look.

**I am not claiming the detector improved.** The measurement changed, in two
ways at once (filters wired, and a reproducible scorer replacing an
unreconstructable one), and the gap between 0/62 and 54/68 on the same operator
is too large to explain by the filters alone. The old figure cannot be
reconciled because the script that produced it no longer exists. That is exactly
the argument for only ever trusting the number a command can regenerate — and
the reason to treat 95.3% as the first honest measurement rather than as an
improvement on 75.3%.

## 7. Open, unresolved

- The budget concurrency bug is **reproduced but not diagnosed**.
- `runs/council/room.md` remains egress-allowed because `.md` is on the allow
  list; it contains the full cross-vendor transcript. Unchanged from before this
  run, still needs a Cerberus review.
- The wiki write path stays blocked pending a named human-PUT gate list.
- The ignition is still incomplete: the loop picks, attempts and gates, but
  promotes nothing until the gate-discrimination receipt is regenerated against
  a green sandbox baseline.
- Nothing from this night is committed.
