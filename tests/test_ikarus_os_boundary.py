"""The chat surface is a spend-and-egress surface, and now it has a door.

``daedalus/budget.py`` has named ``ikarus_os.py`` as one of the four
independent vendor-spend origins since the ceiling was written -- and the
effect-boundary registry had no row for it.  Two public functions (``ask``,
``ask_stream``) reach four provider runtimes: two over HTTP (``_ollama``,
``_deepseek``, plus their streaming twins) and two by spawning a vendor CLI
(``_claude``, ``_codex``, plus ``_claude_stream``).  A chat turn could
therefore open a socket to whatever ``OLLAMA_HOST`` pointed at, or bill a
DeepSeek call, without one canonical start.

These probes pin the three things that changed:

* the two doors and the transport start are registered with the effects they
  really perform, and every sink function is ANCHORED to the transport start,
  so deleting the admission from any single provider is a conformance blocker;
* a refused endpoint costs ZERO connections and ZERO spawns -- asserted by
  making ``socket.connect`` / ``subprocess.run`` raise, so the claim is about
  control flow rather than about a mock returning something plausible;
* the refusal NAMES the endpoint, in the receipt and in the sentence the user
  reads.  A withheld call nobody can attribute to a host is a refusal nobody
  can fix.

MUTATION NOTE (all four verified by hand on 2026-08-22, each one turns the
named probe red):

* delete ``_provider_start("ollama", ...)`` from ``_ollama`` ->
  ``test_every_provider_sink_is_anchored_to_the_transport_start`` and
  ``test_disallowed_ollama_host_refuses_before_any_socket`` go red
  (measured: ``registry.guard_anchor_missing`` blocker, and the refused turn
  becomes one real connect attempt to 10.0.0.9);
* delete ``begin_effect`` from ``ask`` -> ``test_ask_door_is_anchored`` goes red
  (measured: ``daedalus.ikarus_os:ask no longer calls begin_effect``);
* move the ``begin_effect`` call below the classification in ``ask`` ->
  ``test_the_door_is_the_first_statement_of_each_entrypoint`` goes red;
* add a new function that calls ``urlopen``/``subprocess`` without routing
  through ``_provider_start`` ->
  ``test_every_effect_sink_is_reachable_only_through_the_doors`` names it.

NOTHING HERE CLAIMS A SANDBOX.  ``begin_effect`` authorises a start; a Python
caller that imports ``_ollama`` directly still reaches the socket.  What the
boundary buys is that the product's own paths cannot, and that removing one is
loud.
"""
from __future__ import annotations

import ast
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from daedalus.spine.effect_boundary import (
    REGISTRY_BY_ID,
    Effect,
    Surface,
    Wiring,
    check_conformance,
)

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "daedalus" / "ikarus_os.py"

#: Every function in this module that reaches a socket or spawns a vendor.
#: Frozen on purpose: a NEW sink that is not in this set fails the structural
#: probe below rather than quietly inheriting the doors' reputation.
SINK_FUNCTIONS = {
    "_ollama",
    "_ollama_cli",
    "_deepseek",
    "_claude",
    "_codex",
    "_ollama_stream",
    "_deepseek_stream",
    "_claude_stream",
}
DOORS = {"ask", "ask_stream"}

TURN_EFFECTS = {
    Effect.NETWORK_EGRESS,
    Effect.PROCESS_SPAWN,
    Effect.SPEND,
    Effect.SECRETS,
}


