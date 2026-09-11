# daedalus/kernel/runtime_authorization_issuer.py  (33 lines)

Base 54f09753. Static read-only.

## What the file is for

A lazy compatibility facade left behind after the runtime-admission owner
moved out of the kernel in work packet G1-RUNTIME-02. It re-exports exactly
five names (`RUNTIME_AUTHORITY_KEY_ID`, `RUNTIME_LEASE_KEY_ID`,
`acquire_runtime_bound_authorization`, `runtime_trust_ledger`,
`runtime_trust_ledger_path`) by lazily resolving attribute access to
`daedalus.runtimes.admission` via `module.__getattr__`, so old and new import
paths return the identical object rather than a second copy.

## Axis 1 — docstring truth

### CONFIRMED
None.

### PLAUSIBLE
None.

### Checked and honest
- `:3` "The runtime admission owner moved out of the kernel in G1-RUNTIME-02."
  — confirmed: `docs/work-packets/G1-RUNTIME-02_RUNTIME_TRUST_ADMISSION_PORT.md`
  and `docs/work-packets/G1-RUNTIME-02_SHIM_REGISTER.json` exist and the
  latter's `legacy_module` field (`:13`) names exactly
  `"daedalus.kernel.runtime_authorization_issuer"`.
- `:3-4` "Importing this legacy module alone does not load a runtime package.
  Attribute access resolves lazily to the canonical owner" — confirmed by the
  code shape: only `__getattr__` (`:26-29`) touches `import_module`; the
  module body itself (`:1-23`) performs no eager import of
  `daedalus.runtimes.admission`.
- `:5-6` "old and new imports receive the same objects rather than parallel
  wrapper functions or duplicated singleton state" — confirmed:
  `__getattr__` does `return getattr(import_module(_OWNER_MODULE), name)`
  (`:29`) — it returns the owner module's actual object by reference, not a
  copy or a wrapper function.
- `:7-8` "The registered shim and its retirement audit are recorded in the
  packet-local shim register." — confirmed as above; the shim register JSON
  literally lists this module.
- All five names in `__all__` (`:17-23`) exist in the target: verified
  `daedalus/runtimes/admission/__init__.py:4-16` imports and re-exports
  exactly `RUNTIME_AUTHORITY_KEY_ID`, `RUNTIME_LEASE_KEY_ID`,
  `acquire_runtime_bound_authorization`, `runtime_trust_ledger`,
  `runtime_trust_ledger_path` — the same five names, so `__getattr__` will
  resolve every one of them rather than raising `AttributeError` for a name
  that only *looks* re-exported.

## Axis 2 — effect surface

No direct effect sites. `import_module(_OWNER_MODULE)` (`:29`) is a Python
import, not a classed effect under the brief's taxonomy (subprocess, network,
filesystem write, env read); any real effects live inside
`daedalus.runtimes.admission`, outside this file and outside my slice.

## Axis 3 — unreleased resources

No findings. No resource acquisition of any kind in this file.

## Axis 4 — validator gaps (W4 class)

No findings. No path, filename, or identifier construction anywhere in this
33-line file.

## Axis 5 — dead / duplicate

No findings — the module has a promised reader and real readers.
- Docstring names its consumer class ("old and new imports"); the actual
  mechanism is `daedalus/kernel/__init__.py:174`, which lists
  `"runtime_authorization_issuer"` in `_LAZY_MODULES` (`:152-180`), making
  `daedalus.kernel.runtime_authorization_issuer` lazily resolvable as a kernel
  submodule attribute — that is the primary "reader" the docstring implies.
- Exact grep run: `grep -rln "runtime_authorization_issuer" --include=*.py
  daedalus/ tests/` found 4 files: `tests/kernel/test_runtime_trust_port_boundary.py`,
  `tests/kernel/test_runtime_authorization_issuer.py`,
  `tests/kernel/test_kernel_lazy_facade.py`, and
  `daedalus/kernel/__init__.py`. No production module outside `daedalus/kernel/__init__.py`
  imports this shim directly by its legacy dotted path in this revision — but
  that is exactly the intended state for a retained-for-compatibility shim
  whose canonical owner (`daedalus.runtimes.admission`) is what new code is
  expected to import instead; it is not an unwired producer with no consumer,
  it is a deliberately-thin compatibility layer with both a registered retreat
  plan (the shim register) and a live consumer (the kernel's own lazy-module
  loader).
- No duplicate implementation: this file contains no logic duplicated
  elsewhere — it is pure forwarding.

## OWNED-FLAG

Not applicable — this file is not `offload_lease.py`, the flagged
`attempt_execution.py` string-evidence sites, or `effects.py`.

## What I did not cover

Did not audit `daedalus/runtimes/admission/` (the canonical owner package)
itself — out of my assigned slice; I only confirmed its `__init__.py`
re-exports the same five names this shim declares. Did not read the three
test files that reference this module to see what behavior they actually
pin (static read of the shim file and its immediate dependents only).
