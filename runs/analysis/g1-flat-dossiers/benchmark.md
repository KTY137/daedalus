# daedalus/benchmark.py — hierarchy dossier

## 1. Size and shape

- 252 lines (`daedalus/benchmark.py`, measured `wc -l`).
- 1 class, 8 functions (`Grep '^(class |def )'`): `LiveBenchmarkRetired(RuntimeError)` at
  `daedalus/benchmark.py:42`; functions `_cost:97`, `_claude_key:102`,
  `_assumptions:106`, `run:123`, `run_live:182`, `_print_table:194`, `main:214`,
  plus the frozen dataclass `Task` at `daedalus/benchmark.py:65`.
- Module-level state: three module-level constants that are read (never
  mutated) at call time — `PRICES: dict[...]` (`benchmark.py:48-53`),
  `TASKS: tuple[Task, ...]` (`benchmark.py:75-94`), `POSTURE: dict`
  (`benchmark.py:61`). No singleton object, no registry, no cache.
- Import-time side effects: none. No file I/O, no env read, no network, no
  path creation at module scope. The only effectful call
  (`begin_effect(...)`, `benchmark.py:220`) is inside `main()`, guarded behind
  `if __name__ == "__main__"` (`benchmark.py:251-252`) or the CLI dispatcher's
  deferred import — never executed on `import daedalus.benchmark`.

## 2. What it does

It computes a planning-only cost estimate for a fixed, hand-written set of
representative routing tasks by calling `route_task` and `select_provider`
against an unverified, hardcoded USD-per-million-token price table, and prints
or returns the result labelled `comparative_evidence_eligible: False`
(`benchmark.py:169-179`). It exposes a CLI (`main`, `benchmark.py:214-249`)
that begins a centrally-guarded effect before parsing `--json`, and it retains
a `run_live` function that unconditionally raises `LiveBenchmarkRetired`
(`benchmark.py:182-191`) so old callers of a previously removed `--live`
measurement path get an explicit refusal instead of an `ImportError`. The
docstring (`benchmark.py:1-19`) explicitly disclaims benchmark authority and
directs real comparative evidence to `daedalus.eval`.

## 3. Who imports it (MEASURED)

Command run: `Grep` for `from daedalus.benchmark import|from daedalus import benchmark|import daedalus\.benchmark|from \. import benchmark|daedalus\.benchmark` across the repo (excluding `experiments/`, which has its own unrelated local `benchmark.py`), then hand-verified each hit.

TOTAL real Python import edges: **2**.

| importer | layer | scope |
|---|---|---|
| `tests/test_benchmark_authority.py:12` — `from daedalus import benchmark` | tests | MODULE-LEVEL |
| `daedalus/cli.py:1155` — `from .benchmark import main as m; m()` | interfaces/cli (flat `cli.py`, the CLI dispatcher) | DEFERRED — inside `def main()` (`cli.py:1093`), under `elif cmd == "benchmark":` (`cli.py:1154`) |

Non-import references found and excluded (they do not create a Python import
edge, but are load-bearing for reachability/registry evidence — recorded for
section 7):
- `daedalus/spine/effect_boundary.py:2378-2389` — `EntrypointSpec(id="cli.benchmark", target="daedalus.benchmark:main", anchors=(GuardAnchor("daedalus.benchmark:main", "begin_effect"),))`. A bare dotted-path **string** in the effect-boundary registry, not a Python import; it is what `cli.py`'s deferred import is centrally guarded against.
- `tests/test_registry_new_doors.py:112` — `"cli.benchmark": "daedalus.benchmark:main"` — bare string in a test fixture mirroring the registry.
- `daedalus/mapping/reach.py:530` — docstring prose example (`` `from .benchmark import main` ``), not code.
- `experiments/forest_v2/tensor_embeddings/cli.py:16` — `from .benchmark import BenchmarkCase, run_benchmark, ...` — resolves to `experiments/forest_v2/tensor_embeddings/benchmark.py`, a **different, unrelated module**. Excluded.
- `docs/*.md`, `docs/*.json`, `runs/gates/**`, `runs/tensor_embedding_v3/**` — documentation/derived-artifact prose or generated triples, not source imports.

## 4. What it imports (MEASURED)

Command run: `Grep '^from \.|^from daedalus|^import daedalus' daedalus/benchmark.py` plus manual read for function-scope imports inside `main()`.

| import | file:line | scope | target layer |
|---|---|---|---|
| `from .provider_router import select_provider` | `benchmark.py:29` | MODULE-LEVEL | flat (`daedalus/provider_router.py` exists, is not in the declared-foundation list, not an SCC member, not a package) |
| `from .router import route_task` | `benchmark.py:30` | MODULE-LEVEL | flat (`daedalus/router.py` exists, same status) |
| `from .budget import process_guard_boundary_decision` | `benchmark.py:217` | DEFERRED (inside `main()`) | foundation (declared) |
| `from .spine.effect_boundary import REGISTRY_BY_ID, begin_effect` | `benchmark.py:218` | DEFERRED (inside `main()`) | spine |

