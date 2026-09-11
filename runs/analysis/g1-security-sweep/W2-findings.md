# W2 — Network Egress vs. Declared Policy

Base: local main `851ff43c` (branch `wip/g1-freeze-2026-08-31`). Read-only. No writes except this file.

## Enumeration

Greps run (all under `C:/Users/Administrator/daedalus`, excluding `vault/`, `.quarantine/`, `daedalus/lanes/`, `.claude/worktrees/`, `.daedalus_worktrees/`, `build/`, `apps/web/src-tauri/backend/`, `apps/web/src-tauri/target/`):

1. `EgressPolicy|egress_policy|allowed_hosts|allowlist|egress_admission|check_egress|EGRESS` over `daedalus/` → 33 files (policy/registry surface).
2. `import requests|import httpx|urllib\.request|urllib3|http\.client|import socket\b|aiohttp|websockets|subprocess.*curl|subprocess.*wget|anthropic\.|openai\.|litellm|requests\.(get|post)|httpx\.(get|post|Client)` over `**/*.py` → 85 files (includes tests; production subset read below).
3. `chat_completion\(|chat_stream\(|from .._openai_compat|from ._openai_compat` → call sites of the shared HTTP client.
4. `warm_model` → all callers of the module-level Ollama warm-up function.
5. `no egress|zero egress|never leaves this machine|all network|every network|routes? through|no network|blocked before|nothing leaves the machine` (case-insensitive) over `daedalus/**/*.py` → overclaim-hunt surface.

**Actual byte-emitting transports found: 3 primitives, all stdlib `urllib.request` — this repo has no `requests`/`httpx`/`aiohttp`/vendor-SDK network client.**

| Primitive | File | Used by |
|---|---|---|
| `urllib.request.urlopen` (raw) | `daedalus/providers/ollama.py::warm_model` | Ollama VRAM pin |
| `_openai_compat._post` / `chat_completion` / `chat_stream` / `server_reachable` (urllib) | `daedalus/providers/_openai_compat.py` | Ollama + DeepSeek chat, decompose, tier2 eval, ikarus_os chat/stream |
| `_ollama_native.native_chat` (urllib) | `daedalus/providers/_ollama_native.py` | `OllamaProvider` agentic loop / rewrite / window edits |

Vendor CLIs (`provider.claude`, `provider.codex`, `provider.ollama_cli`) are **subprocess spawns**, not in-process sockets; their egress happens inside the child binary and is out of this grep's reach (process-spawn admission is a different W-lane's scope — noted, not re-audited here).

Distinct **call sites that actually reach a socket** (grouped by whether an admission decision runs first):

| # | Site (file:function) | Endpoint source | Routed through `provider.egress_policy` / `lane_for_host` / `_provider_start` first? |
|---|---|---|---|
| 1 | `providers/ollama.py::OllamaProvider.run` → `_run_agentic`/`_run_rewrite`/`_rewrite_by_window`/`_full_file_content`/exception fallback (all call `native_chat`) | `self.host` = `OLLAMA_HOST` env or default | **yes** — `run()` calls `self._refuse_if_remote()` (→ `ollama_endpoint_admission`/`lane_for_host`/`remote_endpoint_consented`) as its first statement |
| 2 | `providers/ollama.py::warm_model` / `warm_model_async` | `host` param or `OLLAMA_HOST` env | **no** — the function itself has zero admission call |
| 2a | …called from `ikarus_os.py::_ollama` / `_ollama_stream` | same | **yes at the call site** — `_provider_start("ollama", endpoint=host, ...)` runs immediately before, and raises on refusal |
| 2b | …called directly (any future/other caller of `warm_model`/`warm_model_async`) | same | **no** — nothing stops a second caller from skipping `_provider_start` |
| 3 | `ikarus_os.py::_ollama` / `_ollama_stream` → `chat_completion`/`chat_stream` | `OLLAMA_HOST` env | **yes** — `_provider_start` precedes both |
| 4 | `ikarus_os.py::_deepseek` / `_deepseek_stream` (not fully quoted above, same pattern per registry note "deepseek: network_egress/spend/secrets") | `DEEPSEEK_BASE_URL` env / default | **yes** — same `_provider_start` pattern (registry anchors `_deepseek`/`_deepseek_stream` → `_provider_start`) |
| 5 | `providers/deepseek.py::DeepSeekProvider.run` / `_full_file_content`-equivalent → `chat_completion` | `self.base_url = os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)` | **no** — direct Python entrypoint; registry row `provider.deepseek` is explicitly `wiring=INVENTORY_ONLY, guard_contracts=()` |
| 6 | `kairos/decompose.py::_ask_model` (reached via `decompose()` ← `build.py:533`, `kairos/scheduler.py:455`) | `OLLAMA_HOST` env | **no** — only `server_reachable` (liveness probe) runs first, no host/lane check |
| 7 | `eval/tier2.py::_ask` (reached via `run_tier2` ← `eval/harness.py::run_tier2` compat shim, tier-2 opt-in eval) | `prov["host"]`, itself built by `eval/harness.py::detect_provider` from `OLLAMA_HOST` env | **no** — no host/lane check anywhere in the tier-2 path |
| 8 | `eval/harness.py::detect_provider` (probe GET `/api/tags`) | `OLLAMA_HOST` env | **no** — raw `urllib.request.urlopen`, no admission |
| 9 | `memory/embeddings.py::OllamaEmbeddingBackend.embed` | caller-selected host | **yes** — `_authorize_egress(self.host)` (→ `ollama_endpoint_admission`) runs immediately before the POST; registry row is `CENTRAL` |
| 10 | `runtimes/admission/offload_egress.py::admit_offload_egress` | declares `"deepseek": "https://api.deepseek.com"` (hardcoded) for the `ollama`/`deepseek` lease lanes | this is the admission function itself — **it never reconciles with the DeepSeek provider's actual `DEEPSEEK_BASE_URL`-derived endpoint** |

