"""Adversarial contracts for the v0.1.6 desktop effect owner."""
from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from daedalus import desktop_runtime
from daedalus.interfaces.desktop import effects, http as desktop_http, projection


_DEFAULT_RETAIN = object()


def _manager(root: Path) -> desktop_runtime.DesktopRuntimeManager:
    manager = object.__new__(desktop_runtime.DesktopRuntimeManager)
    manager.root = root.resolve()
    manager.config_path = manager.root / "config" / "connections.json"
    manager._lock = threading.RLock()
    manager.config = desktop_runtime.normalize_config({})
    manager._config_error = ""
    manager._budget_policy_error = ""
    manager._base_trusted = ""
    manager._ollama_observation = {
        "observed": False,
        "endpoint": manager.config["ollama"]["local_host"],
        "observed_at": None,
        "reachable": False,
        "last_error": "not probed",
    }
    manager._closed = False
    manager._bridge_start_error = ""
    manager._effect_owner = effects.DesktopEffectOwner(
        manager,
        error_type=desktop_runtime.DesktopRuntimeError,
    )
    return manager


class _Authorization:
    def __init__(self, *, fail_completed: bool = False) -> None:
        self.fail_completed = fail_completed
        self.begin_calls: list[object] = []
        self.outcomes: list[str] = []

    def begin_effect(self, execution: object) -> SimpleNamespace:
        self.begin_calls.append(execution)
        return SimpleNamespace(execute=True, receipt=object())

    def finish_effect(
        self,
        receipt: object,
        *,
        outcome: str,
        detail_sha256: str,
    ) -> None:
        assert receipt is not None
        assert re.fullmatch(r"[0-9a-f]{64}", detail_sha256)
        if outcome == "COMPLETED" and self.fail_completed:
            raise OSError("terminal receipt unavailable")
        self.outcomes.append(outcome)


class _Grant:
    def __init__(
        self,
        *,
        entrypoint_id: str = effects.SETTINGS_ENTRYPOINT_ID,
        evidence_errors: list[str] | None = None,
        fail_completed: bool = False,
        retain_value: Any = _DEFAULT_RETAIN,
        retain_error: str = "",
    ) -> None:
        self.execution = SimpleNamespace(execution_id="execution-1")
        self.lease = SimpleNamespace(entrypoint_id=entrypoint_id)
        self.authorization = _Authorization(fail_completed=fail_completed)
        self.evidence_errors = list(evidence_errors or [])
        self.retain_value = (
            {"record_sha256": "c" * 64}
            if retain_value is _DEFAULT_RETAIN
            else retain_value
        )
        self.retain_error = retain_error
        self.evidence_records = {
            "lease_subject": "a" * 64,
            "lease_execution:execution-1": "b" * 64,
        }
        self.retained: list[object] = []

    def execution_for(self, position: int, **kwargs: object) -> object:
        assert position == 0
        self.execution_kwargs = kwargs
        return self.execution

    def retain_terminal_record(self, execution: object) -> Any:
        assert execution is self.execution
        self.retained.append(execution)
        if self.retain_error:
            self.evidence_errors.append(self.retain_error)
        return self.retain_value


def _install_fake_lease(
    monkeypatch: pytest.MonkeyPatch,
    owner: effects.DesktopEffectOwner,
    grant: _Grant,
    *,
    nonce: str = "d" * 32,
    switch: Any | None = None,
) -> dict[str, Any]:
    captured: dict[str, Any] = {}
    if switch is None:
        switch = SimpleNamespace(checkpoint=lambda: None)
    monkeypatch.setattr(owner, "_ensure_switch", lambda: switch)
    monkeypatch.setattr(owner, "_source_revision", "e" * 40)
    monkeypatch.setattr(
        effects.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex=nonce),
    )

    def acquire(root: Path, **kwargs: Any) -> _Grant:
        captured["root"] = root
        captured.update(kwargs)
        return grant

    monkeypatch.setattr(effects, "acquire_effect_lease", acquire)
    return captured


