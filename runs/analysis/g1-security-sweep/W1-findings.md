# W1 — Subprocess spawn-site audit (daedalus/, tools/, scripts/)

Scope per assignment: every subprocess spawn site under `daedalus/` (plus
`tools/` and `scripts/` where reachable from `daedalus/`). Excludes
`daedalus/lanes/`, `vault/`, `.quarantine/`, and the listed stale/build trees.
Base revision: local `main` HEAD as checked out in this worktree
(`git rev-parse HEAD` = `54f0975398fd77120383c3af0ac5bb9291ef7064`; the task
brief cites `851ff43c` as the sweep base — noted, not reconciled, since this
worker only reads).

Read-only. No file outside this report was modified.

## Enumeration

Grep pattern used for every count below:

```
subprocess\.(Popen|run|check_output|check_call|call)\s*\(|os\.system\s*\(|os\.popen\s*\(|os\.exec[lv]|create_subprocess_(shell|exec)
```

- `daedalus/`: **93 occurrences across 51 files** (Grep tool count mode).
- `tools/`: pattern present in **16 files** (not further traced — see "What I
  did not cover"; `daedalus/tools/vet.py` — 1 occurrence — belongs to the
  `daedalus/` count above and IS traced, see F-W1-08).
- `scripts/`: pattern present in **63 files**, essentially all
  `run_*_mutations.py` fault/mutation-injection harnesses plus a handful of
  probes (`fault_mutation_sandbox.py`, `fourfold_*_probe.py`). Checked for
  reachability from `daedalus/`: grepped `daedalus/` for
  `scripts.run_|scripts[/\\]|import scripts` — the 6 hits are docstring/string
  references to script *names*, not imports of `scripts/` modules by
  production `daedalus/` code. These are standalone dev/CI mutation-testing
  entrypoints invoked by a human/CI runner, not spawned by daedalus/ at
  runtime. **Not traced further** (see "What I did not cover").
- Also confirmed **0 occurrences of `shell=True`** in `daedalus/`, `tools/`,
  `scripts/` (reproduced the sibling worker's measurement; did not re-spend
  time on it beyond one confirming grep).

Breakdown of the 93 `daedalus/` occurrences by module area (file: count),
every file with ≥1 hit:

```
accelerators.py:3  adapters/subprocess_adapter.py:1  arch_memory.py:1
bookkeeper.py:1  build_exec.py:1  claude_bridge.py:1  core.py:2
council/publish.py:1  dctx.py:1  desktop_runtime.py:6  doctor.py:2
dotenv.py:1  editor_context.py:3  eval/ceiling.py:2  eval/correctness.py:4
eval/graph_delta.py:1  eval/mint.py:1  eval/provenance.py:1
gates/repository_write_stdlib_delta.py:10 (*)  health.py:2
hooks/_common.py:2  ignition/bundle.py:2  ignition/checks.py:1
ignition/gate1.py:2  ikarus_os.py:4  integrations/hermes/configuration.py:1
integrations/hermes/runtime_adapter.py:1  kairos/_gated_writes_legacy.py.src:2
kairos/evolution.py:1  kairos/worktree.py:1  kernel/attempt_execution.py:1
kernel/promotion.py:1  kernel/promotion_trust_root.py:1  kernel/sandbox.py:1
loop.py:1  mapping/render.py:2  offload.py:1  providers/codex_cli.py:1
providers/ollama.py:2  runtime_registry.py:1
runtimes/execution/budget_process.py:1 (**)  runtimes/fixture_fault_collector.py:1
spine/bootstrap.py:1  spine/cancel.py:0 (Popen type refs only, no spawn)
spine/containment.py:1  spine/effect_boundary.py:4 (***)  spine/killswitch.py:1
status.py:1  structcore/churn.py:2  tools/vet.py:1  verifier.py:5
```

(*) `gates/repository_write_stdlib_delta.py` — all 10 hits are STRING
LITERALS in an AST-scan denylist (`"asyncio.create_subprocess_exec"`,
`"os.execl"`, etc.) used by a static gate that scans *other* code for
forbidden calls. Not an actual spawn site. Verified by reading lines 40-70.

