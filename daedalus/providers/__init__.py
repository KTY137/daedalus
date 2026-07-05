"""Model-provider backends for the agent harness.

A provider turns a task brief into a validated structured report. Providers
differ in capability, not interface:

* ``claude_cli``  — agentic, write-capable, trusted with proprietary IP (primary).
* ``deepseek``    — read-only, external, may only see non-sensitive content.
* ``ollama``      — read-only, local (no egress), trusted with IP.

Selection is done by :mod:`daedalus.provider_router`.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass

from .base import Provider, ProviderCapabilities

__all__ = [
    "Provider",
    "ProviderCapabilities",
    "ProviderMetadata",
    "get_provider",
    "list_providers",
    "provider_health",
    "available_providers",
]


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


_PROVIDERS: dict[str, ProviderMetadata] = {
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
        can_write=False,
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
        trusted_with_ip=True,
        can_write=True,
        agentic=True,
        requires_key=False,
        implemented=False,
    ),
}


def get_provider(name: str) -> Provider:
    if name == "claude_cli":
        from .claude_cli import ClaudeCLIProvider

        return ClaudeCLIProvider()
    if name == "deepseek":
        from .deepseek import DeepSeekProvider

        return DeepSeekProvider()
    if name == "ollama":
        from .ollama import OllamaProvider

        return OllamaProvider()
    raise ValueError(f"unknown provider '{name}'")


def list_providers() -> list[dict]:
    return [asdict(meta) for meta in _PROVIDERS.values()]


def _configured(meta: ProviderMetadata) -> bool:
    if not meta.requires_key:
        return True
    return any(bool(os.environ.get(key)) for key in meta.env_keys)


def _availability_probe(name: str) -> tuple[bool, str]:
    if not _PROVIDERS[name].implemented:
        return False, "provider placeholder; implementation pending"
    try:
        return get_provider(name).available(), ""
    except Exception as exc:
        return False, str(exc)


def provider_health() -> list[dict]:
    rows = []
    for meta in _PROVIDERS.values():
        available, error = _availability_probe(meta.name)
        configured = _configured(meta)
        rows.append({
            **asdict(meta),
            "configured": configured,
            "available": bool(available and configured and meta.implemented),
            "last_error": error,
        })
    return rows


def available_providers() -> dict[str, bool]:
    """Which providers are actually reachable right now (env keys / local server)."""
    return {row["name"]: bool(row["available"]) for row in provider_health() if row["implemented"]}