def test_source_revision_is_truncated_sha256_of_executing_desktop_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = Path(effects.__file__).resolve().parents[2]
    root = package.parent
    paths = (
        package / "atomic.py",
        package / "budget.py",
        package / "desktop_runtime.py",
        package / "interfaces" / "desktop" / "configuration.py",
        package / "interfaces" / "desktop" / "effects.py",
        package / "interfaces" / "desktop" / "http.py",
        package / "interfaces" / "desktop" / "projection.py",
        package / "interfaces" / "desktop" / "settings.py",
        package / "interfaces" / "http" / "effects.py",
        package / "kernel" / "offload_lease.py",
        package / "kernel" / "policy" / "ledger.py",
        package / "kernel" / "policy" / "limits.py",
        package / "limit_policy.py",
        package / "providers" / "ollama.py",
        package / "sensitivity.py",
        package / "spine" / "effect_boundary.py",
        package / "spine" / "envelope.py",
        package / "spine" / "killswitch.py",
    )
    expected = hashlib.sha256()
    for path in paths:
        label = path.relative_to(root).as_posix().encode("utf-8")
        data = path.read_bytes()
        expected.update(len(label).to_bytes(8, "big"))
        expected.update(label)
        expected.update(len(data).to_bytes(8, "big"))
        expected.update(data)

    baseline = effects._source_revision()
    assert baseline == expected.hexdigest()[:40]
    assert re.fullmatch(r"[0-9a-f]{40}", baseline)

    real_read = Path.read_bytes
    changed_path = Path(effects.__file__).resolve()

    def dirty_read(path: Path) -> bytes:
        data = real_read(path)
        return data + b"\n# dirty-byte" if path.resolve() == changed_path else data

    monkeypatch.setattr(Path, "read_bytes", dirty_read)
    assert effects._source_revision() == baseline
    changed = effects._compute_source_revision()
    assert changed != baseline
    assert re.fullmatch(r"[0-9a-f]{40}", changed)


def test_switch_probe_boundary_starts_before_first_control_root_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from daedalus import budget
    from daedalus.spine import effect_boundary

    owner = _manager(tmp_path)._effect_owner
    events: list[str] = []
    running = SimpleNamespace(running=True, reason="armed")

    class Switch:
        def read_state(self) -> object:
            events.append("read_state")
            return running

    owner._switch = Switch()
    decision = SimpleNamespace(contract="budget.process_guard")

    def process_guard() -> object:
        events.append("process_guard")
        return decision

    def begin_effect(
        entrypoint_id: str,
        requested_effects: object,
        decisions: object,
    ) -> object:
        events.append("begin_effect")
        assert entrypoint_id == effects.SWITCH_ENTRYPOINT_ID
        assert tuple(requested_effects) == effect_boundary.REGISTRY_BY_ID[
            effects.SWITCH_ENTRYPOINT_ID
        ].effects
        assert tuple(decisions) == (decision,)
        return object()

    monkeypatch.setattr(budget, "process_guard_boundary_decision", process_guard)
    monkeypatch.setattr(effect_boundary, "begin_effect", begin_effect)

    assert owner._ensure_switch() is owner._switch
    assert events == ["process_guard", "begin_effect", "read_state"]


def test_switch_boundary_refusal_prevents_control_root_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from daedalus import budget
    from daedalus.spine import effect_boundary

    owner = _manager(tmp_path)._effect_owner
    events: list[str] = []

    class Switch:
        def read_state(self) -> object:
            events.append("read_state")
            return SimpleNamespace(running=True, reason="armed")

    owner._switch = Switch()

    def process_guard() -> object:
        events.append("process_guard")
        return SimpleNamespace(contract="budget.process_guard")

    def refuse(*_args: object, **_kwargs: object) -> object:
        events.append("begin_effect")
        raise effect_boundary.EffectStartRefused("synthetic switch denial")

    monkeypatch.setattr(budget, "process_guard_boundary_decision", process_guard)
    monkeypatch.setattr(effect_boundary, "begin_effect", refuse)

    with pytest.raises(
        effects.DesktopEffectUnavailable,
        match="synthetic switch denial",
    ):
        owner._ensure_switch()

    assert events == ["process_guard", "begin_effect"]
    assert ".arm(" not in inspect.getsource(effects.DesktopEffectOwner._ensure_switch)


def test_begin_authorized_accepts_only_exact_noncontainment_note(
    tmp_path: Path,
) -> None:
    owner = _manager(tmp_path)._effect_owner
    note = (
        "disjointness: python.desktop_settings_persist declares no containment "
        "contract, so this grant retains no primary-checkout disjointness record"
    )
    allowed = _Grant(evidence_errors=[note])
    execution, started = owner._begin_authorized(
        allowed,
        ("config/connections.json",),
        (),
        "f" * 64,
    )
    assert execution is allowed.execution
    assert started.execute is True

    refused = _Grant(evidence_errors=[note, "subject retention failed"])
    with pytest.raises(
        effects.DesktopEffectUnavailable,
        match="subject retention failed",
    ):
        owner._begin_authorized(
            refused,
            ("config/connections.json",),
            (),
            "f" * 64,
        )
    assert refused.authorization.begin_calls == []


@pytest.mark.parametrize(
    "missing_key",
    ["lease_subject", "lease_execution:execution-1"],
)
def test_begin_authorized_requires_subject_and_execution_evidence_before_started(
    tmp_path: Path,
    missing_key: str,
) -> None:
    owner = _manager(tmp_path)._effect_owner
    grant = _Grant()
    del grant.evidence_records[missing_key]

    with pytest.raises(
        effects.DesktopEffectUnavailable,
        match=f"missing retained records: {re.escape(missing_key)}",
    ):
        owner._begin_authorized(
            grant,
            ("config/connections.json",),
            (),
            "f" * 64,
        )

    assert grant.authorization.begin_calls == []