(**) `runtimes/execution/budget_process.py` is a monkey-patch guard that
wraps `subprocess.run`/`subprocess.Popen` module-wide to enforce the
execution-limit policy (§4.1 of the master plan) around every other spawn
site — not itself a spawn site with fixed argv. Read in full; it is the
budget-enforcement wrapper referenced by the docstrings quoted in
`effect_boundary.py`, not a new call site.

(***) `spine/effect_boundary.py` — all 4 hits are the `Effect.PROCESS_SPAWN`
classification table plus prose describing spawn sinks elsewhere (verified —
this file registers the guard metadata other spawn sites cite, it does not
itself call `subprocess.*`).

So the REAL spawn-site count under `daedalus/` (excluding the two
non-spawning files above once their hits are subtracted) is **~79 genuine
call sites** across 47 files. I did not attempt to force this to an exact
single number beyond that arithmetic — the point of the count is auditability
of the grep, not a leaderboard digit.

**Traced to callers / reachability confirmed:** 19 sites (listed under
Findings + the negative-result notes below). **Skimmed only** (read the call,
confirmed fixed/internal argv, did not walk further up the call chain): the
remaining ~60, concentrated in `desktop_runtime.py` (ssh/keyscan/keygen,
config-derived host/user, not model-controlled), `eval/*.py` and
`kairos/*.py` git plumbing (rev-parse/log/diff on internal revisions),
`health.py`/`doctor.py`/`accelerators.py` version probes (fixed `--version`
argv), and `verifier.py` (compiler/linter checks on repo-local paths).

## Findings

### F-W1-01 `codex` resolves to an npm `.CMD` shim on Windows and receives an attacker/model-influenced prompt as the final positional argv element

- **file:line**: `daedalus/providers/codex_cli.py:230-262`
- **class**: batfile-quoting (Windows CVE-2024-3566 class) / argument-injection
- **severity**: CRITICAL
- **status**: CONFIRMED
- **evidence**:
  ```python
  # npm installs `codex` as a .CMD shim on Windows; subprocess cannot
  # spawn it by bare name (WinError 2), so resolve the real path.
  codex = shutil.which("codex") or "codex"
  cmd = [
      codex, "exec",
      "--cd", repo_root,
      "--sandbox", "workspace-write" if writable else "read-only",
      "--skip-git-repo-check",
      "--color", "never",
      "--output-schema", str(schema_path),
      "--output-last-message", str(message_path),
  ]
  chosen_model = model or os.environ.get("CODEX_MODEL", "")
  if chosen_model:
      cmd += ["--model", chosen_model]
  cmd.append(prompt)
  ...
  completed = subprocess.run(
      cmd, cwd=repo_root, text=True, capture_output=True,
      encoding="utf-8", errors="replace",
      stdin=subprocess.DEVNULL,
      timeout=effective_timeout, check=False,
  )
  ```
  `prompt = build_prompt(agent, objective, paths, writable, policy, ...)`
  (line 209) embeds `objective` verbatim into the prompt text
  (`daedalus/providers/codex_cli.py:96-146`, `Objective:\n{objective}`-style
  interpolation confirmed by reading `build_prompt`).
- **reachability**: `CodexCLIProvider` is registered as a live production
  provider in `daedalus/providers/__init__.py:50` (`return
  CodexCLIProvider()`), not a test-only stub. `objective` is the task/mission
  text handed to the provider by the caller — under the master plan's Genesis
  strand (§7.1) this is explicitly "a freely phrased construction request"
  compiled from user intent, i.e. natural-language text that is not
  constrained to exclude cmd.exe metacharacters (`&`, `|`, `%`, `^`, `<`,
  `>`, embedded `"`).
