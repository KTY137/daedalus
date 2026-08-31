"""Canonical money-budget ledger, reservation, and spend-envelope authority.

This module owns persistent budget state and its cross-process lock.  The
legacy :mod:`daedalus.budget` module is a compatibility/effect facade and
reexports these exact objects.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from math import isfinite
from pathlib import Path
from typing import Any, Iterator

from .limits import (
    ENV_EXECUTION_LIMIT_POLICY,
    ExecutionLimitPolicy,
    LimitAxes,
    LimitPolicyError,
    MODE_CUSTOM,
    load_from_env as load_limit_policy_from_env,
)
from .pricing import BudgetError, ENV_MAX_CALLS, Estimate, price_call

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LEDGER_PATH = ROOT / "runs" / "budget" / "ledger.json"

ENV_LEDGER = "DAEDALUS_BUDGET_LEDGER"
ENV_CEILING = "DAEDALUS_BUDGET_USD"
ENV_PERIOD_CEILING_ENABLED = "DAEDALUS_BUDGET_PERIOD_CEILING_ENABLED"
ENV_PERIOD = "DAEDALUS_BUDGET_PERIOD"
# Which SPEND ENVELOPES this process (and every child that inherits its
# environment) is spending inside. Comma-separated envelope ids, written by
# :meth:`SpendEnvelope.__enter__`, never by a human. See "spend envelopes"
# below for why a second, tighter ceiling exists at all.
ENV_ENVELOPE = "DAEDALUS_BUDGET_ENVELOPE"

# The default cap. Chosen so that an operator who has configured NOTHING still
# has a cap, and so that the cap is crossed loudly on the third A/B arm rather
# than silently on the three-hundredth. Raise it explicitly with
# DAEDALUS_BUDGET_USD -- that is the point: spending above this is a decision
# someone made, not a default someone inherited.
DEFAULT_CEILING_USD = 5.00
# A second axis, because price is the thing we are least sure of and call count
# is the thing we are most sure of. The canary's default fan-out is 16.
DEFAULT_MAX_CALLS = 40
# What one call of unknown price costs. MUST exceed the most expensive single
# call ever measured here ($1.85, one A/B arm) by a wide margin: under-pricing
# the unknown is exactly the arithmetic that lets a runaway loop through.
# Ledger periods. "day" is the default because an unattended loop runs for days
# and a lifetime cap would either be crossed in week one and disabled, or set so
# high it caps nothing.
PERIODS = ("day", "total")
DEFAULT_PERIOD = "day"

LOCK_TIMEOUT_S = 30.0
MAX_ENTRIES = 500

#: How long an unclosed envelope keeps holding money. A crashed wave must not
#: hold the day's whole ceiling forever, and a hold with no lifetime is exactly
#: what an abandoned process leaves behind. EXPIRY RELEASES ONLY THE UNUSED
#: HOLD -- spend already recorded inside the envelope stays recorded, and a
#: draw attributed to an expired envelope is REFUSED, not waved through.
DEFAULT_ENVELOPE_TTL_S = 6 * 3600.0

__all__ = [
    "BudgetRefused",
    "BudgetState",
    "BudgetUnavailable",
    "DEFAULT_CEILING_USD",
    "DEFAULT_ENVELOPE_TTL_S",
    "DEFAULT_LEDGER_PATH",
    "DEFAULT_MAX_CALLS",
    "ENV_CEILING",
    "ENV_ENVELOPE",
    "ENV_EXECUTION_LIMIT_POLICY",
    "ENV_LEDGER",
    "ENV_PERIOD",
    "ENV_PERIOD_CEILING_ENABLED",
    "Ledger",
    "Reservation",
    "SpendEnvelope",
    "ledger",
    "open_envelope",
    "reserve",
    "reset_default_ledger",
]

# --------------------------------------------------------------------------
# errors
# --------------------------------------------------------------------------

class BudgetUnavailable(BudgetError):
    """The budget state could not be established. This is a REFUSAL.

    Not knowing what has been spent is indistinguishable, from the card's point
    of view, from having spent everything.
    """


class BudgetRefused(BudgetError):
    """The ceiling would be crossed. Carries every number a human needs."""

    def __init__(self, *, label: str, vendor: str, model: str, estimate_usd: float,
                 spent_usd: float, reserved_usd: float, ceiling_usd: float,
                 calls: int, open_calls: int, want_calls: int, max_calls: int,
                 reason: str, envelope: dict[str, Any] | None = None,
                 period_ceiling_enabled: bool = True,
                 billable_call_ceiling_enabled: bool = True,
                 mission_spend_ceiling_enabled: bool = True) -> None:
        # WHICH CEILING REFUSED. Defaulted to None so every existing raise site
        # is unchanged; set when the refusal came from a SPEND ENVELOPE (a
        # lease's own ceiling) rather than from the period ceiling, so a
        # receipt can name the lease that stopped the money instead of
        # reporting the day's cap for a wave that never came near it.
        self.envelope = dict(envelope) if envelope else None
        self.period_ceiling_enabled = period_ceiling_enabled
        self.billable_call_ceiling_enabled = billable_call_ceiling_enabled
        self.mission_spend_ceiling_enabled = mission_spend_ceiling_enabled
        self.label = label
        self.vendor = vendor
        self.model = model
        self.estimate_usd = estimate_usd
        self.spent_usd = spent_usd
        self.reserved_usd = reserved_usd
        self.ceiling_usd = ceiling_usd
        self.calls = calls
        self.open_calls = open_calls
        self.want_calls = want_calls
        self.max_calls = max_calls
        self.reason = reason
        super().__init__(self.message())

    def message(self) -> str:
        period_ceiling = (
            f"${self.ceiling_usd:.4f}"
            if self.period_ceiling_enabled
            else f"uncapped (configured fallback=${self.ceiling_usd:.4f})"
        )
        if self.envelope is not None:
            env = self.envelope
            mission_enforced = bool(env.get("mission_spend_enforced", True))
            envelope_limit = (
                f"cap=${float(env.get('cap_usd') or 0.0):.4f}, "
                f"drawn=${float(env.get('drawn_usd') or 0.0):.4f}, "
                f"remaining=${float(env.get('remaining_usd') or 0.0):.4f}"
                if mission_enforced
                else (
                    "effective cap=unbounded (configured fallback="
                    f"${float(env.get('cap_usd') or 0.0):.4f}), "
                    f"drawn=${float(env.get('drawn_usd') or 0.0):.4f}, "
                    "remaining=unbounded"
                )
            )
            envelope_explanation = (
                "This is the LEASED ceiling; the period USD ceiling is "
                f"{period_ceiling}: the wave was authorised for exactly this "
                "much money and has now asked for more."
                if mission_enforced
                else (
                    "The Mission monetary cap is disabled for this captured "
                    f"contract; this refusal is instead: {self.reason}."
                )
            )
            return (
                f"BUDGET REFUSED: {self.reason}. "
                f"refused='{self.label}' (vendor={self.vendor or '?'}, "
                f"model={self.model or '?'}, {self.want_calls} call(s), "
                f"estimate=${self.estimate_usd:.4f}). "
                f"envelope={env.get('label') or env.get('id')!r} "
                f"lease={env.get('lease_id') or '<none>'} "
                f"{envelope_limit}. {envelope_explanation}"
            )
        remaining = (
            f"${self.ceiling_usd - self.spent_usd - self.reserved_usd:.4f}"
            if self.period_ceiling_enabled
            else "uncapped"
        )
        operator_hint = (
            f"Raise {ENV_CEILING}/{ENV_MAX_CALLS} deliberately, or wait for the "
            "period to roll over."
            if self.period_ceiling_enabled
            else f"The period USD ceiling is explicitly uncapped; raise "
            f"{ENV_MAX_CALLS} deliberately or wait for the period to roll over."
        )
        return (
            f"BUDGET REFUSED: {self.reason}. "
            f"refused='{self.label}' (vendor={self.vendor or '?'}, "
            f"model={self.model or '?'}, {self.want_calls} call(s), "
            f"estimate=${self.estimate_usd:.4f}). "
            f"period_ceiling={period_ceiling}, spent=${self.spent_usd:.4f}, "
            f"reserved=${self.reserved_usd:.4f}, "
            f"remaining={remaining}, "
            f"calls={self.calls}+{self.open_calls} of {self.max_calls}. "
            f"{operator_hint}"
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "refused": self.label, "vendor": self.vendor, "model": self.model,
            "estimate_usd": self.estimate_usd, "spent_usd": self.spent_usd,
            "reserved_usd": self.reserved_usd, "ceiling_usd": self.ceiling_usd,
            "period_ceiling_enabled": self.period_ceiling_enabled,
            "billable_call_ceiling_enabled": (
                self.billable_call_ceiling_enabled
            ),
            "mission_spend_ceiling_enabled": (
                self.mission_spend_ceiling_enabled
            ),
            "period_ceiling_usd": self.ceiling_usd,
            "effective_period_ceiling_usd": (
                self.ceiling_usd if self.period_ceiling_enabled else None
            ),
            "remaining_period_usd": (
                self.ceiling_usd - self.spent_usd - self.reserved_usd
                if self.period_ceiling_enabled else None
            ),
            "calls": self.calls, "open_calls": self.open_calls,
            "want_calls": self.want_calls, "max_calls": self.max_calls,
            "effective_max_calls": (
                self.max_calls if self.billable_call_ceiling_enabled else None
            ),
            "remaining_calls": (
                self.max_calls - self.calls - self.open_calls
                if self.billable_call_ceiling_enabled else None
            ),
            "reason": self.reason, "envelope": self.envelope,
        }


# --------------------------------------------------------------------------
# cross-process lock
# --------------------------------------------------------------------------

class _BudgetLock:
    """Cross-process exclusive lock, same primitives as
    ``runs/council/room.py::_RoomLock`` -- ``msvcrt`` on Windows, ``fcntl`` on
    POSIX -- with ONE DELIBERATE INVERSION.

    ``_RoomLock`` degrades to a NO-OP when the lock cannot be taken, on the
    reasoning that "losing serialisation is bad, losing the human's message is
    worse". For money that reasoning runs backwards. Two processes that both
    read "remaining: $0.50" and both spend it have spent $1.00 against a $0.50
    ceiling, and no downstream verifier reports that by position or otherwise.
    So an unobtainable lock here RAISES :class:`BudgetUnavailable`, which the
    caller must treat as a refusal.

    The lock file is separate from the ledger file: the ledger is replaced
    atomically under the lock, and on Windows you cannot replace a file another
    handle holds open.
    """

    def __init__(self, path: Path, timeout_s: float = LOCK_TIMEOUT_S) -> None:
        self.path = Path(path)
        self.timeout_s = timeout_s
        self._fh: Any = None

    def __enter__(self) -> "_BudgetLock":
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "a+b")
        except OSError as exc:
            self._fh = None
            raise BudgetUnavailable(
                f"cannot open budget lock '{self.path}': {exc}; refusing to "
                "spend without serialisation") from exc

        deadline = time.monotonic() + self.timeout_s
        last: Exception | None = None
        while True:
            try:
                self._acquire()
                return self
            except OSError as exc:
                last = exc
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)

        try:
            self._fh.close()
        except OSError:
            pass
        self._fh = None
        raise BudgetUnavailable(
            f"could not take the budget lock '{self.path}' within "
            f"{self.timeout_s:g}s ({last}); another agent holds it. Refusing "
            "rather than spending unserialised.")

    def _acquire(self) -> None:
        self._fh.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def __exit__(self, *exc: Any) -> bool:
        if self._fh is None:
            return False
        try:
            self._fh.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        try:
            self._fh.close()
        except OSError:
            pass
        self._fh = None
        return False


# --------------------------------------------------------------------------
# ledger
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class BudgetState:
    ceiling_usd: float
    max_calls: int
    spent_usd: float
    reserved_usd: float
    calls: int
    open_calls: int
    period: str
    period_key: str
    #: The part of ``reserved_usd`` that is UNUSED envelope hold -- money
    #: pre-authorised to a lease that has not been drawn yet. Defaulted so
    #: every existing construction of this dataclass is unchanged.
    envelope_hold_usd: float = 0.0
    #: One row per OPEN envelope: id, label, lease_id, cap, drawn, remaining,
    #: expired. Published so a receipt can report the leased ceiling beside
    #: the realized spend without re-reading the ledger file.
    envelopes: tuple[dict[str, Any], ...] = ()
    #: False is the explicit owner-selected no-global-period-USD-cap mode. The
    #: configured positive ceiling is retained for a later switch back.
    period_ceiling_enabled: bool = True
    #: The configured positive call fallback is retained while this axis is
    #: disabled. Calls are still counted in the ledger in every mode.
    billable_call_ceiling_enabled: bool = True
    #: Whether newly issued SpendEnvelopes enforce their monetary fallback.
    #: Each envelope captures this bit at issuance so later policy changes do
    #: not rewrite an active Mission/lease contract.
    mission_spend_ceiling_enabled: bool = True
    #: Canonical policy evidence captured for this state read.
    limit_policy_mode: str = "bounded"
    configured_limit_axes: dict[str, bool] | None = None
    effective_limit_axes: dict[str, bool] | None = None
    limit_policy_fingerprint_sha256: str = ""

    @property
    def committed_usd(self) -> float:
        return self.spent_usd + self.reserved_usd

    @property
    def effective_period_ceiling_usd(self) -> float | None:
        return self.ceiling_usd if self.period_ceiling_enabled else None

    @property
    def remaining_usd(self) -> float | None:
        if not self.period_ceiling_enabled:
            return None
        return self.ceiling_usd - self.committed_usd

    @property
    def effective_max_calls(self) -> int | None:
        return self.max_calls if self.billable_call_ceiling_enabled else None

    @property
    def remaining_calls(self) -> int | None:
        if not self.billable_call_ceiling_enabled:
            return None
        return self.max_calls - self.calls - self.open_calls

    def as_dict(self) -> dict[str, Any]:
        return {"ceiling_usd": self.ceiling_usd,
                "period_ceiling_enabled": self.period_ceiling_enabled,
                "period_ceiling_usd": self.ceiling_usd,
                "effective_period_ceiling_usd": self.effective_period_ceiling_usd,
                "max_calls": self.max_calls,
                "billable_call_ceiling_enabled": self.billable_call_ceiling_enabled,
                "effective_max_calls": self.effective_max_calls,
                "remaining_calls": self.remaining_calls,
                "remaining_billable_calls": self.remaining_calls,
                "mission_spend_ceiling_enabled": self.mission_spend_ceiling_enabled,
                "spent_usd": self.spent_usd, "reserved_usd": self.reserved_usd,
                "committed_usd": self.committed_usd,
                "remaining_usd": self.remaining_usd,
                "remaining_period_usd": self.remaining_usd,
                "calls": self.calls,
                "open_calls": self.open_calls, "period": self.period,
                "period_key": self.period_key,
                "envelope_hold_usd": self.envelope_hold_usd,
                "envelopes": [dict(e) for e in self.envelopes],
                "caps": {
                    "mode": self.limit_policy_mode,
                    "configured": dict(self.configured_limit_axes or {}),
                },
                "effective_caps": dict(self.effective_limit_axes or {}),
                "limit_policy_fingerprint_sha256": (
                    self.limit_policy_fingerprint_sha256
                )}


@dataclass
class Reservation:
    """Money already committed to the ledger for a call that has NOT happened
    yet. Holding one of these is what makes the call legal."""

    id: str
    estimate: Estimate
    label: str
    ledger: "Ledger"
    _closed: bool = False

    @property
    def usd(self) -> float:
        return self.estimate.usd

    def settle(self, actual_usd: float | None = None) -> None:
        """Close the reservation, charging ``actual_usd`` -- or, if that is
        None, the ESTIMATE. An unknown actual is not a free actual."""
        if self._closed:
            return
        self.ledger._close(self, actual_usd, released=False, reason="")
        self._closed = True

    def release(self, reason: str) -> None:
        """Close the reservation charging NOTHING.

        ONLY legal when you can prove no vendor bytes moved -- e.g. the argv was
        rejected before spawn. This is the one fail-OPEN lever in the module;
        it demands a reason so its use is auditable in the ledger entries.
        """
        if self._closed:
            return
        if not (reason or "").strip():
            raise ValueError("release() requires a reason naming why no call happened")
        self.ledger._close(self, 0.0, released=True, reason=reason)
        self._closed = True


@dataclass
class SpendEnvelope:
    """A SECOND, TIGHTER CEILING for the duration of one leased scope.

    WHY THIS EXISTS. An Effect Lease declares ``max_cost_microusd``, and until
    this class nothing on any path turned that number into money enforcement:
    ``daedalus/kernel/effects.py`` only compared the execution's declaration
    against the lease's declaration (a narrowing check between two *claims*),
    so the only real ceiling a wave ever ran under was the period ceiling in
    this module -- the day's ``DAEDALUS_BUDGET_USD``, which is unrelated to the
    ``--max-spend-usd`` the operator typed. A wave leased for $0.25 could spend
    $4.99 without one refusal, because nobody was subtracting.

    An envelope is a PRE-AUTHORISATION, not an extra pot of money:

    * opening one commits its whole ``cap_usd`` to the ledger as hold, so the
      period ceiling accounts for the lease the moment it is granted (and an
      envelope that does not fit under the period ceiling cannot be opened);
    * every reservation attributed to it draws the hold down instead of adding
      to it -- spend inside the envelope does not double-count;
    * a draw that would cross ``cap_usd`` is refused with the lease named, even
      when the period ceiling has room;
    * closing it releases whatever hold was never drawn and reports the
      REALIZED spend, which is what belongs in the wave receipt beside the
      ceiling it was granted.

    ATTRIBUTION -- and its exact boundary. A reservation is charged to this
    envelope when the reserving process is the one that opened it (same pid) or
    when the envelope's id is in ``DAEDALUS_BUDGET_ENVELOPE``, which
    :meth:`__enter__` sets so child processes inherit it. That covers the two
    shapes this repository actually spends in: an in-process interposed
    reservation (``install_process_guard`` monkeypatches this process's
    ``subprocess``/``urlopen``, and worker threads share the pid) and a child
    that installs the guard for itself. It does NOT cover a child spawned with
    a scrubbed environment from a different pid, and it cannot: this module has
    no way to observe a spend it never sees.
    """

    id: str
    label: str
    cap_usd: float
    ledger: "Ledger"
    lease_id: str | None = None
    expires_at: float | None = None
    #: What :meth:`close` reported, kept so a caller that used the context
    #: manager can still read the realized spend after the block.
    result: dict[str, Any] | None = None
    _closed: bool = False
    _prev_env: str | None = None

    def state(self) -> dict[str, Any] | None:
        """This envelope's cap/drawn/remaining right now, or None once closed."""
        return self.ledger.envelope_state(self.id)

    def close(self, reason: str = "") -> dict[str, Any]:
        """Release the unused hold and report what was really spent."""
        if self._closed:
            return self.result or {}
        self.result = self.ledger.close_envelope(self, reason=reason)
        self._closed = True
        return self.result

    def __enter__(self) -> "SpendEnvelope":
        self._prev_env = os.environ.get(ENV_ENVELOPE)
        ids = [i for i in (self._prev_env or "").split(",") if i.strip()]
        if self.id not in ids:
            ids.append(self.id)
        os.environ[ENV_ENVELOPE] = ",".join(ids)
        return self

    def __exit__(self, *exc: Any) -> bool:
        if self._prev_env is None:
            os.environ.pop(ENV_ENVELOPE, None)
        else:
            os.environ[ENV_ENVELOPE] = self._prev_env
        # CLOSED ON EVERY EXIT INCLUDING A RAISE. An envelope that survives its
        # own scope holds the day's money against a wave that is already over.
        self.close(reason="scope exited" if not exc[0] else
                   f"scope raised {exc[0].__name__}")
        return False


