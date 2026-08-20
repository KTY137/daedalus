"""Pumplab calibration pipeline (four-plane mini fixture: code plane).

Documented contract (README, checks): calibrated flow is a linear function
of flow_rate. The pressure correction below is the fixture's deliberate
hidden coupling — it is declared nowhere in the knowledge plane.
"""
import csv
import sys
from pathlib import Path

GAIN = 4.0
OFFSET = 0.25
P_REF = 100.0
P_COEF = 0.002


def load_events(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def calibrate(rows):
    out = []
    for row in rows:
        r = dict(row)
        correction = 1.0 + P_COEF * (float(row["pressure"]) - P_REF)
        r["calibrated"] = round(float(row["flow_rate"]) * GAIN * correction + OFFSET, 6)
        out.append(r)
    return out


def summary(rows):
    cal = calibrate(rows)
    total = sum(r["calibrated"] for r in cal)
    lines = ["sample_id flow_rate calibrated"]
    for r in cal:
        lines.append(f'{r["sample_id"]} {r["flow_rate"]} {r["calibrated"]}')
    lines.append(f"n={len(cal)} sum={round(total, 6)}")
    return "\n".join(lines)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent / "data" / "events.csv")
    print(summary(load_events(path)))


if __name__ == "__main__":
    main()
