# ABSORPTION — what to take from the open-source agent ecosystem, and what to refuse

*A survey cut down to a decision. Written 2026-07-29 against the rule set by
`docs/adrs/002-hermes-upstream.md` and `docs/adrs/017-assistant-upstream.md`:*

> **Absorb formats and ideas. Do not absorb runtimes.**

A library that brings a *format* costs a parser. A library that brings its own
loop, its own state, or its own idea of what is safe doubles the number of
places things can go wrong. ADR-002 rejected a subsystem for being "an
independent, unauthenticated WebSocket server that bypassed the scheduler and
duplicated event types." ADR-017 rejected an entire upstream for the same
shape at larger scale: **a second scheduler, a second ledger, a second safety
predicate, a second transcript store.** Neither rejection was about security or
licence. Both were about duplication.

This document sorts every candidate into exactly one of four buckets. Anything
in **DEPEND** answers all six ADR-002 bars or it does not qualify.

## Provenance of every claim

Same convention as ADR-017, for the same reason — this repo has been burned by
confident prose with no control behind it.

- **MEASURED** — a command was run on this box on 2026-07-29 and its output is
  reported.
- **FETCHED** — read off a named URL on 2026-07-29. Upstream facts age. Every
  FETCHED version string is a snapshot and **must be re-pinned before anyone
  acts on this document.**
- **INHERITED** — taken from an in-repo document (`docs/FITNESS_SIGNAL.md`,
  `docs/GATE_DISCRIMINATION.md`, `docs/adrs/016`, `docs/adrs/017`,
  `docs/archive/2026-07/HANDOFF.md`) and not independently re-verified here.

---

## 0. The environment this decision is made in

MEASURED on this box, because three of the recommendations below depend on it
and all three would be wrong on a different machine:

```text
python 3.10.11
sqlite3 library 3.40.1
  ENABLE_FTS5 ......... True   (bm25() ranking verified working)
  ENABLE_FTS4 ......... True
  load_extension ...... available
```

Third-party packages importable in this interpreter (MEASURED — note that
`pyproject.toml` declares `dependencies = []` and only two optional extras, so
several of these are present but **undeclared**):

| package | version | declared in pyproject? |
| --- | --- | --- |
| `numpy` | 1.26.4 | yes — `math` extra |
| `scipy` | 1.14.1 | yes — `math` extra |
| `networkx` | 3.3 | yes — `math` extra |
| `pyyaml` | 6.0.2 | yes — `yaml` extra |
| `tree_sitter` + `tree_sitter_language_pack` | 0.26.0 | **no** — optional at import site |
| `pydantic` | 2.13.4 | **no** — and unused (`grep`: zero imports in `daedalus/`) |
| `jsonschema` | 4.23.0 | **no** — and unused (zero imports) |
| `pytest` | 9.1.1 | test-time |
| `hypothesis`, `coverage`, `mutmut`, `cosmic_ray`, `libcst`, `opentelemetry`, `pytest-xdist` | — | absent |

**Two of these facts change answers below.** FTS5 with working `bm25()` is
already in the interpreter, which retires a "gap" ADR-017 recorded as needing an
upstream. And `pydantic`/`jsonschema` being present-but-unimported is a trap: a
library that is importable is not a library that is *declared*, and building on
one is how a zero-dependency charter silently becomes false.

## The problems this is ranked against

INHERITED, in the stated order of severity:

1. **The gate cannot discriminate.** `attempt.py` judges a candidate with
   `pytest`; measured rejection rate against the day's three known-bad changes:
   **0/3**.
2. **No trustworthy fitness signal.** `docs/FITNESS_SIGNAL.md`: F1 — the
   criterion that decides the question — is **UNMEASURED**, with a recorded
   advance prediction that mutation score will be *green* on the `worktree.py`
   repository deletion, because you cannot mutate a guard that was never written.
3. **The evaluator and its corpus are advisory.** MEASURED: `eval/harness.py`
   scores by **substring containment** (`_recall`: `m not in slice_text`;
   `_score`: case-insensitive `in`). No oracle, no tests-as-scoring. The
   docstring says so: *"ADVISORY ONLY … must never be wired to block an
   autonomous action."*
4. **Candidate code is not contained on non-win32.** MEASURED:
   `spine/containment.py::platform_supported()` returns `os.name == "nt"`; both
   `label_low_integrity` and `spawn_contained` **raise `ContainmentUnavailable`**
   off Windows. They never no-op — which is correct, and also means there is no
   boundary at all there. INHERITED (ADR-016 P1): containment is wired to
   nothing; MEASURED: `daedalus/health.py` says it in a comment —
   *"containment.py shipped with eleven measured properties and nothing at all
   called it."*
5. **Observability of a long run is thin.** MEASURED: no OpenTelemetry, no
   tracer, no spans, no `trace_id`, and **six independent hand-rolled JSONL/JSON
   run formats** with six different id schemes (`intent_id`, `run_id`,
   `council_id`, `entry_sha`, `source_hash`, bridge `epoch`) and no correlation
   id threaded between them.

**A library that fixes one of those beats five that are merely popular.** Every
bucket entry below is annotated with which problem it touches, or `—` for none.

---

## BUCKET 1 — ADOPT AS FORMAT

*A schema, file convention, or wire protocol we read and write. No process, no
socket, no dependency. Cheapest bucket and usually the right answer.*

### F1. SWE-bench `FAIL_TO_PASS` / `PASS_TO_PASS` task schema — **fixes #3, levers #1**

- **Project** `https://github.com/SWE-bench/SWE-bench` (formerly
  `princeton-nlp/SWE-bench`). **Licence** MIT. FETCHED.
- **What the format is.** Each task carries two lists of test node-ids:
  `FAIL_TO_PASS` (red before the patch, green after) and `PASS_TO_PASS` (green
  before **and** after). Resolution requires every F2P test to pass and every
  P2P test to keep passing. FETCHED.
- **Why here.** This is the exact property `eval/harness.py` lacks. A substring
  check cannot fail for a wrong-but-plausible patch; an F2P test can only pass
  if the behaviour changed, and a P2P list is a regression fence. And the repo
  **already proved this rule works, in another language**: MEASURED,
  `runs/ab/oracle_check.py` requires *the specific conformance test that covers
  the seeded rule* to go **newly** red, receipting 11 seeded / 11 caught over a
  baseline that already had 2 failing tests. Adopting the schema generalises an
  in-repo precedent under a name every reader already understands, and gives
  `eval/mint.py` — which today mints `must_include` substring labels from a diff
  — a target shape that is falsifiable.
- **Adopt the schema. Do NOT adopt the corpus.** FETCHED: OpenAI published an
  audit in February 2026 of 138 of the 500 SWE-bench Verified problems (27.6%)
  and found **59.4% had test-design flaws that reject functionally correct
  submissions**; OpenAI stopped reporting Verified scores that month. A corpus
  with a 59% flaw rate would import someone else's advisory number to replace
  ours. The *schema* is not implicated by that finding — the flawed tests were
  bad F2P sets, which is an argument for minting our own under a good schema.
