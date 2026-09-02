# daedalus/desktop_runtime.py

## 1. Size and shape

1,256 lines (`wc -l` = 1256, matches the size the most recent strangler
work packet claims it reduced to — see §5). 2 top-level classes,
14 top-level functions, 49 class methods (65 `class`/`def` sites total):

- `class DesktopRuntimeError(RuntimeError)` — `:164`
- `class DesktopRuntimeManager` — `:312` (49 methods)
- 14 module-level functions: `_frozen_windows_runtime_root`,
  `_path_is_within`, `_ollama_child_environment`,
  `_set_windows_dll_directory`, `_spawn_ollama_process`, `_defaults`,
  `_port`, `_loopback_endpoint`, `_ide_endpoint`, `_numeric_host`,
  `_pid_is_alive`, `normalize_config`, `install_tunnel_egress_policy`,
  `install_web_integration`.

Module-level state/singletons (`daedalus/desktop_runtime.py:41-60`):
- `CONFIG_REL = Path("config/connections.json")` (`:41`), `KNOWN_HOSTS_REL`
  (`:42`), `LOG_REL = Path("runs/desktop_runtime.log")` (`:43`) — path
  constants, no I/O at import.
- `TUNNEL_FORWARD_VAR`, `TUNNEL_TARGET_VAR`, `REMOTE_OK_VAR`,
  `TRUSTED_HOSTS_VAR` (`:45-48`) — env-var name constants (strings), not
  reads.
- `IDE_DOCKER_CONTAINER`, `IDE_DOCKER_WORKSPACE`, `IDE_DOCKER_IMAGE`
  (from `desktop_configuration.DEFAULT_IDE_DOCKER_IMAGE`, `:52`),
  `IDE_DOCKER_OWNER_LABEL`, `IDE_DOCKER_OWNER_VALUE`,
  `IDE_DOCKER_PROJECT_LABEL` (`:50-55`).
- `DEFAULT_CONFIG: dict[str, Any] = desktop_configuration.DEFAULT_CONFIG`
  (`:57`) — module-level alias binding, evaluated at import (reads a
  constant from `daedalus.interfaces.desktop.configuration`, no I/O).
- `_DOCKER_CONTAINER_ID_RE = re.compile(...)` (`:59`) — regex compile,
  no I/O.
- `_DLL_DIRECTORY_LOCK = threading.Lock()` (`:60`) — module-level
  `threading.Lock` singleton, guarding the Windows `SetDllDirectoryW`
  critical section (`_spawn_ollama_process`, `:116-161`).

**No module-level side effect performs file reads, env reads, registry
mutation, network access, or path creation at import time.** All of
that happens inside `DesktopRuntimeManager.__init__` (`:313-342`), which
is only executed when a caller explicitly instantiates the manager
(confirmed: `grep -n "^[a-zA-Z_]* = DesktopRuntimeManager"` on the file
finds no module-level instantiation — the class is never constructed at
import time). `__init__` itself does perform effects once called: it
reads `TRUSTED_HOSTS_VAR` from `os.environ` (`:332`), reads budget/caps
environment defaults (`:335-339`), loads `config/connections.json`
(`:340`, via `_load`), calls `apply_environment()` (`:341`, which
mutates `os.environ`), and registers `atexit.register(self.close)`
(`:342`) — but none of this runs merely by `import daedalus.desktop_runtime`.

## 2. What it does

`daedalus/desktop_runtime.py` is the desktop application's process/effect
facade: `DesktopRuntimeManager` owns the lifecycle of the file bridge
watcher thread, the local or SSH-tunneled Ollama subprocess, and the
OpenVSCode Server (native process or Docker container), including
config load/save, environment projection, execution-limit policy
application, and a single `install_web_integration` entrypoint that
extends the existing `web_api` HTTP server rather than starting a
second one. It is deliberately the sole owner of every genuinely
effectful primitive in this area — spawning `ManagedProcess`/`Popen`,
starting `threading.Thread`s, pinning SSH host keys via
`ssh-keyscan`/`ssh-keygen`, and managing Docker container identity by
label/mount/port-binding matching — while delegating pure
configuration, settings I/O, and read-only status projection to
implementation-owner modules under `daedalus.interfaces.desktop`. It is
the live entrypoint used by the packaged desktop sidecar
(`scripts/daedalus_desktop_sidecar.py`), not a legacy file left behind
by a completed migration.

