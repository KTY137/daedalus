# Daedalus — Session Handoff (2026-07-19 → 07-20)

## TL;DR
Big session. The **moat is proven** (eval), **Movement I.5 (Foundation Hardening) is complete + green (333 tests)**, the **engine pivoted to Rust** (`structcore-rs` compiles, runs, ~14× faster), and the **lag fix** is done backend-side (SSE) with the frontend in flight. Product identity locked: the **code-intelligence cockpit that sits ABOVE your agents** (not another IDE) — SEE → DISTILL → ORCHESTRATE, BYOK, local, any language.

## Current state (what's real)
- **Backend suite: 333 tests green.** Web build was green before the in-flight LiveChat frontend changes.
- **Movement 0 (cockpit):** glass chat-first UI + live theme editor + selectable-CLI **Ikarus brain** (`daedalus/ikarus_os.py` + `POST /api/ikarus/ask`) — deterministic-safe intents (status/distill/enqueue/design) + freeform brain via local Ollama / Claude CLI; now with **`model` + `effort` knobs** (default `low` — it's an interface chatbot).
- **Movement I (structural core — Python `daedalus/structcore/`, ~18 languages):** exact + **T2 renamed** + **T3 near-miss** clone clusters (SAFETY-CLASS fenced), **all-language dependency + fan-in graph**, **git churn×complexity hotspots**, **import/scope-aware symbol resolver**, tiktoken-ready `tokens.py`. Endpoints `GET /api/structure` + `POST /api/distill` (cached per repo).
- **Eval (`daedalus/eval/`):** Tier-1 deterministic **slice-recall = 100% @ 83.4% compression** — the honest bar's "smaller AND sufficient" proof (deterministic tier). Tier-2 LLM A-vs-B is coded + gated (needs a runtime).
- **Rust engine (`structcore-rs/`):** compiles (WinLibs MinGW), runs, reproduces clone findings, **~14× faster** (4s vs 60s on TCT_app). *v0 subset* (py/rust/js/java/c/go; no QML/TS/lizard-CC). *Normalization is lexical, not tokenize-grade → exact-cluster membership is NOT yet at parity with the Python reference (next Rust task).*
- **Lag fix:** SSE `GET /api/events` (cheap `file_bridge.stream_state` — file bus only, no git/PowerShell/Ollama) **DONE + smoke-tested**. Frontend (SSE consumption to kill the 5s poll + "Ikarus is thinking…" indicator + effort/model selector + glass-blur trim) = **LiveChat agent in flight**.

## How to run / verify
- **App:** `python -m daedalus.cli web` → http://127.0.0.1:8765 (serves built `apps/web/dist`). Dev: `cd apps/web && npm run dev` (5173, proxies `/api`).
- **Python suite:** `python -m pytest -q` (333 green).
- **Structural CLI:** `python -m daedalus.structcore <repo>` · distill: `python -m daedalus.structcore.slice <repo> <file[::symbol]>` · eval: `python -m daedalus.eval`.
- **SSE smoke:** `curl -N "http://127.0.0.1:8765/api/events?project=project_tct"` → `event: hello`.
- **Rust build (Windows toolchain env — REQUIRED each shell):**
  ```bash
  WL="/c/Users/nukei/AppData/Local/Microsoft/WinGet/Packages/BrechtSanders.WinLibs.POSIX.MSVCRT_Microsoft.Winget.Source_8wekyb3d8bbwe/mingw64/bin"
  export PATH="$WL:$HOME/.cargo/bin:$PATH"
  export CC_x86_64_pc_windows_gnu="$WL/gcc.exe"
  export AR_x86_64_pc_windows_gnu="$WL/ar.exe"
  cargo build --release --manifest-path "C:/Users/nukei/Desktop/agent_env/structcore-rs/Cargo.toml"
  "C:/Users/nukei/Desktop/agent_env/structcore-rs/target/release/structcore-rs.exe" <repo>
  ```
  (`walkdir` was removed — it dragged in `windows-sys`→`dlltool`; the crate uses a stdlib walk.)

## Next-session TODO (prioritized)
1. **Verify the LiveChat frontend build** — `cd apps/web && npm run build` green; visually confirm: live/polling chip, "Ikarus is thinking…" indicator, effort (Low/Med/High) + model selector, and that the cockpit feels snappy (no 5s poll jank). Fix/revert if broken.
2. **Rust parity** — swap the lexical normalizer for **tree-sitter comment/string-node stripping** (structural, generalizes to all langs) so exact-cluster membership matches the Python reference; then port T2/T3 + metrics + slice into Rust. Diff Rust output vs `python -m daedalus.structcore` on the harness + TCT_app.
3. **Movement II — WebGL living code map:** expose module→module dependency **edges** on `/api/structure` (additive; `index.py` has `dependencies`, `report.py` currently ships only `fan_in`), then a **Sigma.js/Cosmograph** map consuming it with a **hotspot heat overlay** (churn×complexity) and **"Distill this"** on nodes → `/api/distill`.
4. **Close eval Tier-2** (LLM A-vs-B) against local Ollama → the headline "distilled slice matches the whole-repo dump at a fraction of tokens/cost".
5. **Exactness:** `pip install tiktoken` (exact token counts in the distill %); run structcore across more languages.
6. **Movement 0 leftovers:** `daedalus/providers/gemini_cli.py` (Gemini/Antigravity lane) + `daedalus/agent_discovery.py` (scan a repo for CLAUDE.md/AGENTS.md/.cursorrules/etc. and onboard from them).
7. **Later:** Movement III (orchestration loop — `loop/edits,localize,lsp,select` + `gates.py` + cascade), Movement V (Tauri v2 + the Rust engine compiled in, Nuitka sidecar for the Python core).

## Gotchas / invariants (don't relearn the hard way)
- **Python `structcore` is the REFERENCE ORACLE** — do not delete; the Rust port is diffed against it until parity.
- **Near-clone bounds are load-bearing** (from PyPrecision): `min_shared_rare=4`, `max_cluster=30`, `_MIN_BAG=12`, ubiquitous-token cutoff `max(3, 0.4·n)`. Mirror these exactly in Rust or T3 blows up into 700-member blobs.
- **Rust toolchain:** rustup **GNU** host + **WinLibs MSVCRT** MinGW (matches the `-gnu` ABI). The self-contained rust gcc lacks `ar` → must use WinLibs `gcc`/`ar` via the env vars above.
- **BYOK** (platform holds no paid key; `env.py` only returns `{configured:bool}`), **SAFETY-CLASS fence** (`sensitivity.py`), **additive-only endpoints**, **`/api/dashboard` frozen** (`test_ui_contract`) — all still hold.
- **The lag was never the language** — it was the 5s poll hitting the heavy `get_dashboard` (git+PowerShell+Ollama) + glass blur GPU cost. SSE + cheap `stream_state` + fewer blur layers is the fix. Even in Tauri the UI stays a webview.
- **Plan:** `C:\Users\nukei\.claude\plans\ast-driven-distillation-harness-modular-sprout.md`. **Memory:** `daedalus-agentos-moonshot.md`.