- **why it matters**: `subprocess.run(cmd, shell=False)` on Windows still
  routes through `cmd.exe` when the resolved executable is a `.bat`/`.cmd`
  file (confirmed by the repo's own comment: codex's npm install IS a `.CMD`
  shim on this class of machine). Python's `list2cmdline` escaping assumes
  standard MSVCRT argv parsing, not `cmd.exe` shell-metacharacter parsing, so
  a prompt/objective string containing ordinary characters like `&`, `%VAR%`,
  or `^` can be reinterpreted as command chaining / env-var expansion /
  escape sequences by the wrapping `cmd.exe`, rather than passed through as
  inert argv text. Because the whole `objective` is folded into `prompt` and
  appended as the LAST argv element with no per-token escaping for cmd.exe
  semantics, this is both (a) a real availability/correctness bug (routine
  prompts containing `&` or `%` will silently mis-parse) and (b) an argument/
  command-injection surface for anyone who can influence mission objective
  text reaching this provider.
- **mitigating factors observed**: `classify_data(paths, extra_text=objective,
  policy=policy)` runs first (line 200) but only classifies for
  sensitive/proprietary CONTENT egress — it has no shell-metacharacter
  awareness and does not block or escape `&`/`%`/`^`. `stdin=subprocess.DEVNULL`
  and an explicit `timeout=` are both present and correctly used (no
  availability gap on this particular call).
- **cross-reference**: distinct from the sibling worker's env-leak finding at
  the same provider (no `env=` override) — this finding is about argv
  construction, not environment inheritance.

### F-W1-02 `gh` also resolves to a `.CMD` shim on Windows; `pr`/`repo` values reach argv unsanitized (no leading-dash / `--` guard)

- **file:line**: `daedalus/council/publish.py:133-160`, argv built at
  `:780` and `:815`, unsanitized helper at `:243-244` and `:603-604`
- **class**: batfile-quoting + argument-injection
- **severity**: MEDIUM
- **status**: CONFIRMED
- **evidence**:
  ```python
  def _subprocess_runner(argv: Sequence[str], stdin_text: str | None = None,
                         timeout_s: int = DEFAULT_TIMEOUT_S) -> RunResult:
      argv = list(argv)
      # gh installs as a .CMD shim under some Windows package managers; subprocess
      # cannot spawn it by bare name (WinError 2), so resolve the real path first
      # -- the same lesson codex_cli.py records for the codex shim.
      exe = shutil.which(argv[0]) or argv[0]
      ...
      completed = subprocess.run(
          [exe] + argv[1:],
          text=True, capture_output=True, encoding="utf-8", errors="replace",
          input=stdin_text if stdin_text is not None else "",
          timeout=timeout_s, check=False,
      )
  ```
  and:
  ```python
  def _text(val: Any) -> str:
      return "" if val is None else str(val)
  ...
  def _gh_argv(base: list[str], repo: str | None) -> list[str]:
      return base + (["--repo", str(repo)] if repo else [])
  ...
  argv = _gh_argv(["gh", "pr", "comment", _text(pr), "--body-file", "-"], repo)
  ...
  argv = _gh_argv(["gh", "pr", "view", _text(pr), "--json", "comments"], repo)
  ```
