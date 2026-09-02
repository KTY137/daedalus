# W5 — Dynamic-code and deserialization sweep

Scope: `daedalus/`, `tools/`, `scripts/`. Excluded per instructions: `vault/`,
`.quarantine/`, `daedalus/lanes/`, `.claude/worktrees/`, `.daedalus_worktrees/`,
`build/`, `apps/web/src-tauri/backend/`, `apps/web/src-tauri/target/`.
Read-only static review. No files modified other than this one.

## Enumeration

Exact greps run (ripgrep via the Grep tool), each scoped to `daedalus/`,
`tools/`, `scripts/` unless noted:

1. `\bpickle\.|cPickle|\bdill\.|shelve\.|marshal\.|joblib\.load|torch\.load|numpy\.load`
2. `[^.\w]eval\(|[^.\w]exec\(|[^.\w]compile\(|__import__\(|importlib\.import_module|importlib\.util\.spec_from_file_location`
   (first pass used `\beval\(|\bexec\(|\bcompile\(|...` and was heavily
   polluted by `re.compile(`; re-run with a leading non-word-char exclusion)
3. `yaml\.load\(`
4. `ast\.literal_eval` (files_with_matches)
5. `execute\([^)]*%|execute\([^)]*\+|execute\(f["']|executescript\(f["']|cursor\.execute\(f`
6. `autoescape\s*=\s*False|Environment\(.*autoescape`
7. `globals\(\)\[|locals\(\)\[|type\([a-zA-Z_]+,\s*\(|type\([a-zA-Z_]+,\s*bases`
8. `getattr\(\s*[a-zA-Z_.]+,\s*[a-zA-Z_]+(name|_id|type|kind|key)` (-i)
9. `getattr\([a-zA-Z_.]+,\s*(tool_name|action|command|method_name|op_name|handler|provider_name)\b` (-i)
10. `marshal\.loads|pickle\.loads|dill\.loads|dill\.load\(`
11. `sys\.executable.*\.py|python_executable.*\.py` and a check for subprocess
    invocation of a freshly-written candidate `.py` file
12. Follow-up reads of every hit's surrounding code to establish input trust,
    justification, and reachability (see Findings).

### Count table