- **Cost** two list fields on a minted task, plus a mint-time check that the
  F2P test is red at `minted_at_sha^`. `eval/mint.py` already runs
  `git log <minted_at_sha>^` for the backtest-clean arm in `ceiling.py`, so the
  machinery to check "red before" exists.

### F2. in-toto Attestation Framework (ITE-6) statement envelope — **fixes #5, serves ADR-007**

- **Project** `https://github.com/in-toto/attestation`, in the Linux
  Foundation / CNCF orbit; the envelope SLSA provenance is expressed in.
  **Licence** Apache-2.0. FETCHED.
- **What the format is.** `{_type, subject: [{name, digest: {sha256: …}}],
  predicateType, predicate}` — a claim, about a named artifact, pinned by digest.
  FETCHED: *"SLSA provenance is expressed as an in-toto attestation with the
  SLSA predicate type."*
- **Why here.** Every receipt this repo produces is an ad-hoc shape that
  hand-rolls the same three ideas. MEASURED: `runs/spine/gate_discrimination.json`
  carries `head` and `bootstrap.gate_discrimination()` compares it against live
  HEAD before trusting the receipt — that is a `subject.digest` check, written by
  hand. `DSSReceipt` carries `forest_sha256` + per-input `sha256` — same idea,
  third dialect. `PatchArtifact` carries `diff_sha256`. Wrapping them in one
  envelope makes "which revision is this receipt about" a structural field
  rather than a convention each receipt reinvents. `docs/adrs/007-root-of-trust.md`
  records its own status as **"Proposed; not enforced"**; this is the cheapest
  step toward it that adds no crypto and no key management.
- **Threat model** it is JSON. Adopting the envelope grants nothing and verifies
  nothing on its own — it is a *shape*, and calling a shape a guarantee would be
  exactly the `tsc --noEmit` error one level up. Signing is a separate,
  later, and optional decision (see I8).
- **Cost** a `to_statement()` helper and a test. Deletable in one commit.

### F3. OpenTelemetry GenAI semantic-convention *attribute names* — **fixes #5, partially**

- **Project** `https://github.com/open-telemetry/semantic-conventions-genai`.
  **Licence** Apache-2.0 (code) / CC-BY-4.0 (docs). FETCHED.
- **Status, and it decides the shape of this adoption.** FETCHED, as of
  **2026-07-17: no GenAI span, event, metric, or attribute is marked Stable —
  the conventions remain Development.** `gen_ai.*` content was deprecated out of
  the main semantic-conventions repo at v1.42.0 (2026-06-12) and moved to the
  dedicated repo, which **has no releases and no tags**, and whose README
  schema-URL section is still a TODO.
- **Consequence.** ADR-017 §Candidate-2 Bar 2 set the rule: *"An unpinned
  'standard' is a moving target wearing a stable name."* Adoption there was made
  conditional on pinning a tag or sha. **That condition cannot be met here** —
  there is nothing to pin. So this adoption is deliberately the weakest form
  available: **borrow the attribute names, claim no conformance, export nothing.**
- **Why it is still worth doing.** MEASURED: `council/bus.py` already records
  per turn `meta{cli_version, endpoint, started_ts, latency_ms, prompt_tokens,
  completion_tokens, cost_usd, transport}` — that is `gen_ai.usage.input_tokens`,
  `gen_ai.usage.output_tokens`, and a latency, under different spellings. Naming
  them the way the ecosystem names them makes a future exporter a **rename**
  rather than a re-instrumentation, and costs one line of documentation today.
- **What is NOT adopted** the SDK (see R9), the OTLP transport, and any claim of
  conformance. Absent a stable spec, "OTel-compatible" would be a claim we
  cannot check.

### F4. MCP tool-descriptor schema (spec revision **2026-07-28**) — **fixes nothing tonight**

- **Project** `https://modelcontextprotocol.io` / `modelcontextprotocol` org.
  **Version** the `2026-07-28` specification, released 2026-07-28. **Licence**
  MIT. FETCHED.
- **What changed and why it matters here.** FETCHED: the headline of the
  2026-07-28 revision is that **MCP is now stateless at the protocol layer**,
  plus a formal Extensions framework and a deprecation policy with ≥12 months
  between deprecation and removal. Statelessness removes one of the two standing
  objections — a stateless protocol core does not imply adopting a session
  runtime. A ≥12-month deprecation policy makes a pinned revision meaningful,
  which is more than F3 can offer.
- **What is adopted** the *tool descriptor* only: `{name, description,
  inputSchema}` where `inputSchema` is JSON Schema. `daedalus/file_bridge.py`
  already has a tool dispatch path it controls (`enqueue → watch →
  process_request → archive`); describing those tools in MCP's shape means a
  future MCP surface is a serialiser, not a rewrite.
- **What is NOT adopted, and this is the whole restriction** the client, the
  server, the transport, and any inbound instruction channel. ADR-017 Bar 5's
  argument survives the statelessness change untouched: *"Everything this repo
  has built in the safety direction is about what leaves… There is no fence here
  for what enters."* An MCP server is an inbound channel. Speaking the descriptor
  format is data; accepting instructions over a socket is a runtime.
- **Ordering** this is listed because the research was done and the answer is
  cheap. It unblocks nothing. Do not schedule it ahead of anything in §5.

### F5. Agent Skills `SKILL.md` — already decided

Accepted in ADR-017 §Candidate 2 with three conditions (pin the spec revision;
the loader executes nothing; the loader's return type carries no lane, provider
or path-policy field). Restated here for completeness only. **No new decision.**
Still not urgent; it unblocks nothing in ADR-016.

### F6. JSON Schema (draft 2020-12) as the single source of the report contract — **fixes nothing tonight, closes a live defect class**

- **Standard** `https://json-schema.org/draft/2020-12`. Not a dependency — a
  vocabulary. FETCHED.
- **Why here.** MEASURED: the `agent_report_v1` contract is currently written
  **twice**, in two dialects. `daedalus/schemas.py` has `REPORT_KEYS` plus a
  hand-written 18-line `validate_report()`. `daedalus/providers/codex_cli.py:58`
  has `REPORT_SCHEMA`, a genuine hand-written JSON Schema passed as
  `codex --output-schema`, and `providers/_openai_compat.py:90-96` sends it as
  `response_format: {type: "json_schema", strict: true}`. The two can drift, and
  **have**: `codex_cli.py` carries a comment recording a live `400
  invalid_json_schema` on 2026-07-11 that forced `handoff` to be collapsed.
- **What to do** generate the JSON Schema from the dataclass, so the two cannot
  disagree. **Do not take the `jsonschema` package to do it** — see R6.

---

## BUCKET 2 — STEAL THE IDEA

*Techniques worth reimplementing in our own idiom. Each entry names the specific
mechanism; "be inspired by X" is not a recommendation.*

### I1. Codex CLI's Windows sandbox composition — **fixes #4, on the platform that actually runs**

- **Source** OpenAI, *"Building a safe, effective sandbox to enable Codex on
  Windows"* (2026-05-14), and the accompanying engineering write-ups. FETCHED.
  Idea only; nothing is imported and no code is copied.
