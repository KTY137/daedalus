"""An adapter earns the name by producing the same answer as what it adapts.

``docs/IKARUS_ARIADNE_MASTER_PLAN.md`` §9.2 admits an external library "behind
adapters" and demands four things of the adoption: an adapter contract, a
failure mode, a replacement path, and a measured benefit. Three of those are
testable and are tested here. The fourth -- benefit -- is a measurement, not an
assertion, and lives in ``docs/LANGGRAPH_ADAPTER_20260825.md``.

The contract under test is equivalence: for identical inputs the graph engine
and the stdlib engine compose the SAME run brief. That is what makes the graph
an adapter rather than the "parallel control plane" §13 forbids. If this file
goes red because the two engines disagree, the answer is never to relax the
comparison -- it is that one of them has grown a behaviour the other does not
have, which is the exact thing being guarded against.
"""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

# The OWNER. Three tests below monkeypatch ``langgraph_available``; the
# owner's ``build_graph`` resolves that name in the owner's own globals, so
# patching the flat ``daedalus.langgraph_adapter`` facade G1-FLAT-01 left
# behind would have rebound a copy and silently asserted nothing. G1-FLAT-02
# retired that facade.
from daedalus.orchestration import runbook
from daedalus.orchestration import langgraph_adapter

needs_langgraph = pytest.mark.skipif(
    not langgraph_adapter.langgraph_available(),
    reason="optional extra: pip install -e .[orchestration]",
)

FIXED_RUN_ID = "abcdef012345"


class _FixedUUID:
    hex = FIXED_RUN_ID + "deadbeef"


def _normalise(payload: dict) -> dict:
    """Blank the two fields that read a clock, and only those.

    ``state.created_at`` and the timestamp inside the single recorded event are
    the whole difference two engines are allowed to have. Everything else --
    the routed agent, the pruned context, the constraint list, the event kind
    and its payload -- must match exactly.
    """
    out = copy.deepcopy(payload)
    out["state"]["created_at"] = "<clock>"
    for event in out["state"].get("events", []):
        event["time"] = "<clock>"
    return out


@pytest.fixture
def briefs(tmp_path, monkeypatch):
    """Both engines, same run_id, same tmp run directory."""
    monkeypatch.setattr(runbook, "RUN_DIR", tmp_path / "runs")
    monkeypatch.setattr(runbook, "uuid4", lambda: _FixedUUID())
    made = {}
    for engine in ("stdlib", "langgraph"):
        made[engine] = runbook.create_run(
            "add a docstring to the scan panel",
            ["daedalus/router.py"],
            str(tmp_path / "repo"),
            engine=engine,
        )
    return made


# --------------------------------------------------------------- the contract

@needs_langgraph
def test_both_engines_compose_the_identical_brief(briefs):
    stdlib = _normalise(briefs["stdlib"]["payload"])
    graph = _normalise(briefs["langgraph"]["payload"])
    assert graph == stdlib, (
        "the graph and the line disagree about the brief. This is not a "
        "comparison to loosen: one engine has grown behaviour the other does "
        "not have, which is a second orchestration model in the making."
    )


@needs_langgraph
def test_the_agreement_is_not_vacuous(briefs):
    """A comparison of two empty things passes and proves nothing."""
    payload = briefs["langgraph"]["payload"]
    assert payload["task"]["task_id"] == FIXED_RUN_ID
    assert payload["task"]["agent"], "no agent was routed"
    assert len(payload["task"]["constraints"]) == 4
    assert payload["state"]["events"][0]["kind"] == "task_created"
    assert payload["state"]["paths"] == ["daedalus/router.py"]


@needs_langgraph
def test_the_clock_is_the_only_permitted_difference(briefs):
    """Pin what `_normalise` is allowed to hide, so it cannot quietly grow."""
    raw_stdlib = briefs["stdlib"]["payload"]
    raw_graph = briefs["langgraph"]["payload"]
    differing = [
        key for key in raw_stdlib["state"]
        if raw_stdlib["state"][key] != raw_graph["state"][key]
    ]
    assert differing in ([], ["created_at"], ["created_at", "events"], ["events", "created_at"]), (
        f"engines differ in unexpected state keys: {differing}"
    )


# ----------------------------------------------------------- the failure mode

