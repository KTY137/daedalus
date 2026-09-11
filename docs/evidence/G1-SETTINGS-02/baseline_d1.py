"""Baseline probe for G1-SETTINGS-02: reproduce D1 in both directions.

Run with the worktree's interpreter. Writes only into a fresh temp dir.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from daedalus.interfaces.desktop.configuration import defaults, normalize_config  # noqa: E402

CHILD = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
from daedalus.kernel.policy.ledger import Ledger
led = Ledger()
row = {}
try:
    row["ceiling_usd"] = led.ceiling_usd()
except Exception as exc:
    row["ceiling_usd"] = "ERR " + str(exc)
try:
    row["max_calls"] = led.max_calls()
except Exception as exc:
    row["max_calls"] = "ERR " + str(exc)
try:
    pol = led.execution_limit_policy()
    row["caps_mode"] = pol.mode
    row["period_usd_enforced"] = pol.enforces("period_usd")
except Exception as exc:
    row["caps_mode"] = "ERR " + str(exc)
print(json.dumps(row))
"""

UNBOUNDED = json.dumps(
    {
        "mode": "unbounded_execution",
        "configured": {
            axis: True
            for axis in (
                "attempts",
                "billable_calls",
                "concurrency",
                "mission_spend",
                "period_usd",
                "tokens",
                "wall_time",
                "work_scope",
            )
        },
    },
    separators=(",", ":"),
    sort_keys=True,
)


def child(env_extra: dict[str, str]) -> dict:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("DAEDALUS_BUDGET")
        and k != "DAEDALUS_EXECUTION_LIMIT_POLICY"
    }
    env.update(env_extra)
    out = subprocess.run(
        [sys.executable, "-c", CHILD, str(ROOT)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="d1-baseline-"))
    doc_dir = tmp / "config"
    doc_dir.mkdir(parents=True)

    saved = defaults()
    saved["budget"]["period_ceiling_usd"] = 200.0
    saved["budget"]["max_calls"] = 5000
    saved = normalize_config(saved)
    (doc_dir / "connections.json").write_text(
        json.dumps(saved, indent=2), encoding="utf-8"
    )

    print("admitted document        :", saved["budget"], saved["caps"]["mode"])
    print("document written to      :", doc_dir / "connections.json")
    print("kernel anchor ROOT       :", ROOT)
    print("ROOT/config exists       :", (ROOT / "config").exists())
    print()
    print("A. fresh process, no budget env  ->", child({}))
    print("   direction (a): the admitted document does not reach the kernel")
    print()
    print(
        "B. fresh process, hostile ambient env ->",
        child(
            {
                "DAEDALUS_BUDGET_USD": "999999",
                "DAEDALUS_BUDGET_MAX_CALLS": "1000000",
                "DAEDALUS_EXECUTION_LIMIT_POLICY": UNBOUNDED,
            }
        ),
    )
    print("   direction (b): an unadmitted variable reaches the kernel")
    print()
    print(
        "C. fresh process, deliberately NARROWER env ->",
        child({"DAEDALUS_BUDGET_USD": "1", "DAEDALUS_BUDGET_MAX_CALLS": "2"}),
    )
    print("   the shell workflow that must keep working")
    print()
    print("temp runtime root:", tmp)


if __name__ == "__main__":
    main()