# --------------------------------------------------------------------------- #
# isolation                                                                    #
# --------------------------------------------------------------------------- #
@pytest.fixture
def sealed(tmp_path, monkeypatch):
    """A throwaway budget ledger, no operator declarations, and the interposer
    removed afterwards.

    ``process_guard_boundary_decision`` really monkeypatches
    ``subprocess.run``/``Popen`` and ``urllib.request.urlopen`` for the whole
    process -- that is what makes the door's receipt honest -- so a test that
    installed it and walked away would hand every later test in the session a
    patched stdlib and a shared ledger.  Uninstalled in teardown for the same
    reason ``tests/conftest.py`` re-clears the operator declarations: a suite
    whose verdict depends on which test ran first is not testing anything.
    """
    from daedalus import budget

    monkeypatch.setenv("DAEDALUS_BUDGET_LEDGER", str(tmp_path / "ledger.json"))
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "5.00")
    monkeypatch.setenv("DAEDALUS_BUDGET_PERIOD_CEILING_ENABLED", "true")
    monkeypatch.delenv("DAEDALUS_EXECUTION_LIMIT_POLICY", raising=False)
    monkeypatch.delenv("DAEDALUS_OLLAMA_REMOTE_OK", raising=False)
    monkeypatch.delenv("DAEDALUS_TRUSTED_HOSTS", raising=False)
    budget.reset_default_ledger()
    try:
        yield budget
    finally:
        budget.uninstall_process_guard()
        budget.reset_default_ledger()


@pytest.fixture
def no_effects(monkeypatch):
    """Turn every socket connect and every spawn into a loud failure.

    Returns the two recorders.  Nothing here stubs a *reply*: the point is that
    a refused turn never gets far enough to need one.
    """
    connects: list[object] = []
    spawns: list[object] = []

    def bad_connect(self, address, *a, **k):
        connects.append(address)
        raise AssertionError(f"socket.connect reached: {address!r}")

    def bad_create(address, *a, **k):
        connects.append(address)
        raise AssertionError(f"socket.create_connection reached: {address!r}")

    def bad_run(argv, *a, **k):
        spawns.append(argv)
        raise AssertionError(f"subprocess.run reached: {argv!r}")

    class BadPopen:
        def __init__(self, argv, *a, **k):
            spawns.append(argv)
            raise AssertionError(f"subprocess.Popen reached: {argv!r}")

    monkeypatch.setattr(socket.socket, "connect", bad_connect)
    monkeypatch.setattr(socket, "create_connection", bad_create)
    monkeypatch.setattr(subprocess, "run", bad_run)
    monkeypatch.setattr(subprocess, "Popen", BadPopen)
    return connects, spawns


def _module_functions() -> dict[str, ast.FunctionDef]:
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _calls(node: ast.AST) -> set[str]:
    """Names called directly in one function body (not in nested defs)."""
    found: set[str] = set()

    def walk(current: ast.AST) -> None:
        if current is not node and isinstance(
            current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)
        ):
            return
        if isinstance(current, ast.Call):
            func = current.func
            if isinstance(func, ast.Name):
                found.add(func.id)
            elif isinstance(func, ast.Attribute):
                parts = []
                cur: ast.AST | None = func
                while isinstance(cur, ast.Attribute):
                    parts.append(cur.attr)
                    cur = cur.value
                if isinstance(cur, ast.Name):
                    parts.append(cur.id)
                found.add(".".join(reversed(parts)))
                found.add(func.attr)
        for child in ast.iter_child_nodes(current):
            walk(child)

    walk(node)
    return found


# --------------------------------------------------------------------------- #
# 1. the rows                                                                  #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "entrypoint_id,target,contracts",
    [
        ("ikarus_os.ask", "daedalus.ikarus_os:ask", ("budget.process_guard",)),
        ("ikarus_os.ask_stream", "daedalus.ikarus_os:ask_stream",
         ("budget.process_guard",)),
        ("ikarus_os.provider_call", "daedalus.ikarus_os:_provider_start",
         ("budget.process_guard", "provider.egress_policy")),
    ],
)
def test_each_door_is_registered_with_the_effects_it_performs(
    entrypoint_id, target, contracts
):
    row = REGISTRY_BY_ID[entrypoint_id]
    assert row.target == target
    assert row.surface is Surface.PYTHON
    assert row.wiring is Wiring.CENTRAL, "an inventory-only row admits nothing"
    assert set(row.effects) == TURN_EFFECTS
    assert tuple(row.guard_contracts) == contracts


