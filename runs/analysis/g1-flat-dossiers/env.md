# daedalus/env.py

## 1. Size and shape

89 lines (`wc -l daedalus/env.py` = 89). Zero classes, three top-level
functions, zero methods:

- `def _parse_env_line(line: str) -> tuple[str, str] | None` (private) — `:31`
- `def load_env(path=None, *, override=False) -> dict[str, Any]` — `:45`
- `def env_status(path=None, loaded_keys=None) -> dict[str, Any]` — `:65`

Module-level state (`:13-28`): `ROOT = Path(__file__).resolve().parents[1]`
(`:13`, pure path arithmetic — `resolve()` touches the filesystem to
normalize but does not read `.env`), `ENV_PATH = ROOT / ".env"` (`:14`),
`SECRET_KEYS` (`:16-20`, a 3-tuple of provider API-key env-var names) and
`PUBLIC_KEYS` (`:22-28`, a 5-tuple of non-secret config env-var names).
No import-time file reads, no import-time `os.environ` reads (all
`os.environ.get(...)` calls are inside `load_env`/`env_status` function
bodies, `:59-87`), no registry mutation, no network, no singleton mutable
container. Confirmed by reading the whole file (`Read` tool, full 89
lines) — nothing executes at import beyond two `Path` computations and
four literal tuple/constant assignments.

## 2. What it does

`daedalus/env.py` parses a `.env` file at the repo root (`KEY=value` lines,
`#` comments, quote-stripping) and fills gaps in `os.environ`, never
overwriting an existing value unless `override=True` is passed. It exposes
`env_status()`, which returns REDACTED provider-readiness metadata (booleans
and non-secret URLs/model names for `ollama`, `deepseek`, `anthropic_api`,
`openai_api`) built entirely from `os.environ` at call time, explicitly so
the web UI and VS Code wrapper can show configuration status without ever
receiving a secret value (module docstring, `:1-6`). It is deliberately not
a general dotenv library: no interpolation, no multi-line values, no
`export` prefix handling (contrast `daedalus/dotenv.py`, see §5).

## 3. Who imports it (MEASURED)

**TOTAL: 7 importers**, all git-tracked. Commands run (restricted to
`git ls-files -- '*.py'`, ripgrep honors `.gitignore`/`.git/info/exclude`
by default so `.daedalus_worktrees/` and `.claude/worktrees/` are already
excluded — confirmed both are ignored: `git check-ignore -v
.daedalus_worktrees` → matched by `.gitignore:68`; `git check-ignore -v
.claude/worktrees` → matched by `.git/info/exclude:11`):

```
rg -n 'daedalus\.env\b|from \.env import|from \. import env\b|"daedalus\.env"' --glob '*.py'
rg -n '\benv\b' -i daedalus/interfaces   # caught the 3-dot relative form the first pass missed
```

| Importer | Line | Form | MODULE-LEVEL / DEFERRED | Layer |
| --- | --- | --- | --- | --- |
| `daedalus/interfaces/http/read.py` | `:20` | `from ...env import env_status` | MODULE-LEVEL | `daedalus.interfaces` |
| `daedalus/web_api.py` | `:36` | `from .env import env_status, load_env` | MODULE-LEVEL (called at `:1166`, inside a guard-adjacent startup path — "before the guard: the token may legitimately live in `.env`") | flat |
| `daedalus/runtime_registry.py` | `:25` | `from .env import load_env` | MODULE-LEVEL (called at `:367`) | flat |
| `scripts/daedalus_desktop_sidecar.py` | `:103` | `from daedalus.env import load_env` | DEFERRED (inside a function) | scripts/ (packaged desktop sidecar entrypoint) |
| `tools/guarded_call.py` | `:62` | `from daedalus.env import load_env` | DEFERRED | tools/ |
| `tools/funnel.py` | `:70` | `from daedalus.env import load_env  # noqa: E402` | MODULE-LEVEL | tools/ |
| `tests/test_web_api.py` | `:21` | `from daedalus.env import env_status, load_env` | MODULE-LEVEL, TEST-ONLY | tests/ |

Per-layer breakdown: `daedalus.interfaces` 1, flat `daedalus/` 2, scripts/ 1
(deferred), tools/ 2 (1 deferred, 1 module-level), tests/ 1. 2 of 7 edges
are DEFERRED (`scripts/daedalus_desktop_sidecar.py:103`,
`tools/guarded_call.py:62`); the other 5 are MODULE-LEVEL.

