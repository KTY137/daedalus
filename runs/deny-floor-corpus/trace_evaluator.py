"""Record every file the ATTEMPT GATE's evaluator process opens or imports.

Resolved by execution, never by reading imports off a page: the gate is
`python -m pytest -p no:cacheprovider -q --no-header tests/test_event_field.py`
with cwd set to the candidate worktree (daedalus/ignition/checks.py:pytest_check).
This runs that exact argv under an audit hook and writes what it touched.
"""
import json
import os
import runpy
import sys

RECORD = os.environ["DENY_FLOOR_RECORD"]
seen = {"open": set(), "import": set(), "exec": set()}


def _hook(event, args):
    try:
        if event == "open" and args and isinstance(args[0], (str, bytes, os.PathLike)):
            seen["open"].add(os.fspath(args[0]))
        elif event == "import" and args:
            seen["import"].add(str(args[0]))
        elif event == "exec":
            pass
    except Exception:
        pass


sys.addaudithook(_hook)
sys.argv = ["pytest", "-p", "no:cacheprovider", "-q", "--no-header",
            "tests/test_event_field.py"]
code = 0
try:
    runpy.run_module("pytest", run_name="__main__", alter_sys=True)
except SystemExit as exc:
    code = exc.code
finally:
    files = {m.__file__ for m in list(sys.modules.values())
             if getattr(m, "__file__", None)}
    with open(RECORD, "w", encoding="utf-8") as fh:
        json.dump({"exit": code,
                   "opened": sorted(seen["open"]),
                   "module_files": sorted(files)}, fh, indent=1)
