from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from daedalus.kernel.contracts import (
    CampaignBudgetEqualityEvidence,
    CampaignReceipt,
    CampaignTrialReceipt,
    ContractProvenance,
    ResourceBudget,
    ResourceUsage,
)
from daedalus.spine.envelope import canonical_json, canonical_sha
from daedalus.ariadne.campaign import (
    AriadneCampaignError,
    AriadneConflictError,
    AriadneRequestError,
    _store_scoped_tree,
    run_campaign,
)
from daedalus.kernel.source_trees import SourceTreeStore
from daedalus.runtimes.contracts.repository import RepositoryHeadRevisionBindingError
from daedalus.kernel.campaigns import (
    _require_contract_matches_spec,
    CampaignLifecycleError,
    load_attempt_receipt,
    load_campaign_contract,
    load_campaign_receipt,
    load_evidence_packet,
    load_experiment_spec,
    lookup_campaign_read_only,
    verify_campaign_chain,
)


REV = "a" * 40


def _loc(digest: str) -> str:
    return f"artifact-locator:sha256:{digest}"


def _trial(variant: str, role: str, seed: int, passed: bool, budget_sha: str):
    attempt = (str(seed + 3) * 64)[:64]
    candidate = (str(seed + 6) * 64)[:64]
    evidence = (str(seed + 4) * 64)[:64]
    receipt = (str(seed + 5) * 64)[:64]
    return CampaignTrialReceipt(
        campaign_id="ariadne-v0", seed=seed, replay_role="origin", stage="complete",
        status="passed" if passed else "failed",
        base_source_tree_sha256="b" * 64, base_source_tree_locator=_loc("b" * 64),
        mission_sha256=None, mission_locator=None, attempt_ids=(f"attempt-{variant}",),
        attempt_contract_sha256s=(attempt,), attempt_contract_locators=(_loc(attempt),),
        attempt_receipt_sha256s=(receipt,), attempt_receipt_locators=(_loc(receipt),),
        gate1_receipt_sha256=None, gate1_receipt_locator=None,
        candidate_tree_sha256=candidate, candidate_tree_locator=_loc(candidate),
        candidate_source_bundle_sha256=None, candidate_snapshot_sha256=None,
        candidate_snapshot_locator=None, graph_delta_sha256=None,
        evidence_packet_sha256=evidence, evidence_packet_locator=_loc(evidence),
        metrics={"exact_match": 1 if passed else 0}, usage=ResourceUsage(wall_time_ms=seed + 1),
        negative_outcomes=() if passed else ("evaluator-rejected",),
        blockers=() if passed else ("exact-match-failed",),
        started_at="2026-09-04T10:00:00+00:00",
        finished_at="2026-09-04T10:00:01+00:00",
        variant_id=variant, arm_role=role, configured_budget_sha256=budget_sha,
        receipt_profile="controlled-repair-v1",
    )


def _receipt():
    budget = ResourceBudget(max_wall_time_s=10, max_attempts=1)
    budget_sha = canonical_sha(asdict(budget))
    trials = (
        _trial("baseline", "baseline", 0, False, budget_sha),
        _trial("negative-control", "candidate", 1, False, budget_sha),
        _trial("repair", "candidate", 2, True, budget_sha),
    )
    equality = CampaignBudgetEqualityEvidence(
        configured_budget_sha256=budget_sha,
        trial_keys=tuple(f"{t.variant_id}:{t.seed}" for t in trials),
        trial_budget_sha256s=(budget_sha,) * 3,
        realized_usage_sha256s=tuple(canonical_sha(asdict(t.usage)) for t in trials),
        configured_equal=True, realized_usage_recorded=True, within_budget=True,
    )
    campaign_sha, spec_sha, nomination_sha = "c" * 64, "d" * 64, "e" * 64
    required = {campaign_sha, spec_sha, nomination_sha}
    for trial in trials:
        required.update((trial.base_source_tree_sha256, trial.candidate_tree_sha256, trial.evidence_packet_sha256))
        required.update(trial.attempt_contract_sha256s)
        required.update(trial.attempt_receipt_sha256s)
    return CampaignReceipt(
        campaign_id="ariadne-v0", source_revision=REV,
        campaign_contract_sha256=campaign_sha, campaign_contract_locator=_loc(campaign_sha),
        experiment_spec_sha256=spec_sha, experiment_spec_locator=_loc(spec_sha),
        metric_names=("exact_match",), trials=trials, execution_order=(0, 1, 2),
        outcome="nominated", selected_seed=2,
        candidate_tree_sha256=trials[2].candidate_tree_sha256,
        candidate_tree_locator=trials[2].candidate_tree_locator,
        nomination_receipt_sha256=nomination_sha, nomination_receipt_locator=_loc(nomination_sha),
        usage=ResourceUsage(wall_time_ms=6), overhead_usage=ResourceUsage(),
        negative_outcomes=("evaluator-rejected",),
        reproducibility_note="fixed base, evaluator, variants, order, and budgets",
        blockers=(), started_at="2026-09-04T10:00:00+00:00",
        finished_at="2026-09-04T10:00:02+00:00",
        provenance=ContractProvenance(
            origin="ariadne.v0.test", source_revision=REV,
            created_at="2026-09-04T10:00:02+00:00", input_digests=tuple(sorted(required)),
        ),
        selection_mode="best-passed-trial", selected_variant_id="repair",
        budget_equality=equality,
    )


def test_nomination_retains_failed_baseline_and_negative_control() -> None:
    receipt = _receipt()
    assert receipt.outcome == "nominated"
    assert [trial.status for trial in receipt.trials] == ["failed", "failed", "passed"]
    assert receipt.candidate_tree_sha256 == receipt.trials[2].candidate_tree_sha256
    assert CampaignReceipt.from_dict(receipt.to_dict()) == receipt


def test_selected_variant_and_candidate_are_exactly_bound() -> None:
    receipt = _receipt()
    with pytest.raises(ValueError, match="selected variant/seed"):
        replace(receipt, selected_variant_id="negative-control")
    with pytest.raises(ValueError, match="candidate must equal selected"):
        replace(receipt, candidate_tree_sha256=receipt.trials[1].candidate_tree_sha256,
                candidate_tree_locator=receipt.trials[1].candidate_tree_locator)


def test_budget_equality_refuses_one_unequal_arm() -> None:
    budget_sha = canonical_sha(asdict(ResourceBudget(max_wall_time_s=10, max_attempts=1)))
    with pytest.raises(ValueError, match="unequal configured budgets"):
        CampaignBudgetEqualityEvidence(
            configured_budget_sha256=budget_sha, trial_keys=("a:0", "b:1"),
            trial_budget_sha256s=(budget_sha, "f" * 64),
            realized_usage_sha256s=("1" * 64, "2" * 64),
            configured_equal=True, realized_usage_recorded=True, within_budget=True,
        )


def test_receipt_refuses_false_aggregate_usage() -> None:
    receipt = _receipt()
    with pytest.raises(ValueError, match="aggregate usage"):
        replace(receipt, usage=ResourceUsage(wall_time_ms=5))


def test_receipt_refuses_realized_usage_hash_mutant() -> None:
    receipt = _receipt()
    mutant = replace(
        receipt.budget_equality,
        realized_usage_sha256s=("f" * 64,) + receipt.budget_equality.realized_usage_sha256s[1:],
    )
    with pytest.raises(ValueError, match="realized trial usage"):
        replace(receipt, budget_equality=mutant)


