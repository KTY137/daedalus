"""Escalation metering -- the silent-escalation alarm.

The most load-bearing practitioner warning (docs/IMPROVEMENTS_RESEARCH.md): a
broken verifier can quietly route ~90% of traffic to the expensive model with no
error and no alert, and the savings vanish unnoticed. So we count every routing
outcome and surface the fallback rate. If offloadable work keeps falling back to
Claude, you get told.

Append-only JSONL, ignored by Git (lives under memory/).
"""

from __future__ import annotations

import argparse
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

# Serializes the append below so parallel dispatch can't interleave two rows
# into one corrupt line (Windows append is not guaranteed atomic).
_WRITE_LOCK = threading.Lock()

ROOT = Path(__file__).resolve().parents[1]
LOG = ROOT / "memory" / "offload_metrics.local.jsonl"
ALARM_FALLBACK_RATE = 0.5  # >50% of offloadable work falling back -> something's wrong


def record(*, provider: str, action: str, owner: str = "", risk: str = "",
           eligible: bool = True, note: str = "") -> None:
    """Log one routing outcome. `eligible` = the task *could* have been offloaded
    (a delegable, low/mid-risk task); `action` in
    {offloaded, escalate_to_claude, escalated_after_verify_fail, would_offload}."""
    LOG.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "provider": provider, "action": action, "owner": owner,
        "risk": risk, "eligible": eligible, "note": note[:200],
    }
    with _WRITE_LOCK, LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def _load() -> list[dict]:
    if not LOG.exists():
        return []
    out = []
    for line in LOG.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def summary() -> dict:
    rows = _load()
    eligible = [r for r in rows if r.get("eligible")]
    offloaded = [r for r in eligible if r.get("action") == "offloaded"]
    fell_back = [r for r in eligible if r.get("action", "").startswith("escalate")]
    n = len(eligible)
    rate = (len(fell_back) / n) if n else 0.0
    return {
        "total": len(rows),
        "offloadable": n,
        "offloaded": len(offloaded),
        "fell_back_to_claude": len(fell_back),
        "fallback_rate": round(rate, 3),
        "alarm": n >= 5 and rate > ALARM_FALLBACK_RATE,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Offload metrics / silent-escalation alarm.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    s = summary()
    if args.json:
        print(json.dumps(s, indent=2))
        return
    print("offload metrics\n")
    print(f"  offloadable tasks : {s['offloadable']}")
    print(f"  ran on the bench  : {s['offloaded']}")
    print(f"  fell back to Claude: {s['fell_back_to_claude']}")
    print(f"  fallback rate     : {s['fallback_rate']:.0%}")
    if s["alarm"]:
        print("\n  ALARM: most offloadable work is escalating to Claude -- check the bench / verifier.")
    elif s["offloadable"] == 0:
        print("\n  (no offloadable tasks recorded yet)")
    elif s["offloadable"] < 5:
        print(f"\n  (warming up -- only {s['offloadable']} sample(s); alarm needs 5+)")
    elif s["fallback_rate"] > ALARM_FALLBACK_RATE:
        print("\n  ALARM: fallback rate is high -- check the bench / verifier.")
    else:
        print("\n  OK: the bench is carrying its share.")


if __name__ == "__main__":
    main()