## 3. Who imports it (MEASURED)

**TOTAL: 6 importers**, restricted to git-tracked files, using the
methodology from the task (all import forms plus bare-string form).
Commands run:

```
git grep -n -E "from daedalus\.desktop_runtime|from daedalus import[^;]*\bdesktop_runtime\b|import daedalus\.desktop_runtime|from \.desktop_runtime import|from \. import[^;]*\bdesktop_runtime\b|importlib\.import_module\([\"']daedalus\.desktop_runtime" -- "*.py"
git grep -n "daedalus.desktop_runtime" -- "*.py" "*.json" "*.md" "*.toml"
```

| Importer | Line | Form | MODULE-LEVEL / DEFERRED |
| --- | --- | --- | --- |
| `scripts/daedalus_desktop_sidecar.py` | `:109` | `from daedalus.desktop_runtime import (DesktopRuntimeManager, install_tunnel_egress_policy, install_web_integration)` | **DEFERRED** — inside `main()`, after `daedalus.env.load_env(...)` (see the `dotenv` dossier for that duplicate-loader finding) and before `daedalus.web_api` is imported. This is the packaged desktop entrypoint. |
| `tests/interfaces/test_desktop_configuration_owner.py` | `:12` | `from daedalus import desktop_runtime` | MODULE-LEVEL, TEST-ONLY. |
| `tests/interfaces/test_desktop_settings_owner.py` | `:14` | `from daedalus import desktop_runtime` | MODULE-LEVEL, TEST-ONLY. |
| `tests/interfaces/test_desktop_strangler_architecture.py` | `:13` | `from daedalus import desktop_runtime` | MODULE-LEVEL, TEST-ONLY — this is the architecture-contract test pinning the strangler boundary (see §5). |
| `tests/test_desktop_runtime.py` | `:15` | `from daedalus import desktop_runtime as desktop_runtime_module` | MODULE-LEVEL, TEST-ONLY. |
| `tests/test_desktop_runtime.py` | `:26` | `from daedalus.desktop_runtime import (...)` | MODULE-LEVEL, TEST-ONLY. |

Per-layer breakdown: **1 production/scripts caller** (the desktop
sidecar), **5 test-only references across 4 test files** (`scripts/`
and `tests/` are not layers in the target taxonomy — I report them as
their own bucket). **Zero importers from anywhere under `daedalus/`
itself** — this matches the task's cross-check exactly (6 = 5 tests + 1
under `scripts/`; zero from `daedalus/`).

Additional bare-string (non-import) references to
`"daedalus.desktop_runtime"` found tree-wide, all either
self-referential architecture machinery or test assertions, none a
new functional caller:
- `daedalus/interfaces/desktop/__init__.py:4,32` — docstring plus the
  `import_module("daedalus.desktop_runtime")` lazy-facade call inside
  `__getattr__` (`:32`). This is the ONE sanctioned runtime-string
  back-reference; `tests/interfaces/test_desktop_strangler_architecture.py:308-319`
  (`test_only_documented_runtime_string_import_points_back_to_facade`)
  asserts by AST walk that it is the *only* `import_module("daedalus.desktop_runtime")`
  call in `daedalus/interfaces/desktop/__init__.py`.
- `daedalus/interfaces/desktop/configuration.py:4` and
  `daedalus/interfaces/desktop/settings.py:3` — docstring prose stating
  `daedalus.desktop_runtime` "remains the compatibility/stable...
  facade" (not a code reference).
- `daedalus/kernel/events/envelope.py:722` — a classification-registry
  entry stating `daedalus/desktop_runtime.py`'s own output artifacts
  (`config/connections.json`, `config/known_hosts`,
  `runs/desktop_runtime.log`) are "OPERATOR CONFIGURATION, NOT A RUN
  RECORD" (metadata about the module, not a caller).
- `docs/architecture/import-boundaries.json:73` — the
  `spine-no-outer-layers` forbidden-target-prefix entry (see §6, the
  mandatory finding).
