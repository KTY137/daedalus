#!/usr/bin/env python3
"""Does the prose still point at files that exist?

WHY THIS EXISTS. Documentation rots in one specific, mechanical way long before
it rots in an interesting way: a package is reorganised, a script is retired, a
directory is archived -- and every sentence naming the old path keeps reading
like an instruction. On 2026-08-25 a sweep found ``eval/harness.py``,
``tools/vet.py`` and ``daedalus/spine/promotion_approval.py`` still named in
current pages, long after they had moved to ``daedalus/eval/``,
``daedalus/tools/`` and ``daedalus/kernel/promotion_trust_root.py``. Nothing was
lying; every sentence was simply addressed to a tree that no longer exists.

WHAT IT REFUSES TO DO. It does not judge prose, and it does not fail on history.
``docs/archive/``, ``docs/inventory/``, ``docs/recovery/``, ``docs/missions/``
and the rest of the dated evidence are *supposed* to name paths that are gone --
that is what makes them evidence of what was true then. They are counted and
reported, never blocking.

AND IT CAN SAY IT DID NOT MEASURE. A checker that finds nothing because it
looked at nothing must not be indistinguishable from a clean tree. If the file
census comes back empty this exits 2 with COULD NOT MEASURE, which is a
different outcome from the exit 0 of a clean sweep.

Usage:
    python tools/docs_reference_check.py            # current docs must be clean
    python tools/docs_reference_check.py --all      # include history in the report
    python tools/docs_reference_check.py --json     # machine-readable
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# This file is advertised as `python tools/docs_reference_check.py` (see the
# usage block above), which puts tools/ on sys.path and NOT the repository
# root, so the effect-boundary import inside main() cannot find `daedalus`.
# Module level is the only place this can be fixed: the boundary probe in
# tests/test_registry_new_doors.py requires begin_effect to precede every
# other call in main, so a sys.path repair inside the function would be a
# call above the boundary.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The constitution and its chain. NEVER blocking, and not because they are
# unimportant -- because AGENTS.md forbids an ordinary session from editing
# them ("Ordinary tasks must not edit the plan, amendment chain, active
# instructions, or guards"). A checker that can demand an edit no ordinary
# session may make is a checker that will eventually be satisfied by someone
# making it. They are still reported, under their own heading.
AUTHORITY = (
    "docs/IKARUS_ARIADNE_MASTER_PLAN.md",
    "docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl",
    "docs/DAEDALUS_GESAMTPLAN.md",
    "AGENTS.md",
    "CLAUDE.md",
)

# Dated evidence. These pages describe a tree as it was; a dead path in them is
# the point, not a defect. The plan's authority table settles which is which:
# "ADRs, TODOs, handoffs, inventories | history/backlog | supply evidence and
# proposals". History is a KIND, not only a directory -- docs/HANDOFF.md sits at
# the top level and is as frozen as anything under docs/archive/.
HISTORY_PREFIXES = (
    "docs/archive/",
    "docs/architecture_history/",
    "docs/decisions-taken/",
    "docs/inventory/",
    "docs/missions/",
    "docs/recovery/",
    "docs/research/",
    "docs/superpowers/specs/",
    "docs/work-packets/",
    "docs/adrs/",
    # A plan names the modules it intends to create. Those paths are supposed
    # not to exist yet; failing on them would make the checker punish planning.
    "docs/design/",
    "experiments/",
    "runs/",
    "vault/",
    ".room/",
)

# ... and by name, for the history that lives at the top level.
#
# The date patterns are anchored to `20xx` ON PURPOSE. The first version of this
# file used a bare `\d{8}` and `\d{4}-\d{2}-\d{2}`, which quietly reclassified
# `RFC12345678_current_contract.md` and `schema-1234-56-78.md` as history --
# and a page reclassified as history STOPS BEING CHECKED. That is this
# checker committing the exact failure it was written to catch: drifting
# toward less coverage and reporting the result as clean. Widen these only
# with a case in `tests/test_docs_reference_check.py` that shows what the
# widening buys.
HISTORY_NAME_PATTERNS = (
    re.compile(r"(?:^|/)HANDOFF"),                 # frozen, append-only
    re.compile(r"(?:^|/)AMENDMENT_PROPOSAL_"),     # a proposal describes the tree it was written against
    re.compile(r"(?:^|/)GATE\d[\w]*_"),            # dated gate findings and decisions
    re.compile(r"(?<!\d)20\d{6}(?!\d)"),           # ..._20260817.md
    re.compile(r"(?<!\d)20\d{2}-\d{2}-\d{2}(?!\d)"),  # ..._2026-07-30_NIGHT.md
)

# Deliberate mentions. Each entry is (file, path-as-written) -> why, and each one
# has to earn its line: an allowlist that grows without reasons is how a checker
# stops checking.
ALLOWED = {
    ("README.md", "docs/CODEX_QUEUE.md"):
        "a file the TARGET repo creates; the README says so in the same sentence",
    ("README.md", ".agentenv/agents/"):
        "a path inside the target repo, not in this one",
    ("docs/PROJECT_SCOPE.md", "docs/a/b/c.py"): "illustrative path in an example",
    ("docs/adrs/README.md", "docs/adrs/NNN-slug.md"): "the naming template, not a file",
    # STATUS.md names these BECAUSE they are gone: the report is that the
    # mechanical veto policy still lists three files that no longer exist.
    # Repairing the mention would delete the finding.
    ("docs/STATUS.md", "tools/iron_plan_guard.py"): "reported as a dead entry in agentenv.json",
    ("docs/STATUS.md", "tools/iron_plan_hook_runner.py"): "reported as a dead entry in agentenv.json",
    ("docs/STATUS.md", "tests/test_iron_plan_guard.py"): "reported as a dead entry in agentenv.json",
    ("docs/PROJECT_SCOPE.md", "docs/c.py"): "illustrative path in an example",
    ("docs/ENGINE_PARITY.md", "docs/vendor"): "illustrative path in an example",
    ("docs/ENGINE_PARITY.md", "docs/vendor/x.py"): "illustrative path in an example",
    (".claude/proposals/README.md", "vault/Sessions/YYYY-MM-DD.md"): "date template",
    (".claude/skills/vault-sync/SKILL.md", "vault/Sessions/YYYY-MM-DD.md"): "date template",
    (".claude/proposals/README.md", ".claude/settings.local.json"):
        "an optional operator-local file the proposal explicitly tells the reader to create",
    ("docs/DESKTOP.md", "projects/daedalus.json"):
        "runtime state seeded below the external profile root, not a repository file",
    ("docs/DESKTOP.md", "daedalus/openvscode-server"):
        "a local Docker image tag, not a repository path",
    ("packaging/openvscode/README.md", "vscode-agent-env/dist/daedalus-vscode.vsix"):
        "a build artifact the Dockerfile copies; it exists after packaging, not in the tree",
    # These two name App.tsx BECAUSE it is gone: G1-UI-02 retired the Classic
    # app in e133e09b, and both pages cite the old path to say what the current
    # pointer replaced. Repairing the mention would delete the provenance.
    ("docs/MISSION_CONTROL.md", "apps/web/src/App.tsx"):
        "cited as the retired predecessor of apps/web/src/app/Cockpit.tsx (e133e09b)",
    ("vscode-agent-env/DESIGN.md", "apps/web/src/App.tsx"):
        "cited as the retired surface whose behaviour two paragraphs here assumed (e133e09b)",
    ("docs/chip-design/README.md", ".agentenv/chip-eda-policy.json"):
        "an operator-owned authority-root policy path; the page explicitly records that it is absent here",
    ("docs/chip-design/WORKFLOWS.md", ".agentenv/chip-eda-policy.json"):
        "an operator-owned authority-root policy path; the retained dry run explicitly records its absence",
    ("docs/architecture-narrative.md", "daedalus/hermes/"):
        "named precisely as a removed bytecode husk in the same sentence",
    # Quoted precisely BECAUSE they are wrong: the page is about a tier that
    # invented plausible module paths. Repairing them would delete the evidence.
    (".claude/skills/funnel/SKILL.md", "daedalus/core/process.py"): "quoted hallucination",
    (".claude/skills/funnel/SKILL.md", "daedalus/eval/picker.py"): "quoted hallucination",
    (".claude/skills/funnel/SKILL.md", "daedalus/gate_discrimination.py"): "quoted hallucination",
    # Paths inside OTHER repositories, named as such in the same sentence.
    ("docs/GUI_CATALOGUE.md", "apps/origin/"): "a path in the Origin UI repository",
    ("docs/GUI_CATALOGUE.md", "apps/ui/"): "a path in the Origin UI repository",
    ("docs/GUI_CATALOGUE.md", ".claude/skills/build-gui/"):
        "a proposal under the heading 'What it would be', explicitly not implemented",
    # Same shape as the STATUS.md entries above: the page names this directory
    # BECAUSE it is gone. G1-UI-04 removed twelve catalogue entries whose
    # source_path pointed here after e133e09b deleted it, and section 5 records
    # what was lost and where it is recoverable. Repairing the mention would
    # delete the record of the loss.
    ("docs/GUI_CATALOGUE.md", "apps/web/src/components/glass/"):
        "named precisely as the directory e133e09b deleted; the section is the record of the removal",
}

MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
BACKTICK = re.compile(r"`([^`\n]+)`")
# Only paths that clearly address THIS repository. A bare `foo.py` is prose.
REPO_PATH = re.compile(
    r"^(?:docs|daedalus|tools|tests|scripts|configs|agents|templates|projects|apps|eval"
    r"|experiments|structcore-rs|vscode-agent-env|\.agentenv|\.claude|\.githooks)"
    r"/[\w./*\-]+$"
)


def _is_authority(rel: str) -> bool:
    return rel.replace("\\", "/") in AUTHORITY


def _is_history(rel: str) -> bool:
    rel = rel.replace("\\", "/")
    if rel in AUTHORITY:
        return True
    if rel.startswith(HISTORY_PREFIXES):
        return True
    return any(pattern.search(rel) for pattern in HISTORY_NAME_PATTERNS)


def _tracked_markdown() -> list:
    try:
        out = subprocess.run(
            ["git", "ls-files", "--", "*.md"], cwd=ROOT, capture_output=True, text=True
        )
    except OSError:
        # git itself is absent. The docstring names this cause; before it was
        # caught, the exception propagated and exited 1 -- the same code as
        # "dead references found", so a caller branching on the exit code could
        # not tell a finding from a dead instrument.
        return []
    if out.returncode != 0:
        return []
    return [line.strip() for line in out.stdout.splitlines() if line.strip()]


def _resolve_candidates(name: str) -> list:
    """Where did this basename go? Best-effort, for the repair hint only."""
    try:
        out = subprocess.run(
            # ``--`` matters: a link basename beginning with "-" would
            # otherwise be parsed by git as an option. None of ls-files'
            # options write, execute or reach the network, so this is a class
            # closed rather than a hole patched -- but it costs one token.
            ["git", "ls-files", "--", "*/" + name, name],
            cwd=ROOT, capture_output=True, text=True,
        )
    except OSError:
        return []
    if out.returncode != 0:
        return []
    return [line.strip() for line in out.stdout.splitlines() if line.strip()][:3]


def scan() -> dict:
    files = _tracked_markdown()
    findings = []
    unreadable = []
    read_count = 0
    for rel in files:
        path = ROOT / rel
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            # Counted, never swallowed. `scanned` used to be len(files) -- the
            # GIT LISTING -- so a census where every file failed to open
            # reported "scanned N, clean" and exited 0. That is the precise
            # failure this file's docstring forbids, committed in this file,
            # found by an adversarial reviewer on 2026-08-25.
            unreadable.append(rel)
            continue
        read_count += 1
        base = path.parent
        seen = set()

        for match in MD_LINK.finditer(text):
            target = match.group(1)
            if target.startswith(("http://", "https://", "#", "mailto:", "<")):
                continue
            target = target.split("#", 1)[0]
            if not target or ":" in target[:3]:  # absolute Windows path -> scratch
                continue
            if (base / target).exists():
                continue
            key = ("link", target)
            if key in seen:
                continue
            seen.add(key)
            findings.append({"file": rel, "kind": "link", "target": target,
                             "history": _is_history(rel),
                             "authority": _is_authority(rel)})

        for match in BACKTICK.finditer(text):
            target = match.group(1).strip()
            if not REPO_PATH.match(target) or "*" in target:
                continue
            if (ROOT / target).exists():
                continue
            if (rel, target) in ALLOWED:
                continue
            key = ("mention", target)
            if key in seen:
                continue
            seen.add(key)
            findings.append({"file": rel, "kind": "mention", "target": target,
                             "history": _is_history(rel),
                             "authority": _is_authority(rel)})

    return {"scanned": read_count, "listed": len(files),
            "unreadable": unreadable, "findings": findings}


def main(argv=None) -> int:
    # THE BOUNDARY COMES FIRST -- above parse_args, the c67fd116 shape.
    #
    # This reporter writes nothing; it spawns. scan() -> _tracked_markdown()
    # and _resolve_candidates() both run git through subprocess.run, once per
    # candidate name, so a large tree turns one invocation into many child
    # processes. PROCESS_SPAWN is the whole declaration: no file is created, no
    # socket is opened, and no credential is read on this path, which is why
    # the row does not carry the effect set its neighbours in tools/ do.
    from daedalus.budget import process_guard_boundary_decision
    from daedalus.spine.effect_boundary import REGISTRY_BY_ID, begin_effect

    begin_effect(
        "tools.docs_reference_check",
        REGISTRY_BY_ID["tools.docs_reference_check"].effects,
        (process_guard_boundary_decision(),),
    )

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true",
                        help="report history pages too (never blocking)")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args(argv)

    result = scan()
    listed = result.get("listed", 0)
    unreadable = result.get("unreadable", [])
    if result["scanned"] == 0:
        if listed:
            message = ("COULD NOT MEASURE: {} markdown files are tracked and none "
                       "could be read. The census is not empty -- the reads "
                       "failed. This is not a clean result.".format(listed))
        else:
            message = ("COULD NOT MEASURE: 'git ls-files -- *.md' returned nothing. "
                       "Not a git checkout, or git is unavailable. This is not a "
                       "clean result.")
        if args.json:
            print(json.dumps({"status": "could-not-measure", "reason": message,
                              "listed": listed,
                              "unreadable": unreadable[:20]}, indent=1))
        else:
            print(message, file=sys.stderr)
        return 2

    if unreadable:
        # A partial sweep is not a sweep. Reporting "clean" over the files that
        # happened to open is how a shrinking census passes for a healthy tree.
        _nl = chr(10)
        message = (
            "COULD NOT MEASURE: read {} of {} tracked markdown files; {} "
            "could not be opened. A partial census cannot report clean."
            .format(result["scanned"], listed, len(unreadable))
            + _nl + "  " + (_nl + "  ").join(unreadable[:20])
        )
        if args.json:
            print(json.dumps({"status": "could-not-measure", "reason": message,
                              "scanned": result["scanned"], "listed": listed,
                              "unreadable": unreadable[:20]}, indent=1))
        else:
            print(message, file=sys.stderr)
        return 2

    current = [f for f in result["findings"] if not f["history"]]
    authority = [f for f in result["findings"] if f.get("authority")]
    history = [f for f in result["findings"] if f["history"] and not f.get("authority")]

    if args.json:
        print(json.dumps({
            "status": "measured",
            "scanned": result["scanned"],
            "listed": listed,
            "current": current,
            "authority": authority,
            "history_count": len(history),
            "history": history if args.all else None,
        }, indent=1))
        return 1 if current else 0

    print("scanned {} of {} tracked markdown files".format(result["scanned"], listed))
    shown = current + (history if args.all else [])
    if authority:
        print("")
        print("AUTHORITY pages name {} path(s) that do not exist. Reported, never "
              "blocking: only an owner amendment may edit these.".format(len(authority)))
        for f in authority:
            print("  {}: {}".format(f["file"], f["target"]))

    if not shown:
        print("current pages: clean. history pages: {} dead references, "
              "which is what evidence looks like.".format(len(history)))
        return 0

    by_file = {}
    for finding in shown:
        by_file.setdefault(finding["file"], []).append(finding)
    for rel in sorted(by_file):
        tag = " [history, not blocking]" if _is_history(rel) else ""
        print("\n{}{}".format(rel, tag))
        for finding in sorted(by_file[rel], key=lambda f: f["target"]):
            moved = _resolve_candidates(Path(finding["target"]).name)
            if len(moved) == 1:
                hint = "  -> now at " + moved[0]
            elif moved:
                hint = "  -> candidates: " + ", ".join(moved)
            else:
                hint = "  -> no file of that name anywhere"
            print("  {:8s} {}{}".format(finding["kind"], finding["target"], hint))

    print("\n{} dead reference(s) in current pages, {} in history (not blocking)."
          .format(len(current), len(history)))
    return 1 if current else 0


if __name__ == "__main__":
    raise SystemExit(main())
