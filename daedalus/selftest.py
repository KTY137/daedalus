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
# NOT `import shutil`. The one recursive delete this module had -- the scratch
# repo a LIVE model has just written into -- goes through
# `remove_tree_no_follow`. Keeping the import out means re-introducing
# `shutil.rmtree` costs a visible line in the diff instead of passing as an
# ordinary use of something already imported. Same discipline as
# daedalus/spine/attempt.py, which removed exactly this pattern one file over.
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

# FORCE THE LOCAL LANE. This command's entire reason to exist is proving the
# LOCAL Ollama write round-trip -- if offload() is left free to route (its
# default), an external key present in the environment wins the router's
# normal cost-ordered preference (provider_router.select_provider tries
# DeepSeek before Ollama at equal risk), and DeepSeek is ADVISORY BY DESIGN
# (untrusted lane, never writes). MEASURED: with a DeepSeek key set, this used
# to route provider=deepseek, its own "mode is write" check FAILED,
# before_bytes == after_bytes, and the command still printed a result as if
# it had exercised the thing it is named for. Passing an explicit
# availability dict with every lane but ollama forced off makes offload()'s
# own routing (unchanged here) land on ollama or fail outright -- it can no
# longer silently substitute a different lane.
_LOCAL_ONLY_AVAILABILITY = {"claude_cli": False, "ollama": True,
                            "deepseek": False, "codex_cli": False}


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


def _remove_selftest_repo(repo: Path) -> str | None:
    """Delete the scratch repo through the GUARDED walker.

    Returns ``None`` on success, or a one-line report of what stopped it.

    This was ``shutil.rmtree(repo, ignore_errors=True)`` in a ``finally:``, and
    it is the same pattern the security round removed from
    :mod:`daedalus.spine.attempt` one file over. Both halves of it were wrong
    here for the same reasons they were wrong there:

    1. ``ignore_errors=True`` is a SILENT delete failure inside a ``finally:``.
       A selftest whose whole job is to report honestly on a live round trip
       must not be the thing that swallows a failed delete.
    2. ``repo`` is a ``%TEMP%/daedalus-selftest-*`` directory that a LIVE MODEL
       has just written into, under this user's privileges, with a public
       prefix. That is precisely a directory candidate-authored content could
       have reached. ``shutil.rmtree`` is not safe against a reparse point
       renamed in mid-walk on Windows -- ``os.path.islink`` does not even see a
       ``mklink /J`` junction (measured: ``islink=False``, reparse tag
       ``0xa0000003``) -- so the walker that re-lstats every component is the
       one that has to do this.

    The model here is far less adversarial than a candidate patch: it is a
    small local model writing one greeting function. That is a reason the
    window is narrow, not a reason to leave an unguarded recursive delete in a
    ``finally:``, because "the model probably behaved" is not a property this
    module can check.
    """
    from .kairos.worktree import remove_tree_no_follow

    try:
        remove_tree_no_follow(repo)
        return None
    except Exception as e:                      # noqa: BLE001 - reported, not raised
        return (f"selftest scratch repo {repo} was NOT removed: "
                f"{type(e).__name__}: {e}")


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
    # Bound BEFORE the try: the finally below attaches a cleanup report to it,
    # and an exception raised before the assignment would otherwise turn a
    # round-trip failure into a NameError in the cleanup handler -- hiding the
    # real error behind the bookkeeping for it.
    result: dict | None = None
    try:
        target = Path(repo) / _FILE
        before = target.read_text(encoding="utf-8")
        t0 = time.time()
        res = offload(_OBJECTIVE, repo, [_FILE], live=True,
                      availability=_LOCAL_ONLY_AVAILABILITY)
        dt = round(time.time() - t0, 1)
        after = target.read_text(encoding="utf-8")

        # FAIL LOUD, never silently substitute. `doctor` just said the local
        # bench was ready and every other lane was forced off above, so a
        # decision that still isn't "ollama" means either the bench went down
        # in the gap between that check and this call, or the router did not
        # honor the forced availability (a router bug) -- either way the
        # LOCAL write round-trip this command exists to prove was NOT
        # exercised. Returning here instead of falling into the checks list
        # below matters: an unrelated entry ("mode is write") would go red
        # for a reason that does not name the real problem, and the old
        # lenient "routed to a free lane" check (the historic bug this
        # replaces) would have let this pass outright.
        if res.get("provider") != "ollama":
            result = {
                "ok": False, "skipped": False, "routing_failed": True,
                "seconds": dt, "provider": res.get("provider"), "action": res.get("action"),
                "reason": (
                    f"local lane forced (deepseek/codex_cli/claude_cli disabled) but routing "
                    f"produced provider={res.get('provider')!r} action={res.get('action')!r} -- "
                    "the local Ollama write round-trip was NOT exercised. `daedalus doctor` "
                    "reported the bench ready; either it went down between that check and this "
                    "call, or the router did not honor the forced availability."),
                "before_bytes": len(before), "after_bytes": len(after),
            }
            return result

        checks = [
            ("routed to local Ollama", res.get("provider") == "ollama"),
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
        cleanup_error = _remove_selftest_repo(Path(repo))
        if cleanup_error and isinstance(result, dict):
            # Reported, never swallowed: a delete this module could not
            # complete is a finding about the box, and a selftest that hides
            # one is lying about the thing it exists to check.
            result["cleanup_error"] = cleanup_error


def _emit(result: dict, json_out: bool) -> None:
    if json_out:
        print(json.dumps(result, indent=2))
        return
    if result.get("skipped"):
        print(f"SELFTEST SKIPPED: {result['reason']}")
        return
    print(f"daedalus live selftest -- real Ollama write round-trip\n{'=' * 52}")
    if result.get("routing_failed"):
        # Loud and distinct on purpose -- see the comment at the call site in
        # run(). Does not assume "checks"/"wrote" exist: this shape is
        # returned before either is computed.
        print(f"provider={result['provider']}  action={result['action']}  ({result['seconds']}s)")
        print(f"{'=' * 52}\nVERDICT: FAIL -- local lane not exercised\n  {result['reason']}")
        return
    mark = "PASS" if result["ok"] else "FAIL"
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
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "cli.selftest",
        REGISTRY_BY_ID["cli.selftest"].effects,
        (process_guard_boundary_decision(),),
    )
    res = run()
    _emit(res, args.json)
    raise SystemExit(0 if (res["ok"] or res.get("skipped")) else 1)


if __name__ == "__main__":
    main()
