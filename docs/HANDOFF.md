# Daedalus — Current Claude Handoff (2026-07-28)

This section is authoritative for the next session. The older handoffs remain
below as historical evidence; do not treat their old test counts, open items,
or architecture claims as current.

## 0. Executive state

The session converted the Antigravity synthesis into an evidence-backed
foundation and wrote the long-horizon plan for:

- **Ikarus** — the user-facing, JARVIS-like assistant;
- **Ariadne — the Daedalus Forest Evolution Engine** — the evolutionary search
  subsystem;
- **The Grove** — Ariadne's append-only Quality-Diversity archive;
- **Kairos** — mission compilation and scheduling;
- **Forge / Talos / Nemesis / Cerberus** — execution transactions, evaluator
  packs, independent verification, and policy.

`ForestEvolve` remains a useful descriptive CLI/protocol name. It is not a
second product identity.

Read these first:

1. `docs/IKARUS_ARIADNE_MASTER_PLAN.md` — version 0.2, the dependency-gated
   masterplan and definitions of done.
2. `docs/FOUNDATION_AUDIT.md` — what survived the Antigravity audit and what was
   removed as unsupported.
3. `docs/LATENT_PROJECTION_INDEX.md` — exact Latent Index v2 contract and
   migration behavior.
4. `docs/adrs/009-ariadne-forest-evolution-engine.md` — naming and role
   decision.
5. `docs/bypasses.md` — known security gaps; proposed components are not
   guarantees.

Branch/working state:

```text
branch: checkpoint/2026-07-20-session
HEAD:   f40529c
state:  large, intentionally dirty, uncommitted working tree
```

Do not reset, checkout, bulk-format, or discard this tree. It contains the
user's prior work plus the audited foundation. Split commits only after
reviewing provenance and coherent scope.

## 1. What is implemented now

### 1.1 Knowledge Forest and DSS v0

Relevant files:

```text
daedalus/structcore/forest.py
daedalus/structcore/dss.py
daedalus/context_plan.py
tests/test_forest.py
tests/test_dss.py
tests/test_context_plan.py
```

The implemented object is a versioned multiplex forest/hypergraph, not a claim
that software is literally an acyclic tree.

DSS v0 provides:

- deterministic repo/directory/file hierarchy;
- restriction and branch-bounded prolongation;
- independent import, co-change, exact-clone, near-clone, and rename channels;
- clone hyperedges retained as hyperedges;
- temporal carry only through stable IDs or explicit rename confidence;
- measured file-token costs;
- greedy token-budget packing;
- content-addressed receipts.

The hybrid planner adds path/symbol BM25 seeds plus optional, path-grounded
latent memory seeds:

```powershell
python -m daedalus.cli context "<objective>" `
  --repo-root <repo> --max-tokens 8000 --json

GET /api/context/plan?project=<name>&q=<objective>&max_tokens=8000
```

The smoke run succeeded and produced a deterministic receipt. Known UX issue:
the full JSON includes exhaustive relation-channel traces and can exceed
30 kB. Add a concise default projection plus an explicit debug/evidence mode
before feeding this directly into the UI.

### 1.2 Lossless Agent Shell transport

Relevant files:

```text
daedalus/adapters/events.py
daedalus/adapters/transport.py
daedalus/adapters/subprocess_adapter.py
tests/test_adapters.py
docs/adrs/008-universal-agent-adapter.md
```

Agent shells are translators/interfaces:

```text
native runtime input/output/tool event
  -> lossless TransportRecord
  -> optional text projection
  -> optional versioned embedding projection