def test_settings_temp_name_is_pid_nonce_bound_and_repo_relative(
    tmp_path: Path,
) -> None:
    owner = _manager(tmp_path)._effect_owner
    first = owner._settings_paths("1" * 32)
    second = owner._settings_paths("2" * 32)
    assert first == (
        "config",
        "config/connections.json",
        f"config/.connections.json.{os.getpid()}.{'1' * 32}.tmp",
    )
    assert second[-1] != first[-1]
    assert all(not Path(path).is_absolute() for path in (*first, *second))


def test_invalid_settings_are_rejected_before_nonce_switch_or_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    owner = manager._effect_owner
    effects_started: list[str] = []
    monkeypatch.setattr(
        effects.uuid,
        "uuid4",
        lambda: effects_started.append("nonce") or SimpleNamespace(hex="1" * 32),
    )
    monkeypatch.setattr(
        owner,
        "_ensure_switch",
        lambda: effects_started.append("switch"),
    )
    monkeypatch.setattr(
        effects,
        "acquire_effect_lease",
        lambda *args, **kwargs: effects_started.append("lease"),
    )

    with pytest.raises(effects.DesktopValidationError, match="must be a boolean"):
        owner.save_settings({"bridge": {"auto_start": "yes"}})

    assert effects_started == []


def test_invalid_ollama_config_is_rejected_before_nonce_switch_or_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    owner = manager._effect_owner
    manager.config["ollama"]["local_host"] = "https://example.invalid:11434"
    effects_started: list[str] = []
    monkeypatch.setattr(
        effects.uuid,
        "uuid4",
        lambda: effects_started.append("nonce") or SimpleNamespace(hex="1" * 32),
    )
    monkeypatch.setattr(
        owner,
        "_ensure_switch",
        lambda: effects_started.append("switch"),
    )
    monkeypatch.setattr(
        effects,
        "acquire_effect_lease",
        lambda *args, **kwargs: effects_started.append("lease"),
    )

    with pytest.raises(effects.DesktopValidationError, match="configuration is invalid"):
        owner.start_ollama()

    assert effects_started == []


def test_preplanted_hardlink_temp_is_refused_without_touching_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    owner = manager._effect_owner
    nonce = "3" * 32
    temp = (
        tmp_path
        / "config"
        / f".connections.json.{os.getpid()}.{nonce}.tmp"
    )
    temp.parent.mkdir()
    victim = tmp_path / "outside-victim.txt"
    victim.write_text("keep-me", encoding="utf-8")
    try:
        os.link(victim, temp)
    except OSError as exc:
        pytest.skip(f"hard links unavailable on this filesystem: {exc}")

    grant = _Grant()
    _install_fake_lease(monkeypatch, owner, grant, nonce=nonce)
    before = json.loads(json.dumps(manager.config))
    proposed = json.loads(json.dumps(before))
    proposed["ollama"]["model"] = "must-not-commit"

    with pytest.raises(effects.DesktopEffectUnavailable) as refused:
        owner.save_settings(proposed)

    assert refused.value.committed is False
    assert victim.read_text(encoding="utf-8") == "keep-me"
    assert not manager.config_path.exists()
    assert manager.config == before
    assert grant.authorization.outcomes == ["FAILED"]


def test_terminal_completion_failure_does_not_rewrite_committed_settings_as_failed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    owner = manager._effect_owner
    grant = _Grant(fail_completed=True)
    _install_fake_lease(monkeypatch, owner, grant)
    monkeypatch.setattr(
        owner,
        "_apply_environment_from",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        owner,
        "_detached_snapshot",
        lambda: {"config": json.loads(json.dumps(manager.config))},
    )
    proposed = json.loads(json.dumps(manager.config))
    proposed["ollama"]["model"] = "committed-model"

    with pytest.raises(effects.DesktopSettingsCommittedUnrecorded) as failed:
        owner.save_settings(proposed)

    assert failed.value.status_code == 503
    assert failed.value.error_code == (
        "desktop_settings_committed_receipt_unavailable"
    )
    assert failed.value.committed is True
    assert grant.authorization.outcomes == []
    assert grant.retained == []
    persisted = json.loads(manager.config_path.read_text(encoding="utf-8"))
    assert persisted["ollama"]["model"] == "committed-model"
    assert manager.config == persisted


