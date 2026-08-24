"""Codex point 1: the report path RUNS the six verifiers on raw inputs.

Before this, the composition accepted stage reports somebody else had built and
only checked their type and their binding.  Those checks were real, but the
running of the verifier was another caller's business.  Here the only way a
stage report exists on the report path is that ``_run_stage_verifiers`` invoked
that stage's verifier, in this call, over raw material.

Two AST pins hold the shape: the reporter calls the composition with the
projection alone and no keyword at all, and no function on the report path
declares a parameter that could carry a stage report.
"""
from __future__ import annotations

import ast
import hashlib
import importlib.util
import inspect
import pathlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import daedalus.gates.repository_write_classification as classification
import daedalus.gates.report_v3 as report_v3
import daedalus.gates.repository_write_effect_lease as effect_lease_module
import daedalus.gates.repository_write_evidence_materialization as materialization_module
import daedalus.gates.repository_write_evidence_origin as origin_module
import daedalus.gates.repository_write_guard_structure as guard_module
import daedalus.gates.repository_write_runtime_conformance as conformance_module
import daedalus.gates.repository_write_source_anchor_semantics as anchor_module
from daedalus.gates.repository_write_classification import (
    _STAGE_REPORT_TYPES,
    _STAGE_VERIFIERS,
    AuthenticationStage,
    RepositoryWriteAuthenticationInputs,
    RepositoryWriteClassificationError,
    authenticate_repository_write_surfaces,
    stage_verifier,
)


def _load(name: str, relative: str):
    path = pathlib.Path(__file__).resolve().parents[1] / relative
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_auth = _load(
    "_b5_authentication_fixtures",
    "gates/test_repository_write_evidence_authentication.py",
)

_STAGE_MODULES = {
    AuthenticationStage.MATERIALIZATION: materialization_module,
    AuthenticationStage.ORIGIN: origin_module,
    AuthenticationStage.ANCHOR: anchor_module,
    AuthenticationStage.GUARD: guard_module,
    AuthenticationStage.CONFORMITY: conformance_module,
    AuthenticationStage.LEASE: effect_lease_module,
}


def _inputs(revision: str) -> RepositoryWriteAuthenticationInputs:
    """Raw material only.  There is no stage report among these fields."""

    return RepositoryWriteAuthenticationInputs(
        blobs={},
        origin_attestation=SimpleNamespace(digest="e" * 64),
        guard_manifest=SimpleNamespace(digest="f" * 64),
        runtime_subjects={},
        runtime_trust_ledgers={},
        effect_subjects={},
        collector_keyring={},
        expected_collector_id="collector.1",
        guard_keyring={},
        expected_guard_authority_id="guard-authority.1",
        current_revision=revision,
        now=datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc),
        repository_root=pathlib.Path("."),
    )


def _spy_every_verifier(monkeypatch, returns):
    calls: dict[AuthenticationStage, list[tuple]] = {
        stage: [] for stage in AuthenticationStage
    }
    for stage, module in _STAGE_MODULES.items():
        _module_name, function_name = _STAGE_VERIFIERS[stage]
        assert hasattr(module, function_name)

        def _spy(*args, _stage=stage, **kwargs):
            calls[_stage].append((args, kwargs))
            return returns(_stage)

        monkeypatch.setattr(module, function_name, _spy)
    return calls


