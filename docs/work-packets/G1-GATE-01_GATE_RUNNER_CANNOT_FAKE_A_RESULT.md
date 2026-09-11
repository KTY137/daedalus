# G1-GATE-01 - Gate runner cannot fake a result

## Frozen packet metadata

- Packet ID: G1-GATE-01
- Artifact role: primary
- Active gate: 1
- Classification: ALIGNED
- Owner: repository owner
- Base revision: f60ffd3d90c8ed033cb22c54a7a41cc7b21762c9
- Dependencies: G1-HIER-01, G1-HIER-08
- Promotion authority: repository owner; no automatic merge, promotion, or
  Gate transition
- Master-plan authority: Revision 11
- Master-plan digest:
  `711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
- Effect-registry digest:
  `ac0202783602124e761d762dacc84f1c567513eeb12d7f3f48fa70f1396211ec`

## Primary acceptance claim

The `g1` profile includes the two instruments the hierarchy programme is
scored by, and `tools/run_gate_checks.py` names the cause when it cannot
produce a gate result instead of returning an exit code that looks like a
test failure.

## Scope

- `tools/run_gate_checks.py`: add `tests/contracts/` to `G1_TESTS`; add a
  pytest-availability preflight; treat pytest exit code 5 as a refusal.
- `tests/contracts/test_gate_runner_cannot_fake_a_result.py`: new.
- `tests/contracts/test_suite_runs_in_a_virtual_environment.py`: new — refuses
  a result produced by a system-wide interpreter.
- Out of scope: the profile membership of `G0_TESTS`, the `consolidated`
  profile's derivation, the registered `tools.run_gate_checks` effect door,
  and any change to which interpreter CI selects.

## Contracts and behavior

One real gap is closed and two failure modes are given names. Neither of the
named ones was a silent success — see the correction in the evidence section.

**No pytest.** `sys.executable` is whatever launched the script; on this
machine the bare `python` on PATH resolves through a plugin shim to a
different environment without pytest. That case already failed:
`python -m pytest <paths>` prints `No module named pytest` and exits `1`
[MEASURED 2026-09-01 via `subprocess.run`, the same call `_run` makes], which
`_run` propagated. But exit `1` is indistinguishable from a real test failure,
so the operator debugs the tests instead of the interpreter. `_require_pytest`
checks `importlib.util.find_spec("pytest")` in the interpreter that would
spawn the subprocess and exits with `COULD NOT MEASURE` naming it. The check
runs after `--list`, so listing a profile stays available everywhere. This is
defence in depth and a diagnostic improvement, not a leak being plugged.

**Empty profile.** pytest exits `5` when it collected nothing, and `4` when a
path does not exist. Both were already caught by `if completed.returncode:`.
Exit `5` now carries a `COULD NOT MEASURE` message instead of a bare code,
because a renamed path emptying a profile and a genuinely failing test
deserve different words. A real test failure still propagates unchanged.

**Profile membership — the substantive change.** `tests/contracts/` holds the
import-census SCC contract and the Work Packet registry contract. Neither
appeared in any profile, so `run_gate_checks g1` never ran them.
`tests/test_architecture_boundaries.py` was already present and is unchanged.
The `g1` profile goes from 44 to 115 collected tests and still runs in ~9s.

No effect target, registry row, wiring, anchor, digest, CLI name or exit code
for a passing run changes.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
|---|---|---|
| Refuses without pytest | `_require_pytest` under the Hermes interpreter | `SystemExit` naming the interpreter |
| Stands aside with pytest | `_require_pytest` under the repository venv | returns |
| Refuses an empty profile | exit code 5 injected | `COULD NOT MEASURE` |
| Real failure still fails | exit code 1 injected | `SystemExit(1)` |
| Instruments are scored | `PROFILES["g1"]` membership | contains `tests/contracts/` |
| Gate still green | `run_gate_checks.py g1` under the venv | 115 passed, 1 skipped |
| Refuses a system interpreter | venv guard under Python310 `pytest` | 1 failed, exit 1 |
| Effect stability | Registry digest | unchanged digest above |
| Provider/network budget | builder tests only | zero live provider or network calls |

## Migration and rollback

No persistent data, schema, route or CLI-name migration. Rollback restores the
three-line `_run` body, removes `_require_pytest`, its `importlib.util`
import, the `tests/contracts/` profile entry and the new test file. Historical
evidence, CAS, ledgers, databases, generated artifacts, the Master Plan and
the amendment chain are untouched.

## Evidence, expected failures and review

Offline builder tests only; zero live provider, model, container or external
network calls.

```text
main(['g1']) under the Hermes interpreter -> REFUSED: COULD NOT MEASURE ... has no pytest
_require_pytest under the repository venv -> passes through
pytest tests/contracts/test_gate_runner_cannot_fake_a_result.py -q -> 5 passed
tools/run_gate_checks.py g1 (venv)        -> 115 passed, 1 skipped, 28 subtests
venv guard, repository venv               -> 1 passed
venv guard, Python310 system pytest       -> 1 failed, exit 1
```

The refusal is exercised through `main()`, not only through `_require_pytest`
in isolation. Proving a guard by calling the guard leaves the path it must sit
on unverified — a distinction `daedalus-fd` pressed for, and one that was
missing from the first version of this evidence.

**Retained negative evidence: the original justification for this packet was
wrong, and the error is instructive enough to keep.**

This packet was first written and committed claiming that
`python -m pytest <paths>` exits `0` when pytest is missing, and therefore
that `run_gate_checks` reported green gates having executed nothing. That
claim was a measurement artifact. It came from a shell pipeline:

```sh
python -m pytest tests/test_effect_boundary.py -q 2>&1 | tail -1; echo "EXIT=$?"
```

`$?` after a pipeline is the exit status of the *last* command in it — `tail`,
which always succeeds. pytest's own status was never read. Measured three ways
afterwards:

| method | result |
|---|---|
| no pipeline, `> file 2>&1; echo $?` | `1` |
| same pipeline, `${PIPESTATUS[0]}` | `1` |
| `subprocess.run(argv).returncode` — what `_run` actually reads | `1` |

So `if completed.returncode:` did catch it, and the runner never reported a
green gate from a missing pytest. `daedalus-1e` refused the claim with their
own measurement and was right; a second session had independently reproduced
the same wrong `0` through the same pipeline shape, which is how a shell
artifact briefly became a two-source "confirmation".

The error belongs to the very class this packet is about, committed inside the
fix for that class: an instrument — here a bash pipeline — reported success
where nothing had been examined. Anything measured through `cmd | filter` in
this repository is suspect unless it uses `PIPESTATUS` or avoids the pipe.

The `tests/contracts/` profile gap is unaffected by the correction and remains
the substantive change: it was independently verified and the profile really
did go 44 -> 115.

**The genuinely silent case is a different one, and this packet does not close
it.** Found by `daedalus-84`, reproduced here [MEASURED 2026-09-01]. Bare
`pytest` on PATH is not this repository's interpreter:

```text
which pytest -> C:\Users\...\AppData\Local\Programs\Python\Python310\Scripts\pytest.EXE
                pytest 9.1.1, a different installation from .venv
