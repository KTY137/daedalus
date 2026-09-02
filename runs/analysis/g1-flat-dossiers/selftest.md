# daedalus/selftest.py

## Identity

`C:/Users/Administrator/daedalus/daedalus/selftest.py`, 238 lines. A live,
real-Ollama end-to-end round-trip diagnostic (`daedalus selftest`): builds a
throwaway repo, runs one scoped write through the full offload cascade with
every non-local lane forced off, asserts model-agnostic facts (byte change
on disk, compiles, verifier accepted, zero Claude tokens), and cleans up
after itself.

## Importers (MEASURED)

Scope: `daedalus`, `tests`, `tools` only; `.claude/worktrees/agent-*/`
excluded. Searched `from \.+selftest`, `from daedalus.selftest`,
`from daedalus import ...selftest...`, `import daedalus.selftest` (no
nested-package collision — `Glob daedalus/**/selftest.py` = only
`daedalus/selftest.py`).

**daedalus/ — 1 site**: `daedalus/cli.py:1204`
`from .selftest import main as m; m(rest)` — inside
`elif cmd == "selftest":`, **deferred**.

**tests/ — 2 sites**: `tests/test_cli_effect_boundary.py:90`
(`from daedalus import selftest`, inside a function — **deferred**) and
`tests/test_selftest.py:11` (`from daedalus import selftest`, module
level).

**tools/ — 0 sites.**

Total = 1 + 2 + 0 = 3, of which 2 are deferred — matches the lead's
precomputed count (`selftest 3 total = 1 daedalus/ + 2 tests/ + 0 tools/;
2 deferred`) exactly.

Dynamic/string references: `pyproject.toml [project.scripts]` defines only
`daedalus = "daedalus.cli:main"` — no direct console-script entry for
`selftest` (it is reached only through `cli.py`'s `daedalus selftest`
subcommand dispatch). No `importlib`/`__import__` reference found.

**`__main__` guard and CLI wiring** (per the steer, checked for a
`shift_ticker`-style diagnostic-entrypoint shape): confirmed present.
`selftest.py:237-238`:
```
if __name__ == "__main__":
    main()
```
And it is documented and dispatched as a first-class subcommand:
`cli.py:55` (`daedalus selftest [--json]          live Ollama write
round-trip (real, repeatable)`) and `cli.py:1203-1204`
(`elif cmd == "selftest": from .selftest import main as m; m(rest)`).
So it is directly runnable both as `python -m daedalus.selftest` and as
`daedalus selftest [--json]` — a live, documented CLI diagnostic
entrypoint, exactly the `shift_ticker` shape the steer named, not dead code
despite its low (3) importer count.

## Imports (MEASURED)

Module-level (lines 20-30): stdlib only —
`argparse, json, tempfile, time, pathlib.Path`. (The file's own comment at
line 21-27 explicitly explains why `shutil` is *not* imported at module
level — the one recursive delete goes through a guarded walker instead.)
No daedalus imports, no third-party, at module level.