def test_every_stage_report_is_built_by_running_that_stage_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each verifier is invoked exactly once, on the raw inputs, per call."""

    surface = _auth._surface()
    row = _auth._retired(surface)
    projection = _auth._report(row)
    inputs = _inputs(projection.source_revision)

    calls = _spy_every_verifier(monkeypatch, lambda stage: SimpleNamespace(stage=stage))

    # The sentinels are not the exact classes the verifiers return, so the
    # composition still refuses them -- but only AFTER every verifier ran.
    with pytest.raises(
        RepositoryWriteClassificationError,
        match="exact typed report",
    ):
        authenticate_repository_write_surfaces(projection, inputs=inputs)

    assert {stage: len(rows) for stage, rows in calls.items()} == {
        stage: 1 for stage in AuthenticationStage
    }
    # Every verifier saw the classification this call built, never one handed
    # in, and saw the raw inputs rather than a finished report.
    for stage in (
        AuthenticationStage.MATERIALIZATION,
        AuthenticationStage.ANCHOR,
        AuthenticationStage.GUARD,
        AuthenticationStage.CONFORMITY,
        AuthenticationStage.LEASE,
    ):
        args, _kwargs = calls[stage][0]
        assert args[0] is projection
        assert args[1] is inputs.blobs
    # Origin consumes the materialization report -- built two lines above, in
    # this call.  It is the sentinel the materialization spy returned, which is
    # the proof it came from here.
    origin_args, origin_kwargs = calls[AuthenticationStage.ORIGIN][0]
    assert origin_args[0] is inputs.origin_attestation
    assert origin_args[1].stage is AuthenticationStage.MATERIALIZATION
    assert origin_kwargs["current_revision"] == projection.source_revision


def test_stage_reports_that_are_correctly_typed_reach_the_conjunction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The happy path: verifiers run, and their real reports are composed."""

    surface = _auth._surface()
    row = _auth._retired(surface)
    projection = _auth._report(row)
    surface_sha256 = _auth.surface_binding_sha256(projection.source_revision, surface)
    materialization = _auth._materialization(projection, row)
    built = {
        AuthenticationStage.MATERIALIZATION: materialization,
        AuthenticationStage.ORIGIN: _auth._origin(projection, materialization),
        AuthenticationStage.ANCHOR: _auth._anchor(projection, materialization, row),
        AuthenticationStage.GUARD: _guard_report(projection, materialization),
        AuthenticationStage.CONFORMITY: _auth._conformity(
            projection, materialization, surface_sha256
        ),
        AuthenticationStage.LEASE: _auth._lease(
            projection,
            materialization,
            surface_sha256,
            runtime_bound=False,
            runtime_id=None,
            execution_id="execution.1",
        ),
    }
    calls = _spy_every_verifier(monkeypatch, built.__getitem__)

    result = authenticate_repository_write_surfaces(
        projection,
        inputs=_inputs(projection.source_revision),
    )

    assert all(len(rows) == 1 for rows in calls.values())
    assert result[surface].authenticated is True

    # And with no inputs there is nothing to run: every stage is absent and
    # nothing authenticates.  That is the reporter's state today.
    bare = authenticate_repository_write_surfaces(projection)
    assert bare[surface].authenticated is False
    assert {verdict for _name, verdict in bare[surface].verdicts} <= {
        classification.STAGE_VERDICT_ABSENT,
        classification.STAGE_VERDICT_NOT_APPLICABLE,
    }


def _guard_report(projection, materialization):
    structure = {
        "surface_sha256": _auth.surface_binding_sha256(
            projection.source_revision, _auth._surface()
        ),
        "locator": "cas:sha256:" + "3" * 64,
        "contract": "containment.attempt",
        "implementation_target": "daedalus.example:write",
        "implementation_sha256": "4" * 64,
        "source_path": "daedalus/example.py",
        "source_size": 128,
        "definition_kind": "function",
        "line": 7,
        "column": 0,
        "end_line": 9,
        "end_column": 4,
    }
    payload = {key: value for key, value in structure.items() if key not in {"surface_sha256", "locator"}}
    record = guard_module.GuardStructureRecord(
        **structure,
        structure_sha256=hashlib.sha256(
            _auth.canonical_json(payload).encode("ascii")
        ).hexdigest(),
    )
    return guard_module.RepositoryWriteGuardStructureReport(
        source_revision=projection.source_revision,
        classification_digest=projection.digest,
        materialization_digest=materialization.digest,
        source_anchor_report_digest="7" * 64,
        origin_attestation_digest="8" * 64,
        guard_manifest_report_digest="9" * 64,
        guard_manifest_digest="a" * 64,
        classification_count=1,
        production_classification_count=1,
        guard_contract_count=1,
        guard_binding_count=1,
        record_set_sha256=hashlib.sha256(
            _auth.canonical_json([record.to_dict()]).encode("ascii")
        ).hexdigest(),
        records=(record,),
    )


# ------------------------------------------------------------------ AST pins


