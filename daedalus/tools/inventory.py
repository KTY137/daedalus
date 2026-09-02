"""inventory.py — what tools exist on this machine, and what they are cleared for.

``skills.py`` could parse a ``SKILL.md`` and had no consumer but its own tests;
``control_plane.py`` could list the MCP servers in ``.mcp.json`` and did nothing
with them. This module is the seam: one derived, deterministic inventory of every
skill and MCP server visible from a project, each carrying the ``vet`` verdict
that decides whether an agent may be given it.

Derived, never hand-maintained — regenerate and it is true by construction, the
same contract ``structcore`` holds for the code index.

WHAT IT DOES NOT DO
-------------------
It does not install, enable, start or route. It reads files and returns data.
Provisioning is a separate lane, and capability routing belongs to
``provider_router``, which already owns lane policy — wiring it from here would
put a second policy owner in the tree, which is exactly what ADR-002 and ADR-017
had to rip out.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..foundation import skills as skills_mod
from . import vet as vet_mod

INVENTORY_VERSION = "1"

#: Where skills live, in precedence order. Project scope wins over user scope on
#: a name collision, and BOTH are reported so a shadowed skill is visible rather
#: than silently absent.
SKILL_SCOPES = (
    ("project", ".claude/skills"),
    ("project", ".agentenv/skills"),
)
USER_SKILL_DIRS = ("~/.claude/skills",)

#: MCP configuration files, in the order a client would merge them.
MCP_SCOPES = (
    ("project", ".mcp.json"),
    ("user", "~/.claude.json"),
)


@dataclass(frozen=True)
class ToolRecord:
    """One tool, with its provenance and its verdict."""
    name: str
    kind: str                 # "skill" | "mcp_server"
    scope: str                # "project" | "user"
    source: str               # the file or directory it was read from
    verdict: dict             # vet.Verdict.to_dict()
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "scope": self.scope,
                "source": self.source, "verdict": self.verdict, "detail": self.detail}


def _read_json(path: Path) -> tuple[dict, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return {}, None                        # absent is not an error
    except (OSError, json.JSONDecodeError) as exc:
        # A malformed config is reported, never skipped: "we could not read the
        # tool list" must never render as "there are no tools".
        return {}, f"{path}: {exc.__class__.__name__}: {exc}"


def collect_skills(repo_root: str | Path, *, include_user: bool = True) -> tuple[list[ToolRecord], list[str]]:
    root = Path(repo_root).resolve()
    records: list[ToolRecord] = []
    errors: list[str] = []
    # (name, root) -- the annotation said ``set[str]`` while the code put tuples
    # in it, which is how the key's actual shape stopped being anybody's business.
    seen: set[tuple[str, str]] = set()

    allowances, allow_err = vet_mod.load_allowances(root)
    errors.extend(allow_err)

    roots: list[tuple[str, Path]] = [(scope, root / rel) for scope, rel in SKILL_SCOPES]
    if include_user:
        roots += [("user", Path(p).expanduser()) for p in USER_SKILL_DIRS]

    for scope, sroot in roots:
        if not sroot.is_dir():
            continue
        report = skills_mod.discover(sroot)
        for defect in getattr(report, "defects", ()) or ():
            errors.append(f"{sroot}: {getattr(defect, 'directory', '?')}: "
                          f"{'; '.join(getattr(defect, 'problems', ()) or ['unspecified defect'])}")
        for sk in sorted(getattr(report, "skills", ()) or (), key=lambda s: s.name):
            # KEYED ON THE ROOT, not on the scope label.
            #
            # ADVERSARIAL REVIEW 2026-07-30 (Cerberus, high 7). ``SKILL_SCOPES``
            # labels BOTH ``.claude/skills`` and ``.agentenv/skills`` as
            # "project", so a skill of the same name in the second directory
            # produced the key that the first had already claimed and was
            # ``continue``d past -- never vetted, never in the inventory, never
            # reported as shadowed. A hostile skill became invisible to the trust
            # gate by choosing a name that already existed.
            #
            # The comment above ``SKILL_SCOPES`` says "BOTH are reported so a
            # shadowed skill is visible rather than silently absent". This makes
            # that true. Keying on the root still collapses a genuine duplicate
            # (the same directory scanned twice) and no longer collapses two
            # different files that happen to share a name -- which is the only
            # thing the key was ever meant to do, since precedence is expressed
            # by ORDER in ``roots`` and not by this set.
            key = (sk.name, str(sroot))
            if key in seen:
                continue
            seen.add(key)
            v = vet_mod.vet_skill(sk, allowances=allowances)
            records.append(ToolRecord(
                name=sk.name, kind="skill", scope=scope, source=str(sk.source),
                verdict=v.to_dict(),
                detail={
                    "description": sk.description[:400],
                    "bundled_files": len(sk.bundled_paths),
                    "bundles_code": sk.bundles_code,
                    "script_files": len(sk.script_paths),
                    "licence_declared": sk.licence_declared,
                    "body_sha256": sk.body_sha256,
                },
            ))
    return records, errors


def collect_mcp_servers(repo_root: str | Path, *, include_user: bool = True) -> tuple[list[ToolRecord], list[str]]:
    root = Path(repo_root).resolve()
    records: list[ToolRecord] = []
    errors: list[str] = []
    allowances, allow_err = vet_mod.load_allowances(root)
    errors.extend(allow_err)

    for scope, rel in MCP_SCOPES:
        if scope == "user" and not include_user:
            continue
        path = Path(rel).expanduser() if rel.startswith("~") else root / rel
        data, err = _read_json(path)
        if err:
            errors.append(err)
            continue
        servers = data.get("mcpServers")
        if not isinstance(servers, dict):
            continue
        for name in sorted(servers):
            spec = servers[name]
            v = vet_mod.vet_mcp_server(name, spec, allowances=allowances)
            records.append(ToolRecord(
                name=name, kind="mcp_server", scope=scope, source=str(path),
                verdict=v.to_dict(),
                detail={
                    "command": (spec.get("command") if isinstance(spec, dict) else None),
                    "args": [str(a) for a in (spec.get("args") or [])] if isinstance(spec, dict) else [],
                    "has_env": bool(isinstance(spec, dict) and spec.get("env")),
                },
            ))
    return records, errors


def build(repo_root: str | Path, *, include_user: bool = True) -> dict:
    """The whole inventory. Deterministic: every list sorted by (kind, scope, name)."""
    sk, sk_err = collect_skills(repo_root, include_user=include_user)
    mc, mc_err = collect_mcp_servers(repo_root, include_user=include_user)
    records = sorted(sk + mc, key=lambda r: (r.kind, r.scope, r.name))

    verdict_objs = []
    for r in records:
        v = r.verdict
        verdict_objs.append(_Shim(v["subject"], v["outcome"], v["cleared"]))

    return {
        "version": INVENTORY_VERSION,
        "vet_version": vet_mod.VET_VERSION,
        "root": str(Path(repo_root).resolve()),
        "include_user_scope": include_user,
        "tools": [r.to_dict() for r in records],
        "summary": {
            "skills": sum(1 for r in records if r.kind == "skill"),
            "mcp_servers": sum(1 for r in records if r.kind == "mcp_server"),
            **_summary(verdict_objs),
        },
        # Read errors are NEVER folded into the summary counts. "Could not read
        # the tool list" and "there are no tools" produce the same empty list,
        # and a caller must be able to tell them apart.
        #
        # DEDUPED, because `load_allowances` is called by BOTH collectors above
        # and so reports every problem in the allowance file twice. Two
        # identical strings here are one fact counted twice -- the message
        # carries its own file path, so equal strings mean equal findings.
        "errors": sorted(set(sk_err) | set(mc_err)),
        "degraded": bool(sk_err or mc_err),
    }


@dataclass(frozen=True)
class _Shim:
    """Minimal stand-in so ``vet.summarise`` can score dicts we already rendered."""
    subject: str
    outcome: str
    cleared: bool


def _summary(objs) -> dict:
    s = vet_mod.summarise(objs)
    s.pop("version", None)
    return s


def render(inv: dict) -> str:
    """A flat table for a terminal. The verdict column is the point."""
    tools = inv["tools"]
    if not tools:
        head = "no tools found"
        return head + (" — BUT this report is not the whole truth:\n  "
                       + "\n  ".join(inv["errors"])
                       if inv["degraded"] else " (and every source was read cleanly)")
    w = max(len(t["name"]) for t in tools) + 2
    lines = ["KIND         SCOPE     " + "NAME".ljust(w) + "VERDICT       FINDINGS  SOURCE"]
    lines.append("-" * (44 + w + 30))
    for t in tools:
        v = t["verdict"]
        lines.append(
            f"{t['kind']:<12} {t['scope']:<9} {t['name'].ljust(w)}"
            f"{v['outcome']:<14}{len(v['findings']):>8}  {t['source']}"
        )
    s = inv["summary"]
    lines.append("")
    lines.append(f"{s['skills']} skill(s), {s['mcp_servers']} MCP server(s); "
                 f"cleared {len(s['cleared'])}, review {s['by_outcome'].get('review', 0)}, "
                 f"blocking {len(s['blocking'])}, unscannable {len(s['unscannable'])}")
    if s["blocking"]:
        lines.append("BLOCKING: " + ", ".join(s["blocking"]))
    if s["unscannable"]:
        lines.append("UNSCANNABLE (not the same as clean): " + ", ".join(s["unscannable"]))
    if inv["degraded"]:
        # NOT "some sources could not be read". That was true of every entry in
        # this list until an inert allowance could land here too, and an
        # allowance that does nothing is a config defect in a file that read
        # perfectly. A heading that names the wrong cause is the same defect
        # class this gate exists to catch, so it names the consequence instead
        # and lets each message state its own cause.
        lines.append("DEGRADED — this report is not the whole truth:")
        lines += ["  " + e for e in inv["errors"]]
    return "\n".join(lines)


def main(argv: list[str]) -> int:  # pragma: no cover - thin CLI
    root = argv[0] if argv else "."
    as_json = "--json" in argv
    inv = build(root)
    print(json.dumps(inv, indent=1) if as_json else render(inv))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    raise SystemExit(main(sys.argv[1:]))