**Site count: 10 distinct socket-reaching call paths. Bypass (no admission before the socket call): sites 2 (bare `warm_model`), 5 (`DeepSeekProvider.run`), 6 (`decompose._ask_model`), 7 (`tier2._ask`), 8 (`detect_provider`) — 5 of 10 unrouted, i.e. exactly half.**

## Findings

### F-W2-01 `decompose._ask_model` sends task content to an unvalidated `OLLAMA_HOST`, reachable from `daedalus.build`/`kairos.scheduler`
- **file:line**: `daedalus/kairos/decompose.py:124-152` (`_ask_model`), reached via `daedalus/build.py:533` (`decompose(feature, repo_root)`) and `daedalus/kairos/scheduler.py:455` (`decompose(objective, repo_root)`)
- **class**: egress-bypass
- **severity**: HIGH
- **status**: CONFIRMED with quoted code
- **evidence**:
  ```python
  def _ask_model(objective, paths, max_subtasks, *, timeout_s=60.0):
      host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
      model = os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
      if not server_reachable(host, path="/api/tags"):
          return []
      try:
          raw = chat_completion(
              base_url=host.rstrip("/") + "/v1", model=model,
              system=_SYSTEM, user=_user_prompt(objective, paths, max_subtasks),
              api_key=None, timeout_s=timeout_s, force_json=True, temperature=0.0,
          )
      except (ProviderHTTPError, ValueError, OSError):
          return []
  ```
  `server_reachable` (`providers/_openai_compat.py:181`) is a bare `urlopen(url, timeout=2.0)` liveness probe — it answers "is something listening," never "is this host admitted." No call to `ollama_endpoint_admission`, `lane_for_host`, `remote_endpoint_consented`, or `begin_effect`/`_provider_start` exists anywhere in `decompose.py`. Compare `providers/ollama.py::OllamaProvider.run`, whose very first statement is `self._refuse_if_remote()` specifically **because** (per that function's own docstring) "the rewrite prompt carries whole file bodies... a guard here covers every one of them, including any caller written later." `decompose.py` is exactly such a later caller, and the guard does not cover it.
- **reachability**: `daedalus/build.py::plan_feature` (or equivalent build-mission entry) calls `decompose(feature, repo_root)` unconditionally; `daedalus/kairos/scheduler.py::KairosScheduler.spawn` likewise. Both are production code paths (not test-only), and `objective`/`paths` (which name real repository files/features) are what gets sent as the POST body to `host + "/v1/chat/completions"`. If `OLLAMA_HOST` is repointed to a non-loopback address — an env value an operator, a misconfigured container, or a compromised parent process can set — this content leaves the machine with no consent check and no receipt.

### F-W2-02 `decompose.py` module docstring overclaims "nothing leaves the machine" for the exact function that has no host check
- **file:line**: `daedalus/kairos/decompose.py:7`
- **class**: overclaim
- **severity**: MEDIUM (paired with F-W2-01; the claim is what makes the missing guard invisible to a reader)
- **status**: CONFIRMED with quoted code
- **evidence**: `"""...Best-effort dynamic breakdown via the local Ollama server... Nothing leaves the machine (local server), so this is cheap and private."""` — the function this describes (`_ask_model`) resolves its target from `OLLAMA_HOST` with no verification that the resolved host is in fact local (see F-W2-01). The claim is true only by operator convention, never by code.
- **reachability**: same as F-W2-01 (doc comment sits directly above the unguarded call).

### F-W2-03 `DeepSeekProvider.run` reads its endpoint from `DEEPSEEK_BASE_URL` with zero host validation; the registry's own admission function hardcodes a different (unenforced) endpoint
- **file:line**: `daedalus/providers/deepseek.py:189-190` (`self.base_url = os.environ.get("DEEPSEEK_BASE_URL", DEFAULT_BASE_URL)`), call sites at `deepseek.py:391-395`, `deepseek.py:606-609`; declared admission at `daedalus/runtimes/admission/offload_egress.py:18-20` (`_LANE_ENDPOINTS = {"deepseek": "https://api.deepseek.com"}`)
- **class**: weak-host-validation / ssrf-surface
- **severity**: MEDIUM-HIGH
- **status**: CONFIRMED with quoted code
- **evidence**: There is no DeepSeek equivalent of `lane_for_host`/`ollama_endpoint_admission` anywhere in the tree (`daedalus/sensitivity.py` defines `lane_for_host` for Ollama only — grep-confirmed, no DeepSeek analog). `classify_data`/`slice_egress_rule`/`secret_floor_rule` gate **which bytes** are safe to send to "an untrusted external provider such as DeepSeek" (their own docstrings), never **where** the request actually goes. The registry itself documents the gap honestly at `spine/effect_boundary.py:1901-1929` (`id="provider.deepseek", wiring=Wiring.INVENTORY_ONLY, guard_contracts=()`), noting "deepseek.py imports nothing from the kernel or the broker and run() takes no authorization argument." Separately, `admit_offload_egress`'s lane table (`offload_egress.py:18-20`) hardcodes `"https://api.deepseek.com"` for the `deepseek` lane and is never consulted by, or reconciled against, `DeepSeekProvider.__init__`'s actual `DEEPSEEK_BASE_URL`-derived value — so the one place that *does* declare an allowed DeepSeek endpoint has no wiring to the code path that actually sends bytes, and that code path itself performs no allowlist/scheme check on the URL it uses (`_openai_compat._post` builds `base_url.rstrip("/") + "/chat/completions"` and sends `Authorization: Bearer {api_key}` to whatever that string resolves to, including a non-`https` scheme).
- **reachability**: `DeepSeekProvider.run` is invoked by production write/advisory lanes (registry: "busiest paid lane"). The registry says the *reachable* production path today runs through `tools.guarded_call` (a process-boundary CLI door that does install a spend net + secret floor), which mitigates unpriced/secret-leaking calls but still performs **no host-allowlist check** on `DEEPSEEK_BASE_URL` — the mitigation covers spend and secrets-in-payload, not destination. This is registry-**disclosed** as an open gap (not a hidden bypass, so I am not filing it as an overclaim), but the audit's own hunt list calls out exactly this shape ("declared endpoint" vs. actual behavior mismatch), so I am recording it as CONFIRMED rather than treating the disclosure as closing it: an operator/attacker who can set `DEEPSEEK_API_KEY`+`DEEPSEEK_BASE_URL` in the process environment (e.g. via a compromised `.env`, CI config, or parent shell) redirects the API key and all DeepSeek-classified-safe payloads to an arbitrary host with no code-level check.

### F-W2-04 `eval/tier2.py::_ask` / `eval/harness.py::detect_provider` send question+context to `OLLAMA_HOST` with no admission
- **file:line**: `daedalus/eval/tier2.py:124-158` (`_ask`), `daedalus/eval/harness.py:650-674` (`detect_provider`)
- **class**: egress-bypass / overclaim
- **severity**: LOW-MEDIUM (opt-in Tier-2 eval lane, not a default production path; still reachable via `cli.eval_correctness`/`run_tier2`)
- **status**: CONFIRMED with quoted code
- **evidence**:
  ```python
  # eval/harness.py:650
  def detect_provider(provider: str | None = None) -> dict | None:
      """... Only a local Ollama HTTP endpoint is probed (free, no key, no egress). ..."""
      host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
      ...
      with urllib.request.urlopen(host + "/api/tags", timeout=2) as r:
  ```
  This *is* a real network GET — "no egress" is factually wrong the moment `OLLAMA_HOST` names a non-loopback address, which the code neither prevents nor detects. The returned `prov["host"]` then flows unchecked into:
  ```python
  # eval/tier2.py:124
  def _ask(prov: dict, question: str, context: str) -> dict:
      ...
      text = chat_completion(base_url=prov["host"] + "/v1", model=prov["model"],
                              system=system, user=user, force_json=False, temperature=0.0, timeout_s=120)
  ```
  where `context` is task-provided text (per the calling docstring, "distilled slice (A) vs whole concat (B)" — i.e., real project text in the live-eval case). No `lane_for_host`/consent/`_provider_start` call exists on this path.
- **reachability**: `run_tier2()` is a documented opt-in evaluation entrypoint (`daedalus/eval/tier2.py`, delegated from `eval/harness.py` for compatibility), invoked by `cli.eval_correctness`-style tooling. Lower severity than F-W2-01 because it requires explicitly requesting Tier-2 evaluation, but the underlying defect (env-sourced host, no admission) is identical.

### F-W2-05 `warm_model`/`warm_model_async` perform an unadmitted POST and claim "no egress" unconditionally
- **file:line**: `daedalus/providers/ollama.py:331-378`
- **class**: overclaim / egress-bypass (latent — currently mitigated only by caller discipline)
- **severity**: LOW
- **status**: CONFIRMED with quoted code; PLAUSIBLE that it stays harmless (no repo content in the empty-prompt payload) but the claim and the missing internal guard are both real
- **evidence**:
  ```python
  def warm_model(host=None, model=None, keep_alive=None, timeout_s=60.0) -> bool:
      """... An empty prompt makes this a pure load/refresh ... Local-only, no spend,
      no egress. Returns True if the pin was accepted; never raises.
      """
      host = ollama_http_base_url(host or os.environ.get("OLLAMA_HOST", DEFAULT_HOST))
      ...
      req = urllib.request.Request(f"{host}/api/generate", data=body, ...)
      with urllib.request.urlopen(req, timeout=timeout_s) as resp:
  ```
  No call to `ollama_endpoint_admission`/`lane_for_host` inside this function. The only reason the two current callers (`ikarus_os.py::_ollama`/`_ollama_stream`) are safe is that **they** call `_provider_start(...)` immediately beforehand and that call raises on refusal before reaching `warm_model_async` — i.e., the guarantee lives entirely in caller order, which is exactly the anti-pattern the plan's invariant 8 forbids ("not entrusted to prompts" generalizes to "not entrusted to call-site ordering" for a function whose own docstring claims the property unconditionally).
- **reachability**: today's two callers are gated; the function itself is exported and importable by any future caller (including tests importing it directly, per `tests/test_ikarus_stream.py`) with no internal enforcement.

## What I did not cover

- Vendor CLI subprocess egress (`provider.claude`, `provider.codex`, Ollama CLI transport) — the network calls happen inside the spawned binary, not in Python; that is process-spawn admission (a different boundary) and is out of this grep-based sweep.
- MCP transport (`daedalus/integrations/hermes/tool_gateway.py`) — has a `host`/`port` in its `EnvelopeGrant` dataclass but I did not trace whether that binds a client or a server socket; left unverified rather than guessed.
- TLS verification (`verify=False` equivalent) — moot for this codebase's transport choice: `urllib.request` does not expose a `verify=False`-style bypass the way `requests` does, and I found no `ssl._create_unverified_context()` or `ssl.CERT_NONE` anywhere in `daedalus/` (grepped, zero hits) — noting the absence rather than claiming a positive guarantee.
- Redirect-following behavior of `urllib.request.urlopen` (it follows 3xx by default with no re-check of the target host) — flagged as a plausible but unconfirmed risk for every site above that reaches an externally-configurable `base_url`/`host`; I did not find a redirect-blocking wrapper anywhere in `daedalus/providers/` or `daedalus/memory/embeddings.py`, but I also did not construct a live redirect to verify the failure mode, so this is **not** filed as its own numbered finding — it compounds F-W2-01/03/04 rather than standing alone.
- Desktop/Tauri-side network code (`apps/web/src-tauri/`) was excluded per the stale-tree ignore list in the task brief.
- `daedalus/desktop_runtime.py`'s `keyscan` subprocess call (`desktop_runtime.py:1030`, spawns a network-probing binary against `r["host"]`) was noted in the grep sweep but not traced end-to-end; it looks like a process-spawn diagnostic, not a data-bearing egress, and was deprioritized under time budget.
