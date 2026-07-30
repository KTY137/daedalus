# Session TODO — 30 July 2026, day shift

Written to be read **without** the conversation that produced it, by a reviewer
who has never seen this repo. Every number is tagged MEASURED (reproduced today,
command given where one exists), INHERITED (from an earlier document, not
re-checked) or ASSUMED (estimate).

If you are here for a second opinion, skip to **§4 — the six questions**. That is
where an outside view is worth most; §1–§3 exist so you can judge them.

---

## 0. What this project is, in five lines

Daedalus is a multi-vendor agent harness plus an evaluation core. Three
subsystems where being wrong is expensive: **money** (`budget.py`, a hard spend
ceiling), **egress** (`sensitivity.py`, what may leave the machine), and
**measurement** (`eval/`, whether a claimed improvement is real). It is building
toward **Ariadne**, a code-evolution engine, gated behind nine written
preconditions (`docs/adrs/015-ariadne-preconditions.md`).

Scale, MEASURED: 169 tracked `daedalus/**/*.py` modules, 3.8 MB, **4,152 tests**
(`python -m pytest tests --collect-only -q`). Suite runtime **765 s** idle on the
dev box — an Intel i7-10510U, 4 physical cores, a 15 W 2019 laptop part.

---

## 1. Done today — 26 commits, do not redo

| area | what landed |
|---|---|
| **write lane** | `daedalus/lanes/checks.py` — one shared baseline (parses, not truncated, no elision, not substituted, imports resolve) called by BOTH providers. Two guards had gone into `deepseek.py` and not `ollama.py`, so the paid external lane was strictly safer than the free default one |
| **graph → prompt** | `daedalus/lanes/graph_brief.py` — the import/symbol/document layers as text, injected ahead of the question. No provider module had ever referenced `structcore` |
| **credential leak** | `offload._repo_snapshot` walked with `rglob`; `.captures/` is gitignored and holds Edge `Login Data` + `Network/Cookies`. It hashed them into `result["wrote"]`, which is labelled GROUND TRUTH and arms the test gate. Now `git ls-files`. MEASURED: 0 credential-shaped paths in the snapshot, was 2 |
| **atomic publish** | `daedalus/atomic.py` — four publishers claimed "atomic" and omitted the win32 `os.replace` retry that `killswitch` documents as MEASURED. All four have a live poller. Also fixed a FIXED `.tmp` name shared by concurrent publishers |
| **trust gate** | `vet.py` twice: a pinned allowance could not survive its own loader (the byte-binding was unreachable code, documented as working), and `mcp_spec_digest` collided on `NODE_OPTIONS=--require /tmp/evil.js`, `cwd`, and every command-less remote spec |
| **skill shadowing** | `tools/inventory.py` keyed dedup on `(name, scope)` while two skill roots share the scope label "project" — a skill could become invisible to the trust gate by picking a name |
| **cycle detection** | `structcore/cycles.py` — the package had NONE. `topology.py` uses `nx.Graph()`, an undirected projection, and direction is the only thing a cycle is made of |
| **observability** | flight recorder in `lanes/fanout.py` (what was SENT, digested) + `tools/lane_invariants.py` (7 assertions, exit 1 on blocking) |
| **gate provenance** | `tools/gate_host_preflight.py` + a `host` block in every receipt |
| **fan-out driver** | `daedalus/lanes/fanout.py` — bounded, resumable (0 paid calls on resume), refuses to run if the budget guard cannot be installed |

**THE RECEIPT — MEASURED.** `tools/gate_discrimination.py`: **12 planted, 12
killed, 0 survivors**, whole-suite gate, all four critical defect classes
(`deletes-outside-the-worktree`, `spends-money-without-a-gate`,
`sends-bytes-off-the-machine`, `reports-failure-as-success`). Bound to
`fe634b58`. HEAD has since moved; `--dry-run` confirms all 12 anchors still
apply. See §4.2.

---

## 2. Open work, ranked

### 2.1 Blocking the audit re-run
- **Delete `runs/audit_swarm/`.** The corpus is invalid (see §3.1) and `resume`
  will serve it forever. A recipe digest is now in the task id, so new runs are
  separate — but the old files should go.
- **Fire the re-run** with `TEMPERATURE=0.7`, `AUDIT_SYSTEM`, `paths=()` and the
  claim-extraction question. Built, not yet run. ~750 calls.
  `DAEDALUS_BUDGET_USD` and `DAEDALUS_BUDGET_MAX_CALLS` must BOTH be raised —
  they are independent axes and the second one is what stopped two runs.

