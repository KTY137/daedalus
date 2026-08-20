"""Chemlab calibration pipeline (four-plane mini fixture: code plane).

Documented contract (README, checks): calibrated yield is a fully additive
function of reagent_a, reagent_b and catalyst — every read below is
declared in the knowledge plane. There is no hidden coupling; temperature
and rpm-like extras do not exist here, temperature is read by nothing.
"""
import csv
import sys
from pathlib import Path

A_COEF = 0.8
B_COEF = 0.5
C_COEF = 0.02
OFFSET = 1.5


def load_events(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def calibrate(rows):
    out = []
    for row in rows:
        r = dict(row)
        r["calibrated"] = round(
            A_COEF * float(row["reagent_a"])
            + B_COEF * float(row["reagent_b"])
            + C_COEF * float(row["catalyst"])
            + OFFSET, 6)
        out.append(r)
    return out


def summary(rows):
    cal = calibrate(rows)
    total = sum(r["calibrated"] for r in cal)
    lines = ["sample_id reagent_a calibrated"]
    for r in cal:
        lines.append(f'{r["sample_id"]} {r["reagent_a"]} {r["calibrated"]}')
    lines.append(f"n={len(cal)} sum={round(total, 6)}")
    return "\n".join(lines)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent / "data" / "events.csv")
    print(summary(load_events(path)))


if __name__ == "__main__":
    main()
