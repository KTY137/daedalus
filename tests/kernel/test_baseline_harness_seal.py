"""G3-SEAL-02 acceptance matrix -- the kernel binding that seals a Gate-3 harness.

Every numbered test maps to a row of
``docs/work-packets/G3-SEAL-02_BASELINE_HARNESS_SEAL.md`` §5.

The load-bearing claims are the refusals. A seal that authorizes nothing is
only safe as long as it *stays* unable to authorize anything, so the
cross-artifact (5c.13) and ledger non-interference (5c.14) tests are the ones
that must never be weakened.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest

from daedalus.eval.gate3.contracts import (
    ArmBudget,
    EvaluatorVersion,
    FreezeError,
    FrozenTaskSet,
    RunEnvironment,
    RunManifest,
    SeedPolicy,
)
from daedalus.kernel.approvals import (
    ApprovalExpectation,
    ApprovalLedger,
    issue_owner_approval,
    verify_owner_approval,
)
from daedalus.kernel.contracts.base import ContractProvenance
from daedalus.kernel.contracts.security import SEAL_OPERATION
from daedalus.kernel.seals import (
    SEAL_SIGNING_DOMAIN,
    ConsumedBaselineSeal,
    SealAuthority,
    SealBindingMismatch,
    SealExpectation,
    SealExpired,
    SealLedger,
    SealReplay,
    SealSignatureError,
    SealStateError,
    VerifiedBaselineSeal,
    issue_baseline_seal,
    verify_baseline_seal,
)

OWNER = "repository-owner"
KEY = "gate3-seal-key"
SECRET = b"g3-seal-secret-that-is-long-enough-32+"
BASE_REVISION = "1ba5b66f" + "0" * 32  # 40 chars: the kernel refuses abbreviations
PLAN_DIGEST = "f" * 64
KEYRING = {(OWNER, KEY): SECRET}

ISSUED = datetime(2026, 9, 9, 6, 0, tzinfo=timezone.utc)
NOW = ISSUED + timedelta(minutes=5)
EXPIRES = ISSUED + timedelta(hours=8)


def _ts(value: datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# --------------------------------------------------------------------------- #
# fixtures                                                                    #
# --------------------------------------------------------------------------- #
def _manifest(**overrides) -> RunManifest:
    kwargs = dict(
        task_set=FrozenTaskSet(
            name="voltage-rename-v1",
            task_ids=("t1", "t2", "t3"),
            counting_rule="count(tasks where gold_label_found)",
            label_plane_census={"code": 2, "knowledge": 1},
        ),
        evaluator=EvaluatorVersion(
            name="voltage_rename_scorer", version="1.0.0", code_digest="a" * 64
        ),
        budgets={
            "arm_a": ArmBudget(max_tokens=1000),
            "arm_b": ArmBudget(max_tokens=1000),
        },
        environment=RunEnvironment(
            tokenizer="cl100k_base", os_name="Windows-11", cpu="x86_64", ram_gb=32.0
        ),
        seed_policy=SeedPolicy(seeds=(1,), deterministic=True),
        base_revision=BASE_REVISION,
        plan_digest=PLAN_DIGEST,
    )
    kwargs.update(overrides)
    return RunManifest(**kwargs)


def _expectation(manifest: RunManifest, **overrides) -> SealExpectation:
    kwargs = dict(operation=SEAL_OPERATION, **manifest.seal_expectation_digests())
    kwargs.update(overrides)
    return SealExpectation(**kwargs)


def _provenance(manifest: RunManifest) -> ContractProvenance:
    digests = manifest.seal_expectation_digests()
    bound = (
        digests["manifest_sha256"],
        digests["task_set_sha256"],
        digests["evaluator_sha256"],
        digests["budget_sha256"],
        digests["environment_sha256"],
        digests["seed_policy_sha256"],
        digests["plan_digest"],
    )
    return ContractProvenance(
        origin="owner.seal-ceremony",
        source_revision=BASE_REVISION,
        created_at=_ts(ISSUED),
        input_digests=bound,
    )


def _seal(manifest: RunManifest, *, nonce="seal-nonce-1", seal_id="seal-1", **overrides):
    digests = manifest.seal_expectation_digests()
    kwargs = dict(
        seal_id=seal_id,
        owner_id=OWNER,
        key_id=KEY,
        manifest_sha256=digests["manifest_sha256"],
        task_set_sha256=digests["task_set_sha256"],
        evaluator_sha256=digests["evaluator_sha256"],
        budget_sha256=digests["budget_sha256"],
        environment_sha256=digests["environment_sha256"],
        seed_policy_sha256=digests["seed_policy_sha256"],
        base_revision=BASE_REVISION,
        plan_digest=PLAN_DIGEST,
        nonce=nonce,
        issued_at=_ts(ISSUED),
        expires_at=_ts(EXPIRES),
        provenance=_provenance(manifest),
        secret=SECRET,
    )
    kwargs.update(overrides)
    return issue_baseline_seal(**kwargs)


def _ledger(tmp_path, *, now: datetime = NOW) -> SealLedger:
    return SealLedger(tmp_path / "seals.sqlite3", clock=lambda: now)


def _authority(ledger: SealLedger, **overrides) -> SealAuthority:
    """Every ledger in this file uses the clock seam, so tests that seal a
    manifest must opt into it explicitly. The DEFAULT refusal is asserted
    separately in test_5b20."""
    kwargs = dict(ledger=ledger, keyring=KEYRING, allow_clock_seam=True)
    kwargs.update(overrides)
    return SealAuthority(**kwargs)


# --------------------------------------------------------------------------- #
# 5a -- the positive path                                                     #
# --------------------------------------------------------------------------- #
def test_5a1_issue_verify_consume_round_trip(tmp_path):
    manifest = _manifest()
    seal = _seal(manifest)
    ledger = _ledger(tmp_path)

    receipt = ledger.consume(
        seal, keyring=KEYRING, expectation=_expectation(manifest), seal_use_id="use-1"
    )

    assert isinstance(receipt, ConsumedBaselineSeal)
    assert ledger.consumed(receipt.verified.seal_sha256) is True
    assert ledger.verify_consumption(receipt, keyring=KEYRING).digest == receipt.digest


def test_5a2_sealed_manifest_reports_sealed_and_names_the_seal(tmp_path):
    manifest = _manifest()
    ledger = _ledger(tmp_path)
    receipt = ledger.consume(
        _seal(manifest),
        keyring=KEYRING,
        expectation=_expectation(manifest),
        seal_use_id="use-1",
    )

    sealed = _manifest(consumed_seal=receipt, seal_authority=_authority(ledger))

    assert sealed.sealed is True
    status = sealed.evidence_status()
    assert status.startswith("SEALED run ")
    assert OWNER in status and KEY in status
    assert "NOT Gate-3 baseline evidence" not in status


# --------------------------------------------------------------------------- #
# 5b -- refusals                                                              #
# --------------------------------------------------------------------------- #
def test_5b3_wrong_secret_is_refused():
    manifest = _manifest()
    seal = _seal(manifest)
    with pytest.raises(SealSignatureError):
        verify_baseline_seal(
            seal,
            keyring={(OWNER, KEY): b"a-different-secret-also-32-bytes-long"},
            expectation=_expectation(manifest),
            now=NOW,
        )


def test_5b3b_unknown_key_is_refused():
    manifest = _manifest()
    with pytest.raises(SealSignatureError):
        verify_baseline_seal(
            _seal(manifest),
            keyring={},
            expectation=_expectation(manifest),
            now=NOW,
        )


def test_5b4_bare_digest_signature_is_refused_DOMAIN_SEPARATION():
    """The regression test for the signing domain.

    A signature over the bare canonical digest -- exactly what
    ``daedalus.kernel.approvals`` produces -- must not verify as a seal. If
    this test ever passes without the prefix, the two artifacts have started
    sharing a signature space.
    """
    import dataclasses
    import hashlib
    import hmac

    manifest = _manifest()
    seal = _seal(manifest)
    bare = hmac.new(
        SECRET, seal.signing_digest.encode("ascii"), hashlib.sha256
    ).hexdigest()
    assert bare != seal.signature_sha256
    forged = dataclasses.replace(seal, signature_sha256=bare)

    with pytest.raises(SealSignatureError):
        verify_baseline_seal(
            forged, keyring=KEYRING, expectation=_expectation(manifest), now=NOW
        )


def test_5b4b_domain_prefix_is_actually_used():
    import hashlib
    import hmac

    manifest = _manifest()
    seal = _seal(manifest)
    expected = hmac.new(
        SECRET,
        f"{SEAL_SIGNING_DOMAIN}{seal.signing_digest}".encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    assert seal.signature_sha256 == expected


@pytest.mark.parametrize(
    "instant",
    [EXPIRES, EXPIRES + timedelta(seconds=1), ISSUED - timedelta(seconds=1)],
    ids=["at-expiry", "after-expiry", "before-issue"],
)
def test_5b5_outside_the_validity_window_is_refused(instant):
    manifest = _manifest()
    with pytest.raises(SealExpired):
        verify_baseline_seal(
            _seal(manifest),
            keyring=KEYRING,
            expectation=_expectation(manifest),
            now=instant,
        )


def test_5b6_ttl_above_24h_is_refused_at_issue():
    manifest = _manifest()
    with pytest.raises(ValueError, match="TTL"):
        _seal(manifest, expires_at=_ts(ISSUED + timedelta(hours=25)))


def test_5b7_second_consumption_of_the_same_seal_is_refused(tmp_path):
    manifest = _manifest()
    seal = _seal(manifest)
    ledger = _ledger(tmp_path)
    ledger.consume(
        seal, keyring=KEYRING, expectation=_expectation(manifest), seal_use_id="use-1"
    )
    with pytest.raises(SealReplay):
        ledger.consume(
            seal,
            keyring=KEYRING,
            expectation=_expectation(manifest),
            seal_use_id="use-2",
        )


def test_5b8_reused_nonce_under_a_new_seal_id_is_refused(tmp_path):
    manifest = _manifest()
    ledger = _ledger(tmp_path)
    ledger.consume(
        _seal(manifest, seal_id="seal-1", nonce="shared-nonce"),
        keyring=KEYRING,
        expectation=_expectation(manifest),
        seal_use_id="use-1",
    )
    with pytest.raises(SealReplay):
        ledger.consume(
            _seal(manifest, seal_id="seal-2", nonce="shared-nonce"),
            keyring=KEYRING,
            expectation=_expectation(manifest),
            seal_use_id="use-2",
        )


@pytest.mark.parametrize(
    "field",
    [
        "manifest_sha256",
        "task_set_sha256",
        "evaluator_sha256",
        "budget_sha256",
        "environment_sha256",
        "seed_policy_sha256",
        "plan_digest",
    ],
)
def test_5b9_expectation_disagreeing_on_any_bound_digest_is_refused(field):
    manifest = _manifest()
    with pytest.raises(SealBindingMismatch, match=field):
        verify_baseline_seal(
            _seal(manifest),
            keyring=KEYRING,
            expectation=_expectation(manifest, **{field: "b" * 64}),
            now=NOW,
        )


def test_5b9b_expectation_disagreeing_on_base_revision_is_refused():
    manifest = _manifest()
    with pytest.raises(SealBindingMismatch, match="base_revision"):
        verify_baseline_seal(
            _seal(manifest),
            keyring=KEYRING,
            expectation=_expectation(manifest, base_revision="c" * 40),
            now=NOW,
        )


def test_5b10_swapping_an_obligation_after_sealing_unseals_the_run(tmp_path):
    """A genuinely verified seal, pointed at a manifest whose budgets moved."""
    manifest = _manifest()
    ledger = _ledger(tmp_path)
    receipt = ledger.consume(
        _seal(manifest),
        keyring=KEYRING,
        expectation=_expectation(manifest),
        seal_use_id="use-1",
    )

    moved = _manifest(
        budgets={
            "arm_a": ArmBudget(max_tokens=9999),
            "arm_b": ArmBudget(max_tokens=9999),
        },
        consumed_seal=receipt,
        seal_authority=_authority(ledger),
    )

    assert moved.sealed is False
    assert "DIFFERENT harness" in moved.evidence_status()


def test_5b10b_adding_an_arm_after_sealing_unseals_the_run(tmp_path):
    """The reason budgets are bound as ONE digest, not per-arm."""
    manifest = _manifest()
    ledger = _ledger(tmp_path)
    receipt = ledger.consume(
        _seal(manifest),
        keyring=KEYRING,
        expectation=_expectation(manifest),
        seal_use_id="use-1",
    )

    widened = _manifest(
        budgets={
            "arm_a": ArmBudget(max_tokens=1000),
            "arm_b": ArmBudget(max_tokens=1000),
            "arm_c": ArmBudget(max_tokens=1000),
        },
        consumed_seal=receipt,
        seal_authority=_authority(ledger),
    )

    assert widened.sealed is False


def test_5b20_a_clock_seam_ledger_is_not_a_sealing_authority_by_default(tmp_path):
    """The seam is accepted; the missing piece was the downstream refusal.

    A rewound clock consumes an expired seal, so a receipt produced through an
    injected clock must not seal anything unless a test says so out loud. This
    mirrors ``promotion.authorize_persisted_promotion`` refusing a decision
    whose ``seams_used`` is non-empty.
    """
    manifest = _manifest()
    ledger = _ledger(tmp_path)
    receipt = ledger.consume(
        _seal(manifest),
        keyring=KEYRING,
        expectation=_expectation(manifest),
        seal_use_id="use-1",
    )
    assert ledger.clock_seam_used is True

    with pytest.raises(SealStateError, match="clock seam"):
        _manifest(
            consumed_seal=receipt,
            seal_authority=SealAuthority(ledger=ledger, keyring=KEYRING),
        )
    # and the explicit opt-in works, which is what every other test here uses
    assert _manifest(
        consumed_seal=receipt, seal_authority=_authority(ledger)
    ).sealed is True


def test_5b21_an_expired_seal_is_not_persisted_when_the_lock_delays_us(tmp_path):
    """HIGH-3: consume() must re-check expiry at PERSISTENCE, not only before
    acquiring the write lock, because BEGIN IMMEDIATE can block for up to
    busy_timeout. Simulated by a clock that advances past expiry between the
    preflight sample and the persistence sample."""
    manifest = _manifest()
    ticks = iter([NOW, NOW, EXPIRES + timedelta(seconds=1)])
    ledger = SealLedger(tmp_path / "slow.sqlite3", clock=lambda: next(ticks))

    with pytest.raises(SealExpired, match="expired before consumption persistence"):
        ledger.consume(
            _seal(manifest),
            keyring=KEYRING,
            expectation=_expectation(manifest),
            seal_use_id="use-1",
        )
    # nothing was persisted, and the seal is still consumable by a sane clock
    assert _ledger(tmp_path).consumed(
        verify_baseline_seal(
            _seal(manifest),
            keyring=KEYRING,
            expectation=_expectation(manifest),
            now=NOW,
        ).seal_sha256
    ) is False


def test_5b22_a_ledger_clock_that_moves_backwards_is_refused(tmp_path):
    manifest = _manifest()
    ticks = iter([NOW, NOW - timedelta(hours=1), NOW])
    ledger = SealLedger(tmp_path / "back.sqlite3", clock=lambda: next(ticks))
    with pytest.raises(SealStateError, match="moved backwards"):
        ledger.consume(
            _seal(manifest),
            keyring=KEYRING,
            expectation=_expectation(manifest),
            seal_use_id="use-1",
        )


# --------------------------------------------------------------------------- #
# 5c -- forgery                                                               #
# --------------------------------------------------------------------------- #
def _forged_verified_seal(manifest: RunManifest) -> VerifiedBaselineSeal:
    """A VerifiedBaselineSeal built with no secret, no signature and no ledger.

    Every field it needs is public: ``seal_expectation_digests()`` publishes
    all eight. This is the object an adversarial reviewer used to seal a run
    against the first revision of this packet.
    """
    digests = manifest.seal_expectation_digests()
    return VerifiedBaselineSeal(
        seal_sha256="0" * 64,
        seal_id="i-am-definitely-the-owner-trust-me",
        owner_id="attacker",
        key_id="no-key-at-all",
        operation=SEAL_OPERATION,
        manifest_sha256=digests["manifest_sha256"],
        task_set_sha256=digests["task_set_sha256"],
        evaluator_sha256=digests["evaluator_sha256"],
        budget_sha256=digests["budget_sha256"],
        environment_sha256=digests["environment_sha256"],
        seed_policy_sha256=digests["seed_policy_sha256"],
        base_revision=digests["base_revision"],
        plan_digest=digests["plan_digest"],
        nonce="forged",
        issued_at=_ts(ISSUED),
        expires_at=_ts(EXPIRES),
        signature_sha256="0" * 64,
    )


def test_5c16_a_handbuilt_unsigned_seal_of_the_REAL_class_is_refused(tmp_path):
    """THE row this matrix was missing, and the one that worked.

    §5c covered three forgeries -- the historical string, a promotion approval,
    and a structural impostor of a DIFFERENT class. It never tried the real
    class, hand-built. That is precisely the one an adversarial reviewer used:
    `owner_id="attacker"`, `signature_sha256="0"*64`, no ledger, sealed=True.
    """
    manifest = _manifest()
    forged = _forged_verified_seal(manifest)

    # it cannot even reach the manifest: the field takes a CONSUMPTION receipt
    with pytest.raises(FreezeError, match="ConsumedBaselineSeal"):
        _manifest(
            consumed_seal=forged,  # type: ignore[arg-type]
            seal_authority=_authority(_ledger(tmp_path)),
        )


def test_5c16b_a_handbuilt_consumption_receipt_is_refused(tmp_path):
    """One level up: forge the RECEIPT too, with a self-consistent digest.

    ConsumedBaselineSeal validates its own digest, so a forger can satisfy it.
    The authority is what stops this -- the ledger has no such row.
    """
    import json as _json

    from daedalus.spine.envelope import canonical_sha

    manifest = _manifest()
    forged = _forged_verified_seal(manifest)
    expectation = _expectation(manifest)
    # the canonical normalized form, because __post_init__ runs consumed_at
    # through _utc_timestamp before recomputing the digest
    consumed_at = NOW.isoformat(timespec="microseconds")
    payload = {
        "verified": forged.to_dict(),
        "expectation_sha256": expectation.digest,
        "seal_use_id": "forged-use",
        "consumed_at": consumed_at,
    }
    receipt = ConsumedBaselineSeal(
        verified=forged,
        expectation_sha256=expectation.digest,
        seal_use_id="forged-use",
        consumed_at=consumed_at,
        consumption_sha256=canonical_sha(payload),
    )
    # the forged receipt is internally valid -- that is the point
    assert _json.loads(_json.dumps(receipt.to_dict()))["seal_use_id"] == "forged-use"

    with pytest.raises(SealStateError, match="not persisted"):
        _manifest(
            consumed_seal=receipt, seal_authority=_authority(_ledger(tmp_path))
        )


@pytest.mark.parametrize("route", ["from_dict", "subclass", "pickle", "deepcopy"])
def test_5c16c_no_serialization_route_smuggles_a_forged_seal_in(tmp_path, route):
    """from_dict / subclass / pickle / deepcopy all preserved the forgery when
    the manifest trusted a VALUE. None of them can produce a ledger row."""
    import copy
    # SAFE: this pickles and immediately unpickles an object CONSTRUCTED THREE
    # LINES BELOW, in this process, from literals in this file. No untrusted
    # bytes are involved. Round-tripping it is the point of the test -- pickle
    # is one of the four routes that preserved a forged seal when the manifest
    # trusted a value type, so the route has to be exercised to prove it is
    # now closed. Do not "fix" this to JSON: JSON is already the `from_dict`
    # route, and it would stop testing the pickle route.
    import pickle  # nosec B403 - see comment above

    manifest = _manifest()
    forged = _forged_verified_seal(manifest)
    if route == "from_dict":
        smuggled = VerifiedBaselineSeal.from_dict(forged.to_dict())
    elif route == "subclass":
        class _Sub(VerifiedBaselineSeal):
            pass

        smuggled = _Sub(**forged.to_dict())
    elif route == "pickle":
        smuggled = pickle.loads(pickle.dumps(forged))
    else:
        smuggled = copy.deepcopy(forged)

    assert isinstance(smuggled, VerifiedBaselineSeal)
    with pytest.raises(FreezeError, match="ConsumedBaselineSeal"):
        _manifest(
            consumed_seal=smuggled,  # type: ignore[arg-type]
            seal_authority=_authority(_ledger(tmp_path)),
        )


def test_5c17_a_receipt_without_an_authority_is_refused(tmp_path):
    """Both fields or neither. A receipt alone cannot be authenticated."""
    manifest = _manifest()
    ledger = _ledger(tmp_path)
    receipt = ledger.consume(
        _seal(manifest),
        keyring=KEYRING,
        expectation=_expectation(manifest),
        seal_use_id="use-1",
    )
    with pytest.raises(FreezeError, match="together"):
        _manifest(consumed_seal=receipt)
    with pytest.raises(FreezeError, match="together"):
        _manifest(seal_authority=_authority(ledger))


def test_5c18_a_wrong_keyring_cannot_reauthenticate_a_genuine_receipt(tmp_path):
    """The authority re-runs the HMAC; holding the receipt is not enough."""
    manifest = _manifest()
    ledger = _ledger(tmp_path)
    receipt = ledger.consume(
        _seal(manifest),
        keyring=KEYRING,
        expectation=_expectation(manifest),
        seal_use_id="use-1",
    )
    wrong = SealAuthority(
        ledger=ledger,
        keyring={(OWNER, KEY): b"a-different-secret-also-32-bytes-long"},
        allow_clock_seam=True,
    )
    with pytest.raises(SealSignatureError):
        _manifest(consumed_seal=receipt, seal_authority=wrong)


def test_5c19_a_ledger_row_edited_in_place_no_longer_authenticates(tmp_path):
    """MEDIUM-4: verify_consumption used to compare a self-consistent digest
    to itself, so a hand-edited row passed. It now re-runs the HMAC."""
    manifest = _manifest()
    ledger = _ledger(tmp_path)
    receipt = ledger.consume(
        _seal(manifest),
        keyring=KEYRING,
        expectation=_expectation(manifest),
        seal_use_id="use-1",
    )
    connection = sqlite3.connect(str(ledger.path))
    try:
        connection.execute(
            "UPDATE baseline_harness_seal_consumptions_v1 SET owner_id='attacker'"
        )
        connection.commit()
    finally:
        connection.close()

    # the signed seal_json still names the real owner, so the row now
    # disagrees with its own authority
    with pytest.raises(SealStateError):
        ledger.verify_consumption(receipt, keyring=KEYRING)


def test_5c11_the_historical_string_forgery_still_fails():
    """Kept verbatim in spirit from G3-BASE-01. An independent reviewer sealed
    a manifest with this literal text; it must never work again."""
    manifest = _manifest(owner_seal_ref="i am definitely the owner trust me")
    assert manifest.sealed is False
    assert "UNVERIFIED seal claim" in manifest.evidence_status()


def test_5c12_no_verified_seal_means_unsealed_whatever_the_ref_says():
    assert _manifest(consumed_seal=None, owner_seal_ref="approval-42").sealed is False


def test_5c13_a_promotion_approval_cannot_be_used_as_a_seal(tmp_path):
    """Cross-artifact forgery: a genuine, currently-valid promotion approval.

    Two independent refusals are asserted, because either alone would be a
    single point of failure: the seal verifier refuses the wrong TYPE, and the
    approval's signature does not authenticate under the seal domain.
    """
    provenance = ContractProvenance(
        origin="owner.promotion",
        source_revision=BASE_REVISION,
        created_at=_ts(ISSUED),
        input_digests=("1" * 64, "2" * 64, "3" * 64),
    )
    approval = issue_owner_approval(
        approval_id="approval-1",
        owner_id=OWNER,
        key_id=KEY,
        operation="promote-candidate",
        nomination_receipt_sha256="1" * 64,
        candidate_artifact_sha256="2" * 64,
        evidence_packet_sha256="3" * 64,
        base_revision=BASE_REVISION,
        target_ref="refs/heads/main",
        expected_target_revision="d" * 40,
        nonce="promo-nonce",
        issued_at=_ts(ISSUED),
        expires_at=_ts(EXPIRES),
        provenance=provenance,
        secret=SECRET,
    )
    verified_approval = verify_owner_approval(
        approval,
        keyring=KEYRING,
        expectation=ApprovalExpectation(
            operation="promote-candidate",
            nomination_receipt_sha256="1" * 64,
            candidate_artifact_sha256="2" * 64,
            evidence_packet_sha256="3" * 64,
            base_revision=BASE_REVISION,
            target_ref="refs/heads/main",
            current_target_revision="d" * 40,
        ),
        now=NOW,
    )

    manifest = _manifest()

    # (a) the seal verifier refuses the wrong contract type outright
    with pytest.raises(TypeError):
        verify_baseline_seal(
            approval,  # type: ignore[arg-type]
            keyring=KEYRING,
            expectation=_expectation(manifest),
            now=NOW,
        )

    # (b) a manifest handed the verified PROMOTION refuses at construction.
    # It raises rather than reporting False: presenting a promotion authority
    # as a seal is a forgery attempt, not a legitimate unsealed state, and a
    # silent False would let it sit in a report looking like ordinary prework.
    with pytest.raises(FreezeError, match="ConsumedBaselineSeal"):
        _manifest(
            consumed_seal=verified_approval,  # type: ignore[arg-type]
            seal_authority=_authority(_ledger(tmp_path)),
        )

    # (c) the approval's signature is not a valid seal signature
    import hashlib
    import hmac

    seal_domain_signature = hmac.new(
        SECRET,
        f"{SEAL_SIGNING_DOMAIN}{approval.signing_digest}".encode("ascii"),
        hashlib.sha256,
    ).hexdigest()
    assert approval.signature_sha256 != seal_domain_signature


def test_5c14_consuming_a_seal_does_not_touch_the_promotion_ledger(tmp_path):
    """Ledger non-interference, asserted against ONE sqlite file."""
    shared = tmp_path / "one-file.sqlite3"
    approvals = ApprovalLedger(shared, clock=lambda: NOW)
    seals = SealLedger(shared, clock=lambda: NOW)

    manifest = _manifest()
    receipt = seals.consume(
        _seal(manifest),
        keyring=KEYRING,
        expectation=_expectation(manifest),
        seal_use_id="use-1",
    )

    # the promotion ledger knows nothing about the seal digest
    assert approvals.consumed(receipt.verified.seal_sha256) is False
    # and the two tables coexist
    connection = sqlite3.connect(str(shared))
    try:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        connection.close()
    assert "owner_approval_consumptions_v2" in tables
    assert "baseline_harness_seal_consumptions_v1" in tables


def test_5c15_an_abbreviated_base_revision_cannot_be_sealed():
    """Recorded consequence: the kernel refuses 8-char revisions.

    G3-BASE-01's own fixtures use ``base_revision="1ba5b66f"``. Such a manifest
    is structurally unsealable, which is the fail-closed direction -- an
    ambiguous revision must not be attested.
    """
    manifest = _manifest(base_revision="1ba5b66f")
    with pytest.raises(ValueError, match="40- or 64-character"):
        _expectation(manifest)


# --------------------------------------------------------------------------- #
# 5d -- fault injection                                                       #
# --------------------------------------------------------------------------- #
def test_5d16_concurrent_double_consume_admits_exactly_one(tmp_path):
    manifest = _manifest()
    seal = _seal(manifest)
    ledger = _ledger(tmp_path)
    expectation = _expectation(manifest)

    outcomes: list[str] = []
    barrier = threading.Barrier(2)

    def attempt(use_id: str) -> None:
        barrier.wait()
        try:
            ledger.consume(
                seal, keyring=KEYRING, expectation=expectation, seal_use_id=use_id
            )
            outcomes.append("ok")
        except SealReplay:
            outcomes.append("replay")

    threads = [
        threading.Thread(target=attempt, args=("use-a",)),
        threading.Thread(target=attempt, args=("use-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert sorted(outcomes) == ["ok", "replay"]


def test_5d17_malformed_verified_seal_payload_is_refused():
    with pytest.raises(ValueError):
        VerifiedBaselineSeal.from_dict({"seal_id": "seal-1"})
    with pytest.raises(ValueError):
        ConsumedBaselineSeal.from_dict({"verified": "not-an-object"})


def test_5d17b_unrecorded_consumption_is_refused(tmp_path):
    manifest = _manifest()
    seal = _seal(manifest)
    written = _ledger(tmp_path).consume(
        seal, keyring=KEYRING, expectation=_expectation(manifest), seal_use_id="use-1"
    )
    other = SealLedger(tmp_path / "empty.sqlite3", clock=lambda: NOW)
    with pytest.raises(SealStateError):
        other.verify_consumption(written, keyring=KEYRING)


def test_5d18_a_tampered_consumption_digest_is_refused(tmp_path):
    import dataclasses

    manifest = _manifest()
    verified = verify_baseline_seal(
        _seal(manifest), keyring=KEYRING, expectation=_expectation(manifest), now=NOW
    )
    # a hand-built receipt whose self-digest does not match its own payload
    with pytest.raises(ValueError, match="digest mismatch"):
        ConsumedBaselineSeal(
            verified=verified,
            expectation_sha256="e" * 64,
            seal_use_id="use-1",
            consumed_at=_ts(NOW),
            consumption_sha256="0" * 64,
        )
    # and a genuine receipt cannot be edited in place either: replace()
    # re-runs __post_init__, which recomputes the digest over the new payload
    genuine = _ledger(tmp_path).consume(
        _seal(manifest),
        keyring=KEYRING,
        expectation=_expectation(manifest),
        seal_use_id="use-1",
    )
    with pytest.raises(ValueError, match="digest mismatch"):
        dataclasses.replace(genuine, seal_use_id="use-2")


def test_5d19_seal_secret_floor_is_enforced():
    manifest = _manifest()
    with pytest.raises(ValueError, match="at least 32 bytes"):
        _seal(manifest, secret=b"too-short")


# --------------------------------------------------------------------------- #
# contract-level invariants                                                   #
# --------------------------------------------------------------------------- #
def test_seal_operation_tag_is_fixed():
    manifest = _manifest()
    seal = _seal(manifest)
    assert seal.operation == SEAL_OPERATION
    assert seal.CONTRACT_TYPE == "daedalus.baseline-harness-seal"
    import dataclasses

    with pytest.raises(ValueError, match="operation must be"):
        dataclasses.replace(seal, operation="promote-candidate")


def test_seal_provenance_must_bind_every_referenced_digest():
    manifest = _manifest()
    thin = ContractProvenance(
        origin="owner.seal-ceremony",
        source_revision=BASE_REVISION,
        created_at=_ts(ISSUED),
        input_digests=(manifest.digest,),
    )
    with pytest.raises(ValueError, match="does not bind referenced input digest"):
        _seal(manifest, provenance=thin)


def test_sealing_does_not_change_the_run_digest(tmp_path):
    """Carried forward from G3-BASE-01: the seal is outside the identity."""
    manifest = _manifest()
    ledger = _ledger(tmp_path)
    receipt = ledger.consume(
        _seal(manifest),
        keyring=KEYRING,
        expectation=_expectation(manifest),
        seal_use_id="use-1",
    )
    assert _manifest(
        consumed_seal=receipt, seal_authority=_authority(ledger)
    ).digest == manifest.digest