```

Claude and Codex one-shot profiles are tested. Generic runtimes are
configurable. This is not hidden-state communication. Closed CLI text output
must never be described as model latent state.

### 1.3 Latent Projection Index v2

Relevant files:

```text
daedalus/memory/embeddings.py
daedalus/memory/__init__.py
tests/test_embeddings.py
docs/LATENT_PROJECTION_INDEX.md
```

Implemented:

- current Ollama `POST /api/embed` batch contract;
- injectable embedding backend;
- immutable `EmbeddingSpec` identity over provider, model, optional
  revision/digest, dimension, normalization, and projector version;
- append-only projection tables;
- v1 vectors quarantined instead of guessed/mixed;
- strict finite/dimension/zero-vector validation;
- exact project/trust/source filtering before scoring;
- explicit `ready`, `partial`, `embedder_unavailable`,
  `index_unavailable`, and invalid-response states;
- memory bridge now preserves project, repo root, trust, source, task, status,
  and explicit paths; path evidence is present in metadata and projection text;
- optional `OLLAMA_EMBED_MODEL_REVISION` pins movable Ollama tags.

Remaining P0: `append_event()` still performs embedding synchronously when
`DAEDALUS_VECTOR_INDEX=1`. Build the journal-offset/content-hash Projection
Worker from PR 2.5 in the masterplan; never make Ollama availability part of
the operational append path.

### 1.4 Accelerator capability contract

Relevant files:

```text
daedalus/accelerators.py
tests/test_accelerators.py
```

Surfaces:

```powershell
python -m daedalus.cli accelerators --json
GET /api/accelerators/status
```

The local machine exposes an MX330 (compute capability 6.1, 2 GiB). A shallow
probe does not claim CUDA readiness merely because a Python package imports.
Remote RTX Ollama remains unconfigured:

```text
DAEDALUS_RTX_OLLAMA_HOST
DAEDALUS_RTX_OLLAMA_TOKEN   # optional; always redact
```

Lane semantics are explicit:

- CUDA tensor inference: unverified until an active kernel smoke passes;
- cuVS/cuGraph/Warp/Newton: missing locally;
- Optical Flow: image/UI temporal tasks only;
- DLSS: unsupported as a general code/tensor backend;
- Newton/PhysX: domain evaluators, never general code semantics.

The user's large `D:` HDD is on the remote RTX machine, not this host. Design
that worker as compute + content-addressed artifact storage:

- RTX SSD/NVMe, if present: active scratch/workcells/index hot set;
- RTX `D:` HDD: Grove artifacts, datasets, model cache, completed workcells,
  and cold/warm archive;
- local kernel: digests, metadata, small receipts;
- missing remote volume must return `storage_unavailable`, never silently spill
  to local `C:`.

The next session needs the RTX worker's reachable endpoint, authentication
method, and actual D:-capacity/free-space probe before wiring mutations or
model downloads.

### 1.5 Safety corrections made this session

Two mathematically/security-false execution claims were closed:

1. `core._codex_report` previously granted a direct forced-Codex
   workspace-write while bypassing offload snapshot, verifier, rollback, and
   worktree execution. Forced `--lane codex` is now advisory-only until Forge.
2. Kairos previously called parallel writes “safe” when declared path strings
   were disjoint, although a writer could touch undeclared files while
   `isolate_paths` observed only declared paths. Writable attempts now run
   sequentially with whole-repo attribution. Only advisory work may overlap.

Do not overstate this fix. The system still has split execution worlds:

- legacy offload/provider paths can mutate the primary checkout;
- `_ask_claude_report` is not unified with adapters/worktrees;
- auto-routed Codex/Ollama writes are not Forge transactions;
- worktrees are not a host-security sandbox;
- no durable Mission state machine exists.

The next write-capable architecture must go through one `TaskAttempt` /
`ExecutionTransaction` service. Do not re-enable forced Codex or parallel
workspace writes as an interim shortcut.

### 1.6 Evolution status

`daedalus/kairos/evolution.py` remains a Best-of-N baseline:

- launch N candidates;
- run a fixed `pytest`;
- reject failed candidates;
- choose a green candidate.

It is not evolution at AlphaEvolve level. There is no persistent candidate
archive, lineage, parent/inspiration sampling, Quality-Diversity, frozen
external evaluator bundle, repeated benchmark statistics, or promotion root of
trust.

Ariadne is specified, not implemented. “Better than AlphaEvolve” remains a
falsifiable hypothesis requiring equal-budget, multi-seed held-out comparison.

## 2. Removed or quarantined claims

Do not restore these without an independent benchmark:

- radial projection of Euclidean embeddings called Poincaré semantics;
- weighted embedding averages called a code gradient;
- spectral partitions called conflict-free schedules;
- latent-vector interpolation treated as a decoder for discrete code patches;
- DLSS treated as an arbitrary tensor/code interpolator;
- PhysX collisions treated as merge conflicts;
- graph-layout distance used as semantic ground truth;
- candidate-authored tests used as sole correctness proof.

Sparse spectral analysis remains read-only/scoped visualization with explicit
limits. Hyperbolic geometry is allowed only as a separately trained,
hierarchy-aware experiment with Euclidean/BM25/graph baselines.

## 3. Validation evidence

Final validation on 2026-07-28:

```text
python -m pytest -q
  882 passed, 30 subtests passed in 143.34s

