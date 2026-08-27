# Kill criterion #1 fires: the deny floor is not a fence for the attempt door

Status: MEASURED — the recommendation it tests is withdrawn
Date: 2026-08-24
Revision measured: `7b05c7f9` (worktree `lane/heracles-deny-floor-corpus`)
Author: HERACLES-ATTEMPT-LEASE
Classification: `ALIGNED`, Gate 0. Invariants 3 (isolation), 4 (evidence
boundary), 8 (bounded effects).
Supersedes: section 7 of `CANDIDATE_WRITE_FENCE.md` (same directory). That
document's answer (c′) — "the declaration ceiling is the deny floor" — is
**refuted here by its own kill criterion #1.** Sections 1–6 of it stand
unchanged; section 7 is replaced by section 6 below.

## 0. Verdict

**Kill criterion #1 fires.** The corpus is 152 paths; the deny floor
(`sensitivity.path_write_blocked` under `DEFAULT_POLICY`, i.e. `write_allow=()`)
**admits 94 of them**, and the admitted set includes every surface that lets a
candidate execute code inside its own evaluator.

Proven by execution, not by inspection: a candidate patch that adds **one file
the floor admits** turns the Gate-1 evaluator's verdict from FAIL to PASS
without touching a single file under test.

```
deny floor admits conftest.py: True

base, no conftest (must FAIL)      passed=False
candidate adds one conftest.py     passed=True
```

The whole patch:

```python
# conftest.py
def pytest_sessionfinish(session, exitstatus):
    session.exitstatus = 0
```

That is Invariant 4 (models propose, independent evaluators decide) and
Invariant 3 (a candidate cannot modify its evaluator) defeated by one admitted
path. **(c′) as written falls.** What survives, and what replaces it, is section
6.

## 1. How the corpus was built

Resolved where it could be resolved; declared, with a reason, only where the
file does not exist yet but a candidate patch could create it.

| class | how | n |
| --- | --- | --- |
| A evaluator reads, inside the candidate tree | **executed** | 6 |
| B evaluator question/process surfaces | declared | 14 |
| C git control surfaces | declared | 13 |
| D promotion boundary | **import trace** | 51 |
| E effect boundary + schemas | **import trace** | 4 |
| F declaration generator + gates | **import trace** | 30 |
| G ledgers + control state | filesystem | 5 |
| H tool + hook surfaces | filesystem glob | 25 |
| I plan + constitution | declared | 4 |

**Class A is the important one and it is not guessed.** The attempt gate is
`python -m pytest -p no:cacheprovider -q --no-header tests/test_event_field.py`
with cwd set to the candidate worktree
(`daedalus/ignition/checks.py:pytest_check`). That exact argv was run against a
real `prepare_ignition_repo` tree under an audit hook recording every `open` and
every loaded module file: **899 opened paths, 563 module files, of which 10 lie
inside the candidate tree** (7 real, 3 `__pycache__`):

```
data/events.csv                 src/ignition_app/repository.py
src/ignition_app/__init__.py    tests/test_event_field.py
src/ignition_app/models.py      wiki/Event.md
```

The other 1297 are the installation and the stdlib — outside the candidate
tree, and therefore the business of `primary_tree` and `containment_escapes`,
not of this ceiling (question 1/2 in `CANDIDATE_WRITE_FENCE.md` §1).

Classes D/E/F are repo-relative names in a *Daedalus* checkout, and they belong
in the corpus for a reason that is not hypothetical: **an Ariadne candidate tree
IS a Daedalus checkout.** When the system evolves itself, `daedalus/…`,
`scripts/…`, `runs/…` are names a candidate can declare.

## 2. The result `[MEASURED]`

```
CORPUS 152 paths | REFUSED by the deny floor 58 | ADMITTED 94

group                                       total  refused  admitted
A evaluator reads, inside candidate tree        6        0         6
B evaluator question/process surfaces          14        0        14
C git control surfaces                         13       10         3
D promotion boundary                           51       21        30
E effect boundary + schemas                     4        2         2
F declaration generator + gates                30        0        30
G ledgers + control state                       5        2         3
H tool + hook surfaces                         25       19         6
I plan + constitution                           4        4         0
```

## 3. Every admitted path an evaluator could read

The assignment asked for these by name. Grouped by what the admission buys.

**Executes code inside the evaluator process (class B — 14 of 14 admitted).**
Every one of these is loaded or consulted by the gate argv before any test body
runs:

