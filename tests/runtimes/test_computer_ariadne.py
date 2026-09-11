"""G1-IKARUS-47: ``daedalus.ariadne_campaign`` -- the computer loop's door to
one Ariadne controlled-repair campaign on the registered project.

What is pinned here:

* the policy family and the tool spec (A1, A2);
* capability unavailable without project / runner (A3);
* every pre-run refusal happens BEFORE the runner is called (A4);
* the projection carries no locator, no host path, no ``after`` text (A5);
* the campaign id default is deterministic (A6);
* ``effect_state`` none/uncertain and the service's reconciliation (A7);
* the REAL ``run_campaign`` through the REAL lease on a plain scratch subject:
  nominated, subject untouched, evidence under the control root (A8);
* a linked-worktree subject is refused by the campaign, surfaced verbatim (A9).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from collections.abc import Mapping
from pathlib import Path

import pytest

from daedalus.kernel.policy.computer import (
    ALL_COMPUTER_TOOLS, ARIADNE_TOOLS, DAEDALUS_TOOLS, ComputerPolicy, ComputerRefused, policy_path,
)
from daedalus.runtimes import computer as service_module
from daedalus.runtimes import computer_ariadne as subject
from daedalus.spine import killswitch

TOOL = "daedalus.ariadne_campaign"


# ----------------------------------------------------------------------------- fixtures
def _policy(tmp_path, **kwargs) -> ComputerPolicy:
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return ComputerPolicy(workspace=workspace, tools=ARIADNE_TOOLS + DAEDALUS_TOOLS, **kwargs)


def _project(monkeypatch, repo_root: str, *, deny=("tct_app/devices/",)):
    from daedalus.foundation import projects
    config = {"name": "fixture", "repo_root": repo_root,
              "policy": {"deny": list(deny), "deny_content": [], "allow": ["pkg/", "docs/", ".md", "sample.txt"]}}
    monkeypatch.setattr(projects, "load_project", lambda name: config)
    monkeypatch.setattr(projects, "resolve_repo_root", lambda repo_root, project: repo_root)


class _Recorder:
    """A runner that records the call and returns a real-shaped receipt."""

    def __init__(self, receipt=None, *, raise_with=None, echo_request=True):
        self.calls = []
        self.receipt = receipt if receipt is not None else _receipt()
        self.raise_with = raise_with
        self.echo_request = echo_request

    def run_campaign(self, **kwargs):
        self.calls.append(kwargs)
        if self.raise_with is not None:
            raise self.raise_with
        if self.echo_request:
            # The real campaign's receipt is about the campaign it was asked to
            # run; a fixture that did not echo hid the round-3 D19 check.
            return {**self.receipt, "campaign_id": kwargs.get("campaign_id", self.receipt.get("campaign_id")),
                    "source_revision": kwargs.get("source_revision", self.receipt.get("source_revision"))}
        return self.receipt


def _runner(recorder=None, *, head="a" * 40, protected=None):
    from daedalus.ariadne.campaign import protected_prefix_for
    recorder = recorder or _Recorder()
    return subject.CampaignRunner(
        run_campaign=recorder.run_campaign,
        head_revision=lambda root: head,
        protected_prefix_for=protected or protected_prefix_for), recorder


def _never_runner():
    def explode(**kwargs):
        raise AssertionError("the runner must not be called before admission")
    from daedalus.ariadne.campaign import protected_prefix_for
    return subject.CampaignRunner(run_campaign=explode,
                                  head_revision=lambda root: (_ for _ in ()).throw(AssertionError("HEAD read too early")),
                                  protected_prefix_for=protected_prefix_for)


def _receipt(outcome="nominated"):
    home = str(Path.home())
    return {
        "campaign_id": "ikarus-x", "source_revision": "a" * 40, "outcome": outcome,
        "selected_seed": 2, "selected_variant_id": "repair", "selection_mode": "best-passed-trial",
        "candidate_tree_sha256": "c" * 64, "candidate_tree_locator": f"{home}\\.daedalus\\control\\x\\cas\\c",
        "nomination_receipt_sha256": "d" * 64, "nomination_receipt_locator": f"{home}/control/x/nom.json",
        "campaign_contract_locator": f"{home}/control/x/contract.json",
        "trials": [
            {"variant_id": "baseline", "status": "failed", "usage": {"wall_time_ms": 300},
             "negative_outcomes": ["frozen-evaluator-rejected"], "blockers": ["exact-match-failed"],
             "evidence_packet_locator": f"{home}/control/x/ev1.json"},
            {"variant_id": "negative-control", "status": "failed", "usage": {"wall_time_ms": 310},
             "negative_outcomes": ["frozen-evaluator-rejected"], "blockers": ["exact-match-failed"]},
            {"variant_id": "repair", "status": "passed", "usage": {"wall_time_ms": 320},
             "negative_outcomes": [], "blockers": []},
        ],
        "budget_equality": {"configured_equal": True, "realized_usage_recorded": True, "within_budget": True,
                            "trial_budget_sha256s": ["b" * 64] * 3},
        "negative_outcomes": ["baseline:frozen-evaluator-rejected", "negative-control:frozen-evaluator-rejected"],
        "reproducibility_note": "…",
    }


def _tool(tmp_path, monkeypatch, runner, *, provider="claude_code_cli", repo_root=None):
    if repo_root is None:
        root = tmp_path / "subject"
        for rel in ("pkg/mod.py", "internal/roadmap.py"):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text("return 1\n", encoding="utf-8")
        repo_root = str(root)
    _project(monkeypatch, repo_root)
    policy = _policy(tmp_path, planner_provider=provider, allow_remote_context=True)
    return subject.AriadneCampaignTool(policy, "fixture", lambda: None, tmp_path, runner)


ARGS = {"target_path": "pkg/mod.py", "before": "return 1", "after": "return 2"}


# ----------------------------------------------------------------------------- A1/A2
def test_the_family_is_known_and_a_fresh_policy_grants_nothing(tmp_path):
    assert TOOL in ALL_COMPUTER_TOOLS and ARIADNE_TOOLS == (TOOL,)
    assert TOOL in service_module.TOOL_SPECS and TOOL in service_module._HOST_MUTATION_TOOLS
    fresh = ComputerPolicy(workspace=tmp_path)
    assert fresh.tools == ()
    for bad in ({"target_path": "x"}, {"target_path": "x", "before": "a", "after": "b", "extra": 1},
                {"target_path": 1, "before": "a", "after": "b"}):
        with pytest.raises(ComputerRefused):
            service_module._validate_arguments(TOOL, bad)
    service_module._validate_arguments(TOOL, {**ARGS, "campaign_id": "c1", "timeout_s": 30})


def test_the_policy_path_rule_holds_the_target_path_and_leaves_the_text_fragments_alone(tmp_path):
    """MEASURED 2026-09-10 (live run 1): the kernel's by-name path rule refused
    the campaign's ``before``/``after`` TEXT (a docstring sentence with a
    colon) as "not relative to the workspace". The rule now names the tool's
    path argument -- and still holds it to the lexical rule."""
    policy = ComputerPolicy(workspace=tmp_path / "ws", tools=(TOOL, "vision.changes"))
    policy.admit(TOOL, {"target_path": "daedalus/build.py",
                        "before": "objective: one feature\n", "after": "objective: exactly one feature\n"})
    for bad in ("../x.py", "/etc/x", "C:/Users/x.py", "x\x00", "a<b.py"):
        with pytest.raises(ComputerRefused):
            policy.admit(TOOL, {"target_path": bad, "before": "a", "after": "b"})
    # vision.changes keeps its path semantics for the same key names.
    with pytest.raises(ComputerRefused, match="relative"):
        policy.admit("vision.changes", {"before": "C:/x.png", "after": "y.png"})


# ----------------------------------------------------------------------------- A3
def test_capability_is_unavailable_without_a_project_or_a_runner(tmp_path, monkeypatch):
    monkeypatch.setattr(service_module, "load_policy",
                        lambda root: _policy(tmp_path, planner_provider="claude_code_cli", allow_remote_context=True))
    monkeypatch.setattr(service_module, "control_root", lambda root: tmp_path / "control")
    monkeypatch.setattr(service_module.KillSwitch, "__init__", lambda self, **kw: None)
    without_project = service_module.ComputerService(tmp_path)
    assert without_project.capabilities()["unavailable"][TOOL] == service_module._NO_PROJECT_REFUSAL
    without_runner = service_module.ComputerService(tmp_path, project="fixture", project_readers=object())
    assert without_runner.capabilities()["unavailable"][TOOL] == service_module._NO_RUNNER_REFUSAL
    runner, _ = _runner()
    with_runner = service_module.ComputerService(tmp_path, project="fixture", project_readers=object(),
                                                 campaign_runner=runner)
    names = {tool["name"]: tool for tool in with_runner.capabilities()["tools"]}
    assert TOOL in names and "Project: fixture." in names[TOOL]["description"]
    assert "nomination" in names[TOOL]["description"].lower() and "not improvement" in names[TOOL]["description"]


# ----------------------------------------------------------------------------- A4
@pytest.mark.parametrize("target", [
    "daedalus/spine/killswitch.py", "DAEDALUS/SPINE/x.py", "daedalus/kernel/policy/computer.py",
    "daedalus/kernel/promotion.py", "daedalus/kernel/approvals.py", "daedalus/kernel/contracts/x.py",
    "daedalus/ariadne/campaign.py", "docs/IKARUS_ARIADNE_MASTER_PLAN.md",
    "docs/IKARUS_ARIADNE_MASTER_PLAN.amendments.jsonl", "AGENTS.md", "CLAUDE.md", ".agentenv/x.json",
    "tests/test_ariadne_leakage_boundary.py",
])
def test_the_leakage_boundary_is_refused_before_the_runner_is_called(tmp_path, monkeypatch, target):
    tool = _tool(tmp_path, monkeypatch, _never_runner())
    with pytest.raises(ComputerRefused, match="leakage boundary") as refused:
        tool.execute({**ARGS, "target_path": target})
    assert refused.value.effect_state == "none"


@pytest.mark.parametrize("arguments, reason", [
    ({**ARGS, "target_path": ".git/config"}, "mandatory ignored root"),
    ({**ARGS, "target_path": ".daedalus/x"}, "mandatory ignored root"),
    ({**ARGS, "target_path": "../x.py"}, "repository-relative"),
    ({**ARGS, "target_path": "/etc/passwd"}, "repository-relative"),
    ({**ARGS, "target_path": "C:/Users/x/y.py"}, "repository-relative"),
    ({**ARGS, "target_path": "pkg/mod.py\x00"}, "bounded"),
    ({**ARGS, "target_path": "x" * 1001}, "bounded"),
    # Odysseus round 1 (D2/D3): spellings the subject filesystem rewrites or the
    # campaign refuses after the runner was entered are refused HERE, lexically.
    ({**ARGS, "target_path": "daedalus/spine./killswitch.py"}, "spelling the subject filesystem would rewrite"),
    ({**ARGS, "target_path": "daedalus/spine /x.py"}, "spelling"),
    ({**ARGS, "target_path": "./daedalus/spine/x.py"}, "repository-relative"),
    ({**ARGS, "target_path": "daedalus/./spine/x.py"}, "repository-relative"),
    ({**ARGS, "target_path": "daedalus//spine/x.py"}, "repository-relative"),
    ({**ARGS, "target_path": "pkg/con.py"}, "Windows device"),
    ({**ARGS, "target_path": "pkg/a<b.py"}, "spelling"),
    ({**ARGS, "campaign_id": ".hidden"}, "campaign_id"),
    ({**ARGS, "campaign_id": "-x"}, "campaign_id"),
    ({**ARGS, "before": ""}, "before must be non-empty"),
    ({**ARGS, "after": "return 1"}, "different value"),
    ({**ARGS, "timeout_s": 0}, "timeout_s"),
    ({**ARGS, "timeout_s": 121}, "timeout_s"),
    ({**ARGS, "timeout_s": True}, "timeout_s"),
    ({**ARGS, "campaign_id": "a/b"}, "campaign_id"),
    ({**ARGS, "campaign_id": ""}, "campaign_id"),
])
def test_every_pre_run_refusal_precedes_the_runner(tmp_path, monkeypatch, arguments, reason):
    tool = _tool(tmp_path, monkeypatch, _never_runner())
    with pytest.raises(ComputerRefused, match=reason) as refused:
        tool.execute(arguments)
    assert refused.value.effect_state == "none"


@pytest.mark.skipif(os.name != "nt", reason="directory junctions are a Windows construct")
def test_a_junction_inside_the_subject_cannot_reach_the_leakage_boundary(tmp_path, monkeypatch):
    """Odysseus round 1 (D1, high): ``shortcut`` -> ``daedalus/spine`` is a
    junction, not a symlink, so ``shortcut/killswitch.py`` passed every string
    check and the campaign nominated a change to a protected file. The
    resolved path must spell the requested one and pass the boundary again."""
    root = tmp_path / "subject"
    (root / "daedalus" / "spine").mkdir(parents=True)
    (root / "daedalus" / "spine" / "killswitch.py").write_text("SENTINEL = 1\n", encoding="utf-8")
    (root / "pkg").mkdir()
    (root / "pkg" / "mod.py").write_text("return 1\n", encoding="utf-8")
    link = root / "shortcut"
    proc = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(root / "daedalus" / "spine")],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    tool = _tool(tmp_path, monkeypatch, _never_runner(), repo_root=str(root))
    with pytest.raises(ComputerRefused, match="link, junction or a rewritten spelling") as refused:
        tool.execute({**ARGS, "target_path": "shortcut/killswitch.py"})
    assert refused.value.effect_state == "none"
    # A junction to an ADMITTED directory is refused the same way: the spelling
    # must be the file's own.
    other = root / "alias"
    subprocess.run(["cmd", "/c", "mklink", "/J", str(other), str(root / "pkg")], capture_output=True, check=True)
    with pytest.raises(ComputerRefused, match="link, junction"):
        tool.execute({**ARGS, "target_path": "alias/mod.py"})
    # The plain path passes file admission: the next step, the HEAD read, is
    # the never-runner's trap (surfaced as a pre-run refusal naming its class).
    with pytest.raises(ComputerRefused, match="subject HEAD is unavailable: AssertionError"):
        tool.execute({**ARGS, "target_path": "pkg/mod.py"})


def test_a_missing_or_non_regular_target_is_refused_before_the_runner(tmp_path, monkeypatch):
    """D3: a target the campaign would refuse after entering is refused here,
    provably before any campaign effect."""
    root = tmp_path / "subject"
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "mod.py").write_text("return 1\n", encoding="utf-8")
    tool = _tool(tmp_path, monkeypatch, _never_runner(), repo_root=str(root))
    with pytest.raises(ComputerRefused, match="not a regular file") as refused:
        tool.execute({**ARGS, "target_path": "pkg/absent.py"})
    assert refused.value.effect_state == "none"
    with pytest.raises(ComputerRefused, match="not a regular file"):
        tool.execute({**ARGS, "target_path": "pkg"})
    with pytest.raises(ComputerRefused, match="does not resolve inside the subject|not a regular file"):
        tool.execute({**ARGS, "target_path": "pkg/mod.py/x"})


def test_the_postcondition_is_backed_by_the_evidence_directory(tmp_path, monkeypatch):
    """D4: ``postcondition_verified`` was true for any receipt saying "nominated".
    It now requires two well-formed digests AND the campaign's evidence
    directory under the subject's control root."""
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setattr(killswitch, "OS_PROFILE_DIR", profile)
    runner, _ = _runner()
    tool = _tool(tmp_path, monkeypatch, runner)
    result = tool.execute(dict(ARGS))
    assert result["postcondition_verified"] is False and result["evidence_present"] is False
    evidence = killswitch.control_root(Path(tool._repo_root())) / "ariadne" / "effect-evidence" / result["campaign_id"]
    evidence.mkdir(parents=True)
    (evidence / "lease-subject.json").write_text("{}", encoding="utf-8")
    result = tool.execute(dict(ARGS))
    assert result["postcondition_verified"] is True and result["evidence_present"] is True
    fake = _receipt()
    fake["nomination_receipt_sha256"] = "not-a-hash"
    runner, _ = _runner(_Recorder(receipt=fake))
    tool = _tool(tmp_path, monkeypatch, runner)
    result = tool.execute(dict(ARGS))
    assert result["postcondition_verified"] is False and result["nomination_receipt_sha256"] is None


