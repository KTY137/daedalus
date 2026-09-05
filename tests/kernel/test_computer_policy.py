"""Independent refusal tests for exact computer scope and path authority."""
from __future__ import annotations

from dataclasses import replace
import json
import os
from pathlib import Path

import pytest

from daedalus.kernel.policy.computer import (
    PATH_IO_RELEASE_REFUSAL,
    ComputerPolicy,
    ComputerRefused,
    admit_operation,
    load_policy,
    origin,
    policy_path,
)
from daedalus.spine import killswitch


@pytest.fixture
def policy(tmp_path):
    workspace = tmp_path / "scratch"
    workspace.mkdir()
    return ComputerPolicy(workspace=workspace, tools=("file.read", "file.write"))


@pytest.mark.parametrize("path", ["../escape", "nested/../../escape", "/absolute", "C:/escape",
                                   "C:escape", "\\\\server\\share", "safe.txt:secret", "folder./x",
                                   "folder /x", ".git/config", "x/.AgEnTeNv/policy.json", "AGENTS.md",
                                   "computer-policy.json", "docs/IKARUS_ARIADNE_MASTER_PLAN.md",
                                   "NUL", "CON.txt", "COM1", "LPT9.log", "nul.txt", "x\x00y"])
def test_traversal_ads_devices_and_control_paths_are_refused(policy, path):
    with pytest.raises(ComputerRefused):
        policy.path(path)


def test_nested_relative_path_is_retained_in_workspace(policy):
    assert policy.path("folder/hello.txt") == policy.workspace / "folder" / "hello.txt"


def _symlink(link: Path, target: Path):
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable on host: {exc}")


def test_link_escape_is_refused(policy, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    link = policy.workspace / "linked"
    _symlink(link, outside)
    with pytest.raises(ComputerRefused):
        policy.path("linked/new.txt")


def test_linked_workspace_root_is_refused(policy, tmp_path):
    link = tmp_path / "linked-root"
    _symlink(link, policy.workspace)
    with pytest.raises(ComputerRefused):
        ComputerPolicy(workspace=link, tools=policy.tools)


def test_hardlinked_file_is_refused(policy, tmp_path):
    original = tmp_path / "external.txt"
    original.write_bytes(b"external data")
    try:
        os.link(original, policy.workspace / "hardlink.txt")
    except OSError as exc:
        pytest.skip(f"hard links unavailable on host: {exc}")
    with pytest.raises(ComputerRefused):
        policy.path("hardlink.txt")
    assert original.read_bytes() == b"external data"


def test_policy_roundtrip_and_exact_digest_change(policy):
    assert ComputerPolicy.from_dict(policy.to_dict()).digest == policy.digest
    assert replace(policy, tools=("file.read",)).digest != policy.digest
    with pytest.raises(ComputerRefused):
        ComputerPolicy.from_dict({**policy.to_dict(), "extra_authority": True})
    with pytest.raises(ComputerRefused):
        policy.admit("file.move", {})


@pytest.mark.parametrize("url", ["file:///etc/passwd", "https://user:pass@example.com", "javascript:alert(1)",
                                  "http://example.com:99999", "data:text/html,hello", "https://"])
def test_non_http_or_credential_urls_are_refused(url):
    with pytest.raises(ComputerRefused):
        origin(url)


def test_browser_origin_is_exact_not_hostname_prefix(policy):
    web = replace(policy, tools=("browser.navigate",), origins=("https://example.com",))
    web.admit("browser.navigate", {"url": "https://EXAMPLE.com/path"})
    for url in ("http://example.com", "https://example.com:444", "https://example.com.evil.invalid"):
        with pytest.raises(ComputerRefused):
            web.admit("browser.navigate", {"url": url})


@pytest.mark.parametrize(("tool", "arguments"), [
    ("file.list", {"path": "."}),
    ("file.read", {"path": "note.txt"}),
    ("file.write", {"path": "note.txt", "text": "data"}),
    ("file.mkdir", {"path": "folder"}),
    ("file.move", {"source": "a", "destination": "b", "expected_sha256": "0" * 64}),
    ("vision.match", {"observation_id": "observed", "template": "template.png"}),
    ("vision.changes", {"before": "a.png", "after": "b.png"}),
    ("vision.inspect", {"path": "image.png"}),
    ("vision.ocr", {"path": "image.png"}),
])
def test_v016_release_fence_refuses_every_workspace_path_shape(policy, tool, arguments):
    fenced = replace(policy, tools=(tool,))
    with pytest.raises(ComputerRefused, match="handle-relative") as refusal:
        fenced.admit(tool, arguments)
    assert str(refusal.value) == PATH_IO_RELEASE_REFUSAL


def test_observation_backed_vision_does_not_open_the_path_fence(policy):
    observation_only = replace(policy, tools=("vision.inspect", "vision.ocr"))
    observation_only.admit("vision.inspect", {"observation_id": "observed"})
    observation_only.admit("vision.ocr", {"observation_id": "observed"})


@pytest.mark.parametrize("arguments", [
    {},
    {"source": "image.png"},
    {"template": "image.png"},
    {"observation_id": "observed", "source": "image.png"},
    {"observation_id": 1},
    {"observation_id": ""},
])
@pytest.mark.parametrize("tool", ["vision.inspect", "vision.ocr"])
def test_observation_only_kernel_admission_requires_exact_token_shape(policy, tool, arguments):
    observation_only = replace(policy, tools=(tool,))
    with pytest.raises(ComputerRefused, match="handle-relative") as refusal:
        observation_only.admit(tool, arguments)
    assert str(refusal.value) == PATH_IO_RELEASE_REFUSAL


def test_policy_control_root_is_disjoint_and_operation_binds_current_digest(tmp_path, monkeypatch, policy):
    profile = tmp_path / "profile"
    profile.mkdir()
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setattr(killswitch, "OS_PROFILE_DIR", profile)
    authority = tmp_path / "authority"
    authority.mkdir()
    path = policy_path(authority)
    path.parent.mkdir(parents=True)
    release_safe = replace(policy, tools=("browser.navigate",), origins=("https://example.com",))
    path.write_text(json.dumps(release_safe.to_dict()), encoding="utf-8")
    operation = {"tool": "browser.navigate", "arguments": {"url": "https://example.com/read"},
                 "policy_sha256": release_safe.digest}
    assert admit_operation(authority, operation).digest == release_safe.digest
    for invalid in ({**operation, "policy_sha256": "0" * 64}, {**operation, "extra": "authority"}):
        with pytest.raises(ComputerRefused):
            admit_operation(authority, invalid)
    unsafe = replace(release_safe, workspace=path.parent)
    path.write_text(json.dumps(unsafe.to_dict()), encoding="utf-8")
    with pytest.raises(ComputerRefused, match="disjoint"):
        load_policy(authority)
