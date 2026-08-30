# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import argparse
import json
from typing import Any

from .. import core


def dashboard(project: str | None = None) -> dict[str, Any]:
    return core.get_dashboard(project)


def ollama_models() -> dict[str, Any]:
    return core.model_resources()


def queue_timeline(limit: int = 30) -> dict[str, Any]:
    return core.get_queue(limit=limit)


def watcher_status(project: str | None = None) -> dict[str, Any]:
    return core.watcher_status(project)


def squads(project: str | None = None) -> dict[str, Any]:
    return core.get_squads(project)


def quality_gates(project: str | None = None) -> dict[str, Any]:
    return core.get_quality(project)


def review_diff(project: str, lane: str = "local_only") -> dict[str, Any]:
    return core.review_diff(project, lane)


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, default=str))


def main_dashboard(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Mission Control dashboard JSON.")
    parser.add_argument("--project")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    payload = dashboard(args.project)
    if args.json:
        _print_json(payload)
    else:
        print(f"Mission Control: {payload.get('selected_project')}")


def main_models(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Ollama model resources.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    payload = ollama_models()
    if args.json:
        _print_json(payload)
    else:
        for m in payload["models"]:
            print(f"{m['name']}: {m['size_gb']} GB")


def main_squads(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Project squad configuration.")
    parser.add_argument("--project")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    payload = squads(args.project)
    if args.json:
        _print_json(payload)
    else:
        print(f"Squads for {args.project or 'default'}")


def main_watcher(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Bridge watcher status.")
    sub = parser.add_subparsers(dest="command")
    status_p = sub.add_parser("status")
    status_p.add_argument("--project")
    status_p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "status":
        payload = watcher_status(args.project)
        if args.json:
            _print_json(payload)
        else:
            print("running" if payload["running"] else "not running")
    else:
        parser.print_help()


def main_review_diff(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Queue a local advisory review of the current diff.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--lane", default="local_only", choices=["local_only", "local", "auto"])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    payload = review_diff(args.project, args.lane)
    if args.json:
        _print_json(payload)
    else:
        print(payload["queued"])