def test_receipt_refuses_trial_budget_digest_mutant() -> None:
    receipt = _receipt()
    trials = (replace(receipt.trials[0], configured_budget_sha256="f" * 64),) + receipt.trials[1:]
    with pytest.raises(ValueError, match="trial configured budgets"):
        replace(receipt, trials=trials)


def test_chain_refuses_budget_evidence_not_bound_to_campaign_contract() -> None:
    receipt = _receipt()
    contract = SimpleNamespace(
        campaign_id=receipt.campaign_id,
        source_revision=receipt.source_revision,
        digest=receipt.campaign_contract_sha256,
        experiment_spec_sha256=receipt.experiment_spec_sha256,
        seeds=receipt.execution_order,
        metrics=receipt.metric_names,
        budget=ResourceBudget(max_wall_time_s=11, max_attempts=1),
    )
    with pytest.raises(CampaignLifecycleError, match="CampaignContract budget"):
        verify_campaign_chain(SimpleNamespace(), contract, None, receipt)


def test_path_bearing_campaign_id_is_refused_before_any_path_write(tmp_path) -> None:
    missing = tmp_path / "must-not-be-created"
    with pytest.raises(AriadneCampaignError, match="path-free"):
        run_campaign(
            repo_root=missing, source_revision="a" * 40,
            campaign_id="safe/../../outside", target_path="sample.txt",
            before="x", after="y",
        )
    assert not missing.exists()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "target_path",
    (".git/HEAD", ".GIT/HEAD", ".daedalus/state.json", ".DAEDALUS/state.json"),
)
def test_mandatory_ignored_target_is_refused_before_read_or_effect(
    tmp_path, monkeypatch, target_path
) -> None:
    import daedalus.ariadne.campaign as module

    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.setattr(
        module,
        "read_repository_source",
        lambda *_args: pytest.fail("ignored target reached repository read"),
    )
    monkeypatch.setattr(
        module,
        "acquire_effect_lease",
        lambda *_args, **_kwargs: pytest.fail("ignored target reached effect admission"),
    )

    with pytest.raises(AriadneRequestError, match="mandatory ignored root"):
        module.run_campaign(
            repo_root=root,
            source_revision=REV,
            campaign_id="ignored-target",
            target_path=target_path,
            before="old",
            after="new",
        )


def test_missing_and_symlink_targets_are_typed_pre_effect_request_errors(
    tmp_path, monkeypatch
) -> None:
    import daedalus.ariadne.campaign as module

    root = tmp_path / "repo"
    root.mkdir()
    target = root / "target.txt"
    target.write_text("old", encoding="utf-8")
    link = root / "link.txt"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    monkeypatch.setattr(
        module,
        "acquire_effect_lease",
        lambda *_args, **_kwargs: pytest.fail("unsafe target reached effect admission"),
    )
    # G1-ARIADNE-05: HEAD is observed before the target is read, so this
    # target-typing test verifies HEAD the way the other unit tests do.
    monkeypatch.setattr(
        module,
        "verify_repository_head_revision",
        lambda *_args: SimpleNamespace(to_dict=lambda: {"head": REV}),
    )

    for campaign_id, target_path in (
        ("missing-target", "missing.txt"),
        ("symlink-target", "link.txt"),
    ):
        with pytest.raises(AriadneRequestError, match="unavailable or unsafe"):
            module.run_campaign(
                repo_root=root,
                source_revision=REV,
                campaign_id=campaign_id,
                target_path=target_path,
                before="old",
                after="new",
            )


def test_stale_head_is_a_typed_pre_effect_conflict(tmp_path, monkeypatch) -> None:
    import daedalus.ariadne.campaign as module

    root = tmp_path / "repo"
    root.mkdir()
    (root / "target.txt").write_text("old", encoding="utf-8")

    def stale_head(*_args):
        raise RepositoryHeadRevisionBindingError("repository HEAD differs")

    monkeypatch.setattr(module, "verify_repository_head_revision", stale_head)
    monkeypatch.setattr(
        module,
        "acquire_effect_lease",
        lambda *_args, **_kwargs: pytest.fail("stale HEAD reached effect admission"),
    )

    with pytest.raises(AriadneConflictError, match="source_revision conflict"):
        module.run_campaign(
            repo_root=root,
            source_revision=REV,
            campaign_id="stale-head",
            target_path="target.txt",
            before="old",
            after="new",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("before", b"broken", "before must be a strict string"),
        ("after", None, "after must be a strict string"),
    ],
)
def test_repair_fragments_are_strict_and_bounded_before_filesystem_access(
    tmp_path, field, value, message
) -> None:
    arguments = {
        "repo_root": tmp_path / "must-not-be-created",
        "source_revision": REV,
        "campaign_id": "bounded-input",
        "target_path": "sample.txt",
        "before": "broken",
        "after": "fixed",
    }
    arguments[field] = value
    with pytest.raises(AriadneCampaignError, match=message):
        run_campaign(**arguments)
    assert list(tmp_path.iterdir()) == []


def test_oversized_repair_fragment_is_refused_before_filesystem_access(
    tmp_path,
) -> None:
    with pytest.raises(
        AriadneCampaignError,
        match="after exceeds the 1048576-byte repair-fragment ceiling",
    ):
        run_campaign(
            repo_root=tmp_path / "must-not-be-created",
            source_revision=REV,
            campaign_id="bounded-input",
            target_path="sample.txt",
            before="broken",
            after="x" * (1024 * 1024 + 1),
        )
    assert list(tmp_path.iterdir()) == []


def test_repair_and_negative_control_file_caps_precede_effect_lease(
    tmp_path, monkeypatch
) -> None:
    import daedalus.ariadne.campaign as module

    root = tmp_path / "repo"
    root.mkdir()
    (root / "sample.txt").write_text("broken\n", encoding="utf-8")
    monkeypatch.setattr(
        module,
        "verify_repository_head_revision",
        lambda *_args: SimpleNamespace(to_dict=lambda: {"head": REV}),
    )
    monkeypatch.setattr(module, "MAX_CAMPAIGN_FILE_BYTES", 8)
    monkeypatch.setattr(
        module,
        "acquire_effect_lease",
        lambda *_args, **_kwargs: pytest.fail("effect lease must not be acquired"),
    )

    with pytest.raises(AriadneCampaignError, match="repair output exceeds"):
        module.run_campaign(
            repo_root=root,
            source_revision=REV,
            campaign_id="repair-output-cap",
            target_path="sample.txt",
            before="broken",
            after="replacement",
        )
    with pytest.raises(AriadneCampaignError, match="negative-control output exceeds"):
        module.run_campaign(
            repo_root=root,
            source_revision=REV,
            campaign_id="negative-output-cap",
            target_path="sample.txt",
            before="broken",
            after="",
        )
    assert not (root / "runs").exists()


def test_absent_replay_lookup_creates_nothing(tmp_path) -> None:
    assert lookup_campaign_read_only(
        str(tmp_path / "spine.sqlite3"), str(tmp_path / "cas"), "absent",
        expected_operation_sha256="a" * 64,
    ) is None
    assert list(tmp_path.iterdir()) == []


