# daedalus/dctx.py

## 1. Size and shape

455 lines (`wc -l daedalus/dctx.py` -> 455; file content runs through
`daedalus/dctx.py:456` in a line-numbered read, i.e. 455 newline-terminated lines
plus the `if __name__ == "__main__":` guard at :454-455).

Classes: 0 defined in this file (`Policy` at :46 is imported from `.sensitivity`,
not defined here).

Functions: 11, all module-level (`grep -n "^class \|^def "` -> zero class
matches, eleven def matches): `_commit` (:67), `_unit_digest` (:86), `_canonical`
(:112), `_receipt_sha` (:151), `compile` (:158), `_egress_verdict` (:265),
`_egress_policy_fingerprint` (:282), `_policy_from_fingerprint` (:306),
`_recall_claim_failures` (:324), `verify` (:352), `main` (:409).

Module-level state / singletons: none that are mutable. Three module-level
constants only: `RECEIPT_VERSION = "dctx/1"` (:52), `DIGEST_VERSION =
"dctx-unit/1"` (:56), `LABEL_PROVENANCE = (...)` (:61, a 4-tuple vocabulary used
for validation, not mutated). No dict/list singleton, no registry, no
`threading.Lock`, no cache anywhere in the file.

Module-level side effects at import: none. Read of the full file confirms every
statement at column 0 (import lines aside) is one of the three constant
assignments above or a `def`. The one `subprocess.run` call in the file is
inside `_commit()` (:76-77), executed only when `compile()` or `verify()` calls
it -- not at import. The one filesystem write (`Path(...).write_text`, :447) is
inside `main()`, gated behind an explicit `begin_effect("cli.dctx", ...)` call
(:439-443) that itself runs only when `main()` is invoked as a CLI entrypoint,
never at import.

## 2. What it does

`compile()` (:158) wraps `structcore.slice.semantic_slice` with a deterministic,
content-addressed `.dctx` receipt: it re-hashes every included unit's source
bytes together with its file/role/mode identity (`_unit_digest`, :86), records
the checkout's git commit and status (`_commit`, :67), independently re-runs the
egress/secret gate over everything the slice claims to include
(`_egress_verdict`, :265), computes an optional label-recall number that is
`None` rather than a vacuous `1.0` when no labels were supplied by the caller,
and seals a `receipt_sha` (:151, :261) over a deliberately narrow "structural"
projection of all of that (`_canonical`, :112) that excludes token counts,
backend choice, absolute paths, and timestamps so the same commit produces a
byte-identical receipt on any machine. `verify()` (:352) re-derives every one of
those facts from a live checkout offline (no model, no network) and returns the
specific list of mismatches -- tampered receipt SHA, moved commit, changed unit
bytes, a newly-tripped egress rule, or an internally inconsistent recall claim --
rather than a bare pass/fail. `main()` (:409) is a thin `argparse` CLI
(`daedalus dctx <repo> <target> [--out F]` to mint, `--verify F` to check) that
routes minting through the canonical effect boundary (`begin_effect("cli.dctx",
...)`, :439-443) while leaving `--verify` as fail-open read-only inspection
(:423-429, executed before the boundary call).

## 3. Who imports it (MEASURED)

Commands used: `Grep pattern="from \.dctx|from daedalus\.dctx|from \. import
dctx|import daedalus\.dctx|from daedalus import.*dctx" path=daedalus/` and the
same restricted to `path=daedalus/dctx.py`'s reverse (importer) direction across
`daedalus/`, `tests/`, `tools/`, `apps/`, `.claude/`, `scripts/`, `docs/`
individually. `apps/`, `.claude/`, `scripts/`, and the top-level `tools/` all
returned zero hits for even a bare `dctx` substring search.