def _env_envelope_ids() -> set[str]:
    raw = os.environ.get(ENV_ENVELOPE) or ""
    return {part.strip() for part in raw.split(",") if part.strip()}


def _attributed(envelope_view: dict[str, Any]) -> bool:
    """Does a reservation made HERE, NOW draw on this envelope?

    Two answers, both required. The pid covers the process that opened the
    envelope -- including every worker thread in it, which is where the
    interposed reservations of a wave are actually made. The environment
    variable covers a child that inherited the scope and installed the process
    guard for itself. A spend that satisfies neither is invisible to this
    module and is bounded by the period ceiling alone.
    """
    if envelope_view["id"] in _env_envelope_ids():
        return True
    try:
        return int(envelope_view.get("pid") or -1) == os.getpid()
    except (TypeError, ValueError):
        return False


def _num(value: Any, name: str, *, allow_zero: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BudgetUnavailable(f"budget field '{name}' is not a number: {value!r}")
    out = float(value)
    if not isfinite(out):
        raise BudgetUnavailable(f"budget field '{name}' is not finite: {value!r}")
    if out < 0 or (out == 0 and not allow_zero):
        raise BudgetUnavailable(f"budget field '{name}' is out of range: {value!r}")
    return out


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        out = float(raw.strip())
    except ValueError as exc:
        raise BudgetUnavailable(
            f"{name}={raw!r} is not a number; refusing to guess a ceiling") from exc
    if not isfinite(out) or out <= 0:
        raise BudgetUnavailable(
            f"{name}={raw!r} is not a usable ceiling (must be finite and > 0)")
    return out


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise BudgetUnavailable(
        f"{name}={raw!r} is not a boolean; refusing to guess whether the "
        "period USD ceiling is active"
    )


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        out = int(raw.strip())
    except ValueError as exc:
        raise BudgetUnavailable(
            f"{name}={raw!r} is not an integer; refusing to guess a call cap") from exc
    if out <= 0:
        raise BudgetUnavailable(f"{name}={raw!r} is not a usable call cap (must be > 0)")
    return out


class Ledger:
    """The spend record, plus the ceiling it is checked against.

    Every mutating operation takes the cross-process lock, re-reads from disk,
    decides, and writes atomically. Nothing is cached across the lock boundary:
    a decision made from a value read before another process wrote is the race
    this class exists to close.
    """

    def __init__(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        ceiling_usd: float | None = None,
        period_ceiling_enabled: bool | None = None,
        execution_limit_policy: ExecutionLimitPolicy | None = None,
        max_calls: int | None = None,
        period: str | None = None,
        now: Callable[[], float] | None = None,
        lock_timeout_s: float = LOCK_TIMEOUT_S,
    ) -> None:
        raw = path if path is not None else os.environ.get(ENV_LEDGER) or DEFAULT_LEDGER_PATH
        self.path = Path(raw)
        self.lock_path = self.path.with_name(self.path.name + ".lock")
        self._ceiling_override = ceiling_usd
        self._period_ceiling_enabled_override = period_ceiling_enabled
        self._execution_limit_policy_override = execution_limit_policy
        self._max_calls_override = max_calls
        self._period_override = period
        self._now = now or time.time
        self.lock_timeout_s = lock_timeout_s

    # -- configuration ----------------------------------------------------

    def ceiling_usd(self) -> float:
        if self._ceiling_override is not None:
            return _num(self._ceiling_override, ENV_CEILING, allow_zero=False)
        return _env_float(ENV_CEILING, DEFAULT_CEILING_USD)

    def period_ceiling_enabled(self) -> bool:
        return self.execution_limit_policy().enforces("period_usd")

    def billable_call_ceiling_enabled(self) -> bool:
        return self.execution_limit_policy().enforces("billable_calls")

    def mission_spend_ceiling_enabled(self) -> bool:
        return self.execution_limit_policy().enforces("mission_spend")

    def execution_limit_policy(self) -> ExecutionLimitPolicy:
        """Policy for the next admission, with conservative Rev-9 migration.

        The canonical JSON environment wins when present.  Only when it is
        absent do we project the retired period-only boolean into ``custom``;
        this is what prevents an old USD-only uncapped desktop from silently
        becoming fully unbounded after an upgrade.
        """

        if self._execution_limit_policy_override is not None:
            if self._period_ceiling_enabled_override is not None:
                raise BudgetUnavailable(
                    "execution_limit_policy and period_ceiling_enabled cannot "
                    "both override the canonical policy"
                )
            if not isinstance(
                self._execution_limit_policy_override, ExecutionLimitPolicy
            ):
                raise BudgetUnavailable(
                    "execution_limit_policy must be ExecutionLimitPolicy"
                )
            return self._execution_limit_policy_override
        try:
            if self._period_ceiling_enabled_override is not None:
                if not isinstance(self._period_ceiling_enabled_override, bool):
                    raise BudgetUnavailable(
                        "period_ceiling_enabled must be a boolean"
                    )
                if self._period_ceiling_enabled_override:
                    return ExecutionLimitPolicy()
                return ExecutionLimitPolicy(
                    mode=MODE_CUSTOM,
                    configured=LimitAxes(period_usd=False),
                )
            if ENV_EXECUTION_LIMIT_POLICY in os.environ:
                return load_limit_policy_from_env()
            legacy_period = _env_bool(ENV_PERIOD_CEILING_ENABLED, True)
            if legacy_period:
                return ExecutionLimitPolicy()
            return ExecutionLimitPolicy(
                mode=MODE_CUSTOM,
                configured=LimitAxes(period_usd=False),
            )
        except LimitPolicyError as exc:
            raise BudgetUnavailable(
                f"invalid execution limit policy: {exc}; refusing to guess "
                "which resource caps are enforced"
            ) from exc

    def max_calls(self) -> int:
        if self._max_calls_override is not None:
            if isinstance(self._max_calls_override, bool) or int(self._max_calls_override) <= 0:
                raise BudgetUnavailable(f"max_calls={self._max_calls_override!r} is not usable")
            return int(self._max_calls_override)
        return _env_int(ENV_MAX_CALLS, DEFAULT_MAX_CALLS)

    def period(self) -> str:
        raw = (self._period_override or os.environ.get(ENV_PERIOD) or DEFAULT_PERIOD)
        raw = str(raw).strip().lower()
        if raw not in PERIODS:
            raise BudgetUnavailable(
                f"{ENV_PERIOD}={raw!r} is not one of {PERIODS}; refusing to "
                "guess how long the ceiling lasts")
        return raw

    def period_key(self) -> str:
        if self.period() == "total":
            return "total"
        t = time.gmtime(self._now())
        return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}"

    # -- reading ----------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        """Read the raw ledger. Raises BudgetUnavailable on ANY doubt.

        A MISSING file is the one benign case: it is an unambiguous "nothing has
        been spent yet". A file that exists but does not parse is not benign --
        it means we do not know the spend, and not knowing is a refusal.
        """
        try:
            text = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return self._fresh()
        except OSError as exc:
            raise BudgetUnavailable(
                f"cannot read budget ledger '{self.path}': {exc}; refusing to "
                "spend against an unknown balance") from exc
        if not text.strip():
            raise BudgetUnavailable(
                f"budget ledger '{self.path}' is empty but present; a truncated "
                "ledger is an unknown balance, not a zero balance")
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError) as exc:
            raise BudgetUnavailable(
                f"budget ledger '{self.path}' is corrupt ({exc}); refusing to "
                "spend against an unknown balance") from exc
        if not isinstance(data, dict):
            raise BudgetUnavailable(
                f"budget ledger '{self.path}' is not an object; refusing")
        data["spent_usd"] = _num(data.get("spent_usd"), "spent_usd")
        calls = data.get("calls")
        if isinstance(calls, bool) or not isinstance(calls, int) or calls < 0:
            raise BudgetUnavailable(f"budget ledger 'calls' is not a count: {calls!r}")
        data["calls"] = calls
        open_res = data.get("open")
        if not isinstance(open_res, dict):
            raise BudgetUnavailable("budget ledger 'open' is not an object; refusing")
        for key, row in open_res.items():
            if not isinstance(row, dict):
                raise BudgetUnavailable(f"budget ledger open reservation {key!r} is malformed")
            row["usd"] = _num(row.get("usd"), f"open[{key}].usd")
            n = row.get("calls", 1)
            if isinstance(n, bool) or not isinstance(n, int) or n < 0:
                raise BudgetUnavailable(f"budget ledger open[{key}].calls is not a count")
            row["calls"] = n
            names = row.get("envelopes", [])
            if not isinstance(names, list) or any(
                    not isinstance(n2, str) for n2 in names):
                raise BudgetUnavailable(
                    f"budget ledger open[{key}].envelopes is not a list of ids")
            captured = row.get("limit_policy")
            if captured is not None:
                try:
                    captured_policy = ExecutionLimitPolicy.from_dict(captured)
                    captured_effective = LimitAxes.from_dict(
                        row.get("effective_limit_axes")
                    )
                except LimitPolicyError as exc:
                    raise BudgetUnavailable(
                        f"budget ledger open reservation {key!r} has invalid "
                        f"execution-policy evidence: {exc}"
                    ) from exc
                if captured_effective != captured_policy.effective:
                    raise BudgetUnavailable(
                        f"budget ledger open reservation {key!r} effective "
                        "axes do not match its captured policy"
                    )
                fingerprint = row.get("limit_policy_fingerprint_sha256")
                if fingerprint != captured_policy.fingerprint_sha256:
                    raise BudgetUnavailable(
                        f"budget ledger open reservation {key!r} execution-"
                        "policy fingerprint does not match its captured policy"
                    )
        # ENVELOPES ARE VALIDATED AS HARD AS RESERVATIONS. A malformed envelope
        # is a ceiling we cannot compute, and an uncomputable ceiling is a
        # refusal -- the same rule the rest of this loader follows.
        envs = data.get("envelopes")
        if envs is None:
            envs = {}
            data["envelopes"] = envs
        if not isinstance(envs, dict):
            raise BudgetUnavailable("budget ledger 'envelopes' is not an object; refusing")
        for key, row in envs.items():
            if not isinstance(row, dict):
                raise BudgetUnavailable(f"budget ledger envelope {key!r} is malformed")
            row["cap_usd"] = _num(row.get("cap_usd"), f"envelopes[{key}].cap_usd")
            row["settled_usd"] = _num(row.get("settled_usd", 0.0),
                                      f"envelopes[{key}].settled_usd")
            exp = row.get("expires_at")
            if exp is not None:
                row["expires_at"] = _num(exp, f"envelopes[{key}].expires_at")
            mission_enforced = row.get("mission_spend_enforced", True)
            if type(mission_enforced) is not bool:
                raise BudgetUnavailable(
                    f"budget ledger envelope {key!r} has an invalid captured "
                    "mission-spend policy"
                )
            row["mission_spend_enforced"] = mission_enforced
            captured = row.get("limit_policy")
            if captured is not None:
                try:
                    captured_policy = ExecutionLimitPolicy.from_dict(captured)
                except LimitPolicyError as exc:
                    raise BudgetUnavailable(
                        f"budget ledger envelope {key!r} has an invalid captured "
                        f"execution policy: {exc}"
                    ) from exc
                fingerprint = row.get("limit_policy_fingerprint_sha256")
                if fingerprint not in (None, captured_policy.fingerprint_sha256):
                    raise BudgetUnavailable(
                        f"budget ledger envelope {key!r} execution-policy "
                        "fingerprint does not match its captured policy"
                    )
                if mission_enforced != captured_policy.enforces("mission_spend"):
                    raise BudgetUnavailable(
                        f"budget ledger envelope {key!r} mission-spend flag "
                        "does not match its captured policy"
                    )
        if not isinstance(data.get("entries"), list):
            data["entries"] = []
        return self._roll(data)

    def _fresh(self) -> dict[str, Any]:
        return {"version": 1, "period": self.period(), "period_key": self.period_key(),
                "spent_usd": 0.0, "calls": 0, "open": {}, "envelopes": {},
                "entries": []}

    def _roll(self, data: dict[str, Any]) -> dict[str, Any]:
        """Roll the period over. Settled spend resets; OPEN reservations do NOT
        -- money in flight is still in flight when the clock strikes midnight.

        OPEN ENVELOPES DO NOT RESET EITHER, and their drawn total least of all:
        a lease's ceiling is a property of the lease, not of the calendar. A
        wave that straddles midnight keeps exactly the ceiling it was granted.
        """
        want = self.period_key()
        if data.get("period_key") == want and data.get("period") == self.period():
            return data
        data["period"] = self.period()
        data["period_key"] = want
        data["spent_usd"] = 0.0
        data["calls"] = 0
        return data

    def _envelope_views(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        """One row per OPEN envelope, with its draw computed rather than stored.

        ``drawn`` is DERIVED (settled charges + still-open reservations that
        named this envelope) instead of maintained as a counter, so the two can
        never disagree: there is only one number, and it is recomputed from the
        same rows the period ceiling is computed from.
        """
        open_res = data.get("open") or {}
        now = self._now()
        rows: list[dict[str, Any]] = []
        for eid, row in (data.get("envelopes") or {}).items():
            in_flight = sum(float(r["usd"]) for r in open_res.values()
                            if eid in (r.get("envelopes") or []))
            cap = float(row["cap_usd"])
            drawn = float(row["settled_usd"]) + in_flight
            mission_enforced = bool(row.get("mission_spend_enforced", True))
            expires_at = row.get("expires_at")
            expired = expires_at is not None and now >= float(expires_at)
            rows.append({
                "id": eid,
                "label": str(row.get("label") or ""),
                "lease_id": row.get("lease_id"),
                "cap_usd": cap,
                "effective_cap_usd": cap if mission_enforced else None,
                "mission_spend_enforced": mission_enforced,
                "drawn_usd": drawn,
                "settled_usd": float(row["settled_usd"]),
                "in_flight_usd": in_flight,
                "remaining_usd": (
                    max(0.0, cap - drawn) if mission_enforced else None
                ),
                "opened_at": row.get("opened_at"),
                "expires_at": expires_at,
                "expired": expired,
                "pid": row.get("pid"),
                # UNUSED PRE-AUTHORISATION. Zero once the envelope has expired:
                # an abandoned wave must not hold the day's ceiling forever.
                # Expiry frees the HOLD only -- `drawn` above keeps every
                # dollar that was actually spent.
                "hold_usd": (
                    0.0
                    if expired or not mission_enforced
                    else max(0.0, cap - drawn)
                ),
                "limit_policy": row.get("limit_policy"),
                "limit_policy_fingerprint_sha256": row.get(
                    "limit_policy_fingerprint_sha256", ""
                ),
            })
        return rows

    def _state(self, data: dict[str, Any]) -> BudgetState:
        open_res = data.get("open") or {}
        envelopes = self._envelope_views(data)
        hold = float(sum(e["hold_usd"] for e in envelopes))
        policy = self.execution_limit_policy()
        return BudgetState(
            ceiling_usd=self.ceiling_usd(),
            max_calls=self.max_calls(),
            spent_usd=float(data["spent_usd"]),
            # THE HOLD IS RESERVED MONEY. A granted lease has already committed
            # its ceiling; counting it here is what makes the period ceiling
            # aware of a wave the instant it is authorised rather than only
            # once it starts billing.
            reserved_usd=float(sum(float(r["usd"]) for r in open_res.values())) + hold,
            calls=int(data["calls"]),
            open_calls=int(sum(int(r.get("calls", 1)) for r in open_res.values())),
            period=str(data.get("period", self.period())),
            period_key=str(data.get("period_key", self.period_key())),
            envelope_hold_usd=hold,
            envelopes=tuple(envelopes),
            period_ceiling_enabled=policy.enforces("period_usd"),
            billable_call_ceiling_enabled=policy.enforces("billable_calls"),
            mission_spend_ceiling_enabled=policy.enforces("mission_spend"),
            limit_policy_mode=policy.mode,
            configured_limit_axes=policy.configured.as_dict(),
            effective_limit_axes=policy.effective.as_dict(),
            limit_policy_fingerprint_sha256=policy.fingerprint_sha256,
        )

    def state(self) -> BudgetState:
        """Current state. Read under the lock, so it never straddles a write."""
        with _BudgetLock(self.lock_path, self.lock_timeout_s):
            return self._state(self._load())

    # -- writing ----------------------------------------------------------

    def _store(self, data: dict[str, Any]) -> None:
        entries = data.get("entries") or []
        data["entries"] = entries[-MAX_ENTRIES:]
        tmp = self.path.with_name(self.path.name + f".{os.getpid()}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
            for attempt in range(10):          # Windows: replace can lose a race
                try:
                    os.replace(tmp, self.path)
                    return
                except PermissionError:
                    if attempt == 9:
                        raise
                    time.sleep(0.05)
        except OSError as exc:
            try:
                tmp.unlink()
            except OSError:
                pass
            raise BudgetUnavailable(
                f"cannot write budget ledger '{self.path}': {exc}; refusing to "
                "spend against a balance we cannot record") from exc

    def reserve(self, estimate: Estimate, *, label: str) -> Reservation:
        """Commit ``estimate`` to the ledger BEFORE the call is made.

        This is the enforcement point. It returns only if the money fits; the
        money is already written to disk by the time it returns, so a caller
        that crashes mid-call leaves the spend counted (conservative) rather
        than uncounted (a leak).
        """
        label = (label or "").strip() or "<unlabelled call>"
        with _BudgetLock(self.lock_path, self.lock_timeout_s):
            data = self._load()
            st = self._state(data)
            want = max(1, int(estimate.calls))

            # ---- THE LEASED CEILING, CHECKED BEFORE THE PERIOD CEILING ----
            # Order is deliberate: when a wave crosses its own lease's ceiling
            # the refusal must name the LEASE, not the day's cap. Reporting
            # "spend ceiling would be crossed, ceiling=$5.00" for a wave leased
            # $0.25 tells an operator to raise the wrong number.
            attributed = [e for e in st.envelopes if _attributed(e)]
            relief = 0.0
            if estimate.usd > 0 and attributed:
                for env in attributed:
                    if env["expired"]:
                        raise BudgetRefused(
                            label=label, vendor=estimate.vendor, model=estimate.model,
                            estimate_usd=estimate.usd, spent_usd=st.spent_usd,
                            reserved_usd=st.reserved_usd,
                            ceiling_usd=st.ceiling_usd,
                            calls=st.calls, open_calls=st.open_calls, want_calls=want,
                            max_calls=st.max_calls, envelope=env,
                            reason=("the spend envelope for this lease has expired; "
                                    "an expired pre-authorisation is not a licence "
                                    "to keep spending"),
                            period_ceiling_enabled=st.period_ceiling_enabled,
                            billable_call_ceiling_enabled=(
                                st.billable_call_ceiling_enabled
                            ),
                            mission_spend_ceiling_enabled=(
                                st.mission_spend_ceiling_enabled
                            ))
                    if (
                        env["mission_spend_enforced"]
                        and env["drawn_usd"] + estimate.usd > env["cap_usd"]
                    ):
                        raise BudgetRefused(
                            label=label, vendor=estimate.vendor, model=estimate.model,
                            estimate_usd=estimate.usd, spent_usd=st.spent_usd,
                            reserved_usd=st.reserved_usd,
                            ceiling_usd=st.ceiling_usd,
                            calls=st.calls, open_calls=st.open_calls, want_calls=want,
                            max_calls=st.max_calls, envelope=env,
                            reason="the leased spend ceiling would be crossed",
                            period_ceiling_enabled=st.period_ceiling_enabled,
                            billable_call_ceiling_enabled=(
                                st.billable_call_ceiling_enabled
                            ),
                            mission_spend_ceiling_enabled=(
                                st.mission_spend_ceiling_enabled
                            ))
                # A DRAW INSIDE AN ENVELOPE IS NOT NEW COMMITMENT. Its hold was
                # already counted against the period ceiling when the lease was
                # granted, so the draw converts hold into an open reservation
                # rather than adding to the total. ``min`` across several
                # attributed envelopes is the conservative reading: relief only
                # up to the smallest hold available.
                relief = min(float(e["hold_usd"]) for e in attributed)
            names = [e["id"] for e in attributed]
            extra = max(0.0, estimate.usd - relief)

            # ``> 0`` and not ``>= 0``: the question this axis asks is "does THIS
            # call push the total over", not "is the total already over". A call
            # that adds nothing cannot cross a dollar ceiling, and refusing it
            # buys exactly nothing -- it only makes an exhausted budget block
            # work that is free. MEASURED 2026-07-29: with a subscription vendor
            # declared, `codex --version` was refused at estimate=$0.0000 against
            # spent=$24.00, and that $24 was itself fiction -- worst-case
            # reservations for calls a flat-rate plan had already paid for.
            #
            # This does NOT weaken the cap. A zero that came from a mispriced
            # vendor still gets counted on the call axis below (only the
            # host-certified ``free_local`` basis is exempt there), so an
            # under-priced runaway is still bounded -- by call count, which is
            # the axis this module already says it trusts more than price.
            if (st.period_ceiling_enabled and extra > 0
                    and st.committed_usd + extra > st.ceiling_usd):
                raise BudgetRefused(
                    label=label, vendor=estimate.vendor, model=estimate.model,
                    estimate_usd=estimate.usd, spent_usd=st.spent_usd,
                    reserved_usd=st.reserved_usd,
                    ceiling_usd=st.ceiling_usd,
                    calls=st.calls, open_calls=st.open_calls, want_calls=want,
                    max_calls=st.max_calls,
                    reason=(f"spend ceiling would be crossed "
                            f"(basis={estimate.basis})"),
                    period_ceiling_enabled=st.period_ceiling_enabled,
                    billable_call_ceiling_enabled=(
                        st.billable_call_ceiling_enabled
                    ),
                    mission_spend_ceiling_enabled=(
                        st.mission_spend_ceiling_enabled
                    ))

            # The call cap bounds BILLABLE fan-out (the canary's 16 probes), not
            # work in general. A call to this machine costs nothing, so counting
            # it would price the local lane out of the loop the cap exists to
            # protect. Gated on the BASIS, not on ``usd == 0``: a zero that came
            # from a mispriced vendor must still be counted, and only
            # ``free_local`` is certified zero by the shared host predicate.
            billable = estimate.basis != "free_local"
            if (
                billable
                and st.billable_call_ceiling_enabled
                and st.calls + st.open_calls + want > st.max_calls
            ):
                raise BudgetRefused(
                    label=label, vendor=estimate.vendor, model=estimate.model,
                    estimate_usd=estimate.usd, spent_usd=st.spent_usd,
                    reserved_usd=st.reserved_usd,
                    ceiling_usd=st.ceiling_usd,
                    calls=st.calls, open_calls=st.open_calls, want_calls=want,
                    max_calls=st.max_calls,
                    reason="call-count cap would be crossed",
                    period_ceiling_enabled=st.period_ceiling_enabled,
                    billable_call_ceiling_enabled=(
                        st.billable_call_ceiling_enabled
                    ),
                    mission_spend_ceiling_enabled=(
                        st.mission_spend_ceiling_enabled
                    ))

            rid = uuid.uuid4().hex
            captured_policy = {
                "mode": st.limit_policy_mode,
                "configured": dict(st.configured_limit_axes or {}),
            }
            data["open"][rid] = {
                "usd": float(estimate.usd), "calls": want if billable else 0,
                "vendor": estimate.vendor, "model": estimate.model,
                "basis": estimate.basis, "label": label, "at": self._now(),
                "pid": os.getpid(),
                # WHICH LEASED CEILINGS THIS CALL DRAWS ON. Written on the
                # reservation, not on the envelope, so the draw disappears with
                # the reservation if it is released and cannot be lost if this
                # process dies between the two writes.
                "envelopes": names,
                "limit_policy": captured_policy,
                "effective_limit_axes": dict(st.effective_limit_axes or {}),
                "limit_policy_fingerprint_sha256": (
                    st.limit_policy_fingerprint_sha256
                ),
            }
            data["entries"].append(
                {"kind": "reserve", "id": rid, "usd": float(estimate.usd),
                 "calls": want, "vendor": estimate.vendor, "model": estimate.model,
                 "basis": estimate.basis, "label": label, "at": self._now(),
                 "envelopes": names, "limit_policy": captured_policy,
                 "effective_limit_axes": dict(st.effective_limit_axes or {}),
                 "limit_policy_fingerprint_sha256": (
                     st.limit_policy_fingerprint_sha256
                 )})
            self._store(data)
        return Reservation(id=rid, estimate=estimate, label=label, ledger=self)

    def _close(self, res: Reservation, actual_usd: float | None,
               *, released: bool, reason: str) -> None:
        with _BudgetLock(self.lock_path, self.lock_timeout_s):
            data = self._load()
            row = data["open"].pop(res.id, None)
            if row is None:
                # Rolled over, hand-edited, or already closed. Charging the
                # estimate again would double-bill; ignoring it silently would
                # hide a corrupted ledger. Record and move on.
                data["entries"].append(
                    {"kind": "orphan_close", "id": res.id, "label": res.label,
                     "at": self._now()})
                self._store(data)
                return
            charge = float(row["usd"]) if actual_usd is None else _num(actual_usd, "actual_usd")
            if released:
                charge = 0.0
            data["spent_usd"] = float(data["spent_usd"]) + charge
            data["calls"] = int(data["calls"]) + (0 if released else int(row.get("calls", 1)))
            # THE DRAW MOVES FROM IN-FLIGHT TO SETTLED, on every envelope this
            # reservation named. A released reservation charges zero here for
            # the same reason it charges zero to the period ceiling: no vendor
            # bytes moved. An envelope that was closed while the call was in
            # flight is simply gone -- its money is already in ``spent_usd``.
            drawn_on = [str(e) for e in (row.get("envelopes") or [])]
            for eid in drawn_on:
                env_row = (data.get("envelopes") or {}).get(eid)
                if env_row is not None:
                    env_row["settled_usd"] = float(env_row["settled_usd"]) + charge
            data["entries"].append(
                {"kind": "release" if released else "settle", "id": res.id,
                 "usd": charge, "estimate_usd": float(row["usd"]),
                 "vendor": row.get("vendor"), "model": row.get("model"),
                 "label": res.label, "reason": reason, "at": self._now(),
                 "envelopes": drawn_on,
                 "limit_policy": row.get("limit_policy"),
                 "effective_limit_axes": row.get("effective_limit_axes"),
                 "limit_policy_fingerprint_sha256": row.get(
                     "limit_policy_fingerprint_sha256", ""
                 )})
            self._store(data)

    # -- spend envelopes --------------------------------------------------

    def open_envelope(self, cap_usd: float, *, label: str,
                      lease_id: str | None = None,
                      ttl_s: float | None = None,
                      reuse_open_lease: bool = False) -> SpendEnvelope:
        """Capture a Mission spend fallback and its admission-time policy.

        This is the enforcement point for a lease's ``max_cost_microusd``. The
        When ``mission_spend`` is enforced, the whole cap is written as a hold
        before this returns, exactly as :meth:`reserve` writes a call estimate.
        When the axis is disabled the fallback is still stored and every draw
        is still attributed, but no monetary hold or envelope refusal is
        invented. The captured policy remains with this envelope until close.

        ``reuse_open_lease`` is the crash-recovery seam for a caller that owns
        a stable, authenticated Effect-Lease identity.  Under the same ledger
        lock as admission, an already-open envelope for that exact ``lease_id``
        is returned only when its cap, label and captured limit policy match.
        This closes the otherwise ambiguous crash window between publishing the
        monetary hold and committing the Effect start: a restart re-enters the
        first hold instead of opening a second one or refusing itself against
        money it already reserved.  Ordinary callers keep the fresh-envelope
        behavior by default.

        ``cap_usd == 0`` is legal and means what it says -- a lease granted no
        money refuses every priced call attributed to it, while free local work
        (basis ``free_local``, priced at zero) still runs.
        """
        cap = _num(cap_usd, "cap_usd")
        label = (label or "").strip() or "<unlabelled envelope>"
        ttl = DEFAULT_ENVELOPE_TTL_S if ttl_s is None else float(ttl_s)
        if not isfinite(ttl) or ttl <= 0:
            ttl = DEFAULT_ENVELOPE_TTL_S
        if reuse_open_lease and not str(lease_id or "").strip():
            raise ValueError(
                "reuse_open_lease requires a non-empty Effect-Lease id"
            )
        with _BudgetLock(self.lock_path, self.lock_timeout_s):
            data = self._load()
            st = self._state(data)
            now = self._now()
            captured_policy = {
                "mode": st.limit_policy_mode,
                "configured": dict(st.configured_limit_axes or {}),
            }

            if reuse_open_lease:
                matches = [
                    (str(eid), row)
                    for eid, row in (data.get("envelopes") or {}).items()
                    if row.get("lease_id") == lease_id
                ]
                if len(matches) > 1:
                    raise BudgetUnavailable(
                        f"multiple open spend envelopes claim lease {lease_id!r}; "
                        "refusing ambiguous crash recovery"
                    )
                if matches:
                    eid, row = matches[0]
                    mismatches: list[str] = []
                    if float(row.get("cap_usd", -1.0)) != cap:
                        mismatches.append("cap_usd")
                    if str(row.get("label") or "") != label:
                        mismatches.append("label")
                    if bool(row.get("mission_spend_enforced", True)) != (
                        st.mission_spend_ceiling_enabled
                    ):
                        mismatches.append("mission_spend_enforced")
                    if row.get("limit_policy") != captured_policy:
                        mismatches.append("limit_policy")
                    if str(row.get("limit_policy_fingerprint_sha256") or "") != (
                        st.limit_policy_fingerprint_sha256
                    ):
                        mismatches.append("limit_policy_fingerprint_sha256")
                    expires_at = float(row.get("expires_at") or 0.0)
                    if now >= expires_at:
                        mismatches.append("expired")
                    if mismatches:
                        raise BudgetUnavailable(
                            f"open spend envelope for lease {lease_id!r} "
                            "contradicts this replay: " + ", ".join(mismatches)
                        )
                    data["entries"].append(
                        {
                            "kind": "envelope_reuse",
                            "id": eid,
                            "usd": cap,
                            "label": label,
                            "lease_id": lease_id,
                            "at": now,
                            "mission_spend_enforced": (
                                st.mission_spend_ceiling_enabled
                            ),
                            "limit_policy": captured_policy,
                            "limit_policy_fingerprint_sha256": (
                                st.limit_policy_fingerprint_sha256
                            ),
                        }
                    )
                    self._store(data)
                    return SpendEnvelope(
                        id=eid,
                        label=label,
                        cap_usd=cap,
                        ledger=self,
                        lease_id=lease_id,
                        expires_at=expires_at,
                    )

            if (st.mission_spend_ceiling_enabled
                    and st.period_ceiling_enabled and cap > 0
                    and st.committed_usd + cap > st.ceiling_usd):
                raise BudgetRefused(
                    label=label, vendor="", model="", estimate_usd=cap,
                    spent_usd=st.spent_usd, reserved_usd=st.reserved_usd,
                    ceiling_usd=st.ceiling_usd, calls=st.calls,
                    open_calls=st.open_calls, want_calls=0,
                    max_calls=st.max_calls,
                    reason=(f"the lease asked to pre-authorise ${cap:.4f} and the "
                            f"period ceiling has ${st.remaining_usd:.4f} left; a "
                            "capability nobody can pay for is not issued"),
                    period_ceiling_enabled=st.period_ceiling_enabled,
                    billable_call_ceiling_enabled=(
                        st.billable_call_ceiling_enabled
                    ),
                    mission_spend_ceiling_enabled=(
                        st.mission_spend_ceiling_enabled
                    ))
            eid = uuid.uuid4().hex
            data.setdefault("envelopes", {})[eid] = {
                "cap_usd": cap, "settled_usd": 0.0, "label": label,
                "lease_id": lease_id, "opened_at": now,
                "expires_at": now + ttl, "pid": os.getpid(),
                "mission_spend_enforced": st.mission_spend_ceiling_enabled,
                "limit_policy": captured_policy,
                "limit_policy_fingerprint_sha256": (
                    st.limit_policy_fingerprint_sha256
                ),
            }
            data["entries"].append(
                {"kind": "envelope_open", "id": eid, "usd": cap, "label": label,
                 "lease_id": lease_id, "at": now,
                 "mission_spend_enforced": st.mission_spend_ceiling_enabled,
                 "limit_policy": captured_policy,
                 "limit_policy_fingerprint_sha256": (
                     st.limit_policy_fingerprint_sha256
                 )})
            self._store(data)
        return SpendEnvelope(id=eid, label=label, cap_usd=cap, ledger=self,
                             lease_id=lease_id, expires_at=now + ttl)

    def envelope_state(self, envelope_id: str) -> dict[str, Any] | None:
        """One envelope's cap/drawn/remaining, or None when it is not open."""
        with _BudgetLock(self.lock_path, self.lock_timeout_s):
            for row in self._envelope_views(self._load()):
                if row["id"] == envelope_id:
                    return row
        return None

    def close_envelope(self, envelope: "SpendEnvelope | str", *,
                       reason: str = "") -> dict[str, Any]:
        """Release the unused hold; report the REALIZED spend.

        The returned dict is what a wave receipt carries beside the ceiling it
        was granted: ``cap_usd`` (what the lease allowed) and ``spent_usd``
        (what it actually cost). ``in_flight_usd`` is non-zero only when a call
        reserved inside the envelope had not settled yet -- that money is still
        charged to the period ledger when it settles; it just stops being
        charged to a lease that is over.
        """
        eid = envelope if isinstance(envelope, str) else envelope.id
        with _BudgetLock(self.lock_path, self.lock_timeout_s):
            data = self._load()
            views = {row["id"]: row for row in self._envelope_views(data)}
            view = views.get(eid)
            if view is None:
                # Already closed, hand-edited, or rolled away. Recorded rather
                # than raised: closing twice must not take down a wave that has
                # already finished spending.
                data["entries"].append(
                    {"kind": "envelope_orphan_close", "id": eid,
                     "reason": reason, "at": self._now()})
                self._store(data)
                return {"id": eid, "cap_usd": None, "spent_usd": None,
                        "closed": False, "reason": "envelope was not open"}
            (data.get("envelopes") or {}).pop(eid, None)
            out = {
                "id": eid, "label": view["label"], "lease_id": view["lease_id"],
                "cap_usd": view["cap_usd"],
                "effective_cap_usd": view["effective_cap_usd"],
                "mission_spend_enforced": view["mission_spend_enforced"],
                "spent_usd": view["settled_usd"],
                "in_flight_usd": view["in_flight_usd"],
                "released_hold_usd": view["hold_usd"],
                "expired": view["expired"], "closed": True, "reason": reason,
                "limit_policy": view["limit_policy"],
                "limit_policy_fingerprint_sha256": view[
                    "limit_policy_fingerprint_sha256"
                ],
            }
            data["entries"].append(dict(out, kind="envelope_close",
                                        at=self._now()))
            self._store(data)
        return out


