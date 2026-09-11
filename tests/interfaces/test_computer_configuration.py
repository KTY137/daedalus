from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest

from daedalus.interfaces import computer_configuration as subject
from daedalus.kernel.policy.computer import ComputerPolicy, ComputerRefused, FILE_TOOLS, load_policy, policy_path
from daedalus.spine import killswitch
from daedalus.spine.effect_boundary import EffectStartRefused, GuardDecision


@pytest.fixture
def configured(tmp_path, monkeypatch):
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setattr(killswitch, "OS_PROFILE_DIR", profile)
    monkeypatch.delenv("DAEDALUS_KILLSWITCH", raising=False)
    authority = tmp_path / "authority"
    authority.mkdir()
    workspace = tmp_path / "scratch"
    workspace.mkdir()
    policy = ComputerPolicy(workspace, tools=FILE_TOOLS)
    destination = policy_path(authority)
    destination.parent.mkdir(parents=True)
    destination.write_text(json.dumps(policy.to_dict()), encoding="utf-8")
    return authority, policy, destination


def test_explicit_policy_update_atomic_readback_and_canonical_evidence(configured):
    root, current, path = configured
    proposed = replace(current, tools=current.tools + ("browser.navigate", "app.launch"),
                       origins=("http://127.0.0.1:8080",),
                       applications=(("scratch-editor", (str(root.parent / "trusted-tools" / "editor.exe"),)),))
    result = subject.configure_computer(root, proposed.to_dict(), owner_confirmed=True,
                                       expected_policy_sha256=current.digest)
    assert result["ok"] is True and result["changed"] is True
    assert load_policy(root).digest == proposed.digest == result["policy_sha256"]
    terminal = json.loads((path.parent / "computer-artifacts" / (result["evidence"]["sha256"] + ".json")).read_text())
    assert terminal["base_policy_sha256"] == current.digest
    assert terminal["result_policy_sha256"] == proposed.digest
    assert terminal["phase"] == "completed"
    assert not list(path.parent.glob("computer-policy-*.tmp"))


@pytest.mark.parametrize("confirmation", [False, None, "yes", 1])
def test_confirmation_is_transient_exact_boolean_and_precedes_effects(configured, monkeypatch, confirmation):
    root, policy, path = configured
    before = path.read_bytes()
    monkeypatch.setattr(subject, "begin_effect", lambda *a, **k: pytest.fail("no effect admission expected"))
    with pytest.raises(ComputerRefused, match="owner"):
        subject.configure_computer(root, policy.to_dict(), owner_confirmed=confirmation, expected_policy_sha256=policy.digest)
    assert path.read_bytes() == before


def test_stale_policy_refuses_before_lock_or_evidence(configured, monkeypatch):
    root, policy, path = configured
    before = path.read_bytes()
    monkeypatch.setattr(subject, "begin_effect", lambda *a, **k: pytest.fail("no effect admission expected"))
    with pytest.raises(ComputerRefused, match="changed"):
        subject.configure_computer(root, policy.to_dict(), owner_confirmed=True, expected_policy_sha256="0" * 64)
    assert path.read_bytes() == before
    assert not (path.parent / "computer-setup.lock").exists()


@pytest.mark.parametrize("change", ["partial", "control", "installation", "unknown", "invalid_origin"])
def test_invalid_or_protected_scope_has_no_effect(configured, monkeypatch, change):
    root, policy, path = configured
    payload = policy.to_dict()
    if change == "partial":
        payload.pop("tools")
    elif change == "control":
        payload["workspace"] = str(path.parent)
    elif change == "installation":
        payload["workspace"] = str(Path(subject.__file__).resolve().parents[2])
    elif change == "unknown":
        payload["owner_confirmed"] = True
    else:
        payload["origins"] = ["file:///C:/sensitive"]
    before = path.read_bytes()
    monkeypatch.setattr(subject, "begin_effect", lambda *a, **k: pytest.fail("no effect admission expected"))
    with pytest.raises(ComputerRefused):
        subject.configure_computer(root, payload, owner_confirmed=True, expected_policy_sha256=policy.digest)
    assert path.read_bytes() == before


def test_process_guard_denial_preserves_configuration(configured, monkeypatch):
    root, policy, path = configured
    before = path.read_bytes()
    monkeypatch.setattr(subject, "process_guard_boundary_decision", lambda: GuardDecision("budget.process_guard", False, "fixture denied"))
    with pytest.raises(EffectStartRefused, match="denied"):
        subject.configure_computer(root, replace(policy, max_steps=17).to_dict(), owner_confirmed=True, expected_policy_sha256=policy.digest)
    assert path.read_bytes() == before


