from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

import daedalus.kairos as kairos
import daedalus.kairos.promotion_entrypoint as entrypoint


def _values() -> dict[str, object]:
    return {
        "repo_root": "/repo",
        "candidates": [SimpleNamespace(name="candidate")],
        "project": "project",
        "availability": {"git": True},
        "consumed_approval": SimpleNamespace(name="consumed"),
        "evidence_packet": SimpleNamespace(name="evidence"),
        "target_ref": "refs/heads/experimental",
        "promotion_effect_capability": SimpleNamespace(name="effect-capability"),
        "approval_ledger": SimpleNamespace(name="approval-ledger"),
        "owner_keyring": {("owner", "key"): b"secret"},
        "promotion_execution_ledger": SimpleNamespace(name="execution-ledger"),
        "ledger_path": "/ledger.sqlite3",
        "lock_timeout_s": 11.0,
        "gate_timeout_s": 22.0,
        "cancel": SimpleNamespace(name="cancel"),
    }


def test_public_entrypoint_delegates_once_with_exact_subject(monkeypatch) -> None:
    values = _values()
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    retained = {"promoted": [], "marker": "retained"}

    def delegate(*args, **kwargs):
        calls.append((args, kwargs))
        return retained

    monkeypatch.setattr(
        entrypoint,
        "promote_candidates_with_effect_lifecycle",
        delegate,
    )

    result = entrypoint.promote_candidates(**values)

    assert result is retained
    assert calls == [
        (
            (values["repo_root"], values["candidates"]),
            {
                key: value
                for key, value in values.items()
                if key not in {"repo_root", "candidates"}
            },
        )
    ]


def test_public_entrypoint_does_not_swallow_lifecycle_refusal(monkeypatch) -> None:
    expected = RuntimeError("stale revision")

    def delegate(*_args, **_kwargs):
        raise expected

    monkeypatch.setattr(
        entrypoint,
        "promote_candidates_with_effect_lifecycle",
        delegate,
    )

    with pytest.raises(RuntimeError) as observed:
        entrypoint.promote_candidates(**_values())

    assert observed.value is expected


def test_package_export_is_the_capability_bearing_surface() -> None:
    assert kairos.promote_candidates_with_persisted_effect is entrypoint.promote_candidates
    signature = inspect.signature(entrypoint.promote_candidates)
    assert "promotion_effect_capability" in signature.parameters
    assert signature.parameters["promotion_effect_capability"].kind is inspect.Parameter.KEYWORD_ONLY
    assert all(
        parameter.kind is not inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