def test_the_projection_is_rendered_once_and_bounded(tmp_path, monkeypatch):
    """D6/D9: a stateful ``__str__`` in the receipt was gated on one rendering and
    emitted on another; unbounded lists could make the projection megabytes."""
    class Shifty:
        def __init__(self):
            self.calls = 0

        def __str__(self):
            self.calls += 1
            return "benign-value" if self.calls == 1 else "C:\\Users\\victim\\leaked\\secret.txt"

    receipt = _receipt()
    receipt["selection_mode"] = Shifty()
    receipt["negative_outcomes"] = [f"arm{i}:frozen-evaluator-rejected" for i in range(25)]
    receipt["trials"] = receipt["trials"] * 5
    runner, _ = _runner(_Recorder(receipt=receipt))
    tool = _tool(tmp_path, monkeypatch, runner)
    result = tool.execute(dict(ARGS))
    assert result["selection_mode"] == "benign-value" and "victim" not in json.dumps(result)
    assert len(result["negative_outcomes"]) == subject.LIST_SHOWN and result["negative_outcomes_elided"] == 15
    assert len(result["trials"]) == subject.TRIALS_SHOWN and result["trials_elided"] == 7
    receipt = _receipt()
    receipt["selected_seed"] = float("nan")
    runner, _ = _runner(_Recorder(receipt=receipt))
    tool = _tool(tmp_path, monkeypatch, runner)
    with pytest.raises(ComputerRefused, match="not renderable") as refused:
        tool.execute(dict(ARGS))
    assert refused.value.effect_state == "uncertain"


