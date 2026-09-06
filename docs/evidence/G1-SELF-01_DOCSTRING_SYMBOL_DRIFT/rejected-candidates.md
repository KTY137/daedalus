# G1-SELF-01 — every target considered, and why all but one were rejected

Search was read-only throughout (`git grep`, `ast` parsing, reading). Nothing in
any working tree was edited during the search or the campaign.

Base revision: `cfe8d34b8ef1438156e6fa3e6982f5a30d91696f`.

## Accepted

**`daedalus/build.py`, module docstring lines 4 and 16** — two Sphinx
cross-references to `daedalus.kairos.scheduler.Ikarus` (one of them
`…Ikarus.spawn`). `daedalus/kairos/scheduler.py` exists and its top level
defines `spend_refused_result`, `_paths_overlap`, `Assignment`,
`KairosScheduler`, `_demo_tasks`, `main` — no `Ikarus`. Line 29 of the *same
docstring* correctly writes `daedalus.kairos.scheduler.KairosScheduler`, so the
file contradicts itself. `KairosScheduler.spawn` exists (`scheduler.py:469`,
inside the class at lines 138–498), so the corrected reference resolves in full.

Why this one:

- **Present tense.** It is not a dated measurement of a past state; it tells a
  reader today where to look, and the place it names is not there.
- **The repository already owns this defect class.**
  `daedalus/spine/docrefs.py` defines it exactly — "a reference in the
  documentation to a code symbol that does not exist" — and judges a reference
  only when THE MODULE EXISTS AND THE SYMBOL DOES NOT, which is its entire
  false-positive filter. This case satisfies that filter.
- **Mechanically discriminating.** The frozen gate
  (`gate_docstring_symbol_refs.py`) reuses `docrefs.resolve_reference`, the
  repository's own resolver, and separates the arms: exit 1 on base, baseline
  and negative control; exit 0 on the repair.
- **It does not lower the denominator.** `docrefs`' stated anti-gaming
  invariant is that a fix must never reduce the number of references that
  resolve. Here `n_resolving` rises 11 -> 13 and `n_broken` falls 2 -> 0.
- **`before` occurs exactly once** (764 bytes, 13 lines, the minimal contiguous
  span covering both broken references).
- **`Ikarus` is a public top-level concept**, not a local class name. Master
  plan §3 fixes Ikarus as the persistent assistant/orchestration layer and
  AGENTS.md repeats it. A docstring asserting that a class called `Ikarus`
  lives in `daedalus/kairos/scheduler.py` misattributes one of the three public
  concepts to a local scheduler, which is the confusion the boundary exists to
  prevent.

## Rejected

### 1. The stage-5 target — the Codex `.CMD` shim claim in `CLAUDE.md`

Protected. Master plan §16: ordinary tasks must not edit the plan, the
amendment chain, active instructions or guards; the lane brief forbids it
independently. Already nominated by G1-SELF-00 in any case.

### 2. `daedalus/lanes/checks.py:132` — "`tests/test_iron_plan_guard.py`, a real committed file"

`tests/test_iron_plan_guard.py` was removed on 2026-08-22 with the guard
retirement, so the sentence names a file that is gone. **Rejected because it is
a dated measurement**, opening `MEASURED 2026-07-30:` and recording what the
gate reported on that date, when the file was real and committed. AGENTS.md
working agreement 4 requires retaining experimental evidence; rewriting a dated
record so it matches today's tree destroys the record instead of repairing it.
The honest remedy is an annotation by the owner, not an autonomous repair.

### 3. `daedalus/sensitivity.py:215` — "`WRITABLE  tools/iron_plan_guard.py`"

Same shape, same rejection. The comment opens `THE SECOND HALF OF THIS TUPLE IS
THE HARNESS'S OWN GOVERNANCE, and it was missing. MEASURED against
DEFAULT_POLICY` — the whole block exists to record a pre-fence state. Its
falsity relative to today is the point of it.

### 4. `daedalus/status.py:90` — `"""The six counters, unchanged."""`

`collect_status` returns a dict with **eight** keys. Rejected as **not
deterministically refuted**: `print_counters` immediately below emits exactly
six lines before the git-status block (Repo, Branch, Outbox, Inbox, Memory,
TODO snapshot), so "six counters" plausibly names the rendered counters rather
than the dict keys, and four of the eight keys are not counts at all
(`repo_root`, `git_branch`, `git_status`, `todo_snapshot`). A gate would have to
choose which reading the author meant. That is interpretation, not measurement,
and a campaign must not nominate a repair to a sentence that may be true.

### 5. `__all__` names with no matching definition in seven modules

An AST sweep flagged `daedalus/__init__.py`, `daedalus/kernel/policy/__init__.py`,
`daedalus/spine/__init__.py`, `daedalus/spine/attempt.py`,
`daedalus/orchestration/__init__.py`, `daedalus/structcore/__init__.py` and
`daedalus/kernel/runtime_authorization_issuer.py`. **All false positives of the
sweep**: these are re-export facades whose names arrive through star imports,
lazy module `__getattr__`, or `TYPE_CHECKING` blocks the sweep did not follow.
Not defects; recorded so the negative result is not re-derived.

### 6. The 80 broken references the repository's own gate already reports

`daedalus.spine.docrefs.scan()` at this revision measures 655 files scanned,
**3050 resolving, 80 broken** over its corpus `DOC_GLOBS = ("docs/**/*.md",
"README.md")`. Rejected as campaign targets: the great majority sit in dated
work packets, handoffs and research notes describing a past, planned or refused
state — precisely the false-positive class the `docrefs` module docstring warns
about ("a plan describes what will be built, an ADR describes an option that was
refused"). Two checked in detail:

- `docs/STATUS.md:66-67`, `policy.high_risk_paths` and `policy.write_allow`.
  These name **JSON keys of `.agentenv/agentenv.json`**, not Python symbols;
  `daedalus/kernel/contracts/policy.py` is a coincidental basename and is a
  facade whose only top-level statement is `__all__`. Repairing this would turn
  accurate prose into a falsehood. It belongs on the `_NON_MODULE_DOTTED_NAMES`
  list, not in a campaign.
- `docs/work-packets/G1-UI-12_SCENE_ENVIRONMENTS.md` and its siblings —
  packet prose about symbols that were planned or later renamed; dated records.

### 7. The other 11 first-party references inside `daedalus/build.py`

All resolve. They are the gate's denominator, not defects.

## Observation retained for the owner (not acted on)

`docrefs`' corpus is `DOC_GLOBS = ("docs/**/*.md", "README.md")`. A **docstring
is also prose**, and the defect this campaign repaired sat in one, so the gate
the repository built for exactly this defect class could not see it. Widening
`DOC_GLOBS` to `.py` docstrings would be a code change to the picker's work
source and a new autonomous-edit surface over `daedalus/`, which the module
docstring says was the day-one failure mode. It is therefore recorded here as a
`BACKLOG` observation for an owner decision, and deliberately not attempted in
this EXPERIMENT.

## Search coverage and its limits

Read-only sweeps performed: stale filesystem-path references in comments,
docstrings and message strings under `daedalus/` and `tools/`; `__all__` versus
definitions; unresolved Sphinx cross-references across the whole package;
count/enumeration claims in docstrings versus the code beneath them; the
repository's own `docrefs.scan` over its documentation corpus.

Not claimed: exhaustiveness. One parallel read-only scout searching for stale
path references was lost to a session restart before it reported, and its
findings are not in this record. Dead branches were not searched systematically
— detecting an unreachable branch mechanically is a larger job than this packet
budgeted, and a hand-picked one would not carry a frozen discriminating gate.
