"""Block/allow coverage for the runtime-trust-ledger port guard.

G1-RUNTIME-03. ``_require_runtime_trust_ledger_port`` is a trust boundary: it
decides whether an injected object is allowed to answer the question "is this
runtime still admitted right now?". Every runtime-bearing effect rests on that
answer, so the guard's contract has to be pinned directly.

Before this module the guard had exactly one direct test -- a single refusal on
the issuance path (``tests/kernel/test_runtime_effect_admission.py``) -- and no
test at all on the ``RuntimeBoundEffectAuthorization`` constructor, on the
verification path, or on ANY accepting case. Its only other failure signal was a
raw ``TypeError`` escaping from an unrelated call site, which is precisely why a
stale inert test fixture read as a guard defect instead of a fixture defect.

Two properties are pinned here and both are required. A block-only suite would
also pass against a guard that refuses every ledger, which would take the whole
runtime effect path permanently offline; an allow-only suite would pass against
no guard at all. The accepting case therefore uses the REAL production
``RuntimeTrustLedger``, not a hand-shaped double that could drift away from it.

The non-callable case is the substantive block. ``@runtime_checkable`` protocols
prove only that the member NAME resolves -- ``isinstance`` returns ``True`` for
an object whose ``require_active`` is an integer. Such an object is admitted at
the boundary, every caller proceeds believing runtime trust was checked, and it
fails much later as an unrelated ``TypeError`` from inside verification, after
the lease has already been composed.
"""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from daedalus.kernel.contracts import RuntimeTrustLedgerPort
from daedalus.kernel.runtime_effects import (
    RuntimeBoundEffectAuthorization,
    _require_runtime_trust_ledger_port,
)
from daedalus.runtimes.trust_store import RuntimeTrustLedger

SOURCE = (
    Path(__file__).resolve().parents[2]
    / "daedalus"
    / "kernel"
    / "runtime_effects.py"
)

GUARD_NAME = "_require_runtime_trust_ledger_port"
FIELD_NAME = "runtime_trust_ledger"

# Every module-level surface of runtime_effects.py that accepts an injected
# runtime trust ledger. Pinned so a fourth surface cannot appear without a
# deliberate decision about whether it, too, is guarded.
EXPECTED_LEDGER_SURFACES = frozenset(
    {
        "issue_runtime_bound_effect_lease",
        "verify_runtime_bound_effect_lease",
        "RuntimeBoundEffectAuthorization",
    }
)


class ConformingTrustLedger:
    """Smallest object that genuinely answers the port's one question."""

    def require_active(self, **kwargs: object) -> object:
        return SimpleNamespace(
            runtime_id="runtime-1",
            envelope_sha256="a" * 64,
            conformance_receipt_sha256="b" * 64,
            runtime_manifest_sha256="c" * 64,
            source_revision="0" * 40,
            expires_at="2026-08-03T12:00:00+00:00",
            record_sha256="d" * 64,
        )


class NoRequireActive:
    """No member at all -- the obvious miss."""


class NonCallableRequireActive:
    """Near miss: the NAME resolves, so ``isinstance`` alone admits it."""

    require_active = 42


class NoneRequireActive:
    """A ledger wired to ``None``, e.g. an unresolved optional dependency."""

    require_active = None


def authorization(*, trust_ledger: object) -> RuntimeBoundEffectAuthorization:
    """Construct the production capability bundle with one injected ledger.

    Everything except ``trust_ledger`` is the minimum that satisfies the other
    ``__post_init__`` bindings, so a failure here can only be about the port.
    """

    request = SimpleNamespace(digest="2" * 64)
    policy = SimpleNamespace(digest="3" * 64)
    lease = SimpleNamespace(
        digest="1" * 64,
        request_sha256=request.digest,
        policy_decision_sha256=policy.digest,
    )
    return RuntimeBoundEffectAuthorization(
        capability=SimpleNamespace(lease=lease),
        request=request,
        policy_decision=policy,
        effect_ledger=SimpleNamespace(),
        runtime_trust_ledger=trust_ledger,
        lease_keyring={},
        runtime_authority_keyring={},
        guard_decisions=(object(),),
        current_kill_switch_generation=0,
        registry={},
    )