def test_nothing_after_the_runner_can_raise_a_pre_run_refusal(tmp_path, monkeypatch):
    """Cerberus round 2 (NEW-1, critical): the postcondition check re-read the
    registry AFTER the campaign had run; when that read failed the adapter
    raised ``_PreRunRefusal`` and the service settled the lease as "no effect"
    while the campaign had written its evidence. The projection now takes the
    repository root as an argument and a failing check reads as not verified."""
    from daedalus.foundation import projects
    calls = {"n": 0}
    subject_root = tmp_path / "subject"
    (subject_root / "pkg").mkdir(parents=True)
    (subject_root / "pkg" / "mod.py").write_text("return 1\n", encoding="utf-8")
    config = {"name": "fixture", "repo_root": str(subject_root),
              "policy": {"deny": [], "deny_content": [], "allow": ["pkg/"]}}

    def load(name):
        calls["n"] += 1
        if calls["n"] > 1:
            raise PermissionError(13, "denied", "C:\\Users\\victim\\projects\\fixture.json")
        return config
    monkeypatch.setattr(projects, "load_project", load)
    monkeypatch.setattr(projects, "resolve_repo_root", lambda repo_root, project: repo_root)
    runner, recorder = _runner()
    policy = _policy(tmp_path, planner_provider="claude_code_cli", allow_remote_context=True)
    tool = subject.AriadneCampaignTool(policy, "fixture", lambda: None, tmp_path, runner)
    result = tool.execute(dict(ARGS))
    assert len(recorder.calls) == 1
    assert result["outcome"] == "nominated" and result["evidence_present"] is False
    assert result["postcondition_verified"] is False
    assert result["target_path"] == "<withheld>"  # the gate could not be consulted; withheld, not refused
    assert "victim" not in json.dumps(result)


