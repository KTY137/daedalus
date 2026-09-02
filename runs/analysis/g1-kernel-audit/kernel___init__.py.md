# daedalus/kernel/__init__.py  (224 lines)

Base 54f09753. Static read-only. Auditor: parent (W3 slice, subagent cap hit).

## What the file is for

A lazy compatibility facade for the kernel package. It maps ~70 historical
export names to their owning module and resolves them on first attribute access
via `__getattr__`, so importing one kernel name does not eagerly pull in the
whole package (notably not the SQLite machinery).

## Axis 1 — docstring truth

### Checked and TRUE — the Campaign gap is handled honestly

`:9-11`:

> "The frozen Gate-1 WIP references a Campaign slice that is not present. Its
> compatibility names remain declared so the gap is visible, but requesting one
> fails specifically instead of preventing every unrelated kernel import."

Verified on both halves:

- **The slice really is absent.** `daedalus/kernel/campaigns.py` does not exist
  (enumerated: the package has 27 top-level `.py` files plus `contracts/`,
  `events/`, `policy/`; `campaigns` is not among them).
- **The failure really is specific.** `_load_owner` (`:184-200`) reinterprets
  `ModuleNotFoundError` **only** when `owner == "campaigns" and exc.name ==
  _CAMPAIGN_MODULE` (`:192`), and the inline comment at `:189-191` states the
  reason: "If a future real campaigns.py has a missing dependency, preserve that
  dependency's original name/traceback instead of disguising it as today's WIP
  gap." That is a precise guard against a very easy mistake — swallowing a real
  import error under a cosmetic one — and the message it raises (`:194-197`)
  names the work packet rather than pretending the names exist.

This is a **model instance of the honest pattern** the audit is calibrated
against: a gap declared in the docstring, made specific in the code, and left
visible in `__dir__` rather than hidden. It is the counter-example to the
kill-switch overclaim that motivated this sweep, and worth citing as such.

### CONFIRMED — the "ordinary package-module attributes" enumeration is incomplete

`:149-151`:

> "Preserve ordinary package-module attributes without importing them. Several
> appeared incidentally through the old eager graph; **all remain directly
> importable** and resolve to Python's single canonical module object."

Measured mechanically (AST-parsed `_LAZY_MODULES`, compared against the
directory listing, script run under `.venv/Scripts/python.exe`):

```
declared in _LAZY_MODULES : 27
actual kernel modules     : 29
DECLARED BUT MISSING FROM DISK : ['campaigns']
ON DISK BUT NOT DECLARED       : ['attempt_execution', 'events', 'policy']
```

`campaigns` being declared-but-absent is the documented, intentional case above.
The three undeclared entries are not documented anywhere:

- `attempt_execution` — 2724 lines, the largest attempt module.
- `events` — the subpackage owning `SpineLedger`, the canonical event store.
- `policy` — the subpackage owning the execution-limit policy and ledger.

Consequences, both minor but real:

1. `__dir__` (`:219-221`) has the docstring "Advertise the compatibility
   surface, including the honest Campaign gap." It returns
   `globals() | __all__ | _LAZY_MODULES` (`:221`), so it under-advertises: three
   real submodules of the kernel are invisible to `dir(daedalus.kernel)` and to
   any tool that enumerates the surface that way.
2. After a bare `import daedalus.kernel`, `daedalus.kernel.events` raises
   `AttributeError` from `__getattr__:216` rather than lazily importing, because
   `events` is in neither `_EXPORTS` nor `_LAZY_MODULES`. (`from daedalus.kernel
   import events` still works — Python falls back to submodule import — so this
   is a facade-completeness gap, not a breakage.)

The pattern is that the facade's enumeration was written once and the three
newest additions to the kernel were never added to it. Low severity; I am
reporting it because the claim is universal ("all remain directly importable")
and the audit's standing rule is that universals get enumerated rather than
read.

Note the contrast with the sibling facade: `contracts/__init__.py`'s `_MODULES`
set is **complete** — same measurement, `declared 14 / actual 14`, with empty
difference sets both ways. So the correct pattern exists one directory down.

## Axis 2 — effect surface

None. The module's only operation is `importlib.import_module` (`:14`, `:187`).
No filesystem, subprocess, network, or `os.environ` access. Correctly absent
from the Effect Registry.

Worth noting positively: the laziness has a real trust benefit the docstring
does not claim — importing a kernel contract name does not open the canonical
SQLite event store, so a read-only inspector cannot accidentally create
`-wal`/`-shm` companions merely by importing. That interacts directly with the
`events/ledger.py:322-327` "HONEST LIMIT" note.

## Axis 3 — unreleased resources

None. No resources acquired.

## Axis 4 — validator gaps (W4 class)

Not applicable — no identifiers, no path construction. `_load_owner` builds a
module name by f-string (`:185`) from `owner`, but `owner` comes only from the
module's own frozen `_EXPORT_GROUPS`/`_LAZY_MODULES` literals, never from caller
input. `__getattr__` looks `name` up in those dicts and raises `AttributeError`
on a miss (`:216`) rather than interpolating it. Correct.

## Axis 5 — dead / duplicate

- The 14 `campaigns` export names (`:124-139`) are declared but unresolvable.
  This is the documented visible gap, not dead code — and per the brief this is
  the *good* form of a seam: the promised reader is named (the Campaign Work
  Packet) and the absence is loud.
- `contracts/campaigns.py` exists and re-exports `CampaignContract`,
  `CampaignReceipt`, `CampaignTrialReceipt`, `ExperimentSpec` from `canonical`.
  Measured: **0 importers** anywhere in `daedalus/` or `tests/`. So the Campaign
  *contracts* are defined and reachable while the Campaign *module* is absent
  and nothing consumes either. Consistent with an unlanded slice; recorded so
  the two halves are not mistaken for independent findings.
- `del _owner, _names, _name` at `:224` correctly cleans the loop variables from
  the module namespace. Note it would `NameError` if `_EXPORT_GROUPS` were ever
  emptied — a latent fragility, not a current defect.

## What I did not cover

Whether every one of the ~70 declared export names actually resolves (i.e.
whether each owner module really defines its listed attribute). That is a cheap
mechanical check worth running — it would catch a rename that silently broke a
compatibility name — but it requires importing each owner, which risks side
effects, and this audit is static-only.