### 2.2 Two real defects the swarm did find, both verified by hand
- `daedalus/fallback.py:20` — docstring says "when Claude is missing or blocked";
  line 21 handles `{"done", "needs_review"}` and returns `collaborative`, i.e.
  Claude present and succeeding.
- `daedalus/providers/base.py:48` — says changes move into `handoff.suggestions`;
  line 55 writes `suggested_files`. Seven lines apart. A reader of the docstring
  finds nothing, silently.

### 2.3 The safety core, from a measured false positive
- **`secret_floor_rule` fires on ordinary source.** `accelerators.py:32` is
  `RTX_TOKEN_ENV = "DAEDALUS_RTX_OLLAMA_TOKEN"` — an env var NAME — and it
  refused the module three times as "credential assigned a quoted literal value".
  The floor's own docstring says it "must NOT catch ordinary engine source".
  **Do not weaken the floor.** Make it precise, and make the refusal
  *attributable*: `handoff.offending` is `[]`, so nothing tells an operator which
  line refused.
- **A blocked unit counts as audited.** `status: "blocked"` lands in the same
  `answers` array as a real result, so the unit is `ok`, `resume` never retries
  it, and it reads as clean in every aggregate. 21 of 249 units.
- **`.captures/.../Login Data` is not caught by path.** The floor knows `.env`.
  Today's protection was structural (`git ls-files` excludes gitignored paths),
  not a check.

### 2.4 Remaining Cerberus findings on `vet.py`
- **high 4** — `npx.cmd`, `uv tool run`, `cmd /c npx` and an absolute
  `C:\...\npx.cmd` all evade the unpinned/remote-fetch rules, and a versionless
  `npx -y pkg` does not trip `mcp.unpinned`. **This repo's own `.mcp.json`
  context7 entry is an instance.** Fix: match on `Path(cmd).name` with
  `.cmd`/`.exe`/`.bat` stripped, scan all of `args` not `args[:1]`, treat
  "no version at all" and `@next|@beta|@^|@~` as unpinned.
- **med 5** — a remote server's `url` never reaches `lane_for_host`, so
  `{"type":"http","url":"https://evil.tld/mcp"}` produces zero findings.
- **med 6** — an allowance naming a non-BLOCK rule is silently inert. The live
  `.agentenv/tool-allowances.json` has one (`net.python_http`, which is REVIEW).

### 2.5 Structure (from an independent audit, numbers reproduced by a second implementation)
The 13-module strongly connected component has an **exact minimum feedback arc
set of 4**, two minimum solutions, three forced edges. Three of the four are
accidents, and each pays for itself with no reference to the cycle:
- **delete `KairosScheduler.gate_concurrent_writes`** (`scheduler.py:261`) —
  **zero callers**, and `build.py:262` + `build_exec.py:44` both describe it as
  *the* mechanism. NO TEST covers it, which is itself the finding. It is public
  API on a public class → see §4.6.
- **move `FREE_LANES`** (3 strings) out of `kairos/scheduler.py` into
  `sensitivity.py` (a true leaf) — `offload.py` imports the scheduler for three
  strings.
- **move `READ_ONLY_REPO_VERBS` + `GateResult`** to a spine leaf. Its missing
  test now exists (landed today). Also folds in `gated_writes.py:100`, a
  duplicated `900.0` gate timeout with nothing enforcing equality.
- **do NOT cut `file_bridge -> core`** — real coupling, most-tested seam, and the
  registry alternative creates a fail-open path.

### 2.6 Ariadne preconditions
- **ADR-015 Finding 1 is STALE and the ADR should say so.** It states the runner
  calls a bare `pytest` so `daedalus` resolves to the host checkout. MEASURED:
  `evolution.py:97` has used `sys.executable -m pytest` since 2026-07-29.
- **P10, proposed, not in the ADR:** the population must be DIVERSE and the
  diversity must be measured. `shadow_shell.py`/`evolution.py` contain zero
  occurrences of `temperature`, `seed`, `random`, `variation` or `diversity`; the
  only difference between two candidates is the branch name. At temperature 0 the
  N candidates are identical, so P4 ("the signal must RANK, not merely admit") is
  undefined — you cannot rank identical things. Proposed control: if all pairwise
  diffs between candidates are empty, the run must refuse to name a winner.