def _stub_campaign_admission(module, tmp_path, monkeypatch) -> None:
    payload = b"broken"
    monkeypatch.setattr(
        module,
        "_safe_target",
        lambda _root, _path: (
            "sample.txt",
            SimpleNamespace(source=payload, source_sha256="b" * 64),
        ),
    )
    monkeypatch.setattr(
        module,
        "verify_repository_head_revision",
        lambda *_args: SimpleNamespace(to_dict=lambda: {"head": "a" * 40}),
    )
    monkeypatch.setattr(
        module,
        "resolve_spine_db_path",
        lambda _root: (tmp_path / "spine.sqlite3", None),
    )

    class Switch:
        path = tmp_path / "killswitch"

        def __init__(self, **_kwargs):
            pass

        def read_state(self):
            return SimpleNamespace(running=True)

    monkeypatch.setattr(module, "KillSwitch", Switch)


def test_denied_lease_refuses_before_replay_sqlite_or_any_write(
    tmp_path, monkeypatch
) -> None:
    import daedalus.ariadne.campaign as module

    _stub_campaign_admission(module, tmp_path, monkeypatch)

    class Denied:
        reasons = ("policy denied",)

    monkeypatch.setattr(module, "WaveLeaseDenied", Denied)
    monkeypatch.setattr(module, "acquire_effect_lease", lambda *_a, **_kw: Denied())

    def _replay_must_not_open(*_args, **_kwargs):  # pragma: no cover - refusal path
        raise AssertionError("replay SQLite opened before the lease boundary")

    monkeypatch.setattr(module, "lookup_campaign_read_only", _replay_must_not_open)

    with pytest.raises(AriadneCampaignError, match="effect lease denied"):
        module.run_campaign(
            repo_root=tmp_path,
            source_revision="a" * 40,
            campaign_id="denied-before-replay",
            target_path="sample.txt",
            before="broken",
            after="fixed",
        )

    assert not (tmp_path / "spine.sqlite3-wal").exists()
    assert not (tmp_path / "spine.sqlite3-shm").exists()
    assert list(tmp_path.iterdir()) == []


def test_replay_lookup_is_after_lease_and_begin_effect(tmp_path, monkeypatch) -> None:
    import daedalus.ariadne.campaign as module

    _stub_campaign_admission(module, tmp_path, monkeypatch)
    events: list[str] = []

    class Authorization:
        def begin_effect(self, _execution):
            events.append("begin-effect")
            return SimpleNamespace(execute=False, receipt="existing-start")

    class Granted:
        authorization = Authorization()

        def execution_for(self, *_args, **_kwargs):
            return "execution"

    def _acquire(*_args, **_kwargs):
        events.append("lease")
        return Granted()

    def _lookup(*_args, **_kwargs):
        events.append("replay")
        return None

    monkeypatch.setattr(module, "acquire_effect_lease", _acquire)
    monkeypatch.setattr(
        module,
        "_outer_effect_binding",
        lambda *_args, **_kwargs: events.append("start-evidence") or {},
    )
    monkeypatch.setattr(module, "lookup_campaign_read_only", _lookup)

    with pytest.raises(AriadneCampaignError, match="already terminal or pending"):
        module.run_campaign(
            repo_root=tmp_path,
            source_revision="a" * 40,
            campaign_id="ordered-replay",
            target_path="sample.txt",
            before="broken",
            after="fixed",
        )

    assert events == ["lease", "start-evidence", "begin-effect", "replay"]
    assert list(tmp_path.iterdir()) == []


def test_missing_outer_start_evidence_refuses_before_begin_lock_or_state(
    tmp_path, monkeypatch
) -> None:
    import daedalus.ariadne.campaign as module

    _stub_campaign_admission(module, tmp_path, monkeypatch)
    events: list[str] = []

    class Authorization:
        @staticmethod
        def begin_effect(_execution):  # pragma: no cover - must remain pre-effect
            events.append("begin-effect")
            raise AssertionError("begin_effect followed missing retained start evidence")

    execution = SimpleNamespace(execution_id="outer-execution", digest="b" * 64)

    class Granted:
        authorization = Authorization()
        evidence_records = {}
        evidence_root = str(tmp_path / "missing-evidence")
        lease = SimpleNamespace(digest="a" * 64)

        @staticmethod
        def execution_for(*_args, **_kwargs):
            events.append("execution")
            return execution

    class Lock:
        def __init__(self, *_args, **_kwargs):
            events.append("lock-created")

    monkeypatch.setattr(
        module,
        "acquire_effect_lease",
        lambda *_args, **_kwargs: Granted(),
    )
    monkeypatch.setattr(module, "ExclusiveFileLock", Lock)

    with pytest.raises(
        AriadneCampaignError,
        match="outer campaign effect evidence was not retained before commit",
    ):
        module.run_campaign(
            repo_root=tmp_path,
            source_revision=REV,
            campaign_id="missing-outer-start",
            target_path="sample.txt",
            before="broken",
            after="fixed",
        )

    assert events == ["execution"]
    assert not (tmp_path / "spine.sqlite3").exists()


