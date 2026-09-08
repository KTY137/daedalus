"""Vendor-neutral language-model client policy for Ikarus.

Iron Plan: ALIGNED — this is the vendor-neutral runtime contract required by
master-plan §7.  It deliberately owns *selection and call policy*, not effects:
the actual transports remain in :mod:`daedalus.orchestration.ikarus.shell`, behind the existing
provider effect boundary.  A model is a speaking/proposal surface; selecting it
never grants file, tool, policy, evaluator, or promotion authority.

The client makes the chat default useful: ``auto`` means "pick an available
LLM", never "silently fall back to deterministic help text".  The deterministic
index remains an explicit runtime because status/distill are measurements, not
language-model work.
"""
from __future__ import annotations

import os
import math
from collections.abc import Mapping as MappingABC
from itertools import count
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence

from ..limit_policy import ExecutionLimitPolicy, load_from_env as load_limit_policy


_PROVIDER_ALIASES = {
    "claude": "claude_code_cli",
    "claude_cli": "claude_code_cli",
    "claude_code_cli": "claude_code_cli",
    "codex": "codex_cli",
    "codex_cli": "codex_cli",
    "ollama": "ollama_http",
    "ollama_http": "ollama_http",
    "ollama_cli": "ollama_cli",
    "deepseek": "deepseek",
    "deterministic": "deterministic",
}

# Primary frontier voice first, then local/free, then the other connected
# runtimes. Operators can change this without changing code.
_DEFAULT_ORDER = ("claude_code_cli", "ollama_http", "codex_cli", "ollama_cli", "deepseek")
_RUNTIME_STATUS_ID = {
    "claude_code_cli": "claude_code_cli",
    "codex_cli": "codex_cli",
    "ollama_http": "ollama_http",
    "ollama_cli": "ollama_cli",
}


