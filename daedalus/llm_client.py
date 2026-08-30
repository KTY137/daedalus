"""Vendor-neutral language-model client policy for Ikarus.

Iron Plan: ALIGNED — this is the vendor-neutral runtime contract required by
master-plan §7.  It deliberately owns *selection and call policy*, not effects:
the actual transports remain in :mod:`daedalus.ikarus_os`, behind the existing
provider effect boundary.  A model is a speaking/proposal surface; selecting it
never grants file, tool, policy, evaluator, or promotion authority.

The client makes the chat default useful: ``auto`` means "pick an available
LLM", never "silently fall back to deterministic help text".  The deterministic
index remains an explicit runtime because status/distill are measurements, not
language-model work.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Mapping, Sequence


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
    timeout_s: float
    max_attempts: int
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


StatusProbe = Callable[[str], Mapping[str, Any]]


class IkarusLLMClient:
    """Selection/configuration seam shared by blocking and streaming chat.

    Transport is intentionally injected/owned elsewhere. That keeps the one
    existing effect boundary authoritative while still centralising model
    choice, timeout and retry policy here.
    """

    def __init__(self, *, environ: Mapping[str, str] | None = None,
                 status_probe: StatusProbe | None = None) -> None:
        self.environ = os.environ if environ is None else environ
        self._status_probe = status_probe

    @property
    def timeout_s(self) -> float:
        return _bounded_float(self.environ.get("DAEDALUS_IKARUS_TIMEOUT_S"), 150.0, 10.0, 600.0)

    @property
    def max_attempts(self) -> int:
        # No hidden paid retries by default. Operators can opt into at most two
        # retries; every transport attempt still crosses the budget boundary.
        retries = _bounded_int(self.environ.get("DAEDALUS_IKARUS_RETRIES"), 0, 0, 2)
        return 1 + retries

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
        if self._status_probe is not None:
            return self._status_probe(runtime_id)
        try:
            from .runtime_registry import cached_runtime_status

            return cached_runtime_status(runtime_id)
        except Exception as exc:  # a failed probe is not an available model
            return {"available": False, "last_error": str(exc)}

    def resolve(self, requested: str | None = None) -> LLMSelection:
        requested_norm = normalize_provider(requested)
        env_default = normalize_provider(self.environ.get("DAEDALUS_IKARUS_PROVIDER"))

        # A user explicitly selecting the local index is allowed. Automatic
        # selection never lands here.
        if requested_norm == "deterministic":
            return LLMSelection("deterministic", requested_norm, False,
                                self.timeout_s, 1, "explicit local-index selection")

        explicit = requested_norm if requested_norm != "auto" else env_default
        if explicit not in ("auto", "deterministic"):
            if explicit not in _PROVIDER_ALIASES.values():
                return LLMSelection(None, explicit, requested_norm == "auto",
                                    self.timeout_s, self.max_attempts,
                                    f"unknown Ikarus LLM provider {explicit!r}")
            return LLMSelection(explicit, requested_norm, requested_norm == "auto",
                                self.timeout_s, self.max_attempts,
                                "configured provider" if requested_norm == "auto" else "explicit provider")

        failures: list[str] = []
        for candidate in self._order():
            row = self._probe(candidate)
            if bool(row.get("available")):
                return LLMSelection(candidate, requested_norm, True,
                                    self.timeout_s, self.max_attempts,
                                    "first available provider in automatic preference order")
            failures.append(f"{candidate}: {row.get('last_error') or row.get('auth_status') or 'unavailable'}")
        detail = "; ".join(failures[:5])
        return LLMSelection(None, requested_norm, True, self.timeout_s,
                            self.max_attempts,
                            "no configured LLM runtime is available" + (f" ({detail})" if detail else ""))

    def complete(self, request: LLMRequest,
                 invoke: Callable[[str, LLMRequest, float], LLMResponse | str | None],
                 requested: str | None = None) -> LLMResponse:
        """Run a blocking transport under this client's retry policy.

        This method does not open sockets or spawn processes; ``invoke`` is the
        effect-guarded adapter supplied by the caller.
        """
        selection = self.resolve(requested)
        if not selection.provider or selection.provider == "deterministic":
            raise LLMUnavailable(selection.reason)
        last_error = "model returned no text"
        for attempt in range(1, selection.max_attempts + 1):
            try:
                result = invoke(selection.provider, request, selection.timeout_s)
                if isinstance(result, LLMResponse) and result.text.strip():
                    return LLMResponse(result.text, result.provider, result.model,
                                       result.tool_calls, attempts=attempt)
                if isinstance(result, str) and result.strip():
                    return LLMResponse(result.strip(), selection.provider,
                                       request.model, attempts=attempt)
            except Exception as exc:  # caller still owns the typed provider error
                last_error = f"{type(exc).__name__}: {exc}"
        raise LLMUnavailable(f"{selection.provider} produced no usable response after "
                             f"{selection.max_attempts} attempt(s): {last_error}")
