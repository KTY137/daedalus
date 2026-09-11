"""Fixture texts for the preservation checker.

Contains no tests itself -- it is named ``test_*`` only so it lives beside the
suite that uses it.

``BEFORE`` is ``docs/LOCAL_MODELS.md`` **verbatim at commit f18ff5c**, embedded
rather than read from disk so this regression fixture stays pinned to the text
the failure was actually MEASURED against when the doc later changes.

``AFTER_REGRESSION`` applies exactly the four MEASURED edits a live
qwen2.5-coder:7b rewrite made under the instruction "Keep every fact that is
already in the file and do not add any new ones", and nothing else.

``AFTER_LIVE`` is a real, unedited qwen2.5-coder:7b rewrite of ``BEFORE``
captured from the local Ollama lane -- the honest control, because it is a
mostly-*good* rewrite carrying heavy Title Case churn.

``AFTER_LEGIT`` is a hand-written legitimate improvement: paragraphs rewrapped
and sentences tightened, every fact kept.
"""

BEFORE = """# Local models for the Ikarus bench

The local lane is pointed at an OpenAI-compatible endpoint via three env vars:

| env var | default | used for |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | the local server |
| `OLLAMA_MODEL` | `qwen2.5-coder:7b` | the coder that reads/writes |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | stage-1 semantic routing embeddings |

## Recommended models (2026)

`qwen2.5-coder:7b` is the safe, well-tested baseline but is now the *older* tier.
Per `docs/IMPROVEMENTS_RESEARCH.md`, for stronger agentic tool-use reliability at
a similar footprint, consider upgrading the coder:

- **`qwen3-coder`** — MoE (≈3B active / 80B total), reported competitive with
  Sonnet on some agentic-coding benchmarks. Best pick if VRAM allows.
- **`devstral`** (Devstral Small 24B) — purpose-built for tool-calling /
  multi-step agent workflows.
- **`qwen2.5-coder:14b`** — a modest step up, same Apache-2.0 family, ~12-16 GB VRAM.

Switching is just an env var — no code change:

```powershell
$env:OLLAMA_MODEL = "qwen3-coder"     # or "devstral", "qwen2.5-coder:14b"
```

Re-benchmark tool-use reliability before trusting a new model on `write` mode;
the verifier gate (`daedalus/orchestration/verifier.py`) is your backstop either way.

## Running the bench

### Option A — Ollama (recommended; already multi-model)

Ollama hot-loads the requested model on demand, so a single server serves the
coder **and** the embedder with no extra tooling — just pull both:

```powershell
ollama serve                     # if not already running as a service
ollama pull qwen2.5-coder:7b     # coder (or your upgrade choice)
ollama pull nomic-embed-text     # embeddings for semantic routing
```

`daedalus` talks to it out of the box. Check readiness with:

```powershell
python -m daedalus.doctor
```

### Option B — llama-swap (only if you run raw llama.cpp, not Ollama)

`llama-swap` (MIT, single Go binary) proxies one OpenAI-compatible endpoint and
hot-swaps which `llama.cpp` model process is loaded by requested model name. Use
it only if you are *not* on Ollama — Ollama already gives you multi-model for
free. A starter config is at `configs/llama-swap.example.yaml`; point
`OLLAMA_HOST` at the llama-swap port.
"""


# The four MEASURED regressions, and ONLY those four:
#   1. "is pointed at an OpenAI-compatible endpoint via three env vars"
#          -> "is configured via three environment variables"   (fact deleted)
#   2. "Per `docs/IMPROVEMENTS_RESEARCH.md`," -> gone           (cross-ref deleted)
#   3. `daedalus` -> daedalus                                   (markup stripped)
#   4. "Recommended models" -> "Recommended Models"             (style churn)
AFTER_REGRESSION = """# Local models for the Ikarus bench

The local lane is configured via three environment variables:

| env var | default | used for |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | the local server |
| `OLLAMA_MODEL` | `qwen2.5-coder:7b` | the coder that reads/writes |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | stage-1 semantic routing embeddings |

## Recommended Models (2026)

`qwen2.5-coder:7b` is the safe, well-tested baseline but is now the *older* tier.
For stronger agentic tool-use reliability at
a similar footprint, consider upgrading the coder:

- **`qwen3-coder`** — MoE (≈3B active / 80B total), reported competitive with
  Sonnet on some agentic-coding benchmarks. Best pick if VRAM allows.
- **`devstral`** (Devstral Small 24B) — purpose-built for tool-calling /
  multi-step agent workflows.
- **`qwen2.5-coder:14b`** — a modest step up, same Apache-2.0 family, ~12-16 GB VRAM.

Switching is just an env var — no code change:

```powershell
$env:OLLAMA_MODEL = "qwen3-coder"     # or "devstral", "qwen2.5-coder:14b"
```

Re-benchmark tool-use reliability before trusting a new model on `write` mode;
the verifier gate (`daedalus/orchestration/verifier.py`) is your backstop either way.

## Running the bench

### Option A — Ollama (recommended; already multi-model)

Ollama hot-loads the requested model on demand, so a single server serves the
coder **and** the embedder with no extra tooling — just pull both:

```powershell
ollama serve                     # if not already running as a service
ollama pull qwen2.5-coder:7b     # coder (or your upgrade choice)
ollama pull nomic-embed-text     # embeddings for semantic routing
```

daedalus talks to it out of the box. Check readiness with:

```powershell
python -m daedalus.doctor
```

### Option B — llama-swap (only if you run raw llama.cpp, not Ollama)

`llama-swap` (MIT, single Go binary) proxies one OpenAI-compatible endpoint and
hot-swaps which `llama.cpp` model process is loaded by requested model name. Use
it only if you are *not* on Ollama — Ollama already gives you multi-model for
free. A starter config is at `configs/llama-swap.example.yaml`; point
`OLLAMA_HOST` at the llama-swap port.
"""