@pytest.mark.parametrize(
    ("retain_value", "retain_error"),
    [
        (None, ""),
        ("c" * 64, ""),
        ({"record_sha256": "not-a-record-digest"}, ""),
        (
            {"record_sha256": "c" * 64},
            "terminal evidence store refused the record",
        ),
    ],
    ids=("none", "bare-digest", "malformed-digest", "new-evidence-error"),
)
def test_completed_settings_surface_terminal_retention_failure_without_failed_rewrite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    retain_value: Any,
    retain_error: str,
) -> None:
    manager = _manager(tmp_path)
    owner = manager._effect_owner
    grant = _Grant(retain_value=retain_value, retain_error=retain_error)
    _install_fake_lease(monkeypatch, owner, grant)
    monkeypatch.setattr(
        owner,
        "_apply_environment_from",
        lambda *args, **kwargs: None,
    )
    proposed = json.loads(json.dumps(manager.config))
    proposed["ollama"]["model"] = "retention-fault-model"

    with pytest.raises(effects.DesktopSettingsCommittedUnrecorded) as failed:
        owner.save_settings(proposed)

    assert failed.value.committed is True
    assert failed.value.status_code == 503
    assert grant.authorization.outcomes == ["COMPLETED"]
    assert grant.retained == [grant.execution]
    assert "terminal effect evidence was not retained" in str(failed.value)
    if retain_error:
        assert retain_error in str(failed.value)
    persisted = json.loads(manager.config_path.read_text(encoding="utf-8"))
    assert persisted["ollama"]["model"] == "retention-fault-model"
    assert manager.config == persisted


class _StoppingSwitch:
    def __init__(self, stop_at: int) -> None:
        self.stop_at = stop_at
        self.calls = 0

    def checkpoint(self) -> None:
        self.calls += 1
        if self.calls == self.stop_at:
            raise effects.LoopHalted(f"synthetic stop at checkpoint {self.calls}")


@pytest.mark.parametrize("stop_at", [3, 4], ids=("before-write", "before-replace"))
def test_settings_kill_checkpoints_leave_no_target_or_scratch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stop_at: int,
) -> None:
    manager = _manager(tmp_path)
    owner = manager._effect_owner
    switch = _StoppingSwitch(stop_at)
    grant = _Grant()
    nonce = "4" * 32
    _install_fake_lease(
        monkeypatch,
        owner,
        grant,
        nonce=nonce,
        switch=switch,
    )
    before = json.loads(json.dumps(manager.config))
    proposed = json.loads(json.dumps(before))
    proposed["ollama"]["model"] = "must-not-publish"

    with pytest.raises(effects.DesktopEffectStopped) as stopped:
        owner.save_settings(proposed)

    assert stopped.value.committed is False
    assert switch.calls == stop_at
    assert grant.authorization.outcomes == ["FAILED"]
    assert grant.retained == [grant.execution]
    assert manager.config == before
    assert not manager.config_path.exists()
    config_dir = tmp_path / "config"
    assert not list(config_dir.glob(".connections.json.*.tmp"))


@pytest.mark.parametrize(
    ("retain_value", "retain_error"),
    [
        (None, ""),
        ("c" * 64, ""),
        ({"record_sha256": "not-a-record-digest"}, ""),
        (
            {"record_sha256": "c" * 64},
            "FAILED evidence record was not stored",
        ),
    ],
    ids=("none", "bare-digest", "malformed-digest", "new-evidence-error"),
)
def test_failed_settings_surface_terminal_retention_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    retain_value: Any,
    retain_error: str,
) -> None:
    manager = _manager(tmp_path)
    owner = manager._effect_owner
    switch = _StoppingSwitch(3)
    grant = _Grant(retain_value=retain_value, retain_error=retain_error)
    _install_fake_lease(monkeypatch, owner, grant, switch=switch)

    with pytest.raises(effects.DesktopEffectUnavailable) as failed:
        owner.save_settings(manager.config)

    assert failed.value.committed is False
    assert grant.authorization.outcomes == ["FAILED"]
    assert grant.retained == [grant.execution]
    assert "FAILED terminal effect evidence was not retained" in str(failed.value)
    if retain_error:
        assert retain_error in str(failed.value)
    assert not manager.config_path.exists()


def test_post_replace_identity_failure_is_reported_as_committed_indeterminate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    owner = manager._effect_owner
    grant = _Grant()
    _install_fake_lease(monkeypatch, owner, grant)
    real_check = effects._regular_single_link
    checks = 0

    def fail_published_identity(state: os.stat_result) -> bool:
        nonlocal checks
        checks += 1
        if checks == 2:
            raise OSError("synthetic post-replace identity failure")
        return real_check(state)

    monkeypatch.setattr(effects, "_regular_single_link", fail_published_identity)
    proposed = json.loads(json.dumps(manager.config))
    proposed["ollama"]["model"] = "visible-before-failure"

    with pytest.raises(effects.DesktopSettingsDurabilityIndeterminate) as failed:
        owner.save_settings(proposed)

    assert failed.value.committed is True
    assert failed.value.status_code == 503
    assert grant.authorization.outcomes == ["FAILED"]
    assert grant.retained == [grant.execution]
    persisted = json.loads(manager.config_path.read_text(encoding="utf-8"))
    assert persisted["ollama"]["model"] == "visible-before-failure"
    assert manager.config == persisted


