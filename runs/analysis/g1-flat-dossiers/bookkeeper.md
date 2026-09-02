# daedalus/bookkeeper.py — hierarchy dossier

## 1. Size and shape

- 267 lines (`daedalus/bookkeeper.py`, measured `wc -l`).
- 0 classes, 10 functions (`Grep '^(class |def )'`): `_inline:32`, `_table:42`,
  `render_markdown:50`, `_git_hash:155`, `_wrap:163`, `_body_hash:173`,
  `update:177`, `_load_manifest:214`, `_write_index:225`, `main:243`.
- Module-level state: five module-level path constants computed at import —
  `ROOT = Path(__file__).resolve().parents[1]` (`bookkeeper.py:21`),
  `DOCS = ROOT / "docs"` (`:22`), `SOURCE = DOCS / "ARCHITECTURE.md"` (`:23`),
  `ARTIFACT = DOCS / "architecture.html"` (`:24`),
  `HISTORY = DOCS / "architecture_history"` (`:25`); plus one large string
  constant `_CSS` (`bookkeeper.py:131-152`). These are path objects only —
  path arithmetic, not filesystem access — and a style-sheet string; no
  singleton/registry object.
- Import-time side effects: none. No file is read or written, no directory is
  created, no env var is read, and no network call happens at module scope.
  All filesystem I/O (`SOURCE.read_text`, `ARTIFACT.write_text`,
  `HISTORY.mkdir`, snapshot writes) happens inside `update()`
  (`bookkeeper.py:177-211`), which only runs when called. `subprocess.run`
  (`git rev-parse`) is likewise inside `_git_hash()` (`:155-160`), called only
  from `update()`/`_write_index()`, never at import.

## 2. What it does

It renders `docs/ARCHITECTURE.md` through a small hand-written Markdown-to-HTML
converter (`render_markdown`, `_inline`, `_table` — headings, lists, tables,
code fences, blockquotes, hr, inline emphasis/code/links only) into a
self-contained styled `docs/architecture.html` artifact. When the rendered
content's hash changed since the last recorded snapshot (or `--force` is
passed), it additionally files a timestamped copy into
`docs/architecture_history/`, updates a `manifest.json`, and regenerates an
`index.html` listing every snapshot with its git short-hash and note
(`update`, `_write_index`). It exposes a `daedalus bookkeeper update` CLI
(`main`, `bookkeeper.py:243-263`) that begins a centrally-guarded effect
(`begin_effect("cli.bookkeeper", ...)`, `:257-261`) before calling `update()`.

## 3. Who imports it (MEASURED)

Command run: `Grep` for `from daedalus.bookkeeper import|from daedalus import bookkeeper|import daedalus\.bookkeeper|from \. import bookkeeper|daedalus\.bookkeeper` across the repo, hand-verified each hit.

TOTAL real Python import edges: **4**.

| importer | layer | scope |
|---|---|---|
| `daedalus/build.py:432` — `from .bookkeeper import update as _bk_update` | flat, but `build.py` is one of the 11 **SCC-owned** modules (not to be classified by this dossier; edge recorded per instructions) | DEFERRED — inside `try:` inside a method, guarded by `except Exception: pass` (`build.py:430-435`), only when `update_architecture=True` |
| `daedalus/cli.py:1214` — `from .bookkeeper import main as m; m(rest)` | interfaces/cli (flat `cli.py`, CLI dispatcher) | DEFERRED — inside `def main()` (`cli.py:1093`), under `elif cmd == "bookkeeper":` (`cli.py:1213`) |
| `tests/test_cli_effect_boundary.py:180` — `from daedalus.bookkeeper import main` | tests | DEFERRED — inside `def test_bookkeeper_update_refuses_fail_closed(...)` (`:179`) |
| `tests/test_bookkeeper.py:10` — `from daedalus import bookkeeper as bk` | tests | MODULE-LEVEL |

Non-import references found and excluded (not a Python import edge, recorded
for section 7 instead):
- `daedalus/spine/effect_boundary.py:722-731` — `EntrypointSpec(id="cli.bookkeeper", target="daedalus.bookkeeper:main", anchors=(GuardAnchor("daedalus.bookkeeper:main", "begin_effect"),))` — bare dotted-path string in the effect-boundary registry.
- `tests/test_build.py:68` — `patch("daedalus.bookkeeper.update", return_value=None)` — a mock target string (patches the attribute at runtime via `unittest.mock`), not a static import; `test_build.py` otherwise never imports the module by name.
- `docs/*.md`, `docs/*.json`, `docs/archive/**`, `runs/**` — documentation/generated-artifact prose, not source.

## 4. What it imports (MEASURED)

Command run: `Grep '^from \.|^import' daedalus/bookkeeper.py` for module scope, plus manual read of `main()` for function-scope imports.

| import | file:line | scope | target layer |
|---|---|---|---|
| `import json` (inside `_load_manifest`) | `bookkeeper.py:215` | DEFERRED | stdlib |
| `import json` (inside `_write_index`) | `bookkeeper.py:226` | DEFERRED | stdlib |
| `import argparse` (inside `main`) | `bookkeeper.py:244` | DEFERRED | stdlib |
| `import json` (inside `main`) | `bookkeeper.py:245` | DEFERRED | stdlib |
| `from daedalus.budget import process_guard_boundary_decision` | `bookkeeper.py:254` | DEFERRED (inside `main()`) | foundation (declared) |
| `from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect` | `bookkeeper.py:255` | DEFERRED (inside `main()`) | spine |

