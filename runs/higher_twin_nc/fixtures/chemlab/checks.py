"""Standalone behavior checks for the chemlab fixture.

Deliberately NOT named test_* so repository pytest never collects it; the
experiment evaluator runs it as a subprocess and parses the CHECKS line.

Unlike pumplab, the checks author knows the COMPLETE contract: the
calibrate_additive check recomputes the full documented sum.
"""
import csv
from pathlib import Path

import calib


def run():
    checks = []
    rows = [{"sample_id": "1", "reagent_a": "10.0", "reagent_b": "4.0",
             "catalyst": "20.0", "temperature": "22.0"}]
    cal = calib.calibrate(rows)
    expected = 10.0 * calib.A_COEF + 4.0 * calib.B_COEF + 20.0 * calib.C_COEF + calib.OFFSET
    checks.append(("calibrate_additive", abs(cal[0]["calibrated"] - expected) < 1e-9))
    checks.append(("summary_header", "calibrated" in calib.summary(rows).splitlines()[0]))
    data = Path(__file__).parent / "data" / "events.csv"
    with open(data, newline="") as fh:
        table = list(csv.DictReader(fh))
    checks.append(("row_count", len(table) >= 10))
    checks.append(("reagent_numeric", all(float(r["reagent_a"]) == float(r["reagent_a"]) for r in table)))
    passed = sum(1 for _name, ok in checks if ok)
    print(f"CHECKS {passed}/{len(checks)}")
    return passed == len(checks)


if __name__ == "__main__":
    raise SystemExit(0 if run() else 1)
