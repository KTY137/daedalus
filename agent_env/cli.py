"""Unified `agentenv` command -- one entry point for the whole harness.

    agentenv doctor                     is the bench ready? (Ollama/model/claude)
    agentenv offload "<objective>" ...  route ONE task; run on the bench (--live)
    agentenv spawn "<objective>" ...    decompose ONE objective; plan/dispatch bench
    agentenv ikarus                     spawn plan for the demo tasks
    agentenv metrics                    offload metrics / silent-escalation alarm
    agentenv benchmark                  projected token/cost picture
    agentenv status                     local bridge status
    agentenv init [repo]                scaffold .agentenv/agentenv.json (enables writes)
"""

from __future__ import annotations

import sys

_USAGE = __doc__


def _spawn(argv: list[str]) -> None:
    """Decompose one objective into subtasks and plan (default) or dispatch
    (--live) them across the local bench via Ikarus."""
    import argparse
    import json
    from .ikarus import Ikarus
    from .projects import resolve_repo_root

    parser = argparse.ArgumentParser(
        prog="agentenv spawn",
        description="Decompose an objective and spawn the local bench (plan, or --live).")
    parser.add_argument("objective")
    parser.add_argument("--repo-root")
    parser.add_argument("--project")
    parser.add_argument("--live", action="store_true",
                        help="actually dispatch the accepted subtasks (default: plan only)")
    args = parser.parse_args(argv)

    repo_root = resolve_repo_root(args.repo_root, args.project)
    ikarus = Ikarus(project=args.project)
    result = ikarus.spawn(args.objective, repo_root, dry_run=not args.live)
    print(json.dumps(result, indent=2, default=str))


def _init(argv: list[str]) -> None:
    from pathlib import Path
    from .config import init_repo
    repo = str(Path(argv[0]).resolve()) if argv else str(Path.cwd())
    path = init_repo(repo)
    print(f"wrote {path}\n"
          "Edit the 'policy' block to declare what the local bench may/te may not write, "
          "then run:  agentenv doctor")


def main() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(_USAGE)
        return
    cmd, rest = argv[0], argv[1:]
    sys.argv = [f"agentenv {cmd}", *rest]   # so sub-parsers see a clean argv

    if cmd == "doctor":
        from .doctor import main as m; m()
    elif cmd == "offload":
        from .offload import main as m; m()
    elif cmd == "spawn":
        _spawn(rest)
    elif cmd == "ikarus":
        from .ikarus import main as m; m()
    elif cmd == "metrics":
        from .metrics import main as m; m()
    elif cmd == "benchmark":
        from .benchmark import main as m; m()
    elif cmd == "status":
        from .status import main as m; m()
    elif cmd == "init":
        _init(rest)
    else:
        print(f"unknown command '{cmd}'\n")
        print(_USAGE)


if __name__ == "__main__":
    main()