focused new foundation set
  67 passed in 11.43s

python -m compileall -q daedalus
  pass

npm.cmd run build  (apps/web)
  TypeScript pass
  Vite production build pass
  1,784 modules transformed in 4.58s

python -m pip wheel . --no-deps --wheel-dir runs/validation_wheels
  daedalus-0.1.0-py3-none-any.whl
  365,780 bytes
  SHA256 EE2EC874046DF7EBF3396741B1B0ED5CC24F8758D7A58D9B780807AF229200B6

git diff --check
  pass; only expected LF/CRLF warnings
```

Re-measured after the commit-hygiene pass that landed this foundation
(2026-07-28, later the same day). The `882` above is kept as recorded: it was
true when measured, before the native-Ollama layer added its tests.

```text
python -m pytest -q
  908 passed, 30 subtests passed in 114.43s

python -m compileall -q daedalus
  pass
```

Provenance: [M] measured on this box against the post-hygiene HEAD. Not
re-run in this pass: the npm build and the pip wheel — both regenerate
artifacts (`apps/web/dist`, `runs/validation_wheels/`) that are now
gitignored and deliberately kept out of history, so their numbers above are
[INHERITED] from the run that produced them.

The first full test attempt had three temporary-Git failures while C: had only
0.57 GiB free. After the user cleared Downloads, C: reached ~14.36 GiB; the
failed fixture passed 4/4 and the clean full run above passed. Treat this as
evidence for the planned storage watermark, not a flaky test.

The wheel is in `runs/validation_wheels/`. Frontend output is in
`apps/web/dist/`. The optional `python -m build` package is not installed;
`pip wheel` was used without changing the environment.

## 4. Exact next sequence

Do not add UI spectacle or new math names next. Follow the dependency gates:

### A. Commit hygiene first

1. Inspect the full dirty tree.
2. Separate pre-existing/session work from the audited foundation.
3. Run targeted tests per commit group.
4. Never squash unrelated user work into a mystery “Ariadne” commit.

### B. Movement 1 — Mission Spine

Implement:

```text
daedalus/missions/spec.py
daedalus/missions/state.py
daedalus/missions/store.py
daedalus/missions/events.py
daedalus/missions/recovery.py
```

Start with canonical `MissionSpec`, validated budgets/scope/policy digest, a
durable state machine, idempotency keys, leases/heartbeats, cancel/resume, and
crash-replay tests.

### C. Movement 2/4 — one mutation transaction

Unify adapters, legacy providers, worktrees, and offload behind:

```text
Mission -> TaskAttempt -> ExecutionTransaction
        -> TransportRecords + PatchArtifact
        -> Talos/Nemesis receipts
        -> explicit PromotionPacket
