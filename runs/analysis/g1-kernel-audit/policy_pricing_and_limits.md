# daedalus/kernel/policy/{pricing.py, limits.py, __init__.py}

215 + 283 + 129 lines. Base 54f09753. Static read-only.
Auditor: parent (W4 slice, subagent cap hit).

Covered together because the single material finding spans pricing and limits
(both make money/authority decisions from unauthenticated environment variables)
and `__init__.py` is a lazy facade with nothing of its own.

## `policy/pricing.py` (215 lines)

### What it is for

Converts a declared call into a conservative upper-bound USD estimate before
execution. `UNKNOWN_CALL_USD` deliberately exceeds the most expensive known
vendor so an unpriced call cannot be cheap by default.

### Axis 1 — docstring truth: checked and TRUE

- `:19` "**Unknown cannot mean free.** This deliberately exceeds the most
  expensive…" — verified: `_PRICES` (`:44-52`) tops out at `0.50` per-call for
  `openai_api`/`google_api`, and `UNKNOWN_CALL_USD` is set above that, with
  `remote_inference` mapped to it explicitly (`:51`). Fail-closed by
  construction.
- `:102` `price_call` — "Upper-bound call cost, returning zero **only for proven
  free transport**." The "only" is a universal, so I enumerated every `return`
  of `0.0`: `:118` and `:127` (loopback host, via `is_loopback_host`), `:138`
  (`vendor in FREE_VENDORS and host is None`, where `FREE_VENDORS` is the frozen
  `{"local", "local_inference"}` at `:54`), and `:145` (subscription vendors —
  see below). Three of the four are genuinely "proven free transport". The
  fourth is an owner *declaration*, not a proof — a small stretch in the word
  "proven", noted but not material.
- `:111` "this is pricing after the canonical egress classifier, **never a
  second host-trust authority**" — verified: `:113` imports
  `is_loopback_host`/`lane_for_host` from `daedalus.sensitivity` rather than
  re-deciding host trust locally. Correct deference; `tests/test_budget.py:1297`
  pins the converse (the classifier never consults `subscription_vendors()`).

### CONFIRMED — two environment variables move money decisions, with no in-tree setter

`subscription_vendors()` (`:57-64`) is built **entirely** from
`os.environ.get(ENV_SUBSCRIPTIONS)` where `ENV_SUBSCRIPTIONS =
"DAEDALUS_SUBSCRIPTION_VENDORS"` (`:17`). Its result is consumed at `:141`:

```python
if vendor in subscription_vendors() and not untrusted_endpoint:
    ... return Estimate(..., 0.0, ...)   # :145
```

So setting one environment variable prices a **paid** vendor (`openai_api`,
`deepseek`, `google_api`, …) at `$0.00`, which means no monetary reservation is
made against the period ceiling for those calls. Likewise `ENV_ON_UNKNOWN =
"DAEDALUS_BUDGET_ON_UNKNOWN"` (`:16`) selects between `worst_case` and `refuse`
via `_on_unknown_default()` (`:87-90`).

Two mitigations I checked before writing this up, both real:

1. The set is filtered to *known* vendors — `if name in _PRICES` (`:63`) — so an
   arbitrary string cannot be declared free.
2. `not untrusted_endpoint` (`:141`) keeps the discount off untrusted egress.

And the honesty check that matters most: **no code in this tree sets that
variable.** Scoped grep over `daedalus/`, `apps/`, `tools/` (copy directories
excluded) finds only the definition, the reader, re-exports through
`policy/__init__.py:38,89` and `daedalus/budget.py:61`, and tests. There is no
GUI or API path that flips it.

That materially changes the verdict. Plan §4.1 requires "every GUI/API
transition that widens authority" to carry an explicit confirmation verified by
the effectful backend — but this is not a GUI/API transition, it is a deployment
knob set by the operator outside the process. So I am **not** filing this as a
§4.1 violation. What it is: a documented owner-facing switch that zeroes a money
brake, is inherited by every child process, and has no confirmation or audit
record of its own. Worth knowing when reading a spend receipt; not a defect.

