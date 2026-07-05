# Provider Integration Research: DeepSeek API + Ollama (local)

Date: 2026-07-05
Researcher: Prometheus (stateless research pass, single session)
Purpose: facts needed to write two OpenAI-compatible provider adapters (DeepSeek hosted,
Ollama local) for a Python multi-agent harness emitting strict structured JSON reports.

---

## A) DeepSeek API

### A1. Base URL, models, SDK shape
- OpenAI-compatible base URL: `https://api.deepseek.com` (or `https://api.deepseek.com/v1` — the
  `/v1` path exists only for OpenAI-SDK compatibility, it is not a version selector).
  Anthropic-compatible base URL also exists: `https://api.deepseek.com/anthropic`.
  Source: [Your First API Call](https://api-docs.deepseek.com/) (official docs).
- **Current model IDs (as of 2026-07-05): `deepseek-v4-flash` and `deepseek-v4-pro`.**
  Source: [Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing) (official docs).
- **Legacy IDs `deepseek-chat` and `deepseek-reasoner` are scheduled for deprecation on
  2026-07-24 15:59 UTC** (i.e. ~3 weeks from today) and map to the non-thinking / thinking
  modes of `deepseek-v4-flash` respectively for back-compat.
  Source: [Reasoning Model (deepseek-reasoner)](https://api-docs.deepseek.com/guides/reasoning_model)
  and [Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing) (official docs).
  **Action for adapter:** target `deepseek-v4-flash`/`deepseek-v4-pro` as the canonical IDs;
  do not hardcode `deepseek-chat`/`deepseek-reasoner` as long-term defaults since they die in ~3 weeks.
- Call shape: standard OpenAI SDK chat-completions shape —
  `client.chat.completions.create(model="deepseek-v4-pro", messages=[...], stream=False)`.
  Extra (DeepSeek-specific) params: `thinking`, `reasoning_effort`.
  Source: [Your First API Call](https://api-docs.deepseek.com/) (official docs).
- Both current models: 1M token context, up to 384K max output tokens (per pricing page);
  legacy `deepseek-chat`/`deepseek-reasoner` were only 64K context / 8K max output — a large
  jump, reinforcing "migrate to v4 IDs." Source: [Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing).

### A2. Structured output / schema enforcement / tool calling
- **No strict JSON-Schema-enforced response format documented as GA.** DeepSeek supports
  `response_format={"type": "json_object"}` ("JSON Output" / JSON mode), which requires the
  literal word "json" to appear in the system or user prompt plus an example of the desired
  shape, and only guarantees syntactically valid JSON — **not** schema conformance (required
  keys, enums, types). Source: [JSON Output](https://api-docs.deepseek.com/guides/json_mode) (official docs).
- Function/tool calling is supported (standard OpenAI-style `tools`), and there is a
  **beta "strict" tool-calling mode** where function arguments can be constrained to a
  supported JSON Schema subset — this is the closest thing to schema enforcement DeepSeek
  offers, but it's beta and applies to tool-call arguments, not general chat completions.
  Source: secondary summary citing docs — [DeepSeek API JSON Mode Guide](https://deepseekai.guide/api/deepseek-api-json-mode/); corroborated by official pricing page listing "JSON Output" and "Tool Calls" as per-model capability flags: [Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing).
- Known issue: JSON mode can occasionally return **empty content**; DeepSeek's own docs
  acknowledge this ("actively working on optimizing"). Source: [JSON Output](https://api-docs.deepseek.com/guides/json_mode) (official docs).
- **Adapter implication: use `json_object` mode + your own JSON-Schema validation with a
  retry-on-failure loop (validate-and-retry), not schema-enforced strict mode**, unless you
  specifically route the report through a tool/function call in strict beta mode (added
  complexity, still not GA-guaranteed).

### A3. Pricing (per 1M tokens, USD) — two overlapping generations found; official page reconciled below
- Confirmed from the **official pricing-details page** (`api-docs.deepseek.com/quick_start/pricing-details-usd/`),
  legacy models:
  - `deepseek-chat`: input cache-hit $0.07 / cache-miss $0.27, output $1.10 (64K context, 8K max output).
  - `deepseek-reasoner`: input cache-hit $0.14 / cache-miss $0.55, output $2.19 (64K context, 32K max CoT, 8K max output).
  Source: [pricing-details-usd](https://api-docs.deepseek.com/quick_start/pricing-details-usd/) (official docs).
- Confirmed from the **official current pricing page** (`api-docs.deepseek.com/quick_start/pricing`),
  current models:
  - `deepseek-v4-flash`: input cache-hit $0.0028 / cache-miss $0.14, output $0.28. Concurrency cap 2500.
  - `deepseek-v4-pro`: input cache-hit $0.003625 / cache-miss $0.435, output $0.87. Concurrency cap 500.
  Source: [Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing) (official docs).
  Note: one secondary aggregator (cloudzero/chat-deep.ai via search snippet) quoted a higher
  V4-Pro rate ($1.74/$3.48) as a "standard rate before promotional discount" — **this is not
  what the official docs page shows now**; treat the official page figures above as authoritative
  and re-verify at integration time since DeepSeek has changed pricing/models multiple times in 2026.
- **No genuine free tier for the API.** All confirmed pricing is metered per-token from the
  first token; there is no free API quota documented on the official pricing pages. (There is
  a separate free consumer chat *app*/web UI, which is not the API — the user's "it's free"
  claim likely conflates the two.) Source: [Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing) — no free-tier line item present (official docs, negative finding).

### A4. Rate limits
- **DeepSeek does not publish fixed RPM/TPM.** It uses **dynamic, concurrency-based** limiting:
  a request occupies "one concurrent connection" from send until response completion; per-model
  concurrency caps are `deepseek-v4-pro`: 500, `deepseek-v4-flash`: 2500, applied at the account
  level (with optional per-`user_id` sub-limits for accounts with expanded quota). Exceeding it
  returns HTTP 429. Capacity-expansion requests are free but require a business justification.
  Source: [Rate Limit & Isolation](https://api-docs.deepseek.com/quick_start/rate_limit) (official docs).
- **Adapter implication:** implement exponential-backoff retry on HTTP 429; do not assume a
  fixed RPM/TPM budget to pace requests — concurrency is the throttling axis, not request rate.

### A5. Data retention / training-on-inputs — LOAD-BEARING, called out explicitly
- **DeepSeek's Privacy Policy states inputs/outputs (including personal data) may be used
  "to train and improve our technology, such as our machine learning models."** This clause is
  general and **is not carved out for paid API / Open Platform usage** — the Terms of Use has
  one data-use provision (§4.3, "to a minimal extent... to provide, maintain, operate, develop
  or improve the Services") applying uniformly to consumer app and API alike; no separate
  "API data is never used for training" guarantee exists (unlike, e.g., OpenAI's API-specific
  no-training default). Source: [DeepSeek Privacy Policy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html) and [DeepSeek Terms of Use](https://cdn.deepseek.com/policies/en-US/deepseek-terms-of-use.html) (official policy documents).
- **Opt-out exists but is manual, not a self-service API flag**: users have "the right to
  opt-out of using your Personal Data for training our models," exercised by **emailing
  privacy@deepseek.com**; for retroactively excluding already-shared data you must email and
  specify the exact data/chats. There is no documented API request header or account-setting
  toggle for this at the Open Platform (API) level.
  Source: [DeepSeek Privacy Policy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html) (official).
- **Retention period: unspecified.** Policy language is "for as long as necessary to provide
  our Services and for the other purposes set out in this Privacy Policy" — no fixed day/month
  figure is published. Source: same as above (official, but vague — treat as "no committed
  retention window").
- **Data location / jurisdiction: stored and processed in the People's Republic of China**
  ("we directly collect, process and store your Personal Data in the People's Republic of
  China"), and the Open Platform Terms of Service are governed by PRC law with disputes
  resolved in courts local to Hangzhou DeepSeek Artificial Intelligence Co., Ltd.'s registered
  office. Source: [DeepSeek Privacy Policy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html) and [DeepSeek Open Platform Terms of Service](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html) (official).
- **Ownership**: developer retains rights to Inputs submitted; DeepSeek assigns rights in
  Outputs to the developer. This does not contradict the training-use clause above — DeepSeek
  can still process/train on Inputs under §4.3 even though the developer "owns" them.
  Source: [DeepSeek Open Platform Terms of Service](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html) (official).
- **Bottom line for the "how much source code may we send" decision:** treat DeepSeek's hosted
  API as **not privacy-hardened for proprietary/confidential source code** by default — no
  API-tier no-training guarantee, vague retention, PRC data residency and jurisdiction, and the
  only opt-out is a manual email, not an enforceable, automatable API contract. If sending
  proprietary code is required, either (a) get the opt-out processed and confirmed in writing
  before sending anything sensitive, (b) redact/minimize what's sent, or (c) prefer the local
  Ollama backend for anything genuinely confidential.

### A6. ToS constraints relevant to sending proprietary code
- No explicit clause forbidding submission of proprietary/confidential code was found; §4.1 of
  the Open Platform ToS only requires that the submitter "warrant they have necessary rights
  and permissions to submit" their Inputs — i.e., you must be authorized to share whatever code
  you send (standard requirement, but combine with A5's training/retention facts above — being
  "allowed" to submit it does not mean DeepSeek won't retain/train on it).
  Source: [DeepSeek Open Platform Terms of Service](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html) (official).
- Confirmed governing law is PRC; for a lab / research org this may itself be a compliance
  consideration independent of the training question (export-control-adjacent or institutional
  data-handling policies may bar sending source code to PRC-jurisdiction services — flag to
  Adam/user as a policy question, not just a technical one).

---

## B) Ollama (local)

### B1. Base URLs / endpoints
- Default server base URL: `http://localhost:11434`.
  Source: [OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility) (official docs).
- Native API: `POST /api/chat` (and `/api/generate`).
  OpenAI-compatible API: `POST /v1/chat/completions` (also `/v1/embeddings`, `/v1/models`).
  For the OpenAI-compatible surface, point an OpenAI SDK client at
  `base_url="http://localhost:11434/v1/"` with `api_key="ollama"` (required by the SDK but
  ignored by Ollama). Source: [OpenAI compatibility](https://docs.ollama.com/api/openai-compatibility)
  and [ollama/docs/api.md](https://github.com/ollama/ollama/blob/main/docs/api.md) (official docs/repo).

### B2. Structured outputs (`format` = JSON schema)
- **Added in Ollama v0.5.0** (released ~2024-12-06 per the accompanying blog post). Instead of
  a generic built-in JSON grammar, you supply an actual JSON Schema in the `format` field (on
  both `/api/chat`/`/api/generate` and the OpenAI-compatible endpoints via the Ollama client
  libraries), and Ollama compiles it into a grammar that constrains llama.cpp's token sampling
  to conform to that schema. Source: [Release v0.5.0](https://github.com/ollama/ollama/releases/tag/v0.5.0)
  and [Structured outputs blog post](https://ollama.com/blog/structured-outputs) (official).
- Recommended practice from the same official post: define the schema via Pydantic
  (Python)/Zod (JS) and set `temperature=0` for determinism.
  Source: [Structured outputs blog post](https://ollama.com/blog/structured-outputs) (official).
- **Reliability with small/quantized models is uneven**, per independent write-ups (secondary,
  not official): compliance degrades sharply with schema complexity — one report found
  non-compliance rates rising from ~2-3% on flat schemas to ~68-69% once `$defs`
  (reusable/nested type definitions) are present; nested schemas 3+ levels deep on ~4B-class
  quantized models can silently return empty arrays at intermediate levels. Mitigations cited:
  keep schemas flat (avoid `$defs`/deep nesting), use `temperature=0`, and prefer a
  larger/less-quantized model over a smaller one when schema fidelity matters more than speed.
  Sources (secondary): [glukhov.org – GPT-OSS structured output issues](https://www.glukhov.org/post/2025/10/ollama-gpt-oss-structured-output-issues/),
  [markaicode.com – Reliable structured output from local LLMs](https://markaicode.com/ollama-structured-output-pipeline/).
  **Adapter implication:** keep the report schema flat/shallow, pin `temperature=0`, and still
  implement validate-and-retry (same posture as DeepSeek) rather than trusting the constrained
  grammar alone, especially for 7B-class local models.

### B3. Recommended local coder models (sizes / VRAM / quantization) and ranking
All sizes below are default Q4_K_M-quantized GGUF downloads as published in the Ollama library
(secondary aggregator numbers cross-checked against the Ollama library pages themselves).
- **qwen2.5-coder** family: available at 0.5B/1.5B/3B/7B/14B/32B. `7b` ≈ 4.7 GB download,
  ~5.5 GB VRAM to run; `14b` ≈ 8.7-9 GB, fits comfortably in 12-16 GB VRAM; `32b` ≈ 20 GB,
  wants 24 GB+ VRAM. Apache 2.0 licensed (see B5). Context window up to 128K depending on size.
  Sources: [ollama.com/library/qwen2.5-coder:7b](https://www.ollama.com/library/qwen2.5-coder:7b),
  [ollama.com/library/qwen2.5-coder:14b](https://ollama.com/library/qwen2.5-coder:14b) (official library pages, secondary aggregation for the VRAM figure: [localaimaster.com VRAM table](https://localaimaster.com/blog/ollama-model-ram-vram-table)).
- **deepseek-coder-v2:16b** (MoE, "lite" variant): Q4_K_M download ≈ 8.9-9.4 GB; needs roughly
  12-16 GB VRAM at Q4 (independent benchmarking source suggests 18 GB min / 28 GB optimal for
  the full-precision-adjacent configs — treat the lower Q4 figure as the realistic "modest
  consumer GPU" number). 160K context window (largest among the budget coders). DeepSeek
  custom license (see B5). Source: [ollama.com/library/deepseek-coder-v2:16b](https://ollama.com/library/deepseek-coder-v2:16b)
  (official library page); VRAM figures from secondary source [localvram.com](https://localvram.com/en/models/deepseek-coder-v2-16b-q4/).
- **llama3.1:8b**: general-purpose, not code-specialized; runs on ~8 GB VRAM/RAM class hardware.
  Llama 3.1 Community License (see B5). Source: [ollama.com/library/llama3.1:8b](https://ollama.com/library/llama3.1:8b) (official library page).
- **Ranking for code review / docstring drafting on modest consumer hardware** (synthesized
  from multiple 2026 secondary comparison write-ups — no single official Ollama benchmark page
  covers this; treat ranking as secondary-source consensus, not official):
  1. **qwen2.5-coder:7b** — best quality-per-VRAM; reported to outperform much larger
     general models on code benchmarks (e.g., cited HumanEval-style figures beating
     CodeLlama-70B-class models) while fitting in ~5.5 GB VRAM. Best default pick for an 8 GB
     consumer GPU.
  2. **qwen2.5-coder:14b** — step up in quality if 12-16 GB VRAM is available; still same
     Apache-2.0 family.
  3. **deepseek-coder-v2:16b** (MoE/lite) — competitive, notably larger context window (160K)
     useful for reviewing multi-file diffs, but license is more restrictive and it needs
     somewhat more VRAM/RAM headroom for the same nominal parameter count (MoE overhead).
  4. **llama3.1:8b** — weakest of the four for code-specific tasks (general-purpose model,
     not code-tuned); reasonable fallback if Qwen/DeepSeek license terms are unacceptable or
     as a "known quantity" baseline, but not recommended as primary code-review model.
  Sources (secondary consensus): [morphllm.com – Best Ollama Models 2026](https://www.morphllm.com/best-ollama-models),
  [localaimaster.com – Best Ollama Model for Coding 2026](https://localaimaster.com/models/best-local-ai-coding-models),
  [promptquorum.com – Best Local Coding LLMs 2026](https://www.promptquorum.com/local-llms/best-local-llms-for-coding).
  **Note:** several of these 2026 sources also flag newer entrants (Qwen3-Coder, Kimi K2.6,
  Devstral) as now competitive/superior to qwen2.5-coder for coding — worth a follow-up research
  pass if the adapter's model choice isn't locked yet; qwen2.5-coder remains a safe, well-tested
  default for now.

### B4. Detecting server up / model pulled programmatically
- **Server liveness**: `GET http://localhost:11434/` returns a 2xx ("Ollama is running") when
  the daemon is up; this is the documented lightweight liveness check (no dedicated
  `/api/health` endpoint is documented in the official API reference — some third-party guides
  reference one, but it is not in `ollama/docs/api.md`). Source: official repo
  [ollama/docs/api.md](https://github.com/ollama/ollama/blob/main/docs/api.md); liveness-check
  usage pattern corroborated by secondary sources (e.g. community troubleshooting guides).
- **Which models are pulled**: `GET /api/tags` returns `{"models": [...]}`, each entry with
  `name`/`model`, `modified_at`, `size`, `digest`, and a `details` object (`format`, `family`,
  `parameter_size`, `quantization_level`). Use this to check a required model tag is present
  before dispatching a request. Source: [ollama/docs/api.md](https://github.com/ollama/ollama/blob/main/docs/api.md) (official).
- **Pulling a model programmatically**: `POST /api/pull` with body `{"model": "<name>"}`
  (`insecure`, `stream` optional) streams progress JSON objects (`status`, `digest`, `total`,
  `completed`) and finishes with a `status: "success"` line; the CLI equivalent is
  `ollama pull <model>`. Source: [ollama/docs/api.md](https://github.com/ollama/ollama/blob/main/docs/api.md) (official).
- **Adapter implication:** on adapter init, do `GET /` (or attempt a lightweight `/api/tags` call
  and treat a connection error as "server down") to fail fast with a clear error before
  attempting `/api/chat`/`/v1/chat/completions`; check `/api/tags` for the configured model name
  and, if absent, either auto-`POST /api/pull` (streaming, can take minutes/GB) or fail with an
  actionable "run `ollama pull <model>`" message — auto-pulling multi-GB weights silently on
  every cold start is likely undesirable UX/bandwidth behavior, so prefer fail-with-instructions
  as the default, matching this repo's general "no silent heavyweight side effects" posture.

### B5. Licenses
- **Ollama itself (the ollama/ollama server/CLI): MIT License.**
  Source: [ollama/ollama LICENSE](https://github.com/ollama/ollama/blob/main/LICENSE) (official repo).
- **qwen2.5-coder (all sizes): Apache License 2.0** — permissive, no commercial-use
  restriction, no attribution-in-model-name requirement.
  Source (secondary, consistent across multiple write-ups): [runaihome.com comparison](https://runaihome.com/blog/best-local-coding-llm-2026/); model card license file example: [huggingface.co/EasierAI/Qwen-2.5-Coder-7B LICENSE](https://huggingface.co/EasierAI/Qwen-2.5-Coder-7B/blob/main/LICENSE).
- **deepseek-coder-v2: DeepSeek License Agreement v1.0** (custom, not OSI-approved) — grants a
  broad royalty-free patent/use license but is **not** a standard permissive OSS license;
  described by secondary sources as not restricting personal/small-business use but
  recommending legal review for large-scale commercial deployment.
  Source: [ollama.com deepseek-coder-v2 license blob](https://ollama.com/library/deepseek-coder-v2:16b-lite-instruct-q4_K_M/blobs/4bb71764481f) (primary artifact — the actual license text as shipped in the Ollama library); secondary interpretation via search summary.
- **llama3.1:8b: Llama 3.1 Community License** (Meta's custom license, not OSI-approved) —
  requires retaining a "Built with Llama"/attribution notice, requires prefixing "Llama" in
  the name of any derivative model distributed, and requires requesting a separate license
  from Meta if the deploying product/service has >700M monthly active users. Includes an
  Acceptable Use Policy.
  Source: [ollama.com/library/llama3.1:8b license blob](https://ollama.com/library/llama3.1:latest/blobs/f1cd752815fc) (primary artifact); summarized via secondary source.
- **Adapter/licensing implication:** for a lab tool that may eventually be shared/published,
  qwen2.5-coder's Apache-2.0 is the cleanest to depend on and redistribute references to;
  deepseek-coder-v2 and llama3.1 carry custom-license obligations (attribution text, naming
  rules, or scale-triggered relicensing) that don't block *internal* lab use but should be
  flagged before any external distribution of configs/weights bundling those models.

---

## Summary of what's most load-bearing

1. **DeepSeek: no API-tier no-training guarantee.** Training-use and retention clauses apply
   uniformly to consumer app and Open Platform (API); opt-out is a manual email, not an
   API-level control; data is stored/processed in the PRC under PRC jurisdiction. Treat as
   "send non-sensitive/non-proprietary content only" until/unless an explicit written opt-out
   is obtained. — [Privacy Policy](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html), [Open Platform ToS](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html).
2. **DeepSeek is not free** — it's cheap-but-metered (fractions of a cent per 1M cached input
   tokens up to ~$0.87/1M output on v4-pro); no free API tier exists. — [Models & Pricing](https://api-docs.deepseek.com/quick_start/pricing).
3. **DeepSeek model IDs are mid-migration**: `deepseek-chat`/`deepseek-reasoner` die
   2026-07-24; build adapters against `deepseek-v4-flash`/`deepseek-v4-pro`.
4. **Neither provider offers rock-solid schema-enforced structured output** — DeepSeek's
   `json_object` mode and Ollama's schema-`format` grammar both need validate-and-retry in the
   adapter, not blind trust; Ollama's reliability additionally degrades on deep/nested schemas
   with small quantized models, so keep the report schema flat.
5. **Ollama is fully local/MIT-licensed** — the clean choice whenever source code must not
   leave the machine; qwen2.5-coder (Apache-2.0) is the best default model on modest consumer
   GPUs (7B for ~8GB VRAM, 14B for 12-16GB).