```

No provider may write the primary checkout before promotion. Compare actual
patches for integration; declared path overlap is only a scheduling hint.

### D. Projection Worker in parallel

Consume the append-only journal by file identity, byte offset, and record hash.
Retry independently, pin the Ollama model digest, retain full provenance, and
make re-projection idempotent.

### E. Then Grove + Ariadne Alpha

Only after transactions and frozen evaluators:

1. append-only `Experiment`, `Candidate`, `LineageEdge`, `InspirationEdge`,
   `EvaluationRun`, and `SelectionDecision` schemas;
2. record the current Best-of-N runner as an explicit baseline;
3. external evaluator cascade with timeouts and protected tests;
4. Parent/Novelty/Failure sampling;
5. Pareto + MAP-Elites/island baselines;
6. equal-budget, multi-seed ablations.

### F. Remote RTX worker

Register it through authenticated health/capability/storage receipts. First
jobs should be Ollama embedding batches and reranking. Later candidates:
cuVS ANN, cuGraph layout, Warp semantic kernels, and a custom TensorRT DSS
residual. DLSS remains inspiration, not a backend.

## 5. Stop conditions

Pause and report instead of improvising when:

- Forge/storage volume is unavailable;
- a model revision/dimension does not match its projection index;
- an evaluator/policy digest changes mid-experiment;
- disk drops below the configured watermark;
- a candidate requests evaluator, policy, hidden-test, or promotion writes;
- remote GPU capability is import-only and lacks an active kernel smoke;
- a “latent” feature has no named representation, adapter, baseline, and
  fallback.

---

# Historical handoff (2026-07-20 onward; retained for provenance)

# Daedalus — Session Handoff (2026-07-20, session 2)

> Provenance tags: **[M]** measured this session, uncontended · **[I]** inherited from a
> prior doc, not re-verified · **[A]** assumed/projected, no run behind it. The whole reason
> this section exists is that last session cited its own earlier numbers as fact — so every
> number below says where it came from.

## 0. Session 4 addendum (2026-07-26) — slice→offload WIRED (dark) + the context-window repair — READ FIRST

**STATE: ALL OF THIS IS UNCOMMITTED.** Working tree on `checkpoint/2026-07-20-session`
(tip still `f40529c`): modified `daedalus/offload.py`, `daedalus/providers/ollama.py`,
`daedalus/structcore/slice.py`, `tests/test_rewrite.py`, `tests/test_era1_robustness.py`;
new `daedalus/providers/_ollama_native.py`, `tests/test_ollama_native.py`,
`tests/test_offload_slice_context.py`, `tests/test_slice_include_focus.py`. The session was
STOPPED BY KAYA mid-verification — see "gate status" below before touching anything.

**The lever executed:** handoff item "(3) wire slice→offload (static-only)". It shipped —
but the scoping measurement found something bigger first:

**THE DISCOVERY THAT RESHAPED THE TASK [M, probe-verified twice with fresh unique
prompts]: the local bench head-truncated an over-budget prompt at ~2050 tokens.** Ollama
0.32.1's `/v1` OpenAI-compat shim ignores an `options` block entirely (measured:
`usage.prompt_tokens` stays 2050 with its 4096 default ctx); truncation eats the HEAD, i.e.
the system prompt with the report format and write rules dies first (proven by failed
first-word recall). Every rewrite or fat agentic tool-read that overflowed that default has
therefore been silently degraded since the bench was built — it plausibly explains part of
the historic rewrite-truncation/elision skips. Momus forced the probe matrix BEFORE build
(the A2 lesson, correctly applied): native `/api/chat` honors `options.num_ctx`, so the
native switch was REQUIRED, not gold-plating.

**CORRECTION [M, 2026-07-28]: the old “HALVING LAW” is refuted by measurement.** On the RTX
bench at `num_ctx=16384`, fresh unique ~4k- and ~14k-token prompts produced
`prompt_eval_count=3971` and `14375`, respectively, with first-word recall in both cases.
Only an over-budget prompt fell to `8194` (`num_ctx/2`) and lost first-word recall; an
over-budget prompt at `num_ctx=8192` likewise fell to `4098` and lost recall. The halving
persisted after a fresh server with machine-wide `OLLAMA_NUM_PARALLEL=1`, so parallelism is
not the cause. The usable input budget is the FULL `num_ctx` minus an explicit generation
reserve. The ~`num_ctx/2` result is an over-budget truncation penalty that eats the head, not
the normal request window. **Memory sizing remains measured and unchanged: num_ctx=16384
needs a ~3.9GB runner buffer → loads on an idle box, OOMs mid-session; 8192 OOMs at 4.3GB
free; 6144 loads under the same pressure (~20s cold). `DEFAULT_NUM_CTX=6144`**, with
`OLLAMA_NUM_CTX` available to opt up on an idle box.

**What shipped (Part A — context-window honesty, ollama lane only):**
`providers/_ollama_native.py` (stdlib native `/api/chat` client; OpenAI-shaped message
adapter — tool-call `arguments` re-serialized to JSON string, ids synthesized; a
`_native_messages` normalizer converts our adapted history BACK to native shape for
multi-round loops, or round 2 would 400). All FOUR ollama call sites switched (agentic loop
+ forced-final, rewrite, and the fallback-advisory 4th site Momus caught). Fail-loud window
rules: agentic pre-flight refusal; mid-loop EVICTION to [system, first user, last tool
result, report-now] before the forced final; rewrite reserves OUTPUT tokens
(est(original)+margin) so generation can't overflow either. `warm_model` pins with the same
num_ctx (one stable value — changing num_ctx reloads the model, ~15-45s).

**What shipped (Part B — the wire, trusted lane only, DARK by default):**
`offload._slice_context` builds gated `semantic_slice`s of the declared paths (≤3) ONLY
inside the `decision.provider == "ollama"` branch — codex/deepseek can never receive slice
text (the bootstrap's Cerberus invariant, kept). `lane="trusted"` (floor ON, default-deny
OFF). `semantic_slice` gained additive `include_focus: bool = True`; rewrite-bound tasks get
NEIGHBORHOOD-ONLY context (the prompt already carries the file body; the focus gate still
runs FIRST on the full text and fail-closes identically — invariant proven by test #3 of
`test_slice_include_focus.py`). Provenance never silent: every ollama live result carries
`result["slice_context"]` (injected/reason/per-target status/withheld/trimmed/dropped).
Fail-OPEN on build, fail-CLOSED on content. **Default `OFFLOAD_SLICE_TOKENS=0` = the wire
ships dark** — the Momus landing-gate rule.

**Live verification [M, this box, session lead ran these]:**
- WINDOW: 2.6k-token prompt (above the old 2050 cap) through the new path → full recall of
  the first word. The truncation regime is gone at the default window.
- A/B (n=1, trivial task — directional only): both arms produced the correct
  caller-compatible edit (`step=None` appended); arm B injected a 64-token neighborhood at
  zero time cost. **No lift measurable → default stays OFF.** Flip condition: an op-test A/B
  on tasks hard enough to differentiate (where neighborhood knowledge changes the edit).
- BIG-FILE HONESTY [M at the time; threshold superseded 2026-07-28]: 12k-char rewrite
  target → **0.4s loud skip** "file needs ~6426 tok but the local context window is ~3072
  tok", escalated with reason, file untouched. The fail-loud behavior was correct, but the
  ~3072 threshold came from the now-refuted halving diagnosis; current arithmetic uses the
  full `num_ctx` minus a named generation reserve.

**Gate status — READ BEFORE COMMITTING:** Momus design gate PASSED (GO-WITH-CHANGES, all
adopted). Focused suites green [M]: 21 (`test_ollama_native`) + 8 (`test_offload_slice_context`)
+ 6 (`test_slice_include_focus`) + the 389-test ollama-touching set + the 80-test slice/eval
set (incl. `test_eval`/`test_dctx` byte-identity through the default path). Two legacy test
files were retargeted to the new seam (`test_rewrite.py`, `test_era1_robustness.py` — diffs
reviewed by the session lead, intent preserved, the routing distinction now asserted from the
request shape). **BUT the session was stopped mid-verification: the post-change FULL suite
(Metron), the Nemesis live attack (esp. the native multi-round tool loop — the one thing the
fake-server tests cannot prove, flagged by the build lane itself), and the Cerberus egress
review were all KILLED before returning verdicts. This change is NOT gate-cleared. Do not
commit until all three have run clean.** Also pending: the 2 `test_churn.py` fails from the
baseline (git "not enough memory" while the 5GB model was RAM-resident — re-run with the
model unloaded: `ollama stop qwen2.5-coder:7b` first), and the post-change eval numbers
(pre-change baseline was byte-identical to session 3: 100%/79.3% primary, 86.2%/98.5%
quarantine, gate PASS, ceiling 2.3%/14.0% no reopen).

**Next steps, in order:** (1) rerun the three interrupted verdicts (Metron full gates with
model unloaded; Nemesis per its brief — multi-round native tool loop live, warm/pin
consistency, OOM honesty under env-16384, eviction live, `_slice_context` edge inputs;
Cerberus per its brief), repair findings, THEN commit with provenance-tagged message.
(2) Op-test A/B on a harder corpus → flip `OFFLOAD_SLICE_TOKENS` default only on measured
lift. (3) Chat lane: `ikarus_os`'s ollama branch still rides `/v1` → still truncation-exposed
AND causes reload thrash against the offload lane's 6144 runner (two window sizes, one
server) — switch it to the native client (needs an NDJSON streaming variant for
`chat_stream`). (4) The auto-mint seam (offload → `mint_task_from_landed_edit`) stays the
next flywheel item, unchanged.

**New gotchas (corrected [M] 2026-07-28):** `ollama ps` CONTEXT is the full request budget
for an under-budget prompt; ~`num_ctx/2` is the head-eating penalty only after the prompt
exceeds `num_ctx`, and `OLLAMA_NUM_PARALLEL` is not its cause. `prompt_eval_count` is
polluted by KV-prefix caching — probe with fresh unique content or you measure the cache,
not the window. Changing num_ctx reloads the model — pick ONE value per server. A
RAM-resident 5GB model makes UNRELATED `git init` subprocesses fail
("not enough memory") — unload before memory-sensitive test runs. cl100k over-counts qwen
tokens (~4x on gibberish, direction safe for over-escalation); the code treats estimates as
qwen-tokens with margin and documents the direction.

## 0b. Session 3 addendum (2026-07-21) — the Code Evolution foundation sprint

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

### Campaign Build Day 1 (2026-07-21) — Lane A1 label hygiene + Lane B1 memory ledger

**Item (1) is now shipped.** The first follow-up action landed with two parallel workstreams: minter label filters (Lane A1) that implement the planned junk/cross-language exclusion + floor-withheld classification, and an append-only memory ledger (Lane B1) for task persistence.

**Lane A1: Label hygiene in `_mint_from_diffs` [M].** Three filters now live in `daedalus/eval/mint.py` (~93–121, `_is_junk_label` new):

- **Junk filter:** non-identifier or keyword-shaped names (`if`, `<anonymous>`) never become `must_include`; excluded into `labels_filtered_junk` (sorted, counted).
- **Cross-language filter:** label's source file language must match anchor/target language; mismatches land in `labels_filtered_cross_language` (sorted, counted).
- **Secret floor anchor exclusion:** `secret_floor_rule` applied per-anchor; floor-tripping files drop from anchor pool (stay eligible as sources); if all candidates trip, honest `reason` in `skipped_secret_floor` (sorted, counted).

Wired into `daedalus/eval/harness.py` via `_is_focus_withheld()` / `_focus_withheld_row()`: these rows split from `by_provenance`/means, never fail the gate, never snapshot recall. `daedalus/eval/report.py` renders them one honest sentence: "the secret floor fail-closed on the focus file itself — not a recall miss, not a pass". **Tests: 14 new [M]** in `tests/test_mint_label_hygiene.py`.

**Lane B1: Append-only memory ledger (dmem/1) [M].** `daedalus/memstore.py` (390 lines) + `tests/test_memstore.py` (15 tests). Hash-chained ledger at `memory/ledger.local.jsonl`:

- `append_entry`: forces `trust.minted_tier="quarantine"` at write (earned via fold, never asserted), runs secret floor BEFORE writing over text/detail/paths; refused entries store redacted `gate_outcome` only. Dedupe by `body_sha` returns existing id. Hash boundary: `body_sha` = SHA256(canonical_body, sort_keys, separators, ensure_ascii, excluding ts/prev/entry_sha/id/body_sha); `entry_sha` = SHA256(prev+"\0"+body_sha+"\0"+ts); genesis prev→"".
- `append_confirm`/`append_flag`: control records on chain; `MEM_CONFIRM_THRESHOLD = 3` (cited to `MINT_CONFIRM_THRESHOLD`, not import-coupled).
- `load_ledger` (skip-corrupt), `verify_ledger` (chain walk, three per-line checks naming exact 1-indexed line on failure), `fold_state` (quarantine→primary at 3 confirms; flag→terminal; deterministic `state.local.json`).

**Verification [M]:** `pytest tests/test_memstore.py -q` → **15 passed in 24.35s** (roundtrip/dedupe/trust-forced, determinism byte-identical, tamper tests: flipped-byte and deleted-line break chain, planted AKIA/PEM/`.env` paths all refused with secret absent from raw bytes, 3-confirm-promote / 2-stay / flag-terminal, 1000-entry scale verifies <1s + catches flip at line 501). Adjacent suites: `pytest tests/test_dctx.py tests/test_eval.py -q` → **20 passed in 5.46s** [M]; no breakage.

**Measured result [M, re-verified by the session author against the raw eval printout — an
agent-reported "16 minted / 17 focus_withheld" did NOT survive that check and is corrected
here]:** pytest **779 passed / 0 failed**; independent_diff quarantine tier recall **86.2%
over 17 minted tasks** (up from 61.7% at the foundation-sprint seeding), compression 98.4%;
**17 tasks minted from 20 real commits** (3 skipped with reasons: 0360964, d714128, e2c77ad —
no unit-level change or filters drained all cross-file labels); **zero focus_withheld rows in
the final eval** — the hygienic minter excludes floor-tripping anchors at mint time, so none
reach scoring (the focus_withheld classification remains live for any future store); primary
tier unchanged **100% / 79.3%**; gate **PASS**. The lift 61.7%→86.2% is HONEST ACCOUNTING,
not a slicer improvement: junk + cross-language labels no longer count as misses and
fence-artifact targets are no longer minted. The 7 remaining miss tasks are almost entirely
the temporal class (co-committed symbols with no static import edge) — Lane A2's target.
**Adversarial review: 13 confirmed findings repaired (incl. 2 CRITICALs in the new ledger:
secret floor skipped provenance/refs fields; the refusal receipt re-embedded unscanned
provenance), 1 refuted [M].** Tail-truncation of the ledger is now detectable via a
head/count anchor persisted in state.local.json. `.gitignore` gained `memory/*.local.json`
+ `memory/receipts/`.

### Campaign Build Day 2 (2026-07-21 pm) — Lane A2 CLOSED ON MEASUREMENT, nothing built

**Follow-up (2) is resolved — by refutation, not by construction.** The planned "temporal
co-change slice enrichment" experiment was designed in full (opt-in `temporal_pairs` on
`semantic_slice`, backtest-clean per-task pairs, k-grid both-axes measurement), then
NO-GO'd by Momus at the design gate, which ran the cheap measurement the design had
deferred to its own risk list: a pairs-only reachability CEILING over the 7 miss tasks /
43 missed labels. **Backtest-clean (pairs from `git log <minted_at_sha>^`, min_count=2),
zero missed labels were reachable — 0/43.** I reproduced that independently in a fresh
process before accepting it, then extended it [M]: min_count=1 (any single prior
co-commit) = 1/43; full-history (leaky) = 6/43 at min_count=2 and **42/43 at min_count=1**
— i.e. the handoff's own "19% temporal class" triage number was predominantly **the minted
commit predicting itself** (the mint commit IS a co-change event; count it and almost
every miss looks temporally reachable).

**Nemesis then refuted one sub-claim of MY close, and the instrument was corrected:** my
"rename-aware matching does not change it" had only been measured at min_count=1. The true
rename-aware clean ceiling at min_count=2 is **1/43 = 2.3%** — one genuine
`verifier.py<->providers/ollama.py` coupling crossing the agent_env→daedalus rebrand
boundary (93-file rename; numstat spellings differ per commit, so exact-rel matching
starves real pairs below min_count). Verdict CLOSE-STANDS on materiality: **41/43 missed
labels sit on focus files BORN at their mint commit** (zero pre-mint history — structural
temporal immunity under ANY enrichment), 1/43 is a stale label (`_py_maps`, deleted by the
mint commit itself → NO_INSCOPE_DEF).

**What shipped instead of the tier (small, read-only, the reopen gate):**
`daedalus/eval/ceiling.py` — rename-aware (alias-unified counts via `git log --follow`,
summed across spellings BEFORE min_count), clean + leaky arms, per-label classification
(REACHABLE / UNREACHABLE / STATIC_EDGE / NO_INSCOPE_DEF), machine-printed reopen signal
with a **materiality floor** (>=10% of scored labels or >=3 tasks — a lone label must
read "stay closed"), audit list naming every clean-REACHABLE label, alias-probe failures
surfaced. Run: `python -m daedalus.eval.ceiling`. Plus an additive `rev` param on
`churn.co_change_pairs` (the backtest cut). `semantic_slice` was NOT touched — zero new
core-API surface. **Tests: 16 new** (`tests/test_temporal_ceiling.py`) incl. a positive
control (an always-zero checker fails), the leak-artifact control (clean UNREACHABLE /
leaky REACHABLE on the same fixture), the Nemesis rename-boundary case, and the
materiality-floor case. **[M, current corpus]: clean 2.3% / leaky 14.0%, reopen: none.**

**Standing decision this encodes:** slice-side temporal enrichment is CLOSED unless a
grown corpus trips the rename-aware materiality floor (`ceiling.py` docstring is the
canonical statement). Re-run the ceiling when the corpus grows — today's zero generalizes
weakly (born-at-mint focus files can never show pre-mint coupling). The 7 miss tasks stay
open as honest misses; the next lever on the list is **(3) wire slice→offload
(static-only)** — Horizon Phase 2, unchanged.

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
