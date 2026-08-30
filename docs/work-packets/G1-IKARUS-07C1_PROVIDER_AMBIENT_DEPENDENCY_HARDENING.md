# G1-IKARUS-07C1 — Provider ambient-dependency hardening

Status: draft evidence packet  
Parent: `G1-IKARUS-07C` / PR #272  
Primary blocker: #188  
Hermes parity ledger: #247

## Problem

`ProviderExecutableObjectRegistry` previously proved the authenticated source file,
function target and loaded `__code__`, while rejecting closures and defaults. Python
function semantics also depend on `function.__globals__`. Rebinding a referenced
module global after registration could therefore change provider behavior without
changing the authenticated source bytes or the stored function code object.

That gap makes the 07B admission receipt insufficient as an execution credential.
The broker cutover must not proceed while such ambient substitution remains
possible.

## Bounded correction

This packet keeps the existing registry as the single evidence boundary and adds a
fail-closed ambient dependency proof during both registration and
`verify_registered(...)`:

- inspect `LOAD_GLOBAL` / `LOAD_NAME` dependencies across the complete nested code
  object tree without executing provider code;
- allow only the canonical Python builtins namespace or direct same-module helper
  functions;
- recursively re-prove each referenced helper against the same authenticated source
  path and bytes, exact target, default/closure restrictions and normalized bytecode;
- refuse mutable containers, module objects, imported callables, aliases, ambient
  constants and arbitrary objects until a signed dependency/loader contract exists;
- re-run the dependency proof at the 07C pre-effect binding so a helper rebound after
  registration refuses before lease grant or effect start.

No new provider registry, runtime authority, policy authority or loader is added.
The existing admission receipt schema stays unchanged because this packet does **not**
promote the receipt into execution authority.

## Evidence

Focused regressions cover:

1. same-module helper dependency admission without provider execution;
2. helper rebinding after registration refuses on `verify_registered(...)`;
3. referenced mutable module state such as `CALLS` refuses at registration;
4. module constants refuse until they are covered by a future signed dependency
   manifest;
5. the 07C boundary re-verifies ambient dependencies and refuses helper substitution
   before any effect state exists;
6. inherited source-review tests continue to forbid dynamic import, provider
   execution, effect start and a public callable resolver in the object registry.

## Deliberate limitation / next packet

This is still **not** a safe executable loader. The canonical builtins namespace is
process-global, and validation alone cannot remove the verify-to-execute race. The
next broker cutover must construct or consume a sealed execution namespace from
signed dependency evidence instead of directly trusting mutable module globals.
Until that exists, `provider_execution_allowed`, `effect_start_authorized`,
`callback_seam_removed` and `broker_invocation_performed` remain false.

This packet therefore advances #188 but does not close it and does not claim live
Hermes runtime parity, Gate transition, merge authorization or promotion.