def test_absent_library_leaves_the_stdlib_path_untouched(tmp_path, monkeypatch):
    monkeypatch.setattr(runbook, "RUN_DIR", tmp_path / "runs")
    monkeypatch.setattr(langgraph_adapter, "langgraph_available", lambda: False)
    result = runbook.create_run("anything", [], str(tmp_path))
    assert Path(result["path"]).is_file()
    assert result["payload"]["task"]["agent"]


def test_absent_library_refuses_loudly_rather_than_degrading(tmp_path, monkeypatch):
    """No silent fallback. An engine you cannot name is one you cannot measure."""
    monkeypatch.setattr(runbook, "RUN_DIR", tmp_path / "runs")
    monkeypatch.setattr(langgraph_adapter, "langgraph_available", lambda: False)
    with pytest.raises(langgraph_adapter.LangGraphUnavailable):
        runbook.create_run("anything", [], str(tmp_path), engine="langgraph")
    assert not (tmp_path / "runs").exists(), "a refused engine still wrote a brief"


def test_an_unknown_engine_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(runbook, "RUN_DIR", tmp_path / "runs")
    with pytest.raises(ValueError, match="unknown engine"):
        runbook.create_run("anything", [], str(tmp_path), engine="whatever")


# ------------------------------------------------------- the boundary it keeps

def test_the_graph_writes_nothing(tmp_path, monkeypatch):
    """The single writer is `create_run`. If the graph ever writes, the effect
    boundary has two doors where it registered one."""
    if not langgraph_adapter.langgraph_available():
        pytest.skip("optional extra")
    monkeypatch.setattr(runbook, "RUN_DIR", tmp_path / "runs")
    before = sorted(p.name for p in tmp_path.iterdir())
    payload = langgraph_adapter.run_brief("x", [], str(tmp_path), FIXED_RUN_ID)
    assert payload["task"]["task_id"] == FIXED_RUN_ID
    assert sorted(p.name for p in tmp_path.iterdir()) == before


@needs_langgraph
def test_telemetry_is_pinned_off_not_merely_unset(monkeypatch):
    """langsmith ships a default endpoint at api.smith.langchain.com and is
    enabled by environment variable. Relying on that variable being unset means
    trusting every other process on the machine not to set it."""
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    langgraph_adapter.build_graph()
    assert langgraph_adapter.tracing_is_pinned_off()
    from langsmith import utils as ls_utils

    assert ls_utils.tracing_is_enabled() is False


# --------------------------------------------------------- the replacement path

def test_nothing_imports_langgraph_at_module_scope():
    """The package must still import with zero third-party dependencies. The
    replacement path is 'delete one file'; that is only true while no module
    reaches for the library on the way in."""
    import ast

    offenders = []
    for path in (Path(__file__).resolve().parents[1] / "daedalus").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        for node in tree.body:                      # module scope only
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n.split(".")[0] in {"langgraph", "langchain_core", "langsmith"}
                   for n in names):
                offenders.append(path.name)
    assert offenders == [], offenders


# ---------------------------------------------------- advisory fleet planning

@needs_langgraph
def test_advisory_fleet_capacity_is_one_global_ceiling():
    """Twenty means twenty total, never twenty per project or provider."""
    projects = [
        {"name": "alpha", "objective": "review alpha", "provider": "claude"},
        {"name": "beta", "objective": "review beta", "provider": "codex"},
        {"name": "gamma", "objective": "review gamma", "provider": "claude"},
    ]
    plan = langgraph_adapter.plan_advisory_fleet(
        projects, ["architecture", "tests", "security"], capacity=20
    )

    assert plan["scope"] == "global"
    assert plan["capacity"] == 20
    assert len(plan["slots"]) == 20
    counts = {
        project["name"]: sum(
            slot["project"] == project["name"] for slot in plan["slots"]
        )
        for project in projects
    }
    assert max(counts.values()) - min(counts.values()) <= 1


@needs_langgraph
def test_advisory_fleet_is_deterministic_fair_round_robin():
    projects = [
        {"name": "alpha", "objective": "objective A"},
        {"name": "beta", "objective": "objective B"},
        {"name": "gamma", "objective": "objective C"},
    ]
    roles = ["architect", "tester"]

    first = langgraph_adapter.plan_advisory_fleet(projects, roles, capacity=7)
    second = langgraph_adapter.plan_advisory_fleet(projects, roles, capacity=7)

    assert first == second
    assert [slot["project"] for slot in first["slots"]] == [
        "alpha", "beta", "gamma", "alpha", "beta", "gamma", "alpha"
    ]
    assert [slot["objective"] for slot in first["slots"]] == [
        "objective A", "objective B", "objective C", "objective A",
        "objective B", "objective C", "objective A",
    ]
    assert [slot["role"] for slot in first["slots"]] == [
        "architect", "tester", "architect", "tester", "architect", "tester",
        "architect",
    ]


