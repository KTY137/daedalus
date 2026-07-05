"""Unified `agentenv` command -- one entry point for the whole harness.

    agentenv doctor                     is the bench ready? (Ollama/model/claude)
    agentenv offload "<objective>" ...  route ONE task; run on the bench (--live)
    agentenv ikarus                     spawn plan for the demo tasks
    agentenv metrics                    offload metrics / silent-escalation alarm
    agentenv benchmark                  projected token/cost picture
    agentenv status                     local bridge status
    agentenv init [repo]                scaffold .agentenv/agentenv.json (enables writes)
"""

from __future__ import annotations

import sys

_USAGE = __doc__


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