def test_real_outer_leases_allow_exact_campaign_replay(
    tmp_path, monkeypatch
) -> None:
    """A retry gets fresh invocation authority but reuses no trial effects."""
    import hashlib

    import daedalus.ariadne.campaign as module
    from daedalus.spine.killswitch import KillSwitch

    root = tmp_path / "repo"
    root.mkdir()
    (root / "sample.txt").write_text("broken\n", encoding="utf-8")
    expected_candidate = (root / "sample.txt").read_bytes().replace(
        b"broken", b"fixed", 1
    )
    switch_path = tmp_path / "control" / "killswitch"
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(switch_path))
    monkeypatch.setattr(
        module,
        "verify_repository_head_revision",
        lambda *_args: SimpleNamespace(to_dict=lambda: {"head": REV}),
    )

    evaluations: list[tuple[str, bool]] = []

    class _Contained:
        @staticmethod
        def summary() -> dict[str, object]:
            return {
                "requested": True,
                "executes_candidate": True,
                "contained": True,
                "platform": "test",
                "mechanism": "frozen-evaluator-test-double",
                "inherited_handle_count": 0,
            }

    def fake_command_gate(argv, **_kwargs):
        expected_sha256 = str(argv[-1])

        def evaluate(context):
            payload = (context.worktree / "sample.txt").read_bytes()
            observed_sha256 = hashlib.sha256(payload).hexdigest()
            passed = observed_sha256 == expected_sha256
            output = canonical_json({
                "expected_sha256": expected_sha256,
                "observed_sha256": observed_sha256,
                "passed": passed,
            }) + "\n"
            (context.worktree / "sample.txt").write_bytes(
                b"mutated-after-evaluator-observation"
            )
            evaluations.append((context.task.task_id, passed))
            return SimpleNamespace(
                passed=passed,
                returncode=0 if passed else 1,
                output=output,
                output_sha256=hashlib.sha256(output.encode("ascii")).hexdigest(),
                duration_s=(
                    6.0 if "budget-stop" in context.task.task_id else 0.001
                ),
                containment=_Contained(),
            )

        return evaluate

    monkeypatch.setattr(module, "command_gate", fake_command_gate)
    switch = KillSwitch(repo_root=root)
    assert switch.arm(note="Ariadne replay integration test").running
    arguments = {
        "repo_root": root,
        "source_revision": REV,
        "campaign_id": "real-replay",
        "target_path": "sample.txt",
        "before": "broken",
        "after": "fixed",
        "timeout_s": 5,
    }
    try:
        first = module.run_campaign(**arguments)
        second = module.run_campaign(**arguments)

        assert first == second
        assert first["outcome"] == "nominated"
        assert [passed for _attempt, passed in evaluations] == [False, False, True]
        retained_store = SourceTreeStore.open_existing(
            switch_path.parent / "ariadne" / "source-cas"
        )
        retained_contract = load_campaign_contract(
            retained_store, str(first["campaign_contract_locator"])
        )
        retained_spec = load_experiment_spec(
            retained_store, str(first["experiment_spec_locator"])
        )
        with pytest.raises(
            CampaignLifecycleError,
            match="execution fields differ from ExperimentSpec",
        ):
            _require_contract_matches_spec(
                replace(
                    retained_contract,
                    gate_timeout_s=int(retained_contract.gate_timeout_s) + 1,
                ),
                retained_spec,
            )
        selected_materialization = tmp_path / "selected-candidate"
        retained_store.materialize_tree(
            str(first["candidate_tree_locator"]), selected_materialization
        )
        assert (
            selected_materialization / "sample.txt"
        ).read_bytes() == expected_candidate

        selected_manifest = retained_store.load_tree(
            str(first["candidate_tree_locator"])
        )
        selected_blob_sha = selected_manifest.entries[0].blob_sha256
        selected_blob_path = (
            retained_store.root
            / "objects"
            / selected_blob_sha[:2]
            / selected_blob_sha[2:]
        )
        selected_blob = selected_blob_path.read_bytes()
        selected_blob_path.unlink()
        with pytest.raises(
            AriadneCampaignError,
            match="invalid persisted .* candidate source tree",
        ):
            module.run_campaign(**arguments)
        assert retained_store.put_bytes(selected_blob).sha256 == selected_blob_sha

        selected_evidence_sha = str(
            first["trials"][2]["evidence_packet_sha256"]
        )
        selected_evidence_path = (
            retained_store.root
            / "objects"
            / selected_evidence_sha[:2]
            / selected_evidence_sha[2:]
        )
        selected_evidence = selected_evidence_path.read_bytes()
        selected_evidence_path.unlink()
        with pytest.raises(
            AriadneCampaignError,
            match="invalid persisted EvidencePacket",
        ):
            module.run_campaign(**arguments)
        assert (
            retained_store.put_bytes(selected_evidence).sha256
            == selected_evidence_sha
        )

        crash_calls: list[str] = []

        def crashing_command_gate(*_args, **_kwargs):
            def evaluate(context):
                assert (context.worktree / "sample.txt").is_file()
                crash_calls.append(context.task.task_id)
                raise RuntimeError("injected evaluator crash after candidate capture")

            return evaluate

        crash_arguments = {
            **arguments,
            "campaign_id": "post-capture-error",
        }
        monkeypatch.setattr(module, "command_gate", crashing_command_gate)
        with pytest.raises(
            RuntimeError,
            match="injected evaluator crash after candidate capture",
        ):
            module.run_campaign(**crash_arguments)
        monkeypatch.setattr(module, "command_gate", fake_command_gate)
        crash_receipt = module.run_campaign(**crash_arguments)
        assert crash_calls == ["post-capture-error-baseline"]
        assert crash_receipt["outcome"] == "failed"
        assert crash_receipt["execution_order"] == [0]
        crash_trial = crash_receipt["trials"][0]
        assert crash_trial["status"] == "error"
        assert crash_trial["candidate_tree_sha256"]
        assert crash_trial["evidence_packet_sha256"]
        crash_attempt_receipt = load_attempt_receipt(
            retained_store,
            crash_trial["attempt_receipt_locators"][0],
        )
        assert crash_attempt_receipt.outcome == "faulted"
        assert (
            crash_attempt_receipt.candidate_tree.sha256
            == crash_trial["candidate_tree_sha256"]
        )
        crash_packet = load_evidence_packet(
            retained_store,
            crash_trial["evidence_packet_locator"],
        )
        assert crash_packet.evaluation_status == "failed"
        assert crash_packet.subject_sha256 == crash_trial["candidate_tree_sha256"]
        assert crash_packet.items[0].verdict == "error"
        crash_observation = json.loads(
            retained_store.read_bytes(
                crash_packet.items[0].evidence_locator,
                max_bytes=1024 * 1024,
            ).decode("ascii")
        )
        assert crash_observation["schema"] == (
            "daedalus-ariadne-evaluator-error/1"
        )
        assert (
            crash_observation["candidate_tree_sha256"]
            == crash_trial["candidate_tree_sha256"]
        )

        baseline_attempt_receipt = load_attempt_receipt(
            retained_store,
            first["trials"][0]["attempt_receipt_locators"][0],
        )
        baseline_report = json.loads(
            retained_store.read_bytes(
                baseline_attempt_receipt.report,
                max_bytes=1024 * 1024,
            ).decode("ascii")
        )
        baseline_binding = baseline_report["inner_effect"]
        terminal_root = (
            switch_path.parent
            / "ariadne"
            / "effect-evidence"
            / "real-replay"
            / "lease-terminal"
        )
        matching_terminal_paths = []
        for terminal_path in terminal_root.glob("*.json"):
            terminal_payload = json.loads(terminal_path.read_text(encoding="utf-8"))
            if (
                terminal_payload.get("execution_id")
                == baseline_binding["execution_id"]
            ):
                matching_terminal_paths.append(terminal_path)
        assert len(matching_terminal_paths) == 1
        inner_terminal_path = matching_terminal_paths[0]
        inner_terminal_bytes = inner_terminal_path.read_bytes()

        inner_terminal_path.unlink()
        with pytest.raises(
            AriadneCampaignError,
            match="inner attempt effect needs reconciliation",
        ):
            module.run_campaign(**arguments)
        inner_terminal_path.write_bytes(inner_terminal_bytes)

        inner_terminal_path.write_bytes(b"{}")
        with pytest.raises(
            AriadneCampaignError,
            match="inner attempt effect needs reconciliation",
        ):
            module.run_campaign(**arguments)
        inner_terminal_path.write_bytes(inner_terminal_bytes)

        # Same id, changed material: a CONFLICT (409 over HTTP), the same class
        # as a stale HEAD, not a malformed request (Odysseus finding, 2026-09-05).
        with pytest.raises(AriadneConflictError, match="changed repair inputs"):
            module.run_campaign(**{**arguments, "after": "different"})
        assert len(evaluations) == 3

        collision = module.run_campaign(
            **{
                **arguments,
                "campaign_id": "negative-control-collision",
                "after": "broken__ariadne_negative__",
            }
        )
        assert collision["outcome"] == "nominated"
        assert collision["selected_variant_id"] == "repair"
        assert [trial["status"] for trial in collision["trials"]] == [
            "failed",
            "failed",
            "passed",
        ]
        assert [passed for _attempt, passed in evaluations[-3:]] == [
            False,
            False,
            True,
        ]

        before_budget = len(evaluations)
        budget_failure = module.run_campaign(
            **{
                **arguments,
                "campaign_id": "budget-stop",
            }
        )
        assert budget_failure["outcome"] == "failed"
        assert len(budget_failure["trials"]) == 1
        assert budget_failure["trials"][0]["status"] == "failed"
        assert "budget-exhausted" in budget_failure["trials"][0][
            "negative_outcomes"
        ]
        assert len(evaluations) == before_budget + 1

        from daedalus.kernel.offload_lease import (
            ATTEMPT_ENTRYPOINT_ID,
            WaveOffloadLease,
        )
        from daedalus.spine.ledger import SpineLedger

        original_retain_terminal = WaveOffloadLease.retain_terminal_record

        def omit_inner_terminal(self, execution):
            if self.lease.entrypoint_id == ATTEMPT_ENTRYPOINT_ID:
                return None
            return original_retain_terminal(self, execution)

        monkeypatch.setattr(
            WaveOffloadLease,
            "retain_terminal_record",
            omit_inner_terminal,
        )
        missing_retain_arguments = {
            **arguments,
            "campaign_id": "missing-inner-retain-result",
        }
        with pytest.raises(
            AriadneCampaignError,
            match="inner Attempt effect needs reconciliation",
        ):
            module.run_campaign(**missing_retain_arguments)
        monkeypatch.setattr(
            WaveOffloadLease,
            "retain_terminal_record",
            original_retain_terminal,
        )

        spine_path, spine_error = module.resolve_spine_db_path(root)
        assert spine_error is None and spine_path is not None
        spine = SpineLedger(spine_path, read_only=True)
        try:
            retained_rows = spine.intents_by_effect_key(
                "campaign:missing-inner-retain-result",
                kind="campaign.lifecycle",
            )
            assert len(retained_rows) == 1
            retained_row = retained_rows[0]
            assert retained_row.state == "COMPLETED"
            missing_receipt = load_campaign_receipt(
                retained_store,
                retained_row.result["receipt"],
            )
        finally:
            spine.close()
        assert missing_receipt.outcome == "failed"
        assert len(missing_receipt.trials) == 1
        assert any(
            "inner-terminal-evidence-unavailable" in outcome
            for outcome in missing_receipt.negative_outcomes
        )

        from daedalus.kernel.authorization import NonRuntimeEffectAuthorization

        original_execution_for = WaveOffloadLease.execution_for
        original_begin_effect = NonRuntimeEffectAuthorization.begin_effect
        original_materialize_tree = SourceTreeStore.materialize_tree
        sabotage = {"mode": "missing-subject"}
        inner_begin_calls: list[str] = []
        materialize_calls: list[str] = []

        def sabotaged_execution_for(self, *args, **kwargs):
            issued = original_execution_for(self, *args, **kwargs)
            if self.lease.entrypoint_id == ATTEMPT_ENTRYPOINT_ID:
                if sabotage["mode"] == "missing-subject":
                    kind = "lease-subject"
                    digest = self.evidence_records["lease_subject"]
                    (Path(self.evidence_root) / kind / f"{digest}.json").unlink()
                else:
                    kind = "lease-execution"
                    digest = self.evidence_records[
                        f"lease_execution:{issued.execution_id}"
                    ]
                    (Path(self.evidence_root) / kind / f"{digest}.json").write_bytes(
                        b"{}"
                    )
            return issued

        def watched_begin_effect(self, execution):
            if self.lease.entrypoint_id == ATTEMPT_ENTRYPOINT_ID:
                inner_begin_calls.append(execution.execution_id)
            return original_begin_effect(self, execution)

        def watched_materialize(self, *args, **kwargs):
            materialize_calls.append(str(args[1] if len(args) > 1 else "workspace"))
            return original_materialize_tree(self, *args, **kwargs)

        monkeypatch.setattr(
            WaveOffloadLease,
            "execution_for",
            sabotaged_execution_for,
        )
        monkeypatch.setattr(
            NonRuntimeEffectAuthorization,
            "begin_effect",
            watched_begin_effect,
        )
        monkeypatch.setattr(
            SourceTreeStore,
            "materialize_tree",
            watched_materialize,
        )
        for mode, suffix in (
            ("missing-subject", "missing"),
            ("corrupt-execution", "corrupt"),
        ):
            sabotage["mode"] = mode
            inner_begin_calls.clear()
            materialize_calls.clear()
            with pytest.raises(
                AriadneCampaignError,
                match=(
                    "inner attempt effect evidence is unavailable or invalid "
                    "before commit"
                ),
            ):
                module.run_campaign(
                    **{
                        **arguments,
                        "campaign_id": f"inner-start-{suffix}",
                    }
                )
            assert inner_begin_calls == []
            assert materialize_calls == []
        monkeypatch.setattr(
            WaveOffloadLease,
            "execution_for",
            original_execution_for,
        )
        monkeypatch.setattr(
            NonRuntimeEffectAuthorization,
            "begin_effect",
            original_begin_effect,
        )
        monkeypatch.setattr(
            SourceTreeStore,
            "materialize_tree",
            original_materialize_tree,
        )

        original_settle = module._settle_committed_outer_effect
        monkeypatch.setattr(
            module,
            "_settle_committed_outer_effect",
            lambda *_args, **_kwargs: False,
        )
        debt_arguments = {
            **arguments,
            "campaign_id": "persistent-outer-debt",
        }
        with pytest.raises(
            AriadneCampaignError,
            match="outer effect needs ledger/evidence reconciliation",
        ):
            module.run_campaign(**debt_arguments)
        monkeypatch.setattr(
            module,
            "_settle_committed_outer_effect",
            original_settle,
        )
        with pytest.raises(
            AriadneCampaignError,
            match="bound terminal evidence is missing or ambiguous",
        ):
            module.run_campaign(**debt_arguments)

        nomination_sha = str(first["nomination_receipt_sha256"])
        nomination_path = (
            switch_path.parent
            / "ariadne"
            / "source-cas"
            / "objects"
            / nomination_sha[:2]
            / nomination_sha[2:]
        )
        nomination_path.unlink()
        with pytest.raises(
            AriadneCampaignError,
            match="invalid persisted NominationReceipt",
        ):
            module.run_campaign(**arguments)
    finally:
        switch.clear()


