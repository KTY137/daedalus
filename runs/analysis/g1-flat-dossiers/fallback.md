# daedalus/fallback.py

## 1. Size and shape

58 lines (`wc -l daedalus/fallback.py` = 58). Zero classes, one top-level
function, zero methods:

- `def fallback_decision(claude_status, risk_level="normal", user_requires_claude=False) -> dict[str, Any]` — `:15`

Module-level state: `DEFAULT_POLICY: dict[str, Any]` (`:6-12`), a
five-key static literal dict describing an agent-collaboration policy
(`claude`/`codex` roles, `on_claude_blocked`, `on_codex_unavailable`,
`review_gate`). No import-time file reads, no import-time `os.environ`
reads, no registry mutation, no network, no singleton mutable container —
confirmed by reading the whole file (58 lines): the only executable
statement at module scope besides `from __future__ import annotations`
and the two stdlib-adjacent `typing` imports is that one dict literal
assignment.

**Naming collision worth flagging (not a bug):** `daedalus/fallback.py`
exports a symbol named `DEFAULT_POLICY`, and so does
`daedalus/sensitivity.py` (`sensitivity.py:272`,
`DEFAULT_POLICY = Policy()`) — a completely different, safety-critical
write-confinement policy object consumed throughout `sensitivity.py`,
`provider_router.py`, `kernel/offload_lease.py`, and multiple tests
(`grep -rn "DEFAULT_POLICY\b"` tree-wide shows both symbols coexisting
with no import collision today, since callers always import the specific
module's `DEFAULT_POLICY` under its own namespace — but the identical name
for an "agent collaboration mode" dict versus a "filesystem write
sensitivity" policy object is a readability trap for a future grep-based
search or refactor).

## 2. What it does

`daedalus/fallback.py` decides how agent work should proceed given
Claude's status, including the case where Claude succeeded — its own
docstring (`:20-27`) explicitly corrects an earlier, narrower reading of
the function's purpose ("NOT only 'when Claude is missing or blocked'").
`fallback_decision()` returns one of four modes — `collaborative` (Claude
produced a usable report), `blocked` (the caller explicitly required
Claude and it is unavailable), `codex_cautious` (Claude unavailable, high
risk, Codex may continue with extra scrutiny), or `codex_solo` (Claude
unavailable, normal risk) — as a dict with `mode`/`continue`/`reason`/`todo`
keys. `DEFAULT_POLICY` is a separate, static description of the same
claude/codex collaboration posture, consumed as data (not called) by its
importers.

## 3. Who imports it (MEASURED)

**TOTAL: 3 importers**, all git-tracked, all MODULE-LEVEL. Commands run:

```
rg -n 'daedalus\.fallback\b|from \.fallback import|from \.\.fallback import|from \. import fallback\b' --glob '*.py'
```

(First pass used a single-dot-only pattern and missed the two-dot form;
re-run with a dot-count-agnostic pattern found all three — same class of
gap the sibling `env.md`/`dotenv.md` cross-checks independently hit for
their own modules.)

| Importer | Line | Form | MODULE-LEVEL / DEFERRED | Layer |
| --- | --- | --- | --- | --- |
| `daedalus/claude_bridge.py` | `:18` | `from .fallback import fallback_decision` | MODULE-LEVEL (called once, at `:140`: `decision = fallback_decision("blocked")`) | flat |
| `daedalus/kairos/orchestrate.py` | `:8` | `from ..fallback import DEFAULT_POLICY` | MODULE-LEVEL (used at `:64` and `:91`, embedded verbatim into two returned payload dicts as `"fallback_policy": DEFAULT_POLICY`) | `daedalus.kairos` |
| `tests/test_agent_env.py` | `:6` | `from daedalus.fallback import fallback_decision` | MODULE-LEVEL, TEST-ONLY | tests/ |

Matches the task's own AST census exactly (3, all module-level:
`claude_bridge.py:18`, `kairos/orchestrate.py:8`, `test_agent_env.py:6`).

### Does `fallback` have a live consumer other than `kairos/orchestrate.py`? — measured answer: effectively no, and `kairos/orchestrate.py` itself is not reachable from the shipped CLI either

Per the established fact from a sibling worker (confirmed independently
here, not re-derived from scratch, plus one further hop of measurement):

