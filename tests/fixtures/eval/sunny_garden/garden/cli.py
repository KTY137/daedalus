"""Console presentation for the bundled sunny-garden corpus."""

from __future__ import annotations

from datetime import date

from .care import watering_plan


def main(last_watered: dict[str, date]) -> None:
    for plant in watering_plan(last_watered):
        print(f"water {plant}")

