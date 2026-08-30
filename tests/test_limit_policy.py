from __future__ import annotations

import dataclasses
import re

import pytest

from daedalus.limit_policy import (
    ENV_EXECUTION_LIMIT_POLICY,
    LIMIT_AXES,
    LIMIT_MODES,
    MODE_BOUNDED,
    MODE_CUSTOM,
    MODE_UNBOUNDED_EXECUTION,
    ExecutionLimitPolicy,
    LimitAxes,
    LimitPolicyError,
    load_from_env,
    store_in_env,
)


def _axes(**changes: bool) -> LimitAxes:
    values = {axis: True for axis in LIMIT_AXES}
    values.update(changes)
    return LimitAxes(**values)


def test_public_vocabulary_is_exact_and_ordered() -> None:
    assert LIMIT_MODES == (
        "bounded",
        "custom",
        "unbounded_execution",
    )
    assert LIMIT_AXES == (
        "period_usd",
        "billable_calls",
        "mission_spend",
        "tokens",
        "wall_time",
        "attempts",
        "concurrency",
        "work_scope",
    )
    assert ENV_EXECUTION_LIMIT_POLICY == "DAEDALUS_EXECUTION_LIMIT_POLICY"


def test_default_is_bounded_with_every_axis_enforced() -> None:
    policy = ExecutionLimitPolicy()

    assert policy.mode == MODE_BOUNDED
    assert policy.configured.as_dict() == {axis: True for axis in LIMIT_AXES}
    assert policy.effective.as_dict() == {axis: True for axis in LIMIT_AXES}
    assert all(policy.enforces(axis) for axis in LIMIT_AXES)


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        (MODE_BOUNDED, {axis: True for axis in LIMIT_AXES}),
        (
            MODE_CUSTOM,
            {
                "period_usd": False,
                "billable_calls": True,
                "mission_spend": False,
                "tokens": True,
                "wall_time": False,
                "attempts": True,
                "concurrency": False,
                "work_scope": True,
            },
        ),
        (MODE_UNBOUNDED_EXECUTION, {axis: False for axis in LIMIT_AXES}),
    ],
)
def test_mode_derives_effective_axes_without_rewriting_configured(
    mode: str,
    expected: dict[str, bool],
) -> None:
    configured = LimitAxes(
        period_usd=False,
        billable_calls=True,
        mission_spend=False,
        tokens=True,
        wall_time=False,
        attempts=True,
        concurrency=False,
        work_scope=True,
    )

    policy = ExecutionLimitPolicy(mode=mode, configured=configured)

    assert policy.configured is configured
    assert policy.configured.as_dict()["period_usd"] is False
    assert policy.effective.as_dict() == expected


def test_custom_enforces_each_axis_independently() -> None:
    for disabled in LIMIT_AXES:
        configured = _axes(**{disabled: False})
        policy = ExecutionLimitPolicy(mode=MODE_CUSTOM, configured=configured)

        assert policy.enforces(disabled) is False
        assert all(
            policy.enforces(axis) for axis in LIMIT_AXES if axis != disabled
        )


@pytest.mark.parametrize("axis", ["", "spend", "period_USD", None, 1, True])
def test_enforces_rejects_noncanonical_axes(axis: object) -> None:
    with pytest.raises(LimitPolicyError, match="unknown execution limit axis"):
        ExecutionLimitPolicy().enforces(axis)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [0, 1, "true", "false", None, [], {}])
def test_limit_axes_constructor_rejects_non_booleans(bad: object) -> None:
    values: dict[str, object] = {axis: True for axis in LIMIT_AXES}
    values["tokens"] = bad

    with pytest.raises(LimitPolicyError, match="tokens.*boolean"):
        LimitAxes(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [0, 1, "true", None])
def test_uniform_axes_rejects_non_booleans(bad: object) -> None:
    with pytest.raises(LimitPolicyError, match="must be a boolean"):
        LimitAxes.uniform(bad)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [None, [], "axes", True, 1])
def test_axes_from_dict_requires_an_object(bad: object) -> None:
    with pytest.raises(LimitPolicyError, match="must be an object"):
        LimitAxes.from_dict(bad)