# Hand-written LEGITIMATE improvement: paragraphs rewrapped onto different line
# breaks, several sentences tightened, every fact and every artefact kept.
# The checker must be SILENT on this -- a checker that flags it gets switched
# off, and a switched-off checker protects nothing.
AFTER_LEGIT = """# Local models for the Ikarus bench

The local lane is pointed at an OpenAI-compatible endpoint via three env vars:

| env var | default | used for |
|---|---|---|
| `OLLAMA_HOST` | `http://localhost:11434` | the local server |
| `OLLAMA_MODEL` | `qwen2.5-coder:7b` | the coder that reads/writes |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text` | stage-1 semantic routing embeddings |

## Recommended models (2026)

`qwen2.5-coder:7b` is the safe, well-tested baseline but is now the *older* tier. Per `docs/IMPROVEMENTS_RESEARCH.md`, consider upgrading the coder for stronger agentic tool-use reliability at a similar footprint:

- **`qwen3-coder`** — MoE (≈3B active / 80B total), reported competitive with Sonnet on some agentic-coding benchmarks. Best pick if VRAM allows.
- **`devstral`** (Devstral Small 24B) — purpose-built for tool-calling / multi-step agent workflows.
- **`qwen2.5-coder:14b`** — a modest step up, same Apache-2.0 family, ~12-16 GB VRAM.

Switching is just an env var — no code change:

```powershell
$env:OLLAMA_MODEL = "qwen3-coder"     # or "devstral", "qwen2.5-coder:14b"
```

Re-benchmark tool-use reliability before trusting a new model on `write` mode; the verifier gate (`daedalus/orchestration/verifier.py`) is your backstop either way.

## Running the bench

### Option A — Ollama (recommended; already multi-model)

Ollama hot-loads the requested model on demand, so a single server serves the coder **and** the embedder with no extra tooling — just pull both:

```powershell
ollama serve                     # if not already running as a service
ollama pull qwen2.5-coder:7b     # coder (or your upgrade choice)
ollama pull nomic-embed-text     # embeddings for semantic routing
```

`daedalus` talks to it out of the box. Check readiness with:

```powershell
python -m daedalus.doctor
```

### Option B — llama-swap (only if you run raw llama.cpp, not Ollama)

`llama-swap` (MIT, single Go binary) proxies one OpenAI-compatible endpoint
and hot-swaps which `llama.cpp` model process is loaded by requested model
name. Use it only if you are *not* on Ollama — Ollama already gives you
multi-model for free. A starter config is at
`configs/llama-swap.example.yaml`; point `OLLAMA_HOST` at the llama-swap port.
"""


# UNEDITED live output: qwen2.5-coder:7b via http://127.0.0.1:11434/api/generate
# (temperature 0.2, num_ctx 8192) asked to "Improve the readability of this
# markdown document. Tighten the prose and fix any awkward phrasing. Keep every
# fact that is already in the file and do not add any new ones."
# Captured 2026-07-29. This run happened to be a GOOD rewrite carrying heavy
# Title Case churn -- which is precisely why it is the honest control.
AFTER_LIVE = """# Local Models for the Ikarus Bench

The local lane points to an OpenAI-compatible endpoint via three environment variables:

| Env Var          | Default                | Used For                     |
|------------------|------------------------|------------------------------|
| `OLLAMA_HOST`    | `http://localhost:11434`| The local server              |
| `OLLAMA_MODEL`   | `qwen2.5-coder:7b`     | The coder for reading/writing |
| `OLLAMA_EMBED_MODEL` | `nomic-embed-text`  | Stage-1 semantic routing embeddings |

## Recommended Models (2026)

`qwen2.5-coder:7b` is the safe, well-tested baseline but is now considered the *older* tier.
According to `docs/IMPROVEMENTS_RESEARCH.md`, for stronger agentic tool-use reliability at a similar footprint, consider upgrading the coder:

- **`qwen3-coder`** — MoE (≈3B active / 80B total), reported competitive with Sonnet on some agentic-coding benchmarks. Best pick if VRAM allows.
- **`devstral`** (Devstral Small 24B) — Purpose-built for tool-calling and multi-step agent workflows.
- **`qwen2.5-coder:14b`** — A modest step up, same Apache-2.0 family, ~12-16 GB VRAM.

Switching is as simple as changing an environment variable — no code change required:

```powershell
$env:OLLAMA_MODEL = "qwen3-coder"     # or "devstral", "qwen2.5-coder:14b"
```

Re-benchmark tool-use reliability before trusting a new model in `write` mode; the verifier gate (`daedalus/orchestration/verifier.py`) is your backstop either way.

## Running the Bench

### Option A — Ollama (Recommended; Already Multi-Model)

Ollama hot-loads the requested model on demand, so a single server serves both the coder and the embedder with no extra tooling. Just pull both:

```powershell
ollama serve                     # If not already running as a service
ollama pull qwen2.5-coder:7b     # Coder (or your upgrade choice)
ollama pull nomic-embed-text     # Embeddings for semantic routing
```

`daedalus` talks to it out of the box. Check readiness with:

```powershell
python -m daedalus.doctor
```

### Option B — llama-swap (Only if You Run Raw llama.cpp, Not Ollama)

`llama-swap` (MIT, single Go binary) proxies one OpenAI-compatible endpoint and hot-swaps which `llama.cpp` model process is loaded based on the requested model name. Use it only if you are *not* using Ollama — Ollama already provides multi-model support for free. A starter config is available at `configs/llama-swap.example.yaml`; point `OLLAMA_HOST` at the llama-swap port.
"""