- **reachability**: `publish_council_comment`/`read_pr_thread` take `pr: str
  | int` and `repo: str | None` as public parameters of the `council` skill's
  publish/read path (per `daedalus/council/publish.py:793` signature and the
  `council` skill description: "publish an existing council transcript to a
  GitHub PR ... or read a PR thread back"). `_text()` performs no validation
  at all — it is a bare `str()` coercion — and `_gh_argv` does not insert a
  `--` end-of-options separator before the positional `pr` argument or the
  `--repo` value.
- **why MEDIUM not CRITICAL**: the comment BODY itself (the highest-value
  injection payload) is correctly passed via `--body-file -` + `stdin_text`,
  not argv — that part is done right and is a meaningfully better design than
  F-W1-01. The residual risk is narrower: a `pr`/`repo` value beginning with
  `-` (e.g. a stray `--repo` typo'd into the `pr` field, or a crafted
  `repo="-x"`-shaped string from whatever upstream caller derives it from a
  URL/user text) would be parsed by `gh` as a flag rather than a value —
  argument confusion / CLI misbehavior — and if the resolved `gh` binary is a
  `.CMD` on the host, the same cmd.exe-relay caveat as F-W1-01 nominally
  applies to `pr`/`repo`, though `gh`'s own flag surface has no known direct
  code-exec flag reachable this way (unlike a free-text prompt argument).
- **could not verify**: I did not trace the exact call site(s) that invoke
  `publish_council_comment`/`read_pr_thread` with a `pr`/`repo` value to
  confirm whether it is ever taken from unreviewed model/user text versus
  always an operator-typed skill argument — flagging as PLAUSIBLE for the
  "model-influenced" half of the reachability claim, CONFIRMED for the
  missing-validation code itself.

### F-W1-03 `daedalus/adapters/subprocess_adapter.py` — generic runtime adapter has a live argv-injection shape but is not wired to a real provider today

- **file:line**: `daedalus/adapters/subprocess_adapter.py:209-254`
- **class**: argument-injection (dormant)
- **severity**: LOW (currently) / would be HIGH if wired to a real profile
  with `prompt_mode="argument"`
- **status**: CONFIRMED (code shape) / PLAUSIBLE (no live production caller found)
- **evidence**:
  ```python
  cmd = [self._config.command, *self._config.default_args]
  if model: cmd.extend([self._config.model_arg, str(model)])
  if self._config.cwd_arg: cmd.extend([self._config.cwd_arg, str(cwd)])
  cmd.extend(extra_args)                 # extra_args = config.get("args", ())
  if prompt and self._config.prompt_mode == "argument":
      cmd.append(prompt)                 # prompt = config.get("prompt") or ""
  ...
  process = await asyncio.create_subprocess_exec(*cmd, ...)
  ```
  `RuntimeConfig.prompt_mode` defaults to `"argument"` (dataclass default,
  `:58`), and the ad-hoc constructor path
  (`SubprocessAdapter(command=..., args=...)`, `:131-136`) builds a
  `RuntimeConfig` WITHOUT setting `prompt_mode`, so it inherits `"argument"`.
  Both BUILT-IN profiles (`"claude"`, `"codex"`, `:71-102`) explicitly
  override to `prompt_mode="stdin"`, which avoids this path.
- **reachability**: grepped every `SubprocessAdapter(` construction in the
  repo — only `daedalus/adapters/__init__.py:14` (a docstring example,
  `adapter = SubprocessAdapter(config=RuntimeConfig(command="my-agent"))`)
  and 4 sites in `tests/test_adapters.py`. No production `daedalus/` code
  path constructs a `SubprocessAdapter` with a custom `command=`/`args=` at
  the time of this sweep, so the vulnerable `prompt_mode="argument"` branch
  is reachable only from tests and the doc example today.
- **also note**: `command="claude"` / `command="codex"` in the built-in
  profiles are BARE names, not resolved via `shutil.which` (unlike
  `codex_cli.py` and `council/publish.py`, which explicitly resolve first).
  Per the documented lesson in `runtime_registry.py:294-300` ("npm ships
  `codex` as a `.CMD` shim ... CreateProcess cannot launch it by name"), if
  this adapter's `"codex"` profile is ever exercised on a host where `codex`
  resolves only to a `.cmd`, `asyncio.create_subprocess_exec("codex", ...)`
  would fail outright (WinError 2) rather than silently succeed — an
  availability bug, not injection, but the SAME root cause as F-W1-01/02
  recurring a third time in this codebase.

### F-W1-04 `daedalus/ignition/gate1.py:_git()` has no `timeout=`

- **file:line**: `daedalus/ignition/gate1.py:322-338`
- **class**: missing-timeout
- **severity**: LOW
- **status**: CONFIRMED
- **evidence**:
  ```python
  def _git(args: Sequence[str], *, cwd: Path) -> str:
      env = dict(os.environ)
      env.update(FROZEN_GIT_ENV)
      env["GIT_CONFIG_NOSYSTEM"] = "1"
      env["GIT_TERMINAL_PROMPT"] = "0"
      completed = subprocess.run(
          ["git", *args],
          cwd=str(cwd),
          env=env,
          capture_output=True,
          text=True,
      )
  ```
  No `timeout=` keyword anywhere in the call, confirmed by reading the full
  call (lines 327-333) — every other `subprocess.run(["git", ...])` call site
  found in this sweep (`editor_context.py`, `build_exec.py`, `health.py`,
  `arch_memory.py`, `bookkeeper.py`, `dctx.py`, `attempt_execution.py`,
  `eval/mint.py`, `eval/graph_delta.py`, `eval/correctness.py`,
  `providers/ollama.py`) passes an explicit `timeout=`.
- **reachability**: called from `_freeze_base_repo` (init/config/add/commit/
  rev-parse, `:362-368`) and from a patch-apply path (`:547`,
  `git apply --whitespace=nowarn <patch_file>`) inside the Gate-1 Renovation
  rehearsal. All observed call sites pass local-only git subcommands (no
  `fetch`/`clone`/`push`), so this is not a network-hang vector; `git apply`
  on an adversarially large or pathological patch could still stall
  indefinitely with nothing to kill it. `GIT_TERMINAL_PROMPT=0` prevents an
  interactive credential prompt from hanging the process, but does not
  substitute for a wall-clock bound.
- **severity rationale**: kept at LOW rather than MEDIUM because every
  current caller is local/offline; flagged because the task brief calls out
  "a hung provider CLI is a real availability bug" as a first-class class to
  hunt, and this is the one `git` call site in the sample that lacks the
  timeout every sibling call site in the same file/module family has.

## Negative results (checked, not exploitable)

- **`kairos/worktree.py:1102`** (`self._run_git('worktree', 'add', '-b',
  branch_name, str(worktree_path), base_commit)`) — CONFIRMED SAFE.
  `branch_name` is always constructed as
  `f"{BRANCH_PREFIX}-{_slug(task.task_id)}-{task.digest[:8]}-{uuid4().hex[:6]}"`
  (`daedalus/kernel/attempt_execution.py:1371-1372`) or
  `f"daedalus-correctness-{label}-{uuid4().hex[:8]}"`
  (`daedalus/eval/correctness.py:710`). `_slug()` strips leading/trailing `-`
  (`re.sub(r"[^a-z0-9]+", "-", ...).strip("-")`,
  `attempt_execution.py:311-313`), and both forms are additionally prefixed
  with a fixed literal, so `branch_name` can never begin with `-`. `-b`'s
  value is bound positionally in git's own arg parser regardless, so even a
  leading dash there would not be re-interpreted as a flag. `base_commit` is
  a bare positional with no `--` separator before it, but every caller
  supplies an internal revision string (sha or symbolic base), not raw
  external text — traced but not enumerated exhaustively; noting as the one
  soft spot in an otherwise negative result.
- **`daedalus/kernel/promotion.py:308-324`** (`resolve_live_target_revision`,
  `git rev-parse --verify <ref>`) — CONFIRMED SAFE. `target_ref` is passed
  through `_canonical_identifier` → `_identifier()`
  (`daedalus/kernel/contracts/canonical.py:55-62`), which requires the value
  to "start with an alphanumeric character" — a leading `-` is rejected
  before the value ever reaches `subprocess.run`.
- **`daedalus/spine/containment.py:532-556`** (`cmd = ["cmd", "/c", "type",
  str(probe)]`) — CONFIRMED SAFE / intentional. `probe` is a fixed internal
  path (`root / f".control-probe-{token}"`, `token = uuid4().hex`), not
  externally influenced; the docstring explains the deliberate use of a real
  shell here (cross-process visibility probe) rather than treating it as
  sandbox bypass.
- **`daedalus/desktop_runtime.py:1106-1128`** (`_start_remote_service`,
  ssh + fixed `systemctl`/PowerShell command string) — CONFIRMED SAFE.
  `command` is chosen from a hardcoded 2-way ternary keyed on a config enum
  (`method == "systemd"` else a fixed PowerShell string), not built from
  variable text; `self._target()` interpolates `user`/`host` from local
  desktop-runtime config, not model/network input.
- **claude CLI bare-name spawns** (`claude_bridge.py:308-322`,
  `subprocess_adapter.py` `"claude"` profile) — spawn `"claude"` WITHOUT
  `shutil.which()` resolution, unlike codex/gh. `runtime_registry.py:298-299`
  states "`claude`/`ollama` are real .EXEs" on this class of machine (i.e.
  the standalone installer, not an npm shim), which is why these bare-name
  calls currently work at all — if that install assumption changes (e.g. an
  npm-based `claude` install), these become the same WinError-2 availability
  failure mode as codex was before its fix, not a security defect per se.
  Noted as PLAUSIBLE fragility, not a confirmed vulnerability, since I did
  not find evidence claude is ever npm-shimmed in this repo's supported
  install paths.
- **0 instances of `shell=True`** anywhere in `daedalus/`, `tools/`,
  `scripts/` — reproduced.
- **`gates/repository_write_stdlib_delta.py`** — the 10 matches are a
  denylist of forbidden-call NAMES used by a static AST gate scanning other
  code; not itself a spawn site (see Enumeration).

## Overclaim check

Searched for spawn sites whose surrounding docstring/comment claims
"sandboxed"/"bounded"/"isolated"/"policy-checked" language and checked
whether the code backs it:

- `daedalus/kernel/sandbox.py:run_in_docker_sandbox` (`:238-267`) — claim is
  backed: `argv = policy.argv(command)` runs through a `DockerSandboxPolicy`
  object before spawn, has `timeout=policy.timeout_s`, and classifies
  Docker-engine-unreachable failures explicitly rather than swallowing them.
  No overclaim found here.
- `daedalus/adapters/subprocess_adapter.py:create_session` calls
  `begin_effect("adapter.subprocess", ...)` with a `GuardDecision` before
  spawn (`:240-244`) — the effect-boundary gate is real and present (checked
  against `daedalus/spine/effect_boundary.py`'s registry), so this is not a
  hollow claim; it does not, however, validate `extra_args`/`prompt` content
  for shell-metacharacter safety, which is F-W1-03's actual gap — the
  boundary proves the SPAWN is authorized, not that the ARGV is safe from
  cmd.exe reinterpretation. This is a real distinction worth carrying
  forward: "policy-checked" here means authorization, not argv sanitization,
  and nothing in the surrounding prose overclaims the latter.
- No spawn site read in this sweep claimed "sandboxed" language it did not
  back. This is a stated clean negative, not an unexamined one — see list of
  sites read above.

## What I did not cover

- **`scripts/` (63 files)**: not individually traced. All are `run_*_mutations.py`
  fault-injection/mutation-testing harnesses or `fourfold_*_probe.py`
  research probes, confirmed by filename pattern and spot-checking that
  `daedalus/` production code does not import `scripts.*` modules. These are
  developer/CI-invoked tools operating on the repo's OWN source under test,
  not part of any live Daedalus runtime request path, so the argument-
  injection framing (attacker-controlled argv from a mission/model) mostly
  does not apply to them the same way. If another worker's scope includes
  "developer tooling used in CI", these are worth a dedicated pass —
  explicitly flagging the gap rather than silently skipping it.
- **`tools/` (16 files)**: enumerated by filename only; not traced site-by-site
  beyond `daedalus/tools/vet.py` (which IS inside the `daedalus/` count and
  was read — it is itself the static scanner whose denylist is quoted under
  F-W1 Enumeration, not a spawn site of concern). `tools/watchdog.py`,
  `tools/audit_swarm.py`, `tools/gui_check.py`,
  `tools/build_tauri_sidecar.py`/`smoke_tauri_sidecar.py` looked the most
  production-adjacent by name and were NOT opened due to time budget —
  flagging as the highest-value remaining gap in my scope if another worker
  has slack.
- **~60 "skimmed only" `daedalus/` sites** (desktop_runtime SSH/keyscan/keygen,
  most `eval/*.py` and `kairos/*.py` git plumbing, health/doctor/accelerators
  version probes, verifier.py compiler checks): read the call and confirmed
  argv looked fixed/internal at a glance, but did not walk every one to its
  ultimate caller to rule out a distant model-controlled input. Given the
  85%+ pattern observed (git plumbing on internal revisions, `--version`
  probes, fixed local tool invocations), I judge the marginal risk here low,
  but this is a stated scope limit, not a clean-bill claim.
- Did not attempt to build/run anything (per HARD RULES); all argv/validation
  claims are static-reading conclusions, not exercised proof-of-concepts.
