"""Textlab calibration pipeline (four-plane mini fixture: code plane).

Documented contract (README, checks), complete by construction:
`calibrated = score * W_COEF + OFFSET`. Only `score` is read; `weight`
is inert. The interesting plane of this fixture is knowledge, not code.
"""
import csv
import sys
from pathlib import Path

W_COEF = 1.5
OFFSET = 0.5


def load_events(path):
    with open(path, newline="") as fh:
        return list(csv.DictReader(fh))


def calibrate(rows):
    out = []
    for row in rows:
        r = dict(row)
        r["calibrated"] = round(float(row["score"]) * W_COEF + OFFSET, 6)
        out.append(r)
    return out


def summary(rows):
    cal = calibrate(rows)
    total = sum(r["calibrated"] for r in cal)
    lines = ["sample_id score calibrated"]
    for r in cal:
        lines.append(f'{r["sample_id"]} {r["score"]} {r["calibrated"]}')
    lines.append(f"n={len(cal)} sum={round(total, 6)}")
    return "\n".join(lines)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).parent / "data" / "events.csv")
    print(summary(load_events(path)))


if __name__ == "__main__":
    main()
