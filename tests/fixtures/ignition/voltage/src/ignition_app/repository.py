from __future__ import annotations

from .models import Event


def parse_event(row: dict[str, str]) -> Event:
    return Event(id=row["id"], voltage=float(row["voltage"]))
