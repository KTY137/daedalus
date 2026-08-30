# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""One door for an external model call, usable from a process that has no daedalus.

WHY A PROCESS AND NOT AN IMPORT
-------------------------------
A prompt optimiser (DSPy and its kin) reaches its model through ``litellm``,
which pulls ``openai``, ``aiohttp`` and twenty-six other packages. Installing
that beside the guarded lanes puts a second, unbudgeted, unfenced way to spend
money and send bytes into the same interpreter as the first one -- after which
"all spend goes through the budget ledger" is a convention rather than a fact,
and any code in the tree can quietly stop obeying it.

So the optimiser gets its own environment and reaches DeepSeek through this
script instead. The boundary is then a PROCESS boundary: the other side cannot
import its way around the guard, because the guard is not in its interpreter.

That is the same claim the master plan's invariant 8 makes about effects
generally -- bounded at the effect boundary, not entrusted to whoever is
calling. This file is that claim applied to one concrete case, and it is worth
noticing that the cheapest way to violate it was a `pip install`.

WHAT IT DOES NOT DO
-------------------
It is not a sandbox. A caller on this machine can still run python and import
whatever it likes; what this prevents is the guarded environment ACQUIRING a
second egress path as a side effect of installing a research tool. That is a
real and narrow guarantee, and stating it as a bigger one would be the sort of
claim section 4 forbids.

PROTOCOL
--------
stdin  {"objective": str, "system": str|null, "temperature": float,
        "model": str|null, "timeout_s": int}
stdout {"ok": bool, "report": {...}|null, "error": str|null,
        "sent": {...}}          -- always valid json, always exit 0 on a
                                   refusal, so the caller can distinguish a
                                   policy decision from a crash
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    try:
        request = json.load(sys.stdin)
    except (ValueError, OSError) as exc:
        json.dump({"ok": False, "report": None,
                   "error": f"unreadable request: {exc}", "sent": {}},
                  sys.stdout)
        return 0

    objective = str(request.get("objective") or "")
    if not objective.strip():
        json.dump({"ok": False, "report": None,
                   "error": "empty objective", "sent": {}}, sys.stdout)
        return 0

    from daedalus.env import load_env
    load_env()

    # Canonical Gate-0 effect start. The budget decision installs the real
    # in-process spend net; the egress decision runs the secret floor over
    # the only outbound payload this door sends. A boundary refusal follows
    # this door's protocol: valid JSON, exit 0, so the caller can tell a
    # policy decision from a crash.
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.sensitivity import secret_floor_rule
    from daedalus.spine.effect_boundary import (
        REGISTRY_BY_ID,
        EffectBoundaryError,
        GuardDecision,
        begin_effect,
    )

    outbound = objective + "\n" + str(request.get("system") or "")
    floor_hit = secret_floor_rule("guarded_call.stdin", outbound)
    egress_decision = GuardDecision(
        "provider.egress_policy",
        floor_hit is None,
        f"secret-floor over outbound payload: {floor_hit or 'clean'}",
    )
    try:
        begin_effect(
            "tools.guarded_call",
            REGISTRY_BY_ID["tools.guarded_call"].effects,
            (process_guard_boundary_decision(), egress_decision),
        )
    except EffectBoundaryError as exc:
        json.dump({"ok": False, "report": None,
                   "error": f"effect boundary refused: {exc}", "sent": {}},
                  sys.stdout)
        return 0

    # Imported here, after the request parses: a malformed call should not pay
    # the cost of loading the provider stack, and a missing key should be
    # reported as a refusal rather than an import error.
    from daedalus.providers.deepseek import DeepSeekProvider

    provider = DeepSeekProvider()
    try:
        out = provider.run(
            objective=objective,
            repo_root=str(Path(__file__).resolve().parents[1]),
            paths=[],                       # never re-read files; see funnel.py
            agent={"name": request.get("agent") or "guarded-call"},
            model=request.get("model"),
            timeout_s=int(request.get("timeout_s") or 300),
            system_override=request.get("system"),
            temperature=float(request.get("temperature") or 0.0),
            writable=False,                 # advisory, structurally
        )
    except Exception as exc:                # noqa: BLE001 -- report, never raise
        # A refusal (budget, secret floor) and a transport failure both arrive
        # here. The caller needs to tell them apart, and the message is the
        # only thing that can, so it is passed through whole.
        json.dump({"ok": False, "report": None,
                   "error": f"{type(exc).__name__}: {exc}", "sent": {}},
                  sys.stdout)
        return 0

    report = out.get("report") or {}
    blocked = str(report.get("status", "")) == "blocked"
    json.dump({
        "ok": not blocked,
        "report": report,
        "error": report.get("summary") if blocked else None,
        "sent": {
            "objective_chars": len(objective),
            "temperature": float(request.get("temperature") or 0.0),
            "model": request.get("model") or "",
            "system_chars": len(request.get("system") or ""),
        },
    }, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