- **The mechanism, precisely.** FETCHED, four composed primitives:
  1. **two dedicated local users**, `CodexSandboxOffline` and
     `CodexSandboxOnline`, created at setup — *"these users only have access to
     what has been explicitly granted"*;
  2. a **restricted token** whose restricted-SID list is *"Everyone, the current
     logon session SID, and the synthetic SID"*;
  3. a **synthetic `sandbox-write` SID** with a write-allow ACE stamped onto the
     working directory and nowhere else — *"Every other path on the filesystem
     lacked that ACE"*;
  4. **Windows Firewall rules that deny all outbound traffic for
     `CodexSandboxOffline`** — *"Network control uses the firewall + user
     identity pattern rather than token capabilities"*; plus **Job Objects** for
     process-tree lifecycle.
- **Why this is the highest-value idea in the document.** MEASURED,
  `containment.py`'s own `unmeasured_vectors()` names exactly three gaps:
  `CONFIDENTIALITY: NONE` (MIC is a write-*up* barrier; a Low process reads the
  whole checkout and the user profile), `NETWORK: unrestricted`, `NAMED PIPES:
  UNMEASURED`. **MIC cannot close the first two, by construction.** A distinct
  user principal closes confidentiality with ACLs; a firewall rule scoped to that
  principal closes network. Those are the two properties ADR-016 P1/P2 name as
  blocking, and ADR-017's own reopening clause requires.
- **Half of it already exists here.** MEASURED: `spine/cancel.py` already creates
  children `CREATE_SUSPENDED`, assigns them to a Job Object with
  `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, then resumes — so there is no window to
  spawn a grandchild outside the job — and raises `CancellationUnavailable`
  rather than returning an uncancellable process. Pure ctypes, no pywin32. The
  token/ACL/firewall work lands beside a job-object backend that is already
  correct.
- **Cost** stdlib only: `ctypes` (already used in `containment.py` for
  `CreateProcessAsUserW`), `icacls` (already shelled by `label_low_integrity`),
  and `netsh advfirewall`. **Zero new dependencies.**
- **Two hazards to state before anyone builds it.** (a) Creating local users and
  firewall rules requires elevation *at setup*, which is a new privileged
  install step and must be reviewable, idempotent and reversible — it is exactly
  the kind of step ADR-017 Bar 5 objected to in `curl | bash` form. (b) A
  deny-all-outbound rule on the sandbox user does **not** stop egress through a
  *parent-process* proxy; `attempt.py:499` already declines to use containment
  partly because of parent-process git attack surface. This closes the child's
  network, not the architecture's.

### I2. Hypothesis's `RuleBasedStateMachine` invariant shape — **fixes #2's named blind spot**

- **Source** `https://github.com/HypothesisWorks/hypothesis`. FETCHED. (Taking
  the library itself is D1; the *shape* is stealable even if the dependency is
  refused.)
- **The mechanism.** Declare *rules* (operations) and *invariants*; the engine
  generates random sequences of operations, checks every invariant after each
  step, and **shrinks a failing sequence to the shortest reproducing series of
  calls.** FETCHED.
- **Why exactly this, and exactly here.** INHERITED, `docs/FITNESS_SIGNAL.md`
  §7 F1, recorded **in advance**: *"it will be green on at least the
  `worktree.py` deletion… Those defects are missing guards, and no operator can
  mutate a line that is not there."* That is a signal declaring its own blind
  spot. An invariant does not have that blind spot: *"no path outside the
  worktree root was unlinked"* is checkable after every generated operation
  sequence whether or not a guard exists to be mutated.
  INHERITED, `docs/GATE_DISCRIMINATION.md` §4: the two most severe entries in the
  corpus are `worktree_moved_checkout_unguarded` (Round 1: the primary checkout
  renamed into the worktree, **40/40 tracked files destroyed, nothing refused**)
  and `worktree_drain_skips_reachability` (Round 2: a junction renamed over an
  already-drained subdirectory redirects every remaining `rmdir` out of the tree
  — **3/3, 3000 directories removed, reported as success**). Both are sequences
  of filesystem operations with a rename in the middle. Both are exactly what a
  rule-based state machine generates.
- **Cost if reimplemented rather than depended on** the generator is easy; the
  *shrinker* is not, and an unshrunk 400-step counterexample is close to useless.
  This is the argument for D1.

### I3. Aider's tree-sitter + personalized-PageRank repo map — **fixes nothing tonight, improves #1's inputs**

- **Source** Aider (`https://github.com/Aider-AI/aider`, **Apache-2.0**), *"Building
  a better repository map with tree sitter"*. FETCHED.
