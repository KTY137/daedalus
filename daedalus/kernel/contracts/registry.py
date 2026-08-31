"""Closed registry and strict parser for kernel contract types."""

from .canonical import KERNEL_CONTRACT_TYPES, parse_kernel_contract

__all__ = ["KERNEL_CONTRACT_TYPES", "parse_kernel_contract"]
