"""Standalone behavior checks for the pumplab fixture.

Deliberately NOT named test_* so repository pytest never collects it; the
experiment evaluator runs it as a subprocess and parses the CHECKS line.

The calibrate_linear check encodes the DOCUMENTED contract
(calibrated = flow_rate * GAIN + OFFSET). It passes because its probe row
sits at reference pressure, where the hidden correction is neutral — the
checks author is as unaware of the coupling as the operator author.
"""
import csv
from pathlib import Path

import calib


def run():
    checks = []
    rows = [{"sample_id": "1", "flow_rate": "2.0", "pressure": "100.0",
             "temperature": "25.0", "rpm": "1500.0"}]
    cal = calib.calibrate(rows)
    checks.append(("calibrate_linear", abs(cal[0]["calibrated"] - (2.0 * calib.GAIN + calib.OFFSET)) < 1e-9))
    checks.append(("summary_header", "calibrated" in calib.summary(rows).splitlines()[0]))
    data = Path(__file__).parent / "data" / "events.csv"
    with open(data, newline="") as fh:
        table = list(csv.DictReader(fh))
    checks.append(("row_count", len(table) >= 10))
    checks.append(("flow_numeric", all(float(r["flow_rate"]) == float(r["flow_rate"]) for r in table)))
    passed = sum(1 for _name, ok in checks if ok)
    print(f"CHECKS {passed}/{len(checks)}")
    return passed == len(checks)


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
