"""Owner configuration, not model-selected tests, controls the campaign judge."""
import json
import os

import pytest

from daedalus.ariadne import owner_evaluator as profiles
from daedalus.ariadne.campaign import protected_prefix_for, AriadneCampaignError


def payload():
    return {"schema": profiles.PROFILE_SCHEMA, "argv": ["python", "-m", "pytest", "-q", "tests"],
            "test_roots": ["tests/"], "timeout_s": 30, "acknowledge_unsandboxed_execution": True}


@pytest.fixture
def configured(tmp_path, monkeypatch):
    repo = tmp_path / "repo"; repo.mkdir()
    control = tmp_path / "control"; control.mkdir()
    monkeypatch.setattr(profiles, "control_root", lambda root: control)
    path = control / profiles.PROFILE_NAME
    path.write_text(json.dumps(payload()), encoding="utf-8")
    return repo, control, path


def test_profile_is_frozen_and_bound_to_exact_configuration(configured):
    repo, control, path = configured
    first = profiles.load_owner_test_profile(str(repo))
    assert first.evaluator.argv == ("python", "-m", "pytest", "-q", "tests")
    changed = payload(); changed["timeout_s"] = 31
    path.write_text(json.dumps(changed))
    second = profiles.load_owner_test_profile(str(repo))
    assert first.evaluator.timeout_s == 30
    assert first.profile_sha256 != second.profile_sha256
    assert first.evaluator.digest != second.evaluator.digest


@pytest.mark.parametrize("key,value", [
    ("acknowledge_unsandboxed_execution", False), ("acknowledge_unsandboxed_execution", "true"),
    ("timeout_s", True), ("timeout_s", 0), ("timeout_s", 121),
    ("argv", ["python", "-c", "print(1)"]),
    ("argv", ["python", "-m", "pytest", "--rootdir=/tmp", "tests/"]),
    ("argv", ["python", "-m", "pytest", "-p", "evil"]),
    ("test_roots", ["../tests"]), ("extra", True),
])
def test_invalid_profile_refuses(configured, key, value):
    repo, _, path = configured
    data = payload(); data[key] = value
    path.write_text(json.dumps(data))
    with pytest.raises((ValueError, TypeError, AriadneCampaignError)):
        profiles.load_owner_test_profile(str(repo))


def test_duplicate_keys_refuse(configured):
    repo, _, path = configured
    path.write_text('{"schema":"first","schema":"second"}')
    with pytest.raises(ValueError, match="duplicate"):
        profiles.load_owner_test_profile(str(repo))


def test_missing_profile_never_falls_back_to_candidate_checkout(configured):
    repo, _, path = configured
    (repo / profiles.PROFILE_NAME).write_bytes(path.read_bytes())
    path.unlink()
    with pytest.raises(Exception):
        profiles.load_owner_test_profile(str(repo))


def test_profile_under_subject_is_refused(configured, monkeypatch):
    repo, _, path = configured
    monkeypatch.setattr(profiles, "control_root", lambda root: repo)
    (repo / profiles.PROFILE_NAME).write_bytes(path.read_bytes())
    with pytest.raises(ValueError, match="outside"):
        profiles.load_owner_test_profile(str(repo))


def test_hardlinked_profile_refuses(configured):
    repo, control, path = configured
    try:
        os.link(path, control / "alias.json")
    except OSError:
        pytest.skip("host does not support hard links")
    with pytest.raises(Exception, match="hard link"):
        profiles.load_owner_test_profile(str(repo))


def test_profile_and_hopping_policy_are_protected_from_self_renovation():
    assert protected_prefix_for("daedalus/ariadne/owner_evaluator.py") is not None
    assert protected_prefix_for("daedalus/kernel/policy/hopping.py") is not None
