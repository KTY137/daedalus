from __future__ import annotations

import inspect

import daedalus.kairos.gated_writes as gated_writes


def test_fault_state_is_initialized_before_the_live_mutation_block() -> None:
    source = inspect.getsource(gated_writes.promote_candidates)
    report_at = source.index("report: dict[str, Any] | None = None")
    branch_at = source.index("integration_branch: str | None = None")
    revision_at = source.index("integration_revision: str | None = None")
    mutation_flag_at = source.index("mutation_entered = False")
    lock_at = source.index("with _PromotionLock(")
    enter_at = source.index("mutation_entered = True")
    mutate_at = source.index("report = _promote_locked(")
    assert (
        report_at
        < branch_at
        < revision_at
        < mutation_flag_at
        < lock_at
        < enter_at
        < mutate_at
    )


def test_known_errors_after_mutation_entry_are_faults_not_refusals() -> None:
    source = inspect.getsource(gated_writes.promote_candidates)
    for marker in (
        "except PromotionUnavailable as exc:",
        "except PromotionAuthorizationError as exc:",
    ):
        start = source.index(marker)
        end = source.index("\n    except ", start + len(marker))
        handler = source[start:end]
        assert "if mutation_entered:" in handler
        assert handler.index("_complete_fault(") < handler.index("_complete_refusal(")


def test_generic_post_mutation_fault_receives_every_known_identity() -> None:
    source = inspect.getsource(gated_writes.promote_candidates)
    mutate_at = source.index("report = _promote_locked(")
    generic_fault_at = source.index(
        "except Exception as exc:  # noqa: BLE001 - retain explicit terminal fault",
        mutate_at,
    )
    next_completion_at = source.index(
        "\n    try:\n        primary_after = fingerprint_primary_checkout(root)",
        generic_fault_at,
    )
    fault_slice = source[generic_fault_at:next_completion_at]
    assert "report=report" in fault_slice
    assert "integration_branch=integration_branch" in fault_slice
    assert "integration_revision=integration_revision" in fault_slice


def test_branch_is_retained_before_revision_lookup() -> None:
    source = inspect.getsource(gated_writes.promote_candidates)
    report_at = source.index("report = _promote_locked(")
    observed_at = source.index(
        'observed_branch = report.get("integration_branch")',
        report_at,
    )
    retained_at = source.index("integration_branch = observed_branch", observed_at)
    lookup_at = source.index(
        "integration_revision = resolve_live_target_revision(",
        retained_at,
    )
    assert report_at < observed_at < retained_at < lookup_at


def test_fault_terminal_event_does_not_copy_raw_untrusted_report() -> None:
    source = inspect.getsource(gated_writes._complete_fault)
    assert "fault_report = {" in source
    assert '"observed_report": report is not None' in source
    assert "dict(report or {})" not in source
    assert "fault_report.update(report" not in source