def test_axes_from_dict_requires_every_axis_and_no_unknown_axis() -> None:
    missing = {axis: True for axis in LIMIT_AXES if axis != "tokens"}
    extra = {axis: True for axis in LIMIT_AXES}
    extra["provider_quota"] = True

    with pytest.raises(LimitPolicyError, match="missing keys: tokens"):
        LimitAxes.from_dict(missing)
    with pytest.raises(LimitPolicyError, match="provider_quota"):
        LimitAxes.from_dict(extra)


def test_axes_from_dict_reports_non_string_unknown_keys_as_policy_errors() -> None:
    malformed: dict[object, object] = {axis: True for axis in LIMIT_AXES}
    malformed[1] = True
    malformed["extra"] = True

    with pytest.raises(LimitPolicyError, match="unknown keys"):
        LimitAxes.from_dict(malformed)


@pytest.mark.parametrize(
    "mode",
    ["", "unbounded", "bounded ", "CUSTOM", None, 0, True],
)
def test_policy_rejects_unknown_or_non_text_modes(mode: object) -> None:
    with pytest.raises(LimitPolicyError, match="mode must be one of"):
        ExecutionLimitPolicy(mode=mode)  # type: ignore[arg-type]


@pytest.mark.parametrize("configured", [None, {}, True, "axes"])
def test_policy_constructor_requires_typed_axes(configured: object) -> None:
    with pytest.raises(LimitPolicyError, match="must be LimitAxes"):
        ExecutionLimitPolicy(configured=configured)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", [None, [], "policy", 1, True])
def test_policy_from_dict_requires_an_object(bad: object) -> None:
    with pytest.raises(LimitPolicyError, match="must be an object"):
        ExecutionLimitPolicy.from_dict(bad)


def test_policy_from_dict_requires_exact_top_level_shape() -> None:
    axes = LimitAxes().as_dict()

    with pytest.raises(LimitPolicyError, match="missing keys: configured"):
        ExecutionLimitPolicy.from_dict({"mode": MODE_BOUNDED})
    with pytest.raises(LimitPolicyError, match="unknown keys: 'effective'"):
        ExecutionLimitPolicy.from_dict(
            {"mode": MODE_BOUNDED, "configured": axes, "effective": axes}
        )


def test_as_dict_is_canonical_and_returns_detached_data() -> None:
    policy = ExecutionLimitPolicy(
        mode=MODE_CUSTOM,
        configured=_axes(period_usd=False, attempts=False),
    )

    first = policy.as_dict()
    second = policy.as_dict()

    assert list(first) == ["mode", "configured"]
    assert list(first["configured"]) == list(LIMIT_AXES)
    assert first == second
    assert first is not second
    assert first["configured"] is not second["configured"]

    first["mode"] = MODE_BOUNDED
    first["configured"]["period_usd"] = True
    assert policy.mode == MODE_CUSTOM
    assert policy.configured.period_usd is False


@pytest.mark.parametrize("mode", LIMIT_MODES)
def test_dict_and_environment_roundtrip_for_every_mode(mode: str) -> None:
    policy = ExecutionLimitPolicy(
        mode=mode,
        configured=_axes(
            period_usd=False,
            mission_spend=False,
            attempts=False,
            work_scope=False,
        ),
    )

    assert ExecutionLimitPolicy.from_dict(policy.as_dict()) == policy
    assert ExecutionLimitPolicy.from_env_value(policy.to_env_value()) == policy


def test_environment_encoding_is_compact_deterministic_json() -> None:
    policy = ExecutionLimitPolicy(
        mode=MODE_CUSTOM,
        configured=_axes(period_usd=False),
    )

    encoded = policy.to_env_value()

    assert " " not in encoded
    assert "\n" not in encoded
    assert encoded == policy.to_env_value()
    assert encoded == (
        '{"configured":{"attempts":true,"billable_calls":true,'
        '"concurrency":true,"mission_spend":true,"period_usd":false,'
        '"tokens":true,"wall_time":true,"work_scope":true},"mode":"custom"}'
    )