def test_scoped_tree_contains_only_target_and_preserves_crlf(tmp_path) -> None:
    payload = b"broken\r\nvalue\r\n"
    store = SourceTreeStore(tmp_path / "cas")
    tree = _store_scoped_tree(
        store, payload=payload, relative="nested/sample.txt", tree_id="scoped",
        source_revision=REV, created_at="2026-09-04T10:00:00+00:00",
        trace_id="scoped", origin="ariadne.test.scoped",
    )
    assert [entry.path for entry in tree.manifest.entries] == ["nested/sample.txt"]
    destination = tmp_path / "materialized"
    store.materialize_tree(tree.ref, destination)
    assert (destination / "nested" / "sample.txt").read_bytes() == payload


def test_post_effect_setup_failure_terminalizes_outer_effect_and_releases_lock(
    tmp_path, monkeypatch
) -> None:
    import daedalus.ariadne.campaign as module

    events = []

    class Authorization:
        def begin_effect(self, _execution):
            return SimpleNamespace(execute=True, receipt="started")

        def finish_effect(self, _receipt, *, outcome, output_digests):
            events.append(("finish", outcome, tuple(output_digests)))

    class Granted:
        authorization = Authorization()
        policy_decision = SimpleNamespace(digest="a" * 64)

        def execution_for(self, *_args, **_kwargs):
            return "execution"

        def retain_terminal_record(self, _execution):
            events.append(("retained",))

    class Switch:
        path = tmp_path / "killswitch"

        def __init__(self, **_kwargs):
            pass

        def read_state(self):
            return SimpleNamespace(running=True)

    class Lock:
        def __init__(self, *_args, **_kwargs):
            pass

        def __enter__(self):
            events.append(("lock-enter",))
            return self

        def __exit__(self, *_args):
            events.append(("lock-exit",))

    payload = b"broken"
    monkeypatch.setattr(
        module, "_safe_target",
        lambda _root, _path: ("sample.txt", SimpleNamespace(
            source=payload, source_sha256=canonical_sha({"payload": "broken"}),
        )),
    )
    monkeypatch.setattr(
        module, "verify_repository_head_revision",
        lambda *_args: SimpleNamespace(to_dict=lambda: {"head": "a" * 40}),
    )
    monkeypatch.setattr(module, "resolve_spine_db_path", lambda _root: (tmp_path / "spine.db", None))
    monkeypatch.setattr(module, "lookup_campaign_read_only", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(module, "KillSwitch", Switch)
    monkeypatch.setattr(module, "acquire_effect_lease", lambda *_args, **_kwargs: Granted())
    monkeypatch.setattr(module, "_outer_effect_binding", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(module, "ExclusiveFileLock", Lock)
    monkeypatch.setattr(module, "SourceTreeStore", lambda _path: (_ for _ in ()).throw(OSError("CAS unavailable")))

    with pytest.raises(OSError, match="CAS unavailable"):
        module.run_campaign(
            repo_root=tmp_path, source_revision="a" * 40, campaign_id="setup-fail",
            target_path="sample.txt", before="broken", after="fixed",
        )
    assert ("finish", "FAILED", ()) in events
    assert ("lock-exit",) in events


def test_post_commit_outer_reconciliation_never_marks_effect_failed() -> None:
    from daedalus.ariadne.campaign import _settle_committed_outer_effect

    outcomes = []

    class Authorization:
        calls = 0

        def finish_effect(self, _receipt, *, outcome, output_digests):
            outcomes.append((outcome, tuple(output_digests)))
            self.calls += 1
            if self.calls == 1:
                raise OSError("transient terminal write fault")

    class Granted:
        authorization = Authorization()

        def retain_terminal_record(self, _execution):
            outcomes.append(("retained", ()))
            return {"record_sha256": "b" * 64}

    settled = _settle_committed_outer_effect(
        Granted(), SimpleNamespace(receipt="start"), "execution", "a" * 64
    )
    assert settled is True
    assert outcomes == [
        ("COMPLETED", ("a" * 64,)),
        ("COMPLETED", ("a" * 64,)),
        ("retained", ()),
    ]
    assert all(outcome != "FAILED" for outcome, _digests in outcomes)


def test_post_commit_outer_settlement_requires_retained_terminal_evidence() -> None:
    from daedalus.ariadne.campaign import _settle_committed_outer_effect

    class Authorization:
        @staticmethod
        def finish_effect(_receipt, *, outcome, output_digests):
            assert outcome == "COMPLETED"
            assert tuple(output_digests) == ("a" * 64,)

    class Granted:
        authorization = Authorization()

        @staticmethod
        def retain_terminal_record(_execution):
            return None

    assert not _settle_committed_outer_effect(
        Granted(), SimpleNamespace(receipt="start"), "execution", "a" * 64
    )


def test_ariadne_runtime_has_no_promotion_capability() -> None:
    import daedalus.ariadne.campaign as campaign

    names = set(campaign.__dict__)
    assert not ({"OwnerApproval", "PromotionReceipt", "authorize_promotion"} & names)


def test_real_frozen_evaluator_reaches_nomination_without_gate_fakes(
    tmp_path, monkeypatch
):
    """The live path, unfaked: real Git HEAD, real containment, real evaluator.

    Every other nomination test replaces ``command_gate`` with a test double.
    That double hid a host-level defect: on Windows the venv ``python.exe``
    launcher stub printed ``warning: Making stdin inheritable failed`` into
    the contained gate's merged output, so the exact one-line JSON contract
    of the frozen evaluator never parsed and no campaign could nominate.
    """
    import subprocess

    import daedalus.ariadne.campaign as module
    from daedalus.spine.killswitch import KillSwitch

    root = tmp_path / "repo"
    root.mkdir()

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()

    # Ambient Git configuration, templates and hooks are not part of the
    # frozen protocol: scrub them so a global core.hooksPath cannot execute
    # during the seed commit (council finding, 2026-09-05).
    (tmp_path / "empty-git-template").mkdir()
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_TEMPLATE_DIR", str(tmp_path / "empty-git-template"))
    git("init", "-q", "-b", "main")
    git("config", "user.email", "ariadne@example.invalid")
    git("config", "user.name", "Ariadne Test")
    (root / "sample.txt").write_text("broken\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "seed")
    head = git("rev-parse", "HEAD")

    switch_path = tmp_path / "control" / "killswitch"
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(switch_path))
    switch = KillSwitch(repo_root=root)
    assert switch.arm(note="real frozen evaluator integration test").running
    resolutions: list[str] = []
    real_resolver = module._evaluator_interpreter

    def counted_resolver() -> str:
        resolutions.append(real_resolver())
        return resolutions[-1]

    monkeypatch.setattr(module, "_evaluator_interpreter", counted_resolver)
    try:
        result = module.run_campaign(
            repo_root=root,
            source_revision=head,
            campaign_id="real-evaluator",
            target_path="sample.txt",
            before="broken",
            after="fixed",
            timeout_s=30,
        )
    finally:
        switch.stop()

    trials = result["trials"]
    assert [list(trial["blockers"]) for trial in trials] == [
        ["exact-match-failed"], ["exact-match-failed"], [],
    ], trials
    assert [trial["status"] for trial in trials] == ["failed", "failed", "passed"]
    assert result["outcome"] == "nominated"
    assert (root / "sample.txt").read_text(encoding="utf-8") == "broken\n"
    # One interpreter per campaign, and its identity never carries the
    # user profile path into the retained receipt.
    assert len(resolutions) == 1, resolutions
    assert os.path.expanduser("~").lower() not in json.dumps(result).lower()



@pytest.mark.parametrize(
    ("shape", "error", "fragment"),
    [
        ("short", AriadneCampaignError, "40-hex"),
        ("uppercase", AriadneCampaignError, "40-hex"),
        ("branch-name", AriadneCampaignError, "40-hex"),
        ("other-commit", AriadneConflictError, "HEAD"),
    ],
)
def test_source_revision_is_checked_against_the_real_git_head(
    tmp_path, monkeypatch, shape, error, fragment
):
    """No fake HEAD verifier: the 40-hex shape guard and the live HEAD binding.

    Every other HEAD test monkeypatches ``verify_repository_head_revision``,
    which let a mutant that deleted the shape guard survive (Odysseus,
    2026-09-05). This one drives the real repository and asserts that the
    refusal leaves no control state behind.
    """
    import subprocess

    root = tmp_path / "repo"
    root.mkdir()
    (tmp_path / "empty-git-template").mkdir()
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_TEMPLATE_DIR", str(tmp_path / "empty-git-template"))
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "control" / "killswitch"))

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "ariadne@example.invalid")
    git("config", "user.name", "Ariadne Test")
    (root / "sample.txt").write_text("broken\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-q", "-m", "seed")
    head = git("rev-parse", "HEAD")
    revision = {
        "short": head[:7],
        "uppercase": head.upper(),
        "branch-name": "main",
        "other-commit": ("a" * 40) if head != "a" * 40 else ("b" * 40),
    }[shape]

    with pytest.raises(error, match=fragment):
        run_campaign(
            repo_root=root,
            source_revision=revision,
            campaign_id="head-guard",
            target_path="sample.txt",
            before="broken",
            after="fixed",
            timeout_s=5,
        )
    assert not (tmp_path / "control").exists()
    assert (root / "sample.txt").read_text(encoding="utf-8") == "broken\n"


