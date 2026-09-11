"""Owner commands and nested cancellation; no test claims live model behavior."""
from types import SimpleNamespace

import pytest

from daedalus.orchestration.ikarus import computer_loop as loop
from daedalus.runtimes import computer
from daedalus.interfaces import computer_configuration
from daedalus.orchestration.genesis import service as genesis
from daedalus.orchestration.execution import attempts


@pytest.fixture
def commands(monkeypatch):
    changes = []
    current = {"tools": ["daedalus.status"], "workspace": "/unused"}
    monkeypatch.setattr(computer, "computer_status", lambda *a, **k:
                        {"configuration": current, "policy_sha256": "a" * 64})
    def configure(root, policy, *, owner_confirmed, expected_policy_sha256):
        changes.append((policy, owner_confirmed, expected_policy_sha256))
        return {"policy_sha256": "b" * 64}
    monkeypatch.setattr(computer_configuration, "configure_computer", configure)
    return current, changes


def final(command, project="fixture"):
    return list(loop.conversation_events(project, command))[-1][1]


def test_genesis_grant_requires_explicit_transient_confirmation(commands):
    current, changes = commands
    result = final("/computer enable genesis")
    assert result["computer"]["genesis_tools_change"] == "confirmation_required"
    assert changes == [] and current["tools"] == ["daedalus.status"]
    result = final("/computer enable genesis confirm-builds")
    assert result["computer"]["genesis_tools_change"] == "applied"
    assert changes[0][0]["tools"] == ["daedalus.status", "daedalus.genesis"]
    assert changes[0][1:] == (True, "a" * 64)
    assert "confirm-builds" not in str(changes[0][0])


def test_genesis_revoke_preserves_other_grants_and_noop_writes_nothing(commands):
    current, changes = commands
    result = final("/computer disable genesis")
    assert result["computer"]["genesis_tools_change"] == "unchanged" and not changes
    current["tools"].append("daedalus.genesis")
    result = final("/computer disable genesis")
    assert result["computer"]["genesis_tools_change"] == "applied"
    assert changes[0][0]["tools"] == ["daedalus.status"]


@pytest.mark.parametrize("command", ["/computer enable genesis force", "/computer enable genesis confirm-builds publish"])
def test_unknown_grant_flags_refuse(commands, command):
    assert final(command)["intent"] == "error"
    assert commands[1] == []


def test_hop_uses_existing_mission_loop_with_narrowed_mode(monkeypatch):
    calls = []
    def run(project, root, objective, cancelled, *, hopping=False):
        calls.append((project, objective, hopping, cancelled))
        yield "final", {"intent": "computer", "assistant": "fixture"}
    monkeypatch.setattr(loop, "_run_objective", run)
    assert final("/computer hop improve parser")["intent"] == "computer"
    assert len(calls) == 1 and calls[0][0] == "fixture" and calls[0][2] is True
    assert "improve parser" in calls[0][1] and "evaluation=owner-tests" in calls[0][1]
    assert "never" in calls[0][1].lower()


@pytest.mark.parametrize("command,project", [("/computer hop", "fixture"), ("/computer hop improve parser", None)])
def test_hop_requires_objective_and_registered_project_context(monkeypatch, command, project):
    monkeypatch.setattr(loop, "_run_objective", lambda *a, **k: pytest.fail("should not run"))
    assert final(command, project)["intent"] == "error"


def test_outer_policy_cancellation_reaches_nested_genesis_gate(tmp_path, monkeypatch):
    calls = []
    def checkpoint():
        calls.append(1)
        if len(calls) > 1:
            raise RuntimeError("owner cancelled")
    monkeypatch.setattr(genesis, "resolve_python_argv", lambda argv: tuple(argv))
    monkeypatch.setattr(genesis, "interpreter_provenance", lambda *a: {})
    def command_gate(*a, **kw):
        def gate(context):
            assert context.is_cancelled() is True
            return SimpleNamespace(returncode=1, output="cancelled", timed_out=False,
                                   cancelled=True, duration_s=0.01,
                                   containment=SimpleNamespace(summary=lambda: {"contained": True}))
        return gate
    monkeypatch.setattr(attempts, "command_gate", command_gate)
    observation = genesis._run_command("runtime", ("python", "verify.py"), task_id="cancel-fixture",
        candidate_tree_sha256="a" * 64, workspace=tmp_path, timeout_s=30,
        switch=SimpleNamespace(checkpoint=lambda: None, should_stop=lambda: False), caller_checkpoint=checkpoint)
    assert observation.cancelled and len(calls) == 2


def test_genesis_cancellation_before_entry_creates_no_artifacts(tmp_path):
    def stop():
        raise RuntimeError("owner cancelled")
    with pytest.raises(RuntimeError, match="owner cancelled"):
        genesis.run_genesis("Build a task board", repo_root=tmp_path, caller_checkpoint=stop)
    assert list(tmp_path.iterdir()) == []