def test_secrets_is_in_the_effect_vocabulary():
    """The DeepSeek branch reads DEEPSEEK_API_KEY in-process, so the rows can
    only be honest if the vocabulary has a word for it."""
    assert Effect.SECRETS.value == "secrets"
    assert Effect.SECRETS in REGISTRY_BY_ID["ikarus_os.ask"].effects


def test_ask_door_is_anchored():
    anchors = REGISTRY_BY_ID["ikarus_os.ask"].anchors
    assert ("daedalus.ikarus_os:ask", "begin_effect") in {
        (a.target, a.call) for a in anchors
    }


def test_ask_stream_pins_both_the_delegation_and_the_start():
    """The tap only persists the final turn; the INNER generator is what picks
    a provider, so the boundary lives there and both hops are anchored."""
    pairs = {(a.target, a.call) for a in REGISTRY_BY_ID["ikarus_os.ask_stream"].anchors}
    assert ("daedalus.ikarus_os:ask_stream", "_ask_stream_inner") in pairs
    assert ("daedalus.ikarus_os:_ask_stream_inner", "begin_effect") in pairs


def test_every_provider_sink_is_anchored_to_the_transport_start():
    pairs = {
        (a.target, a.call)
        for a in REGISTRY_BY_ID["ikarus_os.provider_call"].anchors
    }
    for name in SINK_FUNCTIONS:
        assert (f"daedalus.ikarus_os:{name}", "_provider_start") in pairs, name
    assert ("daedalus.ikarus_os:_provider_start", "begin_effect") in pairs


def test_the_three_rows_add_no_conformance_blocker():
    """The registry stays structurally honest about ikarus_os.

    Deliberately scoped to this module's subjects: the tree carries unrelated
    pre-existing blockers (the retired plan guard's two stale rows), and a
    probe that asserted global conformance would be red for reasons that have
    nothing to do with this lane.
    """
    report = check_conformance(ROOT)
    mine = [
        f for f in report.findings
        if f.severity == "blocker" and "ikarus" in f.subject
    ]
    assert mine == [], mine


# --------------------------------------------------------------------------- #
# 2. the door runs first                                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["ask", "_ask_stream_inner"])
def test_the_door_is_the_first_statement_of_each_entrypoint(name):
    """Before classification, before provider selection, before the
    conversation lookup -- the 72b5af82 / c67fd116 shape.  A boundary below a
    branch is a boundary some branch can skip."""
    node = _module_functions()[name]
    body = [stmt for stmt in node.body if not (
        isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
    )]
    # imports for the boundary, then the guarded start -- nothing else before.
    prefix = body[: body.index(next(
        stmt for stmt in body
        if isinstance(stmt, ast.Try) and "begin_effect" in _calls(stmt)
    ))]
    assert all(isinstance(stmt, (ast.Import, ast.ImportFrom)) for stmt in prefix), (
        f"{name} does work before its effect boundary: {prefix}"
    )


# --------------------------------------------------------------------------- #
# 3. a refused endpoint costs nothing                                          #
# --------------------------------------------------------------------------- #
def test_disallowed_ollama_host_refuses_before_any_socket(
    sealed, no_effects, monkeypatch
):
    """MEASURED 2026-08-22: zero connects, zero spawns, refusal receipt.

    ``OLLAMA_HOST`` is an environment variable, so the same chat path talks to
    127.0.0.1 or to a box across a tailnet with no code change.  This is the
    case that used to leave silently.
    """
    import daedalus.ikarus_os as ikarus_os

    connects, spawns = no_effects
    monkeypatch.setenv("OLLAMA_HOST", "http://10.0.0.9:11434")

    envelope = ikarus_os.ask("agent_env", "hallo, wie geht es dir", provider="ollama")

    assert connects == [], f"a refused host still connected: {connects}"
    assert spawns == [], f"a refused host still spawned: {spawns}"
    assert envelope["intent"] == "error"
    assert envelope["ok"] is True, "a refusal is an answer, not a crash"


