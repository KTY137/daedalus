from __future__ import annotations

import base64
import datetime as dt
import json
import os
import subprocess
import sys

REPO = os.environ["GITHUB_REPOSITORY"]
KEEP = [
    "main",
    "g1/ikarus-runtime-invocation-binding-07d3",
    "nemesis/20260830-tier2-evidence-hardening-r2",
    "g1/gardener-post-release-containment-03",
    "exp/tensor-latent-ceiling-01",
    "exp/tensor-kernel-contract-01",
    "feature/chip-design-rtl-tcl",
    "experiment/deepseek-lab",
    "ops/gardener-campaign-20260929",
    "worktree-wiki-generation-gate",
    "g2/knowledge-correlation-bootstrap",
]
KEEP_SET = set(KEEP)
MANIFEST_PATH = "docs/recovery/REMOTE_BRANCH_CONSOLIDATION_20260830.json"


def run(args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    cp = subprocess.run(args, text=True, capture_output=True)
    if check and cp.returncode != 0:
        print(cp.stdout)
        print(cp.stderr, file=sys.stderr)
        raise SystemExit(f"command failed: {args}")
    return cp


def paged_tsv(path: str, jq: str) -> list[str]:
    cp = run(["gh", "api", "--paginate", path, "--jq", jq])
    return [line for line in cp.stdout.splitlines() if line.strip()]


def branches() -> dict[str, str]:
    rows = paged_tsv(
        f"repos/{REPO}/branches?per_page=100",
        '.[] | [.name, .commit.sha] | @tsv',
    )
    out: dict[str, str] = {}
    for row in rows:
        name, sha = row.split("\t", 1)
        if name in out:
            raise SystemExit(f"duplicate branch returned: {name}")
        out[name] = sha
    return out


def open_prs() -> list[tuple[int, str, str]]:
    rows = paged_tsv(
        f"repos/{REPO}/pulls?state=open&per_page=100",
        '.[] | [(.number|tostring), .head.ref, .base.ref] | @tsv',
    )
    out: list[tuple[int, str, str]] = []
    for row in rows:
        number, head, base = row.split("\t", 2)
        out.append((int(number), head, base))
    return out


def persist_manifest(manifest: dict[str, object]) -> None:
    payload = json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n"
    encoded = base64.b64encode(payload).decode()
    existing = run(
        ["gh", "api", f"repos/{REPO}/contents/{MANIFEST_PATH}?ref=main"],
        check=False,
    )
    cmd = [
        "gh", "api", "-X", "PUT",
        f"repos/{REPO}/contents/{MANIFEST_PATH}",
        "-f", "message=chore: snapshot remote branches before consolidation",
        "-f", f"content={encoded}",
        "-f", "branch=main",
    ]
    if existing.returncode == 0:
        cmd += ["-f", f"sha={json.loads(existing.stdout)['sha']}"]
    elif "404" not in (existing.stderr + existing.stdout):
        raise SystemExit("could not determine recovery-manifest state")
    run(cmd)


def main() -> None:
    if len(KEEP) != 11 or len(KEEP_SET) != 11 or "main" not in KEEP_SET:
        raise SystemExit("invalid canonical keep-set")

    before = branches()
    missing = [name for name in KEEP if name not in before]
    if missing:
        raise SystemExit(f"missing canonical branches: {missing}")

    archive_prs: list[dict[str, object]] = []
    for number, head, base in open_prs():
        if head in KEEP_SET:
            if base not in KEEP_SET:
                raise SystemExit(
                    f"open PR #{number} keeps head {head} but depends on retiring base {base}"
                )
        else:
            archive_prs.append({"number": number, "head": head, "base": base})

    retire = {name: sha for name, sha in before.items() if name not in KEEP_SET}
    manifest = {
        "schema": "daedalus-remote-branch-consolidation/1",
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "repository": REPO,
        "trigger_sha": os.environ.get("GITHUB_SHA"),
        "policy": {
            "target_branch_count": 11,
            "force_updates": False,
            "history_rewrites": False,
            "delete_only_after_manifest": True,
        },
        "keep_branches": {name: before[name] for name in KEEP},
        "retired_branches": dict(sorted(retire.items())),
        "open_prs_to_archive": archive_prs,
    }
    persist_manifest(manifest)
    print(f"persisted recovery manifest for {len(before)} branches; retiring {len(retire)}")

    after_manifest = branches()
    if set(after_manifest) != set(before):
        raise SystemExit("branch set changed after inventory; refusing deletion")
    for name, sha in before.items():
        if name != "main" and after_manifest.get(name) != sha:
            raise SystemExit(f"branch moved after inventory: {name}")

    for number, head, base in open_prs():
        if head in KEEP_SET:
            if base not in KEEP_SET:
                raise SystemExit(f"PR #{number} gained retiring base {base}")
            continue
        body = (
            "Repository branch consolidation: this PR is archived without merge. "
            f"Its head `{head}` and exact pre-deletion SHA are preserved in "
            f"`{MANIFEST_PATH}`. This is not a claim that the code was integrated; "
            "unverified unique work remains selectively recoverable/portable from the recorded SHA. "
            "The active repository topology is being reduced to the owner-approved 11 canonical lines under #42."
        )
        run([
            "gh", "api", "-X", "POST", f"repos/{REPO}/issues/{number}/comments",
            "-f", f"body={body}",
        ])
        run([
            "gh", "api", "-X", "PATCH", f"repos/{REPO}/pulls/{number}",
            "-f", "state=closed",
        ])
        print(f"archived PR #{number}: {head} -> {base}")

    for number, head, base in open_prs():
        if head not in KEEP_SET or base not in KEEP_SET:
            raise SystemExit(f"unsafe open PR remains: #{number} {head}->{base}")

    failures: list[dict[str, str]] = []
    for name in sorted(retire):
        cp = run(
            ["gh", "api", "-X", "DELETE", f"repos/{REPO}/git/refs/heads/{name}"],
            check=False,
        )
        if cp.returncode != 0:
            failures.append({"branch": name, "stderr": cp.stderr[-1000:]})
        else:
            print(f"deleted branch: {name}")

    final = branches()
    if failures:
        print(json.dumps({"delete_failures": failures}, indent=2), file=sys.stderr)
    if set(final) != KEEP_SET or len(final) != 11:
        extra = sorted(set(final) - KEEP_SET)
        missing_final = sorted(KEEP_SET - set(final))
        raise SystemExit(
            f"final topology mismatch: count={len(final)} extra={extra} missing={missing_final}"
        )

    print("branch consolidation complete: exactly 11 canonical remote branches remain")
    for name in KEEP:
        print(f"KEEP {name} {final[name]}")


if __name__ == "__main__":
    main()