- `tests/contracts/test_spine_outer_ports.py:77`,
  `tests/interfaces/test_desktop_configuration_owner.py:309`,
  `tests/interfaces/test_desktop_settings_owner.py:255`,
  `tests/interfaces/test_desktop_strangler_architecture.py:127,201,204,319`,
  `tests/test_desktop_runtime.py:1086,1325,1332,1342,1393,1453,1484,1486,1581,1590,1642,1709` —
  all test-only string literals (mostly `monkeypatch.setattr("daedalus.desktop_runtime.X", ...)`
  targets, or AST-assertion string comparisons in the strangler test).
- `docs/work-packets/G1-IFACE-DESKTOP-01/02/03_*.md`,
  `G1-DESKTOP-14_ORPHAN_SAFE_BACKEND_STARTUP.json`,
  `G1-ARIADNE-01_CANONICAL_CAMPAIGN_REHEARSAL.md`,
  `G1-IDE-13_REGISTERED_IDE_PROJECT_AUTHORIZATION.md` — work-packet
  documentation, not code.

## 4. What it imports (MEASURED)

All `daedalus.*` imports, by scope:

**MODULE-LEVEL (9 edges):**

| Import | Line | Target layer |
| --- | --- | --- |
| `from . import budget as budget_kernel` | `:23` | foundation (declared) |
| `from . import runtime_registry` | `:24` | flat (unclassified, not foundation, not SCC) |
| `from .interfaces.desktop import configuration as desktop_configuration` | `:25` | interfaces/desktop |
| `from .interfaces.desktop import http as desktop_http` | `:26` | interfaces/desktop |
| `from .interfaces.desktop import lifecycle as desktop_lifecycle` | `:27` | interfaces/desktop |
| `from .interfaces.desktop import projection as desktop_projection` | `:28` | interfaces/desktop |
| `from .interfaces.desktop import settings as desktop_settings` | `:29` | interfaces/desktop |
| `from .limit_policy import (ENV_EXECUTION_LIMIT_POLICY, ExecutionLimitPolicy, LimitAxes, LimitPolicyError, MODE_CUSTOM, store_in_env as store_limit_policy_in_env)` | `:30-37` | foundation (declared) |
| `from .projects import ProjectRegistryUnavailable, resolve_registered_project_root` | `:38` | flat (unclassified, not foundation, not SCC) |
| `from .spine.cancel import ManagedProcess` | `:39` | spine |

**DEFERRED (4 edges, all function-scope):**

| Import | Line | Inside | Target layer |
| --- | --- | --- | --- |
| `from . import sensitivity` | `:295` | `install_tunnel_egress_policy` | foundation (declared) |
| `from . import file_bridge` | `:425` | `_watch_bridge` | **SCC-owned** (11-module SCC named in task; not classified here per instruction) |
| `from . import file_bridge` | `:447` | `ensure_bridge` | SCC-owned |
| `from . import file_bridge` | `:1236` | `snapshot` | SCC-owned |

**Grouped counts by target layer:** foundation 3 (budget, limit_policy,
sensitivity), interfaces/desktop 5 (configuration, http, lifecycle,
projection, settings), spine 1 (cancel.ManagedProcess), SCC-owned 3
edges / 1 module (file_bridge, all deferred), flat/unclassified 2
(runtime_registry, projects) — 13 `daedalus.*` import statements total
(9 module-level + 4 deferred).

**Third-party imports:** none. Full non-`daedalus` import list
(`:4-21`) is entirely standard library: `atexit`, `hashlib`, `hmac`,
`json`, `os`, `re`, `shutil`, `subprocess`, `sys`, `tempfile`,
`threading`, `time`, `urllib.error`, `urllib.request`, `uuid`,
`pathlib.Path`, `typing.Any`, `urllib.parse.{urlencode, urlsplit}`.
Plus a deferred stdlib import: `ctypes` inside
`_set_windows_dll_directory` (`:105`) and inside `_pid_is_alive`'s
Windows branch (`:223-224`).

## 5. Proposed destination

**keep-flat-as-registered-shim-in-progress** (not one of the eight
named terminal destinations, and deliberately so — see argument below).
If forced to pick from the fixed menu: **interfaces/desktop**, but
**not yet**, and not by simple relocation. Confidence: **high** that it
should NOT move today; **medium** on the long-run terminal layer.