def test_a_hard_link_to_a_protected_file_is_refused_before_the_runner(tmp_path, monkeypatch):
    """Odysseus round 2: a hard link is a second NAME for one inode. The
    resolver returns the requested spelling, so every lexical and realpath
    check passed and the campaign was admitted for a file that also lives at
    ``daedalus/spine/killswitch.py``. The kernel has an ``st_nlink`` check but
    resolves against the computer workspace, so it never sees the subject."""
    root = tmp_path / "subject"
    (root / "pkg").mkdir(parents=True)
    (root / "daedalus" / "spine").mkdir(parents=True)
    protected = root / "daedalus" / "spine" / "killswitch.py"
    protected.write_text("return 1\n", encoding="utf-8")
    linked = root / "pkg" / "hard.py"
    try:
        os.link(protected, linked)
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - filesystem without hard links
        pytest.skip(f"hard links unavailable: {type(exc).__name__}")
    assert linked.stat().st_nlink > 1
    tool = _tool(tmp_path, monkeypatch, _never_runner(), repo_root=str(root))
    with pytest.raises(ComputerRefused, match="more than one name"):
        tool.execute({**ARGS, "target_path": "pkg/hard.py"})
    # A single-named regular file in the same directory still passes.
    (root / "pkg" / "mod.py").write_text("return 1\n", encoding="utf-8")
    runner, recorder = _runner()
    tool = _tool(tmp_path, monkeypatch, runner, repo_root=str(root))
    tool.execute(dict(ARGS))
    assert len(recorder.calls) == 1


def test_a_campaign_id_is_held_to_the_filesystem_spelling_of_its_directory(tmp_path, monkeypatch):
    """Odysseus round 2 (D11): the ID names the evidence directory, and Windows
    folds ``camp1``, ``CAMP1`` and ``camp1.`` into ONE directory, so two IDs
    this adapter treats as distinct shared one postcondition. Reserved device
    names never become a directory at all."""
    tool = _tool(tmp_path, monkeypatch, _never_runner())
    for bad in ("CAMP1", "Camp1", "camp1.", "camp1 ", "con", "NUL", "com1", "lpt9.txt", "aux.log"):
        with pytest.raises(ComputerRefused, match="lower case|path-free"):
            tool.execute({**ARGS, "campaign_id": bad})
    runner, recorder = _runner()
    tool = _tool(tmp_path, monkeypatch, runner)
    result = tool.execute({**ARGS, "campaign_id": "camp1.a-b_2"})
    # The id keeps the planner's label AND carries the operation it belongs to
    # (Odysseus round 3, D14: a bare label let one campaign borrow another's
    # fresh evidence directory and report a verified postcondition).
    assert result["campaign_id"].startswith("camp1.a-b_2-") and len(recorder.calls) == 1
    assert len(result["campaign_id"]) <= 64 and recorder.calls[0]["campaign_id"] == result["campaign_id"]
    other = tool.execute({**ARGS, "after": "return 3", "campaign_id": "camp1.a-b_2"})
    assert other["campaign_id"] != result["campaign_id"]  # a different operation, a different directory


def test_the_evidence_must_have_been_written_during_this_run(tmp_path, monkeypatch):
    """Odysseus round 2 (D4 residue): the default campaign ID is a digest of
    the OPERATION, so a second call with the same arguments found the first
    run's evidence directory. A forged receipt -- a runner that writes nothing
    and returns digests -- then reported a verified postcondition. Evidence
    must carry a timestamp from this run."""
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setattr(killswitch, "OS_PROFILE_DIR", profile)
    runner, _ = _runner()
    tool = _tool(tmp_path, monkeypatch, runner)
    first = tool.execute(dict(ARGS))
    evidence = killswitch.control_root(Path(tool._repo_root())) / "ariadne" / "effect-evidence" / first["campaign_id"]
    evidence.mkdir(parents=True)
    written = evidence / "lease-subject.json"
    written.write_text("{}", encoding="utf-8")
    assert tool.execute(dict(ARGS))["postcondition_verified"] is True
    # The same operation again, but the evidence is older than this run: the
    # directory is inherited, so the postcondition is NOT verified.
    old = time.time() - 3600
    os.utime(written, (old, old))
    forged = tool.execute(dict(ARGS))
    assert forged["campaign_id"] == first["campaign_id"]
    assert forged["evidence_present"] is False and forged["postcondition_verified"] is False
    assert forged["outcome"] == "nominated"  # the receipt still says so; the postcondition does not


def test_every_projected_value_is_bounded_not_only_every_list(tmp_path, monkeypatch):
    """Odysseus round 2 (D9): the counts were bounded but the VALUES were not,
    so a receipt field of two megabytes produced a projection of two and a half
    megabytes for the planner and the retained mission report."""
    huge = _receipt()
    huge["selection_mode"] = "m" * 300000
    huge["negative_outcomes"] = ["n" * 300000]
    huge["selected_variant_id"] = "v" * 300000
    huge["trials"][0]["blockers"] = ["b" * 300000]
    huge["trials"][0]["status"] = "s" * 300000
    runner, _ = _runner(_Recorder(receipt=huge))
    tool = _tool(tmp_path, monkeypatch, runner)
    result = tool.execute(dict(ARGS))
    rendered = json.dumps(result)
    assert len(rendered) < 20000, len(rendered)
    assert result["selection_mode"].endswith("chars)") and len(result["selection_mode"]) < 300
    assert result["negative_outcomes"][0].endswith("chars)")
    assert result["trials"][0]["blockers"][0].endswith("chars)")


