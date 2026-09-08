"""Lazy compatibility facade for :mod:`daedalus.runtimes.admission`.

Runtime admission belongs to the runtime layer, not the kernel. Importing this
legacy module alone does not load the runtime package. Attribute access resolves
lazily to the canonical owner, so old and new imports receive the same objects
rather than parallel wrapper functions or duplicated singleton state.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

_OWNER_MODULE = "daedalus.runtimes.admission"

__all__ = [
    "RUNTIME_AUTHORITY_KEY_ID",
    "RUNTIME_LEASE_KEY_ID",
    "acquire_runtime_bound_authorization",
    "runtime_trust_ledger",
    "runtime_trust_ledger_path",
]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(import_module(_OWNER_MODULE), name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
