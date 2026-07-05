"""Readiness check -- can daedalus actually offload real work right now?

Answers the honest question: is the local bench able to execute, or does
everything still fall back to Claude? Probes are read-only (a localhost HTTP
GET + PATH lookups); nothing is started or installed.
"""

from __future__ import annotations

import json
import os
import shutil
import urllib.error
import urllib.request

from .providers.ollama import DEFAULT_HOST, DEFAULT_MODEL


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


def main() -> None:
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
    print()
    if r["can_offload_local"]:
        print("READY: the local bench can execute. offload/ikarus with --live will run for real.")
    else:
        print("NOT READY: local bench can't execute yet -- everything falls back to Claude (Adam).")


if __name__ == "__main__":
    main()
