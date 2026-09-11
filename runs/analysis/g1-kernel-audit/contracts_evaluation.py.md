# daedalus/kernel/contracts/evaluation.py  (39 lines)

Base 54f09753. Static read-only.

## What the file is for

Defines two `Protocol`s (`EvaluationBaselinePort`, `EvaluationGatePort`) and
one frozen dataclass (`EvaluationPorts`) that name the read/evaluate
capability a picker invocation may be given, without importing a concrete
evaluator. This is a real implementation module, not a re-export facade —
these three names do not exist anywhere in `canonical.py`.

## Axis 1 — docstring truth

Grep for the target words over module/class/function docstrings: 0 hits.
No claims to check. (The module docstring explicitly disclaims doing the
work itself: "The kernel names the capability but does not import an
evaluator implementation." — consistent with the file containing only
`Protocol` declarations and one dataclass, no evaluator logic.)

## Axis 2 — effect surface

| site (file:line) | effect | registry row | covered? |
| --- | --- | --- | --- |
| none | — | — | — |

`Protocol.__call__` signatures declare a return type (`Mapping[str, Any]`)
but carry no implementation (`...` body) — no effect surface in this file
itself; whatever concrete callable is later bound to `load_baseline`/
`run_gate` is out of this file's scope entirely.

## Axis 3 — unreleased resources

None.

## Axis 4 — validator gaps (W4 class)

Not applicable — no identifiers, no paths, no validators.

## Axis 5 — dead / duplicate

- **Not dead.** `grep -rln "kernel.contracts.evaluation import"` → 3
  real importers:
  - `daedalus/orchestration/execution/evaluation.py:9` — imports
    `EvaluationPorts` and constructs one at `:27`
    (`EvaluationPorts(load_baseline=_load_baseline, run_gate=_run_gate)`),
    consumed by `picker_evaluation_ports()`.
  - `daedalus/spine/picker.py:76` — imports `EvaluationPorts`, used as a
    type annotation at five sites (`:1663, 1672, 2267, 2989`) and referenced
    in a docstring at `:1639, 1659`.
  - `tests/kernel/test_evaluation_port_boundary.py:10` — exercises the
    boundary directly.
- **Not a duplicate.** `grep -rln "class EvaluationBaselinePort\|class EvaluationGatePort\|class EvaluationPorts" daedalus` →
  exactly one definition site (`daedalus/kernel/contracts/evaluation.py`
  itself). No second protocol or dataclass with the same name exists
  anywhere in the tree.

## OWNED-FLAG

Not applicable.

## What I did not cover

- Did not read `daedalus/orchestration/execution/evaluation.py` or
  `daedalus/spine/picker.py` beyond the grep context shown above — full
  behavioral review of how `load_baseline`/`run_gate` get bound at runtime
  is outside this file's scope and outside my slice.
