"""Closed registry and strict parser for kernel contract types."""

from . import genesis as _genesis  # register the additive Genesis domain
from .canonical import KERNEL_CONTRACT_TYPES, parse_kernel_contract

__all__ = ["KERNEL_CONTRACT_TYPES", "parse_kernel_contract"]