def test_first_call_returns_the_retained_failed_receipt_for_an_evaluator_contract_violation(
    tmp_path, monkeypatch
):
    """G1-ARIADNE-04: a domain failure is a retained negative outcome, not an error.

    Before this packet the first call re-raised the arm failure after the
    failed receipt had already been committed, so an HTTP caller saw a bare
    400 string and the canonical receipt only on the replay (Odysseus finding
    on G1-ARIADNE-02). Foreign crashes keep raising (see the RuntimeError
    case in test_real_outer_leases_allow_exact_campaign_replay).
    """
    import hashlib as _hashlib

    import daedalus.ariadne.campaign as module
    from daedalus.spine.killswitch import KillSwitch

    root = tmp_path / "repo"
    root.mkdir()
    (root / "sample.txt").write_text("broken\n", encoding="utf-8")
    switch_path = tmp_path / "control" / "killswitch"
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(switch_path))
    monkeypatch.setattr(
        module,
        "verify_repository_head_revision",
        lambda *_args: SimpleNamespace(to_dict=lambda: {"head": REV}),
    )

    class _Contained:
        @staticmethod
        def summary() -> dict[str, object]:
            return {
                "requested": True,
                "executes_candidate": True,
                "contained": True,
                "platform": "test",
                "mechanism": "polluted-evaluator-test-double",
                "inherited_handle_count": 0,
            }

    evaluations: list[str] = []

    def polluted_command_gate(argv, **_kwargs):
        expected_sha256 = str(argv[-1])

        def evaluate(context):
            payload = (context.worktree / "sample.txt").read_bytes()
            observed = _hashlib.sha256(payload).hexdigest()
            # The exact shape of the measured Windows defect: a launcher
            # warning ahead of the one canonical JSON line.
            output = "warning: Making stdin inheritable failed\n" + canonical_json({
                "expected_sha256": expected_sha256,
                "observed_sha256": observed,
                "passed": observed == expected_sha256,
            }) + "\n"
            evaluations.append(context.task.task_id)
            return SimpleNamespace(
                passed=observed == expected_sha256,
                returncode=0 if observed == expected_sha256 else 1,
                output=output,
                output_sha256=_hashlib.sha256(output.encode("ascii")).hexdigest(),
                duration_s=0.001,
                containment=_Contained(),
            )

        return evaluate

    monkeypatch.setattr(module, "command_gate", polluted_command_gate)
    switch = KillSwitch(repo_root=root)
    assert switch.arm(note="failed receipt first call").running
    arguments = {
        "repo_root": root,
        "source_revision": REV,
        "campaign_id": "failed-first-call",
        "target_path": "sample.txt",
        "before": "broken",
        "after": "fixed",
        "timeout_s": 5,
    }
    try:
        first = module.run_campaign(**arguments)
        second = module.run_campaign(**arguments)
    finally:
        switch.stop()

    assert first["outcome"] == "failed"
    assert first["execution_order"] == [0]
    assert first["selected_seed"] is None and first["candidate_tree_sha256"] is None
    assert any("frozen evaluator output is invalid" in b for b in first["blockers"]), first["blockers"]
    # The faulted baseline Attempt is retained with the "error" trial status;
    # the campaign outcome is "failed".
    assert [trial["status"] for trial in first["trials"]] == ["error"]
    assert evaluations == ["failed-first-call-baseline"], evaluations
    # The replay is the same canonical receipt and executes nothing.
    assert second == first
    assert (root / "sample.txt").read_text(encoding="utf-8") == "broken\n"


