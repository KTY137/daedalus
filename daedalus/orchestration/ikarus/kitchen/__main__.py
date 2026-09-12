"""``python -m daedalus.orchestration.ikarus.kitchen`` -- the kitchen door from a terminal.

    kitchen order  "bau mir eine Todo-App"        [--project NAME] [--async]
    kitchen feed   <repo-url-or-path> [...]        [--project NAME]
    kitchen status [ORDER_ID]                      [--project NAME]
    kitchen search "<query>" [--plane code|type|data|knowledge] [-k 8]

Orders run synchronously here (the terminal is the table) unless ``--async``.
"""
from __future__ import annotations

import argparse
import json
import sys

from .orders import KIND_FEED, Order, detect_language, parse_order
from .waiter import kitchen_for, order_status, place_order, _repo_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m daedalus.orchestration.ikarus.kitchen")
    parser.add_argument("--project", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    order = sub.add_parser("order")
    order.add_argument("text")
    order.add_argument("--async", dest="run_async", action="store_true")
    feed = sub.add_parser("feed")
    feed.add_argument("sources", nargs="+")
    status = sub.add_parser("status")
    status.add_argument("order_id", nargs="?")
    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--plane", default=None)
    search.add_argument("-k", type=int, default=8)
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    if args.command == "order":
        parsed = parse_order(args.text)
        if parsed is None:
            print(json.dumps({"ok": False, "error": "not an order; try 'bau mir eine App …' or 'verbessere diese App …'"}))
            return 2
        result = place_order(args.project, parsed, sync=not args.run_async)
    elif args.command == "feed":
        text = "feed ariadne " + " ".join(args.sources)
        parsed = Order(KIND_FEED, text, detect_language(text), sources=tuple(args.sources))
        result = place_order(args.project, parsed, sync=True)
    elif args.command == "status":
        result = order_status(args.project, args.order_id)
    else:
        kitchen = kitchen_for(_repo_root(args.project))
        result = {"hits": kitchen.grey.search(args.query, k=args.k, plane=args.plane), "grey_matter": kitchen.grey.stats()}
    json.dump(result, sys.stdout, indent=2, ensure_ascii=False, default=str)
    sys.stdout.write("\n")
    status_value = result.get("status") if isinstance(result, dict) else None
    return 0 if status_value in (None, "nominated", "done", "accepted", "cooking") else 1


if __name__ == "__main__":
    raise SystemExit(main())