def test_local_ollama_probe_uses_exact_endpoint_without_proxy_or_redirect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    endpoint = "http://127.0.0.1:11436"
    opened: dict[str, object] = {}

    class Response:
        status = 200

        def __init__(self) -> None:
            self._body = b'{"models": []}'

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            assert size != 0
            body, self._body = self._body, b""
            return body

    class Opener:
        def open(self, url: str, *, timeout: float) -> Response:
            opened["url"] = url
            opened["timeout"] = timeout
            return Response()

    def build_opener(*handlers: object) -> Opener:
        opened["handlers"] = handlers
        return Opener()

    monkeypatch.setenv("OLLAMA_HOST", "http://198.51.100.7:11434")
    monkeypatch.setattr(
        desktop_runtime.urllib.request,
        "build_opener",
        build_opener,
    )
    ok, detail = manager._probe(
        timeout=0.25,
        endpoint=endpoint,
        switch=SimpleNamespace(checkpoint=lambda: None),
    )

    assert (ok, detail) == (True, "")
    assert opened["url"] == endpoint + "/api/tags"
    observed_timeout = opened["timeout"]
    assert isinstance(observed_timeout, float)
    assert 0 < observed_timeout <= 0.25
    proxy, redirects = opened["handlers"]
    assert isinstance(proxy, desktop_runtime.urllib.request.ProxyHandler)
    assert proxy.proxies == {}
    assert isinstance(redirects, desktop_runtime._RefuseRedirects)


@pytest.mark.parametrize(
    "body",
    [
        b'{"ok": true}',
        b'{"models": {}}',
        b'{"models": [{}]}',
        b'{"models": [], "extra": true}',
        b'{"models": [], "models": []}',
        b'{"models": [{"name": "model", "size": NaN}]}',
    ],
)
def test_local_ollama_probe_rejects_non_ollama_json_shapes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: bytes,
) -> None:
    manager = _manager(tmp_path)
    checkpoints: list[str] = []

    class Response:
        status = 200

        def __init__(self) -> None:
            self.body = body

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            chunk, self.body = self.body[:size], self.body[size:]
            return chunk

    class Opener:
        def open(self, url: str, *, timeout: float) -> Response:
            assert url.endswith("/api/tags")
            assert timeout > 0
            return Response()

    monkeypatch.setattr(
        desktop_runtime.urllib.request,
        "build_opener",
        lambda *handlers: Opener(),
    )
    switch = SimpleNamespace(checkpoint=lambda: checkpoints.append("checkpoint"))

    ok, detail = manager._probe(timeout=0.25, switch=switch)

    assert ok is False
    assert detail
    assert len(checkpoints) >= 2


@pytest.mark.parametrize("stop_at", [1, 2], ids=("before-open", "before-read"))
def test_local_ollama_probe_checks_operator_switch_before_network_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stop_at: int,
) -> None:
    manager = _manager(tmp_path)
    switch = _StoppingSwitch(stop_at)
    activity: list[str] = []

    class Response:
        status = 200

        def __enter__(self) -> "Response":
            activity.append("entered")
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            activity.append("read")
            return b'{"models": []}'

    class Opener:
        def open(self, url: str, *, timeout: float) -> Response:
            activity.append("open")
            return Response()

    monkeypatch.setattr(
        desktop_runtime.urllib.request,
        "build_opener",
        lambda *handlers: Opener(),
    )

    with pytest.raises(effects.LoopHalted):
        manager._probe(timeout=0.25, switch=switch)

    if stop_at == 1:
        assert activity == []
    else:
        assert activity == ["open", "entered"]


@pytest.mark.parametrize("expire_at", [1, 2], ids=("before-open", "before-read"))
def test_local_ollama_probe_deadline_prevents_late_network_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    expire_at: int,
) -> None:
    manager = _manager(tmp_path)
    clock = [0.0]
    checkpoints = 0
    activity: list[str] = []

    def checkpoint() -> None:
        nonlocal checkpoints
        checkpoints += 1
        if checkpoints == expire_at:
            clock[0] = 2.0

    class Response:
        status = 200

        def __enter__(self) -> "Response":
            activity.append("entered")
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self, size: int = -1) -> bytes:
            activity.append("read")
            return b'{"models": []}'

    class Opener:
        def open(self, url: str, *, timeout: float) -> Response:
            activity.append("open")
            return Response()

    monkeypatch.setattr(desktop_runtime.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        desktop_runtime.urllib.request,
        "build_opener",
        lambda *handlers: Opener(),
    )

    ok, detail = manager._probe(
        timeout=1.0,
        switch=SimpleNamespace(checkpoint=checkpoint),
    )

    assert ok is False
    assert "deadline" in detail
    if expire_at == 1:
        assert activity == []
    else:
        assert activity == ["open", "entered"]