No module-level `daedalus.*` imports at all — every internal dependency is
deferred into `main()`. Third-party imports: none beyond stdlib (`hashlib`,
`html`, `re`, `subprocess`, `time`, `pathlib`).

## 5. Proposed destination

**interfaces/cli** — confidence **medium**.

Argument from measured edges: `bookkeeper.py` has zero module-level
`daedalus.*` dependencies (foundation/spine imports are deferred into `main()`
only), so it is nearly self-contained — a docs-artifact renderer plus a CLI
entrypoint. Its only production callers are `daedalus/cli.py`'s dispatcher
(a CLI subcommand, deferred+guarded) and `daedalus/build.py` (an SCC-owned
build orchestrator, calling it best-effort after a build session). It is not
`kernel`/`spine`/`twin`/`runtimes` (touches none of their contracts), not
`foundation` (it is not infrastructure other layers build on — nothing
imports it except a CLI dispatcher and one SCC-owned caller), and not
`orchestration` in the Mission/Attempt/WorkItem sense — it does no
multi-step orchestration, just renders one file and files a snapshot. The CLI
identity (`main()` parses `argparse`, begins the guarded CLI effect, and is
the module's only meaningfully-used export beyond `update()` itself) argues
for `interfaces/cli`.

What would change my mind: `update()` is a plain library function
(`bookkeeper.py:177-211`) called directly by `build.py` (SCC-owned) without
going through the CLI at all — if the SCC-owner's classification of
`build.py` places it in `orchestration`, that direct non-CLI caller would be
a stronger pull toward classifying `bookkeeper.py` as a small
docs/reporting utility colocated near `orchestration` or even `foundation`
rather than `interfaces/cli`. Since `build.py` is out of scope for this
dossier (SCC-owned, not to be classified), I cannot resolve that pull here;
confidence stays medium rather than high.

## 6. Boundary-rule check after the move

None of the four documented rules (`kernel-no-outer-layers`,
`runtimes-no-gates`, `spine-no-outer-layers`, `twin-no-outer-layers`) have
`source_prefixes` matching `daedalus.interfaces`, so moving this module to
`interfaces/cli` triggers **no rule check today**.

(a) Own-import refusal check if moved to `interfaces/cli`: N/A — no
`interfaces-*` rule exists in the contract. Even hypothetically, its two
`daedalus.*` imports (`daedalus.budget`, `daedalus.spine.effect_boundary`) are
both deferred inside `main()`, and the checker walks the whole AST including
deferred imports, so if such a rule existed it would see these edges; today
neither is a forbidden target under any existing rule.

(b) Does a current rule name this module by prefix? No.
`daedalus.bookkeeper` is not named in any `forbidden_target_prefixes` list.
Nothing changes for existing rules if it moves under `daedalus/interfaces/cli/`.

(c) Allowlist exposure: N/A — `interfaces/cli` is not `kernel`/`spine`/`twin`,
so the allowlist enumeration requirement does not apply. (For reference, if it
were hypothetically placed under `daedalus/spine/` instead — not proposed —
`daedalus.budget` and `daedalus.spine` sub-imports are both in
`spine-no-outer-layers`'s `allowed_target_prefixes`, so no conflict would
arise there either; the destination choice is not boundary-constrained
either way.)

## 7. Dead-code signals

Importer count (real Python edges) = 4, all live: one production CLI
subcommand (`cli.py:1214`, deferred, guarded), one SCC-owned production caller
(`build.py:432`, best-effort, deferred), and two direct tests
(`test_bookkeeper.py` module-level, `test_cli_effect_boundary.py` deferred).
This is **LIVE**, not a dead-code candidate.

Evidence checked per the required checklist:
- Docstring: "keeps the living architecture artifact in sync with reality...
  After every build session (and on demand)" (`bookkeeper.py:1-9`) — a
  promised reader (the build session flow) exists and is confirmed wired via
  `build.py:432`.
- `pyproject.toml`: no `console_scripts` entry for `bookkeeper` (checked; no
  match).
- Bare-string/registry references: `daedalus/spine/effect_boundary.py:722-731`
  registers `EntrypointSpec(id="cli.bookkeeper", target="daedalus.bookkeeper:main", ...)`
  with `wiring=Wiring.CENTRAL` and a `GuardAnchor`, confirming the CLI door is
  centrally guarded and live. `tests/test_build.py:68` patches
  `"daedalus.bookkeeper.update"` directly, confirming the attribute path is a
  live integration point exercised by `build.py`'s own test suite.
- `git log`: added 2026-07-06 (`6e692e74`, "feat: bookkeeper — living
  architecture.html artifact + versioned history") and referenced in current
  `docs/archive/swarm-2026-07-30/census/shard12.md` as a dependency of
  `daedalus/build.py` — no evidence the consumer was ever removed.

Label: **LIVE**.
