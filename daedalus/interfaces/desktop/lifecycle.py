"""Desktop service-lifecycle composition without process ownership."""
from __future__ import annotations

from typing import Any


def bootstrap(manager: Any, *, error_type: type[Exception]) -> dict[str, Any]:
    """Start only the services already admitted by the manager configuration."""

    if manager.config["bridge"]["auto_start"]:
        manager.ensure_bridge()
    if manager.config["ollama"]["auto_start"]:
        try:
            manager.ensure_ollama()
        except error_type as exc:
            manager._log(f"ollama autostart failed: {exc}")
    if manager.config["ide"]["auto_start"]:
        try:
            manager.ensure_ide()
        except error_type as exc:
            manager._log(f"IDE autostart failed: {exc}")
    return manager.snapshot()


def close(
    manager: Any,
    *,
    strict: bool,
    timeout: float,
    error_type: type[Exception],
) -> None:
    """Close manager-owned services through their existing stop methods."""

    manager._closed = True
    manager._bridge_stop.set()
    cleanup_error: Exception | None = None
    try:
        manager.stop_ide(owned_only=True, strict=strict, timeout=timeout)
    except error_type as exc:
        cleanup_error = exc
    manager.stop_ollama()
    if strict and cleanup_error is not None:
        raise cleanup_error