I record it mainly because the naive version of this finding ("env var bypasses
the spend cap!") is exactly the kind of inflated claim this audit is supposed to
avoid, and the grep for a setter is what deflates it.

### Axes 2/3/4/5

Effect surface: env reads at `:60`, `:88`. No writes, no subprocess, no network.
Resources: none. Validators: no `_identifier`, no path construction — vendor and
model strings are lowercased and compared against frozen tables, never
interpolated into a path. Dead code: none identified; `price_call` is the
module's purpose and `subscription_vendors`/`FREE_VENDORS` are both consumed at
`:138-141`.

## `policy/limits.py` (283 lines)

### What it is for

The `ExecutionLimitPolicy` contract from Plan §4.1 — which of the eight
canonical resource axes are enforced for newly admitted work, in `bounded`,
`custom`, or `unbounded_execution` mode.

### Axis 1 — docstring truth: checked and TRUE, including the hard part

- `:4-6` "It is deliberately separate from [trust boundaries]… **are not axes
  here and therefore cannot be disabled through this contract**." This is the
  claim that matters most in the whole file, because Plan §4.1's entire safety
  argument rests on execution caps and trust boundaries being different things.
  Verified structurally: `LIMIT_AXES` contains exactly the eight resource axes,
  and there is no member for the kill switch, egress, write roots, secrets,
  authentication, evaluator isolation, or promotion. A trust boundary is not
  representable in this contract, so it cannot be toggled by it. The claim is
  true *by the shape of the data model*, which is the strongest way to be true.
- `:8-12` "The stored representation retains the owner's per-axis choices in
  **every** mode… a disabled cap is represented by an explicit `False`
  enforcement flag, **never** [by Infinity/MAX_INT/zero/omission]." Matches
  Plan §4.1's explicit prohibition on `Infinity`/`MAX_INT`/zero/omitted fields.
  `LimitAxes` (`:79`) holds boolean flags per axis; `uniform` (`:96-99`) rejects
  a non-`bool` with `type(enforced) is not bool` — note that is a strict type
  identity check, so it correctly refuses `1`/`0`, which `isinstance` would have
  accepted since `bool` subclasses `int`. That is a deliberate, correct detail.
- `:243` `load_from_env` — "a missing or empty value is **bounded**." Verified
  at `:249-251`: `if raw is None or raw == "": return ExecutionLimitPolicy()`,
  the default-constructed (bounded) policy. **Fail-safe default confirmed** —
  absence of configuration does not disable caps.

### Axis 2 — effect surface

`:245` and `:262` touch `os.environ` (read and **write** respectively), but both
take an injectable `environ` parameter and only fall back to `os.environ` when
it is `None`. `store_in_env` (`:254-267`) writes
`DAEDALUS_EXECUTION_LIMIT_POLICY`. Unregistered, like every other env write in
the kernel — the `Effect` enum has no environment-mutation member at all
(`effect_boundary.py:43-51`).

The design point worth stating: **the execution-limit policy travels to child
processes through an environment variable.** `from_env_value` (`:~225-237`)
validates it as JSON and raises `LimitPolicyError` on anything malformed, so a
corrupt value fails closed rather than silently disabling axes. I checked that
specifically, because "malformed policy → treated as unbounded" would have been
a serious defect. It is not what happens.

### Axes 3/4/5

Resources: none. Validators: no `_identifier`, no path construction. Dead code:
not separately assessed.

## `policy/__init__.py` (129 lines)

Lazy re-export facade, same construction as `contracts/__init__.py` and
`events/__init__.py`. Docstring `:6-10` claims laziness so that "importing one
name [does not pull] the budget ledger and pricing tables into every process" —
verified: resolution happens only in the `__getattr__` at `:119`
("Resolve one reexport by loading only the owner that holds it"), with no
module-level owner imports.

No effects, no resources, no validators, nothing dead. Clean.

## What I did not cover

Axis 5 systematically for all three files, and the `ExecutionLimitPolicy`
serialization round-trip (`to_env_value`/`from_dict`) beyond its failure mode.