TOTAL: 4 static importer edges (1 production, 3 test), plus one CLI-string
reference in `daedalus/cli.py`'s own help text (:35, not an import) and two
data-only mentions (`daedalus/eval/minted_tasks.json:565`'s `"target":
"daedalus/dctx.py"` field and `docs/architecture-state.json:57`), neither of
which is Python import syntax.

Per-layer breakdown:
- flat (unclassified): 1 importer -- `daedalus/cli.py`, the unified CLI
  entrypoint (itself a Gate-1 hierarchy candidate for `interfaces/cli`, but not
  yet moved -- `ls daedalus/interfaces/` shows only `bridge`, `desktop`, `http`
  today, no `cli` subpackage).
- tests: 3 importers.

Full list:

- `daedalus/cli.py:1149` -- `from .dctx import main as m; m()`, inside the
  `elif cmd == "dctx":` branch of `def main()` (`daedalus/cli.py:1093`).
  DEFERRED (function-scope).
- `tests/test_cli_effect_boundary.py:187` -- `from daedalus.dctx import main`,
  inside `def test_dctx_mint_refuses_fail_closed(...)`. DEFERRED.
- `tests/test_dctx_policy_egress.py:24` -- `from daedalus import dctx`, at
  file column 0 above the test classes. MODULE-LEVEL.
- `tests/test_dctx.py:27` -- `from daedalus import dctx`, at file column 0.
  MODULE-LEVEL.

One additional occurrence, deliberately excluded from the import count:
`tests/test_dctx.py:148` -- `from daedalus import dctx` -- is NOT a live Python
import statement in this file's own module graph. It is a line inside a
triple-quoted string literal, `_DETERMINISM_SNIPPET` (:145-151), that gets
`.format()`-substituted and written into a **subprocess** script (the comment at
:143-144 explains why: `PYTHONHASHSEED` is read at interpreter start, so the
determinism probe must run in a fresh child process). It is real evidence that
`dctx` is imported at runtime by a spawned `python -c`-style child, but it is
invisible to any static AST import-boundary checker walking this test file, and
double-counting it as a fifth static edge would overstate the measured graph.

Confirmed live call sites (not merely imported): `cli.py:1149` calls `m()`
immediately; the three test files call `dctx.compile`, `dctx.verify`, and
`dctx.main` respectively across their bodies.

## 4. What it imports (MEASURED)

Command used: full read of `daedalus/dctx.py` (imports are not numerous enough
to require grep; two module-level lines at the top, two more deferred inside
`main()`).

- `from .sensitivity import Policy, slice_egress_rule, _compile` --
  `daedalus/dctx.py:46`. MODULE-LEVEL. Target: `daedalus.sensitivity` --
  **foundation** (declared FOUNDATION in this packet's scope).
- `from .structcore.slice import _read, semantic_slice` -- `daedalus/dctx.py:50`.
  MODULE-LEVEL. Target: `daedalus.structcore` -- existing real package, not one
  of the eleven flat modules assigned to me and not on the declared-FOUNDATION
  list either. Per `docs/architecture/import-boundaries.json`, `daedalus.
  structcore` is on the ALLOWLIST both `spine-no-outer-layers` (:98) and
  `twin-no-outer-layers` (:121) grant their own layer, i.e. both spine and twin
  are permitted to depend on it, and its rationale note (:123) says structcore
  "need[s] [its] own rule if [it] ever acquire[s] an outer edge" -- implying it
  currently has none. Best-guess layer for structcore itself (out of my
  assigned scope, not asserted as fact): twin-adjacent/foundation-tier code
  intelligence (Tree-sitter-style slicing per plan section 9.2), sitting below
  both spine and twin. This edge is the one fact that most constrains dctx.py's
  own destination -- see section 5.
- `from daedalus.budget import process_guard_boundary_decision` --
  `daedalus/dctx.py:436`, inside `def main()` (:409). DEFERRED. Target:
  `daedalus.budget` -- **foundation** (declared).
- `from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect` --
  `daedalus/dctx.py:437`, inside `def main()`. DEFERRED. Target:
  `daedalus.spine` -- existing package, spine layer.

Third-party imports: none. `hashlib`, `json`, `subprocess`, `pathlib.Path`, and
(inside `main()`) `argparse` are all stdlib.

## 5. Proposed destination

**twin**. Confidence: medium.

Argument from measured edges: this module's only two substantive daedalus
dependencies are `daedalus.sensitivity` (foundation -- allowed from every layer)
and `daedalus.structcore.slice` (module-level, unconditional -- the module's own
docstring calls `structcore.slice.semantic_slice` the thing this file is "a thin
wrapper over," :9-12, and forbids re-implementing any of its logic). `structcore`
is precisely the Project Twin's code-plane slicer per plan section 9.2
("Tree-sitter/SCIP/Joern for code intelligence"), and both `spine-no-outer-layers`
and `twin-no-outer-layers` already treat `daedalus.structcore` as a legitimate,
named dependency of their own layer (section 4). `dctx.py` produces a
content-addressed, offline-verifiable certificate ABOUT a Twin-plane slice --
"what was included, what was withheld, what the source bytes were" (:18-20) --
which is squarely Twin-adjacent evidence/provenance machinery, not orchestration
policy or an interface. Its only OTHER dependencies at runtime are deferred,
function-scoped, and gated behind the canonical effect boundary
(`daedalus.budget`, `daedalus.spine.effect_boundary`) purely to let `main()`
mint through the CLI safely -- they do not run when `compile()`/`verify()` are
called as a library, which is the shape every real importer (section 3) uses:
`cli.py` calls `main()` (which itself calls `compile()`), while all three test
files call `compile()`/`verify()` directly, never touching the CLI/budget path.

Two competing readings I considered and rejected at higher confidence:
- **interfaces/cli**: `main()` (:409-451) is a real `argparse` CLI and IS the
  only way an external user reaches this module today (`daedalus dctx ...`,
  `cli.py:1149`). But `main()` is 43 of 455 lines (:409-451) and is a thin
  dispatcher over `compile()`/`verify()`, which are the actual payload and are
  called directly by every test. Splitting the CLI wrapper into
  `interfaces/cli` while the certificate logic stays in `twin` is possible but
  is a second Work Packet's decision, not evidence this whole file belongs in
  interfaces.
- **foundation**: tempting because `dctx.py` has almost no daedalus dependencies
  and the module docstring insists it "ADDS NO CONTEXT LOGIC" (:9). But
  foundation in this packet's terms is the seven already-declared modules
  (atomic, budget, config, limit_policy, primary_tree, sensitivity, storage) that
  everything else, including twin, is meant to sit on -- and `dctx.py` itself
  depends on `structcore` (twin-adjacent), which nothing in the declared
  foundation set does. A module that consumes twin-tier slicing cannot be
  foundation to twin.

What would change my mind: an authoritative classification of `daedalus.
structcore` itself as `foundation` rather than `twin` would remove the one edge
tying this file to the twin layer and make **foundation** the stronger reading
instead (its sensitivity dependency already fits foundation, and its remaining
edges are deferred/CLI-only). Conversely, if `structcore` is classified as
`kernel`, `twin` still holds via the `twin -> kernel, spine, structcore`
allowlist (section 6c), so that particular alternative would not change this
verdict.

## 6. Boundary-rule check after the move

(a) Would `daedalus.twin.dctx`'s own imports be refused by `twin-no-outer-layers`?
No. `twin-no-outer-layers`'s allowlist is exactly `kernel, spine, structcore`
(`import-boundaries.json:118-122`). This file's two module-level daedalus edges
are `daedalus.sensitivity` and `daedalus.structcore` -- see (c), `sensitivity` is
NOT on that allowlist and would be REFUSED. The two deferred edges inside
`main()`, `daedalus.budget` and `daedalus.spine`, are also checked: `spine` IS
allowed; `budget` is NOT (and note the rule's own rationale explicitly discusses
walking "the whole AST," :123 in the spine rule's twin, so it sees this
function-scope import too, not just module scope). Concrete offending edges if
this module lands in `twin` unmodified:
  - `daedalus/dctx.py:46` -- `from .sensitivity import ...` -- `daedalus.
    sensitivity` not in twin's allowlist. REFUSED.
  - `daedalus/dctx.py:436` -- `from daedalus.budget import ...` (inside
    `main()`) -- `daedalus.budget` not in twin's allowlist. REFUSED.

(b) Does a current rule name this module by prefix? No. `dctx` does not appear
in any `forbidden_target_prefixes` or `allowed_target_prefixes` list in any of
the four rules. Nothing is unblocked or newly blocked by the bare act of moving
it into a package, other than activating whichever layer-source rule already
exists for the destination package (see (a) for `twin`).

(c) Destination is one of kernel/spine/twin, so allowlists apply -- enumerated
exactly, per (a): `daedalus.sensitivity` (:46, module-level) and `daedalus.
budget` (:436, deferred inside `main()`) are the two flat-module imports this
file makes that are NOT on `twin-no-outer-layers`'s allowlist and would be
REFUSED if this file moves to `twin` as-is. `daedalus.structcore` (:50) and
`daedalus.spine` (:437) are both already on that allowlist and need no action.
Two live options to reconcile this, for whichever packet actually executes the
move: either (i) get `daedalus.sensitivity` added to `twin-no-outer-layers`'s
allowlist alongside the other declared-foundation entries already granted to
`kernel-no-outer-layers` (atomic, budget, config, limit_policy, primary_tree,
sensitivity, storage -- note `sensitivity` IS already granted to `kernel` at
:43 but not to `twin`), which looks like an oversight given `twin` is meant to
sit no higher than `kernel` in the stack; or (ii) leave `main()`'s CLI-only
`daedalus.budget`/`daedalus.spine.effect_boundary` pair behind in a thin
`interfaces/cli` wrapper (see section 5's rejected-alternative discussion) so
the `twin`-resident core (`compile`/`verify`/`_commit`/etc.) only needs
`sensitivity` and `structcore` allowed. Either fix is a decision for the
packet that actually executes this move, not something this dossier resolves.

(d) Destination is `twin`, not `orchestration`, so the orchestration-specific
check does not directly apply. For completeness: `daedalus.orchestration` is
forbidden as a target from kernel, spine, AND twin alike (all three rules list
it, :29/:83/:113), and this file does not import `daedalus.orchestration` at any
scope (confirmed by the full read in section 4 -- only four daedalus edges
exist in the whole file, none of them orchestration), so there is no
orchestration-related hazard from this specific move.

## 7. Dead-code signals

Not applicable as a finding of absence: importers == 4 static edges (section 3),
one of them (`daedalus/cli.py:1149`) is a live production CLI dispatch reachable
from the package's sole console-script entrypoint (`pyproject.toml:77-78`,
`daedalus = "daedalus.cli:main"` -> `cli.py`'s `main()` -> the `elif cmd ==
"dctx":` branch at :1148-1149), and `cli.py`'s own top-of-file usage banner
documents the subcommand explicitly (`daedalus/cli.py:35`, `daedalus dctx <repo>
<target> [--out F] | dctx <repo> --verify F`). LIVE.

Searches run to satisfy the checklist even though importers > 0 and a promised
reader is already evident:
- Docstring/comments for a promised reader: the module's own docstring commits
  to a specific consumer relationship it warns against re-deriving --
  `daedalus/eval/tasks.py` and `eval/harness.py:_recall` are named by path as
  the circular pattern this module was built to avoid (`daedalus/dctx.py:167-
  170`) -- confirming this module has a designed place in the eval/twin
  provenance story, not an orphaned utility.
- `pyproject.toml` console_scripts: only `daedalus` and `daedalus-chip`
  (`pyproject.toml:77-79`); `dctx` is reached as a subcommand of `daedalus`, not
  its own entrypoint, consistent with `cli.py`'s dispatch table.
- Bare-string / dynamic reference grep: `dctx` (case-sensitive substring) across
  `daedalus/`, `tests/`, `docs/`, plus zero-hit checks in `apps/`, `.claude/`,
  `scripts/`, `tools/`. Hits beyond the four import edges are all data/prose:
  `daedalus/eval/minted_tasks.json:565` (`"target": "daedalus/dctx.py"`, a task
  fixture path, not code), `docs/architecture-state.json:57`, and narrative
  mentions in `docs/architecture-narrative.md:42,91,248` and
  `WATCHDOG_STATUS.md:295` describing the module's history -- no CLI subcommand
  string outside `cli.py`'s own dispatch, no registry key, no other dynamic
  loader.
- Git history: `git log --oneline -- daedalus/dctx.py` shows two commits:
  `83380687 feat(dctx): certified context receipts - deterministic SHA, offline
  verify, anti-tautology provenance` (the module's introduction) and
  `bcc0feaf feat(g0): port the central-wiring mission -- 58 doors gained real
  gates, 12 remain with reasons` (the commit that added the `cli.dctx`
  `EntrypointSpec` and the `begin_effect` call inside `main()`, per
  `daedalus/spine/effect_boundary.py:733-746`). No evidence of a removed
  consumer; the second commit is exactly the wiring this dossier finds still
  live.

Label: **LIVE**.
