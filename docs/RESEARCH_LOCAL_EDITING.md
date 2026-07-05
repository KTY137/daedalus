# Research: Local-Model Edit Application, Tool Calling, and Verifier Design

*Researched 2026-07-05 for daedalus. Context: qwen2.5-coder:7b never emits `write_file` tool
calls in the agentic loop (narrates edits, `files_changed=[]`), but returns correct full-file
rewrites as forced-JSON `{"content": ...}` in ~50s.*

## Executive summary — recommendations for daedalus

1. **Standardize on full-file rewrite via structured JSON output** (`format=<schema>`, native
   `/api/chat`). This is the industry-validated path for weak models: aider routes its weakest
   models to the "whole" format, and aider's own Qwen3 benchmark found whole *beat* diff even at
   32B/235B (100% well-formed vs ~94%). Cursor's data: "fully rewriting the full file outperforms
   aider-like diffs for files under 400 lines" — and Cursor/Morph built their entire "fast apply"
   pipeline on full-file rewrite. Do **not** invest in search/replace or unified-diff formats at
   7B; they are the formats weak models fail at.
2. **Add rewrite guards before the verifier**: (a) reject on elision markers
   (`# ... rest of|unchanged|omitted|existing code`), (b) line-count/length-ratio guard (reject if
   output < ~60% or > ~200% of input lines without an explicit deletion task), (c) cap eligible
   files at ~400 lines / escalate larger ones to Claude or a per-function chunked rewrite,
   (d) `temperature 0`, (e) ensure `num_ctx` and `num_predict` are large enough that the whole
   file fits — Ollama's small default context *silently truncates* and is a top cause of mangled
   edits.
3. **If tool calls are ever needed locally: use native `/api/chat`, never `/v1`, and avoid
   streaming+tools together.** The OpenAI-compat layer has documented bugs (streaming breaks or
   silently drops tool calls). qwen2.5-coder's tool weakness is well documented across Ollama,
   opencode, Cline, and aider issue trackers; its Ollama library page doesn't even list the
   `tools` capability.
4. **Pull and benchmark as alternatives** (43GB disk budget, unknown GPU):
   `qwen3:8b` (5.2GB, tools+thinking), `qwen3:14b` (9.3GB), `llama3.1:8b` (4.9GB, Ollama's
   canonical tool-calling model — use as a format-reliability control). Stretch: `devstral:24b`
   (14GB, purpose-built agentic coder, 46.8% SWE-bench Verified, needs ~RTX 4090 / 32GB RAM).
   First three total ~19.4GB.
5. **Verifier cascade is already near best practice** (schema → py_compile → tests →
   require-changes). Cheap additions worth making: ruff/pyflakes gate after py_compile, the
   length-ratio guard from (2), k-sample regeneration on verifier failure before escalating, and
   logging (task, output, verdict) so a FrugalGPT-style learned accept/escalate scorer is possible
   later.

---

## 1. Edit-application formats for small local models