# ---------------------------------------------------------------------------
# BLOCK: objects that cannot answer the trust question are refused.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "candidate",
    [
        pytest.param(object(), id="bare-object"),
        pytest.param(NoRequireActive(), id="no-require-active"),
        pytest.param(NonCallableRequireActive(), id="non-callable-require-active"),
        pytest.param(NoneRequireActive(), id="none-require-active"),
        pytest.param(None, id="none"),
    ],
)
def test_guard_refuses_objects_that_cannot_answer_the_trust_question(
    candidate: object,
) -> None:
    with pytest.raises(TypeError, match="RuntimeTrustLedgerPort"):
        _require_runtime_trust_ledger_port(candidate)


def test_known_residual_hole_the_ledger_class_itself_is_still_admitted() -> None:
    """KNOWN RESIDUAL HOLE, recorded rather than closed. Not an endorsement.

    Passing the ``RuntimeTrustLedger`` CLASS instead of an instance is admitted:
    the class object carries a ``require_active`` attribute and that attribute
    is callable, so both halves of the guard are satisfied. The mistake would
    surface later as a missing-``self`` ``TypeError`` at the first lookup.

    It is left open deliberately. Refusing every ``type`` would also refuse a
    legitimate ledger that exposes ``require_active`` as a ``staticmethod`` or
    ``classmethod``, i.e. it would block a valid implementation to catch a
    caller error that no production composition site can currently make --
    ``daedalus.runtimes.admission.authorization.runtime_trust_ledger`` returns
    an instance. Reaching this hole requires write access to the composition
    site, at which point the guard is not the remaining line of defence.

    If this assertion ever fails, someone has closed the hole. Delete this test
    and say so in the packet; do not re-open it to make the test pass.
    """

    assert _require_runtime_trust_ledger_port(RuntimeTrustLedger) is RuntimeTrustLedger


def test_isinstance_alone_would_have_admitted_the_non_callable_ledger() -> None:
    """Pin WHY the guard cannot be a bare ``isinstance`` check.

    If this assertion ever flips, ``@runtime_checkable`` has become strict
    enough on its own and the extra callability check may be reconsidered --
    deliberately, with this test as the record of the reason it exists.
    """

    assert isinstance(NonCallableRequireActive(), RuntimeTrustLedgerPort) is True


def test_authorization_constructor_refuses_a_non_conforming_ledger() -> None:
    """The constructor is a guarded surface, not merely an annotated one.

    This is the case that was untested: the field carried a type annotation and
    nothing verified it, so an inert ``object()`` travelled through the
    constructor unnoticed.
    """

    with pytest.raises(TypeError, match="RuntimeTrustLedgerPort"):
        authorization(trust_ledger=object())

    with pytest.raises(TypeError, match="RuntimeTrustLedgerPort"):
        authorization(trust_ledger=NonCallableRequireActive())


# ---------------------------------------------------------------------------
# ALLOW: a real ledger is not refused. Without these, a guard that refuses
# everything would pass the block cases above and silently take the runtime
# effect path offline.
# ---------------------------------------------------------------------------


def test_guard_admits_the_real_production_trust_ledger(tmp_path: Path) -> None:
    ledger = RuntimeTrustLedger(
        tmp_path / "runtime-trust.sqlite3", integrity_key=b"k" * 32
    )

    assert _require_runtime_trust_ledger_port(ledger) is ledger


def test_authorization_constructor_admits_the_real_production_trust_ledger(
    tmp_path: Path,
) -> None:
    ledger = RuntimeTrustLedger(
        tmp_path / "runtime-trust.sqlite3", integrity_key=b"k" * 32
    )

    value = authorization(trust_ledger=ledger)

    assert value.runtime_trust_ledger is ledger


