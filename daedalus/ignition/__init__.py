# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Gate-1 Renovation ignition slice.

:mod:`daedalus.ignition.gate1` is the Gate-1 slice as plan §10 states it -- one
MissionContract, two WorkItems, two isolated attempts, three checks, one
EvidencePacket, no promotion. :mod:`daedalus.ignition.runner` is the earlier
in-process rehearsal it grew out of; it is retained because it is still the
cheapest way to exercise the Fourfold delta and behaviour measurements, and
``gate1`` reuses those three functions rather than copying them.
"""

from .runner import (
    IgnitionError,
    IgnitionGraphDelta,
    IgnitionResult,
    IgnitionWorkItem,
    materialize_voltage_rename,
    run_voltage_ignition,
)

__all__ = [
    "IgnitionError",
    "IgnitionGraphDelta",
    "IgnitionResult",
    "IgnitionWorkItem",
    "materialize_voltage_rename",
    "run_voltage_ignition",
]