def test_a_receipt_about_another_campaign_does_not_verify_the_postcondition(tmp_path, monkeypatch):
    """Odysseus round 3 (D19): the projection echoes the REQUEST, so a receipt
    about a different campaign or revision was reported under this campaign's
    id and target with `outcome` taken from that foreign receipt."""
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setattr(killswitch, "OS_PROFILE_DIR", profile)
    foreign = _receipt()
    foreign["campaign_id"] = "somebody-elses-campaign"
    foreign["source_revision"] = "b" * 40
    runner, _ = _runner(_Recorder(receipt=foreign, echo_request=False))
    tool = _tool(tmp_path, monkeypatch, runner)
    first = tool.execute(dict(ARGS))
    evidence = killswitch.control_root(Path(tool._repo_root())) / "ariadne" / "effect-evidence" / first["campaign_id"]
    evidence.mkdir(parents=True)
    (evidence / "lease-subject.json").write_text("{}", encoding="utf-8")
    result = tool.execute(dict(ARGS))
    assert result["evidence_present"] is True and result["receipt_contradicts_request"] is True
    assert result["postcondition_verified"] is False
    assert "somebody-elses-campaign" not in json.dumps(result)
    # A receipt that asserts NOTHING does not contradict the request: absent is
    # not matching, and the field name says which of the two it measures
    # (Cerberus round 3).
    silent = _receipt()
    silent.pop("campaign_id"), silent.pop("source_revision")
    runner, _ = _runner(_Recorder(receipt=silent, echo_request=False))
    quiet = _tool(tmp_path, monkeypatch, runner).execute(dict(ARGS))
    assert quiet["receipt_contradicts_request"] is False


def test_evidence_with_a_future_timestamp_does_not_verify_forever(tmp_path, monkeypatch):
    """Odysseus round 3 (D15): the freshness floor had no ceiling, so a single
    file dated in the future verified every later forgery."""
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setattr(killswitch, "OS_PROFILE_DIR", profile)
    runner, _ = _runner()
    tool = _tool(tmp_path, monkeypatch, runner)
    first = tool.execute(dict(ARGS))
    evidence = killswitch.control_root(Path(tool._repo_root())) / "ariadne" / "effect-evidence" / first["campaign_id"]
    evidence.mkdir(parents=True)
    planted = evidence / "lease-subject.json"
    planted.write_text("{}", encoding="utf-8")
    ahead = time.time() + 365 * 24 * 3600
    os.utime(planted, (ahead, ahead))
    result = tool.execute(dict(ARGS))
    assert result["evidence_present"] is False and result["postcondition_verified"] is False


def test_a_large_integer_in_the_receipt_is_described_not_rendered(tmp_path, monkeypatch):
    """Odysseus round 3 (D16): `_short` passed every int through, so only
    CPython's 4300-digit conversion limit bounded the projection -- 62 KB out
    of rules that promise 200 characters."""
    huge = _receipt()
    huge["selected_seed"] = 10 ** 4000
    huge["trials"][0]["usage"] = {"wall_time_ms": 10 ** 4000}
    runner, _ = _runner(_Recorder(receipt=huge))
    tool = _tool(tmp_path, monkeypatch, runner)
    result = tool.execute(dict(ARGS))
    rendered = json.dumps(result)
    assert len(rendered) < 20000, len(rendered)
    assert str(result["selected_seed"]).startswith("<integer of ")
    assert str(result["trials"][0]["wall_time_ms"]).startswith("<integer of ")


def test_an_unreadable_receipt_shape_is_classified_not_crashed(tmp_path, monkeypatch):
    """Odysseus round 3 (D18/D20/D21): a Mapping that is not a dict renders to
    a STRING through `default=str`, and every read then raised an unclassified
    AttributeError; an unreadable list shape read as "empty, nothing elided";
    a string in a budget-equality field read as a true flag."""
    class NotADict(Mapping):
        def __init__(self, data): self._data = data
        def __getitem__(self, key): return self._data[key]
        def __iter__(self): return iter(self._data)
        def __len__(self): return len(self._data)

    runner, _ = _runner(_Recorder(receipt=NotADict(_receipt()), echo_request=False))
    tool = _tool(tmp_path, monkeypatch, runner)
    with pytest.raises(ComputerRefused, match="not an object"):
        tool.execute(dict(ARGS))

    shaped = _receipt()
    shaped["trials"] = {"a": 1}
    shaped["negative_outcomes"] = {"b": 2}
    shaped["budget_equality"] = {"configured_equal": "false", "realized_usage_recorded": "no", "within_budget": 0}
    runner, _ = _runner(_Recorder(receipt=shaped))
    result = _tool(tmp_path, monkeypatch, runner).execute(dict(ARGS))
    assert result["trials"] == [] and result["trials_readable"] is False
    assert result["negative_outcomes_readable"] is False
    assert list(result["budget_equality"].values()) == [None, None, None]


def test_a_failing_evidence_check_reads_as_unverified_never_as_a_refusal(tmp_path, monkeypatch):
    """Odysseus round 3 (D17): removing the guard around the evidence check made
    no test fail, because no test made that check raise. A campaign HAS run at
    that point, so a control root that cannot be read is "not verified" -- it
    is never a pre-run refusal, which would settle the lease as effect-free."""
    from daedalus.spine import killswitch as ks
    runner, recorder = _runner()
    tool = _tool(tmp_path, monkeypatch, runner)

    def explode(root):
        raise PermissionError(13, "denied", "C:\\Users\\victim\\control")
    monkeypatch.setattr(ks, "control_root", explode)
    result = tool.execute(dict(ARGS))
    assert len(recorder.calls) == 1  # the campaign ran
    assert result["outcome"] == "nominated" and result["evidence_present"] is False
    assert result["postcondition_verified"] is False and "victim" not in json.dumps(result)


def test_a_failing_gate_call_in_the_projection_withholds_the_target(tmp_path, monkeypatch):
    """Odysseus round 3 (D17): the projection's own guard around the target-path
    gate was never exercised, because the gate's inner guard swallowed the only
    failure a test produced. A failure there withholds the path; it never
    refuses after the runner."""
    runner, recorder = _runner()
    tool = _tool(tmp_path, monkeypatch, runner)

    def explode(relative):
        raise RuntimeError("gate is unavailable: C:\\Users\\victim\\projects")
    monkeypatch.setattr(tool, "_admit_path", explode)
    result = tool.execute(dict(ARGS))
    assert len(recorder.calls) == 1
    assert result["target_path"] == "<withheld>" and result["outcome"] == "nominated"
    assert "victim" not in json.dumps(result)


