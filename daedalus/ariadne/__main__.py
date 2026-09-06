from __future__ import annotations

import argparse
import json
from pathlib import Path

from .campaign import run_campaign


def main(argv: list[str] | None = None) -> int:
    # The module door is effectful even though run_campaign has its own exact
    # lease: argument handling must not be able to precede the process-wide
    # spend/process guard.  The inner python.ariadne_campaign boundary still
    # owns write policy, containment, the durable lease, and each trial.
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "cli.ariadne_campaign",
        REGISTRY_BY_ID["cli.ariadne_campaign"].effects,
        (process_guard_boundary_decision(),),
    )

    parser = argparse.ArgumentParser(prog="python -m daedalus.ariadne")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--timeout-s", type=int, default=30)
    args = parser.parse_args(argv)
    result = run_campaign(
        repo_root=Path(args.repo_root), source_revision=args.source_revision,
        campaign_id=args.campaign_id, target_path=args.target,
        before=args.before, after=args.after, timeout_s=args.timeout_s,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
