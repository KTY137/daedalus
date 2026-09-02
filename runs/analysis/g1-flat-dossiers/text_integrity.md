# daedalus/text_integrity.py — classification dossier

Scope note: same restriction as the `skills.py` dossier — every search below
is `git grep`/AST-scoped to `daedalus`, `tests`, `tools` only
(`git ls-files -- daedalus tests tools '*.py'`, 1536 tracked files matched by
that pathspec; `.claude/worktrees/agent-*/` full-repo copies were never
searched, so nothing here double-counts an importer that also exists in a
worktree copy).

## Identity

`C:/Users/Administrator/daedalus/daedalus/text_integrity.py`, 26 lines. One
function, `safe_terminal_text(value)`, that collapses an untrusted value to a
single bounded printable-ASCII line for terminal display without mutating the
retained evidence value itself.

## Importers (MEASURED)

AST scan + `git grep` cross-check agree on 3 hits, 0 deferred:

| file:line | kind |
| --- | --- |
| `daedalus/eval/_text_integrity.py:18` | `from daedalus.text_integrity import (TERMINAL_FIELD_MAX_CHARS, safe_terminal_text)` |
| `daedalus/loop.py:104` | `from .text_integrity import safe_terminal_text` |
| `tests/test_loop_terminal_rendering.py:10` | `from daedalus.text_integrity import (...)` |

2 daedalus/ sites + 1 tests/ site — matches the lead's precomputed count
exactly. Note `daedalus/eval/tier2.py:15` imports `from ._text_integrity import
(...)` — that is a *different*, local module
(`daedalus/eval/_text_integrity.py`, a 191-line Tier-2-specific wrapper that
re-exports `safe_terminal_text` as `safe_ascii_field` and adds
`expected_asserted`), not a direct importer of the target module; it is one
hop downstream and is walked in Dead-code signals below.

Dynamic/string references searched and found NONE: `importlib.*text_integrity`,
`__import__.*text_integrity`, the literal strings `"daedalus.text_integrity"` /
`'daedalus.text_integrity'`, `-m daedalus.text_integrity`, any `*_REGISTRY = {`
table, and `pyproject.toml` `[project.scripts]` (only `daedalus:main` and
`daedalus-chip:main`) — zero matches in all cases.

## Imports (MEASURED)

AST script run with `.venv/Scripts/python.exe`:

```
=== daedalus/text_integrity.py ===
daedalus/text_integrity.py:9 enclosing='<module>' :: from __future__ import annotations
```

**Module-level:** 1 import, `from __future__ import annotations` (a syntax
directive, not a dependency) — zero stdlib, zero third-party, zero
`daedalus.*`. **Deferred/function-scope:** 0 (confirmed by AST scan and a
plain grep for indented `import`/`from` lines — no hits beyond the module-level
`__future__` line).

## What it does

Provides exactly one presentation-boundary function that strips a value to
whitespace-joined text, transliterates it to printable ASCII (replacing C0/C1
controls, bidi/format controls, and lone surrogates with `?`), and truncates
it to `TERMINAL_FIELD_MAX_CHARS` (160) with an ellipsis. It exists so a
terminal rendering path never has to re-derive this sanitization inline, and
so retained evidence dictionaries stay byte-for-byte untouched while only the
terminal projection is lossy. 26 lines, zero dependencies.

## Proposed destination

**`foundation`.** Argument: 26 lines, literally zero imports beyond
`__future__`, one pure function with no side effects, no I/O, no `daedalus.*`
coupling of any kind — the textbook shape of the existing foundation set
(all leaf, near-zero-dependency utility modules). It is also *used by*
`daedalus/loop.py`, itself a live production console door
(`python -m daedalus.loop`, registered as a canonical guarded effect target
in `daedalus/spine/effect_boundary.py:566,576` with anchor
`"daedalus.loop:main"`), so this is not a hypothetically-foundational module —
it backs a real production entrypoint today.
Strongest counter-argument: at 26 lines it is arguably too small to deserve
module status at all, and could be inlined into each of its two callers
instead of moved. It loses (see Dead-code signals) because inlining would
duplicate the exact sanitization logic in two places — `daedalus/loop.py` and
`daedalus/eval/_text_integrity.py` — which is precisely the "one canonical
path per responsibility" rule this repo's own instructions (`AGENTS.md` §
non-negotiable boundaries) forbid recreating by hand in two call sites.