def test_the_refusal_receipt_names_the_host_and_the_contract(
    sealed, no_effects, monkeypatch
):
    import daedalus.ikarus_os as ikarus_os

    monkeypatch.setenv("OLLAMA_HOST", "http://10.0.0.9:11434")
    envelope = ikarus_os.ask("agent_env", "hallo", provider="ollama")

    receipt = envelope["refusal"]
    assert receipt["host"] == "http://10.0.0.9:11434"
    assert receipt["contract"] == "provider.egress_policy"
    assert receipt["entrypoint_id"] == "ikarus_os.provider_call"
    assert receipt["verdict"] == "deny"
    assert receipt["connected"] is False and receipt["spawned"] is False
    assert receipt["security_boundary_claimed"] is False
    assert len(receipt["receipt_sha256"]) == 64
    assert len(receipt["registry_sha256"]) == 64
    # ...and the human sentence carries it too. A receipt the user never sees
    # is a refusal they cannot act on.
    assert "10.0.0.9" in envelope["assistant"]


def test_operator_consent_for_that_exact_endpoint_admits_it(sealed, monkeypatch):
    """The refusal is about an UNDECLARED lane, not about remoteness.

    Same decision function the embedding backend uses, so consent and refusal
    cannot drift apart between the two lanes.
    """
    import daedalus.ikarus_os as ikarus_os

    monkeypatch.setenv("DAEDALUS_OLLAMA_REMOTE_OK", "http://10.0.0.9:11434")
    receipt = ikarus_os._provider_start(
        "ollama", endpoint="http://10.0.0.9:11434", model="qwen2.5-coder:7b")
    assert receipt.entrypoint_id == "ikarus_os.provider_call"
    assert "network_egress" in receipt.requested_effects


def test_loopback_ollama_is_admitted_and_costs_no_effects(sealed):
    """The ordinary path is unchanged: a local endpoint is physics, not policy."""
    import daedalus.ikarus_os as ikarus_os

    receipt = ikarus_os._provider_start(
        "ollama", endpoint="http://127.0.0.1:11434", model="qwen2.5-coder:7b")
    assert receipt.requested_effects == ("network_egress",), (
        "a loopback ollama call spends nothing and reads no key; requesting "
        "spend/secrets here would make the registry meaningless"
    )


def test_exhausted_ceiling_refuses_deepseek_before_socket_or_spawn(
    sealed, no_effects, monkeypatch
):
    """The paid lane, with the ledger already at its ceiling.

    The refusal mirrors ``Ledger.reserve``'s own two conditions (dollar
    ceiling, call cap) as a READ -- the interposer still does the reserving at
    the socket, so the money is counted once.  What the pre-flight adds is that
    the verdict arrives before the connection and with a name on it.
    """
    import daedalus.ikarus_os as ikarus_os

    connects, spawns = no_effects
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-not-a-real-key")
    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "1.00")
    sealed.reset_default_ledger()
    sealed.reserve("deepseek", "deepseek-chat", label="seed").settle(0.99)

    envelope = ikarus_os.ask("agent_env", "hallo", provider="deepseek")

    assert connects == [], f"an exhausted ceiling still connected: {connects}"
    assert spawns == [], f"an exhausted ceiling still spawned: {spawns}"
    receipt = envelope["refusal"]
    assert receipt["contract"] == "budget.process_guard"
    assert "ceiling" in receipt["reason"]
    assert "api.deepseek.com" in receipt["host"]


def test_explicit_uncapped_mode_admits_paid_preflight_above_configured_amount(
        sealed, monkeypatch):
    import daedalus.ikarus_os as ikarus_os

    monkeypatch.setenv("DAEDALUS_BUDGET_USD", "0.01")
    monkeypatch.setenv("DAEDALUS_BUDGET_PERIOD_CEILING_ENABLED", "false")
    sealed.reset_default_ledger()

    decision = ikarus_os._spend_decision("deepseek", "deepseek-chat")

    assert decision.allowed is True
    assert "explicitly uncapped" in decision.evidence