```
conftest.py            tests/conftest.py      src/conftest.py
pytest.ini             pyproject.toml         setup.cfg           tox.ini
sitecustomize.py       usercustomize.py       src/sitecustomize.py
ignition_app.pth       src/vendored.pth       setup.py
src/ignition_app/__init__.py
```

`conftest.py` is the one demonstrated in §0. `pytest.ini` / `pyproject.toml` /
`setup.cfg` / `tox.ini` choose plugins, `addopts` and rootdir; `.pth` and
`sitecustomize` run at interpreter startup; `__init__.py` runs on import of the
package under test.

**Is read by the evaluator as its subject (class A — 6 of 6 admitted).**

```
data/events.csv   src/ignition_app/models.py   src/ignition_app/repository.py
wiki/Event.md     src/ignition_app/__init__.py   tests/test_event_field.py
```

Four of these are *declared target paths* — writing them **is the task**, and
`gate1.py` already says so in prose (`gate_reads_scope=True` for the code/type
item, because the suite imports `ignition_app` from `src/`). This is the line
the kill criterion as I originally wrote it could not draw, and §5 draws it.
`tests/test_event_field.py` is the criterion itself, sealed by a *different*
instrument (`gate_criterion_paths`), not by the floor.

**Is the machinery that judges, promotes or bounds (classes D/E/F/G/H — 71
admitted).** Named because each is a thing an evaluator or the kernel reads:

```
daedalus/spine/effect_boundary.py      daedalus/spine/killswitch.py
daedalus/spine/cancel.py               daedalus/storage.py   daedalus/atomic.py
daedalus/schemas.py
daedalus/gates/repository_write_classification.py
daedalus/gates/evidence.py             daedalus/gates/evidence_verifier.py
daedalus/gates/trust_bundle.py         daedalus/gates/release.py
daedalus/runtimes/trust.py             daedalus/runtimes/trust_store.py
daedalus/runtimes/fault_matrix.py      daedalus/runtimes/profiles.py
scripts/declare_write_surfaces.py      scripts/gate0_release.py
scripts/report_gate0_v3.py
runs/budget/ledger.json                runs/spine/spine.sqlite3
runs/hooks/ledger.jsonl
daedalus/hooks/*.py                    daedalus/structcore/*  daedalus/twin/*
.gitattributes  .gitignore  .gitmodules
```

## 4. The floor's refusals are a hazmat list, not a boundary `[MEASURED]`

The 58 refusals are not principled with respect to this door. They come from the
project denylists, not from `GENERIC_DENY_SUBSTRINGS` (`generic_hit=[]` for
every probe below), and they land arbitrarily:

```
daedalus/sensitivity.py                            refused=True
daedalus/spine/killswitch.py                       refused=False
AGENTS.md                                          refused=True
runs/budget/ledger.json                            refused=False
tools/watchdog.py                                  refused=True
daedalus/gates/repository_write_classification.py  refused=False
.git/config                                        refused=True
```

The floor refuses the sensitivity module and admits the **kill switch** module.
It refuses the watchdog and admits the **budget ledger**. It refuses `AGENTS.md`
and admits the **write-classification chain**. That is what a hazmat list built
for a device/vendor repository looks like when it is asked a question about an
evaluator: it answers, and the answer means nothing here. A fence that admits
`daedalus/spine/killswitch.py` is not bounding effects.

## 5. What actually catches the planted conftest — and the two holes `[MEASURED]`

Fairness demands the composition be measured, not just the floor. In the real
attempt path the target-scope check runs **before** the gate
(`attempt.py:1603-1609`), so an out-of-scope `conftest.py` is refused before the
evaluator ever starts:

```
scope=('src/ignition_app/models.py','src/ignition_app/repository.py')
                                        escaped=('conftest.py','tests/conftest.py')
scope=('src/ignition_app',)             escaped=('conftest.py','tests/conftest.py')
scope=('data/events.csv','fourfold.json') escaped=('conftest.py','tests/conftest.py')
```

So for the Gate-1 slice as it stands, the declaration — not the floor — is what
holds the line. Two holes, both measured:

**Hole 1 — an empty declaration disables the check entirely.**
`attempt.py:1603` reads `if self.task.target_paths:`. A task that declares
nothing gets **no scope check at all**, and the planted `conftest.py` lands in
the evaluator. Empty is not "declare nothing"; it is "fence nothing".