def test_default_fingerprint_is_stable_and_lowercase_sha256() -> None:
    fingerprint = ExecutionLimitPolicy().fingerprint_sha256

    assert fingerprint == (
        "0701d8651dabacf1bfbb3ef8972ce9fac03855591affbcce25c89ff204c1fa47"
    )
    assert re.fullmatch(r"[0-9a-f]{64}", fingerprint)


def test_fingerprint_is_key_order_independent_but_semantically_sensitive() -> None:
    reversed_axes = {
        axis: axis != "period_usd" for axis in reversed(LIMIT_AXES)
    }
    policy = ExecutionLimitPolicy.from_dict(
        {"configured": reversed_axes, "mode": MODE_CUSTOM}
    )
    same = ExecutionLimitPolicy(
        mode=MODE_CUSTOM,
        configured=_axes(period_usd=False),
    )
    changed_mode = ExecutionLimitPolicy(
        mode=MODE_BOUNDED,
        configured=_axes(period_usd=False),
    )
    changed_axis = ExecutionLimitPolicy(mode=MODE_CUSTOM)

    assert policy.fingerprint_sha256 == same.fingerprint_sha256
    assert policy.fingerprint_sha256 != changed_mode.fingerprint_sha256
    assert policy.fingerprint_sha256 != changed_axis.fingerprint_sha256


@pytest.mark.parametrize("env", [{}, {ENV_EXECUTION_LIMIT_POLICY: ""}, {ENV_EXECUTION_LIMIT_POLICY: "   \t"}])
def test_missing_or_empty_environment_defaults_to_bounded(
    env: dict[str, str],
) -> None:
    assert load_from_env(env) == ExecutionLimitPolicy()


def test_store_and_load_use_only_the_single_named_environment_value() -> None:
    policy = ExecutionLimitPolicy(
        mode=MODE_UNBOUNDED_EXECUTION,
        configured=_axes(tokens=False),
    )
    env = {"UNCHANGED": "yes"}

    encoded = store_in_env(policy, env)

    assert env == {
        "UNCHANGED": "yes",
        ENV_EXECUTION_LIMIT_POLICY: encoded,
    }
    assert load_from_env(env) == policy


@pytest.mark.parametrize(
    "raw",
    [
        "{",
        "[]",
        '"policy"',
        "true",
        "0",
        "NaN",
        "Infinity",
        '{"mode":"bounded"}',
        '{"mode":"bounded","configured":{},"unknown":true}',
        '{"mode":"bounded","mode":"custom","configured":{}}',
        (
            '{"mode":"custom","configured":{'
            '"period_usd":true,"period_usd":false,'
            '"billable_calls":true,"mission_spend":true,"tokens":true,'
            '"wall_time":true,"attempts":true,"concurrency":true,'
            '"work_scope":true}}'
        ),
        (
            '{"mode":"custom","configured":{'
            '"period_usd":0,"billable_calls":true,"mission_spend":true,'
            '"tokens":true,"wall_time":true,"attempts":true,'
            '"concurrency":true,"work_scope":true}}'
        ),
    ],
)
def test_invalid_environment_values_fail_closed(raw: str) -> None:
    with pytest.raises(LimitPolicyError):
        ExecutionLimitPolicy.from_env_value(raw)
    with pytest.raises(LimitPolicyError):
        load_from_env({ENV_EXECUTION_LIMIT_POLICY: raw})


def test_environment_helpers_reject_wrong_runtime_types() -> None:
    with pytest.raises(LimitPolicyError, match="must be text"):
        ExecutionLimitPolicy.from_env_value(1)  # type: ignore[arg-type]
    with pytest.raises(LimitPolicyError, match="must be a mapping"):
        load_from_env([])  # type: ignore[arg-type]
    with pytest.raises(LimitPolicyError, match="must be ExecutionLimitPolicy"):
        store_in_env(LimitAxes(), {})  # type: ignore[arg-type]
    with pytest.raises(LimitPolicyError, match="must be a mutable mapping"):
        store_in_env(ExecutionLimitPolicy(), ())  # type: ignore[arg-type]


def test_policy_and_axes_are_frozen_value_objects() -> None:
    policy = ExecutionLimitPolicy()

    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.mode = MODE_CUSTOM  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.configured.tokens = False  # type: ignore[misc]