Third-party imports: none beyond stdlib (`argparse`, `json`, `sys`,
`dataclasses`, `typing`).

## 5. Proposed destination

**orchestration** — confidence **medium**.

Argument from measured edges: the module's only real production caller is
`daedalus/cli.py`'s dispatcher (a deferred, guarded CLI subcommand), and its
own module-level imports are `provider_router` and `router`, both flat
routing/provider-selection modules that decide which lane/model/provider a
task goes to — that is orchestration-shaped work (selecting an agent/provider
per task and estimating routing cost), not kernel/spine/twin/runtime/foundation
work. It is not `interfaces/cli` itself because it has no CLI-argument-parsing
identity beyond a thin `argparse` wrapper around a domain computation (`run`),
and the domain computation (task routing cost estimation) is the actual
payload; `interfaces/cli` should be the thin dispatch layer that already lives
in `cli.py`, not this module.

What would change my mind: if `provider_router.py` and `router.py` are
themselves later classified as `interfaces/cli`-adjacent or `foundation`
rather than `orchestration`, the natural pull for `benchmark.py` would follow
them. Since neither is decided yet (both are flat, unassigned), medium
confidence rather than high.

## 6. Boundary-rule check after the move

None of the four documented rules (`kernel-no-outer-layers`,
`runtimes-no-gates`, `spine-no-outer-layers`, `twin-no-outer-layers`) have
`source_prefixes` matching `daedalus.orchestration`, so moving this module to
`orchestration` triggers **no rule check today** — the boundary contract
(`docs/architecture/import-boundaries.json`) is silent on orchestration as a
source.

(a) Own-import refusal check if moved to `orchestration`: N/A — no
`orchestration-*` rule exists in the contract to refuse anything.

(b) Does a current rule name this module by prefix? No. `daedalus.benchmark`
is not named as a `forbidden_target_prefix` in any of the four rules, and none
of `kernel-no-outer-layers` / `spine-no-outer-layers` / `twin-no-outer-layers`
forbid `daedalus.orchestration` by targeting `daedalus.benchmark` specifically
— they forbid the whole `daedalus.orchestration` prefix as a target. If
`daedalus.benchmark` moves under `daedalus/orchestration/benchmark.py`, then
any future kernel/spine/twin import of it becomes refused by the existing
`daedalus.orchestration` entries in `kernel-no-outer-layers` (`forbidden_target_prefixes`, line naming `daedalus.orchestration`) and `spine-no-outer-layers`
(same). Today that costs nothing (no kernel/spine/twin module imports
`daedalus.benchmark` — confirmed in section 3's full importer list), but it
would proactively close the same class of leak the rule file's own rationale
warns about.

(c) Allowlist exposure: N/A — `orchestration` is not `kernel`/`spine`/`twin`,
so the allowlist enumeration requirement in the rule file does not apply to
this move. (If it were later placed under `daedalus/spine/` instead — not
proposed — its own imports of `provider_router`/`router`, both flat and
unlisted in `spine-no-outer-layers`'s `allowed_target_prefixes`, would be
refused; that is a reason not to choose spine.)

## 7. Dead-code signals

Importer count (real Python edges) = 2, both live: one production CLI
subcommand (`cli.py:1155`, deferred, guarded) and one focused contract test
(`test_benchmark_authority.py`). This is **LIVE**, not a dead-code candidate.

Evidence checked per the required checklist:
- Docstring/comments: explicitly self-describes as "not a benchmark
  authority" (`benchmark.py:7`) but simultaneously documents itself as the
  registered CLI cost-estimate surface (`benchmark.py:214-249`) and the retired
  `--live` compatibility shim (`benchmark.py:184-191`) — a promised reader
  (the CLI) exists and is confirmed wired.
- `pyproject.toml`: no `console_scripts` entry for `benchmark` (checked;
  no match for `daedalus.benchmark` or `console_scripts` block referencing
  it).
- Bare-string/registry references: `daedalus/spine/effect_boundary.py:2378-2389`
  registers `EntrypointSpec(id="cli.benchmark", target="daedalus.benchmark:main", ...)`
  with `wiring=Wiring.CENTRAL` and a `GuardAnchor` — this is the effect-boundary
  registry proving the CLI door is centrally guarded and live, not vestigial.
  `tests/test_registry_new_doors.py:112` mirrors the same registry entry in a
  test fixture.
- `git log`: added 2026-07-05 (`46a4d45b`, "feat: rebrand agent_env → daedalus
  + Mission Control cockpit + dynamic agent configurator") and has an explicit
  later work packet retiring its live path (`docs/work-packets/G1-BENCH-AUTH-01.json`,
  "delete the independent offload/live measurement loop and runtime metrics
  aggregation from daedalus.benchmark") — the consumer (CLI `benchmark`
  subcommand) was never removed, only the `--live` capability inside it was
  narrowed.

Label: **LIVE**.