| Construct | Sites found (production code, in scope) | Justified | Reach model/network input |
|---|---|---|---|
| `pickle`/`cPickle`/`dill`/`shelve`/`marshal`/`joblib.load`/`torch.load`/`numpy.load` | 1 (`marshal.dumps`, serialization not deserialization) | 1/1 | 0/1 |
| `eval(` | 0 | – | – |
| `exec(` | 1 (`daedalus/kairos/gated_writes.py:44`) | 1/1 | 0/1 (repo-internal, hash-pinned) |
| `compile(...)` feeding an `exec` | 1 (same site as above; `compile()` call at line 45) | 1/1 | 0/1 |
| `compile(...)` never exec'd (hash/identity or equivalence use only) | 2 sites (`daedalus/eval/mutate.py:197-198`, `daedalus/runtimes/provider_executable_object_registry.py:1233` used only for `_code_sha256`) | 2/2, explicit docstrings | 0/2 |
| `__import__(` | 4 (`daedalus/integrations/hermes/kernel_provider.py:33,44,56`, `daedalus/integrations/hermes/worker.py:252`) | 4/4 (fixed literal module names) | 0/4 |
| `importlib.import_module` | 8 (`daedalus/accelerators.py:147` inside an embedded child-process probe script; `daedalus/ignition/runner.py:146`; `daedalus/gates/repository_write_classification.py:583,592`; `daedalus/twin/extractors/tree_sitter_adapter.py:123-124`; `daedalus/twin/extractors/root_file_adapter.py:72`) | 8/8 (fixed literal names or dict lookup keyed by an internal enum) | 0/8 |
| `importlib.util.spec_from_file_location` | 2 (`daedalus/eval/graph_delta.py:81`, `daedalus/integrations/hermes/worker.py:85`) | 2/2 | worker.py loads **external vendor source** (pinned, hash-verified, not model/network at runtime); graph_delta.py loads a fixed repo-relative path |
| `getattr()` used for dispatch on a name from data | 0 (all ~40 `getattr(self, field_name)` hits are dataclass-field introspection over the object's own declared fields, or fixed literal tuples/dict lookups — none keyed by model/user/network-supplied strings) | n/a | 0 |
| `yaml.load` without `SafeLoader` | 0 | – | – |
| `ast.literal_eval` (safe pattern) | 2 (`daedalus/spine/receipts.py:1084`, `daedalus/spine/effect_boundary.py:3344-3345`) | good pattern, both parse repo-internal config files (`pyproject.toml`-style) | n/a |
| `type()`/`globals()`/`locals()` dynamic construction from external data | 0 (8 `globals()[name] = value` sites are all PEP-562 lazy-module-attribute idioms keyed by the name Python's own import machinery requests, not external data) | n/a | 0 |
| SQL built by string interpolation into `execute()` | 6 (`daedalus/health.py:835`; `daedalus/runtimes/provider_observation_store.py:342`; `daedalus/kernel/events/ledger.py:334,352,444`, plus `provider_observation_store.py:533`) | 6/6 — all `PRAGMA`/introspection statements (sqlite gives no parameter placeholder for `PRAGMA` or identifiers); interpolated values are either hardcoded literal table names at the call site, table names read back from `sqlite_master` of the same self-owned local DB file, or `int()`-cast integers | 0/6 |
| Template rendering with autoescape disabled | 0 | – | – |
| `subprocess` of a generated `.py` file | 0 matched (no site writes a `.py` file and then subprocess-executes it) | – | – |

Total sites requiring individual write-up below: 4 (the ones with any nuance
worth a reviewer's attention). Everything else in the table above is a clean
negative already explained inline.

## Findings

### F-W5-01 Hermes worker `exec_module`s pinned upstream vendor source
- **file:line**: `daedalus/integrations/hermes/worker.py:83-97` (`_load_upstream`) and `daedalus/integrations/hermes/worker.py:237-243,255-261` (`_verify_worker_source`, `main`)
- **class**: dynamic-exec
- **severity**: INFO (justified, but flagged because it is the one real code-loading site outside `provider_executable_object_registry.py`)
- **status**: CONFIRMED with quoted code
- **evidence**:
  ```python
  def _load_upstream(checkout_root: Path) -> ModuleType:
      path = checkout_root / "run_agent.py"
      spec = importlib.util.spec_from_file_location("daedalus_pinned_hermes_run_agent", path)
      ...
      spec.loader.exec_module(module)
  ```
  ```python
  def _verify_worker_source(checkout_root: Path, request: Mapping[str, object]) -> None:
      run_agent = checkout_root / "run_agent.py"
      ...
      digest = sha256(run_agent.read_bytes()).hexdigest()
      if digest != request["run_agent_sha256"]:
          raise HermesWorkerError("run_agent.py changed between parent verification and worker import")
  ```
  The expected digest is a hardcoded constant in `daedalus/integrations/hermes/configuration.py:96`:
  `run_agent_sha256="b8e0244cfdbdce9328040d92adb9b89d78351000ee88bafae35d71b3e33fb8a1"` bound to a
  named upstream release (`NousResearch/hermes-agent`, tag `v2026.8.19`, commit `fcbd107...`) whose
  `repository` field is hard-refused to anything but that exact string
  (`HermesPinnedSource.__post_init__`, configuration.py:57-58).
- **input-trust-class**: external vendor source, but pinned by SHA-256 at rest and re-verified
  byte-for-byte immediately before `exec_module` (TOCTOU window between the two checks is the
  filesystem itself, not attacker input). Not model output, not live network content at
  invocation time.
- **reachability**: reachable from the Hermes provider path (`HermesKernelProvider.invoke_authenticated`
  → `run_runtime_provider` → spawns this worker subprocess). This is the declared, justified
  containment path (`daedalus/integrations/hermes/__init__.py` docstring names "containment, gateway
  and broker subjects" and the outer `HermesSandboxProfile.command_prefix` is meant to wrap the
  worker process). No overclaim found in the docstrings near this code — they describe pinning and
  hash verification, not "sandboxed"/"safe" without a mechanism.

### F-W5-02 `HermesSandboxProfile` default constructor silently disables containment
- **file:line**: `daedalus/integrations/hermes/configuration.py:117-134,183-184`
- **class**: overclaim / unsafe-default (adjacent to dynamic-exec F-W5-01: this is the guard that is
  supposed to gate whether the pinned upstream source above runs inside an outer sandbox command)
- **severity**: LOW-MEDIUM (latent, not currently reachable from a production entrypoint — see below)
- **status**: CONFIRMED with quoted code; reachability is PLAUSIBLE-negative (I could not find a
  live caller that hits the unsafe default)
- **evidence**:
  ```python
  @dataclass(frozen=True)
  class HermesSandboxProfile:
      command_prefix: tuple[str, ...]
      ...
      test_only_uncontained: bool = False

      def __post_init__(self) -> None:
          ...
          if not self.command_prefix and not self.test_only_uncontained:
              raise HermesConfigurationError("production Hermes execution requires an outer sandbox command")
  ```
  ```python
  @dataclass(frozen=True)
  class HermesRuntimeConfig:
      ...
      sandbox: HermesSandboxProfile = field(
          default_factory=lambda: HermesSandboxProfile(command_prefix=(), test_only_uncontained=True)
      )
  ```
  Constructing `HermesRuntimeConfig(checkout_root=..., python_executable=...)` **without** an
  explicit `sandbox=` argument produces `command_prefix=()` and `test_only_uncontained=True`, which
  is exactly the combination the `__post_init__` guard is designed to refuse for production
  ("production Hermes execution requires an outer sandbox command") — the default silently opts
  into the escape hatch instead of raising.
- **input-trust-class**: n/a — this is a code-level default, not attacker input.
- **reachability**: The only production construction path found is
  `HermesRuntimeConfig.from_metadata` (`configuration.py:238-278`), which requires the wire payload
  to contain an *exact* field set including `"sandbox"` (`if set(value) != exact: raise`), so the
  default factory is never consulted on that path. The only call sites that construct
  `HermesRuntimeConfig(...)` positionally/by-keyword and could hit the risky default are in
  `tests/integrations/test_hermes_runtime_adapter.py` and
  `tests/integrations/test_hermes_kernel_provider.py` (both out of my scope, but confirm the shape
  is reachable if any future non-test caller constructs the dataclass directly instead of going
  through `from_metadata`). Reported because a fail-open default on a safety-relevant dataclass is
  exactly the kind of thing this repo's own review rules call release-blocking when it becomes
  reachable, and nothing today stops a future caller from doing `HermesRuntimeConfig(checkout_root=x,
  python_executable=y)` directly.

### F-W5-03 `daedalus/kairos/gated_writes.py` execs a hash-pinned retained module (informational)
- **file:line**: `daedalus/kairos/gated_writes.py:42-47`
- **class**: dynamic-exec
- **severity**: INFO (well justified)
- **status**: CONFIRMED with quoted code
- **evidence**:
  ```python
  _retained_source = _resource_files(__package__).joinpath(_RETAINED_SOURCE_NAME)
  _retained_source_bytes = _verify_retained_source(_retained_source.read_bytes())
  exec(
      compile(_retained_source_bytes, str(_retained_source), "exec"),
      globals(),
  )
  ```
  `_verify_retained_source` computes the Git blob SHA-1 of the packaged resource and compares it
  with `hmac.compare_digest` against a hardcoded constant
  (`_RETAINED_SOURCE_GIT_BLOB_SHA1 = "0783f7e68e22f9c8e6c687a42e3b8ef294fb57c2"`), refusing to run
  anything but the exact committed blob.
- **input-trust-class**: repo-internal packaged resource, integrity-pinned against a value committed
  in this same source tree.
- **reachability**: imported at module load time by anything that imports
  `daedalus.kairos.gated_writes` (the promotion seam). This is the sole `eval(`/`exec(` call in the
  entire scope. The docstring is accurate about what it does and does not claim "sandboxed" or
  "safe" beyond the integrity check it actually performs — not an overclaim.

### F-W5-04 Gate-1 sealed provider execution path (negative finding, noted because it is the system's main dynamic-exec surface)
- **file:line**: `daedalus/runtimes/provider_executable_object_registry.py` (whole module, ~2637 lines)
- **class**: n/a — reviewed for overclaim and found none
- **severity**: n/a (clean)
- **status**: CONFIRMED clean by reading; this module never calls `eval`/`exec` on arbitrary text —
  its only `compile()` call (line 1233, inside `_compiled_target_code`) recompiles already-authenticated
  repository source purely to compute a bytecode SHA-256 for identity comparison
  (`_code_sha256`), and the `types.FunctionType(...)` clones at lines 1455, 1573, 1805 rebind an
  **already-loaded, already-verified** function's existing `__code__` object into a namespace with a
  detached builtins snapshot and a `_SealedImporter` that only admits `hashlib.sha256`,
  `json.{JSONDecodeError,dumps,loads}`, and `subprocess.run` (`_SEALED_IMPORT_MEMBERS`,
  lines 89-95). No caller-selected callable crosses this seam per the module's own docstring, and
  that claim matches what the code does: dispatch to the sealed function is entrypoint-gated by an
  authenticated `pre_admission` receipt, not by attacker-chosen strings.
- **input-trust-class**: repository-internal (module source files under `daedalus/`), verified by
  bytecode hash against the pre-admission receipt before any clone is invoked.
- **reachability**: this is the canonical Gate-1 broker execution path (`_invoke_hermes_payload` in
  `kernel_provider.py` is one of the sealed operations registered against it). Reported here as a
  clean negative because the priority instructions specifically call out that model-generated-code
  execution is expected in this product and only an unsandboxed or overclaiming instance would be a
  finding — this instance is neither.

## What I did not cover

- General `subprocess.run`/`Popen` auditing beyond the specific "subprocess of a generated `.py`
  file" pattern (46 files call `subprocess.*` in `daedalus/`) — out of my 8-construct scope; likely
  covered by an egress/sandbox-focused worker.
- `pickle.loads` usage in `tests/` (11+ hits, e.g. `tests/kernel/test_contract_hierarchy.py`,
  `tests/runtimes/test_claude_provider_strangler_architecture.py`) — explicitly out of scope
  (`tests/` is not in `daedalus/`, `tools/`, or `scripts/`); flagging here only so a reviewer with
  test-scope knows it exists. These appear to be intentional pickle-identity/back-compat tests
  (`pickle.loads(pickle.dumps(x)) == x`, or fixed pickle byte-string literals asserting a moved
  class still resolves) rather than deserialization of untrusted data.
- `apps/web/` (JS/TS, out of scope for a Python-construct sweep) and the explicitly excluded
  `vault/`, `.quarantine/`, `daedalus/lanes/`, worktree/build/target duplicate trees.
- Did not attempt to enumerate every one of the ~40 `getattr(self, field_name)` call sites
  individually in this document — verified a representative sample plus grep-pattern coverage
  showing they all iterate a `dataclasses.fields()`-derived or literal-tuple `field_name`, never a
  string taken from a request/payload/model-output variable (confirmed via a second targeted grep
  for `getattr(..., tool_name|action|command|method_name|op_name|handler|provider_name)` which
  returned zero hits).
- Did not independently verify `run_agent_sha256` in `configuration.py:96` actually matches the
  named upstream release's real `run_agent.py` byte-for-byte (would require fetching the pinned
  GitHub release, which is a network call outside a read-only static sweep) — noted as an assumption
  a reviewer with network access may want to confirm.
