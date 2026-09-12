"""``python -m daedalus.orchestration.ikarus.kitchen`` -- the kitchen door from a terminal.

    kitchen --project NAME order "bau mir eine Todo-App" [--new-request | --request-id ID]
    kitchen --project NAME feed <repo-url-or-path> [...] [--new-request | --request-id ID]
    kitchen status [ORDER_ID]                      [--project NAME]
    kitchen search "<query>" [--plane code|type|data|knowledge] [-k 8]

Orders run synchronously here. Background orders require the persistent chat
service; a one-shot CLI cannot keep a daemon worker alive. Repeat deliveries
replay an existing result; ``--new-request`` explicitly preserves it and starts
a fresh request.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from uuid import uuid4

from .orders import KIND_FEED, Order, detect_language, parse_order
from .waiter import kitchen_for, order_status, place_order, _repo_root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m daedalus.orchestration.ikarus.kitchen")
    parser.add_argument("--project", default=None)
    sub = parser.add_subparsers(dest="command", required=True)
    order = sub.add_parser("order")
    order.add_argument("text")
    order.add_argument("--async", dest="run_async", action="store_true")
    order_request = order.add_mutually_exclusive_group()
    order_request.add_argument("--request-id", help="stable delivery ID; reusing it replays the existing result")
    order_request.add_argument("--new-request", action="store_true", help="make a fresh request, preserving previous evidence")
    feed = sub.add_parser("feed")
    feed.add_argument("sources", nargs="+")
    feed_request = feed.add_mutually_exclusive_group()
    feed_request.add_argument("--request-id", help="stable delivery ID for this feed")
    feed_request.add_argument("--new-request", action="store_true", help="refresh sources as a new request, preserving old results")
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
        if args.run_async:
            parser.error("--async cannot survive this CLI process; run synchronously or use the persistent chat service")
        parsed = parse_order(args.text)
        if parsed is None:
            print(json.dumps({"ok": False, "error": "not an order; try 'bau mir eine App …' or 'verbessere diese App …'"}))
            return 2
        parsed = replace(parsed, request_id=uuid4().hex if args.new_request else args.request_id)
        result = place_order(args.project, parsed, sync=not args.run_async)
    elif args.command == "feed":
        text = "feed ariadne " + " ".join(args.sources)
        parsed = Order(KIND_FEED, text, detect_language(text), sources=tuple(args.sources),
                       request_id=uuid4().hex if args.new_request else args.request_id)
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