- **A provenance assertion exists** (`daedalus/eval/provenance.py`, landed today):
  the evaluator proves `daedalus.*` resolved under the candidate root. P2
  (evaluator outside the candidate's reach) is still open.

### 2.7 Deferred with a reason
- **Re-bind the receipt to HEAD.** Needs a quiet box, ~2.5 h at 765 s × 12. The
  right host is the owner's Ryzen 9000-series X3D box; `gate_host_preflight` must
  pass there first, and "RTX env-var drift" is already on the bug list.
- **Mutations 13 and 14** for the discrimination corpus — the write-lane
  substitution and the `.captures` leak both now have guards and neither guard is
  in the corpus. **These should not be written by whoever wrote the guards.**
- **Expedition tier 1** — ~20 external repos, import graph only, to turn every
  structural number into a percentile. `core` loses 29% of reachability on
  removal; nobody knows whether that is the 50th or 97th percentile, n=1.
- **Latent ceiling run** — design and prediction recorded in
  `docs/research/LATENT_CEILING_SHARED_REPRESENTATION.md`. Needs a quiet box.
- **`coerce_report` silently drops unknown keys** (`providers/_report.py:63-77`).
  It rebuilds from `REPORT_KEYS`, so a model returning a key you did not expect
  has its content **destroyed rather than rejected** — a valid-looking report
  with the evidence removed. This is how ~250 answers were lost today.
- **`status` is a hardcoded default.** `coerce_report` defaults it to
  `needs_review`, so it was constant across 715 answers and carries zero bits
  while every consumer reads it as a verdict.
- **`runs/spine/` is gitignored**, so the receipt cannot be committed. An
  artefact whose whole purpose is "bound to this commit" cannot say which one.
- **arch memory is stale** and the `post-commit` hook that rebuilds it ends in
  `|| true`, so it failed silently — exactly as its own comment predicts.

---

## 3. Do NOT reschedule — checked and false, or already fixed

1. **"The audit found nothing, so the code is clean."** FALSE, and the most
   expensive available misreading. See §3.1.
2. **"ADR-015 Finding 1 blocks Ariadne."** Fixed 2026-07-29.
3. **"The 13-module cycle is managed by hiding it in function-body imports."**
   REFUTED by measurement: the import-time graph over all 150 modules is **272
   edges, 0 cycles — a strict DAG**, and only **3 of 23** deferred imports are
   load-bearing. The cycle was never felt because it was never *visible*.
4. **"The suite takes 105 s."** STALE (it is in `docs/HANDOFF_2026-07-30_NIGHT.md`
   and cost hours twice). It is 765 s / 4,152 tests. The "mysterious" 18 min per
   gate mutation is simply 765 s plus overhead.
5. **"The ledger says we spent $5.85."** No. Every entry is `basis:
   worst_case`, `kind: reserve`, priced at a deliberate over-estimate of $0.05 a
   call. Real cost is ~10x lower. A ledger total is a CEILING, never an invoice.
6. **"Coverage-guided mutant selection is broken / disconnected."** No — it is
   opt-in (`--coverage-guided`) and a run reporting "0 pre-excluded by coverage"
   was simply not asked to exclude anything.

### 3.1 Why the swarm's zero is not a verdict — MEASURED

A fan-out sent all 169 modules (249 chunked units) to DeepSeek `deepseek-chat`,
3 votes each. Result: **715 usable answers, 713 "no defect found", 2 findings**
(both real, both verified by hand). The same day, on the same codebase, two
focused agents produced more than ten real findings including a blocking
security defect.

`tools/lane_invariants.py runs/audit_swarm` explains it in arithmetic:

```
units_whose_votes_are_identical            242  of 246
distinct_answer_shapes                       4
most_common_shape_share                   0.94      (692 of 736)
finding_rate                              0.0028
answers_blocked                             21      all unattributable
answers_with_flight_recorder                 0
```

Causes, in order of size — none of which is the model's capability:
1. **The system prompt forbade the mechanism.** `token_policy.STATIC_PROMPT_PREFIX`,
   prepended to every advisory call by `_report.build_prompt`, says *"Minimize
   tokens ... Prefer short summaries ... Do not include chain-of-thought; include
   only conclusions and evidence"*. Every defect worth finding is a multi-step
   comparison. The highest-authority message banned the scratchpad.
2. **The worked example demonstrated the empty answer.** `report_instructions()`
   ends with `"risks": []`. 692 of 736 answers reproduced that exact field
   pattern.
3. **The question priced silence at zero.** It supplied one verbatim output
   string — `"no defect found"` — and nothing comparable for the positive case,
   under a threat that a malformed finding would be discarded.
4. **The unit's source was sent twice.** Because tasks declared `paths`, the
   provider re-read each file and appended it truncated at 24,000 chars with no
   marker. For a chunked unit that is a DIFFERENT region of the same file under a
   contradictory label.
5. **3 votes at temperature 0.0 is one sample counted three times.**
6. **The cache key had no prompt identity**, so three harness fixes could not
   reach the 60 units they were written for.

MEASURED and worth keeping: **0 of 715 answers cited missing context**, and the
question explicitly invited it. So context was not the binding constraint.

---

## 4. The six questions — where an outside opinion is worth most

**4.1 Is the two-judge split sound?**
The plan: keep the existing deterministic project gate as an *admit* step
(binary, fail-closed, runs first), and add a **global prior** learned from
external flagship repos as a *rank* step over candidates that already passed.
Composition strictly lexicographic, never additive. The claim is that a judge
trained on foreign repos cannot be gamed by our population because our
candidates are not in its training data, which is what makes learning safe here
when a project-trained judge would co-adapt. Two constraints we think are
load-bearing: the external corpus must be structurally unreachable from the
engine evaluator (contamination firewall), and the prior must never reward
*typicality* — it flags outliers and breaks ties, because everything that makes
this repo worth building is statistically abnormal. **Is the reasoning right, and
is the lexicographic composition actually sufficient to prevent reward hacking?**

**4.2 Should the receipt's freshness test become "ancestor with no relevant diff"
instead of HEAD equality?**
The receipt binds to a commit. Six commits landed during the run, so
`proven=False`, even though `--dry-run` confirms all 12 mutation anchors still
apply at HEAD and only one mutated file changed (not at its anchor). The proposed
fix is in the handoff and predates today. **We deliberately did NOT implement it,
because the first thing it would do is validate our own receipt** — loosening a
promotion gate while being its beneficiary. Is that caution correct, or is it
superstition that costs a real 2.5 h re-run?

**4.3 Is a `--scoped` gate legitimate for a promotion-grade receipt?**
`--scoped` runs only the covering test files per mutation instead of all 4,152
tests, and the receipt records `gate_scope`. Whole-suite answers "does ANY test
catch this", which seems like the honest question for a discrimination
measurement. Scoped is ~10x cheaper. **Does scoping weaken the claim enough to
matter, given the receipt says which was used?**

**4.4 Is the claim-extraction rewrite the right fix, or is a cheap model simply
the wrong tool?**
The new prompt makes output length a function of the code, not the verdict: one
line per docstring claim with KEPT/BROKEN/UNCHECKABLE, plus four mechanical
checks, plus a rule that BROKEN requires a cited line. There is no way to say
"nothing found" because a unit with fourteen claims produces fourteen lines. The
theory is that this plays to extract-compare-tabulate and away from "decide
whether this matters". **Or should volume go to labelling (where judgment over a
diff is genuinely needed) and depth stay with a strong model, full stop?**

