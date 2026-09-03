# G1-ISO-01 — the behavior probe leaves the verifier process

Packet ID: `G1-ISO-01`
Active gate: Gate 1 (Renovation ignition slice)
Classification: `ALIGNED`
Owner: repository owner
Base revision: `b7251af8`
Branch: `packet/g1-iso-01`
Dependencies: none (the Gate-1 slice is green at this revision — see
`runs/ignition/mission-gate1-voltage-ignition/receipt.json`, measured
2026-09-03, `replay_demonstrated: true`)

## 1. The defect

`daedalus/ignition/runner.py::_behavior` (aliased as `candidate_behavior`, and
called by `daedalus/ignition/gate1.py:1068`) imports the CANDIDATE package into
the verifier's own interpreter:

```python
sys.path.insert(0, source)
module = importlib.import_module("ignition_app")
event = module.parse_event({"id": "1", "bias_voltage": "125.0"})
```

That interpreter is the same process that holds the `python.attempt`
EffectLease, assembles the `EvidencePacket`, decides `behavior_ok`, and writes
the receipt. Candidate module-level code therefore executes inside its own
evaluator.

This was named on 2026-08-17 in
`docs/work-packets/G1_ACTIVATION_CHECKLIST.md` §2.3 and never closed.

Rules it violates:

- master plan invariant 3 (Isolation): "Candidate execution is
  capability-bounded and cannot modify its evaluator, policy, evidence, budget
  ledger, or promotion mechanism";
- master plan §13, forbidden directions: "candidate access to its evaluator";
- `AGENTS.md` review rules: "candidate access to its evaluator or policy" is a
  release-blocking defect.

Aggravating detail: the resulting measurement is recorded with
`assurance="deterministic"` and enters the PASSED `EvidencePacket` as
`gate1-behavior`. Evidence produced by in-process candidate execution is
currently counted as independent evaluator evidence.

Today's candidate is produced by a deterministic rename operator and is benign.
The packet is about the mechanism, not about this candidate.

## 2. Baseline (measured before any change)

`tests/ignition/test_behavior_probe_isolation.py`, run against the unmodified
implementation at `b7251af8`:

```
4 failed, 2 passed in 18.94s
```

The discriminating failure, which no implementation can satisfy without
actually leaving the interpreter:

```
test_candidate_import_does_not_run_in_this_process
E   AssertionError: candidate code executed inside the verifier process
E   assert 54412 != 54412
```

The other three baseline failures are `isolation` not declared, and two raw
exceptions (`ModuleNotFoundError`, `RuntimeError`) escaping instead of
`IgnitionError`.

## 3. Scope

In scope:

- `daedalus/ignition/runner.py` — `_behavior` only, plus its imports;
- `tests/ignition/test_behavior_probe_isolation.py` — new.

Forbidden paths: the master plan, the amendment chain, `AGENTS.md`,
`daedalus/spine/**`, `daedalus/kernel/**`, `daedalus/ignition/gate1.py`,
anything under `apps/`. The receipt's contract does not change, so `gate1.py`
needs no edit; if it turns out to need one, that is a new packet.

## 4. Decision, and the option that was rejected

**Chosen:** run the probe in a bounded child interpreter
(`sys.executable -I -c <probe>`), parse one JSON object from its stdout.

**Rejected: `daedalus.spine.containment.spawn_contained`** (Low-integrity job
object), which is the stronger isolation and is already in the tree. Three
measured reasons:

1. `containment.platform_supported()` is `os.name == "nt"`; `spawn_contained`
   raises `ContainmentUnavailable` elsewhere and, by design, "never falls back
   to an ordinary spawn". Using it would make the Gate-1 slice win32-only — a
   portability regression in a slice the plan expects to run on supported
   platforms.
2. With `log=None` the contained child "has no stdio", so the probe's JSON
   result could not be read back. Wiring a `LowIntegrityLog` for a single
   four-field measurement is a larger integration than this packet's axis.
3. Overstating the guarantee is itself a listed defect. A child interpreter is
   PROCESS isolation, not capability-bounded containment.

Consequence, stated rather than hidden: the probe result declares
`"isolation": "subprocess"`. It does not claim containment. Escalating this
probe to `spawn_contained` where the platform supports it is deferred work, not
part of this packet.

## 5. Acceptance matrix

| # | Claim | Test | Must fail before |
| --- | --- | --- | --- |
| 1 | candidate code does not execute in the verifier process | `test_candidate_import_does_not_run_in_this_process` | yes (pid equality) |
| 2 | the rename measurement is unchanged | `test_probe_still_reports_the_rename_contract` | no (regression guard) |
| 3 | the evidence names its isolation mode | `test_probe_declares_how_it_isolated` | yes |
| 4 | the measurement is byte-stable across runs | `test_probe_output_is_stable_across_runs` | no (replay guard) |
| 5 | a candidate that raises is a refusal carrying its cause | `test_a_candidate_that_raises_is_a_refusal` | yes |
| 6 | a missing candidate package is a refusal, never an in-process fallback | `test_a_missing_candidate_package_is_a_refusal` | yes |

Integration acceptance (not a unit test):

| # | Claim | Evidence |
| --- | --- | --- |
| 7 | the Gate-1 slice is still green end to end | `python -m daedalus.ignition` exit 0, `blockers: []` |
| 8 | replay still demonstrated under the new evaluator | receipt `replay_demonstrated: true` on the third run |
| 9 | the pre-existing rehearsal suites stay green | `tests/ignition/`, `tests/test_ignition_gate1.py` |

Claim 4 is load-bearing and easy to get wrong: `gate1` digests the returned
mapping into the `ignition-behavior` evidence item, and the receipt compares
two runs' check reports. A pid, duration or absolute path in the result would
make every Gate-1 run report itself as a failed replay.

## 6. Expected failures

- The FIRST run after this change is legitimately not a replay: the evaluator
  bundle digest moves because `runner.py` moved. Two further runs are required
  before `replay_demonstrated` can be true again.
- The probe adds one interpreter start per slice run. [MEASURED 2026-09-03,
  7 calls on this box] 49/51/51/51/59/62/64 ms, median **51 ms** — below the
  0.1-0.3 s this packet first estimated. Slice wall time over the three
  acceptance runs was 15/15/17 s, unchanged within noise.

## 7. Rollback

Revert the single commit on `packet/g1-iso-01`. No schema, no stored artifact,
no ledger and no receipt contract changes shape, so a revert needs no
migration. The `isolation` key disappearing from the behavior mapping changes
the `ignition-behavior` output digest, which is a new evaluator bundle and
therefore a new replay baseline — the same two-run cost as adopting it.

## 8. Review questions

1. Does `-I` (isolated mode) actually prevent the child from importing the
   evaluator's own package, or only from reading `PYTHON*` environment
   variables and the script directory?
2. Is `subprocess.run(..., timeout=)` sufficient on win32 to guarantee the
   child tree is dead, or does the probe need
   `daedalus.spine.cancel.ManagedProcess` like the gate path does?
3. Does any other evaluator in the ignition path import candidate code
   in-process (the schema and link checks read files; `pytest_check` already
   spawns)?
4. Is `runs/ignition/**` tracked evidence that a green run on this branch would
   overwrite, and should the packet's runs therefore stay in a worktree?
