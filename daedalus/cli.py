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
    daedalus accelerators [--deep] [--probe-remote] --json
                                        evidence-based local/RTX compute readiness
    daedalus squads --project NAME --json
    daedalus watcher status --project NAME --json
    daedalus review-diff --project NAME --lane local_only
    daedalus projects                   list registered projects
    daedalus dctx <repo> <target> [--out F] | dctx <repo> --verify F
                                        mint/verify a certified-context receipt
    daedalus context "<objective>" [--project X|--repo-root R] [--latent] --json
                                        plan budgeted hybrid DSS context
    daedalus agents list|show|add|edit|rm   manage agent-role definitions at runtime
    daedalus categories list|show|set   manage role-category presets (icon/color/lane/tier)
    daedalus claude-crew --project NAME     detect Claude Code subagents in .claude/agents/
    daedalus drafts list|show|apply|dismiss|rm   advisory drafts (free-lane proposals)
    daedalus selftest [--json]          live Ollama write round-trip (real, repeatable)
    daedalus bookkeeper update          refresh docs/architecture.html (+ history snapshot)
    daedalus web                         run the local Agent OS web API/app
    daedalus enforce                    add/update Codex/Claude harness instructions
    daedalus init [repo]                scaffold .agentenv/agentenv.json (enables writes)