Argument from measured evidence: `daedalus/desktop_runtime.py` is not
a stale duplicate of `daedalus/interfaces/desktop/` — it is the
**source** of that package, mid-strangler. `daedalus/interfaces/desktop/`
was created by three owner-approved, dependency-chained work packets
(`docs/work-packets/G1-IFACE-DESKTOP-01/02/03_*.md`) that explicitly
state, each time, that `daedalus.desktop_runtime` "remains the stable
[sidecar/CLI/effect/process] facade" while individual responsibilities
(`http` composition, `projection` snapshots, `lifecycle`
bootstrap/close, `configuration` defaults/validation, `settings`
load/save) are extracted one packet at a time. The file's own size
history proves this directly: 1,964 lines (frozen base before
G1-IFACE-DESKTOP-01) → 1,719 (after 01) → 1,483 (after 02) → **1,256
(current, matches `wc -l` exactly)** after 03
(`git log --follow -- daedalus/desktop_runtime.py`: `bacd9e6e`,
`0ce7414a`, `08fcc512`, all dated 2026-08-31, one day before this
audit's baseline). This is an **active, measured, in-flight
migration**, not dead weight.

The relationship is also directionally locked and test-enforced
(`tests/interfaces/test_desktop_strangler_architecture.py`,
`test_implementation_owners_do_not_mint_process_http_or_effect_authority`,
`:181-214`): the five `daedalus.interfaces.desktop.*` implementation
modules are AST-asserted to (a) never import `daedalus.desktop_runtime`
themselves, and (b) never call `ManagedProcess`, `Popen`, `Thread`,
`ThreadingHTTPServer`, `begin_effect`, or `serve_forever`, and never
define `DesktopRuntimeManager`/`main`/`run`. `desktop_runtime.py` is
therefore, by test-enforced contract, the **only** place in this whole
package tree that is currently allowed to spawn processes, open
sockets, start threads, or acquire effect leases for the desktop
surface. Moving the file wholesale into `daedalus/interfaces/desktop/`
today, before the strangler series completes and re-authorizes that
authority somewhere, would either violate this test outright or require
rewriting it — a decision this static audit should surface, not make.

What would change my mind, and to what: once a fourth (currently
unwritten) packet moves the actual process/effect-spawning
authority — `DesktopRuntimeManager`'s `_watch_bridge`/`ensure_bridge`,
`ensure_ide`/`_ensure_docker_ide`, `ensure_local_ollama`/`ensure_remote_ollama`,
`install_web_integration` — into `daedalus.interfaces.desktop` and
retires the flat facade (deleting `daedalus/desktop_runtime.py` or
reducing it to a thin `__getattr__`-only re-export symmetric with
`daedalus/interfaces/desktop/__init__.py`'s own compat layer), the
terminal destination is unambiguously **interfaces/desktop**. Until
that packet lands and the strangler test suite is rewritten to match,
recommending an immediate physical move is recommending a documented,
in-progress owner plan be short-circuited outside its own review chain.

No split-boundary proposal beyond what the owner has already frozen
into the G1-IFACE-DESKTOP-0{1,2,3} packet boundaries (http /
projection / lifecycle / configuration / settings) — those are already
the measured, tested split.

## 6. Boundary-rule check after the move

**(b) Does any CURRENT rule name this module by prefix? — MANDATORY, answered first.**

**Yes.** `docs/architecture/import-boundaries.json:73`, rule
`spine-no-outer-layers`, lists `daedalus.desktop_runtime` explicitly in
`forbidden_target_prefixes` (source `daedalus.spine`). Verified by
reading the full rule text (`:64-102`): the rule's own rationale
explains its forbidden list exists because "the event spine is
canonical infrastructure and cannot depend on product, orchestration,
evaluator, provider, runtime, or interface implementations" and that
the checker "walks the whole AST" so it sees deferred imports too.

**What breaks / is silently un-forbidden on the move — this is the
highest-value finding in this dossier:**

If `daedalus/desktop_runtime.py` (or the process/effect authority
currently inside it — `_spawn_ollama_process`'s `ManagedProcess`
construction, `ensure_bridge`'s `threading.Thread`, `install_web_integration`'s
HTTP-handler wiring) is relocated into `daedalus/interfaces/desktop/`
and the flat name `daedalus.desktop_runtime` stops existing as a source
of that code, the string `"daedalus.desktop_runtime"` in
`spine-no-outer-layers`'s forbidden list becomes **permanently
unreachable** — there is no longer any module at that import path for
a `daedalus.spine` import to name. The rule does not error or warn on
a dead forbidden-prefix entry; it simply never fires for it again.

Critically, **`daedalus.interfaces` is not a forbidden prefix in this
rule, or in any of the four rules in `import-boundaries.json`** (see
part (d) below) — I read the full 19-entry forbidden list for
`spine-no-outer-layers` (`:68-89`: `build`, `build_exec`, `chip_design`,
`core`, `desktop_runtime`, `eval`, `file_bridge`, `gates`, `ikarus`,
`ikarus_os`, `integrations`, `kairos`, `loop`, `offload`,
`orchestration`, `providers`, `runtimes`, `schemas`, `twin`,
`web_api`) and confirmed no `daedalus.interfaces` or
`daedalus.interfaces.desktop` entry exists anywhere in the file. So a
`daedalus/spine/*.py` module could, after such a move, freely write
`from daedalus.interfaces.desktop import lifecycle` (or any of the
other four now-relocated implementation modules) and reach exactly the
subprocess-spawning, thread-starting, HTTP-server-extending code this
rule was written to keep out of the spine — completely unconstrained,
and the boundary checker would report green throughout, exactly the
"one-hop launder" failure pattern the rule's own rationale text
(`:100`) already documents happened once before with
`daedalus.schemas` (MEASURED at `4c370f2ad757da82eacb2b231d050d1baeb85212`:
`daedalus.spine.receipts` cold-imported 13 forbidden modules through
that one facade while the rule stayed green). This is the same defect
shape recurring at a different prefix, and it is **prospective, not yet
triggered**: today `daedalus.spine` imports nothing under
`daedalus.interfaces` or `daedalus.desktop_runtime`
(`git grep -n "desktop_runtime\|interfaces\.desktop" -- daedalus/spine/*.py` was not
separately re-verified in this pass beyond the rule's own file-scoped
audit trail — treat that specific zero-count claim as UNVERIFIED by me
directly, since it is a claim about `daedalus/spine/` sources rather
than about `desktop_runtime.py`, which is this dossier's assigned
scope).

Answer, stated directly as the prompt requires: **yes, moving
`daedalus.desktop_runtime`'s effectful authority into
`daedalus.interfaces.desktop` silently un-forbids it from the spine's
perspective**, because `daedalus.interfaces` carries no constraint of
its own in any current rule. The fix is not "don't move it" forever —
the strangler plan in §5 is a legitimate, owner-approved trajectory —
it is that **the move must be paired with either adding
`daedalus.interfaces.desktop` (or `daedalus.interfaces` generally) to
`spine-no-outer-layers`'s forbidden list, or an explicit owner decision
that spine-vs-desktop-effects was never actually the risk the rule
modeled.** That decision belongs to whoever owns G1-HIER (the
boundary-contract packet series), not to this read-only audit.

**(a) Moved to `interfaces/desktop` (the terminal destination from
§5): would any of ITS OWN imports be refused?** No rule in
`import-boundaries.json` currently uses `daedalus.interfaces` (or
`daedalus.interfaces.desktop`) as a `source_prefixes` entry (confirmed
by reading all four rules), so none of `desktop_runtime.py`'s 13
`daedalus.*` imports (§4) — including its one `daedalus.spine.cancel`
edge and its deferred `daedalus.file_bridge` edges — would be refused
by any existing rule if the file's source prefix became
`daedalus.interfaces.desktop`. This is not evidence the move is safe
(see (b) above — the danger runs the other direction, from spine
INTO interfaces/desktop, not from desktop_runtime's own outbound
imports).

**(c) If it lands in kernel/spine/twin: which flat imports would be
refused?** N/A directly — §5's proposed destination is
interfaces/desktop, not kernel/spine/twin, and nothing in this dossier
argues for those three. For completeness, if it were hypothetically
placed as a `daedalus.kernel`, `daedalus.spine`, or `daedalus.twin`
source: `spine-no-outer-layers`' allowlist (`atomic, budget, config,
kernel, limit_policy, mapping, sensitivity, structcore`) would refuse
its `daedalus.interfaces.desktop.*` imports (5 edges, not on the
allowlist), its `daedalus.projects` import (not on the allowlist), its
`daedalus.runtime_registry` import (not on the allowlist), and its
deferred `daedalus.file_bridge` imports (not on the allowlist) — only
`budget`, `limit_policy`, and `sensitivity` would be allowed.
`kernel-no-outer-layers`' and `twin-no-outer-layers`' allowlists
(narrower still — no `mapping`, no `structcore` overlap issue here,
but also no `interfaces`, `projects`, `runtime_registry`, or
`file_bridge`) would refuse the same set. This module could not
legally become a `kernel`, `spine`, or `twin` source without first
losing 7 of its 13 `daedalus.*` imports — strong independent evidence
against those three destinations, consistent with §5's conclusion.

**(d) No rule currently constrains `daedalus.interfaces` as a SOURCE —
confirmed.** Read all four rules in full; none uses `daedalus.interfaces`
as a `source_prefixes` value. This is exactly the mechanism analyzed in
(b): an `interfaces/*` move launders the `daedalus.desktop_runtime`
forbidden prefix behind a currently-unconstrained one, because nothing
stops `daedalus.interfaces.desktop` code from being imported BY the
spine, and nothing stops `daedalus.interfaces.desktop` code FROM
importing outer layers either (it already does, by design — 5 edges
into itself plus whatever `daedalus.interfaces.desktop.*` implementation
modules import on their own, which is out of this dossier's assigned
scope to enumerate). Both directions are open. Confirmed, explicit
answer: **yes, an interfaces/* move launders a forbidden prefix behind
an unconstrained one**, for this module specifically, today.

## 7. Dead-code signals

**Label: LIVE.** Not a dead-code candidate by any measure:

- **Promised/actual reader**: `scripts/daedalus_desktop_sidecar.py:109`
  imports `DesktopRuntimeManager`, `install_tunnel_egress_policy`,
  `install_web_integration` from it inside `main()` and immediately
  instantiates/calls all three (`:114-122`) — this is the packaged
  desktop application's real startup path, not a docstring promise.
- **Architecture-test-pinned**: `tests/interfaces/test_desktop_strangler_architecture.py`
  contains 8 test functions that AST-verify specific facts about this
  exact file (retained methods, delegate bounds, banned calls in its
  extracted siblings, Effect Registry digest stability,
  `registry_sha256() == "ac02...96211ec"`, literal-digest pinning of
  HTTP route JSON) — a test suite actively asserting this file's shape
  cannot be read as evidence of a stale or unwired module.
- **Registered as a live governance object, not a shim**: it does NOT
  appear in `docs/architecture/shim-registry.json` (`git grep -n
  "desktop_runtime" docs/architecture/shim-registry.json` → no output)
  — unlike `daedalus.decompose` or `daedalus.file_bridge`, it is not
  classified as a compatibility re-export awaiting removal; it is
  classified in `import-boundaries.json` as a forbidden-for-spine
  effectful module, and in `daedalus/kernel/events/envelope.py:722` as
  a legitimate non-run-record configuration/log owner.
- **Effect Registry**: `test_registered_effect_targets_and_digest_are_unchanged`
  (`test_desktop_strangler_architecture.py:107-119`) pins that
  `daedalus.web_api` Effect Registry rows (`web.server`,
  `web.mutations`, `cli.web_api`, `web.mutations_put`) are unchanged by
  this file's presence — `desktop_runtime.py` itself does not register
  new Effect Registry entrypoints (`git grep -n "desktop_runtime" --
  daedalus/spine/effect_boundary.py` → no output), it extends the
  existing `web_api` server via `install_web_integration` instead,
  consistent with the module's own docstring ("Add desktop routes
  without creating a second HTTP/control server", `:1247`).
- **Git history**: 8 commits, all dated 2026-08-30/31 — i.e. this file
  was actively developed and restructured in the 48 hours immediately
  before the 2026-09-01 master-plan revision this repository is
  currently operating under, and the size reduction sequence (1,964 →
  1,719 → 1,483 → 1,256) is a live, ongoing, owner-directed
  decomposition, not orphaned legacy code.

Not evaluated as CANDIDATE-DELETE, UNWIRED-WITH-PROMISED-READER, or
TEST-ONLY: none of those labels fit a module with a real, current,
non-test production caller and an active governing test/work-packet
chain.