def normalize_provider(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw in ("", "auto", "none"):
        return "auto"
    return _PROVIDER_ALIASES.get(raw, raw)


def _bounded_float(value: str | None, default: float, low: float, high: float) -> float:
    try:
        parsed = float(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


def _bounded_int(value: str | None, default: int, low: int, high: int) -> int:
    try:
        parsed = int(value) if value is not None else default
    except (TypeError, ValueError):
        parsed = default
    return max(low, min(high, parsed))


@dataclass(frozen=True)
class LLMToolCall:
    """A model-proposed tool call. It is data, never permission to execute."""

    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)
    call_id: str | None = None


@dataclass(frozen=True)
class LLMRequest:
    """Provider-neutral request contract.

    ``tools`` describes callable shapes for providers that support structured
    tool use. Ikarus Voice currently sends an empty tuple; effectful work stays
    on the Hand/supervisor path and therefore cannot be smuggled through chat.
    """

    message: str
    project: str | None = None
    model: str | None = None
    effort: str | None = None
    tools: tuple[Mapping[str, Any], ...] = ()
    conversation_id: str | None = None


@dataclass(frozen=True)
class LLMSelection:
    provider: str | None
    requested: str
    auto_selected: bool
    timeout_s: float | None
    max_attempts: int | None
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "requested": self.requested,
            "auto_selected": self.auto_selected,
            "timeout_s": self.timeout_s,
            "max_attempts": self.max_attempts,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider: str
    model: str | None = None
    tool_calls: tuple[LLMToolCall, ...] = ()
    attempts: int = 1


class LLMUnavailable(RuntimeError):
    pass


def _is_authoritative_refusal(exc: Exception) -> bool:
    """Return True when an adapter already produced a canonical deny receipt.

    The provider/effect layers own authority and produce content-addressed
    refusal receipts. Retrying such an exception is not resilience: it repeats
    a decision that already said the effect may not start, and wrapping it in
    ``LLMUnavailable`` discards the evidence callers need to explain the denial.
    Keep the client decoupled from concrete provider exception classes by
    recognising the receipt contract instead of importing their modules.
    """
    receipt = getattr(exc, "receipt", None)
    if not isinstance(receipt, MappingABC):
        return False
    return str(receipt.get("verdict") or "").strip().lower() in {"deny", "denied", "refuse", "refused"}



StatusProbe = Callable[[str], Mapping[str, Any]]


class IkarusLLMClient:
    """Selection/configuration seam shared by blocking and streaming chat.

    Transport is intentionally injected/owned elsewhere. That keeps the one
    existing effect boundary authoritative while still centralising model
    choice, timeout and retry policy here.
    """

    def __init__(self, *, environ: Mapping[str, str] | None = None,
                 status_probe: StatusProbe | None = None,
                 limit_policy: ExecutionLimitPolicy | None = None) -> None:
        self.environ = os.environ if environ is None else environ
        self._status_probe = status_probe
        self.limit_policy = limit_policy or load_limit_policy(self.environ)
        if not isinstance(self.limit_policy, ExecutionLimitPolicy):
            raise TypeError("limit_policy must be an ExecutionLimitPolicy")

    @property
    def timeout_s(self) -> float | None:
        if not self.limit_policy.enforces("wall_time"):
            return None
        return _bounded_float(self.environ.get("DAEDALUS_IKARUS_TIMEOUT_S"), 150.0, 10.0, 600.0)

    @property
    def max_attempts(self) -> int | None:
        if not self.limit_policy.enforces("attempts"):
            return None
        # No hidden paid retries by default. Operators can opt into at most two
        # retries; every transport attempt still crosses the budget boundary.
        retries = _bounded_int(self.environ.get("DAEDALUS_IKARUS_RETRIES"), 0, 0, 2)
        return 1 + retries

    @property
    def readiness_ttl_s(self) -> float:
        """Maximum age of runtime evidence that may drive automatic Voice choice.

        The cockpit's runtime cache is an observability/performance control and
        can be tuned independently. Voice selection is an execution decision, so
        it owns a small freshness ceiling instead of inheriting an arbitrarily
        long dashboard cache TTL. Thirty seconds matches the registry default;
        the bounded override exists for slow installations without allowing an
        hours-old positive probe to masquerade as current readiness.
        """
        return _bounded_float(
            self.environ.get("DAEDALUS_IKARUS_READINESS_TTL_S"), 30.0, 1.0, 120.0
        )


    def _normalise_probe_row(
        self, provider: str, runtime_id: str, row: object
    ) -> Mapping[str, Any]:
        """Validate observational runtime evidence before it influences routing.

        ``bool("false")`` is True in Python, so truthiness is not a safe runtime
        boundary. The registry contract emits a real boolean; anything else is
        malformed and therefore unavailable. Cached observations additionally
        carry ``measured_age_s``. When present, a negative, non-finite or expired
        age is rejected rather than silently treated as a fresh positive probe.
        """
        if not isinstance(row, MappingABC):
            return {
                "available": False,
                "last_error": (
                    f"{provider}: malformed runtime observation (expected mapping, "
                    f"got {type(row).__name__})"
                ),
            }
        observed_id = row.get("id")
        if observed_id not in (None, runtime_id):
            return {
                "available": False,
                "last_error": (
                    f"{provider}: runtime observation identity mismatch "
                    f"({observed_id!r} != {runtime_id!r})"
                ),
            }
        available = row.get("available")
        if type(available) is not bool:
            return {
                "available": False,
                "last_error": (
                    f"{provider}: malformed runtime observation ('available' must "
                    "be a boolean)"
                ),
            }
        if "measured_age_s" in row:
            try:
                age = float(row.get("measured_age_s"))
            except (TypeError, ValueError):
                age = math.nan
            if not math.isfinite(age) or age < 0:
                return {
                    "available": False,
                    "last_error": (
                        f"{provider}: malformed runtime observation "
                        "('measured_age_s' must be finite and non-negative)"
                    ),
                }
            if age >= self.readiness_ttl_s:
                return {
                    "available": False,
                    "last_error": (
                        f"{provider}: stale runtime observation ({age:.3f}s old; "
                        f"Voice limit {self.readiness_ttl_s:.3f}s)"
                    ),
                }
        return row


    @staticmethod
    def _probe_failure(provider: str, row: Mapping[str, Any]) -> str:
        detail = row.get("last_error") or row.get("auth_status") or "unavailable"
        return f"{provider}: {detail}"


    def _order(self) -> tuple[str, ...]:
        configured = self.environ.get("DAEDALUS_IKARUS_PROVIDER_ORDER", "")
        if not configured.strip():
            return _DEFAULT_ORDER
        values = tuple(normalize_provider(v) for v in configured.split(",") if v.strip())
        return tuple(v for v in values if v not in ("auto", "deterministic")) or _DEFAULT_ORDER

    def _probe(self, provider: str) -> Mapping[str, Any]:
        if provider == "deepseek":
            return {"available": bool(str(self.environ.get("DEEPSEEK_API_KEY", "")).strip())}
        runtime_id = _RUNTIME_STATUS_ID.get(provider)
        if runtime_id is None:
            return {"available": False, "last_error": "not a wired Ikarus voice runtime"}
        try:
            if self._status_probe is not None:
                row = self._status_probe(runtime_id)
            else:
                from .runtime_registry import cached_runtime_status

                # Voice owns the freshness of the evidence it acts on. Do not
                # inherit a dashboard cache TTL that an operator may have made
                # deliberately long for cheap observability.
                row = cached_runtime_status(runtime_id, ttl_s=self.readiness_ttl_s)
        except Exception as exc:  # a failed probe is not an available model
            row = {"available": False, "last_error": str(exc)}
        return self._normalise_probe_row(provider, runtime_id, row)


    def resolve(self, requested: str | None = None) -> LLMSelection:
        requested_norm = normalize_provider(requested)
        env_default = normalize_provider(self.environ.get("DAEDALUS_IKARUS_PROVIDER"))

        # A user explicitly selecting the local index is allowed. Automatic
        # selection never lands here.
        if requested_norm == "deterministic":
            return LLMSelection("deterministic", requested_norm, False,
                                self.timeout_s, 1, "explicit local-index selection")

        # Explicit provider choice is a hard preference and therefore never
        # falls back. Keep transport-owned readiness semantics for HTTP/local
        # lanes: an explicit Ollama request must still reach its egress policy so
        # a denied endpoint produces the canonical refusal receipt rather than a
        # generic "unavailable" selection. Claude is the exception because its
        # runtime probe now includes the exact executable-admission rule used by
        # the sealed path; preserving that pre-spawn refusal here prevents the
        # chat picker from claiming an unsafe Windows .cmd/.bat shim is usable.
        if requested_norm != "auto":
            if requested_norm not in _PROVIDER_ALIASES.values():
                return LLMSelection(None, requested_norm, False,
                                    self.timeout_s, self.max_attempts,
                                    f"unknown Ikarus LLM provider {requested_norm!r}")
            if requested_norm == "claude_code_cli":
                row = self._probe(requested_norm)
                if row.get("available") is not True:
                    return LLMSelection(
                        None, requested_norm, False, self.timeout_s, self.max_attempts,
                        "explicit provider is unavailable ("
                        + self._probe_failure(requested_norm, row) + ")",
                    )
                reason = "explicit provider is available"
            else:
                reason = "explicit provider; transport owns final readiness"
            return LLMSelection(requested_norm, requested_norm, False,
                                self.timeout_s, self.max_attempts, reason)

        # The operator may deliberately pin the default Voice to the local,
        # deterministic index. That is a policy choice, not a readiness
        # fallback: honour it before probing any LLM so an omitted/`auto`
        # request cannot silently become a paid Claude/Codex turn against the
        # configured intent. Automatic probing still never chooses the
        # deterministic runtime unless this explicit environment policy says so.
        if env_default == "deterministic":
            return LLMSelection("deterministic", requested_norm, True,
                                self.timeout_s, 1,
                                "configured deterministic Voice policy")

        failures: list[str] = []

        # DAEDALUS_IKARUS_PROVIDER is the operator's preferred automatic Voice,
        # not permission to lie about readiness. Try it first when configured;
        # if its measured status is unavailable, retain the reason and continue
        # through the normal preference order. This makes `auto` resilient while
        # preserving the rule that a directly requested provider never changes
        # underneath the user.
        if env_default not in ("auto", "deterministic"):
            if env_default not in _PROVIDER_ALIASES.values():
                failures.append(f"{env_default}: unknown configured provider")
            else:
                row = self._probe(env_default)
                if row.get("available") is True:
                    return LLMSelection(env_default, requested_norm, True,
                                        self.timeout_s, self.max_attempts,
                                        "configured provider is available")
                failures.append(self._probe_failure(env_default, row))

        for candidate in self._order():
            if candidate == env_default:
                continue
            row = self._probe(candidate)
            if row.get("available") is True:
                reason = "first available provider in automatic preference order"
                if failures:
                    reason += "; earlier preference unavailable: " + failures[0]
                return LLMSelection(candidate, requested_norm, True,
                                    self.timeout_s, self.max_attempts, reason)
            failures.append(self._probe_failure(candidate, row))
        detail = "; ".join(failures[:5])
        return LLMSelection(None, requested_norm, True, self.timeout_s,
                            self.max_attempts,
                            "no configured LLM runtime is available" + (f" ({detail})" if detail else ""))


    def complete(self, request: LLMRequest,
                 invoke: Callable[[str, LLMRequest, float | None], LLMResponse | str | None],
                 requested: str | None = None) -> LLMResponse:
        """Run a blocking transport under this client's retry policy.

        This method does not open sockets or spawn processes; ``invoke`` is the
        effect-guarded adapter supplied by the caller.
        """
        selection = self.resolve(requested)
        if not selection.provider or selection.provider == "deterministic":
            raise LLMUnavailable(selection.reason)
        last_error = "model returned no text"
        attempts: Iterable[int] = (
            count(1)
            if selection.max_attempts is None
            else range(1, selection.max_attempts + 1)
        )
        for attempt in attempts:
            try:
                result = invoke(selection.provider, request, selection.timeout_s)
                if isinstance(result, LLMResponse) and (result.text.strip() or result.tool_calls):
                    return LLMResponse(result.text, result.provider, result.model,
                                       result.tool_calls, attempts=attempt)
                if isinstance(result, str) and result.strip():
                    return LLMResponse(result.strip(), selection.provider,
                                       request.model, attempts=attempt)
            except Exception as exc:  # caller still owns the typed provider error
                if _is_authoritative_refusal(exc):
                    raise
                last_error = f"{type(exc).__name__}: {exc}"
        # The unbounded-attempt iterator has no natural exhaustion, so this is
        # reachable only for a bounded admission.
        raise LLMUnavailable(f"{selection.provider} produced no usable response after "
                             f"{selection.max_attempts} attempt(s): {last_error}")