**Reconciliation with the two independent cross-checks supplied:**

- The task's own AST census reported 7 with the identical per-layer
  breakdown (`interfaces 1, flat 2, scripts 1, tools 2, tests 1; 2
  deferred`) — my count matches it exactly, row for row.
- A sibling worker's `dotenv.md` (already written into this same
  directory, read for cross-check only — not edited) reports only 6
  importers of `daedalus.env`, omitting `daedalus/interfaces/http/read.py`.
  Reproduced the gap: their grep pattern was `from \.env import` (single
  dot), which does not match `from ...env import` (`read.py` is three
  package levels below `daedalus/` — `daedalus/interfaces/http/read.py` —
  so the relative import needs three leading dots to reach
  `daedalus.env`). A first pass of my own grep made the identical mistake
  and undercounted at 6 before I re-ran a broader, dot-count-agnostic
  search over `daedalus/interfaces/`. **7 is the correct, reproduced
  count**; the sibling's 6 is an undercount from an import-form regex gap,
  not a real disagreement about production wiring.

## 4. What it imports (MEASURED)

Zero `daedalus.*` imports. Full import list (`daedalus/env.py:9-11`):
- `os` (stdlib)
- `pathlib.Path` (stdlib)
- `typing.Any` (stdlib)

No third-party imports, no intra-repo imports at all — a leaf module with
no upward or lateral dependency inside `daedalus/`.

## 5. Proposed destination

**foundation.** Confidence: **medium-high**.

Argument from measured edges: `env.py` has zero `daedalus.*` imports (§4),
so it cannot violate any of the four boundary rules regardless of where it
lands — nothing in it can ever be a forbidden target-prefix hit. Its
callers span `daedalus.interfaces` (1), flat `daedalus/` (2), `scripts/`
(1), `tools/` (2), and `tests/` (1) — a genuinely cross-cutting consumer
set with no single owning layer, the same shape the declared FOUNDATION
set (`atomic, budget, config, limit_policy, primary_tree, sensitivity,
storage`) already exhibits: bottom-of-stack utilities everyone is allowed
to reach.

**Verified against sibling worker `flat-dossiers-a`'s claim** (relayed via
SendMessage while this dossier was in progress) that `daedalus/env.py` and
`daedalus/dotenv.py` are two independent `.env` loaders and that `env.py`
lacks a git-tracked-secret refusal check:

1. **Confirmed, both parts, by direct read of both files.**
   `daedalus/env.py`'s `load_env()` (`:45-62`) does exactly this on a
   `.env` hit: `if env_path.exists(): for line in
   env_path.read_text(...).splitlines(): ...; os.environ[key] = value`.
   There is **no** call to anything resembling `_is_git_tracked` anywhere
   in the 89-line file (`grep -n "git\|tracked" daedalus/env.py` → no
   output) — a git-tracked `.env` loads silently. `daedalus/dotenv.py`, by
   contrast, has `_is_git_tracked()` (`:54-69`, a `git ls-files
   --error-unmatch` subprocess check) and `load()` raises `DotEnvRefused`
   (`:113-118`) before ever reading the file when the check trips. This is
   the one condition `dotenv.py`'s docstring calls out as "the one
   condition that raises rather than warns" (`dotenv.py:24`) — `env.py`
   has no equivalent condition at all.
