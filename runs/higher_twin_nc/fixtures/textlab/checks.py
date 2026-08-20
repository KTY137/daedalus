"""Standalone behavior checks for the textlab fixture.

Deliberately NOT named test_* so repository pytest never collects it; the
experiment evaluator runs it as a subprocess and parses the CHECKS line.
"""
import csv
from pathlib import Path

import calib


def run():
    checks = []
    rows = [{"sample_id": "1", "score": "4.0", "weight": "2.5"}]
    cal = calib.calibrate(rows)
    checks.append(("calibrate_linear", abs(cal[0]["calibrated"] - (4.0 * calib.W_COEF + calib.OFFSET)) < 1e-9))
    checks.append(("summary_header", "calibrated" in calib.summary(rows).splitlines()[0]))
    data = Path(__file__).parent / "data" / "events.csv"
    with open(data, newline="") as fh:
        table = list(csv.DictReader(fh))
    checks.append(("row_count", len(table) >= 10))
    checks.append(("score_numeric", all(float(r["score"]) == float(r["score"]) for r in table)))
    passed = sum(1 for _name, ok in checks if ok)
    print(f"CHECKS {passed}/{len(checks)}")
    return passed == len(checks)


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