def test_a_runner_of_the_wrong_type_is_refused(tmp_path, monkeypatch):
    _project(monkeypatch, str(tmp_path / "subject"))
    with pytest.raises(ComputerRefused, match="wrong type"):
        subject.AriadneCampaignTool(_policy(tmp_path), "fixture", lambda: None, tmp_path, 42)  # type: ignore[arg-type]
    service, _ = _service(tmp_path, monkeypatch, lambda **kw: None)  # a bare callable is not a CampaignRunner
    outcome = service.execute(TOOL, dict(ARGS), mission_id="m", attempt_id="a1")
    assert outcome["ok"] is False and "wrong type" in outcome["error"]


def test_the_lexical_boundary_check_precedes_the_registry_read(tmp_path, monkeypatch):
    """Mutation M1: the string-level boundary refusal is not redundant with the
    resolved-file check -- it fires BEFORE the registry is consulted, so a
    protected spelling is refused even for a project that cannot be resolved,
    and no registry or filesystem read happens for it."""
    from daedalus.foundation import projects
    calls = []

    def load(name):
        calls.append(name)
        raise KeyError("must not be consulted for a protected spelling")
    monkeypatch.setattr(projects, "load_project", load)
    policy = _policy(tmp_path, planner_provider="claude_code_cli", allow_remote_context=True)
    tool = subject.AriadneCampaignTool(policy, "fixture", lambda: None, tmp_path, _never_runner())
    with pytest.raises(ComputerRefused, match="leakage boundary"):
        tool.execute({**ARGS, "target_path": "daedalus/spine/x.py"})
    assert calls == []


def test_an_unregistered_project_and_an_unreadable_head_refuse_before_the_runner(tmp_path, monkeypatch):
    from daedalus.foundation import projects
    monkeypatch.setattr(projects, "load_project", lambda name: (_ for _ in ()).throw(KeyError("nope")))
    policy = _policy(tmp_path, planner_provider="claude_code_cli", allow_remote_context=True)
    tool = subject.AriadneCampaignTool(policy, "fixture", lambda: None, tmp_path, _never_runner())
    with pytest.raises(ComputerRefused, match="registered project is unavailable") as refused:
        tool.execute(dict(ARGS))
    assert refused.value.effect_state == "none"
    recorder = _Recorder()
    from daedalus.ariadne.campaign import protected_prefix_for
    bad_head = subject.CampaignRunner(run_campaign=recorder.run_campaign,
                                      head_revision=lambda root: "not-a-sha", protected_prefix_for=protected_prefix_for)
    tool = _tool(tmp_path, monkeypatch, bad_head)
    with pytest.raises(ComputerRefused, match="40-hex") as refused:
        tool.execute(dict(ARGS))
    assert refused.value.effect_state == "none" and recorder.calls == []


# ----------------------------------------------------------------------------- A5/A6
def test_the_projection_carries_verdicts_and_hashes_but_no_locator_path_or_after_text(tmp_path, monkeypatch):
    runner, recorder = _runner()
    tool = _tool(tmp_path, monkeypatch, runner)
    result = tool.execute({**ARGS, "after": "return 'ODYSSEUSCHIMERA'"})
    assert recorder.calls == [{"repo_root": str(tmp_path / "subject"), "source_revision": "a" * 40,
                               "campaign_id": result["campaign_id"], "target_path": "pkg/mod.py",
                               "before": "return 1", "after": "return 'ODYSSEUSCHIMERA'", "timeout_s": 30, "caller_checkpoint": tool._checkpoint}]
    assert result["outcome"] == "nominated" and result["applied"] is False
    assert result["postcondition_verified"] is False  # no evidence directory under this control root
    assert result["host_mutation"] is True
    assert result["target_path"] == "pkg/mod.py" and result["selected_variant_id"] == "repair"
    assert [t["status"] for t in result["trials"]] == ["failed", "failed", "passed"]
    assert result["trials"][0]["wall_time_ms"] == 300
    assert result["budget_equality"] == {"configured_equal": True, "realized_usage_recorded": True, "within_budget": True}
    assert result["candidate_tree_sha256"] == "c" * 64 and result["nomination_receipt_sha256"] == "d" * 64
    assert result["evaluator"] == subject.EVALUATOR_LABEL
    dumped = json.dumps(result)
    for forbidden in ("locator", str(Path.home()), "ODYSSEUSCHIMERA", "control\\\\", "evidence_packet"):
        assert forbidden not in dumped, forbidden
    assert result["campaign_id"].startswith("ikarus-") and len(result["campaign_id"]) == 7 + 24


def test_the_default_campaign_id_is_deterministic_per_operation_and_a_given_label_is_bound_to_it(tmp_path, monkeypatch):
    runner, _ = _runner()
    tool = _tool(tmp_path, monkeypatch, runner)
    first = tool.execute(dict(ARGS))["campaign_id"]
    assert tool.execute(dict(ARGS))["campaign_id"] == first
    assert tool.execute({**ARGS, "after": "return 3"})["campaign_id"] != first
    # A supplied label is KEPT and bound to the operation (Odysseus round 3,
    # D14): the label alone named a directory another campaign could fill.
    named = tool.execute({**ARGS, "campaign_id": "owner.named-1"})["campaign_id"]
    assert named.startswith("owner.named-1-") and named.endswith(first[len("ikarus-"):][:12])


def test_the_target_path_is_withheld_on_the_untrusted_lane_when_the_gate_refuses_it(tmp_path, monkeypatch):
    """The planner named it, but a retained mission report is read by more
    than the planner: the echo goes through the lane's gate."""
    runner, _ = _runner()
    tool = _tool(tmp_path, monkeypatch, runner, provider="codex_cli")
    result = tool.execute({**ARGS, "target_path": "internal/roadmap.py"})
    assert result["target_path"] == "<withheld>" and result["lane"] == "untrusted"


# ----------------------------------------------------------------------------- A7
def test_a_runner_failure_is_surfaced_with_its_class_and_marked_uncertain(tmp_path, monkeypatch):
    class AriadneConflictError(Exception):
        pass
    runner, _ = _runner(_Recorder(raise_with=AriadneConflictError("source_revision conflict: HEAD moved")))
    tool = _tool(tmp_path, monkeypatch, runner)
    with pytest.raises(ComputerRefused, match="AriadneConflictError: source_revision conflict") as refused:
        tool.execute(dict(ARGS))
    assert refused.value.effect_state == "uncertain"


