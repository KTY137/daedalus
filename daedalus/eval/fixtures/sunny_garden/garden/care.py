"""Watering decisions for the bundled sunny-garden corpus."""

from __future__ import annotations

from datetime import date

from .plants import PLANTS


def needs_water(plant: str, last_watered: date, today: date | None = None) -> bool:
    """Return whether ``water_every_days`` has elapsed for ``plant``."""

    current = today or date.today()
    return (current - last_watered).days >= PLANTS[plant]["water_every_days"]


def watering_plan(last_watered: dict[str, date], today: date | None = None) -> list[str]:
    """Return the plants that need water today."""

    return [
        plant
        for plant in PLANTS
        if needs_water(plant, last_watered[plant], today=today)
    ]
