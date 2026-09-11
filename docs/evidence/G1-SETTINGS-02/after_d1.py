"""Post-fix probe for G1-SETTINGS-02: the same matrix as baseline_d1.py."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from daedalus.interfaces.desktop.configuration import defaults, normalize_config  # noqa: E402

CHILD = r"""
import json, os, sys
sys.path.insert(0, sys.argv[1])
from daedalus.kernel.policy.ledger import Ledger
root = sys.argv[2] or None
led = Ledger(runtime_root=root)
row = {}
try:
    row["ceiling_usd"] = led.ceiling_usd()
except Exception as exc:
    row["ceiling_usd"] = "REFUSED " + type(exc).__name__
try:
    row["max_calls"] = led.max_calls()
except Exception as exc:
    row["max_calls"] = "REFUSED " + type(exc).__name__
try:
    pol = led.execution_limit_policy()
    row["caps_mode"] = pol.mode
    row["period_usd_enforced"] = pol.enforces("period_usd")
except Exception as exc:
    row["caps_mode"] = "REFUSED " + type(exc).__name__
try:
    prov = led.limit_provenance()
    row["src"] = {
        "ceiling": prov["period_ceiling_usd"]["source"],
        "refused_env_ceiling": prov["period_ceiling_usd"]["refused_environment_value"],
        "policy": prov["execution_limit_policy"]["source"],
        "refused_axes": len(prov["execution_limit_policy"]["refused_environment_axes"]),
        "document": prov["admitted_document"] is not None,
    }
except Exception as exc:
    row["src"] = "REFUSED " + type(exc).__name__
print(json.dumps(row))
"""

AXES = (
    "attempts",
    "billable_calls",
    "concurrency",
    "mission_spend",
    "period_usd",
    "tokens",
    "wall_time",
    "work_scope",
)
UNBOUNDED = json.dumps(
    {"mode": "unbounded_execution", "configured": {a: True for a in AXES}},
    separators=(",", ":"),
    sort_keys=True,
)


def child(root: Path | None, env_extra: dict[str, str]) -> dict:
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("DAEDALUS_BUDGET")
        and k != "DAEDALUS_EXECUTION_LIMIT_POLICY"
    }
    env.update(env_extra)
    out = subprocess.run(
        [sys.executable, "-c", CHILD, str(ROOT), "" if root is None else str(root)],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(out.stdout.strip().splitlines()[-1])


def write_doc(root: Path, **budget) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    saved = defaults()
    saved["budget"].update(budget)
    saved = normalize_config(saved)
    (root / "config" / "connections.json").write_text(
        json.dumps(saved, indent=2), encoding="utf-8"
    )


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="d1-after-"))
    write_doc(tmp, period_ceiling_usd=200.0, max_calls=5000)

    print("admitted document: period_ceiling_usd=200.0 max_calls=5000 caps=bounded")
    print()
    print("A. no budget env, admitted document  ->", child(tmp, {}))
    print("B. hostile ambient env               ->", child(tmp, {
        "DAEDALUS_BUDGET_USD": "999999",
        "DAEDALUS_BUDGET_MAX_CALLS": "1000000",
        "DAEDALUS_EXECUTION_LIMIT_POLICY": UNBOUNDED,
    }))
    print("C. deliberately NARROWER env         ->", child(tmp, {
        "DAEDALUS_BUDGET_USD": "1", "DAEDALUS_BUDGET_MAX_CALLS": "2",
    }))
    print("D. no document at all, hostile env   ->", child(None, {
        "DAEDALUS_BUDGET_USD": "999999",
        "DAEDALUS_BUDGET_MAX_CALLS": "1000000",
        "DAEDALUS_EXECUTION_LIMIT_POLICY": UNBOUNDED,
    }))
    corrupt = Path(tempfile.mkdtemp(prefix="d1-corrupt-"))
    (corrupt / "config").mkdir(parents=True)
    (corrupt / "config" / "connections.json").write_text("{ not json", encoding="utf-8")
    print("E. corrupt document + hostile env    ->", child(corrupt, {
        "DAEDALUS_BUDGET_USD": "999999",
    }))

    # cost of one resolution, measured
    sys.path.insert(0, str(ROOT))
    from daedalus.kernel.policy.ledger import Ledger, load_admitted_settings

    for _ in range(200):
        load_admitted_settings(tmp)
    t0 = time.perf_counter()
    for _ in range(2000):
        load_admitted_settings(tmp)
    per_read_us = (time.perf_counter() - t0) / 2000 * 1e6

    led_doc = Ledger(runtime_root=tmp)
    led_none = Ledger(runtime_root=corrupt.parent / "nonexistent")
    for _ in range(200):
        led_doc.ceiling_usd()
        led_none.ceiling_usd()
    t0 = time.perf_counter()
    for _ in range(2000):
        led_doc.ceiling_usd()
    with_doc_us = (time.perf_counter() - t0) / 2000 * 1e6
    t0 = time.perf_counter()
    for _ in range(2000):
        led_none.ceiling_usd()
    no_doc_us = (time.perf_counter() - t0) / 2000 * 1e6

    print()
    print(f"cost: load_admitted_settings  {per_read_us:8.2f} us/call")
    print(f"cost: ceiling_usd() with doc  {with_doc_us:8.2f} us/call")
    print(f"cost: ceiling_usd() no doc    {no_doc_us:8.2f} us/call")


if __name__ == "__main__":
    main()