# --------------------------------------------------------------------------
# module-level convenience
# --------------------------------------------------------------------------

_DEFAULT: Ledger | None = None
_DEFAULT_LOCK = threading.Lock()


def ledger() -> Ledger:
    """The process-wide default ledger (path from ``DAEDALUS_BUDGET_LEDGER``)."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        if _DEFAULT is None:
            _DEFAULT = Ledger()
        return _DEFAULT


def reset_default_ledger() -> None:
    """Drop the cached default ledger. For tests and for a process that has just
    changed ``DAEDALUS_BUDGET_LEDGER``."""
    global _DEFAULT
    with _DEFAULT_LOCK:
        _DEFAULT = None


def reserve(
    vendor: str | None,
    model: str | None = None,
    *,
    label: str,
    calls: int = 1,
    host: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    led: Ledger | None = None,
) -> Reservation:
    """Price and reserve in one step. Raises :class:`BudgetRefused` /
    :class:`BudgetUnavailable` / :class:`UnknownPrice` instead of returning."""
    est = price_call(vendor, model, calls=calls, host=host,
                     input_tokens=input_tokens, output_tokens=output_tokens)
    return (led or ledger()).reserve(est, label=label)


def open_envelope(cap_usd: float, *, label: str, lease_id: str | None = None,
                  ttl_s: float | None = None,
                  led: Ledger | None = None) -> SpendEnvelope:
    """Open a spend envelope on the process-wide ledger. See
    :meth:`Ledger.open_envelope`; raises :class:`BudgetRefused` when the
    pre-authorisation does not fit under the period ceiling."""
    return (led or ledger()).open_envelope(
        cap_usd, label=label, lease_id=lease_id, ttl_s=ttl_s)