"""

from __future__ import annotations

import sys

_USAGE = __doc__


def _spawn(argv: list[str]) -> None:
    """Decompose one objective into subtasks and plan (default) or dispatch
    (--live) them across the local bench via Kairos."""
    import argparse
    import json
    from .kairos.scheduler import KairosScheduler
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
    ikarus = KairosScheduler(project=args.project)
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


def _accelerators(argv: list[str]) -> None:
    import argparse
    import json

    from .accelerators import accelerator_status

    parser = argparse.ArgumentParser(
        prog="daedalus accelerators",
        description=(
            "Report evidence-based CUDA/RTX backend readiness. "
            "A visible GPU is not treated as a usable ML backend."
        ),
    )
    parser.add_argument(
        "--deep",
        action="store_true",
        help="import optional frameworks in an isolated process and verify CUDA readiness",
    )
    parser.add_argument(
        "--probe-remote",
        action="store_true",
        help="probe DAEDALUS_RTX_OLLAMA_HOST /api/tags when configured",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    payload = accelerator_status(deep=args.deep, probe_remote=args.probe_remote)
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return
    hardware = payload["hardware"]
    devices = hardware.get("devices") or []
    if devices:
        for device in devices:
            print(
                f"{device['name']}  cc {device['compute_capability']}  "
                f"{device['memory_mib']} MiB  driver {device['driver_version']}"
            )
    else:
        print(f"NVIDIA hardware unavailable: {hardware.get('error')}")
    for lane in payload["lanes"]:
        print(f"{lane['state']:<11} {lane['id']}: {lane['label']}")


def _context(argv: list[str]) -> None:
    import argparse
    import json

    from .context_plan import plan_context
    from .projects import load_project, resolve_repo_root
    from .structcore.churn import co_change_pairs
    from .structcore.index import cached_index

    parser = argparse.ArgumentParser(
        prog="daedalus context",
        description=(
            "Plan read-only, token-budgeted context with lexical/optional "
            "versioned-latent seeds and deterministic DSS graph propagation."
        ),
    )
    parser.add_argument("objective")
    parser.add_argument("--repo-root")
    parser.add_argument("--project")
    parser.add_argument("--max-tokens", type=int, default=8_000)
    parser.add_argument(
        "--latent",
        action="store_true",
        help="add path-grounded hits from the versioned event projection index",
    )
    parser.add_argument("--embedding-host")
    parser.add_argument("--embedding-model")
    parser.add_argument(
        "--cochange",
        action="store_true",
        help="derive bounded git co-change relations (runs a separate git-history pass)",
    )
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    repo_root = resolve_repo_root(args.repo_root, args.project)
    center: list[str] = []
    ignore: list[str] = []
    if args.project:
        project_data = load_project(args.project)
        raw_center = project_data.get("center") or []
        raw_ignore = project_data.get("ignore") or []
        center = [raw_center] if isinstance(raw_center, str) else list(raw_center)
        ignore = [raw_ignore] if isinstance(raw_ignore, str) else list(raw_ignore)
    idx = cached_index(
        repo_root,
        refresh=args.refresh,
        center=center,
        ignore=ignore,
    )
    temporal_pairs = co_change_pairs(repo_root) if args.cochange else ()
    options = {
        "idx": idx,
        "project": args.project,
        "token_budget": args.max_tokens,
        "use_latent": args.latent,
        "temporal_pairs": temporal_pairs,
    }
    if args.embedding_host:
        options["embedding_host"] = args.embedding_host
    if args.embedding_model:
        options["embedding_model"] = args.embedding_model
    result = plan_context(repo_root, args.objective, **options)
    payload = result.to_dict()
    if args.json:
        print(json.dumps(payload, indent=2, default=str))
        return
    plan = result.dss.context_plan
    print(
        f"DSS CONTEXT  {len(plan.selected)} selected / "
        f"{plan.tokens_used}/{plan.token_budget} tokens"
    )
    print(f"receipt {result.receipt_sha256}")
    for item in plan.selected:
        why = ", ".join(item.reasons) or "ranked"
        print(
            f"{item.score:0.4f}  {item.estimated_tokens:>6}t  "
            f"{item.node_id}  [{why}]"
        )


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


def _drafts(argv: list[str]) -> None:
    """List / show / remove persisted advisory drafts (runs/drafts/). Drafts
    are free-lane PROPOSALS awaiting review -- applying one stays a human /
    Claude action by design (a free model may propose, never merge)."""
    import argparse
    import json
    from .kairos import drafts as dr

    parser = argparse.ArgumentParser(
        prog="daedalus drafts",
        description="Manage persisted advisory drafts (free-lane proposals).")
    sub = parser.add_subparsers(dest="action", required=True)
    lp = sub.add_parser("list"); lp.add_argument("--json", action="store_true")
    sp = sub.add_parser("show"); sp.add_argument("id")
    rp = sub.add_parser("rm"); rp.add_argument("id")
    apf = sub.add_parser("apply", help="mark handled + print the review packet for the Claude lane")
    apf.add_argument("id"); apf.add_argument("--json", action="store_true")
    dsf = sub.add_parser("dismiss"); dsf.add_argument("id")

    args = parser.parse_args(argv)
    if args.action == "list":
        rows = dr.list_drafts()
        if args.json:
            print(json.dumps(rows, indent=2))
        elif not rows:
            print("no drafts (advisory offloads store their proposals here)")
        else:
            for d in rows:
                print(f"{d['id']}\t{d['agent']}\t{d['status']}\t{d['objective']}")
    elif args.action == "show":
        d = dr.get_draft(args.id)
        print(json.dumps(d, indent=2) if d else f"unknown draft '{args.id}'")
    elif args.action == "rm":
        print("removed" if dr.delete_draft(args.id) else f"unknown draft '{args.id}'")
    elif args.action == "apply":
        packet = dr.apply_payload(args.id)
        if packet is None:
            print(f"unknown draft '{args.id}'")
        elif args.json:
            print(json.dumps(packet, indent=2))
        else:
            print(f"# review packet for {packet['id']} (marked applied)")
            print(f"objective: {packet['objective']}")
            print(f"paths    : {', '.join(packet['paths']) or '-'}")
            print(f"proposal : {packet['proposal']}")
            print(f"\n{packet['handoff']}")
    elif args.action == "dismiss":
        d = dr.set_status(args.id, "dismissed")
        print("dismissed" if d else f"unknown draft '{args.id}'")


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
        from .kairos.scheduler import main as m; m()
    elif cmd == "dctx":
        from .dctx import main as m; m()
    elif cmd == "context":
        _context(rest)
    elif cmd == "metrics":
        from .metrics import main as m; m()
    elif cmd == "benchmark":
        from .benchmark import main as m; m()
    elif cmd == "status":
        from .status import main as m; m()
    elif cmd == "dashboard":
        from .kairos.control import main_dashboard as m; m(rest)
    elif cmd == "models":
        from .kairos.control import main_models as m; m(rest)
    elif cmd == "accelerators":
        _accelerators(rest)
    elif cmd == "squads":
        from .kairos.control import main_squads as m; m(rest)
    elif cmd == "watcher":
        from .kairos.control import main_watcher as m; m(rest)
    elif cmd == "review-diff":
        from .kairos.control import main_review_diff as m; m(rest)
    elif cmd == "projects":
        _projects(rest)
    elif cmd == "agents":
        _agents(rest)
    elif cmd == "categories":
        _categories(rest)
    elif cmd == "claude-crew":
        _claude_crew(rest)
    elif cmd == "drafts":
        _drafts(rest)
    elif cmd == "selftest":
        from .selftest import main as m; m(rest)
    elif cmd == "bookkeeper":
        from .bookkeeper import main as m; m(rest)
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
