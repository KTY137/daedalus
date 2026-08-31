"""Runtime-owned provider metadata and health projection.

Concrete provider construction is an effectful compatibility door. This
module therefore owns the deterministic catalogue and projection logic while
receiving availability as an injected probe.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Protocol


@dataclass(frozen=True)
class ProviderMetadata:
    name: str
    display_name: str
    local: bool
    trusted_with_ip: bool
    can_write: bool
    agentic: bool
    requires_key: bool
    env_keys: tuple[str, ...] = ()
    implemented: bool = True


PROVIDER_CATALOGUE: dict[str, ProviderMetadata] = {
    "ollama": ProviderMetadata(
        name="ollama",
        display_name="Ollama",
        local=True,
        trusted_with_ip=True,
        can_write=True,
        agentic=True,
        requires_key=False,
    ),
    "claude_cli": ProviderMetadata(
        name="claude_cli",
        display_name="Claude CLI",
        local=False,
        trusted_with_ip=True,
        can_write=True,
        agentic=True,
        requires_key=False,
    ),
    "deepseek": ProviderMetadata(
        name="deepseek",
        display_name="DeepSeek API",
        local=False,
        trusted_with_ip=False,
        can_write=True,
        agentic=False,
        requires_key=True,
        env_keys=("DEEPSEEK_API_KEY",),
    ),
    "openai_api": ProviderMetadata(
        name="openai_api",
        display_name="OpenAI API",
        local=False,
        trusted_with_ip=False,
        can_write=False,
        agentic=False,
        requires_key=True,
        env_keys=("OPENAI_API_KEY",),
        implemented=False,
    ),
    "anthropic_api": ProviderMetadata(
        name="anthropic_api",
        display_name="Anthropic API",
        local=False,
        trusted_with_ip=True,
        can_write=False,
        agentic=False,
        requires_key=True,
        env_keys=("ANTHROPIC_API_KEY",),
        implemented=False,
    ),
    "codex_cli": ProviderMetadata(
        name="codex_cli",
        display_name="Codex CLI",
        local=False,
        trusted_with_ip=False,
        can_write=True,
        agentic=True,
        requires_key=False,
    ),
}

AvailabilityProbe = Callable[[str], tuple[bool, str]]


class AvailableProvider(Protocol):
    def available(self) -> bool: ...


ProviderFactory = Callable[[str], AvailableProvider]


def list_providers() -> list[dict]:
    return [asdict(meta) for meta in PROVIDER_CATALOGUE.values()]


def configured(
    meta: ProviderMetadata,
    *,
    environ: Mapping[str, str] | None = None,
) -> bool:
    if not meta.requires_key:
        return True
    env = os.environ if environ is None else environ
    return any(bool(env.get(key)) for key in meta.env_keys)


def probe_provider(name: str, factory: ProviderFactory) -> tuple[bool, str]:
    """Probe one implemented provider through an injected construction door."""

    if not PROVIDER_CATALOGUE[name].implemented:
        return False, "provider placeholder; implementation pending"
    try:
        return factory(name).available(), ""
    except Exception as exc:  # noqa: BLE001 - a failed probe is health data
        return False, str(exc)


def provider_health(
    probe: AvailabilityProbe,
    *,
    environ: Mapping[str, str] | None = None,
) -> list[dict]:
    rows: list[dict] = []
    for meta in PROVIDER_CATALOGUE.values():
        available, error = probe(meta.name)
        is_configured = configured(meta, environ=environ)
        rows.append(
            {
                **asdict(meta),
                "configured": is_configured,
                "available": bool(
                    available and is_configured and meta.implemented
                ),
                "last_error": error,
            }
        )
    return rows


def available_from_health(rows: Iterable[Mapping[str, object]]) -> dict[str, bool]:
    return {
        str(row["name"]): bool(row["available"])
        for row in rows
        if bool(row["implemented"])
    }


__all__ = [
    "PROVIDER_CATALOGUE",
    "ProviderMetadata",
    "available_from_health",
    "configured",
    "list_providers",
    "probe_provider",
    "provider_health",
]
