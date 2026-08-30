# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import ast
import importlib.util
import inspect
import sys
from datetime import timedelta
from pathlib import Path

import pytest

import daedalus.kernel.runtime_effects as runtime_effects
from daedalus.kernel.effects import EffectLeaseExpired
from daedalus.kernel.runtime_effects import RuntimeBoundEffectAuthorization

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_PATH = ROOT / "tests" / "kernel" / "test_runtime_effect_admission.py"
RUNTIME_SOURCE = ROOT / "daedalus" / "kernel" / "runtime_effects.py"
BROKER_SOURCE = ROOT / "daedalus" / "runtimes" / "broker.py"


def _fixture():
    name = "daedalus_test_runtime_authorization_clock_fixture"
    spec = importlib.util.spec_from_file_location(name, FIXTURE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


fixture = _fixture()


def test_public_runtime_verification_has_no_caller_clock() -> None:
    parameters = tuple(
        inspect.signature(RuntimeBoundEffectAuthorization.verify).parameters
    )
    assert parameters == ("self",)


def test_expired_capability_cannot_be_backdated_through_public_facade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trust_ledger, _ = fixture.admitted_ledger(tmp_path, monkeypatch)
    req, policy, capability = fixture.issue(
        trust_ledger,
        expires_at=fixture.NOW + timedelta(minutes=5),
    )
    authorization = fixture.authorization(
        tmp_path,
        trust_ledger,
        req,
        policy,
        capability,
    )

    monkeypatch.setattr(
        runtime_effects,
        "_utc_now",
        lambda: fixture.NOW + timedelta(minutes=6),
    )
    with pytest.raises(EffectLeaseExpired, match="expired"):
        authorization.verify()
    with pytest.raises(TypeError, match="unexpected keyword"):
        authorization.verify(now=fixture.NOW + timedelta(seconds=2))  # type: ignore[call-arg]


def test_grant_and_start_use_one_private_verification_seam() -> None:
    source = RUNTIME_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    authorization = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and node.name == "RuntimeBoundEffectAuthorization"
    )
    methods = {
        node.name: ast.get_source_segment(source, node) or ""
        for node in authorization.body
        if isinstance(node, ast.FunctionDef)
    }
    assert "def _verify_at(self, instant: datetime)" in methods["_verify_at"]
    assert "return self._verify_at(_utc_now())" in methods["verify"]
    assert "self._verify_at(instant)" in methods["grant"]
    assert "self._verify_at(pre_start)" in methods["begin_effect"]
    assert "self._verify_at(_utc_now())" in methods["begin_effect"]
    assert "self.verify(now=" not in source


def test_provider_broker_cannot_supply_historical_verification_time() -> None:
    source = BROKER_SOURCE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    provider = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "run_runtime_provider"
    )
    body = ast.get_source_segment(source, provider) or ""
    assert body.count("authorization.verify()") == 2
    assert "authorization.verify(now=" not in body


def test_counter_review_does_not_claim_operational_or_owner_authority() -> None:
    # Each forbidden claim is joined from separate words at runtime so this
    # counter-review can name what it refuses to claim without the contiguous
    # phrase appearing in the very file it scans. A claim spelled out anywhere
    # in this file -- prose, comment, docstring or string literal -- still fails.
    forbidden_claims = tuple(
        " ".join(words)
        for words in (
            ("approved", "by", "owner"),
            ("human", "review", "passed"),
            ("gate", "0", "closed"),
        )
    )
    source = Path(__file__).read_text(encoding="utf-8").lower()
    for claim in forbidden_claims:
        assert claim not in source, f"counter-review must not claim: {claim}"