# --------------------------------------------------------------------------
# G1-ARIADNE-05: the campaign base is a working-tree base and the receipt says so
# --------------------------------------------------------------------------

_BASE_BINDING_SCHEMA = "daedalus-ariadne-base-tree-binding/1"


def _git_repo(tmp_path, monkeypatch, *, content: bytes = b"broken\n", attributes: str | None = None):
    """A real repository with one committed target; Git config scrubbed."""
    import subprocess

    root = tmp_path / "repo"
    root.mkdir()
    (tmp_path / "empty-git-template").mkdir(exist_ok=True)
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_TEMPLATE_DIR", str(tmp_path / "empty-git-template"))
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "control" / "killswitch"))

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-q", "-b", "main")
    git("config", "user.email", "ariadne@example.invalid")
    git("config", "user.name", "Ariadne Test")
    if attributes is not None:
        (root / ".gitattributes").write_text(attributes, encoding="ascii")
    (root / "sample.txt").write_bytes(content)
    git("add", "-A")
    git("commit", "-q", "-m", "seed")
    return root, git


def _passing_fake_gate(module, monkeypatch):
    """A deterministic exact-match gate double; no subprocess, no containment."""
    import hashlib as _hashlib

    class _Contained:
        @staticmethod
        def summary() -> dict[str, object]:
            return {
                "requested": True, "executes_candidate": True, "contained": True,
                "platform": "test", "mechanism": "working-tree-base-test-double",
                "inherited_handle_count": 0,
            }

    def fake_command_gate(argv, **_kwargs):
        expected_sha256 = str(argv[-1])
        target = str(argv[-2])  # the frozen evaluator argv ends in (relative, expected_sha)

        def evaluate(context):
            payload = (context.worktree / target).read_bytes()
            observed = _hashlib.sha256(payload).hexdigest()
            passed = observed == expected_sha256
            output = canonical_json({
                "expected_sha256": expected_sha256,
                "observed_sha256": observed,
                "passed": passed,
            }) + "\n"
            return SimpleNamespace(
                passed=passed, returncode=0 if passed else 1, output=output,
                output_sha256=_hashlib.sha256(output.encode("ascii")).hexdigest(),
                duration_s=0.001, containment=_Contained(),
            )

        return evaluate

    monkeypatch.setattr(module, "command_gate", fake_command_gate)


def _run(module, root, head, campaign_id, *, before="broken", after="fixed"):
    from daedalus.spine.killswitch import KillSwitch

    switch = KillSwitch(repo_root=root)
    # force=True: a previous run of this helper stopped the switch deliberately.
    assert switch.arm(force=True, note="working-tree base test").running
    try:
        return module.run_campaign(
            repo_root=root, source_revision=head, campaign_id=campaign_id,
            target_path="sample.txt", before=before, after=after, timeout_s=5,
        )
    finally:
        switch.stop()


def _base_binding(tmp_path, receipt: dict) -> dict:
    from daedalus.kernel.artifacts import ArtifactRef

    store = SourceTreeStore.open_existing(tmp_path / "control" / "ariadne" / "source-cas")
    found = []
    for digest in receipt["provenance"]["input_digests"]:
        try:
            payload = store.read_bytes(ArtifactRef.from_sha256(digest), max_bytes=1 << 16)
            value = json.loads(payload.decode("ascii"))
        except Exception:
            continue
        if isinstance(value, dict) and value.get("schema") == _BASE_BINDING_SCHEMA:
            found.append(value)
    assert len(found) == 1, found
    return found[0]


