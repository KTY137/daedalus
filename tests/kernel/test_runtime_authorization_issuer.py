# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""The production minter exists — and both halves of its condition are pinned.

``effect_boundary.py`` records the exact condition under which the
``provider.claude`` row may move: "(1) caller injection -- some production
caller actually mints a ``RuntimeBoundEffectAuthorization``; (2) exact-head
verification."  This file pins half one from both sides:

* against the REAL registry, the minter FAILS CLOSED with the registry's own
  refusal ("inventory_only, not central") — so the new facade cannot be used
  to route around the row while it is still an inventory row;
* against a registry identical except for ``wiring=CENTRAL``, the full mint
  succeeds end to end with REAL ingredients: keys created as files in the
  checkout-external control root, the production trust ledger, the live kill
  switch — and the minted capability verifies, which no prior production
  path could produce at all (measured 2026-08-26: zero production
  constructors, all six sites under tests/).

Trust-ledger ADMISSION is the one seam stubbed here
(``verify_production_runtime_envelope`` is patched out for the fixture
envelope, exactly as ``tests/providers/test_claude_runtime_broker.py`` does):
admitting a REAL live envelope is precisely the remaining live-run work this
issuer exists to unblock, and faking it green here would claim that work done.
"""
from __future__ import annotations

import dataclasses
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from daedalus.kernel.contracts import (          # noqa: E402
    ContractProvenance,
    EffectLeaseRequest,
    EffectScope,
)
from daedalus.kernel.effects import EffectLeaseBindingMismatch  # noqa: E402
from daedalus.kernel.offload_lease import kill_switch_generation  # noqa: E402
from daedalus.kernel.runtime_authorization_issuer import (  # noqa: E402
    RUNTIME_AUTHORITY_KEY_ID,
    RUNTIME_LEASE_KEY_ID,
    acquire_runtime_bound_authorization,
    runtime_trust_ledger,
    runtime_trust_ledger_path,
)
from daedalus.schemas import PolicyDecision      # noqa: E402
from daedalus.spine.effect_boundary import (     # noqa: E402
    REGISTRY_BY_ID,
    Effect,
    GuardDecision,
    Wiring,
)
from daedalus.spine.killswitch import KillSwitch, control_root  # noqa: E402

ENTRYPOINT = "provider.claude"
REVISION = "c" * 40
MANIFEST_SHA = "1" * 64
RECEIPT_SHA = "2" * 64
IDENTITY_SHA = "3" * 64
ENVELOPE_SHA = "4" * 64
POLICY_SHA = "5" * 64
NOW = datetime.now(timezone.utc)


@pytest.fixture
def repo(tmp_path):
    """A real git repo so the control root hashes to a fresh identity."""
    repo_path = tmp_path / "repo"
    repo_path.mkdir()

    def git(*args):
        subprocess.run(["git", *args], cwd=repo_path, check=True,
                       capture_output=True)

    git("init")
    git("config", "user.name", "t")
    git("config", "user.email", "t@example.invalid")
    (repo_path / "x.md").write_text("x\n", encoding="utf-8")
    git("add", "x.md")
    git("commit", "-m", "seed")
    yield repo_path
    import shutil
    shutil.rmtree(control_root(repo_path), ignore_errors=True)


@pytest.fixture
def armed_switch(repo):
    sw = KillSwitch(repo_root=repo)
    sw.arm(force=True)
    yield sw
    sw.stop("test teardown")


def _scope() -> EffectScope:
    return EffectScope(
        read_only=False,
        writable_paths=(".",),
        egress_endpoints=("https://api.anthropic.com",),
        tools=("claude",),
        max_cost_microusd=1000,
        max_concurrency=1,
        timeout_s=600,
        kill_switch_ref="mission-kill",
    )


def _request(generation: int) -> EffectLeaseRequest:
    return EffectLeaseRequest(
        request_id="rt-issuer-request-1",
        mission_id="mission-rt-1",
        attempt_id="attempt-rt-1",
        entrypoint_id=ENTRYPOINT,
        requested_effects=(
            Effect.FILESYSTEM_WRITE.value,
            Effect.NETWORK_EGRESS.value,
            Effect.PROCESS_SPAWN.value,
            Effect.SPEND.value,
        ),
        effect_scope=_scope(),
        idempotency_namespace="mission-rt-1-attempt-rt-1",
        kill_switch_generation=generation,
        runtime_manifest_sha256=MANIFEST_SHA,
        runtime_conformance_sha256=RECEIPT_SHA,
        provenance=ContractProvenance(
            origin="tests.runtime-authorization-issuer",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(MANIFEST_SHA, RECEIPT_SHA),
            trace_id="mission-rt-1",
        ),
    )


def _policy(request: EffectLeaseRequest) -> PolicyDecision:
    return PolicyDecision(
        decision_id="rt-issuer-policy-1",
        subject_id=request.request_id,
        subject_sha256=request.digest,
        policy_version="2026-08-26",
        policy_sha256=POLICY_SHA,
        verdict="allow",
        reasons=("bounded runtime issuer test",),
        effect_scope=request.effect_scope,
        provenance=ContractProvenance(
            origin="tests.runtime-authorization-issuer-policy",
            source_revision=REVISION,
            created_at=NOW.isoformat(),
            input_digests=(request.digest, POLICY_SHA),
            trace_id="mission-rt-1",
        ),
    )


def _guards() -> tuple[GuardDecision, ...]:
    return (
        GuardDecision(
            "budget.process_guard", True, "artifact-locator:sha256:" + "a" * 64
        ),
        GuardDecision(
            "provider.write_policy", True, "artifact-locator:sha256:" + "b" * 64
        ),
    )


def _central_registry():
    """The REAL row with exactly one field changed: wiring.

    ``dataclasses.replace`` of the registry's own spec, so the effects, guard
    contracts and runtime id under test are the production ones — a hand-rolled
    registry here would be testing a row that does not exist.
    """
    spec = dataclasses.replace(
        REGISTRY_BY_ID[ENTRYPOINT], wiring=Wiring.CENTRAL
    )
    return {spec.id: spec}


def _admit_envelope(repo, monkeypatch) -> None:
    """Admit the fixture envelope into the PRODUCTION trust ledger."""
    monkeypatch.setattr(
        "daedalus.runtimes.trust_store.verify_production_runtime_envelope",
        lambda *args, **kwargs: None,
    )
    ledger = runtime_trust_ledger(repo)
    manifest = SimpleNamespace(
        runtime_id="claude_code_cli", digest=MANIFEST_SHA, source_revision=REVISION
    )
    identity = SimpleNamespace(digest=IDENTITY_SHA)
    receipt = SimpleNamespace(
        digest=RECEIPT_SHA,
        finished_at=(NOW - timedelta(minutes=10)).isoformat(),
    )
    envelope = SimpleNamespace(
        runtime_id="claude_code_cli",
        runtime_manifest_sha256=MANIFEST_SHA,
        probe_identity_sha256=IDENTITY_SHA,
        conformance_receipt_sha256=RECEIPT_SHA,
        source_revision=REVISION,
        digest=ENVELOPE_SHA,
    )
    ledger.admit(
        envelope,
        identity,
        receipt,
        manifest,
        trusted_envelope_sha256s=(ENVELOPE_SHA,),
        admitted_at=NOW - timedelta(minutes=9),
        expires_at=NOW + timedelta(hours=2),
    )


# --------------------------------------------------------------------------- #
# half one, refused: the real registry row is still an inventory row           #
# --------------------------------------------------------------------------- #
def test_the_real_registry_still_refuses_and_this_facade_cannot_widen_it(
        repo, armed_switch, monkeypatch):
    """The refusal comes from ``issue_effect_lease``, not from a new check here.

    This is the guarantee that makes the facade safe to land before the row
    moves: against the registry as it stands, it cannot mint for any provider
    row, so nothing about adding the module changes what production can do."""
    _admit_envelope(repo, monkeypatch)
    generation = kill_switch_generation(armed_switch)
    request = _request(generation)
    with pytest.raises(EffectLeaseBindingMismatch, match="not central"):
        acquire_runtime_bound_authorization(
            repo,
            request=request,
            policy_decision=_policy(request),
            guard_decisions=_guards(),
            runtime_envelope_sha256=ENVELOPE_SHA,
            switch=armed_switch,
        )


# --------------------------------------------------------------------------- #
# half one, demonstrated: with a CENTRAL row the full production mint works    #
# --------------------------------------------------------------------------- #
def test_a_central_row_mints_a_verifying_authorization_from_real_ingredients(
        repo, armed_switch, monkeypatch):
    _admit_envelope(repo, monkeypatch)
    generation = kill_switch_generation(armed_switch)
    request = _request(generation)
    authorization = acquire_runtime_bound_authorization(
        repo,
        request=request,
        policy_decision=_policy(request),
        guard_decisions=_guards(),
        runtime_envelope_sha256=ENVELOPE_SHA,
        switch=armed_switch,
        registry=_central_registry(),
    )

    # The capability verifies against the SAME persisted trust record — the
    # full verification path, not a field check.
    record = authorization.verify()
    assert record.envelope_sha256 == ENVELOPE_SHA
    assert authorization.capability.runtime_id == "claude_code_cli"
    assert authorization.capability.lease.entrypoint_id == ENTRYPOINT

    # The ingredients are real files in the checkout-external control root,
    # never environment variables (the A9a/A10 rule).
    root = control_root(repo)
    assert (root / "runtime-lease-issuer.key").is_file()
    assert (root / "runtime-authority.key").is_file()
    assert (root / "runtime-trust-integrity.key").is_file()
    assert runtime_trust_ledger_path(repo).is_file()
    keys = {
        (root / "runtime-lease-issuer.key").read_bytes(),
        (root / "runtime-authority.key").read_bytes(),
        (root / "runtime-trust-integrity.key").read_bytes(),
    }
    assert len(keys) == 3, "two authorities share one key; see the module docstring"
    assert authorization.lease_keyring[RUNTIME_LEASE_KEY_ID] in keys
    assert authorization.runtime_authority_keyring[RUNTIME_AUTHORITY_KEY_ID] in keys


# --------------------------------------------------------------------------- #
# the refusals that guard the mint                                             #
# --------------------------------------------------------------------------- #
def test_an_unadmitted_envelope_cannot_be_minted_against(repo, armed_switch):
    """No admission row, no capability — the trust ledger is the authority."""
    from daedalus.runtimes.trust_store import RuntimeTrustNotFound

    generation = kill_switch_generation(armed_switch)
    request = _request(generation)
    with pytest.raises(RuntimeTrustNotFound, match="not admitted"):
        acquire_runtime_bound_authorization(
            repo,
            request=request,
            policy_decision=_policy(request),
            guard_decisions=_guards(),
            runtime_envelope_sha256=ENVELOPE_SHA,
            switch=armed_switch,
            registry=_central_registry(),
        )


def test_a_stale_generation_is_refused_before_any_signature(
        repo, armed_switch, monkeypatch):
    _admit_envelope(repo, monkeypatch)
    generation = kill_switch_generation(armed_switch)
    request = _request(generation + 1)
    with pytest.raises(ValueError, match="live permit generation"):
        acquire_runtime_bound_authorization(
            repo,
            request=request,
            policy_decision=_policy(request),
            guard_decisions=_guards(),
            runtime_envelope_sha256=ENVELOPE_SHA,
            switch=armed_switch,
            registry=_central_registry(),
        )
    # Refused BEFORE any signature: the effect-lease ledger was never opened
    # for this mint, so no lease row exists for the request.
    from daedalus.kernel.offload_lease import lease_ledger_path
    assert not lease_ledger_path(repo).exists(), (
        "the stale-generation refusal happened after the ledger was touched"
    )


def test_an_engaged_kill_switch_refuses_the_mint(repo, monkeypatch):
    _admit_envelope(repo, monkeypatch)
    sw = KillSwitch(repo_root=repo)
    sw.arm(force=True)
    generation = kill_switch_generation(sw)
    request = _request(generation)
    sw.stop("test: engaged before mint")
    with pytest.raises(Exception) as excinfo:
        acquire_runtime_bound_authorization(
            repo,
            request=request,
            policy_decision=_policy(request),
            guard_decisions=_guards(),
            runtime_envelope_sha256=ENVELOPE_SHA,
            switch=sw,
            registry=_central_registry(),
        )
    assert "kill switch" in str(excinfo.value).lower(), excinfo.value