## Boundary-rule verdict after the move

Same four rules as the `skills.py` dossier, bound only to
`daedalus.kernel`/`daedalus.runtimes`/`daedalus.spine`/`daedalus.twin` as
SOURCE prefixes.

- **(b) target direction — CLEAN, vacuously**, per the lead's measurement: no
  file under `daedalus/kernel`, `daedalus/spine`, `daedalus/twin`, or
  `daedalus/runtimes` imports `daedalus.text_integrity` at any AST scope,
  confirmed independently here (0 hits in those four subtrees; both real
  importers — `daedalus/loop.py` and `daedalus/eval/_text_integrity.py` — sit
  outside all four). **Foundation caveat** (stated for completeness, does not
  bite): moving an *already-allowlisted* flat kernel/spine name to
  `daedalus.foundation.<name>` would drop it off the kernel/spine allowlist
  and refuse those layers' imports of it. `text_integrity` was never on either
  allowlist and no kernel/spine/twin/runtimes file imports it, so this caveat
  is inapplicable here — noted only because a later foundation-migration
  packet for the seven currently-allowlisted names will need exactly this
  distinction.
- **(a) source direction — N/A, not a rule source.** `daedalus.foundation` is
  not one of the four bound source prefixes; moving `text_integrity.py` there
  never makes it an evaluated SOURCE. It has zero `daedalus.*` imports to
  refuse regardless (see Imports above).

One-line verdict: **CLEAN (vacuous on (b); N/A-not-a-rule-source on (a)).**

## Dead-code signals

This is the main event for a 26-line module. It has 2 real daedalus/ callers,
not zero, and one of them is load-bearing:

- `daedalus/loop.py:104` — `daedalus/loop.py` is a live production console
  door. `git grep "daedalus\.loop" -- daedalus tests tools` shows it registered
  in `daedalus/spine/effect_boundary.py` as a canonical guarded effect target
  (`target="daedalus.loop:main"`, with an explicit comment: *"`python -m
  daedalus.loop` is a SECOND console door into the same [...]"*), has its own
  entrypoint-guard test (`tests/test_loop_entrypoint_guard.py`), and is driven
  operationally by `tools/continuous_daedalus.ps1`. `safe_terminal_text` is
  called directly inside `safe_ascii_field` at `daedalus/loop.py:101-104`,
  which the module's own docstring says exists precisely so callers don't
  reimplement the sanitization.
- `daedalus/eval/_text_integrity.py:18` — chased one hop: `_text_integrity.py`
  re-exports the two names into `daedalus/eval/tier2.py:15`, and `tier2.py`'s
  only importer anywhere in `daedalus`/`tests`/`tools` is
  `tests/test_eval_tier2_integrity.py:16` — i.e. this second chain is
  test-only reachable, same shape as `skills.py`'s chain.

**Inlining vs. moving:** inlining loses here specifically because there are
two independent call sites (one production, one test-only) that would each
need to reproduce the exact ASCII-collapse/truncate logic; a single shared
`foundation` module keeps that logic canonical, matching the module's own
docstring claim that "terminal-facing metadata is rendered as one bounded
printable-ASCII line" — a claim that stops being true by construction the
moment two copies can drift. Moving (not inlining) is the right call.

**What would have to be true for deletion to be safe:** deletion requires
removing or rewriting the `daedalus/loop.py:101-104` call site, which means
`python -m daedalus.loop`'s terminal-rendering path would need a replacement
sanitizer with equivalent bounds — this is not a dead-code deletion, it would
be a behavior change to a live console entrypoint's fail-closed presentation
guard, gated by the same evidence bar as any other production change (tests,
a regression check on `tests/test_loop_terminal_rendering.py`, and an
explicit acceptance criterion). Deletion is therefore **not safe today**;
moving to `foundation` is.

## Confidence

**High.** Importer/import counts reproduce the lead's precomputed numbers
exactly via an independent AST scan; the load-bearing status of
`daedalus/loop.py` as a production entrypoint was confirmed directly against
`daedalus/spine/effect_boundary.py`'s guard registration and
`tests/test_loop_entrypoint_guard.py`, not inferred from the docstring alone.
Would raise further only by actually running
`python -m daedalus.loop --dry-run` to observe the sanitizer fire at runtime —
out of scope for this read-only dossier.