```

It does not refuse and it does not fail to import. Its behaviour splits:

| target | result under the foreign pytest |
|---|---|
| `tests/contracts/test_gate_runner_...py` | `5 passed`, exit `0` |
| `tests/test_hooks_v2.py`, imports `daedalus.hooks` | `155 passed`, exit `0` |
| `tests/contracts/test_work_packet_index.py` | `ModuleNotFoundError: 'tools'`, exit `2` |

The discriminator is not dependency weight. An earlier version of this section
claimed it was, and `daedalus-84` refuted it by running a dependency-heavy file
green under the foreign interpreter. `daedalus` declares `dependencies = []`,
so most of the tree imports under any Python that has pytest. What fails is
incidental -- here a top-level `tools` package absent from the foreign
interpreter's path. Two files in the same directory disagree.

So it is silent wherever the imports happen to resolve, which in a deliberately
dependency-free repository is the normal case, and likeliest on exactly the
narrow targeted runs people make before committing.

It applies to this packet's own test file. `tests/contracts/
test_gate_runner_cannot_fake_a_result.py` needs nothing but pytest and the
standard library, so it passes green under the wrong interpreter — a guard
against wrong-interpreter measurement that is itself measurable by the wrong
interpreter. `_require_pytest` does not help: that interpreter *has* pytest.

`tests/contracts/test_suite_runs_in_a_virtual_environment.py` closes it
partially. `sys.prefix != sys.base_prefix` is true inside a venv and false for
a system installation [MEASURED across the three interpreters on this
machine], so it names no path: a repository `.venv`, a worktree borrowing the
primary checkout's venv, and CI all pass, while the PATH `pytest` does not.

```text
repository venv        -> 1 passed, exit 0
Python310 system pytest -> 1 failed, exit 1
```

The mechanism was proposed by `daedalus-84` over the alternative — "always
write `python -m pytest` with an explicit path" — on the grounds that the
alternative is a discipline rule, and discipline is what failed four separate
times on 2026-09-01. That reasoning is adopted here.

**Its limit, and it is the important half.** The guard only fires when it is
itself collected. A targeted run of one unrelated file under the foreign
interpreter still reports a confident false green — and targeted runs are
precisely where this failure is silent. Closing that needs a session-level
check in `tests/conftest.py`, which would fire on every invocation. That is
not done here: `conftest.py` is shared by every session working in this tree,
a session-start assertion there fails *every* run under a non-venv
interpreter, and whether that is correct for CI and for setups this session
cannot observe is an owner decision, not a builder's.

Known limits, not closed here. The runner still trusts `sys.executable`
rather than pinning the repository virtualenv — the preflight makes the wrong
interpreter loud instead of silent, which is a smaller claim than making it
impossible. Nothing asserts that CI invokes the runner with the right
interpreter. And a profile entry that exists but matches no test file inside a
directory would still collect zero from that entry without emptying the whole
profile.

Review questions: should the runner pin the repository virtualenv outright
rather than only refusing a bad one; does any CI workflow call pytest directly
and therefore bypass both new refusals; and is `consolidated`, derived from
`G0_TESTS + G1_TESTS`, now the profile CI should use.
