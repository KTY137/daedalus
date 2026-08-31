"""Desktop compatibility surface above the canonical runtime facade.

The sidecar and existing callers intentionally continue to import
``daedalus.desktop_runtime``.  These lazy exports expose those exact objects
through the hierarchical package without caching monkeypatch-sensitive facade
attributes.  Implementation modules in this package never import the facade.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any


_COMPAT_EXPORTS = frozenset(
    {
        "DesktopRuntimeError",
        "DesktopRuntimeManager",
        "install_tunnel_egress_policy",
        "install_web_integration",
        "normalize_config",
    }
)

__all__ = tuple(sorted(_COMPAT_EXPORTS))


def __getattr__(name: str) -> Any:
    """Resolve the stable desktop facade without creating a second owner."""

    if name not in _COMPAT_EXPORTS:
        raise AttributeError(name)
    facade = import_module("daedalus.desktop_runtime")
    return getattr(facade, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | _COMPAT_EXPORTS)