**Hole 2 — a declared directory can contain the loader.**

```
scope=('tests',)                        escaped=('conftest.py',)
```

`tests/conftest.py` is **not** escaped. Declaring the `tests` directory — an
entirely ordinary declaration for a test-generation operator, one of the
plan's §9 initial operator families — admits a conftest that pytest loads on the
collection path of the criterion. The floor admits it, `containment_escapes`
admits it, and §0 shows what it then does.

Neither hole is reachable in today's ignition run, because both work items
declare files rather than directories and neither declares nothing. Both become
reachable the moment an operator declares a directory or omits the scope.

## 6. What replaces (c′)

The correction is small and it is the whole of it: **the ceiling is not the deny
floor, and it is not any file-kind predicate. The ceiling is an
authority-declared allowlist of what may be DECLARED, and the declaration is the
fence.**

1. **The operator declares, in the installation's own `.agentenv`, what a
   candidate task may declare** — as an allowlist with the same
   root-anchored prefix semantics `_within_write_allow` already implements,
   evaluated against `target_paths`, positively declared and digested in the
   receipt. Never `DEFAULT_POLICY` reached by absence; that unchanged warning
   from the superseded section is the one part of it that measurement
   strengthened rather than weakened.
2. **The deny floor stays, underneath, as what it is** — a hazmat list that
   composes on top and contributes a few real refusals (`.env`, `secrets/`,
   `id_rsa`, `.git/config`). It is not load-bearing and must not be described
   as the fence.
3. **An empty `target_paths` must refuse the attempt, not skip the check**
   (hole 1). This is the cheapest fix in this document and it is a one-branch
   change at `attempt.py:1603`.
4. **The evaluator's loader set must be excluded from any declaration,
   whatever the ceiling admits** (hole 2) — `conftest.py`, `pytest.ini`,
   `pyproject.toml`, `setup.cfg`, `tox.ini`, `sitecustomize.py`,
   `usercustomize.py`, `*.pth`, and `__init__.py` on the criterion's import
   path. This is the class-B list in §3, and it belongs next to
   `gate_criterion_paths`, which is the instrument that already answers "may the
   candidate write what judges it". The seal covers the criterion **file**; it
   does not cover the files that decide **whether and how the criterion runs**.
5. Parts 3 and 4 of the superseded section (subject/authority split;
   `target_paths` and the intent ledger must be authority-bound) are unaffected
   and still required.

The finding under the correction is the same sentence as before, now with a
fourth instance: the candidate must not supply the material against which it is
judged — not the ledger, not the policy, not the declaration, **and not the
loader that runs its evaluator.**

## 7. What this document does not claim

- It does not claim the ignition slice is exploitable today. §5 says the
  opposite, and names the two declarations that would make it so.
- It does not claim the class-B list is complete. It is 14 entries and pytest,
  setuptools and CPython all grow loaders; the list is a floor for part 4, not a
  ceiling.
- It does not measure the non-pytest gates. Every operator family in plan §9
  brings its own runner, and each has its own loader set.
- Class A was resolved on **one** gate invocation of **one** fixture. A second
  fixture or a second operator would read a different set.

## 8. Reproduction

```
runs/deny-floor-corpus/trace_evaluator.py   # audit-hook trace of the real gate argv
runs/deny-floor-corpus/build_corpus.py      # the 152-path corpus and the table
runs/deny-floor-corpus/evaluator_inside.json
runs/deny-floor-corpus/result.json
```

The §0 subversion is fifteen lines: `prepare_ignition_repo`, write the
`conftest.py` above, call `ignition_checks.pytest_check(repo)` twice — once
without it, once with.

Iron Plan: ALIGNED
Iron Gate: 0 (now CLOSED at 657c8af5, 2026-08-26)
Evidence: the executed FAIL→PASS subversion in §0; the 152-path corpus table in
§2 with 94 admitted; the class-A audit-hook trace (899 opened, 563 module files,
10 inside the candidate tree); the arbitrariness probe in §4; the
`containment_escapes` composition matrix and the two holes in §5, including
`attempt.py:1603`. All at `7b05c7f9`. `tools/iron_plan_guard.py` does not exist
in this tree, so the mandated verify step could not run; the gap is reported,
not routed around. **UPDATE 2026-08-26**: This finding supports recommendation in CANDIDATE_WRITE_FENCE.md §7a; Gate 0 closure decision is recorded at GATE0_CLOSURE_DECISION_20260826.md.
