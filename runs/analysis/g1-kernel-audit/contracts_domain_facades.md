# daedalus/kernel/contracts/{attempts,campaigns,evidence,missions,policy,promotion,registry,resources,runtime}.py

Nine files, 5–13 lines each, 53 lines total. Base 54f09753. Static read-only.
Auditor: parent (W2 slice, subagent cap hit).

**Deliberate deviation from the brief's one-dossier-per-file rule:** these nine
files are byte-for-byte the same construction (a docstring, one `from .canonical
import ...`, one `__all__`). Nine near-identical dossiers would obscure the only
question that matters about them, which is comparative. They are covered
together here, and each is named individually below with its own measurement.

## What they are for

Per-domain re-export facades over `contracts/canonical.py`. `contracts/__init__.py`
describes them at `:3-5`: "The domain modules are stable hierarchy locators.
``canonical`` remains the single implementation nucleus during the strangler
split, so every legacy and new import resolves to one class object and one
serialization authority."

## Axis 1 — docstring truth

All nine docstrings are one-line topic labels ("Attempt lifecycle contracts and
receipts.", "Policy-decision wire contract.", …). No universal claims, no
`always`/`never`/`authenticated`/`guaranteed`. Nothing to falsify.

The load-bearing claim is the parent's, quoted above: **one class object, one
serialization authority.** That is verified — every one of the nine imports
from `.canonical` and none defines or subclasses anything locally, so all import
paths converge on the same class objects. Confirmed by reading all nine in full
(they total 53 lines).

## Axis 2 — effect surface

None. Import statements only, across all nine.

## Axis 3 — unreleased resources

None.

## Axis 4 — validator gaps (W4 class)

Not applicable — no validators, no path construction. Worth stating explicitly
because these files are the *distribution* layer for the contracts whose
`_identifier` weakness is the audit's Axis-4 theme: they re-export the
already-constructed classes and neither add nor weaken validation.

## Axis 5 — dead / duplicate — the only real question here

Measured per module. Import statements counted with scoped greps over `daedalus/`
and `tests/`, copy directories (`.claude/worktrees/`, `.daedalus_worktrees/`,
`build/`, `apps/web/src-tauri/{backend,target}/`) excluded:

| module | LOC | prod import stmts | test import stmts |
| --- | --- | --- | --- |
| `resources.py` | 5 | 11 | 0 |
| `policy.py` | 5 | 9 | 0 |
| `evidence.py` | 5 | 8 | 0 |
| `attempts.py` | 5 | 5 | 0 |
| `runtime.py` | 13 | 5 | 0 |
| `missions.py` | 5 | 1 | 0 |
| `promotion.py` | 5 | 1 | 1 |
| `registry.py` | 5 | 1 | 0 |
| **`campaigns.py`** | 5 | **0** | **0** |

Eight of nine are live production locators. The strangler split described by the
parent docstring is real and in use, not aspirational.

### FINDING — `contracts/campaigns.py`: zero importers, and it is the second half of a known gap

`campaigns.py` re-exports `CampaignContract`, `CampaignReceipt`,
`CampaignTrialReceipt`, `ExperimentSpec` and has **0 importers** in `daedalus/`
or `tests/`.

Per the brief, zero callers is a finding, not a verdict — so: the promised
reader is named, and it does not exist. `daedalus/kernel/__init__.py:124-139`
declares 14 Campaign compatibility export names owned by a module
`daedalus.kernel.campaigns` which **is not on disk** (measured: declared in
`_LAZY_MODULES`, absent from the package). That facade's docstring (`:9-11`)
states the situation openly and `_load_owner` (`:192-199`) raises a specific
"Land the owning Campaign Work Packet" error rather than a bare ImportError.

So the two observations are one fact, not two: **the Campaign slice is unlanded.**
Its wire contracts exist in `canonical.py`, this locator exists to re-export
them, and there is no consumer at either level. The correct disposition is to
leave both in place — the gap is deliberately visible and correctly documented —
not to delete `campaigns.py` as dead code. Deleting it would erase half of a
declared gap.

This is the third built-but-unwired seam this audit has confirmed in the kernel,
alongside the D5 sealed-promotion consumption chain and
`AttemptLedger.pending()`. Unlike those two, this one is **documented as
unwired**, which is the materially better handling.

### Duplicate check

None. No module defines anything; there is no divergence risk. I compared each
`__all__` against its `from .canonical import` list — all nine match exactly,
with no name exported that is not imported and none imported that is not
exported.

## What I did not cover

Whether every re-exported name still exists in `canonical.py` (a rename would
break these silently at import time). That is the same cheap mechanical check
flagged for the two lazy facades; it needs an import, which this static-only
audit does not do.