**Aider's format taxonomy** ([edit formats doc](https://aider.chat/docs/more/edit-formats.html)):
`whole` (return entire updated file), `diff` (search/replace blocks), `diff-fenced` (Gemini
quirk), `udiff` (unified diff, built to fight GPT-4-Turbo laziness), `editor-*` (architect mode).
Aider matches format to model strength; only the weakest models are given `whole`, and its
[troubleshooting doc](https://aider.chat/docs/troubleshooting/edit-errors.html) says most local
models are "just barely capable" of the structured formats and recommends `--edit-format whole`
when edits fail.

**Evidence whole > diff for Qwen models specifically** — aider's
[Qwen3 benchmark](https://aider.chat/2025/05/08/qwen3.html) (May 2025): Qwen3-235B whole 65.3%
correct / 100% well-formed vs diff 61.3% / 94.7%; Qwen3-32B whole 45.8% / 100% vs diff 41.3% /
94.2%. If diff loses even at 32-235B for this family, a 7B has no chance —
[aider #2371](https://github.com/Aider-AI/aider/issues/2371) documents qwen2.5-coder-32b failing
diff edits locally.

**Industry cross-check**: Cursor's Instant Apply ([blog](https://cursor.com/blog/instant-apply),
2024) deliberately uses full-file rewrite as the apply representation ("full rewrite outperforms
aider-like diffs for files <400 lines" — [aider #625](https://github.com/Aider-AI/aider/issues/625)),
made fast via speculative decoding ([Fireworks writeup](https://fireworks.ai/blog/cursor)).
[Morph](https://www.morphllm.com/fast-apply-model) sells the same architecture. Plan-then-rewrite
(big model sketches, apply model rewrites whole file) is exactly the daedalus shape, with Claude
as planner and the local model as the apply stage.

**Known failure modes of full-file rewrite + standard mitigations**:
- *Truncation / laziness*: model emits `# ... rest of code ...` or stops early on long files.
  Mitigate: elision-marker regex reject; length/line-count ratio guard; explicit "return the
  ENTIRE file, no omissions" instruction; cap file size and escalate/chunk above it (~400 lines
  per Cursor's crossover); set `num_predict` high enough.
- *Gratuitous reformatting*: whole-file output rewrites untouched lines (whitespace, quotes,
  import order), producing noisy diffs. Mitigate: diff the applied result and bound
  changed-line count vs task scope; run a formatter (e.g. `ruff format`) on both sides before
  diffing; reject if unrelated-hunk ratio too high.
- *Context starvation*: Ollama's default `num_ctx` is small and **silently discards** overflow
  (aider troubleshooting doc) — the model then rewrites from a partial file. Mitigate: set
  `num_ctx` explicitly per request; verify input file fits with margin.
- *Cost/latency O(file size)*: acceptable here (local = free); still argues for the size cap.

## 2. Tool-calling reliability of local models on Ollama (2025-2026)

**qwen2.5-coder's weakness is documented, not just ours**:
[ollama#7051](https://github.com/ollama/ollama/issues/7051) (hallucinated/non-schema tool calls),
[ollama#7445](https://github.com/ollama/ollama/issues/7445) (no `tool_calls` node, fabricated
results), [opencode#7030](https://github.com/anomalyco/opencode/issues/7030) (**identical symptom
to ours**: edit/write "executed" but no files modified),
[cline#10843](https://github.com/cline/cline/issues/10843) (raw JSON in `content` instead of
`tool_calls`, infinite loop). The [Ollama library page](https://ollama.com/library/qwen2.5-coder)
lists code generation/reasoning/fixing but **no `tools` capability**. Conclusion: this model
family was tuned for code completion, not agentic tool use — don't fight it.

**Ollama API caveats** (cross-checked):
- `/v1` OpenAI-compat + `tools` + `stream=true` is broken or degraded:
  [ollama#9092](https://github.com/ollama/ollama/issues/9092) (streaming collapses to one block),
  [ollama#9632](https://github.com/ollama/ollama/issues/9632), and downstream reports of the
  compat layer *silently dropping* tool calls when streaming.
- Native `/api/chat` has supported streaming + tool calls since ~May 2025 (v0.8) and parses
  model-specific tool templates ([tool support blog](https://ollama.com/blog/tool-support),
  Jul 2024). **Use native endpoint, non-streamed, for any local tool-calling.**

**Models with reliable function calling at 7-14B, pull-able today**:
- `qwen3:8b` (5.2GB) / `qwen3:14b` (9.3GB) — `tools` + `thinking` capabilities on Ollama; Qwen3
  was explicitly trained for agentic tool use in both modes. Best coder-quality-per-GB candidates.
  Consider disabling thinking for edit tasks (aider found thinking hurt coding scores/latency).
- `llama3.1:8b` (4.9GB) — the model Ollama's own tool-support launch used; weaker coder, but the
  most battle-tested tool-call *format* reliability at 8B. Good control model.
- `devstral:24b` (14GB, 128K ctx) — Mistral+All Hands agentic coder, "editing multiple files and
  powering SWE agents", 46.8% SWE-bench Verified (above GPT-4.1-mini); needs RTX-4090-class GPU
  or 32GB RAM ([library page](https://ollama.com/library/devstral)). Pull only if hardware allows.
- FYI: BFCL v3/v4 top small models are function-calling specialists (ToolACE-8B, xLAM, Hammer) —
  great at emitting calls, not coders; not worth bench slots here
  ([BFCL](https://gorilla.cs.berkeley.edu/leaderboard.html)).

**But note**: our JSON-rewrite path *sidesteps* tool calling entirely for the write stage. Tool
calling only matters if the local loop needs read/search/run tools — benchmark that separately.

## 3. Verifier / cascade design (FrugalGPT-style)

- **FrugalGPT** ([paper, May 2023](https://arxiv.org/pdf/2305.05176) — foundational, pre-dates
  modern local models): cascade with a learned scoring function g(q, a) → [0,1] (fine-tuned
  DistilBERT) and per-stage threshold; accept if above, else escalate to next model. Lesson for
  us: our deterministic gates are the scorer; logging outcomes now enables training a cheap
  learned scorer later. Surveys (e.g. [dynamic routing/cascading survey,
  2026](https://arxiv.org/html/2603.04445v2)) frame the standard trio: pre-router → quality
  estimator → escalation policy.
- **Execution-grounded verification beats judge-only**: CodeT-style *dual execution agreement*
  (generate candidate + generate tests, accept candidates that pass their own generated tests);
  [ReVeal (2025)](https://arxiv.org/pdf/2506.11442) has the model generate test cases on the fly;
  [Semantic Voting (2026)](https://arxiv.org/pdf/2605.08680) picks among k samples by execution
  consensus rather than string match.
- **What we already do** (schema → py_compile → optional test suite → require-changes) matches
  the established gate stack. Marginal additions, in cost order:
  1. `ruff check` (or pyflakes) after py_compile — catches undefined names/unused imports that
     compile fine; milliseconds.
  2. Pre-verifier length-ratio + elision guard (§1) — rejects before wasting a test run.
  3. Retry-then-escalate: on gate failure, regenerate once or twice (k-sampling) at the local
     tier before escalating to Claude; self-consistency is the cheapest accuracy multiplier.
  4. LLM-judge only for the borderline band (passed syntax, no tests available) — judge the
     *diff*, not the file, and prefer Claude-as-judge sparingly or a second local model.
  5. Log every (task, model, output, gate verdicts) tuple → future learned accept/escalate
     threshold, FrugalGPT-style.

## 4. JSON structured-output reliability at 7B

- Ollama ≥ v0.5 `format=<json schema>` compiles the schema to a llama.cpp **GBNF grammar** and
  masks invalid tokens at sampling time — syntactic validity is *guaranteed*, unlike prompt-only
  JSON mode ([Ollama blog](https://ollama.com/blog/structured-outputs),
  [how it works](https://blog.danielclayton.co.uk/posts/ollama-structured-outputs/)). Prefer a
  real schema (`{"content": {"type":"string"}, ...}` with `required`) over bare `format=json`.
- Caveats ([docs](https://docs.ollama.com/capabilities/structured-outputs)): also put the schema
  in the prompt; `temperature 0`; still validate (pydantic) — grammar guarantees shape, not
  sense; bare `format=json` without prompting for JSON can produce runaway whitespace; output
  truncated mid-string if `num_predict` is hit still parses as invalid — treat parse failure as
  an escalate signal, which our schema gate already does.
- **Constraint tax**: ["Let Me Speak Freely?" (Aug 2024)](https://arxiv.org/pdf/2408.02442) found
  format restriction degrades *reasoning*-heavy tasks; stricter constraint → bigger drop. For
  mechanical edit tasks our benchmark shows the tax is acceptable; for harder local tasks, use
  two-step (free-form reasoning → forced-JSON restatement) rather than dropping structure.

## Benchmark next

- [ ] Re-run today's edit benchmark with `qwen3:8b` and `qwen3:14b` on the JSON full-file-rewrite
      path (thinking off); compare correctness + wall-clock vs qwen2.5-coder:7b.
- [ ] Same models, native `/api/chat` + `tools`, non-streaming: do write_file calls actually fire?
      (Separates "rewrite path" from "agentic loop" capability.) Add `llama3.1:8b` as control.
- [ ] Implement + test the rewrite guards: elision-marker regex, line-ratio bounds, 400-line cap,
      explicit `num_ctx`/`num_predict`; measure rejected-vs-caught-by-py_compile overlap.
- [ ] Add `ruff check` gate; measure incremental catch rate over py_compile on benchmark outputs.
- [ ] Try k=2 local retry before Claude escalation; measure escalation-rate delta.
- [ ] Check GPU (`ollama ps` / `nvidia-smi`) before deciding on `devstral:24b` (14GB) or
      `qwen2.5-coder:14b` as the "bigger sibling" comparison.
- [ ] Long-file stress: 300/500/800-line files through the rewrite path to find our truncation
      cliff and validate the size cap.