2. **They are genuine duplicate canonical paths for the same
   responsibility (loading `.env` into `os.environ`), not different
   things for different consumers**, with one load-bearing wrinkle: their
   consumer sets do not currently overlap in the same call — `env.py`'s
   `load_env()` is called from `web_api.py:1166` and
   `runtime_registry.py:367`; `dotenv.py`'s `load()` is called from
   `cli.py:1123` and `loop.py:1661` (verified: `grep -n "dotenv" 
   daedalus/web_api.py daedalus/runtime_registry.py` → no output; `grep
   -n "\.env import\|import env\b" daedalus/cli.py daedalus/loop.py` → no
   output — neither module references the other's loader). But `cli.py`
   dispatches to `web_api.main` in-process for the `daedalus web-api`
   subcommand (`daedalus/cli.py:1218: from .web_api import main as m;
   m(rest)`), so a single `daedalus web-api` invocation can run `cli.py`'s
   `main()` (which calls the *safe*, refusing `dotenv.load()` at `:1123`
   before anything else) and then, deeper in the same process, reach
   `web_api.py`'s own startup path which calls the *unsafe*, non-refusing
   `env.load_env()` at `:1166`. Both are idempotent (env-var-presence
   gated), so today this does not double-load or corrupt state — but it
   means the `dotenv.py` refusal that already ran upstream provides no
   actual protection against `web_api.py`'s own, independent, unguarded
   re-read of the same file lower in the same call stack; a
   `.env` file added to the tracked tree *after* the `cli.py` gate ran
   (or reached via a code path that skips `cli.py`'s `main()` entirely —
   e.g. `daedalus_desktop_sidecar.py`'s direct `from daedalus.env import
   load_env`, §3) would load through `env.py` with no refusal anywhere in
   that path. `dotenv.py`'s own docstring premise — *"nothing in this
   tree ever read the file"* (`dotenv.py:7`) — was already false the day
   it was written (2026-07-29): `env.py` existed since 2026-07-06
   (`git log --follow --diff-filter=A --format="%H %ad %s" --
   daedalus/env.py` → `1da0c0d ... Jul 6 02:56:10 2026 ... feat:
   API-first Agent OS — local web_api backend + React/Vite webapp`) and
   was already reading `.env` in `web_api.py`. This reads as one team
   building the hardened loader without knowing the other already
   existed, not a deliberate two-tier design.
3. **This is a one-canonical-path concern under AGENTS.md §"Non-negotiable
   boundaries" / global-CLAUDE.md §5 ("Pro Verantwortung genau einen
   kanonischen Ausführungspfad")**, not a false alarm. On the measured
   evidence, `daedalus/dotenv.py` should win: it has the git-tracked-secret
   refusal, presence-not-truthiness handling with a recorded Cerberus
   finding (`dotenv.py:126-132`), and a narrower, more disciplined parser
   (`export` prefix, stricter key-char validation). `env.py`'s only
   feature `dotenv.py` lacks is `env_status()` — the redacted
   provider-readiness projection used by the web UI/VS Code status
   screens (§2) — which is a distinct, additive responsibility (reporting,
   not loading) that could be kept or moved onto `dotenv.py`'s `describe()`
   shape. **Marking this OUT OF SCOPE for this read-only classification
   packet** — no edit, no consolidation, no fix proposed here; this is a
   finding for a future Work Packet, per the task's explicit instruction.

What would change my mind on the foundation placement itself: if a future
hierarchy packet defines a narrower "process-bootstrap"/"environment" layer
distinct from foundation (the sibling dossier for `dotenv.py` raises the
same caveat) — but no such layer exists in the target layout given to this
task, and until the env/dotenv duplication above is resolved by an
explicit Work Packet, keeping both at the same layer (foundation) is the
least-surprising interim placement.

**No split boundary** — `env.py` is one coherent module (parse a `.env`
line, fill `os.environ` gaps, report redacted status), not two things
fused. (The env/dotenv duplication above is a *cross-module* concern, not
an internal fusion inside this file.)

## 6. Boundary-rule check after the move

**(a) Moved to `foundation`: would any of its own imports be refused?**
No. `env.py` imports only `os`, `pathlib.Path`, `typing.Any` (§4) — zero
`daedalus.*` edges, so none of the four rules in
`docs/architecture/import-boundaries.json` can ever fire against it
regardless of source-prefix classification.

**(b) Does any CURRENT rule name this module by prefix?** No. Read the
full `docs/architecture/import-boundaries.json` (all four rules'
`source_prefixes`, `forbidden_target_prefixes`, `allowed_target_prefixes`,
plus the single `baseline` entry) — `daedalus.env` appears nowhere. No
move of this file changes any rule's behavior today.

**(c) If it lands in kernel/spine/twin: which flat imports would be
refused, and what does widening cost?** **None — mandatory answer for the
most likely foundation candidate.** Since `env.py` imports zero
`daedalus.*` modules (§4), it would trivially satisfy even the strictest
allowlist (`twin-no-outer-layers`: `kernel, spine, structcore`;
`spine-no-outer-layers`: `atomic, budget, config, kernel, limit_policy,
mapping, sensitivity, structcore`; `kernel-no-outer-layers`: `atomic,
budget, config, limit_policy, primary_tree, sensitivity, spine, storage,
twin`) if it were ever placed as a *source* under one of those three — zero
of its own imports could be refused. The cost runs the OTHER direction:
today, `daedalus.env` is absent from all three allowlists as a *target*,
so if kernel/spine/twin code ever wanted `from daedalus.env import
env_status` directly, that import would be REFUSED by whichever rule
governs the importing module, and admitting it would require a reviewed
diff to `tests/test_architecture_boundaries.py::test_the_allowlists_cannot_grow_quietly`
(`tests/test_architecture_boundaries.py:344-386`) adding `"daedalus.env"`
to that rule's pinned `allowed_target_prefixes` list — exactly the
reviewed-diff cost the pin test exists to force, not a silent JSON edit.
Landing `env.py` in `foundation` and adding `daedalus.env` to, say,
`kernel-no-outer-layers`' allowlist (mirroring how `daedalus.config` is
already there) would be that one reviewed diff, and is a reasonable
follow-on if a kernel/spine/twin module later needs it.

**(d) Does any rule constrain `daedalus.interfaces` as a source?** No —
confirmed by reading all four rules; none uses `daedalus.interfaces` as a
`source_prefixes` entry (only `daedalus.kernel`, `daedalus.runtimes`,
`daedalus.spine`, `daedalus.twin` are ever sources). Not directly
applicable to `env.py` itself, since `foundation` (not `interfaces/*`) is
the proposed destination — but it is directly relevant to one of `env.py`'s
own importers: `daedalus/interfaces/http/read.py` already imports
`env_status` (§3) with zero governing rule today. If `interfaces/*` is
later given its own outer-layer rule (mirroring kernel/spine/twin), that
rule would need to explicitly allow `daedalus.env` (or whatever prefix
`env.py` lands under) for `read.py`'s existing edge to keep passing —
otherwise a currently-invisible edge becomes a newly-forbidden one.

## 7. Dead-code signals

**LIVE.** `load_env()` is called from two flat-module production paths
(`web_api.py:1166`, `runtime_registry.py:367`) and reachable from the
packaged desktop sidecar (`scripts/daedalus_desktop_sidecar.py:103`,
deferred) and from `tools/funnel.py:70` / `tools/guarded_call.py:62`
(the latter deferred). `env_status()` backs the `/api/env/status` HTTP
route (`daedalus/interfaces/http/read.py:20,158-159`, module-level import,
route wired into the dispatcher) and is exercised directly by
`tests/test_web_api.py:21`. Not a dead-code candidate.

Searched for a promised-but-unwired reader beyond the measured callers
(none found — reported for completeness since §7 requires the search be
shown, not just the conclusion):
- `.agentenv/agentenv.json` / the capability-policy artifact: `env.py`
  does **not** read it. `grep -n "agentenv" daedalus/env.py` → no output.
  The `.agentenv/agentenv.json` policy file is owned by `daedalus/config.py`
  (`REPO_CONFIG = ".agentenv/agentenv.json"` at `config.py:33`,
  `scaffold_repo_config` at `config.py:337-340`) — a **separate,
  already-declared-foundation** module. `env.py` is unrelated to that
  concern: it is process-environment/`.env`-secrets handling only, not
  mechanical capability-policy handling. Confirmed this by grepping every
  reference to `agentenv.json` in `daedalus/*.py`
  (`config.py`, `cli.py`, `offload.py`, `selftest.py`, `sensitivity.py`
  comment) — `env.py` is not among them. This measurement, not
  assumption, is what grounds the foundation classification in §5: it is
  foundation on the strength of its zero-dependency, everyone-reaches-it
  shape, not because it participates in the `.agentenv` policy plane.
- `pyproject.toml`: `grep -n -i "env" pyproject.toml` returns unrelated
  hits (build/venv references, no `[project.scripts]` entry naming `env`
  or `load_env`/`env_status`).
- `docs/architecture/shim-registry.json`: `grep -n "env"
  docs/architecture/shim-registry.json` → no output naming `daedalus.env`;
  not a registered shim.
- `daedalus/spine/effect_boundary.py` registered CLI-target strings
  (per the task's warning about string-only registrations such as
  `"daedalus.arch_memory:main"`): `grep -n "daedalus\.env\|\"env\"\|'env'"
  daedalus/spine/effect_boundary.py` → no output. Not registered as an
  effect-boundary door target.

No CANDIDATE-DELETE signal anywhere; this module is straightforwardly LIVE
with a real, if fragmented, caller set.