def test_uncapped_paid_preflight_still_refuses_at_the_call_cap(
        sealed, monkeypatch):
    import daedalus.ikarus_os as ikarus_os

    monkeypatch.setenv("DAEDALUS_BUDGET_PERIOD_CEILING_ENABLED", "false")
    monkeypatch.setenv("DAEDALUS_BUDGET_MAX_CALLS", "1")
    sealed.reset_default_ledger()
    sealed.reserve("deepseek", "deepseek-chat", label="use only call").settle()

    decision = ikarus_os._spend_decision("deepseek", "deepseek-chat")

    assert decision.allowed is False
    assert "call-count cap" in decision.evidence
    assert "explicitly uncapped" in decision.evidence


def test_disabled_billable_call_axis_admits_but_keeps_recorded_count(
        sealed, monkeypatch):
    import daedalus.ikarus_os as ikarus_os
    from daedalus.limit_policy import ExecutionLimitPolicy, LimitAxes, MODE_CUSTOM

    policy = ExecutionLimitPolicy(
        mode=MODE_CUSTOM,
        configured=LimitAxes(billable_calls=False),
    )
    monkeypatch.setenv(
        "DAEDALUS_EXECUTION_LIMIT_POLICY", policy.to_env_value()
    )
    monkeypatch.setenv("DAEDALUS_BUDGET_MAX_CALLS", "1")
    sealed.reset_default_ledger()
    sealed.reserve("deepseek", "deepseek-chat", label="record first call").settle()

    decision = ikarus_os._spend_decision("deepseek", "deepseek-chat")

    assert decision.allowed is True
    assert "billable-call ceiling explicitly disabled" in decision.evidence
    assert sealed.ledger().state().calls == 1