def test_failure_texts_keep_the_class_and_drop_a_message_that_names_a_host_path(tmp_path, monkeypatch):
    """Cerberus round 1 (CRITICAL 1): ``git rev-parse``'s stderr and the campaign's
    ``repo_root is unavailable or unsafe: [WinError 2] … 'C:\\…'`` reached the
    planner's history through the refusal text. The class stays; a message
    naming a host path is withheld; a clean message stays useful."""
    class AriadneRequestError(Exception):
        pass
    dirty = AriadneRequestError("repo_root is unavailable or unsafe: [WinError 2] The system cannot find the file: "
                                "'C:\\Users\\victim\\AppData\\Local\\Temp\\no-such-subject'")
    runner, _ = _runner(_Recorder(raise_with=dirty))
    tool = _tool(tmp_path, monkeypatch, runner)
    with pytest.raises(ComputerRefused) as refused:
        tool.execute(dict(ARGS))
    assert str(refused.value) == f"AriadneRequestError: {subject._MESSAGE_WITHHELD}"
    assert refused.value.effect_state == "uncertain"
    from daedalus.ariadne.campaign import protected_prefix_for
    head_dirty = subject.CampaignRunner(
        run_campaign=lambda **kw: None,
        head_revision=lambda root: (_ for _ in ()).throw(
            RuntimeError("git rev-parse failed: fatal: cannot change to '/home/victim/no-such-subject'")),
        protected_prefix_for=protected_prefix_for)
    tool = _tool(tmp_path, monkeypatch, head_dirty)
    with pytest.raises(ComputerRefused) as refused:
        tool.execute(dict(ARGS))
    assert str(refused.value) == f"subject HEAD is unavailable: RuntimeError: {subject._MESSAGE_WITHHELD}"
    assert refused.value.effect_state == "none"
    from daedalus.foundation import projects
    monkeypatch.setattr(projects, "load_project",
                        lambda name: (_ for _ in ()).throw(PermissionError(13, "denied", "C:\\Users\\victim\\p.json")))
    tool = subject.AriadneCampaignTool(_policy(tmp_path, planner_provider="claude_code_cli", allow_remote_context=True),
                                       "fixture", lambda: None, tmp_path, _never_runner())
    with pytest.raises(ComputerRefused) as refused:
        tool.execute(dict(ARGS))
    assert str(refused.value) == "registered project is unavailable: PermissionError"


def _service(tmp_path, monkeypatch, runner):
    profile = tmp_path / "profile"
    profile.mkdir(exist_ok=True)
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setattr(killswitch, "OS_PROFILE_DIR", profile)
    monkeypatch.delenv("DAEDALUS_KILLSWITCH", raising=False)
    authority = tmp_path / "authority"
    authority.mkdir(exist_ok=True)
    policy = _policy(tmp_path, planner_provider="claude_code_cli", allow_remote_context=True)
    path = policy_path(authority)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(policy.to_dict()), encoding="utf-8")
    switch = killswitch.KillSwitch(repo_root=authority, sweep_managed=False)
    assert switch.arm(note="ariadne tool fixture").running
    return service_module.ComputerService(authority, project="fixture", project_readers=object(),
                                          campaign_runner=runner), authority


def test_the_service_keeps_the_lease_started_after_a_runner_failure_and_settles_a_pre_run_refusal(
        tmp_path, monkeypatch):
    class AriadneCampaignError(Exception):
        pass
    (tmp_path / "subject" / "pkg").mkdir(parents=True)
    (tmp_path / "subject" / "pkg" / "mod.py").write_text("return 1\n", encoding="utf-8")
    _project(monkeypatch, str(tmp_path / "subject"))
    runner, _ = _runner(_Recorder(raise_with=AriadneCampaignError("effect lease denied")))
    service, authority = _service(tmp_path, monkeypatch, runner)
    outcome = service.execute(TOOL, dict(ARGS), mission_id="m", attempt_id="a1")
    assert outcome["ok"] is False and outcome["state"] == "reconciliation_required"
    assert "AriadneCampaignError: effect lease denied" in outcome["error"]
    refused = service.execute(TOOL, {**ARGS, "target_path": "daedalus/spine/x.py"}, mission_id="m", attempt_id="a2")
    # A pre-run refusal is provably effect-free: the lease is settled ("blocked"),
    # not left for reconciliation.
    assert refused["ok"] is False and refused["state"] == "blocked", refused
    assert refused["error_type"] == "_PreRunRefusal" and "leakage boundary" in refused["error"]


def test_a_session_without_a_runner_is_refused_before_any_lease(tmp_path, monkeypatch):
    """Mutation M14: admission refuses the tool without a runner BEFORE the
    lease is issued -- the dispatch refusal behind it would come after."""
    _project(monkeypatch, str(tmp_path / "subject"))
    service, authority = _service(tmp_path, monkeypatch, None)
    outcome = service.execute(TOOL, dict(ARGS), mission_id="m", attempt_id="a1")
    assert outcome["ok"] is False and "campaign runner" in outcome["error"]
    evidence = service.control / "computer-effect-evidence"
    assert not evidence.exists() or not any(evidence.rglob("*")), "refused before any lease evidence"


