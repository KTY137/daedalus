"""The run brief, built as a graph instead of as a line.

WHAT THIS IS. ``daedalus.runbook.create_run`` composes a run brief in four
steps: route the objective to one agent, build the pruned ``AgentTask``, open a
``RunState``, record the ``task_created`` event. That is a straight line, and it
is written as one. This module expresses the *same four steps* as a LangGraph
graph over the *same state keys*, so the two can be compared byte for byte.

WHAT IT IS NOT, and this is the load-bearing part. It is not a second
orchestration model. ``docs/IKARUS_ARIADNE_MASTER_PLAN.md`` §13 forbids "a
parallel control plane", and §9.2 admits an external library only "behind
adapters", with "an adapter contract, failure mode, replacement path, and
measured benefit". So:

* the graph is **pure** -- it computes the payload and writes nothing. The one
  writer stays ``create_run``, which is the only place the effect boundary
  knows about;
* the graph carries **no state of its own**. Its schema is ``RunState``'s
  fields plus the task, nothing invented;
* it is **opt-in**. ``create_run`` defaults to the stdlib path and takes
  ``engine="langgraph"`` only when a caller asks for it by name;
* nothing under ``daedalus/`` imports this module at module scope, so the
  package still imports with zero third-party dependencies installed.

THE CONTRACT. For identical inputs -- including ``run_id``, which the caller
supplies rather than the graph minting -- ``run_brief(...)`` returns a payload
equal to the stdlib one, except for the two fields that read a clock
(``state.created_at`` and the timestamp inside ``state.events[0]``).
``tests/test_langgraph_adapter.py`` asserts exactly that, and asserts it over
the real router rather than a stub.

FAILURE MODE. LangGraph absent -> :class:`LangGraphUnavailable`, and the stdlib
path is untouched and still correct; a caller that did not ask for the graph
never learns the library is missing. The graph raising mid-run cannot leave a
half-written brief, because the graph does not write. There is no fallback
*inside* this module: silently degrading from the graph to the line would make
"which engine produced this?" unanswerable, and an engine you cannot name is
not an engine you can measure.

REPLACEMENT PATH. Delete this file and the ``orchestration`` extra in
``pyproject.toml``. Nothing else changes: ``create_run``'s default argument
already is the stdlib path, and its ``engine`` parameter can go with it. That
is deliberate -- the cost of removing a dependency should be one deletion, and
it is measurable today rather than promised.

EGRESS. Installing LangGraph pulls ``langsmith``, whose default endpoint is
``https://api.smith.langchain.com``. Tracing is off unless an environment
variable turns it on -- which means an environment variable set anywhere on the
machine, for any reason, would turn it on here too. This module therefore pins
it off explicitly before importing anything from the library, rather than
relying on the absence of configuration. Absence of a switch is not a fence.
"""
from __future__ import annotations

import os
from typing import Any, TypedDict


#: Set before the first LangGraph import, never read back from the environment.
#: See EGRESS in the module docstring: the point is to state the value rather
#: than to inherit whatever the machine happens to have.
_TRACING_OFF = {
    "LANGSMITH_TRACING": "false",
    "LANGCHAIN_TRACING_V2": "false",
    "LANGSMITH_TRACING_V2": "false",
}


class LangGraphUnavailable(RuntimeError):
    """LangGraph was asked for and is not installed."""


def _pin_tracing_off() -> None:
    for key, value in _TRACING_OFF.items():
        os.environ[key] = value


def langgraph_available() -> bool:
    """Is the optional dependency importable? Never raises."""
    try:
        import langgraph  # noqa: F401
    except ImportError:
        return False
    return True


def tracing_is_pinned_off() -> bool:
    """Every telemetry switch this adapter knows about reads as off.

    Exposed so a test can assert it, because a security property nobody checks
    is a comment.
    """
    return all(os.environ.get(k) == v for k, v in _TRACING_OFF.items())


class BriefState(TypedDict, total=False):
    """The graph's state schema: ``RunState``'s keys, plus the task it carries.

    Nothing here is invented for the graph's benefit. If a key is needed that
    ``RunState`` does not have, that is a signal to change ``RunState`` -- not
    to grow a second state model beside it.
    """

    # inputs
    run_id: str
    objective: str
    repo_root: str
    paths: list
    # derived
    agent: dict
    active_agent: str
    task: dict
    state: dict


def _node_route(state: BriefState) -> dict:
    """Pick exactly one agent. The router is the same one the stdlib path uses;
    this node adds no scoring, no tie-break and no second opinion."""
    from .router import route_task

    agent = route_task(state["objective"], list(state.get("paths") or []))
    return {"agent": agent, "active_agent": agent["name"]}


def _node_build_task(state: BriefState) -> dict:
    """Build the pruned brief. The constraint list is quoted from
    ``runbook.create_run`` rather than re-worded: two copies of a rule that
    drift apart are worse than one copy in the wrong place."""
    from .schemas import AgentTask

    agent = state["agent"]
    task = AgentTask(
        task_id=state["run_id"],
        agent=agent["name"],
        repo_root=state["repo_root"],
        objective=state["objective"],
        paths=list(state.get("paths") or []),
        context={
            "must_read": agent.get("must_read", []),
            "model_tier": agent.get("model_tier", "sonnet"),
            "call_name": agent.get("call_name", agent["name"]),
        },
        constraints=[
            "Do not read or pass full chat history.",
            "Read only files needed for this task.",
            "Return agent_report_v1 JSON only.",
            "No agent-to-agent chat; report to orchestrator only.",
        ],
    )
    return {"task": task.brief()}


def _node_open_state(state: BriefState) -> dict:
    """Open the RunState and record the one event the stdlib path records."""
    from .schemas import RunState

    run_state = RunState(
        run_id=state["run_id"],
        objective=state["objective"],
        repo_root=state["repo_root"],
        active_agent=state["active_agent"],
        paths=list(state.get("paths") or []),
    )
    run_state.add_event("task_created", state["task"])
    return {"state": run_state.to_dict()}


def build_graph() -> Any:
    """Compile the three-node graph. Raises :class:`LangGraphUnavailable`."""
    if not langgraph_available():
        raise LangGraphUnavailable(
            "LangGraph is not installed. `pip install -e .[orchestration]`, or "
            "use the default engine='stdlib' path, which needs nothing."
        )
    _pin_tracing_off()
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(BriefState)
    graph.add_node("route", _node_route)
    graph.add_node("build_task", _node_build_task)
    graph.add_node("open_state", _node_open_state)
    graph.add_edge(START, "route")
    graph.add_edge("route", "build_task")
    graph.add_edge("build_task", "open_state")
    graph.add_edge("open_state", END)
    return graph.compile()


def run_brief(objective: str, paths: list, repo_root: str, run_id: str) -> dict:
    """The payload ``create_run`` would build, computed by the graph.

    ``run_id`` is an input, not something the graph mints, so two engines can
    be compared on identical inputs. Returns ``{"state": ..., "task": ...}``
    and writes nothing.
    """
    app = build_graph()
    final = app.invoke(
        {
            "run_id": run_id,
            "objective": objective,
            "repo_root": repo_root,
            "paths": list(paths or []),
        }
    )
    return {"state": final["state"], "task": final["task"]}