- **The mechanism.** Parse each file with tree-sitter; extract `def` and `ref`
  tags; build a graph whose nodes are files and edges are references; run
  **PageRank personalized on the current query**, with edge weights multiplied
  (10× for identifiers named in the user's message); emit a token-budgeted
  summary of the top-ranked definitions. FETCHED.
- **Why here.** MEASURED: `context_plan.lexical_seed_scores` is a textbook-correct
  Okapi BM25 (`k1=1.2, b=0.75`) whose *corpus is file-path terms plus symbol
  names* — source bodies are never scanned — and which **recomputes document
  frequency on every call with no inverted index**. It is a good fuzzy file
  finder, not code search. Meanwhile `structcore/forest.py` already holds the
  reference graph, and `networkx` 3.3 is installed and already declared in the
  `math` extra and already used by `topology.py`. The personalization vector is
  the piece that is missing, and it is the piece that makes ranking respond to
  the query.
- **Boundary** steal the ranking; keep the receipt. `dss.py`'s
  restrict/prolongate/diffuse pipeline plus `DSSReceipt` (content-addressed:
  `forest_sha256`, `hierarchy_sha256`, per-input `sha256`, branch
  selected/pruned lists, per-channel digests) has **no off-the-shelf equivalent**
  and must not be traded away for a ranking improvement.

### I4. mutmut's coverage-guided mutant selection — **fixes #2's cost problem**

- **Source** `https://github.com/boxed/mutmut`, **v3.6.0**, **BSD-3-Clause**,
  released 2026-06-06, requires-python ≥3.10. FETCHED. Idea only — the package
  is refused as a dependency (R7).
- **The mechanism.** *"Can use coverage data to only do mutation testing on
  covered lines."* FETCHED. A mutant on a line no test executes is a survivor by
  construction and tells you nothing you could not have learned from coverage in
  a fraction of the time.
- **Why here.** INHERITED, `docs/FITNESS_SIGNAL.md` §5 objection 4, MEASURED not
  estimated: `sensitivity.py` = 62 mutants against 258 tests = **17.2 minutes**
  (16.6 s/mutant); `token_monitor.py` = 20 mutants = **10.8 minutes**
  (32.5 s/mutant). That is *two modules of forty-nine*. That arithmetic is what
  forces the diff-scoped form — and coverage-guided selection is what makes the
  diff-scoped form fit inside an attempt rather than beside it.
- **The stronger, cheaper move it unlocks.** Coverage answers *"does any test
  execute this changed line"* **without running a single mutant**. A diff whose
  changed lines are entirely uncovered fails diff-scoped admission immediately.
  INHERITED: the A/B arms that passed a `tsc --noEmit` gate while containing **no
  tests at all** would have been rejected by that one question. This is the
  cheapest possible floor and it is strictly upstream of mutation.

### I5. cosmic-ray's resumable session-in-a-database — **fixes #2's operability**

- **Source** `https://github.com/sixty-north/cosmic-ray`, **MIT**, latest release
  2026-04-02, requires-python ≥3.9. FETCHED. Idea only (R7).
- **The mechanism.** A mutation *session* is a database of (mutant, status) rows
  built in one pass and executed in another, so a run is resumable and
  distributable rather than all-or-nothing.
- **Why here.** MEASURED and INHERITED, `docs/GATE_DISCRIMINATION.md` §8: one
  full discrimination run is 13 invocations of `pytest -q` over ~2500 tests,
  **18m29s measured under load**, and §8.1 records that a run taken during a
  low-disk window had to be **discarded, not reported**. An all-or-nothing
  multi-hour job that must be voided wholesale is an operability defect.
- **And it unlocks the hold-back this repo says it lacks.** `GATE_DISCRIMINATION.md`
  §6 is explicit: *"A stronger version of this instrument has a second agent add
  mutants after the gate config is committed, or requires a signed hash of the
  corpus posted before the run. Neither exists yet."* A committed corpus table
  with per-row status is precisely the artifact that makes "a second agent adds
  mutants to a frozen corpus" mechanical instead of aspirational. `spine/ledger.py`
  already demonstrates the exact pattern — append-only SQLite, state derived from
  the latest event, no `UPDATE` statement anywhere in the module.

### I6. Inspect's solver/scorer split and its named sandbox provider — **fixes #3 and #4 structurally**

- **Source** `https://github.com/UKGovernmentBEIS/inspect_ai` (UK AI Security
  Institute), **MIT**. FETCHED. Idea only — refused as a dependency (R3).
- **Two mechanisms.** (a) The thing that *produces* an answer (solver) and the
  thing that *judges* it (scorer) are separate, separately swappable, and both
  named in the log. (b) The sandbox is a **named provider selected per task**,
  so "which boundary did this task run inside" is a recorded field.
- **Why here.** (a) MEASURED: `eval/harness.py` fuses production and judgement —
  `_recall` computes the substring match inline, and there is no scorer object to
  swap for a test-based one. Splitting them is the refactor that makes F1
  (adopting `FAIL_TO_PASS`) a change of scorer rather than a rewrite of the
  harness. (b) MEASURED: containment today is answered by
  `platform_supported()`, a boolean about the *platform*, and the answer appears
  in no artifact. Making it a named provider recorded on the `AttemptResult`
  turns "was this contained?" from an inference into a field — which is what a
  promotion decision has to read.

### I7. SWE-bench Pro's contamination-resistance-by-licence — **fixes #3's hold-back**

- **Source** Scale AI, SWE-Bench Pro (arXiv 2509.16941; leaderboards at
  `labs.scale.com`). FETCHED.
- **The mechanism.** The public and held-out sets are built **exclusively from
  strongly copyleft (GPL) repositories**, on the theory that the licence itself
  is a legal deterrent against inclusion in commercial training corpora — so the
  benchmark is contamination-resistant *by construction* rather than by secrecy.
  FETCHED. It works: FETCHED, the standardised leader on 2026-06-28 scores 59.1%,
  far below Verified-era numbers.
- **Why here.** MEASURED: `eval/ceiling.py` already runs a backtest-clean arm
  (`git log <minted_at_sha>^`) *alongside* a leaky full-history arm specifically
  to expose the self-prediction artifact, and measured clean 1/43 = 2.3% against
  leaky 42/43. That is the same instinct — hold-back by construction, with the
  contaminated arm reported next to it so the gap is visible. The licence trick
  is a **second, independent lever** on the same axis for any future hold-out
  corpus, and it costs nothing but a selection rule.
- **Honest limit** it is a deterrent, not a proof. Nothing verifies a model's
  training set. Treat it as raising the cost of contamination, never as
  eliminating it.

### I8. Sigstore/SLSA's "keyless identity, and absence is failure" — **serves ADR-007**

- **Source** Sigstore (Linux Foundation), SLSA v1.0 attestation model. FETCHED.
- **Two mechanisms.** (a) Signing uses **short-lived certificates tied to an
  OIDC identity** rather than a long-lived key an agent could read off disk —
  which matters on a box where the threat is a candidate process that can read
  the whole checkout (`containment.py`: `CONFIDENTIALITY: NONE`). (b) The
  consumer verifies, and a *missing* attestation is a failure, not a pass.
- **Why here.** (b) is already this repo's rule and it should be recognised as
  convergent rather than borrowed: MEASURED, `spine/bootstrap.py` treats an
  absent `runs/spine/gate_discrimination.json` as **"unproven", never "fine so
  far"**, with no override flag. (a) is the part that is genuinely new, and it is
  the honest answer to `docs/adrs/007-root-of-trust.md`'s "signed policy/evaluator
  identities" acceptance condition, currently **"Proposed; not enforced."**
- **Ordering** last in this bucket on purpose. It fixes none of the five
  problems. Do not schedule it.

---

## BUCKET 3 — DEPEND ON IT

*The expensive bucket. Three candidates qualify. Each answers all six ADR-002
bars, including the one that kills most candidates: **what does it REPLACE
here?** If it replaces nothing, it is not a dependency, it is a second system.*

---

### D1. Hypothesis — **fixes #2's named blind spot**

| Bar | Answer |
| --- | --- |
| **1. Project** | `https://github.com/HypothesisWorks/hypothesis` (`hypothesis-python`). FETCHED. |
| **2. Version** | **6.163.0**, requires-python **≥3.10** (this box: 3.10.11 ✓). Runtime deps: `sortedcontainers>=2.1,<3` and `exceptiongroup>=1.0` (only on <3.11) — **two, both pure-Python**. FETCHED from PyPI JSON. |
| **3. Licence** | **MPL-2.0.** FETCHED. File-level copyleft: the obligation attaches to modified *Hypothesis source files*. We import it, never modify it, never redistribute it → obligation nil. **Record it anyway: this is the strictest licence in this entire document**, and it is the one bar where a future decision to vendor or patch upstream would change the answer. |
| **4. What it REPLACES** | Two things, and the second is honest about being weaker. (a) It replaces the **enumerated-input** style in `tests/` and in `tools/self_test.py`'s hand-picked defect inputs, for the specific properties it is pointed at. (b) It replaces **the build we would otherwise do**: a bespoke random-sequence generator *with a shrinker*, which is the only way to attack the missing-guard class named in F1. This second half is "replaces an unmade decision, not code" — the same argument ADR-017 accepted for `SKILL.md` (Bar 4). **It is the weaker half and it is flagged as such.** A reviewer who rejects that precedent should reject D1. |
| **5. Threat model** | Stateable in full. Hypothesis executes **only strategies we write**, in-process, at test time, with no network and no subprocess. It is not in `daedalus/`'s import graph. **Two real hazards, both configuration, both interacting with measurements that already exist:** (i) it writes an **example database** (default `.hypothesis/examples`) that persists failing inputs across runs — under `HeadOnlySandbox`'s "clone committed HEAD only" this either vanishes (losing the counterexample) or leaks in from the host (making the run depend on host state), and `GATE_DISCRIMINATION.md` §8.1 exists *because* a run that depends on uncommitted host state is not a measurement. The database path must be explicit and inside the sandbox. (ii) **`derandomize=True` with a pinned seed is mandatory, not optional.** `FITNESS_SIGNAL.md` F4 is *"any mutant whose status differs between two runs… every number produced from it is noise"*, measured passing on n=10 with **zero** status disagreements. A random-by-default generator would make F4 red by construction and void §4's numbers. |
| **6. Replacement cost** | Each property is 15–30 lines. On removal, Hypothesis **prints the shrunk counterexample**, so every property degrades to `@pytest.mark.parametrize` over inputs it already found — you keep the findings and lose the search. Deletable in one commit; no data format, no on-disk state that outlives it, no upstream cadence that can break a seam. |

**Where to point it first, and why it is a measurement rather than a feature.**
`daedalus/kairos/worktree.py`, one invariant: *no path outside the worktree root
was unlinked*. That gives F1 a **second arm**: if diff-scoped mutation is green
on the reconstructed pre-fix commit (as predicted in advance) and a property test
is red on the same commit, the result is a measured statement about what each
signal covers — strictly more useful than either number alone, and it is the
experiment `FITNESS_SIGNAL.md` says has *"a cheap answer and it has not been paid
for."*

---

### D2. coverage.py — **fixes #2's cost problem, and buys #1 a floor**

| Bar | Answer |
| --- | --- |
| **1. Project** | `https://github.com/nedbat/coveragepy`. FETCHED. |
| **2. Version** | **7.15.2**, requires-python **≥3.10**. Runtime deps: **none** on this interpreter (`tomli` only for ≤3.11.0a6 *with* the `toml` extra, which we would not install). FETCHED from PyPI JSON. |
| **3. Licence** | **Apache-2.0.** FETCHED. |
| **4. What it REPLACES** | `tools/mutation_score.py`'s test-selection strategy, which is *"run the entire selection for every mutant"* — MEASURED at 16.6 s/mutant (`sensitivity.py`, 62 mutants, 17.2 min) and 32.5 s/mutant (`token_monitor.py`). Coverage replaces that with a line→test mapping, and replaces mutating-uncovered-lines with not generating them. **This is a genuine replacement of an existing strategy, not an addition** — the instrument works today and would keep working; it would stop doing the most expensive thing it does. |
| **5. Integration seam** | **Subprocess and a file. Never an import.** `python -m coverage run --rcfile=<pinned> -m pytest …` then read `coverage.json`. Nothing in `daedalus/` or `tools/` imports `coverage`. This is the same shape `pyproject.toml` already declares for its real dependencies — *"The real dependencies are external tools (Ollama, the claude CLI)"* — and the same shape `attempt.py` already uses for `git` (exactly one `subprocess.run`, asserted by a test). |
| **6. Threat model** | The tracer runs **in the same process as the tests**, so it sits inside a trust boundary the test suite already has; it adds no privilege and no network. **Two real hazards, both closable and both already patterned in this repo:** (i) coverage reads configuration from `.coveragerc` / `pyproject.toml` / `setup.cfg` **inside the tree being measured** — so a candidate patch could change how it is measured. `--rcfile` must point at a file **outside the worktree**, or the gate becomes self-measuring, which is the `tsc --noEmit` disease again. (ii) coverage ships a `.pth` hook that auto-starts tracing when `COVERAGE_PROCESS_START` is set — that variable must be popped, exactly as `attempt._git_env()` already pops `GIT_EXTERNAL_DIFF`, `GIT_SSH_COMMAND`, `GIT_CONFIG_COUNT` and nine others. The pattern for this hazard is already written in this repo; it just has to be applied. |
| **7. Replacement cost** | A `sys.monitoring` (3.12+) or `sys.settrace` hand-roll: ~150 lines, slower, and branch arithmetic is genuinely fiddly. But the honest number is smaller than that, because **removing coverage returns you to today's behaviour**, which works. This is a speed-and-scope purchase, not a correctness one. |

---

### D3. bubblewrap — **fixes #4, on a platform this box is not**

| Bar | Answer |
| --- | --- |
| **1. Project** | `https://github.com/containers/bubblewrap`. A ~50 KB binary, ~4000 lines of C, maintained in the GNOME/containers orbit; used by Flatpak, and by Claude Code's own Linux sandbox (paired with `PR_SET_NO_NEW_PRIVS` + seccomp). FETCHED. |
| **2. Version** | **0.11.2 minimum, and the minimum is load-bearing.** 0.11.0–0.11.1 carry **CVE-2026-41163** (CWE-269, **CVSS 8.7 HIGH**): in **setuid** mode the unprivileged setup phase remains ptrace-attachable, letting a local attacker drive privileged operations including overlay mounts. Patched in 0.11.2. **Install non-setuid** (unprivileged user namespaces); upstream states setuid support is deprecated and will be dropped. FETCHED. |
| **3. Licence** | **LGPL-2.0-or-later.** FETCHED. **Invoked as a separate binary via `subprocess`, never linked** → the LGPL relinking obligation does not attach. Identical in shape to `git` and `ollama`, which `pyproject.toml` already names as the real dependencies. |
| **4. What it REPLACES** | `spine/containment.py`'s posix branch, which is currently exactly one statement: `raise ContainmentUnavailable`. It is the missing half of a function whose other half already exists. It replaces nothing on win32 and must not be allowed to. |
| **5. Integration seam** | An **argv prefix** built inside `spawn_contained`, returning the same `ContainedProcess` / `ManagedProcess` object the caller already gets. No import, no daemon, no state, no scheduler, and — the bar that matters — **no second safety predicate**: what is *allowed* stays in `sensitivity.py`; bwrap only enforces a filesystem and network view that was decided elsewhere. |
| **6. Threat model** | It closes two of the three gaps `containment.py` documents about itself. Bind-mount namespaces give a **real confidentiality boundary** — closing `CONFIDENTIALITY: NONE`, which MIC cannot do at all. `--unshare-net` gives a **real network bound** — closing `NETWORK: unrestricted`. It does **not** give a syscall filter on its own; that requires `PR_SET_NO_NEW_PRIVS` + seccomp beside it, which is what Claude Code's Linux sandbox does (FETCHED). Residual, stated: kernel LPE via unprivileged user namespaces; every `--dev-bind` reintroduces a piece of the host; **Linux only — macOS gets nothing from this.** Landlock (kernel ≥5.13, ABI V3 on ≥6.2) is an in-process filesystem-allowlist fallback needing no extra binary. |
| **7. Replacement cost** | The argv builder is ~50 lines. Substitutes exist **at the same seam**: `nsjail` (Apache-2.0), `podman`/`docker` (Apache-2.0), Landlock (kernel). Multiple drop-in substitutes at one seam is what low replacement cost means. |

**Rank it honestly: this box is win32.** D3 fixes problem #4 on the platform this
repo does not currently run on, which is why it sits below I1 in §5. It becomes
first-order the moment a Linux target is real — and it is the thing that would
let ADR-017's reopening condition (ii) be answered.

---

## BUCKET 4 — REJECT

*Named, with the reason. Several of these are good projects.*

| # | Candidate | Version / licence (FETCHED) | Reason |
| --- | --- | --- | --- |
| **R1** | **Hermes Agent** (NousResearch) | v0.19.0 (2026-07-20), MIT | Already decided in ADR-017. Two schedulers, two ledgers, two safety predicates, two transcript stores; its documented boundary is the container, which does not exist on win32. |
| **R2** | **goose** (Block / LF Agentic AI Foundation) · **Letta** | Apache-2.0 · Apache-2.0 | Already decided in ADR-017. goose: a Rust toolchain and a second process into a stdlib-Python repo, plus `goose-server`'s REST **and WebSocket** API — a second network transport in the repo that deleted one. Letta: a long-lived stateful service holding a second copy of what the assistant knows, in front of the corpus `slice_egress_rule` exists to withhold. |
| **R3** | **inspect_ai** (UK AISI) | **0.3.250**, MIT, requires-python ≥3.10 | **The clearest "second everything" in this survey, and it is an excellent project.** MEASURED from its PyPI metadata: **~40 runtime dependencies**, including `fastapi`, `uvicorn`, `boto3`, `s3fs`, `pydantic`, `textual`, `tiktoken`, `httpx`, `jsonschema`, `zstandard`, `agent-client-protocol`. It brings its own task scheduler, its own sandbox abstraction, its own eval-log store, its own viewer, and its own retry/limit policy — four of which this repo already has in some form and one of which (`fastapi`+`uvicorn`) is a **web server** arriving as a transitive dependency of an evaluation library. Into a repo whose charter is `dependencies = []`. Steal I6; import nothing. |
| **R4** | **LangGraph · CrewAI · AutoGen / Microsoft Agent Framework 1.0 · OpenAI Agents SDK (0.18, Jul 2026) · PydanticAI · smolagents** | all MIT or Apache-2.0 | Every one is **a second agent loop**. MEASURED (INHERITED from ADR-017's table): `ikarus_os._chat` is single-shot and carries no history — so any of these would not duplicate the loop, it would *become* it, and bring its own tool protocol, its own state, and its own retry semantics with it. And the decisive point is the same one ADR-017 used to reject Hermes: **none of the six fixes any of the five ranked problems.** Licence is not the objection; ADR-002's shape is. |
| **R5** | **Langfuse** · **Arize Phoenix** | MIT · **Elastic License 2.0** | Langfuse: self-hosting needs **Postgres + ClickHouse + Redis + S3** — four daemons to look at a run on a local-first box — and it is a second transcript store beside `council/bus.py`, `memstore.py` and `spine/ledger.py`. Phoenix is lighter (single container, OTel-native) but is **ELv2, not OSI-approved**; that is not a licence to put under a core observability path on a private repo. Name both and move on. |
| **R6** | **`jsonschema` (4.23.0) · `pydantic` (2.13.4)** | MIT · MIT | **Fails bar 4 by a small margin, and the margin is the point.** What `jsonschema` would replace is `schemas.validate_report()` — **18 hand-written lines that work.** What it costs is `attrs` + `jsonschema-specifications` + `referencing` + `rpds-py`, the last a **compiled Rust extension**, entering a stdlib-only core. Both packages are MEASURED importable on this box and MEASURED **unimported by any file in `daedalus/`** — which is precisely the trap: building on a library that is present-but-undeclared is how `dependencies = []` becomes quietly false. **Adopt the format (F6), refuse the package.** Reopen if the schema surface grows past one report type. |
| **R7** | **mutmut (3.6.0, BSD-3-Clause)** · **cosmic-ray (MIT)** | — | As **dependencies**. mutmut pulls `click`, `coverage`, `libcst`, `pytest`, `setproctitle`, `textual`, `toml`. Both generate *syntactic* mutants. Neither can express `room_ssh_rce_reintroduced` (a shell-injection reintroduction), `worktree_drain_skips_reachability` (a junction redirecting `rmdir` out of the tree), or `free_lanes_includes_claude` (a data-side invariant) — and those sit in the four `CRITICAL_DEFECT_CLASSES` that alone decide whether `gate_discrimination()` returns `proven`. **Replacing a 740-line targeted instrument with a general one that cannot express the corpus that matters is a downgrade wearing a maintenance-saving costume.** Steal I4 and I5. |
| **R8** | **sqlite-vec** | MIT (the `sqlite-vec-client` Python wrapper; the extension is a Mozilla Builders project) | A **native C extension loaded into a sqlite3 connection** — and MEASURED, `enable_load_extension` is available on this box, so the door is genuinely open. It would load into the same process that holds `memstore.py`'s hash-chained ledger and `spine/ledger.py`'s intents. That is a new native-code-execution surface in the process that owns the tamper-evident records, bought for a **983 KB** index (MEASURED: `memory/vectors.db`) that a numpy dot product searches fast enough. **REJECT now; reopen at a measured index size where a linear numpy scan exceeds a stated latency budget** — and note that reopening means arguing the extension into the ledger's process, not just into the codebase. |
| **R9** | **OpenTelemetry Python SDK** | 1.44.0, Apache-2.0 | The *SDK* is a second in-process pipeline: providers, processors, exporters, samplers, and a shutdown ordering problem. And the conventions it would carry are **unpinnable**: FETCHED, as of 2026-07-17 nothing in `semantic-conventions-genai` is Stable, the repo has **no releases and no tags**, and its schema-URL section is a TODO. ADR-017's own condition 1 — pin a tag or a sha — **cannot be satisfied**. Take the names (F3), refuse the pipeline. Reopen when the GenAI conventions cut a versioned release. |
| **R10** | **SCIP** (Sourcegraph) · **tree-sitter-stack-graphs** | Apache-2.0 · — | **The correct long-term answer to a real weakness, refused on timing.** MEASURED: `structcore/graph.py`'s call graph is *identifier-regex name matching* with a 3-tier resolver, and `imports.py`'s non-Python tier is per-language regex — and the modules **name SCIP as the deferred correct answer themselves**. But SCIP needs a separate indexer binary per language (`scip-python`, `scip-typescript`, `scip-java`, …) plus a protobuf schema, and **Python — the one language where structcore is precise, via stdlib `ast` — is the language where an indexer would buy least.** Fixes none of the five. Reopen when a non-Python repo becomes a first-class target. |
| **R11** | **CodeQL** · **Semgrep OSS** | source-available, free **only for open source** · LGPL-2.1 | CodeQL's licence is a trap for a private local-first repo — the failure mode is a licence violation discovered late, not a technical one. Semgrep OSS is cleanly licensed but fixes no ranked problem. Neither is a fit. |
| **R12** | **MCP client / server / transport; any messaging gateway (Telegram, Discord, Slack, email)** | — | An **inbound untrusted-instruction channel**. ADR-017 Bar 5 stands unchanged: *"There is no fence here for what enters, because until now nothing entered except a human at a terminal."* The 2026-07-28 stateless core removes the *session-runtime* objection; it does not touch this one. MEASURED: `council/vendors.py` passes `--strict-mcp-config` specifically to **deny** MCP for council seats — the repo's existing posture is refusal, and this document does not overturn it. Adopt the descriptor format (F4) only. |
| **R13** | **pytest-xdist** — *for the gate* | MIT | Already refused, correctly, and the refusal is endorsed here rather than revisited. INHERITED, `GATE_DISCRIMINATION.md` §8: *"`-n auto` is not in `pytest_gate_argv`'s output and adding it would mean measuring a gate nobody runs."* **Note the boundary**: that argument is about the *gate*. A mutation sweep is not the gate, and parallelising the sweep measures nothing the gate depends on — so xdist is legitimate there and only there. |
| **R14** | **DSPy / GEPA** | `gepa-ai/gepa`, integrated as `dspy.GEPA`; arXiv 2507.19457, ICLR 2026 oral | Genuinely strong (FETCHED: +13% over MIPROv2, +20% over GRPO with 35× fewer rollouts) and genuinely the wrong purchase now: it optimises **prompts** against a metric, and this repo's problem is that **it does not have a trustworthy metric.** Optimising against `_recall`'s substring match would Goodhart the corpus at speed — `FITNESS_SIGNAL.md` §5 objection 2 describes exactly this pathology. **Reopen after F1 lands and the corpus discriminates.** Then it becomes a serious candidate. Cite, meanwhile, the sibling finding ADR-017 already records: `hermes-agent-self-evolution` states its promotion rule as *"All changes go through human review, never direct commit"* — independent corroboration that `daedalus improve` should keep having no `--apply`. |

---

## 5. The top three to do first

Ranked by *what they fix*, not by what they cost.

### 1. Steal I1 — the win32 containment upgrade, and wire it to `attempt.py`

Fixes **#4** on the platform that actually runs, which D3 does not.

`containment.py` shipped with eleven measured properties and, MEASURED, **zero
production callers** — `daedalus/health.py` says so in its own comment. ADR-016
P1 is red for that reason. And the module's `unmeasured_vectors()` names two
gaps that **MIC cannot close by construction**: `CONFIDENTIALITY: NONE` and
`NETWORK: unrestricted`. A dedicated sandbox user closes the first with ACLs; a
firewall rule scoped to that user principal closes the second. Job-object
lifecycle — the fourth piece of the Codex composition — **already exists** and is
already correct in `spine/cancel.py`.

Zero new dependencies: `ctypes` (already used there), `icacls` (already shelled
there), `netsh advfirewall`. It is also the precondition ADR-017 wrote for its
own reopening, so doing it makes a rejected decision cheap to revisit rather
than permanent.

Two things to state in the plan, not discover in the build: creating local users
and firewall rules needs **elevation at setup** (a new privileged install step —
reviewable, idempotent, reversible, or it is `curl | bash` with better manners),
and a child-scoped deny-outbound rule does not stop egress through a *parent*
process, which `attempt.py:499` already flags as the reason it declines
containment today.

### 2. Adopt F1 — `FAIL_TO_PASS` / `PASS_TO_PASS` on minted tasks

Fixes **#3** outright and is the cheapest lever available on **#1**.

MEASURED: today `harness._recall` is `m not in slice_text`. A substring check
**cannot fail** for a wrong-but-plausible patch — which is the single shape all
four documented escapes share, per `FITNESS_SIGNAL.md` §1: *"the check could not
fail."* A `FAIL_TO_PASS` test can only pass if behaviour changed. A
`PASS_TO_PASS` list is a regression fence.

The precedent is already in the tree and already receipted:
`runs/ab/oracle_check.py` requires the *specific* covering test to go **newly**
red, and its committed receipt reads **11 seeded / 11 caught / 0 survived over a
baseline with 2 pre-existing failures.** F1 generalises that from one TypeScript
conformance suite to the minted corpus, under a schema name every reader
already knows.

**Zero dependencies. Zero new runtime.** And it converts the eval from advisory
to discriminating without touching the promotion path — the corpus becomes able
to say "no" long before anything is allowed to act on it.

Adopt the schema; **do not adopt the corpus** (OpenAI's Feb-2026 audit: 59.4% of
138 sampled Verified problems carried test-design flaws).

### 3. Take D1 — Hypothesis, pointed at `kairos/worktree.py` first

Fixes **#2's named blind spot**, and does it as a *measurement* rather than a
feature.

`FITNESS_SIGNAL.md` F1 is **UNMEASURED and decisive**, and it carries a
prediction recorded in advance: mutation score will be **green** on the
`worktree.py` repository deletion, *"because you cannot mutate a guard that was
never written."* That is a signal declaring its own blind spot in writing, with
the experiment unpaid for.

A `RuleBasedStateMachine` over worktree operations with one invariant — *nothing
outside the worktree root was unlinked* — attacks exactly that class, and both
Round-1 and Round-2 deletions are sequences of filesystem operations with a
rename in the middle: precisely what such a machine generates and then
**shrinks**. Running it beside diff-scoped mutation on the same reconstructed
pre-fix commit gives F1 two arms and a real answer about coverage of the class
that has actually escaped here — twice.

**Non-negotiable configuration, or this makes things worse:** `derandomize=True`
with a pinned seed (F4 measured zero status disagreements on n=10; a
random-by-default generator would make F4 red by construction and void
`FITNESS_SIGNAL.md` §4), and an explicit example-database path inside the
sandbox (or `HeadOnlySandbox` runs start depending on host state, which is the
exact failure `GATE_DISCRIMINATION.md` §8.1 was written to prevent).

**Honourable mention, and it is genuinely close to displacing #3:** D2 +
I4's one cheap question — *does any test execute the changed line?* — costs one
coverage run, requires no mutants at all, and would have rejected the A/B arms
that passed a gate **while containing no tests whatsoever**. If the win32 work
in item #1 slips, do this instead of waiting.

---

## 6. What we should stop hand-rolling

The inverse mistake is real. Seven items, ordered by ratio of benefit to risk.
Every one has a named replacement that is **already installed or already in the
interpreter** — none of them is a new dependency argument.

1. **Brute-force vector search.** MEASURED: `memory/embeddings.py::search_report`
   selects every matching row and scores it with `_cosine` — a pure-Python
   `sum(x*y for x, y in zip(...))` over 768 float32 values unpacked one row at a
   time with `struct.unpack`. That is O(N·d) in Python floats, per query.
   `numpy` 1.26.4 is **installed and already declared** in the `math` extra. One
   `np.dot` over a float32 matrix is the same arithmetic, two orders of magnitude
   faster, with **no new dependency and no native extension in the ledger's
   process** (which is why R8 refuses sqlite-vec). Keep the identity anchor and
   the dimension-mismatch refusal — those are yours and they catch what a spec
   hash cannot.

2. **Lexical search over file *content*.** MEASURED on this box: SQLite 3.40.1
   with `ENABLE_FTS5` compiled in and `bm25()` verified working, in the **stdlib
   `sqlite3` module**. ADR-017 recorded *"long-term memory / FTS5: does not
   exist… no FTS5 anywhere in code"* as a gap an upstream would fill. **It is in
   the interpreter, free, today.** `context_plan.lexical_seed_scores` is a
   textbook-correct Okapi BM25 — and MEASURED, it recomputes document frequency
   on every call with no inverted index, over a corpus of *paths and symbol
   names only*. FTS5 gives content search with the same ranking function, an
   inverted index, and zero dependencies. (FTS5's `k1`/`b` are hard-coded at
   1.2/0.75 — identical to the constants already in `context_plan.py`.)

3. **Graph ranking and diffusion.** MEASURED: `networkx` 3.3 is installed,
   declared in the `math` extra, and already used by `structcore/topology.py`.
   Meanwhile `dss.py`'s `diffuse_relation_scores` is a hand-rolled
   personalized-PageRank / heat-diffusion variant, and `context_plan`'s ranking
   has no personalization at all. The diffusion kernel is `nx.pagerank(...,
   personalization=...)` or ~15 lines of `scipy.sparse`. **Keep the
   `DSSReceipt`** — the content-addressed provenance chain (`forest_sha256`,
   `hierarchy_sha256`, per-input digests, branch selected/pruned) has no
   off-the-shelf equivalent and is the reason this component is worth having.
   Replace the arithmetic, not the accountability.

4. **The report contract, written twice in two dialects.** MEASURED:
   `schemas.REPORT_KEYS` + an 18-line hand-written `validate_report()`, and
   separately `providers/codex_cli.py:58`'s `REPORT_SCHEMA`, a hand-written JSON
   Schema. They can drift and **have** — `codex_cli.py` carries a comment
   recording a live `400 invalid_json_schema` on 2026-07-11. Generate one from
   the other. (Not with `jsonschema` — see R6. The generation is a dict
   comprehension.)

5. **The JSON salvage path — and this is the weakest link found in this survey.**
   MEASURED: `providers/_report.py::extract_json` repairs a malformed response by
   slicing `text.find("{")` to `text.rfind("}")` and re-parsing. That is the
   entire repair strategy: it mis-slices on prose containing braces after the
   object, and handles neither fenced code blocks, trailing commas, nor
   unterminated strings. And the re-ask exists in **exactly one provider**:
   `deepseek.py:76-81` re-asks once; `ollama.py`'s **four** `coerce_report(
   extract_json(...))` call sites (lines 368, 384, 419, 599) and `codex_cli.py`'s
   one do not.
   **This is not a buy-a-library item.** `_openai_compat.py` already sends
   `response_format: {type: "json_schema", strict: true}` and `codex_cli.py`
   already passes `--output-schema`. The fix is to make the strict path
   mandatory where the provider supports it and delete the salvage — not to add
   `instructor` or `outlines` on top of a feature already being paid for.

6. **Three mutation engines.** MEASURED: `tools/self_test.py` (371 lines),
   `tools/mutation_score.py` (740), `tools/gate_discrimination.py` (789) —
   **1,900 lines** implementing seed-a-defect-and-require-a-red against three
   different oracles (`system_check.py`'s CHECKS, a test selection, and plain
   `pytest tests/`). **This is emphatically not "replace them with mutmut"** —
   see R7; the corpus of semantic defect classes is the valuable part and mutmut
   cannot express it. It is *"collapse three engines into one, keep three
   corpora."* The repo already knows this: `gate_discrimination.py` imports
   `system_check.Sandbox` and `bootstrap.CRITICAL_DEFECT_CLASSES` **rather than
   re-typing them, specifically so the two lists cannot drift apart.** That
   instinct is right and it is 30% applied.

7. **Cross-file symbol resolution for non-Python.** MEASURED:
   `structcore/graph.py`'s call graph is identifier-regex name matching against a
   stopword list, sharpened by a 3-tier resolver; `imports.py`'s non-Python tier
   is one regex per language plus a hand-rolled module→file resolver
   (Rust `mod.rs`, a JS extension ladder, Java package→dir). Both modules **name
   SCIP / stack-graphs as the correct answer in their own docstrings**, and both
   correctly drop unresolved edges rather than guessing. **Do not fix this now**
   — R10 explains why it fixes none of the five problems. The item here is
   narrower and it is a discipline, not a build: **stop treating the regex
   resolver as a thing to keep incrementally improving.** It has a precision
   ceiling that no amount of careful regex reaches, and effort spent raising it
   is effort not spent on the five.

### And the inverse list — things that look hand-rolled and must stay that way

Named explicitly, because a future reader with a refactoring urge will find
them and the argument above will look like permission.

`DSSReceipt`'s content-addressed provenance chain · the embedding **identity
anchor** (re-embeds a pinned projection and refuses at cosine drift > 1e-4 —
catching a moved `ollama` tag, a swapped host, or a requantized model, which the
spec hash provably cannot) · the **journal watermark** that refuses to move
backwards and reports `unanchored` as *unknown* rather than *fresh* · the drift
gate's dated two-tier acceptances with `MAX_HORIZON_DAYS = 90` and expiry that
resurfaces the item **with its own prose attached** · `reach.py`'s refusal to
count imports under `if False:` or inside a swallowed `ImportError` as evidence
· both **hash-chained ledgers** · `sensitivity.py` in its entirety · and
`spine/picker.py` having no `--apply`.

Nothing off the shelf does any of these. Every one of them encodes a specific
incident this repository actually had. **They are not un-absorbed ecosystem —
they are the absorption already done, correctly, and they are the reason most of
Bucket 4 is a rejection rather than a gap.**

---

## 7. What would make this document wrong

Stated in advance, so it can be checked rather than re-argued.

- **Every FETCHED version is a 2026-07-29 snapshot.** Re-pin before acting. The
  three that decide something: Hypothesis 6.163.0, coverage 7.15.2, bubblewrap
  **≥0.11.2** (below that is CVE-2026-41163, CVSS 8.7).
- **§0's measurements are about this box.** FTS5-in-stdlib is a property of this
  Python build. On an interpreter compiled without it, recommendation 6.2
  evaporates and ADR-017's "no FTS5" gap returns.
- **R9 and F3 expire on a release.** The moment
  `open-telemetry/semantic-conventions-genai` cuts a versioned release with a
  schema URL, the "unpinnable" objection dies and the SDK question deserves a
  real ADR rather than a table row.
- **R8 expires on a number.** sqlite-vec is refused at a **983 KB** index. It
  should be reopened against a measured latency budget, not a feeling.
- **D1's bar 4 is the weakest bar in this document** and it is flagged as such in
  place. It leans on ADR-017's `SKILL.md` precedent that "replaces an unmade
  decision" can satisfy bar 4. A reviewer who rejects that precedent should
  reject D1 — and should say so, because the same precedent is load-bearing for
  anything future that fills a hole rather than displacing code.
- **This document recommends no installs.** Nothing here was installed,
  vendored, or added to `pyproject.toml`. Each of D1, D2, D3 needs its own
  decision to become real; this is the argument they would have to survive, not
  a record that they did.
