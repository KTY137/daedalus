"""Command-line entry point for the wiki module: ``python -m daedalus.wiki``.

Three subcommands, each delegating to the module that already owns the work
instead of reimplementing it:

* ``plan <root> [--authors N] [--wiki-dir D]``  -> :func:`daedalus.wiki.plan.main`
* ``verify <root> [wiki-dir]``                  -> :func:`daedalus.wiki.verify.main`
* ``health <root>``                             -> ``daedalus.wiki.metrics.wiki_health``

This entrypoint is not an effect boundary, because it has no effects to bound.
It reads the tree and writes exactly the two artefact files its delegates
already write -- ``<root>/runs/wiki_plan.json`` and
``<root>/runs/wiki_verify.json``. It opens no other write root, makes no
network call, and calls no model. ``health`` writes nothing at all.

The effectful half of wiki generation -- fanning the emitted task prompts out
to agents, letting them search the web, letting them write pages -- deliberately
does not live here. It stays a separate step so that spend, egress, write roots
and the kill switch stay at one boundary: ``daedalus/spine/effect_boundary.py``
is where a runtime start that has effects is registered and guarded. Adding a
``generate`` subcommand to this file would put a model call and a write root
behind a docs command, which is the bypass that boundary exists to prevent.

Exit codes:

* ``0`` -- ``plan``/``health`` succeeded, or ``verify``'s verdict is PASS
* ``1`` -- ``verify``'s verdict is FAIL, or there is no wiki at the given path
* ``2`` -- usage error, or ``<root>`` is not a directory
* ``3`` -- ``health`` could not measure: ``daedalus.wiki.metrics`` is not
  importable yet, or exposes no callable ``wiki_health``

``3`` is deliberately distinct from ``0``. "I could not measure" and "I
measured and found nothing wrong" are different statements, and an instrument
that cannot tell them apart fails silently toward less coverage.

Submodules are imported inside the subcommand handlers, not at module scope,
for the reason the package docstring gives: each carries a tree walk that a
caller who only wanted ``--help``, or only wanted a different subcommand,
should not pay for.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import pathlib
import sys

EPILOG = """\
boundary:
  read-only, except for the two artefacts the delegates write:
    plan   -> <root>/runs/wiki_plan.json
    verify -> <root>/runs/wiki_verify.json
    health -> writes nothing
  no network, no model call, no other write root. Dispatching the planned
  tasks to agents is a separate, effectful step and does not live here; see
  daedalus/spine/effect_boundary.py.

exit codes:
  0  plan/health ok, or verify verdict PASS
  1  verify verdict FAIL, or no wiki at the given path
  2  usage error, or <root> is not a directory
  3  health could not measure (daedalus.wiki.metrics unavailable)