def test_receipt_binds_the_working_tree_base_honestly_on_a_clean_commit(tmp_path, monkeypatch):
    """The base bytes are content-addressed; the receipt says they came from the working tree."""
    import daedalus.ariadne.campaign as module

    root, git = _git_repo(tmp_path, monkeypatch)
    head = git("rev-parse", "HEAD")
    _passing_fake_gate(module, monkeypatch)

    receipt = _run(module, root, head, "wt-clean")

    assert receipt["outcome"] == "nominated"
    binding = _base_binding(tmp_path, receipt)
    assert binding == {
        "schema": _BASE_BINDING_SCHEMA,
        "campaign_id": "wt-clean",
        "source_revision": head,
        "target_path": "sample.txt",
        "base_file_sha256": hashlib.sha256(b"broken\n").hexdigest(),
        "base_source": "working-tree",
        "head_content_verified": False,
    }
    assert "working-tree" in json.dumps(receipt), "the receipt must name the working tree as base origin"


def test_dirty_and_untracked_targets_run_and_are_bound_to_their_working_bytes(tmp_path, monkeypatch):
    """No cleanliness refusal (git line-ending filters would make raw compares lie); the binding is honest instead."""
    import daedalus.ariadne.campaign as module

    root, git = _git_repo(tmp_path, monkeypatch)
    head = git("rev-parse", "HEAD")
    _passing_fake_gate(module, monkeypatch)

    (root / "sample.txt").write_bytes(b"still broken\n")  # modified after the commit
    dirty = _run(module, root, head, "wt-dirty", before="still broken", after="fixed")
    assert dirty["outcome"] == "nominated"
    assert _base_binding(tmp_path, dirty)["base_file_sha256"] == hashlib.sha256(b"still broken\n").hexdigest()

    (root / "sample.txt").write_bytes(b"broken\n")
    (root / "fresh.txt").write_bytes(b"broken\n")  # untracked target
    from daedalus.spine.killswitch import KillSwitch

    switch = KillSwitch(repo_root=root)
    assert switch.arm(force=True, note="untracked").running
    try:
        untracked = module.run_campaign(
            repo_root=root, source_revision=head, campaign_id="wt-untracked",
            target_path="fresh.txt", before="broken", after="fixed", timeout_s=5,
        )
    finally:
        switch.stop()
    assert untracked["outcome"] == "nominated"
    assert _base_binding(tmp_path, untracked)["target_path"] == "fresh.txt"


def test_base_binding_is_independent_of_the_git_index(tmp_path, monkeypatch):
    """Staging the same bytes changes nothing the receipt records (determinism under replay)."""
    import daedalus.ariadne.campaign as module

    root, git = _git_repo(tmp_path, monkeypatch)
    head = git("rev-parse", "HEAD")
    _passing_fake_gate(module, monkeypatch)
    (root / "sample.txt").write_bytes(b"still broken\n")

    unstaged = _run(module, root, head, "wt-index", before="still broken", after="fixed")
    git("add", "sample.txt")  # staged without a commit: HEAD unchanged
    replay = _run(module, root, head, "wt-index", before="still broken", after="fixed")

    assert replay == unstaged
    binding = _base_binding(tmp_path, replay)
    assert set(binding) == {
        "schema", "campaign_id", "source_revision", "target_path",
        "base_file_sha256", "base_source", "head_content_verified",
    }


def test_crlf_text_auto_target_is_not_refused(tmp_path, monkeypatch):
    """A raw byte compare against HEAD would call this dirty; git calls it clean; we refuse nothing."""
    import daedalus.ariadne.campaign as module

    root, git = _git_repo(tmp_path, monkeypatch, content=b"broken\r\n", attributes="* text=auto\n")
    head = git("rev-parse", "HEAD")
    _passing_fake_gate(module, monkeypatch)

    receipt = _run(module, root, head, "wt-crlf")
    assert receipt["outcome"] == "nominated"
    assert _base_binding(tmp_path, receipt)["base_file_sha256"] == hashlib.sha256(b"broken\r\n").hexdigest()


def test_head_moving_while_the_target_is_read_is_a_conflict(tmp_path, monkeypatch):
    """The race Momus named: verify HEAD, read target, re-verify HEAD identical."""
    import daedalus.ariadne.campaign as module

    root, git = _git_repo(tmp_path, monkeypatch)
    head = git("rev-parse", "HEAD")
    _passing_fake_gate(module, monkeypatch)
    real_safe_target = module._safe_target

    def moving_head_target(repo_root, value):
        snapshot = real_safe_target(repo_root, value)
        git("commit", "-q", "--allow-empty", "-m", "moved during read")
        return snapshot

    monkeypatch.setattr(module, "_safe_target", moving_head_target)
    with pytest.raises(AriadneConflictError, match="source_revision"):
        _run(module, root, head, "wt-race")
    assert not (tmp_path / "control" / "ariadne").exists(), "a refused start leaves no campaign state"


# --------------------------------------------------------------------------
# G1-ARIADNE-06: refusals that name their cause and the remedy
# --------------------------------------------------------------------------


def test_linked_worktree_subject_is_a_named_actionable_refusal(tmp_path, monkeypatch):
    """A linked worktree (.git is a gitdir pointer file) is a deliberately
    unsupported subject (tests/test_git_is_a_process_launcher.py measured the
    pointer-rewrite attack; tests/gates/test_repository_head_revision.py pins the
    gate refusal). The facade names the layout and the remedy, creates no state."""
    import daedalus.ariadne.campaign as module

    root = tmp_path / "wt"
    root.mkdir()
    (root / ".git").write_text("gitdir: ../main/.git/worktrees/wt\n", encoding="utf-8")
    (root / "sample.txt").write_text("broken\n", encoding="utf-8")
    monkeypatch.setenv("DAEDALUS_KILLSWITCH", str(tmp_path / "control" / "killswitch"))

    with pytest.raises(AriadneRequestError) as caught:
        run_campaign(
            repo_root=root, source_revision=REV, campaign_id="wt-subject",
            target_path="sample.txt", before="broken", after="fixed", timeout_s=5,
        )
    message = str(caught.value)
    assert "linked git worktree" in message and "clone" in message, message
    assert "must be a real directory" in message, "the gate refusal stays visible"
    assert not (tmp_path / "control").exists()


def test_partial_campaign_state_refusal_names_the_spine_cas_split(tmp_path):
    """A spine database without its source-tree CAS refuses fail-closed and says which half is missing."""
    spine = tmp_path / "runs" / "spine" / "spine.sqlite3"
    spine.parent.mkdir(parents=True)
    spine.write_bytes(b"not even sqlite")
    with pytest.raises(CampaignLifecycleError) as caught:
        lookup_campaign_read_only(
            str(spine), str(tmp_path / "control" / "ariadne" / "source-cas"),
            "any-id", expected_operation_sha256="0" * 64,
        )
    message = str(caught.value)
    assert message.startswith("partial persisted Campaign state is unsafe"), message
    assert "source-tree CAS is missing" in message and "control root" in message, message
