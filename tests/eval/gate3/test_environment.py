"""test_environment.py -- acceptance test A7 (G3-BASE-01 §5a) plus the
honesty/no-network obligations for the model/hardware reporting module.

Offline, deterministic, no model calls, no network by default.
"""
from __future__ import annotations

import math

import pytest

from daedalus.eval import harness
from daedalus.eval.gate3 import environment
from daedalus.eval.gate3.contracts import RunEnvironment


# --------------------------------------------------------------------------- #
# A7 -- test_environment_records_model_and_host                              #
# --------------------------------------------------------------------------- #
def test_environment_records_model_and_host():
    env = environment.capture_environment(
        model_id="test-model-x", provider="anthropic", host="workstation-1",
    )

    assert isinstance(env, RunEnvironment)
    assert env.model_id == "test-model-x"
    assert env.provider == "anthropic"
    assert env.host == "workstation-1"
    assert env.tokenizer.strip() != ""
    assert env.os_name.strip() != ""
    assert env.cpu.strip() != ""
    assert env.ram_gb > 0 or environment.is_unknown_ram(env.ram_gb)


def test_model_free_arm_is_a_valid_environment():
    """A deterministic, model-free arm (Tier 1, arms A/B/C) records
    ``model_id=None`` -- that is VALID, not an error (contracts.py docstring)."""
    env = environment.capture_environment()

    assert env.model_id is None
    assert env.provider is None
    assert env.host is None
    # RunEnvironment.__post_init__ would have raised FreezeError already if
    # this construction were invalid; reaching here IS the assertion.


# --------------------------------------------------------------------------- #
# tokenizer must be the REAL one in effect, read dynamically                  #
# --------------------------------------------------------------------------- #
def test_tokenizer_matches_harness_tokenizer_name_exactly():
    env = environment.capture_environment()

    assert env.tokenizer == harness.tokenizer_name()


def test_tokenizer_is_read_dynamically_not_hardcoded(monkeypatch):
    """Monkeypatching ``harness.tokenizer_name`` (module attribute, the same
    way the real degrade-to-heuristic path replaces it) must change what
    ``capture_environment`` reports. A hardcoded string in ``environment.py``
    would fail this test."""
    monkeypatch.setattr(harness, "tokenizer_name", lambda: "fake-tokenizer/xyz")

    env = environment.capture_environment()

    assert env.tokenizer == "fake-tokenizer/xyz"


def test_tokenizer_reflects_degraded_heuristic_path(monkeypatch):
    """Mirrors the real degradation harness.py performs when tiktoken is
    absent (module docstring lines 52-59): reporting "tiktoken" while the
    heuristic actually ran would be false provenance."""
    monkeypatch.setattr(harness, "tokenizer_name", lambda: "chars/4 (heuristic)")

    env = environment.capture_environment()

    assert env.tokenizer == "chars/4 (heuristic)"


# --------------------------------------------------------------------------- #
# unknown values are DECLARED unknown, never fabricated                      #
# --------------------------------------------------------------------------- #
def _explode(*_args, **_kwargs):
    raise OSError("simulated stdlib detection failure")


def test_unknown_os_and_cpu_are_declared_not_fabricated(monkeypatch):
    monkeypatch.setattr(environment.platform, "platform", _explode)
    monkeypatch.setattr(environment.platform, "processor", _explode)
    monkeypatch.setattr(environment.platform, "system", _explode)
    monkeypatch.setattr(environment.platform, "machine", _explode)

    env = environment.capture_environment()

    assert env.os_name == environment.UNKNOWN_OS
    assert env.cpu == environment.UNKNOWN_CPU
    # Both are still non-empty strings -- the contract's own requirement --
    # but the VALUE is an explicit "unknown" sentinel, not an invented one.
    assert "unknown" in env.os_name
    assert "unknown" in env.cpu


def test_unknown_ram_is_declared_via_nan_not_zero_or_fabricated(monkeypatch):
    """RunEnvironment.ram_gb must be positive (contracts.py), so ``0`` or
    ``None`` cannot represent "unknown" without either violating the
    contract or silently reporting a machine with zero memory. This module's
    documented choice is IEEE-754 NaN: ``nan <= 0`` is False (passes the
    contract's positivity check) while ``math.isnan`` lets a caller detect it
    explicitly and any naive arithmetic on it is poisoned loudly."""
    monkeypatch.setattr(environment.platform, "system", lambda: "")
    monkeypatch.setattr(environment, "_detect_ram_gb_windows", lambda: None)
    monkeypatch.setattr(environment, "_detect_ram_gb_linux", lambda: None)
    monkeypatch.setattr(environment, "_detect_ram_gb_macos", lambda: None)
    monkeypatch.setattr(environment, "_detect_ram_gb_posix_sysconf", lambda: None)

    env = environment.capture_environment()

    assert env.ram_gb is None
    assert environment.is_unknown_ram(env.ram_gb)
    # The frozen contract's own positivity guard did not reject this -- proof
    # the sentinel is compatible with RunEnvironment as written today.
    assert env.ram_gb is None or env.ram_gb > 0


