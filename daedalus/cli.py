"""Unified `daedalus` command -- one entry point for the whole harness.

    daedalus doctor                     is the bench ready? (Ollama/model/claude)
    daedalus offload "<objective>" ...  route ONE task; run on the bench (--live)
    daedalus spawn "<objective>" ...    decompose ONE objective; plan/dispatch bench
    daedalus build "<feature>" --project X   plan a multi-wave, frontier-first build
    daedalus ikarus                     spawn plan for the demo tasks
    daedalus metrics                    offload metrics / silent-escalation alarm
    daedalus benchmark                  projected token/cost picture
    daedalus status                     local bridge status
    daedalus dashboard --project NAME --json
    daedalus models --json
    daedalus squads --project NAME --json
    daedalus watcher status --project NAME --json
    daedalus review-diff --project NAME --lane local_only
    daedalus projects                   list registered projects
    daedalus agents list|show|add|edit|rm   manage agent-role definitions at runtime
    daedalus categories list|show|set   manage role-category presets (icon/color/lane/tier)
    daedalus claude-crew --project NAME     detect Claude Code subagents in .claude/agents/
    daedalus web                         run the local Agent OS web API/app
    daedalus enforce                    add/update Codex/Claude harness instructions
    daedalus init [repo]                scaffold .agentenv/agentenv.json (enables writes)
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
        prog="daedalus spawn",
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


def _build(argv: list[str]) -> None:
    """Plan a multi-wave build for one feature objective: decompose it, route
    each subtask to its owner, assign a frontier builder (Claude) or the local
    bench off the category lane, and group into bounded waves. Plan only for
    now -- persists a session snapshot under runs/build/."""
    import argparse
    import json
    from .build import plan_build
    from .projects import resolve_repo_root

    parser = argparse.ArgumentParser(
        prog="daedalus build",
        description="Plan a multi-wave, frontier-first build for one feature (plan only).")
    parser.add_argument("feature")
    parser.add_argument("--repo-root")
    parser.add_argument("--project")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo_root = resolve_repo_root(args.repo_root, args.project)
    session = plan_build(args.feature, repo_root, project=args.project)

    if args.json:
        print(json.dumps(session.to_dict(), indent=2))
        return

    summary = session.summary()
    print(f"BUILD PLAN  {session.feature!r}")
    print(f"  {summary['subtasks']} subtask(s) across {summary['waves']} wave(s) "
          f"(<= {session.max_workers}/wave); "
          f"{summary['frontier']} frontier, {summary['local']} local bench.")
    if session.snapshot_path:
        print(f"  snapshot: {session.snapshot_path}")
    for wave in session.waves:
        print(f"\nwave {wave.index}")
        print(f"  {'objective':<38}{'owner':<16}{'category':<16}{'builder':<10}{'lane/tier'}")
        print("  " + "-" * 92)
        for t in wave.tasks:
            builder = f"{t.builder}{'*' if t.frontier else ''}"
            print(f"  {t.objective[:37]:<38}{t.agent[:15]:<16}{t.category[:15]:<16}"
                  f"{builder:<10}{t.lane}/{t.tier}")
    print("\n(* = frontier builder lane)")


def _init(argv: list[str]) -> None:
    from pathlib import Path
    from .config import init_repo
    repo = str(Path(argv[0]).resolve()) if argv else str(Path.cwd())
    path = init_repo(repo)
    print(f"wrote {path}\n"
          "Edit the 'policy' block to declare what the local bench may/te may not write, "
          "then run:  daedalus doctor")


def _projects(argv: list[str]) -> None:
    from .projects import list_projects
    projects = list_projects()
    if not projects:
        print("no registered projects")
        return
    for name in projects:
        print(name)


def _agents(argv: list[str]) -> None:
    """Create / list / edit / delete agent-role definitions at runtime -- the
    roles Ikarus routes to. With --repo-root/--project, writes a per-repo
    override under .agentenv/agents/; otherwise the built-in global agents/."""
    import argparse
    import json
    from . import agents_registry as reg
    from .projects import resolve_repo_root

    parser = argparse.ArgumentParser(
        prog="daedalus agents",
        description="Manage agent-role definitions (the roles Ikarus routes to).")
    sub = parser.add_subparsers(dest="action", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--repo-root")
        p.add_argument("--project")

    lp = sub.add_parser("list"); common(lp); lp.add_argument("--json", action="store_true")
    sp = sub.add_parser("show"); sp.add_argument("name"); common(sp)

    ap = sub.add_parser("add"); ap.add_argument("name"); common(ap)
    ap.add_argument("--call-name", default="")
    ap.add_argument("--model-tier", default="sonnet", choices=list(reg.MODEL_TIERS))
    ap.add_argument("--external-ok", action="store_true")
    ap.add_argument("--owns", default="")
    ap.add_argument("--triggers", default="")
    ap.add_argument("--must-read", default="")
    ap.add_argument("--output-schema", default="agent_report_v1")
    ap.add_argument("--category", default="")
    ap.add_argument("--overwrite", action="store_true")

    ep = sub.add_parser("edit"); ep.add_argument("name"); common(ep)
    ep.add_argument("--call-name")
    ep.add_argument("--model-tier", choices=list(reg.MODEL_TIERS))
    ep.add_argument("--external-ok", dest="external_ok", action="store_const", const=True, default=None)
    ep.add_argument("--no-external-ok", dest="external_ok", action="store_const", const=False)
    ep.add_argument("--owns")
    ep.add_argument("--triggers")
    ep.add_argument("--must-read")
    ep.add_argument("--output-schema")
    ep.add_argument("--category")

    rp = sub.add_parser("rm"); rp.add_argument("name"); common(rp)

    args = parser.parse_args(argv)
    repo_root = resolve_repo_root(args.repo_root, args.project) if (args.repo_root or args.project) else None
    split = lambda s: [x.strip() for x in s.split(",") if x.strip()]

    if args.action == "list":
        roles = reg.list_roles(repo_root)
        if args.json:
            print(json.dumps(roles, indent=2))
        else:
            for r in roles:
                tag = "external" if r.get("external_ok") else "local-only"
                print(f"{r.get('name')}\t{r.get('call_name', '')}\t{r.get('model_tier', '')}\t{tag}")
    elif args.action == "show":
        role = reg.get_role(args.name, repo_root)
        print(json.dumps(role, indent=2) if role else f"unknown agent '{args.name}'")
    elif args.action == "add":
        spec = {
            "name": args.name, "call_name": args.call_name, "model_tier": args.model_tier,
            "external_ok": args.external_ok, "owns": split(args.owns), "triggers": split(args.triggers),
            "must_read": split(args.must_read), "output_schema": args.output_schema,
            "category": args.category,
        }
        try:
            print(f"wrote {reg.create_role(spec, repo_root, overwrite=args.overwrite)}")
        except (ValueError, FileExistsError) as exc:
            print(f"error: {exc}")
    elif args.action == "edit":
        patch: dict = {}
        if args.call_name is not None: patch["call_name"] = args.call_name
        if args.model_tier is not None: patch["model_tier"] = args.model_tier
        if args.external_ok is not None: patch["external_ok"] = args.external_ok
        if args.owns is not None: patch["owns"] = split(args.owns)
        if args.triggers is not None: patch["triggers"] = split(args.triggers)
        if args.must_read is not None: patch["must_read"] = split(args.must_read)
        if args.output_schema is not None: patch["output_schema"] = args.output_schema
        if args.category is not None: patch["category"] = args.category
        try:
            print(f"wrote {reg.update_role(args.name, patch, repo_root)}")
        except (ValueError, KeyError) as exc:
            print(f"error: {exc}")
    elif args.action == "rm":
        ok = reg.delete_role(args.name, repo_root)
        print(f"removed {args.name}" if ok else f"no writable role '{args.name}' to remove")


def _categories(argv: list[str]) -> None:
    """List / show / recolor role categories -- the icon/color/lane/tier
    presets that group agent roles for the UI. With --repo-root/--project,
    `set` writes a per-repo override under .agentenv/categories.json;
    otherwise the built-in global agents/categories.json."""
    import argparse
    import json
    from . import categories as cats
    from .projects import resolve_repo_root

    parser = argparse.ArgumentParser(
        prog="daedalus categories",
        description="Manage role-category presets (icon/color/lane/tier).")
    sub = parser.add_subparsers(dest="action", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--repo-root")
        p.add_argument("--project")

    lp = sub.add_parser("list"); common(lp); lp.add_argument("--json", action="store_true")
    sp = sub.add_parser("show"); sp.add_argument("id"); common(sp)

    stp = sub.add_parser("set"); stp.add_argument("id"); common(stp)
    stp.add_argument("--icon")
    stp.add_argument("--color")
    stp.add_argument("--lane", choices=list(cats.LANES))
    stp.add_argument("--tier", choices=list(cats.MODEL_TIERS))

    args = parser.parse_args(argv)
    repo_root = resolve_repo_root(args.repo_root, args.project) if (args.repo_root or args.project) else None

    if args.action == "list":
        rows = cats.load(repo_root)
        if args.json:
            print(json.dumps(rows, indent=2))
        else:
            try:
                sys.stdout.reconfigure(encoding="utf-8")  # emoji icons on cp1252 consoles
            except (AttributeError, OSError):
                pass
            for c in rows:
                print(f"{c.get('icon')} {c.get('id')}\t{c.get('name')}\t{c.get('lane')}\t{c.get('tier')}")
    elif args.action == "show":
        cat = cats.get(args.id, repo_root)
        print(json.dumps(cat, indent=2) if cat else f"unknown category '{args.id}'")
    elif args.action == "set":
        patch: dict = {}
        if args.icon is not None: patch["icon"] = args.icon
        if args.color is not None: patch["color"] = args.color
        if args.lane is not None: patch["lane"] = args.lane
        if args.tier is not None: patch["tier"] = args.tier
        try:
            print(f"wrote {cats.update(args.id, patch, repo_root)}")
        except (ValueError, KeyError) as exc:
            print(f"error: {exc}")


def _claude_crew(argv: list[str]) -> None:
    """List Claude Code subagents detected in a repo's .claude/agents/ -- the
    frontier crew, distinct from the harness roles Ikarus routes to."""
    import argparse
    import json
    from pathlib import Path
    from .claude_detect import detect_claude_crew
    from .projects import resolve_repo_root

    parser = argparse.ArgumentParser(
        prog="daedalus claude-crew",
        description="Detect Claude Code subagents in a repo's .claude/agents/.")
    parser.add_argument("--repo-root")
    parser.add_argument("--project")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo_root = resolve_repo_root(args.repo_root, args.project) if (args.repo_root or args.project) else str(Path.cwd())
    result = detect_claude_crew(repo_root)
    if args.json:
        print(json.dumps(result, indent=2))
    elif not result["count"]:
        print(f"no .claude/agents found under {repo_root}")
    else:
        for a in result["agents"]:
            print(f"{a['name']}\t{a['model']}\t{a['description'][:64]}")


def main() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(_USAGE)
        return
    cmd, rest = argv[0], argv[1:]
    sys.argv = [f"daedalus {cmd}", *rest]   # so sub-parsers see a clean argv

    if cmd == "doctor":
        from .doctor import main as m; m()
    elif cmd == "offload":
        from .offload import main as m; m()
    elif cmd == "spawn":
        _spawn(rest)
    elif cmd == "build":
        _build(rest)
    elif cmd == "ikarus":
        from .ikarus import main as m; m()
    elif cmd == "metrics":
        from .metrics import main as m; m()
    elif cmd == "benchmark":
        from .benchmark import main as m; m()
    elif cmd == "status":
        from .status import main as m; m()
    elif cmd == "dashboard":
        from .mission_control import main_dashboard as m; m(rest)
    elif cmd == "models":
        from .mission_control import main_models as m; m(rest)
    elif cmd == "squads":
        from .mission_control import main_squads as m; m(rest)
    elif cmd == "watcher":
        from .mission_control import main_watcher as m; m(rest)
    elif cmd == "review-diff":
        from .mission_control import main_review_diff as m; m(rest)
    elif cmd == "projects":
        _projects(rest)
    elif cmd == "agents":
        _agents(rest)
    elif cmd == "categories":
        _categories(rest)
    elif cmd == "claude-crew":
        _claude_crew(rest)
    elif cmd == "web":
        from .web_api import main as m; m(rest)
    elif cmd == "enforce":
        from .enforce import main as m; m()
    elif cmd == "init":
        _init(rest)
    else:
        print(f"unknown command '{cmd}'\n")
        print(_USAGE)


if __name__ == "__main__":
    main()
