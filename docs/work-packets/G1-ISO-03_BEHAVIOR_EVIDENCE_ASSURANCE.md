# G1-ISO-03 — the behavior item stops citing a seal it does not have

Packet ID: `G1-ISO-03`
Active gate: Gate 1
Classification: `ALIGNED`
Owner: repository owner
Base revision: `a6e740b1`
Branch: `packet/g1-iso-02` (stacked; G1-ISO-02 green and twice adversarially reviewed)
In scope: `daedalus/ignition/gate1.py`, `tests/test_ignition_gate1.py`
Forbidden: everything else, including `runner.py` and `checks.py` — this packet
changes what the record CLAIMS, not what the probe does.

## 1. Why

`gate1.py` minted the `gate1-behavior` and `gate1-graph-delta` evidence items
with `assurance="deterministic"` as a literal while passing
`assurance_reason=assurance_reason` — the reason **derived** by
`_derive_assurance` for a different set of checks.

`daedalus/spine/receipts.py::evaluator_assurance_detail` states the standard
these two were the exception to, in its first line: *"How much the gate verdict
is worth, and WHY — derived, never asserted."*

## 2. What was actually wrong, and what was not

**Not a bypass, and saying so matters.** `kernel/contracts/canonical.py:1190`
refuses a conclusive packet holding any `unverified` item, so a run whose
derivation fell to `unverified` failed at packet assembly regardless of what
these two literals said. The defect is a contradiction *inside the record*, not
a hole in the gate. An earlier draft of this packet overstated it as a bypass;
that reading is retracted here rather than quietly dropped.

**Wrong, and plainly so:** the behavior report declared
`criterion_paths=("daedalus/ignition/gate1.py",)`. The probe body and the
result contract are `runner._BEHAVIOR_PROBE` and `runner._validated_behavior`;
this module only reads the answer back. `criterion_paths` is a claim about what
judged, and it named the wrong file — from before G1-ISO-01 moved the probe out
of process, which made it wrong a second way.

**Overstated:** the borrowed reason describes an anchored conformance suite,
frozen in the judged tree outside every work item's `target_paths`. The
behavior probe has no such anchor. Its criterion is module code, and — measured
2026-09-03, not assumed — its answer channel is forgeable in four lines:

```python
import __main__, json, os
json.dump({"nonce": __main__._nonce, "result": {...}}, open(__main__._out, "w"))
os._exit(0)
```

under `python -I -c`, `_nonce` and `_out` are ordinary `__main__` attributes.
No `Event` class and no `parse_event` need exist. An item citing another
check's seal is claiming a property it does not have.

## 3. Decision

- pass the **derived** `assurance` to both items rather than a literal;
- give each item **its own** reason, with the composed checks' reason appended
  as context rather than substituted for its own;
- correct `criterion_paths` to `daedalus/ignition/runner.py`.

**Rejected: downgrading the behavior item to `unverified`.** The vocabulary is
`{deterministic, independent, unverified}` and a conclusive packet may hold no
`unverified` item, so this would take the Gate-1 slice from a passing packet to
none at all — trading an overstated label for a destroyed result. The
overstatement lives in the *reason*, and that is where it is fixed.

**Rejected: removing the item from the packet.** It is a real measurement of
real runtime behavior; the schema and link checks have the same shape of limit
and are kept as items with their limit stated. Consistency beats a special case.

## 4. Acceptance

| # | Claim | Test | Red before |
| --- | --- | --- | --- |
| 1 | the item names the module that judged it | `test_the_behavior_item_names_the_module_that_actually_judged_it` | **yes** |
| 2 | the item states its own residual, not another check's seal | `test_the_behavior_item_states_its_own_residual` | **yes** |
| 3 | no item carries an assurance the derivation did not produce | `test_the_derived_assurance_reaches_every_item` | **no — see below** |

Row 3 is a **consistency assertion, not a guard**, and its docstring says so.
In a green run every item is `deterministic`, so it cannot distinguish "derived"
from "asserted the same value"; the discriminating case is refused at packet
assembly before any item is observable, which
`test_an_unverified_assurance_prevents_the_packet` already covers. Labelling it
honestly is deliberate: this packet exists because a green test asserting
something other than its stated proposition shipped once already
(G1-ISO-02 §4.1).

Verified red-before by reverting `gate1.py` to `HEAD` with the new tests in
place: **2 failed, 1 passed** — exactly rows 1, 2 and 3.

## 5. What this does not change

The probe's forgeability is **unchanged**. This packet moves no boundary; it
corrects what the evidence says about the boundary that exists. Closing the
forgery needs the evaluator to observe the candidate from outside the
interpreter — containment — which remains deferred work named in
G1-ISO-01 §7b and G1-ISO-02 §5.

A full slice still cannot be won by that forgery: the composed `pytest_check`
imports `ignition_app` and the straggler scan reads the tree, so both go red.
The residue is a fabricated `gate1-behavior` item — which, after this packet,
at least describes itself accurately.

## 6. Rollback

Revert the single commit. No schema, artifact, ledger or promotion path changes
shape. The evaluator bundle digest moves because `gate1.py` moves, so the first
run after a revert is legitimately not a replay.