**4.5 Candidate diversity: temperature or strategy variation?**
Cheap: raise the decode temperature. Better, we think: vary the *approach* per
candidate ("smallest intervention first", "risk first", "testability first"), so
candidates differ in strategy rather than in noise, and a ranking over them
carries information. **Which, and is the refuse-to-name-a-winner-without-diversity
control the right shape?**

**4.6 Is deleting `KairosScheduler.gate_concurrent_writes` safe?**
Zero callers in-repo, zero tests, and two docstrings point at it as the live
mechanism (the real path is `gated_writes.run_write_wave`). It is public API on a
public class, so an out-of-repo consumer is conceivable. **Nothing would go red
if the deletion were wrong — which is itself the finding.**

---

## 5. Commands that regenerate the numbers here

```bash
python -m pytest tests --collect-only -q                  # 4,152 tests
python -m tools.gate_host_preflight                       # host fitness + identity
python -u tools/gate_discrimination.py --dry-run          # 12/12 anchors, ~2 min
python -u tools/gate_discrimination.py --head-only        # the receipt, ~2.5 h
python tools/lane_invariants.py runs/audit_swarm          # exit 1 on blocking
python tools/audit_triage.py --min-votes 2                # corroborated findings
python -m daedalus.eval.graph_delta . --held-out --count 300
python -c "from daedalus.structcore import cycle_report; import json; \
           print(json.dumps(cycle_report(repo_root='.'), indent=1))"
```

Numbers without a command in this document are marked INHERITED or ASSUMED. After
today, a number without a command is treated as no number.