"""


def _resolve_root(raw: str) -> pathlib.Path | None:
    """The resolved repository root, or None -- with the reason on stderr.

    The resolved path is what is reported, not the raw argument, so that a
    relative root shows which directory was actually looked at. Same wording
    and same exit code as the delegates use for this case.
    """
    root = pathlib.Path(raw).expanduser().resolve()
    if root.is_dir():
        return root
    print(f"not a directory: {root}", file=sys.stderr)
    return None


def _cmd_plan(args: argparse.Namespace) -> int:
    root = _resolve_root(args.root)
    if root is None:
        return 2
    from . import plan

    # plan.main takes argv, argv[0] being the program name, then
    # <repo-root> [authors] [wiki-dir] positionally. Its own defaults are
    # mirrored by this parser, so the delegation never needs to change it.
    return plan.main(["daedalus.wiki.plan", str(root), str(args.authors), args.wiki_dir])


def _cmd_verify(args: argparse.Namespace) -> int:
    root = _resolve_root(args.root)
    if root is None:
        return 2
    from . import verify

    argv = ["daedalus.wiki.verify", str(root)]
    if args.wiki_dir is not None:
        # Passed through verbatim: verify.main resolves it against the current
        # working directory, not against <root>. Papering over that here would
        # make the same argument mean two different things depending on which
        # entrypoint you used.
        argv.append(args.wiki_dir)
    return verify.main(argv)


def _cmd_health(args: argparse.Namespace) -> int:
    root = _resolve_root(args.root)
    if root is None:
        return 2
    try:
        from . import metrics
    except Exception as exc:  # noqa: BLE001 - a half-written parallel module
        # Broad on purpose: a module still being written raises ImportError,
        # SyntaxError or anything its top level does. The exception type is
        # printed so the unavailability is never silent.
        print(f"metrics not available yet: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    fn = getattr(metrics, "wiki_health", None)
    if not callable(fn):
        print("metrics not available yet: daedalus.wiki.metrics exposes no "
              "callable wiki_health", file=sys.stderr)
        return 3

    # Signature frozen at review 2026-08-25: wiki_health(root, k: int = 3).
    # This CLI deliberately exposes no k, so the callee's own default stands.
    # After the freeze a signature change is a bug, not unavailability, so it
    # propagates as a TypeError rather than being laundered into exit 3.
    #
    # Negative evidence, retained (AGENTS.md 4): the deleted version of this
    # call bound arguments BY ARITY and so put a Path into k, crashing inside
    # metrics.k_core with "'>=' not supported between instances of 'int' and
    # 'WindowsPath'". Never fill a parameter somebody else gave a default to.
    result = fn(root)
    if dataclasses.is_dataclass(result) and not isinstance(result, type):
        result = dataclasses.asdict(result)
    if isinstance(result, (dict, list)):
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    else:
        print(result)
    # health reports, it does not gate. verify is the gate, and it is the one
    # that returns 1 on a bad verdict.
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m daedalus.wiki",
        description="Plan, verify and measure a generated project wiki. "
                    "Read-only apart from the two artefact files listed below.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="{plan,verify,health}")

    p_plan = sub.add_parser(
        "plan",
        help="survey a tree, partition it into topics, emit agent task prompts",
        description="Survey <root>, partition it into topic buckets and write the "
                    "dispatchable task prompts to <root>/runs/wiki_plan.json. "
                    "Dispatching them is a separate, effectful step.",
    )
    p_plan.add_argument("root", help="repository root to survey")
    p_plan.add_argument("--authors", type=int, default=3, metavar="N",
                        help="how many authors to balance the topics across (default: 3)")
    p_plan.add_argument("--wiki-dir", default="docs/wiki", metavar="D",
                        help="where the authors are told to write pages, relative to "
                             "the repository root (default: docs/wiki). Recorded in "
                             "the plan and in the prompts; nothing is written there.")
    p_plan.set_defaults(handler=_cmd_plan)

    p_verify = sub.add_parser(
        "verify",
        help="check every claim a wiki makes against the tree it describes",
        description="Verify the wiki against <root> and write the report to "
                    "<root>/runs/wiki_verify.json. Exits 1 when the verdict is FAIL.",
    )
    p_verify.add_argument("root", help="repository root the wiki claims to describe")
    p_verify.add_argument("wiki_dir", nargs="?", default=None, metavar="wiki-dir",
                          help="the wiki directory (default: <root>/docs/wiki). "
                               "A relative path is resolved against the current "
                               "working directory, not against <root> -- this is "
                               "daedalus.wiki.verify's own convention, kept verbatim.")
    p_verify.set_defaults(handler=_cmd_verify)

    p_health = sub.add_parser(
        "health",
        help="report the wiki's health metrics (daedalus.wiki.metrics)",
        description="Print the health metrics for the wiki of <root>. Writes "
                    "nothing. Exits 3, not 0, when the metrics module cannot "
                    "be reached -- 'could not measure' is not 'measured, fine'.",
    )
    p_health.add_argument("root", help="repository root whose wiki to measure")
    p_health.set_defaults(handler=_cmd_health)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