@needs_langgraph
def test_advisory_fleet_has_unique_slots_and_only_slot_one_is_probe():
    plan = langgraph_adapter.plan_advisory_fleet(
        [{"name": "alpha", "objective": "review"}],
        ["architecture"],
        capacity=20,
    )
    slots = plan["slots"]
    assert [slot["ordinal"] for slot in slots] == list(range(1, 21))
    assert len({slot["slot_id"] for slot in slots}) == 20
    assert [slot["ordinal"] for slot in slots if slot["probe"]] == [1]
    assert all(slot["probe"] is (slot["ordinal"] == 1) for slot in slots)


@needs_langgraph
@pytest.mark.parametrize("capacity", [None, False, True, "20", 1.5, -1, 0, 21])
def test_advisory_fleet_refuses_invalid_capacity(capacity):
    with pytest.raises(ValueError, match="capacity"):
        langgraph_adapter.plan_advisory_fleet(
            [{"name": "alpha", "objective": "review"}],
            ["architecture"],
            capacity=capacity,
        )


@needs_langgraph
@pytest.mark.parametrize("projects", [None, []])
def test_advisory_fleet_refuses_missing_or_empty_projects(projects):
    with pytest.raises(ValueError, match="projects"):
        langgraph_adapter.plan_advisory_fleet(projects, ["architecture"])


@needs_langgraph
@pytest.mark.parametrize("roles", [None, [], [""], [42]])
def test_advisory_fleet_refuses_missing_or_invalid_roles(roles):
    with pytest.raises(ValueError, match="role"):
        langgraph_adapter.plan_advisory_fleet(
            [{"name": "alpha", "objective": "review"}], roles
        )


@needs_langgraph
def test_advisory_fleet_refuses_duplicate_project_names():
    projects = [
        {"name": "Alpha", "objective": "first"},
        {"name": " alpha ", "objective": "second"},
    ]
    with pytest.raises(ValueError, match="duplicate project name"):
        langgraph_adapter.plan_advisory_fleet(projects, ["architecture"])


@needs_langgraph
def test_advisory_fleet_refuses_duplicate_roles():
    with pytest.raises(ValueError, match="duplicate role"):
        langgraph_adapter.plan_advisory_fleet(
            [{"name": "alpha", "objective": "review"}],
            ["Architecture", " architecture "],
        )


@needs_langgraph
@pytest.mark.parametrize(
    "projects",
    [
        ["alpha"],
        [{"objective": "review"}],
        [{"name": "alpha"}],
        [{"name": " ", "objective": "review"}],
        [{"name": "alpha", "objective": " "}],
    ],
)
def test_advisory_fleet_refuses_malformed_project_entries(projects):
    with pytest.raises(ValueError, match="project"):
        langgraph_adapter.plan_advisory_fleet(projects, ["architecture"])


@needs_langgraph
def test_advisory_fleet_is_pure_and_does_not_mutate_inputs(tmp_path):
    projects = [{"name": "alpha", "objective": "review"}]
    roles = ["architecture", "tests"]
    before_projects = copy.deepcopy(projects)
    before_roles = list(roles)
    before_files = list(tmp_path.iterdir())

    plan = langgraph_adapter.plan_advisory_fleet(projects, roles, capacity=2)

    assert projects == before_projects
    assert roles == before_roles
    assert list(tmp_path.iterdir()) == before_files
    plan["slots"][0]["role"] = "mutated by caller"
    replay = langgraph_adapter.plan_advisory_fleet(projects, roles, capacity=2)
    assert replay["slots"][0]["role"] == "architecture"


def test_advisory_fleet_refuses_when_optional_library_is_absent(monkeypatch):
    monkeypatch.setattr(langgraph_adapter, "langgraph_available", lambda: False)
    with pytest.raises(langgraph_adapter.LangGraphUnavailable):
        langgraph_adapter.plan_advisory_fleet(
            [{"name": "alpha", "objective": "review"}], ["architecture"]
        )
