"""Compatibility and effect doors for model-provider backends.

Provider contracts, metadata, and health projection are owned by
``daedalus.runtimes.providers``. Concrete construction remains here while
the registered provider targets retain their historical module paths.
"""

from __future__ import annotations

from ..runtimes.providers.catalogue import (
    PROVIDER_CATALOGUE as _PROVIDERS,
    ProviderMetadata,
    available_from_health as _available_from_health,
    configured as _configured,
    list_providers,
    probe_provider as _probe_provider,
    provider_health as _project_provider_health,
)
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


def get_provider(name: str) -> Provider:
    """Construct one concrete provider through the stable effect door."""

    if name == "claude_cli":
        from .claude_cli import ClaudeCLIProvider

        return ClaudeCLIProvider()
    if name == "deepseek":
        from .deepseek import DeepSeekProvider

        return DeepSeekProvider()
    if name == "ollama":
        from .ollama import OllamaProvider

        return OllamaProvider()
    if name == "codex_cli":
        from .codex_cli import CodexCLIProvider

        return CodexCLIProvider()
    raise ValueError(f"unknown provider '{name}'")


def _availability_probe(name: str) -> tuple[bool, str]:
    return _probe_provider(name, get_provider)


def provider_health() -> list[dict]:
    return _project_provider_health(_availability_probe)


def available_providers() -> dict[str, bool]:
    """Which implemented providers are reachable and configured right now."""

    return _available_from_health(provider_health())
