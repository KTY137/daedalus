"""Model-provider backends for the agent harness.

A provider turns a task brief into a validated structured report. Providers
differ in capability, not interface:

* ``claude_cli``  — agentic, write-capable, trusted with proprietary IP (primary).
* ``deepseek``    — read-only, external, may only see non-sensitive content.
* ``ollama``      — read-only, local (no egress), trusted with IP.

Selection is done by :mod:`agent_env.provider_router`.
"""

from __future__ import annotations

from .base import Provider, ProviderCapabilities

__all__ = ["Provider", "ProviderCapabilities", "get_provider", "available_providers"]


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


def available_providers() -> dict[str, bool]:
    """Which providers are actually reachable right now (env keys / local server)."""
    from .claude_cli import ClaudeCLIProvider
    from .deepseek import DeepSeekProvider
    from .ollama import OllamaProvider

    return {
        "claude_cli": ClaudeCLIProvider().available(),
        "deepseek": DeepSeekProvider().available(),
        "ollama": OllamaProvider().available(),
    }