def test_an_unreadable_ledger_denies_rather_than_passes(sealed, monkeypatch):
    """FAIL CLOSED.  Absence of a readable budget is not absence of a cap."""
    import daedalus.ikarus_os as ikarus_os

    ledger_path = Path(sealed.ledger().path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text("{not json", encoding="utf-8")
    sealed.reset_default_ledger()

    decision = ikarus_os._spend_decision("deepseek", "deepseek-chat")
    assert decision.allowed is False
    assert decision.contract == "budget.process_guard"
    assert decision.evidence.strip(), "a refusal with no evidence is not a refusal"


def test_ask_stream_refuses_at_the_same_door_without_a_single_delta(
    sealed, no_effects, monkeypatch
):
    import daedalus.ikarus_os as ikarus_os

    connects, _spawns = no_effects
    monkeypatch.setenv("OLLAMA_HOST", "http://10.0.0.9:11434")

    events = list(ikarus_os.ask_stream("agent_env", "hallo", provider="ollama"))
    kinds = [kind for kind, _payload in events]

    assert connects == []
    assert "delta" not in kinds, "a refused stream must not emit text"
    final = [payload for kind, payload in events if kind == "final"][0]
    assert final["refusal"]["host"] == "http://10.0.0.9:11434"


# --------------------------------------------------------------------------- #
# 4. ordering, seen from outside the code                                      #
# --------------------------------------------------------------------------- #
def test_audit_trace_puts_the_boundary_before_every_spawn_and_socket(
    sealed, monkeypatch
):
    """An interpreter-level trace, not an assertion about what we think we wrote.

    ``sys.addaudithook`` cannot be uninstalled, so the hook is a permanent but
    inert closure over a flag: it appends only while this test is running and
    costs a boolean check for the rest of the session.
    """
    import daedalus.ikarus_os as ikarus_os
    from daedalus.spine import effect_boundary

    trace: list[str] = []
    recording = {"on": False}

    def hook(event, args):
        if not recording["on"]:
            return
        if event in ("socket.connect", "subprocess.Popen", "urllib.Request"):
            trace.append(event)

    sys.addaudithook(hook)

    real_begin = effect_boundary.begin_effect

    def traced_begin(entrypoint_id, effects, decisions, **kw):
        if recording["on"]:
            trace.append(f"boundary:{entrypoint_id}")
        return real_begin(entrypoint_id, effects, decisions, **kw)

    monkeypatch.setattr(effect_boundary, "begin_effect", traced_begin)
    monkeypatch.setenv("OLLAMA_HOST", "http://10.0.0.9:11434")

    recording["on"] = True
    try:
        ikarus_os.ask("agent_env", "hallo", provider="ollama")
    finally:
        recording["on"] = False

    assert trace, "the trace recorded nothing at all"
    assert trace[0] == "boundary:ikarus_os.ask", trace
    effectful = [i for i, row in enumerate(trace) if not row.startswith("boundary:")]
    assert all(
        any(trace[j].startswith("boundary:") for j in range(i))
        for i in effectful
    ), trace
    # ...and on a refused host there is nothing after the two boundaries at all.
    assert effectful == [], f"a refused turn produced effects: {trace}"


# --------------------------------------------------------------------------- #
# 5. structure: no second way in                                               #
# --------------------------------------------------------------------------- #
def test_every_effect_sink_is_reachable_only_through_the_doors():
    """Name the offenders rather than merely failing.

    A function in this module that reaches ``urlopen``/``chat_completion``/
    ``chat_stream``/``subprocess`` and is NOT reachable from ``ask`` or
    ``ask_stream`` is an unguarded second entrance -- the exact shape the
    registry exists to make visible.
    """
    functions = _module_functions()
    sink_calls = {
        "subprocess.run", "subprocess.Popen", "subprocess.check_call",
        "subprocess.check_output", "urlopen", "urllib.request.urlopen",
        "chat_completion", "chat_stream", "socket.create_connection",
    }

    discovered = {
        name for name, node in functions.items() if _calls(node) & sink_calls
    }
    assert discovered == SINK_FUNCTIONS, (
        "the set of effect sinks in daedalus/ikarus_os.py changed: "
        f"new={sorted(discovered - SINK_FUNCTIONS)} "
        f"gone={sorted(SINK_FUNCTIONS - discovered)}"
    )

    reachable: set[str] = set()
    frontier = list(DOORS)
    while frontier:
        name = frontier.pop()
        if name in reachable or name not in functions:
            continue
        reachable.add(name)
        frontier.extend(_calls(functions[name]) & set(functions))

    offenders = sorted(discovered - reachable)
    assert offenders == [], f"effect sinks not reachable from ask/ask_stream: {offenders}"

    unguarded = sorted(
        name for name in discovered if "_provider_start" not in _calls(functions[name])
    )
    assert unguarded == [], f"effect sinks that skip the transport start: {unguarded}"


def test_the_transport_start_is_the_first_statement_of_each_sink():
    """Before the request object, before the argv, before the warm thread.

    ``warm_model_async`` connects on a daemon thread, so an admission placed
    after it would have already leaked the endpoint.
    """
    functions = _module_functions()
    late = []
    for name in sorted(SINK_FUNCTIONS):
        body = [
            stmt for stmt in functions[name].body
            if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))
        ]
        index = next(
            i for i, stmt in enumerate(body) if "_provider_start" in _calls(stmt)
        )
        before = body[:index]
        allowed = (ast.Import, ast.ImportFrom, ast.Assign, ast.AnnAssign, ast.If, ast.Return)
        if any(not isinstance(stmt, allowed) for stmt in before):
            late.append(name)
        for stmt in before:
            assert not (_calls(stmt) & {
                "chat_completion", "chat_stream", "warm_model_async",
                "subprocess.run", "subprocess.Popen",
            }), f"{name} performs an effect before its transport start"
    assert late == [], late
