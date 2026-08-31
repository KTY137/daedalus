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

``write_wave_policy`` currently resolves only to ``"never"``. Historical
``"low_risk"`` and ``"always"`` values are treated as denied input, not as
permission: candidates may be nominated automatically, but production
promotion requires an explicit owner action.
"""

from __future__ import annotations

import json
from pathlib import Path

from .resources import iter_builtin_files, read_builtin_text

REPO_CONFIG = ".agentenv/agentenv.json"
TEMPLATE_DIR = Path(__file__).resolve().parents[1] / "templates"

# --------------------------------------------------------------------------- #
# write_wave_policy: production candidates always wait for an owner.          #
# --------------------------------------------------------------------------- #
# Older releases exposed low_risk/always. Accepting those values would still
# call promote_candidates without an owner at the candidate -> integration
# boundary, which violates the sealed-promotion invariant even though primary
# checkout merge remained manual. The production vocabulary is therefore
# deliberately one value. Experimental auto-promotion must be simulated as a
# "would nominate" result in an isolated campaign, never wired to this path.
WRITE_WAVE_POLICY_LEVELS = ("never",)
#: Fail-closed default for a project config that omits the key, or sets an
#: unrecognized value -- e.g. a typo, or a value from a future level this
#: version of the code does not know about. Absence (or garbage) must never
#: be read as permission.
DEFAULT_WRITE_WAVE_POLICY = "never"


def resolve_write_wave_policy(pdata: dict | None) -> str:
    """Resolve the sealed production write-wave policy.

    ``pdata`` is a project dict as returned by :func:`resolve_project` (or
    ``None``). Missing, legacy, malformed, or future values all resolve to
    ``"never"``. Configuration cannot grant automatic promotion.
    """
    raw = (pdata or {}).get("write_wave_policy")
    if raw in WRITE_WAVE_POLICY_LEVELS:
        return raw
    return DEFAULT_WRITE_WAVE_POLICY


# --------------------------------------------------------------------------- #
# external_write_lanes: may an UNTRUSTED external provider APPLY a change,     #
# or only advise?                                                             #
# --------------------------------------------------------------------------- #
# Every external lane has always been advisory-only: it reads (what egress
# permits), proposes, and a trusted lane applies. This key is the operator's
# opt-in to let a NAMED external lane land its own full-file rewrite instead.
#
# It is a LIST OF LANE NAMES rather than a bool because "external writes" is not
# one decision -- enabling DeepSeek must not silently enable a lane added next
# year. Unknown names are DISCARDED (see below), so the config cannot grant a
# permission this version of the code does not implement.
#
# What it does NOT do, and this matters because the key reads more permissive
# than it is:
#   * it does not widen EGRESS. A named lane still only receives bytes
#     `daedalus.sensitivity.classify_data` already permits (the repo's `allow` /
#     `default_deny` keys). Denylisted content is refused before any prompt.
#   * it does not widen WRITE CONFINEMENT. A named lane may still only touch
#     paths `write_allow` permits; `path_write_blocked` guards every target.
#   * it does not reach MID or HIGH change-risk, and never a review-only task.
#     `provider_router._mode` ANDs this key with risk == "low".
#   * it does not skip the verify gate, and the provider keeps a byte-exact
#     rollback of every file it touched.
# It is also PAID: a lane named here spends real money per file rewritten.
KNOWN_EXTERNAL_WRITE_LANES = ("deepseek",)
#: Fail-closed default for a config that omits the key, or sets something that
#: is not a list of known lane names -- a typo, a bool, a bare string, a lane
#: from a future version. Absence (or garbage) must never be read as permission,
#: and a name we do not recognize must never be read as one we do.
DEFAULT_EXTERNAL_WRITE_LANES: tuple[str, ...] = ()


def resolve_external_write_lanes(pdata: dict | None) -> tuple[str, ...]:
    """The external lanes a resolved project config permits to WRITE.

    ``pdata`` is a project dict as returned by :func:`resolve_project` (or
    ``None``); the key is read from its ``policy`` block, alongside the other
    egress/write knobs it belongs with. The result is the INTERSECTION of what
    the config asks for and :data:`KNOWN_EXTERNAL_WRITE_LANES` -- an
    intersection, not a passthrough, so an unrecognized name grants nothing
    instead of being handed to a router that might match it later. Comparison
    is case-insensitive and whitespace-trimmed; ordering is
    :data:`KNOWN_EXTERNAL_WRITE_LANES`' so two processes reading the same file
    produce the same tuple.
    """
    if not isinstance(pdata, dict):
        return DEFAULT_EXTERNAL_WRITE_LANES
    policy = pdata.get("policy")
    if not isinstance(policy, dict):
        return DEFAULT_EXTERNAL_WRITE_LANES
    raw = policy.get("external_write_lanes")
    if not isinstance(raw, (list, tuple)):
        return DEFAULT_EXTERNAL_WRITE_LANES
    asked = {x.strip().lower() for x in raw if isinstance(x, str)}
    return tuple(name for name in KNOWN_EXTERNAL_WRITE_LANES if name in asked)


def external_write_lanes_for_repo(repo_root: str | None) -> tuple[str, ...]:
    """:func:`resolve_external_write_lanes` for the repo that will be WRITTEN.

    Reads the repository's own ``.agentenv/agentenv.json``. Every failure mode
    -- no ``repo_root``, no config file, unreadable, malformed JSON, no policy
    block -- resolves to :data:`DEFAULT_EXTERNAL_WRITE_LANES`, so a router that
    cannot read the config routes exactly as it did before this key existed.

    Deliberately repo-local and NOT registry-aware: this grants an untrusted
    external lane write rights over a specific checkout, so the permission has
    to live in the checkout it applies to, reviewable in that repo's version
    control -- not in a registry entry written for some other repository, which
    is the exact shape of the bug ``_apply_repo_confinement`` exists to undo.
    """
    return resolve_external_write_lanes({"policy": _repo_local_policy(repo_root)})


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
        "deny_content": [],
        "_comment_external_write_lanes": "Which UNTRUSTED external provider "
            "lanes may APPLY a change instead of only advising. Empty -- the "
            "default, and the behaviour every version before this key had -- "
            "means every external lane is advisory-only. Add \"deepseek\" to "
            "let the DeepSeek lane land its own full-file rewrite, and only on "
            "LOW change-risk, non-review tasks. Enabling it widens NOTHING "
            "else: that lane still only receives bytes the egress keys "
            "('allow'/'default_deny') permit, still only writes paths "
            "'write_allow' permits, still faces the verify gate, and keeps a "
            "byte-exact rollback of every file it touched. Unknown lane names "
            "here are discarded, not honoured. DeepSeek writes are PAID -- "
            "this is an occasional opt-in, not a default lane.",
        "external_write_lanes": []
    },
    "test_command": None,   # opt-in: a fresh repo has no suite -- don't gate writes on a nonexistent one
    "test_cwd": ".",
    # Runaway budget for test_command, in seconds. Stated explicitly (rather
    # than left absent) so the knob is discoverable in every scaffolded repo,
    # and set to the SAME value as verifier.DEFAULT_TEST_TIMEOUT_S so writing
    # the starter file changes no behaviour. Raise it if your suite is slower
    # than this; a suite that overruns is killed and blocks the write.
    "test_timeout_s": 120,
    # Curated autonomy is opt-in. The picker reports this source as "disabled"
    # until a repository deliberately enables it; a missing enabled file is a
    # distinct "absent" source failure, never an empty healthy queue.
    "work_queue": {
        "enabled": False,
        "path": ".agentenv/work-queue.json",
    },
    # Enabled sources are required: a missing configured source is reported as
    # absent, not as a healthy empty result. Repositories that intentionally do
    # not maintain a legacy source must say "disabled" explicitly.
    "picker_sources": {
        "map": "enabled",
        "inventory": "enabled",
        "eval_baseline": "enabled",
    },
    # Repo-bound by default so an external ``daedalus improve`` run reads and
    # writes the same attempt memory. Absolute and ``..``-escaping configured
    # paths are rejected by the picker.
    "spine": {
        "ledger_path": "runs/spine/spine.sqlite3",
    },
    "_comment_write_wave_policy": "Candidate nomination and promotion are "
        "separate. The safe scaffold default is 'never': clean gated "
        "candidates remain held for an explicit human promotion decision. "
        "The legacy 'low_risk' and 'always' spellings are accepted as input "
        "only so old configuration can fail closed: both resolve to 'never' "
        "and cannot authorize integration-worktree promotion.",
    "write_wave_policy": "never",
}


def _repo_local_policy(repo_root: str | None) -> dict | None:
    """The `policy` block a repository declares ABOUT ITSELF, or None."""
    if not repo_root:
        return None
    f = Path(repo_root) / REPO_CONFIG
    if not f.exists():
        return None
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        policy = data.get("policy")
        return policy if isinstance(policy, dict) else None
    except (OSError, UnicodeError, json.JSONDecodeError):
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
    registered_root = data.get("repo_root")
    # A committed registry entry can outlive the workstation path that created
    # it. When that path is gone and the caller supplied an existing checkout,
    # judge the checkout that can actually be written. This never widens a
    # live registered target: an existing registry root still wins, and the
    # selected repo-local policy is intersected below rather than replaced.
    policy_root = registered_root or repo_root
    if registered_root and not Path(str(registered_root)).is_dir():
        policy_root = repo_root
    local = _repo_local_policy(str(policy_root))
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
    dst = agentenv_dir / "agents"
    dst.mkdir(exist_ok=True)
    for path in iter_builtin_files(
        "templates/agents", legacy=TEMPLATE_DIR / "agents", suffix=".json"
    ):
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
        try:
            content = read_builtin_text(
                f"templates/{name}", legacy=TEMPLATE_DIR / name
            )
        except FileNotFoundError:
            continue
        target = repo_root / name
        if not target.exists():
            target.write_text(content, encoding="utf-8")


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
