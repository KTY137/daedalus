"""Portable per-repo config resolution.

To run the bench against ANY repo, the safety policy travels *with that repo*.
Resolution order:
  1. explicit --project from the registry (projects/<name>.json), else
  2. a repo-local `.agentenv/agentenv.json` in the target repo, else
  3. None -> fail-closed: the bench may read/advise but never write.

The file shape mirrors a project entry:
    {"policy": {...}, "test_command", "test_cwd", "test_timeout_s"}

``test_timeout_s`` is the verify gate's runaway budget for ``test_command``, in
seconds. Omit it and the gate uses ``verifier.DEFAULT_TEST_TIMEOUT_S`` (120), so
a repo that never declares one keeps exactly the behaviour it had before this
key existed -- a silent re-timing of every other repo's gate is not acceptable.
Declare it when the repo's suite genuinely needs longer than 120 s; a suite that
cannot finish inside the budget is killed and the gate reports ``status:
"timeout"``, which blocks the write but is NOT a test failure.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_CONFIG = ".agentenv/agentenv.json"
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"

STARTER: dict = {
    "_comment": "daedalus policy for THIS repo. Generic secret protections are "
                "always merged in; add your own denies. With no 'policy' block, "
                "the bench is read/advise-only (fail-closed). Edit, then run `daedalus doctor`.",
    "policy": {
        "deny": ["secret", "credential", ".env", "id_rsa", ".pem"],
        "allow": ["docs/", "/tests/", "test_", ".md", "readme"],
        "allow_exceptions": ["_simulated.py"],
        "high_risk_paths": [],
        "high_risk_terms": ["delete", "drop table", "migration", "auth",
                            "payment", "production", "deploy"],
        "deny_content": []
    },
    "test_command": None,   # opt-in: a fresh repo has no suite -- don't gate writes on a nonexistent one
    "test_cwd": ".",
    # Runaway budget for test_command, in seconds. Stated explicitly (rather
    # than left absent) so the knob is discoverable in every scaffolded repo,
    # and set to the SAME value as verifier.DEFAULT_TEST_TIMEOUT_S so writing
    # the starter file changes no behaviour. Raise it if your suite is slower
    # than this; a suite that overruns is killed and blocks the write.
    "test_timeout_s": 120
}


def _repo_local_policy(repo_root: str | None) -> dict | None:
    """The `policy` block a repository declares ABOUT ITSELF, or None."""
    if not repo_root:
        return None
    f = Path(repo_root) / REPO_CONFIG
    if not f.exists():
        return None
    try:
        return (json.loads(f.read_text(encoding="utf-8")) or {}).get("policy") or None
    except (OSError, json.JSONDecodeError):
        return None


def _apply_repo_confinement(data: dict | None, repo_root: str) -> dict | None:
    """Fold a repo's own confinement into a registry entry that shadowed it.

    MEASURED, and this is why the function exists: naming a project dropped the
    target repo's write confinement completely::

        resolve_project(root, None)         -> write_allow ('docs/','tests/','readme.md')
        resolve_project(root, "agent_env")  -> write_allow ()  == UNCONFINED

    Under `--project agent_env`, `daedalus/sensitivity.py` (the egress fence),
    `daedalus/config.py` (this file, which loads the policy) and
    `.agentenv/agentenv.json` (the policy itself) were all writable by the local
    model. Registry entries predate `write_allow` and simply do not carry one,
    so every one of them silently unconfined its target.

    The invariant restored: **naming a project must never grant more write
    permission than not naming one.** A repository's statement about itself is
    not the caller's to discard, which is the same "extend, never weaken"
    discipline `sensitivity.load_policy` already applies to the generic secret
    and high-blast-radius floors.

    The repo consulted is the one that will actually be WRITTEN -- the registry
    entry's own `repo_root` when it has one, not the caller's cwd.
    """
    if not data:
        return data
    local = _repo_local_policy(data.get("repo_root") or repo_root)
    if not local:
        return data
    from .sensitivity import intersect_write_allow

    policy = dict(data.get("policy") or {})
    merged = intersect_write_allow(local.get("write_allow") or (),
                                   policy.get("write_allow") or ())
    if merged:
        policy["write_allow"] = list(merged)
    # Unioned, never intersected: high-risk paths and denies are floors, and a
    # floor declared in either place must hold in both.
    for key in ("high_risk_paths", "deny"):
        union = list(dict.fromkeys(
            list(local.get(key) or ()) + list(policy.get(key) or ())))
        if union:
            policy[key] = union
    if policy:
        data = dict(data)
        data["policy"] = policy
    return data


def resolve_project(repo_root: str, project: str | None = None) -> dict | None:
    """Return a project-config dict (with a 'policy' block) or None."""
    if project:
        from .projects import load_project
        return _apply_repo_confinement(load_project(project), repo_root)
    f = Path(repo_root) / REPO_CONFIG
    if f.exists():
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        data.setdefault("repo_root", str(Path(repo_root).resolve()))
        return data
    return None


def _copy_template_agents(agentenv_dir: Path) -> None:
    """Seed `<repo>/.agentenv/agents/` with the generic template roles.

    Copies `templates/agents/*.json` into the repo. Existing files are never
    overwritten, so per-repo customizations survive a re-run of `init_repo`.
    """
    src = TEMPLATE_DIR / "agents"
    if not src.is_dir():
        return
    dst = agentenv_dir / "agents"
    dst.mkdir(exist_ok=True)
    for path in sorted(src.glob("*.json")):
        target = dst / path.name
        if not target.exists():
            target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


TOOL_INSTRUCTION_TEMPLATES = ("CLAUDE.md", "AGENTS.md")


def _copy_tool_instructions(repo_root: Path) -> None:
    """Drop per-tool instruction files into the target repo root.

    `templates/CLAUDE.md` (for Claude Code) and `templates/AGENTS.md` (for
    Codex) tell each tool to route delegable work through the harness. Only
    templates that exist are copied, and existing target files are never
    overwritten, so per-repo customizations survive a re-run of `init_repo`.
    """
    for name in TOOL_INSTRUCTION_TEMPLATES:
        src = TEMPLATE_DIR / name
        if not src.exists():
            continue
        target = repo_root / name
        if not target.exists():
            target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")


def init_repo(repo_root: str) -> str:
    """Scaffold `.agentenv/agentenv.json` in a repo. Returns the path written."""
    d = Path(repo_root) / ".agentenv"
    d.mkdir(exist_ok=True)
    f = d / "agentenv.json"
    if not f.exists():
        f.write_text(json.dumps(STARTER, indent=2), encoding="utf-8")
    _copy_template_agents(d)
    _copy_tool_instructions(Path(repo_root))
    return str(f)
