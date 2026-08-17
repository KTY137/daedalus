"""Unified `daedalus` command -- one entry point for the whole harness.

    daedalus doctor                     is the bench ready? (Ollama/model/claude)
    daedalus offload "<objective>" ...  route ONE task; run on the bench (--live)
    daedalus spawn "<objective>" ...    decompose ONE objective; plan/dispatch bench
    daedalus build "<feature>" --project X   plan a multi-wave, frontier-first build
    daedalus ikarus                     spawn plan for the demo tasks
    daedalus metrics                    offload metrics / silent-escalation alarm
    daedalus benchmark                  projected token/cost picture
    daedalus status                     local bridge status; EXITS NON-ZERO when a
                                        subsystem is degraded or unproven
    daedalus health [--deep] [--probe-remote] [--json]
                                        what is working / present-but-unexercised /
                                        degraded / absent / unknown, with the
                                        provenance of every number. `present` and
                                        `unknown` are NOT passes and exit 2
    daedalus drill [--json]             trip every operability control end to end --
                                        promotion, spend ceiling, kill switch,
                                        gate escape, damage bounding -- and report
                                        whether SCHEDULING a shadow run would be
                                        defensible. It never schedules anything
    daedalus project-memory [--dry-run] [--limit N] [--json]
                                        project the append-only memory journal into
                                        the vector index and record the watermark
                                        that makes `context --latent` freshness
                                        answerable
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
    daedalus council "<question>" --dry-run|--live [--patch F] [--file P]
                                        convene the cross-vendor council over a
                                        patch/file; ADVISORY -- it promotes nothing.
                                        --live is REQUIRED to call any vendor: it
                                        spends real money; --dry-run calls nothing
    daedalus canary --dry-run|--live [--quick] [--vendors a,b]
                                        health-check every vendor lane with a
                                        small REAL task that has a checkable
                                        answer; "unavailable" is NOT failure.
                                        --live is REQUIRED to call any lane: a
                                        REAL task costs real money; --dry-run
                                        names the lanes and calls nothing
    daedalus claude-crew --project NAME     detect Claude Code subagents in .claude/agents/
    daedalus drafts list|show|apply|dismiss|rm   advisory drafts (free-lane proposals)
    daedalus selftest [--json]          live Ollama write round-trip (real, repeatable)
    daedalus bookkeeper update          refresh docs/architecture.html (+ history snapshot)
    daedalus map [--json] [--check] [--accept ITEM --why TEXT]
                                        generate docs/architecture-map.html: the
                                        mechanical half derived every run, the
                                        narrative half read from
                                        docs/architecture-narrative.md; --check
                                        is the gate and exits non-zero on drift
    daedalus web                         run the local Agent OS web API/app
    daedalus enforce                    add/update Codex/Claude harness instructions
    daedalus init [repo]                scaffold .agentenv/agentenv.json (enables writes)
    daedalus governance [--json]        may this system promote anything right now,
                                        and why not? the discrimination gate, the
                                        installed write confinement and the
                                        operability drill, each with its own state
                                        and provenance; exits non-zero when
                                        promotion is refused
    daedalus fault-attestation issue|verify
                                        operator step that signs retained
                                        Linux-host runtime-fault observations
                                        into the trust set, or checks a bundle;
                                        the fault driver never calls it, so
                                        producing evidence is not a way to
                                        produce trust
    daedalus fixture-fault-attestation issue|verify
                                        the same operator step for the
                                        deterministic-fixture column, with its
                                        own authority and its own key; neither
                                        issuer can sign the other's rows
    daedalus improve [--once] [--dry-run] [--limit N]
                                        rank the repo's own work by measurement;
                                        --once attempts the top item in an isolated
                                        worktree and prints a patch for HUMAN review
                                        (it never applies anything)
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


def _council(argv: list[str]) -> None:
    """Convene the cross-vendor council over a patch or a question.

    Four independent vendors answer the SAME question over the SAME evidence:
    round 1 blind, later rounds refuting. Every turn is appended to a
    hash-chained, offline-verifiable transcript under runs/council/.

    The output is ADVISORY and PROMOTES NOTHING. It carries no majority, no
    score and no approve/reject field, by construction: a deterministic gate
    (tests, fences, diffs) is the only thing that decides. What the council
    produces is a queue of checks for that gate to run."""
    import argparse
    import json
    from pathlib import Path
    from .council import session as cs
    from .council import vendors as cv

    parser = argparse.ArgumentParser(
        prog="daedalus council",
        description=(
            "Ask N independent model vendors the same question over the same "
            "evidence and record every dissent verbatim. ADVISORY: the verdict "
            "promotes nothing -- the deterministic gate decides, not a model."))
    # Optional only for --dry-run: a plan is about who would be seated and what
    # would be sent, and asking for it must not require inventing a question.
    parser.add_argument("question", nargs="?", default="",
                        help="what the council is asked to examine")
    parser.add_argument("--patch", help="unified diff file to review (the evidence)")
    parser.add_argument("--file", action="append", default=[],
                        help="evidence file to show the council (repeatable)")
    parser.add_argument("--rounds", type=int, default=cs.DEFAULT_ROUNDS,
                        help=f"deliberation rounds (default {cs.DEFAULT_ROUNDS}, "
                             f"hard cap {cs.MAX_ROUNDS_CAP}); round 1 is always blind")
    parser.add_argument("--vendors", default=",".join(cs.VENDOR_KEYS),
                        help=f"comma-separated subset of {','.join(cs.VENDOR_KEYS)}")
    parser.add_argument("--model", action="append", default=[], metavar="VENDOR=NAME",
                        help="pin a vendor's model (repeatable)")
    parser.add_argument("--trust", default="",
                        help="comma-separated vendors the OPERATOR lifts off the "
                             "untrusted allow-list for this council (recorded)")
    parser.add_argument("--ollama-host", default=cv.DEFAULT_BENCH_OLLAMA_HOST)
    parser.add_argument("--agy-signed-in", action="store_true",
                        help="assert agy has completed its interactive sign-in")
    parser.add_argument("--timeout", type=float, default=cs.DEFAULT_PER_CALL_TIMEOUT_S,
                        help="per-vendor call cap in seconds")
    parser.add_argument("--wall-clock", type=float, default=cs.DEFAULT_WALL_CLOCK_S,
                        help="whole-council cap in seconds")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan and vendor availability; call NO model")
    parser.add_argument("--live", action="store_true",
                        help="AUTHORISE REAL VENDOR CALLS: spends money and sends "
                             "the evidence to every seated vendor. Without this "
                             "flag no model is called.")
    parser.add_argument("--json", action="store_true")
    # -- the PR channel ----------------------------------------------------
    # daedalus/council/publish.py renders a stored deliberation and posts it as
    # a PR comment. It had NO production caller: SKILL.md told agents to type
    # `from daedalus.council.publish import publish_to_pr` by hand, so the
    # secret-floor gate inside it was never on any path a human could take.
    # These three flags are that path.
    parser.add_argument("--publish-pr", metavar="PR",
                        help="render a stored council and post it as a comment "
                             "on this PR. Requires --live to actually send; "
                             "without it the body is rendered and gated but gh "
                             "is never invoked.")
    parser.add_argument("--read-thread", metavar="PR",
                        help="read a PR's comments back as council turns "
                             "(INPUT to a later round; authoritative for nothing)")
    parser.add_argument("--transcript", metavar="PATH",
                        help="the council to publish: a runs/council/*.jsonl "
                             "path, or a bare council id")
    parser.add_argument("--repo", metavar="OWNER/NAME",
                        help="target repository (default: gh's current repo)")
    args = parser.parse_args(argv)

    # The PR channel convenes nobody, so it returns BEFORE the spend gate below
    # -- which exists to stop a council calling vendors, and would otherwise
    # demand a question for an operation that does not have one.
    if args.publish_pr or args.read_thread:
        _council_pr(args, parser)
        return

    if not args.question.strip():
        if not args.dry_run:
            parser.error("a question is required unless --dry-run is given")
        args.question = "(no question given -- plan only)"

    # THE SPEND GATE, before a single adapter is built. `--dry-run` is a
    # different question from `--live`, and asking both at once is ambiguous
    # about intent, so it is refused rather than settled by a precedence rule
    # nobody will remember at 2am. cs.convene has the same gate independently:
    # this one only makes the refusal legible to the operator.
    if args.live and args.dry_run:
        parser.error("--live and --dry-run contradict each other: one calls every "
                     "vendor for real, the other calls none. Pick one.")
    if not args.live and not args.dry_run:
        parser.error("refusing to convene: without --live this command calls NO "
                     "model. A live council spends real money at every seated "
                     "vendor and ships the evidence off this machine, so it must "
                     "be asked for explicitly. Use --dry-run to see exactly who "
                     "would be seated and what would be sent, then --live to run "
                     "it.")

    models: dict[str, str] = {}
    for pair in args.model:
        if "=" not in pair:
            print(f"error: --model expects VENDOR=NAME, got '{pair}'")
            return
        vendor, name = pair.split("=", 1)
        models[vendor.strip().lower()] = name.strip()
    names = [v.strip() for v in args.vendors.split(",") if v.strip()]
    try:
        participants = cs.default_participants(
            names, models=models, ollama_host=args.ollama_host,
            agy_signed_in=args.agy_signed_in)
    except ValueError as exc:
        print(f"error: {exc}")
        return

    if args.patch:
        text = Path(args.patch).read_text(encoding="utf-8", errors="replace")
        paths = sorted({m for m in _diff_paths(text)})
        evidence = cs.Evidence(label=f"patch:{Path(args.patch).name}",
                               paths=tuple(paths),
                               files=(("PATCH.diff", text),))
    elif args.file:
        evidence = cs.Evidence.from_files(args.file, label="files")
    else:
        evidence = cs.Evidence(label="question-only")

    if args.dry_run:
        plan = cs.dry_run_plan(
            args.question, evidence, participants, rounds=args.rounds,
            per_call_timeout_s=args.timeout, wall_clock_s=args.wall_clock)
        seatable = cv.available_vendors(ollama_host=args.ollama_host,
                                        agy_signed_in=args.agy_signed_in)
        plan["availability"] = [
            {"vendor": a.vendor, "available": a.available, "reason": a.reason,
             "endpoint": a.endpoint, "lane": a.lane}
            for a in seatable]
        if args.json:
            print(json.dumps(plan, indent=2, default=str))
            return
        print("COUNCIL PLAN (DRY RUN -- no model was called)")
        print(f"  question : {args.question}")
        print(f"  evidence : {plan['evidence']['label']}  "
              f"{len(plan['evidence']['changed_paths'])} changed path(s), "
              f"{plan['evidence']['evidence_tokens']} evidence tokens")
        print(f"  rounds   : {len(plan['rounds'])} (round 1 blind), "
              f"{plan['distinct_classes']} distinct weight family/families")
        if plan["duplicate_classes"]:
            print(f"  WARNING  : duplicate weight families -- "
                  f"{', '.join(plan['duplicate_classes'])} (one opinion, twice)")
        print(f"  bounds   : {args.timeout}s/call, {args.wall_clock}s total, "
              f"<= {plan['bounds']['token_ceiling']} prompt tokens")
        # The lane shown is the SEAT's lane, not the probe's guess: it decides
        # whether the egress allow-list is on for that participant.
        probe = {a.vendor: a for a in seatable}
        print("\n  seat                                     lane        available")
        print("  " + "-" * 68)
        for p in plan["participants"]:
            a = probe.get(p["vendor"])
            state = "unprobed" if a is None else (
                "yes" if a.available else f"no ({a.reason})")
            print(f"  {p['actor'] + ' ' + p['endpoint']:<40} {p['lane']:<11} {state}")
        print("\n  round assignments")
        for r in plan["rounds"]:
            who = ", ".join(f"{x['actor']}={x['role']}" for x in r["assignments"])
            print(f"    r{r['round']} [{r['mode']}] {who}")
        print("\nThe council's output is ADVISORY. It carries no majority and no "
              "score, and\npromotes nothing: run the checks it emits through the "
              "gate.")
        # Say the price out loud in the plan, so --live is never a surprise.
        live_seats = cs.live_egress_seats(participants)
        if live_seats:
            print(f"\nNO MODEL WAS CALLED. Re-running this with --live would call "
                  f"{len(live_seats)} real\nvendor seat(s) and send the evidence "
                  f"above to each of them:")
            for seat in live_seats:
                print(f"  - {seat}")
        return

    # A vendor answer is arbitrary Unicode and a Windows console is cp1252; an
    # UnicodeEncodeError here would discard a council that already ran and
    # already cost four calls. The transcript on disk is UTF-8 regardless.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    record = cs.convene(
        args.question, evidence, participants, rounds=args.rounds,
        per_call_timeout_s=args.timeout, wall_clock_s=args.wall_clock,
        trusted_vendors=[v.strip() for v in args.trust.split(",") if v.strip()],
        live=args.live)
    if args.json:
        import dataclasses
        print(json.dumps(dataclasses.asdict(record), indent=2, default=str))
        return
    print(record.render())


def _council_pr(args, parser) -> None:
    """The council's GitHub channel: publish a stored deliberation, or read a
    PR thread back as turns.

    FAIL CLOSED. Publishing sends a whole deliberation off this machine, so it
    is a dry run unless ``--live`` is given -- the same posture the convene path
    takes about spending money, for the same reason. The secret floor inside
    ``publish_to_pr`` runs on the dry path too, so a rehearsal is honest rather
    than a way around the gate.

    Every operational failure here is a STATUS, never an exception: the module
    enumerates them precisely so a caller does not have to guess."""
    from pathlib import Path
    from .council import publish as cp

    # A deliberation is arbitrary Unicode and a Windows console is cp1252. The
    # convene path already learned this; the early return for the PR channel
    # jumps over that guard, and an UnicodeEncodeError here would abort AFTER
    # the egress gate had already passed the body. MEASURED: a stored council
    # containing U+2192 crashed this command before this line existed.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    if args.read_thread:
        res = cp.read_pr_thread(args.read_thread, args.repo)
        print(f"[{res.status}] {res.detail}")
        for turn in res.turns:
            print(f"\n--- {turn.author}  {turn.created_at}  {turn.url}")
            print(turn.body)
        if res.status != cp.STATUS_READ_OK:
            raise SystemExit(1)
        print("\nNothing above is authoritative: a reply is INPUT to a later "
              "round, and is not on the hash-chained bus until a council "
              "appends it there.")
        return

    if not args.transcript:
        parser.error("--publish-pr needs --transcript: the path of the council "
                     "to publish (runs/council/<id>.jsonl) or its bare id")
    store = Path(args.transcript)
    if not store.is_file():
        # Accept a bare council id, which is what the transcript header and the
        # convene output both print.
        cand = Path("runs/council") / f"{args.transcript}.jsonl"
        if not cand.is_file():
            print(f"error: no such council transcript: {args.transcript}")
            raise SystemExit(1)
        store = cand

    verdict, turns = cp.load_for_publish(store)
    res = cp.publish_to_pr(verdict, turns, args.publish_pr, args.repo,
                           dry_run=not args.live)
    print(f"[{res.status}] {res.detail}")
    if res.status == cp.STATUS_DRY_RUN:
        print("\n" + res.markdown)
        print(f"\nNOTHING WAS SENT. Re-run with --live to post this to PR "
              f"{args.publish_pr}.")
        return
    if res.status == cp.STATUS_PUBLISHED:
        if res.comment_url:
            print(res.comment_url)
        return
    # refused_secret / gh_missing / gh_unauthenticated / pr_not_found / ...
    raise SystemExit(1)


def _diff_paths(diff_text: str) -> list[str]:
    """Changed paths out of a unified diff -- the PATH channel of the secret
    floor, which is the only tier that can see a patch ADDING a `.env`."""
    import re
    out: list[str] = []
    for line in diff_text.splitlines():
        m = re.match(r"^diff --git a/(.+?) b/(.+)$", line)
        if m:
            out.extend([m.group(1), m.group(2)])
            continue
        m = re.match(r"^(?:\+\+\+|---) [ab]/(.+?)(?:\t.*)?$", line)
        if m and m.group(1) != "dev/null":
            out.append(m.group(1))
    return sorted(set(out))


def _canary(argv: list[str]) -> int:
    """Health-check every vendor lane with a small task that has a checkable
    answer, and fail loud when a lane degrades.

    Each probe is (prompt, deterministic checker) -- no model judges another
    model, because a checker that needed an LLM would have the same failure
    mode the canary exists to catch. Exit code is non-zero ONLY when a lane
    that used to pass a LIVENESS probe now fails it."""
    import argparse
    import dataclasses
    import json
    from .council import canary as cn

    parser = argparse.ArgumentParser(
        prog="daedalus canary",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Give every vendor lane a small real task with a checkable answer "
            "and fail loud when one degrades. Every probe is a (prompt, "
            "deterministic-Python checker) pair: no model grades another model."),
        epilog=(
            "UNAVAILABLE IS NOT FAILURE.\n"
            "  'we could not ask' (agy not signed in, bench asleep, CLI not\n"
            "  installed) and 'we asked and the answer was wrong' are separate\n"
            "  statuses and are never merged -- conflating them is the main way\n"
            "  a health check lies. An unavailable lane never trips the exit code.\n"
            "\n"
            "PROBES\n"
            + "".join(f"  {p.name:<14} [{p.severity}] {p.blurb}\n" for p in cn.PROBES)
            + "  liveness = did our bytes arrive and did the lane obey the shape\n"
              "  quality  = is this lane's reasoning the right shape for a job.\n"
              "             A quality regression is printed but does NOT trip the\n"
              "             exit code: a lane can be alive and still be a bad fit.\n"
            "\n"
            "EXIT CODE\n"
            "  1 only when a previously-passing liveness probe now fails, so this\n"
            "  can be wired into a scheduled run. A lane that has never passed is\n"
            "  reported but is not a regression.\n"))
    parser.add_argument("--vendors", default=",".join(cn.VENDOR_KEYS),
                        help=f"comma-separated subset of {','.join(cn.VENDOR_KEYS)}")
    parser.add_argument("--probes", default="",
                        help="comma-separated subset of "
                             f"{','.join(p.name for p in cn.PROBES)} (default: all)")
    parser.add_argument("--quick", action="store_true",
                        help=f"one probe per lane ('{cn.QUICK_PROBE}' -- the probe "
                             "that catches a truncated prompt)")
    parser.add_argument("--model", action="append", default=[], metavar="VENDOR=NAME",
                        help="pin a vendor's model (repeatable); the default local "
                             f"model is the cheap {cn.DEFAULT_OLLAMA_MODEL}, not a 32b")
    parser.add_argument("--ollama-host", default=cn.DEFAULT_BENCH_OLLAMA_HOST,
                        help="passed EXPLICITLY per call; OLLAMA_HOST is never read "
                             "for routing and never written. Only 127.0.0.1 counts "
                             "as local -- the bench is egress")
    parser.add_argument("--agy-signed-in", action="store_true",
                        help="assert agy completed its interactive sign-in "
                             "(otherwise it reports unavailable, which is fine)")
    parser.add_argument("--timeout", type=float, default=cn.DEFAULT_PER_PROBE_TIMEOUT_S,
                        help="hard per-probe cap in seconds")
    parser.add_argument("--wall-clock", type=float, default=cn.DEFAULT_WALL_CLOCK_S,
                        help="total cap in seconds; a hung lane is abandoned here "
                             "and reported as a timeout, never blocking the rest")
    parser.add_argument("--max-parallel", type=int, default=cn.DEFAULT_MAX_PARALLEL,
                        help="lanes probed concurrently (probes WITHIN a lane are "
                             "sequential: four calls at once is a load test)")
    parser.add_argument("--history", default=str(cn.DEFAULT_HISTORY_PATH),
                        help="append-only JSONL run log used for the median/pass-rate "
                             "comparison")
    parser.add_argument("--no-record", action="store_true",
                        help="compare against history but do not append this run")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan, name the lanes --live would call, "
                             "and call NOTHING")
    parser.add_argument("--live", action="store_true",
                        help="AUTHORISE REAL VENDOR CALLS: every probe is a small "
                             "REAL task run at a real lane, so this spends real "
                             "money. Without this flag no model is called.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    # THE SPEND GATE, before a lane is built, before the history file is read or
    # written, before a probe body exists. `--dry-run` was only ever an OPT-OUT,
    # and an opt-out protects the operator who already knew to type it: a bare
    # `daedalus canary` spawned `claude` and `codex` for real. `--dry-run` is a
    # different question from `--live`, and asking both at once is ambiguous
    # about intent, so it is refused rather than settled by a precedence rule
    # nobody will remember at 2am. cn.run_canary has the same gate independently;
    # this one only makes the refusal legible to the operator.
    if args.live and args.dry_run:
        parser.error("--live and --dry-run contradict each other: one runs a real "
                     "task at every lane and bills you for it, the other calls "
                     "none. Pick one.")
    if not args.live and not args.dry_run:
        parser.error("refusing to run the canary: without --live this command "
                     "calls NO model. Every probe here is a small REAL task sent "
                     "to a real vendor lane, so it spends real money and its "
                     "payload leaves this machine for every non-loopback lane. "
                     "Use --dry-run to see exactly which lanes would be called "
                     "and what would be sent, then --live to run it.")

    names = [v.strip() for v in args.vendors.split(",") if v.strip()]
    probe_names = [p.strip() for p in args.probes.split(",") if p.strip()]
    models: dict[str, str] = {}
    for pair in args.model:
        if "=" not in pair:
            print(f"error: --model expects VENDOR=NAME, got '{pair}'")
            return 2
        vendor, name = pair.split("=", 1)
        models[vendor.strip().lower()] = name.strip()
    try:
        probes = cn.probes_for(probe_names, quick=args.quick)
        lanes = cn.default_lanes(names, models=models,
                                 ollama_host=args.ollama_host,
                                 agy_signed_in=args.agy_signed_in)
    except ValueError as exc:
        print(f"error: {exc}")
        return 2

    if args.dry_run:
        plan = cn.dry_run_plan(lanes, probes, per_probe_timeout_s=args.timeout,
                               wall_clock_s=args.wall_clock,
                               max_parallel=args.max_parallel,
                               history_path=args.history)
        if args.json:
            print(json.dumps(plan, indent=2, default=str))
            return 0
        print("VENDOR CANARY PLAN (DRY RUN -- no model was called)")
        print(f"  {plan['calls']} call(s): {len(lanes)} lane(s) x {len(probes)} probe(s)")
        print(f"  bounds  : {args.timeout}s/probe, {args.wall_clock}s total, "
              f"{args.max_parallel} lane(s) in flight")
        print(f"  history : {plan['history_path']}")
        print("\n  lane                                     egress")
        print("  " + "-" * 62)
        for lane in plan["lanes"]:
            print(f"  {lane['vendor'] + ' ' + lane['model'] + ' @ ' + lane['endpoint']:<40} "
                  f"{lane['egress']}")
        print("\n  probe          severity  chars  what it catches")
        print("  " + "-" * 74)
        for p in plan["probes"]:
            print(f"  {p['name']:<14} {p['severity']:<9} {p['prompt_chars']:<6} {p['blurb']}")
        print("\nUnavailable is not failure. Nothing was asked and nothing was billed.")
        # Say the price out loud in the plan, so --live is never a surprise.
        if plan["live_seats"]:
            print(f"\nNO MODEL WAS CALLED. Re-running this with --live would call "
                  f"{len(plan['live_seats'])} real\nvendor lane(s) with "
                  f"{plan['calls']} billable probe(s):")
            for seat in plan["live_seats"]:
                print(f"  - {seat}")
        return 0

    # A vendor answer is arbitrary Unicode and a Windows console is cp1252; an
    # UnicodeEncodeError here would discard a canary that already ran.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

    history = cn.load_history(args.history)
    run = cn.run_canary(lanes, probes, per_probe_timeout_s=args.timeout,
                        wall_clock_s=args.wall_clock,
                        max_parallel=args.max_parallel, history=history,
                        live=args.live)
    if not args.no_record:
        cn.append_history(run, args.history)

    if args.json:
        payload = dataclasses.asdict(run)
        payload["summary"] = run.summary()
        payload["exit_code"] = run.exit_code()
        print(json.dumps(payload, indent=2, default=str))
        return run.exit_code()
    print(cn.render_table(run))
    return run.exit_code()


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


_GOV_GLYPH = {"working": "OK", "present": "??", "degraded": "!!",
              "absent": "XX", "unknown": "??"}


def _governance(argv: list[str]) -> int:
    """May this system promote anything right now, and why not?

    Same payload the web API and both UIs render -- `core.get_governance` is
    the only place this is computed, so the CLI cannot answer differently from
    the screen. Exits non-zero when promotion is refused so a script can gate
    on it without parsing prose.
    """
    import argparse

    p = argparse.ArgumentParser(prog="daedalus governance")
    p.add_argument("--project", default=None)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    import json

    from .core import get_governance

    g = get_governance(args.project)
    if args.json:
        print(json.dumps(g, indent=2))
        return 0 if g["promotion_allowed"] else 1

    head = (g.get("head") or "unknown")[:12]
    print("PROMOTION: " + ("ALLOWED" if g["promotion_allowed"] else "REFUSED"))
    print(f"  {g['verdict']}")
    print(f"  aggregate state: {g['state']}   HEAD: {head}")
    print()
    for gate in g.get("gates", []):
        print(f"  [{_GOV_GLYPH.get(gate['state'], '??')}] "
              f"{gate['state']:<9} {gate['provenance']:<9} {gate['id']}")
        print(f"        {gate['question']}")
        print(f"        {gate['headline']}")
        if gate.get("write_allow"):
            print(f"        write_allow: {', '.join(gate['write_allow'])}")
        print()
    for w in g.get("warnings", []):
        print(f"  warning: {w}")
    if not g["promotion_allowed"]:
        print("Nothing may be promoted on the strength of this gate. "
              "Promotion remains a human act in every case.")
    return 0 if g["promotion_allowed"] else 1


def main() -> None:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(_USAGE)
        return
    cmd, rest = argv[0], argv[1:]
    sys.argv = [f"daedalus {cmd}", *rest]   # so sub-parsers see a clean argv

    # THE SPEND CEILING, INSTALLED BEFORE ANY SUBCOMMAND CAN SPEND.
    #
    # There is no chokepoint to put it at. Paid calls leave this repo from four
    # subsystems that share no dispatch path -- providers/, council/,
    # ikarus_os.py and runs/ -- across 17 sites, three of which no text scan can
    # even see (one builds the argv while another spawns it; one takes the
    # vendor as a base_url). daedalus/budget.py therefore MANUFACTURES a
    # chokepoint at the syscall boundary, and every one of those 17 sites bottoms
    # out in it.
    #
    # Non-vendor spawns are classified and passed straight through untouched, so
    # git and pytest are not affected -- asserted by a test, because a spend cap
    # that broke ordinary subprocesses would be removed within the hour and then
    # there would be no cap at all.
    #
    # Installed here rather than inside each subcommand for the reason that
    # matters: a cap you have to remember to install is a cap that is missing
    # exactly where somebody forgot.
    # BEFORE the guard, because the guard's own configuration -- the ceiling,
    # the call cap, the declared subscription vendors -- is exactly the kind of
    # thing that belongs in `.env`. Loading after it would read the defaults and
    # silently ignore what the operator configured.
    from .dotenv import DotEnvRefused, load as _load_dotenv

    try:
        _load_dotenv()
    except DotEnvRefused as exc:
        # The one config error worth stopping the whole CLI for: a tracked .env
        # is a secret already in the repository, and every command from here on
        # would be spending or sending with a leaked key.
        print(f"[daedalus] REFUSED: {exc}", file=sys.stderr)
        return 2

    from .budget import install_process_guard

    install_process_guard()

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
        # The verdict is the point of this command, so it must reach the shell.
        # `m()` alone discarded it and every `daedalus status` looked like a
        # success -- including the ones reporting a degraded subsystem.
        from .status import main as m; raise SystemExit(m())
    elif cmd == "health":
        from .health import main as m; raise SystemExit(m(rest))
    elif cmd == "project-memory":
        from .memory.projection_worker import main as m; raise SystemExit(m(rest))
    elif cmd == "drill":
        # tools/ is not a package, so this shells out rather than importing.
        # Resolved from this file's location, never from cwd -- `daedalus drill`
        # must mean the same thing from anywhere.
        import pathlib
        import subprocess as _sp
        script = pathlib.Path(__file__).resolve().parents[1] / "tools" / "operability_drill.py"
        if not script.exists():
            print(f"the operability drill is not installed at {script}",
                  file=sys.stderr)
            raise SystemExit(2)
        raise SystemExit(_sp.run([sys.executable, str(script), *rest]).returncode)
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
    elif cmd == "council":
        _council(rest)
    elif cmd == "canary":
        raise SystemExit(_canary(rest))
    elif cmd == "claude-crew":
        _claude_crew(rest)
    elif cmd == "drafts":
        _drafts(rest)
    elif cmd == "selftest":
        from .selftest import main as m; m(rest)
    elif cmd == "bookkeeper":
        from .bookkeeper import main as m; m(rest)
    elif cmd == "map":
        from .mapping.render import main as m; raise SystemExit(m(rest))
    elif cmd == "web":
        from .web_api import main as m; m(rest)
    elif cmd == "enforce":
        from .enforce import main as m; m()
    elif cmd == "improve":
        from .spine.picker import main as m; raise SystemExit(m(rest))
    elif cmd == "init":
        _init(rest)
    elif cmd == "governance":
        raise SystemExit(_governance(rest))
    elif cmd == "fault-attestation":
        # Deliberately an operator command and nothing else. The fault driver
        # produces evidence; only this separate, explicitly invoked step turns
        # a retained observation into a trusted one, so a candidate that can
        # write evidence still cannot write trust.
        from .runtimes.fault_attestation_issuer import main as m
        raise SystemExit(m(rest))
    elif cmd == "fixture-fault-attestation":
        # The sibling operator command for the deterministic-fixture column.
        # It is a separate entrypoint with a separate authority and a separate
        # key parameter on purpose: neither column's issuer can sign the
        # other's rows, so compromising one collector does not buy trust in
        # the other.
        from .runtimes.fixture_fault_attestation_issuer import main as m
        raise SystemExit(m(rest))
    else:
        print(f"unknown command '{cmd}'\n")
        print(_USAGE)


if __name__ == "__main__":
    main()