- **`daedalus/claude_bridge.py` has zero production importers in the
  tracked tree today.** `grep -rn "claude_bridge"` tree-wide, excluding
  `.daedalus_worktrees/`, `.claude/worktrees/`, `build/`,
  `apps/web/src-tauri/target/`, `apps/web/src-tauri/backend/_internal/`
  (all stale packaged mirrors, not the live source), shows every
  remaining hit is either `daedalus/claude_bridge.py` itself, a docstring
  mention (`daedalus/core.py:1344`, `daedalus/providers/claude_cli.py:14`,
  `daedalus/runtimes/admission/authorization.py:12`), a comment in
  `daedalus/spine/effect_boundary.py` (`:1890`, `:2146`) recording that
  the module's CLI-registry row was **deleted on 2026-08-17**, or a test
  file. Confirmed the deletion is real and enforced:
  `tests/test_effect_boundary.py:527-558`
  (`test_remaining_tools_rows_and_the_invisible_system_check_are_registered`)
  asserts `"cli.claude_bridge" not in by_id` and
  `not any(row.target == "daedalus.claude_bridge:main" for row in
  ENTRYPOINTS)`, with the surrounding comment in
  `effect_boundary.py:2146-2148` explaining why: `"a fail-closed stub
  (parser.error after parse_args, no reachable effect)"`. The build-mirror
  hit `.../providers/claude_cli.py:23: from ..claude_bridge import
  _invoke_claude_payload` does **not** exist in the live tracked
  `daedalus/providers/claude_cli.py` — checked directly
  (`grep -n "claude_bridge" daedalus/providers/claude_cli.py` → one
  docstring mention only, `:14`, no import). `claude_bridge.py` is a
  deregistered, fail-closed stub with a stale packaged-build shadow, not a
  live production entrypoint.
- **`daedalus/kairos/orchestrate.py` is real, tested business logic
  (`prepare_task`/`main`, argparse CLI with `--message`, `--repo-root`,
  `--project`, `--paths`, `--lane`, `--strategy`), but it is not reachable
  from the packaged `daedalus` console-script (`pyproject.toml:78`,
  `daedalus = "daedalus.cli:main"`) at all.** Measured:
  `grep -n "prepare_task\|kairos.orchestrate" daedalus/cli.py
  daedalus/web_api.py daedalus/router.py` → no output in any of the three
  — no CLI subcommand, no HTTP route, no router dispatch reaches it.
  `daedalus/orchestrate.py` (a separate, top-level compatibility shim,
  `"""Compatibility CLI for :mod:`daedalus.kairos.orchestrate`."""`) does
  `from .kairos.orchestrate import _infer_paths, main, prepare_task` and
  exposes `if __name__ == "__main__": main()` — but nothing in the
  tracked tree imports `daedalus.orchestrate` either
  (`grep -rn "from \.orchestrate import\|from daedalus\.orchestrate
  import\|daedalus\.orchestrate:"` → no output outside the file itself),
  and it is absent from `daedalus.cli`'s subcommand dispatch and from
  `daedalus/spine/effect_boundary.py`'s registrations
  (`grep -n "orchestrate" daedalus/spine/effect_boundary.py` → no
  output). The only ways to reach `kairos/orchestrate.py`'s `main()` in
  the current tree are direct script execution
  (`python -m daedalus.kairos.orchestrate` or
  `python daedalus/orchestrate.py`) or `tests/test_agent_env.py`'s direct
  import of `_infer_paths` (`:8`). `DEFAULT_POLICY` itself has no other
  consumer: `grep -rn "DEFAULT_POLICY\b"` tree-wide shows every
  `daedalus.fallback.DEFAULT_POLICY` reference is exactly the three rows
  in the table above; every *other* `DEFAULT_POLICY` hit in the tree
  belongs to the unrelated `daedalus.sensitivity.DEFAULT_POLICY` symbol
  (§1).

**Answer to the mandated question:** `fallback.py` has no consumer that is
both live (module-level or otherwise executed) and reachable from the
shipped `daedalus` console-script surface. Its two "production" importers
are: (1) `claude_bridge.py`, confirmed dead (deregistered fail-closed
stub, zero further callers), and (2) `kairos/orchestrate.py`, confirmed
real and tested but itself orphaned from `daedalus.cli`'s dispatch table —
reachable only by direct script invocation or by test import. So
`fallback.py` **does follow `kairos`**, in the sense that its one
substantive consumer lives in `daedalus.kairos`, but that consumer is
itself two hops removed from anything a packaged `daedalus` install
actually runs. This is a genuine finding about `kairos/orchestrate.py`'s
own wiring (out of scope to fix here — flagging, not touching), not
something that changes `fallback.py`'s own classification decision in §5.

## 4. What it imports (MEASURED)

Zero `daedalus.*` imports. Full import list (`daedalus/fallback.py:1-3`):
- `typing.Any` (stdlib)

No third-party imports, no intra-repo imports — a leaf module exactly like
`env.py` and `dotenv.py` in dependency shape.

