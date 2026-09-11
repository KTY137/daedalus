"""Neutral closed vocabulary for observed subsystem and dispatch outcomes.

The five strings are persisted by conversation dispatch reports and rendered
by the health surface.  Their shared contract therefore belongs below both
consumers: neither diagnostic implementation nor conversation storage owns a
second copy of the vocabulary.
"""

WORKING = "working"
PRESENT = "present"
DEGRADED = "degraded"
ABSENT = "absent"
UNKNOWN = "unknown"

OBSERVATION_STATES = (WORKING, PRESENT, DEGRADED, ABSENT, UNKNOWN)

__all__ = [
    "ABSENT",
    "DEGRADED",
    "OBSERVATION_STATES",
    "PRESENT",
    "UNKNOWN",
    "WORKING",
]