def test_replace_failure_retains_original_and_cleans_temporary(configured, monkeypatch):
    root, policy, path = configured
    before = path.read_bytes()
    def fail(*args):
        raise OSError("fixture replace failure")
    monkeypatch.setattr(subject.os, "replace", fail)
    with pytest.raises(OSError, match="replace failure"):
        subject.configure_computer(root, replace(policy, max_steps=17).to_dict(), owner_confirmed=True, expected_policy_sha256=policy.digest)
    assert path.read_bytes() == before
    assert not list(path.parent.glob("computer-policy-*.tmp"))


def test_competing_update_during_preparation_is_not_overwritten(configured, monkeypatch):
    root, policy, path = configured
    competitor = replace(policy, max_steps=23)
    real_temporary = subject.tempfile.NamedTemporaryFile
    def interleave(*args, **kwargs):
        result = real_temporary(*args, **kwargs)
        path.write_text(json.dumps(competitor.to_dict()), encoding="utf-8")
        return result
    monkeypatch.setattr(subject.tempfile, "NamedTemporaryFile", interleave)
    with pytest.raises(ComputerRefused, match="changed during"):
        subject.configure_computer(root, replace(policy, max_steps=17).to_dict(), owner_confirmed=True, expected_policy_sha256=policy.digest)
    assert load_policy(root).digest == competitor.digest


def test_noop_has_no_effect_or_confirmation_persistence(configured, monkeypatch):
    root, policy, path = configured
    before = path.read_bytes()
    monkeypatch.setattr(subject, "begin_effect", lambda *a, **k: pytest.fail("no effect admission expected"))
    result = subject.configure_computer(root, policy.to_dict(), owner_confirmed=True, expected_policy_sha256=policy.digest)
    assert result["changed"] is False and result["evidence"] is None
    assert path.read_bytes() == before and "owner_confirmed" not in json.loads(before)


def test_configuration_does_not_clear_sticky_stop(configured):
    root, policy, _ = configured
    switch = killswitch.KillSwitch(repo_root=root, sweep_managed=False)
    switch.stop("fixture stop remains authoritative")
    state = switch.read_state()
    subject.configure_computer(root, replace(policy, max_steps=17).to_dict(), owner_confirmed=True, expected_policy_sha256=policy.digest)
    assert switch.read_state() == state


def test_post_replace_evidence_failure_reports_changed_state(configured, monkeypatch):
    root, policy, _ = configured
    proposed = replace(policy, max_steps=17)
    real_store = subject.store_canonical_json
    def store(root, data):
        if data["phase"] == "completed":
            raise OSError("fixture final evidence failure")
        return real_store(root, data)
    monkeypatch.setattr(subject, "store_canonical_json", store)
    with pytest.raises(ComputerRefused, match="policy was changed"):
        subject.configure_computer(root, proposed.to_dict(), owner_confirmed=True, expected_policy_sha256=policy.digest)
    assert load_policy(root).digest == proposed.digest


def test_missing_policy_does_not_implicitly_setup(configured, monkeypatch):
    root, policy, _ = configured
    other = root.parent / "unconfigured"
    other.mkdir()
    monkeypatch.setattr(subject, "begin_effect", lambda *a, **k: pytest.fail("no effect admission expected"))
    with pytest.raises(ComputerRefused, match="unavailable"):
        subject.configure_computer(other, policy.to_dict(), owner_confirmed=True, expected_policy_sha256=policy.digest)
    assert not policy_path(other).exists()


def test_supplied_workspace_symlink_is_not_erased_by_resolution(configured, monkeypatch):
    root, policy, path = configured
    linked = root.parent / "linked-workspace"
    try:
        linked.symlink_to(policy.workspace, target_is_directory=True)
    except OSError:
        pytest.skip("host lacks symlink creation permission")
    payload = policy.to_dict()
    payload["workspace"] = str(linked)
    before = path.read_bytes()
    monkeypatch.setattr(subject, "begin_effect", lambda *a, **k: pytest.fail("no effect admission expected"))
    with pytest.raises(ComputerRefused, match="link"):
        subject.configure_computer(root, payload, owner_confirmed=True, expected_policy_sha256=policy.digest)
    assert path.read_bytes() == before


@pytest.mark.parametrize("application", ["interpreter", "candidate"])
def test_host_configuration_cannot_grant_candidate_or_interpreter_execution(configured, application):
    root, policy, path = configured
    payload = policy.to_dict()
    executable = Path(sys.executable).resolve() if application == "interpreter" else policy.workspace / "candidate.exe"
    payload["tools"].append("app.launch")
    payload["applications"] = {"unsafe": [str(executable)]}
    before = path.read_bytes()
    with pytest.raises(ComputerRefused):
        subject.configure_computer(root, payload, owner_confirmed=True, expected_policy_sha256=policy.digest)
    assert path.read_bytes() == before
