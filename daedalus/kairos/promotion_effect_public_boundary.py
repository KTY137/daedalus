"""Install the persisted Effect-Lease lifecycle as the public promotion seam.

This module is deliberately inert until
:func:`install_promotion_effect_public_boundary` is called from the completed
``daedalus.kairos.gated_writes`` module.  The installer captures the already
sealed promotion implementation, makes it reachable only through a scoped
capability token, and replaces the historic public name with a fail-closed
compatibility facade.

The compatibility facade preserves the historic callable metadata and visible
signature, but a fresh repository effect additionally requires the keyword-only
``promotion_effect_capability`` at runtime.  Calls that omit it are refused
before the retained delegate can be entered.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import inspect
import json
from types import ModuleType
from typing import Any, Callable, Mapping, MutableMapping


_ENTRYPOINT_ID = "python.promote_candidates"
_INSTALLATION_SCHEMA = "daedalus-promotion-public-boundary/1"
_MARKER = "_PROMOTION_EFFECT_PUBLIC_BOUNDARY_INSTALLATION"


class PromotionEffectPublicBoundaryError(RuntimeError):
    """The live promotion facade could not be installed or entered safely."""


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True)
class PromotionEffectPublicBoundaryReceipt:
    """Machine-readable, non-authoritative proof of an exact installation."""

    entrypoint_id: str
    delegate_module: str
    delegate_qualname: str
    visible_signature: str
    capability_keyword: str
    direct_delegate_blocked: bool
    automatic_promotion_allowed: bool
    receipt_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": _INSTALLATION_SCHEMA,
            "entrypoint_id": self.entrypoint_id,
            "delegate_module": self.delegate_module,
            "delegate_qualname": self.delegate_qualname,
            "visible_signature": self.visible_signature,
            "capability_keyword": self.capability_keyword,
            "direct_delegate_blocked": self.direct_delegate_blocked,
            "automatic_promotion_allowed": self.automatic_promotion_allowed,
            "receipt_sha256": self.receipt_sha256,
        }


@dataclass(frozen=True)
class _InstalledBoundary:
    public_entrypoint: Callable[..., Any]
    delegate_facade: object
    receipt: PromotionEffectPublicBoundaryReceipt


def _receipt_for(delegate: Callable[..., Any]) -> PromotionEffectPublicBoundaryReceipt:
    module = getattr(delegate, "__module__", None)
    qualname = getattr(delegate, "__qualname__", None)
    if not isinstance(module, str) or not module:
        raise PromotionEffectPublicBoundaryError(
            "promotion delegate has no canonical module identity"
        )
    if not isinstance(qualname, str) or not qualname:
        raise PromotionEffectPublicBoundaryError(
            "promotion delegate has no canonical qualified name"
        )
    try:
        visible_signature = str(inspect.signature(delegate))
    except (TypeError, ValueError) as exc:
        raise PromotionEffectPublicBoundaryError(
            "promotion delegate has no inspectable signature"
        ) from exc
    body = {
        "schema": _INSTALLATION_SCHEMA,
        "entrypoint_id": _ENTRYPOINT_ID,
        "delegate_module": module,
        "delegate_qualname": qualname,
        "visible_signature": visible_signature,
        "capability_keyword": "promotion_effect_capability",
        "direct_delegate_blocked": True,
        "automatic_promotion_allowed": False,
    }
    digest = hashlib.sha256(_canonical_json(body)).hexdigest()
    return PromotionEffectPublicBoundaryReceipt(
        entrypoint_id=_ENTRYPOINT_ID,
        delegate_module=module,
        delegate_qualname=qualname,
        visible_signature=visible_signature,
        capability_keyword="promotion_effect_capability",
        direct_delegate_blocked=True,
        automatic_promotion_allowed=False,
        receipt_sha256=digest,
    )


def _copy_compatibility_metadata(
    public: Callable[..., Any],
    delegate: Callable[..., Any],
) -> None:
    """Preserve normal introspection without publishing ``__wrapped__``.

    ``functools.wraps`` would expose the retained effectful delegate through the
    public ``__wrapped__`` attribute.  The strangler instead copies inert
    metadata and installs the historic signature explicitly.
    """

    for attribute in ("__name__", "__qualname__", "__module__", "__doc__"):
        value = getattr(delegate, attribute, None)
        if value is not None:
            setattr(public, attribute, value)
    annotations = getattr(delegate, "__annotations__", None)
    if isinstance(annotations, dict):
        public.__annotations__ = dict(annotations)
    public.__signature__ = inspect.signature(delegate)  # type: ignore[attr-defined]


def _submitted_candidates(args: tuple[Any, ...], kwargs: Mapping[str, Any]) -> list[Any]:
    raw: Any
    if len(args) >= 2:
        raw = args[1]
    else:
        raw = kwargs.get("candidates", ())
    try:
        return list(raw)
    except (TypeError, ValueError):
        return []


def _missing_capability_refusal(
    namespace: Mapping[str, Any],
    args: tuple[Any, ...],
    kwargs: Mapping[str, Any],
) -> dict[str, Any]:
    error = PromotionEffectPublicBoundaryError(
        "persisted PromotionEffectCapability is mandatory before any promotion effect"
    )
    refusal = namespace.get("_promotion_refusal")
    if not callable(refusal):
        raise error
    report = refusal(_submitted_candidates(args, kwargs), error)
    if not isinstance(report, dict):
        raise PromotionEffectPublicBoundaryError(
            "promotion refusal boundary returned a non-mapping report"
        )
    report["promotion_effect_boundary"] = {
        "schema": _INSTALLATION_SCHEMA,
        "entrypoint_id": _ENTRYPOINT_ID,
        "entered": False,
        "automatic_promotion_allowed": False,
        "reason": "missing_promotion_effect_capability",
    }
    return report


def _install_boundary(
    namespace: MutableMapping[str, Any],
    lifecycle_module: ModuleType,
) -> PromotionEffectPublicBoundaryReceipt:
    """Install against an exact module namespace; exposed privately for tests."""

    if not isinstance(namespace, MutableMapping):
        raise TypeError("promotion boundary requires a mutable module namespace")
    retained = namespace.get(_MARKER)
    current = namespace.get("promote_candidates")
    if retained is not None:
        if not isinstance(retained, _InstalledBoundary):
            raise PromotionEffectPublicBoundaryError(
                "promotion boundary marker has an unexpected type"
            )
        if current is not retained.public_entrypoint:
            raise PromotionEffectPublicBoundaryError(
                "public promotion entrypoint changed after boundary installation"
            )
        if getattr(lifecycle_module, "gated_writes", None) is not retained.delegate_facade:
            raise PromotionEffectPublicBoundaryError(
                "promotion lifecycle delegate facade changed after installation"
            )
        return retained.receipt

    if not callable(current):
        raise PromotionEffectPublicBoundaryError(
            "public promotion delegate is missing or not callable"
        )
    source_module = getattr(lifecycle_module, "gated_writes", None)
    if not isinstance(source_module, ModuleType):
        raise PromotionEffectPublicBoundaryError(
            "promotion lifecycle is not bound to the canonical gated_writes module"
        )
    if source_module.__dict__ is not namespace:
        raise PromotionEffectPublicBoundaryError(
            "promotion lifecycle and installation namespace do not share identity"
        )
    lifecycle_entry = getattr(
        lifecycle_module,
        "promote_candidates_with_effect_lifecycle",
        None,
    )
    if not callable(lifecycle_entry):
        raise PromotionEffectPublicBoundaryError(
            "promotion effect lifecycle entrypoint is missing"
        )

    delegate = current
    receipt = _receipt_for(delegate)
    call_scope: ContextVar[object | None] = ContextVar(
        "daedalus_promotion_delegate_scope",
        default=None,
    )
    scope_capability = object()

    class _ScopedDelegateFacade:
        __slots__ = ()

        def promote_candidates(self, *args: Any, **kwargs: Any) -> Any:
            if call_scope.get() is not scope_capability:
                raise PromotionEffectPublicBoundaryError(
                    "sealed promotion delegate is reachable only from the public "
                    "Effect-Lease lifecycle"
                )
            return delegate(*args, **kwargs)

        def __setattr__(self, _name: str, _value: Any) -> None:
            raise PromotionEffectPublicBoundaryError(
                "sealed promotion delegate facade is immutable"
            )

    delegate_facade = _ScopedDelegateFacade()

    def public_entrypoint(*args: Any, **kwargs: Any) -> Any:
        if "promotion_effect_capability" not in kwargs:
            return _missing_capability_refusal(namespace, args, kwargs)
        capability = kwargs.pop("promotion_effect_capability")
        token = call_scope.set(scope_capability)
        try:
            return lifecycle_entry(
                *args,
                promotion_effect_capability=capability,
                **kwargs,
            )
        finally:
            call_scope.reset(token)

    _copy_compatibility_metadata(public_entrypoint, delegate)
    public_entrypoint.__dict__["promotion_effect_boundary_receipt"] = receipt.to_dict()
    lifecycle_module.gated_writes = delegate_facade
    namespace["promote_candidates"] = public_entrypoint
    installed = _InstalledBoundary(
        public_entrypoint=public_entrypoint,
        delegate_facade=delegate_facade,
        receipt=receipt,
    )
    namespace[_MARKER] = installed

    if namespace.get("promote_candidates") is not public_entrypoint:
        raise PromotionEffectPublicBoundaryError(
            "public promotion boundary installation did not retain exact identity"
        )
    if lifecycle_module.gated_writes is not delegate_facade:
        raise PromotionEffectPublicBoundaryError(
            "promotion lifecycle did not retain the scoped delegate facade"
        )
    return receipt


def install_promotion_effect_public_boundary(
    namespace: MutableMapping[str, Any],
) -> PromotionEffectPublicBoundaryReceipt:
    """Install the fail-closed outer promotion facade exactly once.

    The caller is expected to pass ``globals()`` from the completed
    ``daedalus.kairos.gated_writes`` module.  No OwnerApproval, Effect Lease,
    promotion, merge, branch update or checkout mutation is performed by the
    installer itself.
    """

    from . import promotion_effect_lifecycle

    return _install_boundary(namespace, promotion_effect_lifecycle)


__all__ = (
    "PromotionEffectPublicBoundaryError",
    "PromotionEffectPublicBoundaryReceipt",
    "install_promotion_effect_public_boundary",
)
