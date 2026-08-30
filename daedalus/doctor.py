# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Readiness check -- can daedalus actually offload real work right now?

Answers the honest question: is the local bench able to execute, or does
everything still fall back to Claude? Probes are read-only (a localhost HTTP
GET + PATH lookups); nothing is started or installed.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request

from .providers.ollama import DEFAULT_HOST, DEFAULT_MODEL


def codex_status() -> dict:
    """Presence/version/auth of the OpenAI Codex CLI. All probes are cheap and
    non-interactive: PATH lookup, ``codex --version``, and ``codex login status``
    (documented subcommand; exit 0 = logged in). Nothing here ever triggers a
    login flow or a model call."""
    # Use the resolved path: npm ships `codex` as a .CMD shim on Windows and
    # subprocess cannot spawn it by bare name (WinError 2).
    # A FIRING GUARD MUST NOT KILL THE DIAGNOSTIC. The spend ceiling wraps
    # subprocess.run and raises BudgetRefused -- which is neither OSError nor
    # SubprocessError, so it escaped both handlers below and `daedalus doctor`
    # died on a traceback the moment the ceiling was reached. Measured at
    # ceiling=$5.00 spent=$5.00: doctor exited 1 mid-report.
    #
    # `refused` is its OWN state, deliberately not folded into present=False.
    # "codex is not installed" and "I was not allowed to ask" are different
    # facts, and a doctor that reports the second as the first sends the
    # operator to reinstall a CLI that is sitting right there.
    from .budget import BudgetRefused

    codex = shutil.which("codex")
    version: str | None = None
    logged_in: bool | None = None
    refused: str | None = None
    if codex:
        try:
            v = subprocess.run([codex, "--version"], capture_output=True,
                               text=True, timeout=10, check=False)
            if v.returncode == 0:
                version = v.stdout.strip() or None
        except BudgetRefused as exc:
            refused = str(exc).split("\n")[0]
        except (OSError, subprocess.SubprocessError):
            version = None
        if refused is None:
            try:
                s = subprocess.run([codex, "login", "status"], capture_output=True,
                                   text=True, timeout=10, check=False)
                logged_in = s.returncode == 0
            except BudgetRefused as exc:
                refused = str(exc).split("\n")[0]
            except (OSError, subprocess.SubprocessError):
                logged_in = None
    return {"present": codex is not None, "version": version,
            "logged_in": logged_in, "refused": refused}


def _ollama_models(host: str) -> list[str] | None:
    """Return the list of pulled model tags, or None if the server is down."""
    try:
        with urllib.request.urlopen(host.rstrip("/") + "/api/tags", timeout=3) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return [m.get("model") or m.get("name") for m in data.get("models", [])]
    except (urllib.error.URLError, OSError, json.JSONDecodeError, ValueError):
        return None


def check() -> dict:
    host = os.environ.get("OLLAMA_HOST", DEFAULT_HOST)
    want = os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)
    models = _ollama_models(host)
    up = models is not None
    stem = want.split(":")[0]
    model_ok = up and any(stem in (m or "") for m in models)
    return {
        "claude_cli": shutil.which("claude") is not None,
        # PATH-presence only (cheap: check() runs on every bridge dispatch);
        # version/auth details live in codex_status() for the human doctor.
        "codex_cli": shutil.which("codex") is not None,
        "ollama_up": up,
        "ollama_host": host,
        "ollama_model_wanted": want,
        "ollama_models": models or [],
        "ollama_model_present": model_ok,
        "deepseek_key": bool(os.environ.get("DEEPSEEK_API_KEY")),
        "can_offload_local": model_ok,
    }


def _m(ok: bool) -> str:
    return "OK" if ok else "--"


def _print_watcher_heartbeat() -> None:
    """WARN when the file-bridge watcher heartbeat is stale/missing -- the
    watcher dies with the orchestrator session and nothing else notices."""
    from .file_bridge import STALE_AFTER_S, heartbeat_status

    hb = heartbeat_status()
    state = hb["state"]
    if state == "alive":
        who = f"pid {hb.get('pid')}, project {hb.get('project') or '?'}"
        print(f"[OK] bridge watcher heartbeat   ({hb['age_s']}s ago; {who})")
    elif state == "busy":
        cur = (hb.get("current") or {}).get("file", "?")
        print(f"[OK] bridge watcher busy        (on {cur} for {hb.get('busy_for_s')}s)")
    elif state == "wedged":
        cur = (hb.get("current") or {}).get("file", "?")
        print(f"[!!] bridge watcher WEDGED?     (on {cur} for {hb.get('busy_for_s')}s "
              "> task budget)")
        print(f"     -> investigate the task, then restart:  {hb['restart']}")
    elif state == "stale":
        print(f"[!!] bridge watcher heartbeat STALE ({hb['age_s']}s ago > "
              f"{STALE_AFTER_S:.0f}s) -- the watcher is dead; queued tasks will sit.")
        print(f"     -> restart it:  {hb['restart']}")
    else:  # none
        print("[--] bridge watcher heartbeat   none recorded (watcher not running, "
              "or started before heartbeats landed)")
        print(f"     -> if it should be running:  {hb['restart']}")
        print("     (cross-check running processes:  python -m daedalus.cli "
              "watcher status --project <project>)")


def main() -> None:
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "cli.doctor",
        REGISTRY_BY_ID["cli.doctor"].effects,
        (process_guard_boundary_decision(),),
    )
    r = check()
    print("daedalus doctor -- can we offload real work?\n")
    print(f"[{_m(r['claude_cli'])}] claude CLI on PATH          (senior lane)")
    print(f"[{_m(r['ollama_up'])}] Ollama server reachable     {r['ollama_host']}")
    if r["ollama_up"]:
        print(f"[{_m(r['ollama_model_present'])}] model '{r['ollama_model_wanted']}' pulled")
        if not r["ollama_model_present"]:
            print(f"     -> run:  ollama pull {r['ollama_model_wanted']}")
            if r["ollama_models"]:
                print(f"     (present: {', '.join(r['ollama_models'])})")
    else:
        print(f"     -> start it:  ollama serve   then  ollama pull {r['ollama_model_wanted']}")
    print(f"[{_m(r['deepseek_key'])}] DEEPSEEK_API_KEY set        (optional external lane)")
    cx = codex_status()
    detail = cx["version"] or "on PATH"
    print(f"[{_m(cx['present'])}] codex CLI                   "
          f"({detail}; external lane, egress-gated)")
    if cx.get("refused"):
        # NOT an error line. The ceiling doing its job is a healthy system, and
        # the operator needs to read it as "I did not ask" rather than as a
        # broken CLI or an unknown auth state.
        print(f"     probe refused by the spend ceiling -- version/auth NOT measured")
        print(f"     {cx['refused']}")
    elif cx["present"]:
        if cx["logged_in"] is True:
            print("     auth: logged in (codex login status)")
        elif cx["logged_in"] is False:
            print("     -> not logged in: run  codex login")
        else:
            print("     auth: unknown (codex login status did not answer)")
    _print_watcher_heartbeat()
    print()
    if r["can_offload_local"]:
        print("READY: the local bench can execute. offload/ikarus with --live will run for real.")
    else:
        print("NOT READY: local bench can't execute yet -- everything falls back to Claude (Adam).")


if __name__ == "__main__":
    main()
