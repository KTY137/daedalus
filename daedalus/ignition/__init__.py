"""Gate-1 Renovation ignition slice.

:mod:`daedalus.ignition.gate1` is the Gate-1 slice as plan §10 states it -- one
MissionContract, two WorkItems, two isolated attempts, three checks, one
EvidencePacket, no promotion. It is what ``python -m daedalus.ignition`` runs,
and since ``G1-RENOVATION-02A`` (2026-09-06) it is the ONLY implementation of
that clause: :mod:`daedalus.ignition.runner` used to hold a second, in-process
rehearsal of the same slice and now holds only the three measurements ``gate1``
reuses (tree digest, Fourfold graph delta, candidate behaviour).
"""

from .runner import IgnitionError, IgnitionGraphDelta

__all__ = [
    "IgnitionError",
    "IgnitionGraphDelta",
]