def test_explicit_ollama_adoption_leases_and_uses_exact_loopback_endpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    endpoint = "http://127.0.0.1:11436"
    manager.config = desktop_runtime.normalize_config(
        {"ollama": {"local_host": endpoint}}
    )
    owner = manager._effect_owner
    grant = _Grant(entrypoint_id=effects.OLLAMA_ENTRYPOINT_ID)
    captured = _install_fake_lease(monkeypatch, owner, grant)
    adopted: list[tuple[str, object]] = []
    monkeypatch.setattr(
        manager,
        "_adopt_local_ollama_owned",
        lambda exact, *, switch: adopted.append((exact, switch))
        or {"mode": "local", "reachable": True},
    )

    result = owner.start_ollama()

    assert result == {"mode": "local", "reachable": True}
    assert adopted == [(endpoint, captured["switch"])]
    assert captured["entrypoint_id"] == effects.OLLAMA_ENTRYPOINT_ID
    assert captured["writable_paths"] == ()
    assert captured["tools"] == ()
    assert len(captured["lanes"]) == 1
    admission = captured["egress_admission"](captured["lanes"])
    assert admission.endpoints == (endpoint,)
    assert admission.decision.allowed is True
    assert grant.authorization.outcomes == ["COMPLETED"]


def test_ollama_adoption_without_terminal_evidence_returns_typed_503(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    owner = manager._effect_owner
    grant = _Grant(
        entrypoint_id=effects.OLLAMA_ENTRYPOINT_ID,
        retain_value=None,
    )
    _install_fake_lease(monkeypatch, owner, grant)
    monkeypatch.setattr(
        manager,
        "_adopt_local_ollama_owned",
        lambda endpoint, *, switch: {
            "mode": "local",
            "reachable": True,
        },
    )

    with pytest.raises(effects.DesktopEffectUnavailable) as failed:
        owner.start_ollama()

    assert failed.value.status_code == 503
    assert failed.value.committed is False
    assert "terminal effect evidence was not retained" in str(failed.value)
    assert "no child was started" in str(failed.value)
    assert grant.authorization.outcomes == ["COMPLETED"]
    assert grant.retained == [grant.execution]


def _projection_budget() -> dict[str, Any]:
    return {
        "available": False,
        "mode": "bounded",
        "configured_caps": {},
        "effective_caps": {},
        "limit_policy_fingerprint_sha256": "0" * 64,
        "last_error": "",
    }


def test_malformed_heartbeat_projects_invalid_state_instead_of_crashing_get(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    monkeypatch.setattr(manager, "_budget_status", lambda **kwargs: _projection_budget())
    malformed_bridge = SimpleNamespace(
        heartbeat_status=lambda: {
            "state": "alive",
            "non_json_detail": object(),
        }
    )

    snapshot = projection.snapshot(
        manager,
        file_bridge=malformed_bridge,
        environ={},
        tunnel_target_var="unused",
    )

    bridge = snapshot["services"]["bridge"]
    assert bridge["state"] == "invalid"
    assert "heartbeat state is malformed" in bridge["detail"]
    assert bridge["managed"] is False


def test_snapshot_reads_and_routes_exactly_one_detached_config_generation(
    tmp_path: Path,
) -> None:
    first = desktop_runtime.normalize_config(
        {"ollama": {"model": "first-generation"}}
    )
    second = desktop_runtime.normalize_config(
        {
            "ollama": {
                "model": "second-generation",
                "local_host": "http://127.0.0.1:11436",
            }
        }
    )

    class Manager:
        def __init__(self) -> None:
            self._lock = threading.RLock()
            self._reads = 0
            self.seen_generations: list[int] = []
            self.config_path = tmp_path / "config" / "connections.json"
            self._config_error = ""
            self._budget_policy_error = ""
            self._bridge_start_error = ""
            self._ollama_observation = {
                "observed": False,
                "endpoint": first["ollama"]["local_host"],
                "observed_at": None,
                "reachable": False,
                "last_error": "not probed",
            }

        @property
        def config(self) -> dict[str, Any]:
            self._reads += 1
            return first if self._reads == 1 else second

        def _budget_status(self, *, config: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
            self.seen_generations.append(id(config))
            return _projection_budget()

        def _ide_status(
            self,
            project: Any = None,
            *,
            config: dict[str, Any],
        ) -> dict[str, Any]:
            del project
            self.seen_generations.append(id(config))
            return {"generation_model": config["ollama"]["model"]}

    manager = Manager()
    snapshot = projection.snapshot(
        manager,
        file_bridge=SimpleNamespace(
            heartbeat_status=lambda: {"state": "none", "detail": "not running"}
        ),
        environ={},
        tunnel_target_var="unused",
    )

    assert manager._reads == 1
    assert len(set(manager.seen_generations)) == 1
    assert snapshot["config"]["ollama"]["model"] == "first-generation"
    assert snapshot["services"]["ollama"]["endpoint"] == first["ollama"][
        "local_host"
    ]
    assert snapshot["services"]["ide"]["generation_model"] == "first-generation"


@pytest.mark.parametrize(
    ("error_type", "status", "code", "committed"),
    [
        (effects.DesktopEffectRefused, 400, "desktop_effect_refused", False),
        (effects.DesktopValidationError, 400, "desktop_validation_error", False),
        (effects.DesktopPolicyDenied, 403, "desktop_policy_denied", False),
        (
            effects.DesktopFeatureUnavailable,
            409,
            "desktop_feature_unavailable",
            False,
        ),
        (effects.DesktopEffectStopped, 423, "desktop_operator_stop", False),
        (
            effects.DesktopEffectUnavailable,
            503,
            "desktop_effect_authorization_unavailable",
            False,
        ),
        (
            effects.DesktopOllamaUnreachable,
            503,
            "desktop_ollama_unreachable",
            False,
        ),
        (
            effects.DesktopSettingsDurabilityIndeterminate,
            503,
            "desktop_settings_durability_indeterminate",
            True,
        ),
        (
            effects.DesktopSettingsCommittedUnrecorded,
            503,
            "desktop_settings_committed_receipt_unavailable",
            True,
        ),
        (
            effects.DesktopSettingsCommittedFollowupError,
            503,
            "desktop_settings_committed_followup_failed",
            True,
        ),
    ],
)
def test_effect_errors_preserve_http_contract(
    error_type: type[effects.DesktopEffectRefused],
    status: int,
    code: str,
    committed: bool,
) -> None:
    error = error_type("synthetic")
    assert error.status_code == status
    assert error.error_code == code
    assert error.committed is committed
    assert desktop_http._error_payload(error) == {
        "ok": False,
        "error": "synthetic",
        "error_code": code,
        "committed": committed,
    }


@pytest.mark.skipif(os.name != "nt", reason="MoveFileExW is Windows-only")
def test_windows_write_through_move_replaces_exact_existing_file(
    tmp_path: Path,
) -> None:
    source = tmp_path / "settings.tmp"
    target = tmp_path / "settings.json"
    source.write_bytes(b"new-settings")
    target.write_bytes(b"old-settings")

    effects._move_file_ex_windows_write_through(source, target)

    assert not source.exists()
    assert target.read_bytes() == b"new-settings"


@pytest.mark.skipif(os.name != "nt", reason="Windows publisher contract")
def test_windows_settings_completion_uses_write_through_when_directory_flush_is_unsupported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    owner = manager._effect_owner
    grant = _Grant()
    _install_fake_lease(monkeypatch, owner, grant)
    moves: list[tuple[Path, Path]] = []
    native_move = effects._move_file_ex_windows_write_through

    def observed_move(source: Path, target: Path) -> None:
        moves.append((source, target))
        native_move(source, target)

    monkeypatch.setattr(effects, "_move_file_ex_windows_write_through", observed_move)
    monkeypatch.setattr(effects, "_flush_windows_directory", lambda handle: False)
    monkeypatch.setattr(
        effects.os,
        "replace",
        lambda *args, **kwargs: pytest.fail(
            "Windows settings must not fall back to non-write-through os.replace"
        ),
    )
    monkeypatch.setattr(owner, "_apply_environment_from", lambda *args, **kwargs: None)
    proposed = json.loads(json.dumps(manager.config))
    proposed["ollama"]["model"] = "write-through-model"

    result = owner.save_settings(proposed)

    assert result["config"]["ollama"]["model"] == "write-through-model"
    assert len(moves) == 1
    assert moves[0][1] == manager.config_path
    assert grant.authorization.outcomes == ["COMPLETED"]


@pytest.mark.skipif(os.name != "nt", reason="Windows publisher contract")
def test_unexpected_windows_directory_flush_failure_is_committed_indeterminate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    owner = manager._effect_owner
    grant = _Grant()
    _install_fake_lease(monkeypatch, owner, grant)
    monkeypatch.setattr(
        effects,
        "_flush_windows_directory",
        lambda handle: (_ for _ in ()).throw(OSError("synthetic flush failure")),
    )
    proposed = json.loads(json.dumps(manager.config))
    proposed["ollama"]["model"] = "visible-write-through-model"

    with pytest.raises(effects.DesktopSettingsDurabilityIndeterminate) as failed:
        owner.save_settings(proposed)

    assert failed.value.committed is True
    assert grant.authorization.outcomes == ["FAILED"]
    persisted = json.loads(manager.config_path.read_text(encoding="utf-8"))
    assert persisted["ollama"]["model"] == "visible-write-through-model"
    assert manager.config == persisted


@pytest.mark.skipif(os.name != "nt", reason="Windows publisher contract")
def test_windows_move_that_publishes_then_raises_is_reconciled_as_committed_unknown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    owner = manager._effect_owner
    grant = _Grant()
    _install_fake_lease(monkeypatch, owner, grant)
    native_move = effects._move_file_ex_windows_write_through

    def move_then_raise(source: Path, target: Path) -> None:
        native_move(source, target)
        raise OSError("synthetic wrapper failure after native move")

    monkeypatch.setattr(
        effects,
        "_move_file_ex_windows_write_through",
        move_then_raise,
    )
    proposed = json.loads(json.dumps(manager.config))
    proposed["ollama"]["model"] = "moved-before-error"

    with pytest.raises(effects.DesktopSettingsDurabilityIndeterminate) as failed:
        owner.save_settings(proposed)

    assert failed.value.committed is True
    assert grant.authorization.outcomes == ["FAILED"]
    persisted = json.loads(manager.config_path.read_text(encoding="utf-8"))
    assert persisted["ollama"]["model"] == "moved-before-error"
    assert manager.config == persisted
    assert not list((tmp_path / "config").glob(".connections.json.*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Windows publisher contract")
def test_windows_move_failure_before_publication_remains_uncommitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    owner = manager._effect_owner
    grant = _Grant()
    _install_fake_lease(monkeypatch, owner, grant)
    before = json.loads(json.dumps(manager.config))
    monkeypatch.setattr(effects, "REPLACE_RETRY_S", 0.0)
    monkeypatch.setattr(
        effects,
        "_move_file_ex_windows_write_through",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            OSError("synthetic failure before native move")
        ),
    )
    proposed = json.loads(json.dumps(before))
    proposed["ollama"]["model"] = "must-not-publish"

    with pytest.raises(effects.DesktopEffectUnavailable) as failed:
        owner.save_settings(proposed)

    assert failed.value.committed is False
    assert grant.authorization.outcomes == ["FAILED"]
    assert manager.config == before
    assert not manager.config_path.exists()
    assert not list((tmp_path / "config").glob(".connections.json.*.tmp"))


@pytest.mark.skipif(os.name != "nt", reason="Windows publisher contract")
def test_windows_uninspectable_move_outcome_is_commit_unknown_without_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(tmp_path)
    owner = manager._effect_owner
    grant = _Grant()
    nonce = "f" * 32
    _install_fake_lease(monkeypatch, owner, grant, nonce=nonce)
    target = manager.config_path
    temp = (
        tmp_path
        / "config"
        / f".connections.json.{os.getpid()}.{nonce}.tmp"
    )
    move_failed = False
    real_lstat = effects.os.lstat

    def fail_before_move(source: Path, destination: Path) -> None:
        nonlocal move_failed
        move_failed = True
        raise OSError("synthetic move result transport failure")

    def hide_publish_identities(path: str | os.PathLike[str]):
        candidate = Path(path)
        if move_failed and candidate in {temp, target}:
            raise OSError("synthetic identity inspection failure")
        return real_lstat(path)

    monkeypatch.setattr(
        effects,
        "_move_file_ex_windows_write_through",
        fail_before_move,
    )
    monkeypatch.setattr(effects.os, "lstat", hide_publish_identities)
    proposed = json.loads(json.dumps(manager.config))
    proposed["ollama"]["model"] = "outcome-unknown"

    with pytest.raises(effects.DesktopSettingsDurabilityIndeterminate) as failed:
        owner.save_settings(proposed)

    assert failed.value.committed is True
    assert "outcome could not be determined" in str(failed.value)
    assert grant.authorization.outcomes == ["FAILED"]
    assert real_lstat(temp).st_nlink == 1
    assert not target.exists()


def test_ariadne_campaign_live_is_derived_from_the_wired_mutation_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The capability flag follows the HTTP route table, not a literal.

    G1-ARIADNE-02 matrix item 7: the packaged projection advertises
    ``ariadne_campaign_live`` only while the production route is wired. A
    literal ``True`` (measured 2026-09-05) would keep advertising a route
    that no longer exists; deriving it from the same table the preflight and
    dispatch consult turns it off with the route.
    """
    from daedalus.interfaces.http import effects as http_effects

    manager = _manager(tmp_path)
    monkeypatch.setattr(manager, "_budget_status", lambda **kwargs: _projection_budget())
    bridge = SimpleNamespace(heartbeat_status=lambda: {"state": "stopped"})

    assert http_effects.mutation_route_wired("/api/ariadne") is True
    wired = projection.snapshot(
        manager, file_bridge=bridge, environ={}, tunnel_target_var="unused"
    )
    assert wired["caps"]["ariadne_campaign_live"] is True

    monkeypatch.setattr(
        http_effects,
        "_PREFLIGHT_POST_PATHS",
        frozenset(http_effects._PREFLIGHT_POST_PATHS - {"/api/ariadne"}),
    )
    assert http_effects.mutation_route_wired("/api/ariadne") is False
    unwired = projection.snapshot(
        manager, file_bridge=bridge, environ={}, tunnel_target_var="unused"
    )
    assert unwired["caps"]["ariadne_campaign_live"] is False
