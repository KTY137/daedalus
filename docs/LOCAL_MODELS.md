# Local models for the Ikarus bench

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