## 5. Proposed destination

**orchestration.** Confidence: **medium**.

Argument from measured edges: `fallback.py` itself imports nothing from
`daedalus.*` (§4), so the move is unconstrained by its own dependency
graph — the decision rests entirely on *who legitimately needs it*, not on
*what it needs*. Its one substantive consumer (`kairos/orchestrate.py`,
§3) is squarely an orchestration-layer concern: deciding whether an
in-flight multi-agent task continues, blocks, or falls back to a
different provider is a workflow/scheduling decision, not kernel trust
logic, not spine event-plumbing, not a twin/graph concern, and not a
runtime-admission concern. `daedalus/kairos/` as a package (scheduler,
gated_writes, control, drafts, decompose, worktree) is itself clearly
destined for `orchestration` on the same reasoning, and `fallback.py`
should co-locate with the one place it is actually used.

Confidence is medium rather than high because the measured live-wiring is
weak (§3): the only consumer reachable from the packaged CLI does not
reach `fallback.py` at all (`claude_bridge.py` is dead), and the consumer
that does reach it (`kairos/orchestrate.py`) is itself unwired from
`daedalus.cli`. What would change my mind: if `kairos/orchestrate.py` is
found to be intentionally retired/superseded (rather than merely
unfinished-integration) by a future audit, `fallback.py` would drop to
zero live consumers and become a stronger CANDIDATE-DELETE case (see §7)
rather than an orchestration placement.

**No split boundary** — one function plus one policy-shaped constant
answering the same question ("what happens when Claude isn't available"),
not two things fused.

## 6. Boundary-rule check after the move

**(a) Moved to `orchestration`: would any of its own imports be refused?**
Vacuously no — `fallback.py` imports nothing from `daedalus.*` (§4), so
there is nothing for any rule to refuse regardless of source layer. (Also:
no rule in `docs/architecture/import-boundaries.json` currently sources
`daedalus.orchestration` at all — the four rules only source `kernel`,
`runtimes`, `spine`, `twin` — so even a non-empty import list would face
no governing rule today.)

**(b) Does any CURRENT rule name this module by prefix?** No.
`daedalus.fallback` appears nowhere in any rule's `source_prefixes`,
`forbidden_target_prefixes`, or `allowed_target_prefixes` (confirmed by
reading the full `import-boundaries.json`). No move of this file changes
any rule's behavior today. (`daedalus.kairos`, however, *is* named — see
(e) below.)

**(c) If it lands in kernel/spine/twin: enumeration.** N/A for the
proposed destination (`orchestration`, not kernel/spine/twin) — included
for completeness since the module's own zero-import profile makes the
answer trivial either way: zero `daedalus.*` imports means zero could ever
be refused, so it would satisfy even the strictest allowlist
(`twin-no-outer-layers`) if placed there. No widening of any allowlist
(and therefore no reviewed diff to
`test_the_allowlists_cannot_grow_quietly`) would ever be forced by
`fallback.py`'s own imports.

**(d) Does any rule constrain `daedalus.interfaces` as a SOURCE?** No —
same finding as `env.md`/`dotenv.md`: none of the four rules uses
`daedalus.interfaces` as a `source_prefixes` entry. Not directly relevant
to `fallback.py` (proposed destination is `orchestration`, and no
`daedalus.interfaces` module imports `fallback.py` — confirmed absent from
the importer table in §3), but relevant context for the sibling
`gui_catalogue.md` dossier, which does have an `interfaces/http` importer.

**(e) Mandatory: direction analysis for `fallback` specifically.**
`daedalus/kairos/orchestrate.py` imports `daedalus.fallback` at MODULE
LEVEL (`:8`), and `daedalus.kairos` is named in `forbidden_target_prefixes`
by all three of `kernel-no-outer-layers`, `spine-no-outer-layers`, and
`twin-no-outer-layers`. Precisely, if `fallback.py` were relocated to
`daedalus.kernel.fallback` (or `.spine.fallback` / `.twin.fallback`):

