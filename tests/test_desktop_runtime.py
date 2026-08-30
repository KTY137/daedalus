from __future__ import annotations

import os

import pytest

from daedalus import sensitivity
from daedalus.desktop_runtime import (
    REMOTE_OK_VAR,
    TRUSTED_HOSTS_VAR,
    TUNNEL_FORWARD_VAR,
    TUNNEL_TARGET_VAR,
    DesktopRuntimeManager,
    install_tunnel_egress_policy,
    normalize_config,
)

_RUNTIME_ENV = (
    "OLLAMA_HOST",
    "OLLAMA_MODEL",
    REMOTE_OK_VAR,
    TRUSTED_HOSTS_VAR,
    TUNNEL_FORWARD_VAR,
    TUNNEL_TARGET_VAR,
)


@pytest.fixture(autouse=True)
def restore_runtime_env():
    before = {key: os.environ.get(key) for key in _RUNTIME_ENV}
    yield
    for key, value in before.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def remote_config(**patch):
    remote = {
        "host": "192.168.50.20",
        "user": "kaya",
        "port": 22,
        "identity_file": "",
        "host_key_fingerprint": "SHA256:" + "A" * 43,
        "local_port": 11435,
        "remote_port": 11434,
        "start_method": "none",
        "trust_remote_host": False,
    }
    remote.update(patch)
    return {
        "bridge": {"auto_start": True},
        "ollama": {
            "mode": "remote_ssh",
            "auto_start": False,
            "model": "qwen2.5-coder:7b",
            "local_host": "http://127.0.0.1:11434",
            "remote": remote,
        },
    }


def test_defaults_autostart_bridge_and_local_ollama():
    cfg = normalize_config({})
    assert cfg["bridge"]["auto_start"] is True
    assert cfg["ollama"]["auto_start"] is True
    assert cfg["ollama"]["mode"] == "local"


def test_settings_do_not_accept_password_or_private_key_bytes():
    cfg = normalize_config(
        remote_config(password="do-not-store", private_key="-----BEGIN PRIVATE KEY-----")
    )
    remote = cfg["ollama"]["remote"]
    assert "password" not in remote
    assert "private_key" not in remote
    assert set(remote) == {
        "host",
        "user",
        "port",
        "identity_file",
        "host_key_fingerprint",
        "local_port",
        "remote_port",
        "start_method",
        "trust_remote_host",
    }


def test_remote_mode_rejects_option_injection_and_dns_trust():
    with pytest.raises(ValueError):
        normalize_config(remote_config(host="-oProxyCommand=evil"))
    with pytest.raises(ValueError):
        normalize_config(remote_config(host="bench.example", trust_remote_host=True))


def test_remote_environment_keeps_transport_and_physical_target_separate(tmp_path, monkeypatch):
    monkeypatch.delenv(TRUSTED_HOSTS_VAR, raising=False)
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config(remote_config())
    manager.apply_environment()
    try:
        assert os.environ["OLLAMA_HOST"] == "http://127.0.0.1:11435"
        assert os.environ[TUNNEL_FORWARD_VAR] == "http://127.0.0.1:11435"
        assert os.environ[TUNNEL_TARGET_VAR] == "http://192.168.50.20:11434"
        assert os.environ[REMOTE_OK_VAR] == "http://127.0.0.1:11435"
    finally:
        manager.close()


def test_tunnel_forward_is_egress_even_though_socket_is_loopback(monkeypatch):
    install_tunnel_egress_policy()
    monkeypatch.delenv(TRUSTED_HOSTS_VAR, raising=False)
    monkeypatch.setenv(TUNNEL_FORWARD_VAR, "http://127.0.0.1:11435")
    monkeypatch.setenv(TUNNEL_TARGET_VAR, "http://192.168.50.20:11434")

    assert sensitivity.is_loopback_host("http://127.0.0.1:11435") is True
    assert sensitivity.lane_for_host("http://127.0.0.1:11435") == "untrusted"
    assert sensitivity.lane_for_host("http://127.0.0.1:11434") == "trusted"


def test_explicit_numeric_remote_trust_survives_tunnel(monkeypatch):
    install_tunnel_egress_policy()
    monkeypatch.setenv(TRUSTED_HOSTS_VAR, "192.168.50.20")
    monkeypatch.setenv(TUNNEL_FORWARD_VAR, "http://127.0.0.1:11435")
    monkeypatch.setenv(TUNNEL_TARGET_VAR, "http://192.168.50.20:11434")
    assert sensitivity.lane_for_host("http://127.0.0.1:11435") == "trusted"


def test_ssh_is_strict_key_only(tmp_path, monkeypatch):
    manager = DesktopRuntimeManager(tmp_path)
    manager.config = normalize_config(remote_config(host_key_fingerprint=""))
    manager.apply_environment()
    monkeypatch.setattr("daedalus.desktop_runtime.shutil.which", lambda name: f"/bin/{name}")
    try:
        args = manager._ssh()
    finally:
        manager.close()
    joined = " ".join(args)
    assert "BatchMode=yes" in joined
    assert "PasswordAuthentication=no" in joined
    assert "KbdInteractiveAuthentication=no" in joined
    assert "StrictHostKeyChecking=yes" in joined
    assert "UserKnownHostsFile=" in joined


def test_corrupt_settings_fall_back_without_bricking_desktop(tmp_path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "connections.json").write_text("{not-json", encoding="utf-8")

    manager = DesktopRuntimeManager(tmp_path)
    try:
        assert manager.config["ollama"]["mode"] == "local"
        assert "cannot read" in manager._config_error
    finally:
        manager.close()


def test_local_endpoint_must_be_numeric_loopback_and_clean_url():
    with pytest.raises(ValueError):
        normalize_config({"ollama": {"local_host": "http://localhost:11434"}})
    with pytest.raises(ValueError):
        normalize_config({"ollama": {"local_host": "http://0.0.0.0:11434"}})
    with pytest.raises(ValueError):
        normalize_config({"ollama": {"local_host": "http://user@127.0.0.1:11434"}})
    with pytest.raises(ValueError):
        normalize_config({"ollama": {"local_host": "http://127.0.0.1:11434?x=1"}})


def test_ipv6_loopback_keeps_required_brackets():
    cfg = normalize_config({"ollama": {"local_host": "http://[::1]:11434"}})
    assert cfg["ollama"]["local_host"] == "http://[::1]:11434"
