# LangGraph, adopted as an adapter: contract, failure mode, replacement path, benefit

**MEASURED 2026-08-25.** Every number below names the command that produced it.
`Iron Plan: EXPERIMENT` · `Iron Gate: 0`

The owner asked for LangGraph to be wired up properly. Plan §9.2 admits an
external library "behind adapters" and requires four things of any adoption —
*an adapter contract, failure mode, replacement path, and measured benefit*.
This page is those four. §12 additionally holds that, while Gate 0 is open, new
work is either wired through the canonical kernel or kept as a bounded
experiment; this is wired through the canonical path and stays opt-in, so it is
neither a new feature path nor a new state store.

## What was built

`daedalus.runbook.create_run` composes one pruned run brief in four steps:
route the objective to a single agent, build the `AgentTask`, open a
`RunState`, record the `task_created` event. `daedalus/langgraph_adapter.py`
expresses those same four steps as a three-node LangGraph graph over the *same*
state keys, and `create_run` gained one parameter:

```python
create_run(objective, paths, repo_root, engine="stdlib")   # default, unchanged
create_run(objective, paths, repo_root, engine="langgraph")
```

`engine` selects who **composes** the brief, never who **writes** it. Both
engines return through `_write_brief`, the single writer, which is the only
effect either path produces. That is what keeps this an adapter rather than the
"parallel control plane" §13 forbids.

## 1. The adapter contract — equivalence

> For identical inputs, including a caller-supplied `run_id`, the two engines
> produce the same brief. The only permitted difference is the two fields that
> read a clock: `state.created_at` and the timestamp inside the single event.

`tests/test_langgraph_adapter.py` asserts it against the **real** router, not a
stub, and pins three further things so the assertion cannot rot:

- `test_the_agreement_is_not_vacuous` — a comparison of two empty payloads
  passes and proves nothing, so the routed agent, the four constraints, the
  event kind and the paths are each asserted present;
- `test_the_clock_is_the_only_permitted_difference` — the normaliser cannot
  quietly grow a third exemption;
- `test_nothing_imports_langgraph_at_module_scope` — an AST walk over every
  `daedalus/**/*.py`, because the replacement path below is only true while no
  module reaches for the library on the way in.

**Mutation-checked.** Changing one word in one constraint string inside the
adapter turned `test_both_engines_compose_the_identical_brief` red, and only
that test; the file was restored byte-exactly (sha256 `a42d153a4fbb6c00` before
and after). A green equivalence test that cannot go red is decoration.

## 2. The failure mode

| situation | behaviour |
|---|---|
| library absent, `engine="stdlib"` (default) | nothing changes; the stdlib path never learns |
| library absent, `engine="langgraph"` | raises `LangGraphUnavailable`; **no brief is written** |
| graph raises mid-run | exception propagates; nothing written, because the graph never writes |
| unknown engine name | `ValueError`, before any work |

There is deliberately **no silent fallback** from the graph to the line. A
degrade-in-silence would make "which engine produced this brief?"
unanswerable, and an engine you cannot name is one you cannot measure. Both
refusals are tested, including that the refused engine leaves no file behind.

### Egress, which is a failure mode here too

Installing LangGraph pulls `langsmith`, whose default endpoint is
`https://api.smith.langchain.com`. It is off unless an environment variable
turns it on — which means *any* process on the machine that sets
`LANGSMITH_TRACING` would turn it on for this repository as well. The adapter
therefore **pins the switches off explicitly** before the first LangGraph
import rather than relying on their absence, and
`test_telemetry_is_pinned_off_not_merely_unset` sets them to `"true"` first and
proves they read as off afterwards, via `langsmith.utils.tracing_is_enabled()`.
Absence of a switch is not a fence.

## 3. The replacement path

Delete `daedalus/langgraph_adapter.py` and the `orchestration` extra in
`pyproject.toml`; drop the `engine` parameter. Nothing else changes, because
nothing else depends on it:

- core stays `dependencies = []` — the library is an optional extra, never a
  runtime dependency [MEASURED: `pyproject.toml:14`];
- no module under `daedalus/` imports it at module scope [MEASURED by the AST
  test above];
- the default argument is already the stdlib path, so no caller changes.

The cost of removing this dependency is one file deletion, and that is
measurable today rather than promised for later.

## 4. The measured benefit — and its honest size

**Cost first.** 14 packages, **9.80 MB** on disk
[MEASURED 2026-08-25, `importlib.metadata` file sizes]:

| | MB |
|---|---:|
| `langsmith` | 2.93 |
| `langchain-core` | 2.31 |
| `zstandard` | 1.31 |
| `langgraph` | 0.99 |
| the other ten | 2.26 |

**Benefit: resumability the straight line does not have.** Probed with an
`InMemorySaver` checkpointer and a node instrumented to crash:

```text
crash in open_state      -> calls: route, build, open
update_state(as_node="build_task"); next node -> ('open_state',)
resume app.invoke(None)  -> calls: route, build, open, open
   route re-run? False | build_task re-run? False | open_state re-run? True
```

On resume, **only the failed node ran again**; the two completed nodes were
restored from the checkpoint rather than recomputed. The stdlib line has no
equivalent: a failure anywhere means running `create_run` from the top.

**And the honest size of that.** For *this* graph the benefit is close to
theoretical: three cheap, deterministic, side-effect-free nodes. Re-running
them costs one router call. The capability matters only when a node becomes
expensive or effectful — an attempt that spends tokens, a verifier that runs a
suite — which is precisely the shape Gate 1 and Gate 2 work has. So the
measured benefit today is **a proven capability, not a realised saving**, and
this page says so rather than implying otherwise. If that shape never arrives,
the replacement path above is the correct answer.

**Not measured.** No wall-clock or throughput number is reported: several lanes
were running concurrently and any timing taken here would have been noise. One
detail of the crash probe — a `state` key present in the checkpoint immediately
after the failing node raised — is not understood and no claim is built on it.

## How to reproduce

```powershell
pip install -e ".[orchestration]"
python -m pytest tests/test_langgraph_adapter.py -q
python -m daedalus.runbook "add a docstring" --paths daedalus/router.py --engine langgraph
python -m daedalus.runbook "add a docstring" --paths daedalus/router.py   # stdlib, same brief
```