Deferred/function-scope — **5 daedalus imports**, all inside functions:
`from .kairos.worktree import remove_tree_no_follow`
(`_remove_selftest_repo`, line 98); `from .doctor import check` (`run`,
line 120); `from .offload import offload` (`run`, line 126); `from
daedalus.budget import process_guard_boundary_decision` (`main`, line 224);
`from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect`
(`main`, line 225). Five distinct top-level daedalus targets: `kairos`,
`doctor`, `offload`, `budget`, `spine`. No third-party imports anywhere in
the file. Matches the lead's outbound profile (`selftest -> {budget,
doctor, kairos, offload, spine}; 0 third-party; 5 deferred`) exactly.

## What it does

Builds a scratch repo with a minimal agent policy and one seed file, forces
every provider lane except Ollama off via an explicit availability dict
(to stop an external API key silently winning routing), runs one real write
through `offload()`, and checks eight model-agnostic facts (routed to
Ollama, write mode, offloaded, verifier passed, disk actually changed, the
right file was written, the result still compiles, zero Claude tokens) before
tearing the scratch repo down through a reparse-point-safe walker. 238
lines.

## Proposed destination

**interfaces.cli.**

Argument: it is a CLI-invoked diagnostic tool by construction — it has its
own `argparse` parser, its own `__main__` guard, is registered and
documented as a `daedalus <subcommand>` in `cli.py`, and its entire purpose
(per its own docstring) is to be the thing a human or CI job runs to answer
"can the real bench actually write a file and clear the verifier gate, end
to end?" — a question orthogonal to any production request path. It begins
its own effect boundary explicitly (`begin_effect("cli.selftest", ...)`,
line 227-231), which is itself CLI-entrypoint machinery
(`daedalus/spine/effect_boundary.py:624-636` names `cli.selftest` as a
registered CLI entrypoint with anchor `daedalus.selftest:main` /
`begin_effect`), reinforcing that this module's own kernel already treats
it as an interface, not a workload.

Strongest counter-argument: it reaches into orchestration-shaped modules
(`doctor`, `kairos.worktree`, `offload`) more than a typical CLI shim would,
so it could be argued into `orchestration` alongside `offload` itself. This
loses because none of that reach is *orchestration logic* — `selftest`
does not decide routing or compose a mission; it calls `offload()` once
with a fixed, hard-forced availability dict and inspects the result. The
orchestration-shaped imports are inputs to a diagnostic, not the diagnostic
performing orchestration. `interfaces.cli` is exactly the layer meant to
hold thin, single-purpose entrypoints that call into orchestration/runtime
modules without being one themselves.

## Boundary-rule verdict after the move

Direction (b), all four rules: **CLEAN, vacuous** — spot-checked directly,
0 matches for `selftest` under `daedalus/kernel`, `daedalus/spine`,
`daedalus/twin`, `daedalus/runtimes`.

Direction (a) — if `selftest` hypothetically landed in a rule-source layer
itself, using its five deferred daedalus imports (`kairos.worktree`,
`doctor`, `offload`, `budget`, `spine.effect_boundary`):

- **kernel-no-outer-layers** (denylist includes `daedalus.kairos`;
  allowlist = atomic/budget/config/limit_policy/primary_tree/sensitivity/
  spine/storage/twin, `import-boundaries.json:26-46`): **REFUSED** —
  `daedalus.kairos.worktree` at `selftest.py:98` (ground 1, denylist).
  `daedalus.doctor` at `selftest.py:120` and `daedalus.offload` at
  `selftest.py:126` are **also refused** (ground 2 — neither is on the
  allowlist, and neither is in the eight-prefix denylist either, which is
  exactly the allowlist-closes-the-gap case the rule's own rationale
  describes). `daedalus.budget` (line 224) is **allowed** (on the
  allowlist). `daedalus.spine.effect_boundary` (line 225) is **allowed**
  (spine is a permitted peer layer for kernel).
- **runtimes-no-gates** (denylist = `daedalus.gates` only): does
  `selftest` import `daedalus.gates` at any scope? **No** — confirmed by
  reading the whole file; none of its five daedalus imports touch
  `daedalus.gates`. **CLEAN** if it hypothetically landed here.
- **spine-no-outer-layers** (denylist includes `daedalus.kairos` and
  `daedalus.offload`; allowlist = atomic/budget/config/kernel/limit_policy/
  mapping/sensitivity/structcore, `import-boundaries.json:67-98`):
  **REFUSED** — `daedalus.kairos.worktree` at `selftest.py:98` and
  `daedalus.offload` at `selftest.py:126` (both ground 1, denylist).
  `daedalus.doctor` at `selftest.py:120` is **also refused** (ground 2 —
  not on the allowlist and not in this rule's denylist either).
  `daedalus.budget` (line 224) allowed. `daedalus.spine.effect_boundary`
  (line 225) would be a self-import if `selftest` itself were under
  `daedalus.spine` — allowed.
- **twin-no-outer-layers** (denylist includes `daedalus.kairos`; allowlist
  = kernel/spine/structcore, `import-boundaries.json:107-121`):
  **REFUSED** — `daedalus.kairos.worktree` at `selftest.py:98` (ground 1).
  `daedalus.doctor` at `selftest.py:120`, `daedalus.offload` at
  `selftest.py:126`, and `daedalus.budget` at `selftest.py:224` are **all
  also refused** (ground 2 — twin's allowlist is narrower than kernel's and
  spine's and does not include `budget`). `daedalus.spine.effect_boundary`
  (line 225) is allowed (spine is on twin's allowlist).

One-line verdict: **REFUSED (kernel, spine, twin — each via at least
`daedalus.kairos.worktree` at selftest.py:98, plus additional per-layer
refusals detailed above); CLEAN for runtimes-no-gates.** This mirrors the
steer's question directly: `selftest`'s deferred imports of `offload` and
`kairos` are genuinely off-limits for kernel/spine/twin (not merely
off-allowlist noise), which is a second, independent confirmation that this
module is not foundation/kernel-adjacent — it belongs in an outer layer,
consistent with the `interfaces.cli` proposal above.

## Dead-code signals

Zero-importer risk is real in shape (only 3 sites total) but resolved by
direct evidence, not by inference from the name. It is **not** dead:
documented, dispatched, and independently invocable. Docstring (lines 1-16)
states its purpose and explicitly justifies its own existence against "why
not put real Ollama in the unit tests" — a promised reader
(a human/CI operator running `daedalus selftest`) that the `cli.py:55`
help text and `cli.py:1203-1204` dispatch confirm is real, plus
`tests/test_selftest.py` (11 lines of imports, a dedicated test file)
exercising `selftest.run()` under mocks for the harness mechanics while the
capability itself is meant to be run live and separately.

## Confidence

High. Importer/import counts match the lead's precomputed numbers exactly
(3 total, 2 deferred; 5 deferred outbound daedalus imports); the
`__main__`/CLI-entrypoint shape was verified by reading the file directly
rather than assumed from the steer's hint; the boundary-refusal claims were
derived line-by-line from the actual denylist/allowlist text in
`import-boundaries.json`, not estimated.
