"""A default HARD CEILING on money. Ledger-backed, cross-process, fail-closed.

WHY THIS EXISTS
---------------
This repo spends real money on vendor APIs and, until this module, had no cost
ceiling of any kind. A single A/B feature build measured $1.43-$1.85 per arm;
``daedalus canary`` defaults to 4 lanes x 4 probes = 16 billable calls. Behind a
human typing one command that is fine. Behind the unattended loop this repo is
being built toward it is the failure that ends the project: a loop with no cap
bills until the card declines.

THERE IS NO SINGLE CHOKEPOINT IN THIS REPO. Vendor spend leaves from at least
four independent subsystems (``providers/``, ``council/vendors.py``,
``ikarus_os.py``, ``runs/``), each spawning the vendor itself. So this module
offers enforcement at two levels:

1. **Explicit** -- :func:`reserve` / :func:`guard` at a call site. Precise: the
   site knows the vendor, the model, and how many calls it is about to make.
2. **Interposed** -- :func:`install_process_guard` monkeypatches
   ``subprocess.run``/``Popen`` and ``urllib.request.urlopen`` for the whole
   process. Coarse (it must guess the price) but it MANUFACTURES the chokepoint
   the architecture lacks, and it covers the sites this module cannot edit.

Level 2 is the net under level 1. An unattended entrypoint should install it
once at startup; every site that also does level 1 is charged exactly once
(the interposer stands down inside an explicit reservation).

THE FIVE INVARIANTS
-------------------
* **FAIL CLOSED.** If the budget state cannot be read -- corrupt ledger,
  unparseable ceiling, a lock we could not take -- the answer is
  :class:`BudgetUnavailable`, never "allow". Absence of configuration is not
  absence of a cap: an unconfigured process gets :data:`DEFAULT_CEILING_USD`,
  not infinity. Only the canonical owner execution-limit policy can disable a
  resource axis; the ledger and attribution remain active in every mode.
* **THE CHECK HAPPENS BEFORE THE CALL.** :meth:`Ledger.reserve` PERSISTS the
  reservation to disk before it returns, so the money is committed before a
  single vendor byte moves. A cap that inspects what was already spent is not a
  cap; it is a receipt.
* **REFUSAL IS LOUD AND NAMED.** :class:`BudgetRefused` carries the ceiling, the
  spend, the estimate, and what was refused, and says all four in ``str()``.
* **CONCURRENCY.** Sixteen agents run here at once. Reserve/settle happen under
  a cross-process advisory lock built on the same primitives as
  ``runs/council/room.py::_RoomLock`` (``msvcrt`` on Windows, ``fcntl`` on
  POSIX) -- with ONE deliberate inversion, see :class:`_BudgetLock`.
* **AN UNKNOWN PRICE IS NOT A FREE PRICE.** An unpriced vendor, an unpriced
  model, or an inference host we cannot place is charged
  :data:`UNKNOWN_CALL_USD` -- deliberately above the most expensive call this
  repo has ever measured -- or refused outright under
  ``DAEDALUS_BUDGET_ON_UNKNOWN=refuse``. Never zero.
"""

from __future__ import annotations

from typing import Callable

from .kernel.policy.pricing import (
    BudgetError,
    ENV_MAX_CALLS,
    ENV_ON_UNKNOWN,
    ENV_SUBSCRIPTIONS,
    Estimate,
    FREE_VENDORS,
    UNKNOWN_CALL_USD,
    UnknownPrice,
    VendorPrice,
    _PRICES,
    price_call,
    subscription_vendors,
)

from .kernel.policy.ledger import (
    DEFAULT_CEILING_USD,
    DEFAULT_ENVELOPE_TTL_S,
    DEFAULT_LEDGER_PATH,
    DEFAULT_MAX_CALLS,
    DEFAULT_PERIOD,
    ENV_CEILING,
    ENV_ENVELOPE,
    ENV_EXECUTION_LIMIT_POLICY,
    ENV_LEDGER,
    ENV_PERIOD,
    ENV_PERIOD_CEILING_ENABLED,
    LOCK_TIMEOUT_S,
    MAX_ENTRIES,
    PERIODS,
    ROOT,
    BudgetRefused,
    BudgetState,
    BudgetUnavailable,
    Ledger,
    Reservation,
    SpendEnvelope,
    _BudgetLock,
    ledger,
    open_envelope,
    reserve,
    reset_default_ledger,
)

__all__ = [
    "BudgetError", "BudgetRefused", "BudgetUnavailable", "UnknownPrice",
    "Estimate", "BudgetState", "Reservation", "Ledger",
    "SpendEnvelope", "open_envelope", "ENV_ENVELOPE",
    "ENV_PERIOD_CEILING_ENABLED",
    "ENV_EXECUTION_LIMIT_POLICY",
    "price_call", "reserve", "guard", "ledger", "reset_default_ledger",
    "classify_argv", "classify_url",
    "install_process_guard", "uninstall_process_guard",
    "BILLABLE_SITES",
]


# --------------------------------------------------------------------------
# process-aware reservation guard
# --------------------------------------------------------------------------

from .runtimes.execution.budget_process import (
    BILLABLE_SITES,
    _EXPLICIT,
    _INFERENCE_PATHS,
    _INSTALLED,
    _PAID_API_HOSTS,
    _PAID_EXECUTABLES,
    _READ_ONLY_VENDOR_PROBES,
    _WRAPPERS,
    _basename,
    _enter_explicit,
    _exit_explicit,
    _guarded_popen,
    _guarded_spawn,
    _guarded_urlopen,
    _inside_explicit,
    _is_read_only_vendor_probe,
    _render,
    classify_argv,
    classify_url,
    guard,
    uninstall_process_guard,
)
from .runtimes.execution.budget_process import (
    install_process_guard as _install_runtime_process_guard,
)


def install_process_guard() -> Callable[[], None]:
    """Install the runtime spend net through the current facade ports.

    Passing the current bindings preserves the legacy tests and integrations
    that replace daedalus.budget.classify_argv, classify_url, or reserve before
    installing the net.
    """

    return _install_runtime_process_guard(
        argv_classifier=classify_argv,
        url_classifier=classify_url,
        reserve_call=reserve,
    )


def process_guard_boundary_decision():
    """Run the ``budget.process_guard`` contract and report its decision.

    This is the contract module's own evidence for a canonical effect start:
    it actually installs the process-wide spend net (idempotent) and returns
    the :class:`~daedalus.spine.effect_boundary.GuardDecision` naming what is
    now interposed.  It never broadens the decision: a caller that skips this
    and asserts the contract by hand is visible in the receipt evidence.
    """
    from daedalus.spine.effect_boundary import GuardDecision

    install_process_guard()
    return GuardDecision(
        "budget.process_guard",
        True,
        "install_process_guard active: subprocess.run/subprocess.Popen/"
        "urllib.request.urlopen priced against the budget ceiling in-process",
    )