def test_the_reporter_calls_the_composition_with_the_projection_alone() -> None:
    """Pin one: no caller-supplied stage object can reach the report path.

    NARROWED 2026-08-24 (Momus): the original spelling asserted
    ``keywords == []``, which overshot 6be14dff -- the rule bans STAGE
    OBJECTS on the report path, not keywords as such -- and thereby pinned
    the measured broken state in which the reporter could never pass
    ``inputs=`` and ``authenticated_cleared`` was zero by construction
    (LEASED_RUN_CENSUS_DELTA.md). What must stay banned, and stays banned
    below: any keyword that could carry a finished stage report or verdict.
    ``inputs=`` (raw material the verifiers RUN on) is the one permitted
    spelling; Pin Two still refuses stage-report classes on every parameter.
    """

    classifier = inspect.getsource(report_v3._classify_repository_write_surfaces)
    composition = [
        node
        for node in ast.walk(ast.parse(inspect.cleandoc(classifier)))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "authenticate_repository_write_surfaces"
    ]
    assert len(composition) == 1
    banned = {"stage_reports", "stages", "reports", "verdicts", "authentications"}
    passed_keywords = {kw.arg for kw in composition[0].keywords}
    assert not (passed_keywords & banned), passed_keywords
    assert passed_keywords <= {"inputs"}, (
        f"only raw inputs may ride the report path, got {passed_keywords}")
    assert len(composition[0].args) == 1
    # And the public entry has no such keyword to be called with, under any
    # spelling: the parameter was removed, not merely left unused.
    parameters = inspect.signature(authenticate_repository_write_surfaces).parameters
    assert "stage_reports" not in parameters
    assert set(parameters) == {
        "report",
        "inputs",
        "non_runtime_bindings",
        "collector_secrets",
    }


# ``GateReportV3`` is the reporter's own output type and
# ``RepositoryWriteClassificationReport`` is the projection the reporter builds
# from the inventory in the same call.  Neither is a stage report -- the
# assertion below proves that against the stage table rather than asserting it.
_ALLOWED_REPORT_ANNOTATIONS = frozenset(
    {"GateReportV3", "RepositoryWriteClassificationReport"}
)


def _annotation_names(annotation: ast.expr) -> set[str]:
    text = ast.unparse(annotation).strip()
    if text[:1] in {"'", '"'}:
        text = text.strip("'\"")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:  # pragma: no cover - annotations here are all parseable
        return {text}
    names = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }
    names |= {
        node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
    }
    return names


def test_no_function_on_the_report_path_accepts_a_report_typed_parameter() -> None:
    """Pin two: a stage report cannot arrive as an argument anywhere here."""

    stage_report_classes = {class_name for _mod, class_name in _STAGE_REPORT_TYPES.values()}
    assert len(stage_report_classes) == 6
    assert not stage_report_classes & _ALLOWED_REPORT_ANNOTATIONS

    targets = [(report_v3, None), (classification, {"authenticate_repository_write_surfaces"})]
    offenders: list[str] = []
    checked = 0
    for module, only in targets:
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if only is not None and node.name not in only:
                continue
            checked += 1
            arguments = [
                *node.args.posonlyargs,
                *node.args.args,
                *node.args.kwonlyargs,
                node.args.vararg,
                node.args.kwarg,
            ]
            for argument in arguments:
                if argument is None or argument.annotation is None:
                    continue
                names = _annotation_names(argument.annotation)
                if names & stage_report_classes:
                    offenders.append(f"{node.name}({argument.arg}) names a stage report")
                for name in names:
                    if name.endswith("Report") and name not in _ALLOWED_REPORT_ANNOTATIONS:
                        offenders.append(f"{node.name}({argument.arg}): {name}")
    assert checked > 1
    assert offenders == []

    # The raw-input record itself is the other half of the pin: none of its
    # fields may be a stage report either.
    for name, annotation in RepositoryWriteAuthenticationInputs.__annotations__.items():
        assert "Report" not in str(annotation), name


def test_the_stage_verifier_table_names_one_verifier_per_stage() -> None:
    assert set(_STAGE_VERIFIERS) == set(AuthenticationStage)
    for stage in AuthenticationStage:
        assert callable(stage_verifier(stage))
    with pytest.raises(RepositoryWriteClassificationError):
        stage_verifier("materialization")