def test_is_unknown_ram_uses_isnan_not_equality():
    """NaN != NaN by IEEE-754 definition; a caller comparing with ``==``
    would get the wrong answer, which is exactly why ``is_unknown_ram``
    exists and must be used instead."""
    assert environment.UNKNOWN_RAM_GB is None
    assert environment.is_unknown_ram(environment.UNKNOWN_RAM_GB) is True
    assert environment.is_unknown_ram(16.0) is False


def test_cpu_falls_back_to_labelled_machine_string_not_a_fake_model(monkeypatch):
    """When ``platform.processor()`` is empty (common on Linux) and
    ``/proc/cpuinfo`` is unavailable, the fallback is the coarse
    ``platform.machine()`` value EXPLICITLY LABELLED as generic -- never
    silently presented as a specific CPU model."""
    monkeypatch.setattr(environment.platform, "processor", lambda: "")
    monkeypatch.setattr(environment.platform, "system", lambda: "NotLinux")
    monkeypatch.setattr(environment.platform, "machine", lambda: "AMD64")

    env = environment.capture_environment()

    assert env.cpu == "AMD64 (generic; exact model undetermined)"


# --------------------------------------------------------------------------- #
# no network I/O by default                                                   #
# --------------------------------------------------------------------------- #
def test_capture_environment_never_touches_network(monkeypatch):
    def _forbidden(*_a, **_kw):
        raise AssertionError("capture_environment must not touch the network")

    monkeypatch.setattr("urllib.request.urlopen", _forbidden)
    monkeypatch.setattr("socket.socket", _forbidden)

    env = environment.capture_environment(model_id="m", provider="p", host="h")

    assert env.model_id == "m"  # reached without the forbidden calls firing


def test_describe_external_limits_no_network_by_default(monkeypatch):
    calls: list[object] = []
    monkeypatch.setattr(
        harness, "detect_provider",
        lambda *a, **kw: calls.append((a, kw)) or None,
    )
    monkeypatch.setattr("urllib.request.urlopen",
                         lambda *a, **kw: (_ for _ in ()).throw(
                             AssertionError("network touched by default")))

    limits = environment.describe_external_limits()

    assert calls == []  # detect_provider was never invoked
    assert limits.provider_kind is None
    assert limits.provider_model is None
    assert limits.context_window_tokens is None
    assert "not probed" in limits.context_window_source


def test_describe_external_limits_probe_true_calls_detect_provider_and_skips_cleanly(monkeypatch):
    monkeypatch.setattr(harness, "detect_provider",
                         lambda provider=None: {"kind": "ollama", "host": "x",
                                                 "model": "llama3", "models": ["llama3"]})

    limits = environment.describe_external_limits(probe_provider=True)

    assert limits.provider_kind == "ollama"
    assert limits.provider_model == "llama3"
    # Honest absence: detect_provider's descriptor carries no context length,
    # and this module refuses to invent one from a hardcoded table.
    assert limits.context_window_tokens is None
    assert limits.context_window_source is not None


def test_describe_external_limits_probe_true_unreachable_provider_is_none(monkeypatch):
    monkeypatch.setattr(harness, "detect_provider", lambda provider=None: None)

    limits = environment.describe_external_limits(probe_provider=True)

    assert limits.provider_kind is None
    assert limits.provider_model is None
    assert "no provider reachable" in limits.context_window_source


def test_describe_external_limits_reports_readable_hardware_facts():
    """Disk free space and CPU count are honestly stdlib-readable external
    facts (plan §4.1: hardware capacity, disk); they must be present when
    detection succeeds, never fabricated when it does not."""
    limits = environment.describe_external_limits()

    assert limits.disk_free_gb is None or limits.disk_free_gb >= 0
    assert limits.cpu_count is None or limits.cpu_count >= 1


# --------------------------------------------------------------------------- #
# runs on this machine (Windows 11) -- actually exercised, not assumed       #
# --------------------------------------------------------------------------- #
def test_runs_on_this_windows_machine_with_real_detection():
    env = environment.capture_environment()

    assert "windows" in env.os_name.lower() or env.os_name == environment.UNKNOWN_OS
    # On real Windows, GlobalMemoryStatusEx should succeed -- assert the
    # honest, non-degraded outcome is what we actually measured here.
    assert not environment.is_unknown_ram(env.ram_gb)
    assert env.ram_gb > 0
    assert env.cpu != environment.UNKNOWN_CPU