- **The edge that exists is `daedalus.kairos.orchestrate` (source) →
  `daedalus.fallback` (target)`, i.e. OUTER LAYER IMPORTING INNER LAYER.**
  None of the four rules constrain `daedalus.kairos` as a *source* at all
  — `kairos` never appears in any rule's `source_prefixes` — so this edge
  is **not evaluated by any rule today**, and relocating the target module
  under `kernel`/`spine`/`twin` does not change that: the checker only
  fires when the *source* module (the one doing the importing) matches a
  rule's `source_prefixes`, and `kairos/orchestrate.py` never will under
  any of the four defined rules. An outer/orchestration-layer module
  importing a kernel/spine/twin module is exactly the *permitted*
  direction in a layered architecture (kernel/spine/twin sit below
  orchestration and are meant to be imported by it) — it is the reverse
  direction (kernel/spine/twin importing back out into `kairos`) that the
  rules exist to forbid, and `fallback.py` never imports `kairos` (§4:
  zero `daedalus.*` imports), so that reverse edge cannot occur regardless
  of where `fallback.py` lands.
- **Precise statement: no rule fires in either direction if `fallback.py`
  is moved into kernel/spine/twin.** Not because the move is safe by
  design, but because (i) `fallback.py` itself has no outbound
  `daedalus.*` edge that could ever be caught as a forbidden-target hit,
  and (ii) the inbound edge from `kairos/orchestrate.py` runs in the
  permitted inner-is-imported-by-outer direction, which these four rules
  do not evaluate at all (they only ever check kernel/spine/twin/runtimes
  as sources, never as importable-by-outer-code targets). The reason this
  placement is nonetheless a bad idea is a **layering/meaning** argument,
  not a measured mechanical refusal: `fallback_decision()` is an
  orchestration-workflow policy call ("how does agent work continue"),
  and putting workflow policy inside the trust kernel would blur the
  Mission/Policy/Execution/Evidence spine's boundary even though no
  current static rule would catch it. This is exactly why `orchestration`
  (§5), not kernel/spine/twin, is the recommended destination.

## 7. Dead-code signals

**LIVE, but weakly wired** — not CANDIDATE-DELETE. Evidence for "live":
`fallback_decision()` is called by `claude_bridge.py:140` (module itself
dead, §3) and directly tested by `tests/test_agent_env.py:147,152`.
`DEFAULT_POLICY` is embedded into two real payload dicts in
`kairos/orchestrate.py:64,91`, and `kairos/orchestrate.py` has its own
tested, real `argparse` CLI surface (not a stub — full option parsing,
real `prepare_task()` logic that infers paths, calls `route_task`,
appends memory events, and optionally enqueues a Claude review request).
Neither importer's docstring nor the module's own docstring frames
`fallback.py` as provisional or deprecated.

What I searched for a promised reader beyond the measured callers, per the
task's §7 requirement:
- `pyproject.toml`: `grep -n -i "fallback" pyproject.toml` → no output.
  Not a console-script target.
- `docs/architecture/shim-registry.json`: `grep -n "fallback"
  docs/architecture/shim-registry.json` → no output. Not a registered shim.
- `daedalus/spine/effect_boundary.py` registered CLI-target strings (per
  the task's warning about e.g. `"daedalus.arch_memory:main"`):
  `grep -n "daedalus\.fallback\|\"fallback\"\|'fallback'"
  daedalus/spine/effect_boundary.py` → no output. Not registered as an
  effect-boundary door target. (`daedalus.kairos.orchestrate` itself is
  also absent from that file, per §3 — consistent with "unwired, not
  registered.")
- `daedalus.fallback` / `daedalus.kairos.orchestrate` as a bare string
  anywhere in the tracked tree beyond the import forms already counted:
  `grep -rn "daedalus\.fallback\|daedalus\.kairos\.orchestrate"` tree-wide
  (excluding the ignored worktree mirrors) returns only the rows already
  in §3's table plus this dossier itself once written — no dynamic
  `importlib.import_module` or `mock.patch(...)` string reference to
  either module exists (contrast `dotenv.py`, which has exactly one such
  reference in `tests/test_loop_bound_safety.py:58`).
- git log: `git log --follow --diff-filter=A --format="%H %ad %s" --
  daedalus/fallback.py` → introduced `2026-07-06` alongside `env.py` (same
  "API-first Agent OS" commit, `1da0c0d`). `git log --format="%H %ad %s"
  -3 -- daedalus/kairos/orchestrate.py` shows its most recent touch was
  `2026-07-28` ("refactor(kairos): namespace and harden scheduler
  execution") — no commit in the visible history removed a `daedalus.cli`
  wiring for `orchestrate.py`; the compatibility shim
  (`daedalus/orchestrate.py`) and the underlying module read as an
  unfinished integration (a CLI door that was written and tested but never
  connected to the `daedalus` subcommand dispatcher), not a deliberately
  retired one.

**Label: LIVE** (via `kairos/orchestrate.py`, itself
UNWIRED-WITH-PROMISED-READER relative to the packaged `daedalus`
console-script — see §3's closing paragraph). Not CANDIDATE-DELETE: it has
a real, tested, non-stub caller with genuine business logic depending on
it, even though that caller's own reachability from the shipped product
surface is itself the more interesting finding in this dossier.