# ----------------------------------------------------------------------------- A8/A9
def _plain_subject(tmp_path, monkeypatch, name="subject"):
    root = tmp_path / name
    root.mkdir()
    (tmp_path / "empty-git-template").mkdir(exist_ok=True)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_TEMPLATE_DIR", str(tmp_path / "empty-git-template"))

    def git(*args):
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-q", "-b", "main")
    git("config", "user.email", "ariadne@example.invalid")
    git("config", "user.name", "Ariadne Test")
    (root / "sample.txt").write_text("broken\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "seed")
    return root, git


def test_the_real_campaign_through_the_real_lease_nominates_and_leaves_the_subject_untouched(tmp_path, monkeypatch):
    """A8: the REAL run_campaign as runner, the REAL computer lease, a plain
    scratch subject registered as the project. Nominated; the subject's
    working tree and HEAD unchanged; evidence under the subject's control
    root; the retained result carries no host path and never applies."""
    from daedalus.ariadne import run_campaign
    from daedalus.ariadne.campaign import protected_prefix_for
    from daedalus.orchestration.ikarus.computer_loop import head_revision
    root, git = _plain_subject(tmp_path, monkeypatch)
    _project(monkeypatch, str(root))
    runner = subject.CampaignRunner(run_campaign=run_campaign, head_revision=head_revision,
                                    protected_prefix_for=protected_prefix_for)
    service, authority = _service(tmp_path, monkeypatch, runner)
    subject_switch = killswitch.KillSwitch(repo_root=root)
    assert subject_switch.arm(note="ariadne tool real subject").running
    head_before = git("rev-parse", "HEAD")
    try:
        outcome = service.execute(TOOL, {"target_path": "sample.txt", "before": "broken", "after": "fixed"},
                                  mission_id="computer-ariadne-real", attempt_id="attempt-1")
    finally:
        subject_switch.stop()
    assert outcome["ok"] is True, outcome
    result = outcome["result"]
    assert result["outcome"] == "nominated" and result["applied"] is False
    assert [t["status"] for t in result["trials"]] == ["failed", "failed", "passed"]
    assert result["source_revision"] == head_before and result["postcondition_verified"] is True
    assert (root / "sample.txt").read_text(encoding="utf-8") == "broken\n"
    # The tracked tree and HEAD are untouched. The one thing the campaign adds
    # inside the subject is its record in the subject's CANONICAL SPINE
    # (``runs/spine/spine.sqlite3``, invariant 1: one event store per
    # repository; ignored by this repository's .gitignore) -- measured here,
    # not claimed away.
    assert git("status", "--porcelain", "--untracked-files=no") == "" and git("rev-parse", "HEAD") == head_before
    untracked = [line for line in git("status", "--porcelain").splitlines() if line.startswith("??")]
    assert untracked == ["?? runs/"], untracked
    assert sorted(p.relative_to(root).as_posix() for p in (root / "runs").rglob("*") if p.is_file()) == [
        "runs/spine/spine.sqlite3"]
    evidence = killswitch.control_root(root) / "ariadne" / "effect-evidence" / result["campaign_id"]
    assert evidence.is_dir() and any(evidence.rglob("*"))
    stored = [json.loads(p.read_text(encoding="utf-8")) for p in (service.control / "computer-artifacts").glob("*.json")]
    results = [b for b in stored if b.get("schema") == "daedalus-computer-result/1"]
    assert len(results) == 1 and results[0]["host_mutation"] is True
    assert results[0]["filesystem_scope_kind"] == "control-root-ariadne-campaign"
    dumped = json.dumps(results[0]["result"])
    assert str(tmp_path) not in dumped and str(Path.home()) not in dumped and "locator" not in dumped


def test_a_linked_worktree_subject_is_refused_by_the_campaign_verbatim(tmp_path, monkeypatch):
    """A9: G1-ARIADNE-06 -- the campaign refuses a gitdir-pointer subject. The
    refusal is the campaign's own text; the lease cannot claim no effect."""
    from daedalus.ariadne import run_campaign
    from daedalus.ariadne.campaign import protected_prefix_for
    from daedalus.orchestration.ikarus.computer_loop import head_revision
    root, git = _plain_subject(tmp_path, monkeypatch)
    linked = tmp_path / "linked"
    git("worktree", "add", "-q", str(linked), "-b", "side")
    _project(monkeypatch, str(linked))
    runner = subject.CampaignRunner(run_campaign=run_campaign, head_revision=head_revision,
                                    protected_prefix_for=protected_prefix_for)
    service, _ = _service(tmp_path, monkeypatch, runner)
    subject_switch = killswitch.KillSwitch(repo_root=linked)
    assert subject_switch.arm(note="linked worktree subject").running
    try:
        outcome = service.execute(TOOL, {"target_path": "sample.txt", "before": "broken", "after": "fixed"},
                                  mission_id="computer-ariadne-linked", attempt_id="attempt-1")
    finally:
        subject_switch.stop()
    assert outcome["ok"] is False
    assert "linked git worktree" in outcome["error"] and "AriadneRequestError" in outcome["error"]
    assert (linked / "sample.txt").read_text(encoding="utf-8") == "broken\n"


# G1-IKARUS-HOPPING-01: the model chooses a mode, never its own test command.
def test_owner_profile_is_bound_into_campaign_identity_and_passed_to_canonical_runner(tmp_path, monkeypatch):
    from dataclasses import replace
    from daedalus.ariadne.campaign import TestCommandEvaluator
    from daedalus.ariadne.owner_evaluator import OwnerTestProfile
    runner, recorder = _runner()
    evaluator = TestCommandEvaluator(("python", "-m", "pytest", "-q", "tests"), timeout_s=30)
    profile = OwnerTestProfile(evaluator, "a" * 64)
    runner = replace(runner, load_test_profile=lambda root: profile)
    tool = _tool(tmp_path, monkeypatch, runner)
    result = tool.execute({**ARGS, "evaluation": "owner-tests"})
    first_id = recorder.calls[-1]["campaign_id"]
    assert recorder.calls[-1]["evaluator"] is evaluator
    assert callable(recorder.calls[-1]["caller_checkpoint"])
    assert result["evaluation_mode"] == "owner-tests" and result["evaluator_sha256"] == evaluator.digest
    assert result["verdict_is_self_reported"] is True
    assert result["child_network"] == "unrestricted"
    assert result["hopping"]["activation_permitted"] is False
    changed_runner = replace(runner, load_test_profile=lambda root: OwnerTestProfile(evaluator, "b" * 64))
    _tool(tmp_path, monkeypatch, changed_runner).execute({**ARGS, "evaluation": "owner-tests"})
    assert recorder.calls[-1]["campaign_id"] != first_id


def test_requested_owner_tests_without_profile_never_fall_back(tmp_path, monkeypatch):
    runner, recorder = _runner()
    tool = _tool(tmp_path, monkeypatch, runner)
    with pytest.raises(ComputerRefused, match="profile") as caught:
        tool.execute({**ARGS, "evaluation": "owner-tests"})
    assert caught.value.effect_state == "none" and recorder.calls == []


def test_model_test_argv_is_not_admitted(tmp_path, monkeypatch):
    runner, recorder = _runner()
    tool = _tool(tmp_path, monkeypatch, runner)
    with pytest.raises(ComputerRefused):
        tool.execute({**ARGS, "test_argv": ["python", "-c", "pass"]})
    assert recorder.calls == []