def test_guard_admits_a_kwargs_forwarding_ledger() -> None:
    """Callability is the whole check; the signature is deliberately not pinned.

    A ``**kwargs`` forwarder is a legitimate implementation shape. Refusing it
    would be a guard that blocks a valid ledger.
    """

    ledger = ConformingTrustLedger()

    assert _require_runtime_trust_ledger_port(ledger) is ledger
    assert authorization(trust_ledger=ledger).runtime_trust_ledger is ledger


# ---------------------------------------------------------------------------
# No unguarded surface: every module-level entry that takes a trust ledger
# routes through the guard.
# ---------------------------------------------------------------------------


def _module() -> ast.Module:
    return ast.parse(SOURCE.read_text(encoding="utf-8"))


def _is_the_injected_ledger(node: ast.expr) -> bool:
    """True only for the injected ledger itself, not for some other value.

    Accepts the bare parameter ``runtime_trust_ledger`` and the dataclass field
    ``self.runtime_trust_ledger``.
    """

    if isinstance(node, ast.Name):
        return node.id == FIELD_NAME
    return (
        isinstance(node, ast.Attribute)
        and node.attr == FIELD_NAME
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
    )


def _guards_unconditionally(body: list[ast.stmt]) -> bool:
    """The guard must be a direct, unconditional statement of this scope.

    Deliberately NOT ``ast.walk``. A walk over the whole scope is satisfied by
    any mention of the guard anywhere -- inside an ``if``, inside a ``try``, or
    in a helper method that construction never calls. That is a test which
    passes while the boundary is gone; it was measured doing exactly that
    before this function replaced it. Only a top-level ``expr`` or assignment
    statement whose call takes the injected ledger counts.
    """

    for stmt in body:
        if isinstance(stmt, ast.Expr):
            call = stmt.value
        elif isinstance(stmt, (ast.Assign, ast.AnnAssign)):
            call = stmt.value
        else:
            continue
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == GUARD_NAME
            and len(call.args) == 1
            and _is_the_injected_ledger(call.args[0])
        ):
            return True
    return False


def _guarded_scope(node: ast.AST) -> list[ast.stmt]:
    """The body that must contain the guard for this surface.

    For a class the only scope that counts is ``__post_init__``: a dataclass
    field is validated at construction or not at all.
    """

    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.body
    assert isinstance(node, ast.ClassDef)
    post_init = [
        stmt
        for stmt in node.body
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef))
        and stmt.name == "__post_init__"
    ]
    assert post_init, f"{node.name} holds a trust ledger field but has no __post_init__"
    return post_init[0].body


def _ledger_surfaces() -> dict[str, ast.AST]:
    surfaces: dict[str, ast.AST] = {}
    for node in _module().body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = node.args
            names = [
                arg.arg for arg in (*args.args, *args.posonlyargs, *args.kwonlyargs)
            ]
            if FIELD_NAME in names:
                surfaces[node.name] = node
        elif isinstance(node, ast.ClassDef):
            fields = [
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign)
                and isinstance(stmt.target, ast.Name)
            ]
            if FIELD_NAME in fields:
                surfaces[node.name] = node
    return surfaces


def test_the_set_of_ledger_accepting_surfaces_is_pinned() -> None:
    """A fourth surface must be a deliberate decision, not an accident."""

    assert set(_ledger_surfaces()) == set(EXPECTED_LEDGER_SURFACES)


@pytest.mark.parametrize("surface", sorted(EXPECTED_LEDGER_SURFACES))
def test_every_ledger_accepting_surface_guards_unconditionally(
    surface: str,
) -> None:
    """The guard must run on the way in, not merely exist somewhere nearby."""

    body = _guarded_scope(_ledger_surfaces()[surface])

    assert _guards_unconditionally(body), (
        f"{surface} accepts a trust ledger without an unconditional guard on "
        "the injected value in the scope that admits it"
    )
