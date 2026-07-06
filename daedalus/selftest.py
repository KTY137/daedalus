"""Live self-test -- a REAL Ollama round-trip, repeatable, separate from the
unit suite.

Why not put real Ollama in the unit tests? Those must be fast, deterministic and
always-green; a live model is slow, non-deterministic (you can't assert exact
text) and env-dependent (Ollama off -> weather-dependent skips). So the split is:

  * unit tests (mocked)  -> the MECHANICS: routing, gates, rollback, attribution.
  * `daedalus selftest`  -> the CAPABILITY: can the real bench actually write a
                            file and clear the verifier gate, end to end?

This builds a throwaway repo, runs ONE live scoped write through the full
offload cascade, and asserts only model-AGNOSTIC facts (a real byte change on
disk, the file still compiles, the verifier accepted, zero Claude tokens). It
cleans up after itself. Skips cleanly (not fails) when the bench isn't ready.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from pathlib import Path

_AGENT = {
    "name": "greeter", "call_name": "Hey", "model_tier": "haiku",
    "external_ok": True, "owns": ["src/"], "triggers": ["docstring", "greeting", "greet"],
    "must_read": [], "output_schema": "agent_report_v1", "category": "docs",
}
_POLICY = '{"policy": {"default_deny": true, "allow": ["src/", ".md"]}}'
_FILE = "src/hello.py"
_SEED = "def greet(name):\n    return 'hi ' + name\n"
_OBJECTIVE = "Add a one-line docstring to the greet function; keep the code identical."


def _build_repo() -> str:
    tmp = tempfile.mkdtemp(prefix="daedalus-selftest-")
    cfg = Path(tmp) / ".agentenv"
    (cfg / "agents").mkdir(parents=True)
    (cfg / "agentenv.json").write_text(_POLICY, encoding="utf-8")
    (cfg / "agents" / "greeter.json").write_text(json.dumps(_AGENT), encoding="utf-8")
    p = Path(tmp) / _FILE
    p.parent.mkdir(parents=True)
    p.write_text(_SEED, encoding="utf-8", newline="\n")
    return tmp


def _compiles(path: Path) -> bool:
    import py_compile
    try:
        py_compile.compile(str(path), doraise=True)
        return True
    except py_compile.PyCompileError:
        return False


def run() -> dict:
    """Run the live round-trip and RETURN the result dict (silent -- the CLI
    layer prints). Unit tests call this directly without console noise."""
    from .doctor import check
    ready = check()
    if not ready.get("can_offload_local"):
        return {"ok": False, "skipped": True,
                "reason": "local bench not ready (start Ollama + pull the model; `daedalus doctor`)"}

    from .offload import offload
    repo = _build_repo()
    try:
        target = Path(repo) / _FILE
        before = target.read_text(encoding="utf-8")
        t0 = time.time()
        res = offload(_OBJECTIVE, repo, [_FILE], live=True)
        dt = round(time.time() - t0, 1)
        after = target.read_text(encoding="utf-8")

        checks = [
            ("routed to a free lane", res.get("provider") in ("ollama", "deepseek")),
            ("mode is write", res.get("mode") == "write"),
            ("accepted (offloaded)", res.get("action") == "offloaded"),
            ("verifier passed", bool((res.get("verify") or {}).get("ok"))),
            ("file changed on disk", before != after),
            ("wrote is ground-truth", res.get("wrote") == [_FILE.replace("\\", "/")]),
            ("result still compiles", _compiles(target)),
            ("zero Claude tokens", res.get("action") == "offloaded"),
        ]
        ok = all(v for _, v in checks)
        result = {
            "ok": ok, "skipped": False, "seconds": dt,
            "model": res.get("persona"), "provider": res.get("provider"),
            "action": res.get("action"), "wrote": res.get("wrote"),
            "checks": [{"name": n, "ok": v} for n, v in checks],
            "before_bytes": len(before), "after_bytes": len(after),
        }
        return result
    finally:
        shutil.rmtree(repo, ignore_errors=True)


def _emit(result: dict, json_out: bool) -> None:
    if json_out:
        print(json.dumps(result, indent=2))
        return
    if result.get("skipped"):
        print(f"SELFTEST SKIPPED: {result['reason']}")
        return
    mark = "PASS" if result["ok"] else "FAIL"
    print(f"daedalus live selftest -- real Ollama write round-trip\n{'=' * 52}")
    print(f"provider={result['provider']}  action={result['action']}  "
          f"wrote={result['wrote']}  ({result['seconds']}s)")
    for c in result["checks"]:
        print(f"  [{'OK' if c['ok'] else 'XX'}] {c['name']}")
    print(f"{'=' * 52}\nVERDICT: {mark}  "
          f"({result['before_bytes']} -> {result['after_bytes']} bytes on disk)")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="daedalus selftest",
                                description="Live Ollama write round-trip (real, repeatable).")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    res = run()
    _emit(res, args.json)
    raise SystemExit(0 if (res["ok"] or res.get("skipped")) else 1)


if __name__ == "__main__":
    main()
