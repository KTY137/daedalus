"""Suite-wide determinism for stage-1 routing and for operator declarations.

The latent (embedding) route in ``daedalus/semantic_route.py`` is wired into
``provider_router.route_and_select`` and is ON by default in production. That
makes every test that routes depend on whether the box it runs on happens to
have a working embedding backend -- and on what that backend's model thinks
this week.

Both states currently pass, which is luck rather than design: a box WITH
``nomic-embed-text`` routes some objectives to a different role than a box
without one, and a suite that is green either way is green by accident. The
first embedding-model bump or roster edit turns that into a test failure in a
file that never mentions embeddings, and whoever gets it will have no reason to
suspect stage 1.

So the latent route is pinned OFF for the whole suite. Tests where the latent
route is the SUBJECT re-enable it explicitly and point it at a local fake
backend -- see ``tests/test_semantic_route_wired.py``, which clears this
variable in ``setUp`` under a ``patch.dict`` that restores it afterwards, and
``tests/test_semantic_route_live.py``, which calls the module directly and is
unaffected by this switch.

Set deliberately rather than with ``setdefault``: inheriting an operator's
exported value is exactly the machine-dependence this removes.

THE SAME ARGUMENT, FOR DECLARATIONS THAT MOVE A VERDICT
-------------------------------------------------------
``DAEDALUS_TRUSTED_HOSTS`` and ``DAEDALUS_SUBSCRIPTION_VENDORS`` are operator
declarations: the first decides whether a host is inside the egress fence, the
second whether a vendor's calls cost dollars. Both legitimately live in a
developer's ``.env``, and ``daedalus.cli.main`` loads that file into
``os.environ`` for real -- permanently, on purpose, because the guard it
configures must see it.

Measured 2026-07-29: several tests invoke ``cli.main`` IN-PROCESS. The first one
to run loaded a developer's ``.env`` and every egress test after it was judging
that developer's machine rather than the code. Fourteen tests went red in the
full suite and green in isolation, and the failing assertion -- "this host is
untrusted" -- was the fence's most important claim. A suite whose verdict about
the fence depends on who is running it is not testing the fence.

Cleared rather than left alone, and re-cleared before every test rather than
once at import, for the same reason the latent route is re-pinned: an
in-process ``cli.main`` can reload the file at any point in the session, so a
one-shot clear at collection time would be undone by the first test that runs
the CLI. Tests where a declaration is the SUBJECT set it themselves
(``tests/test_host_predicate.py`` via ``monkeypatch.setenv``, which runs after
this fixture and is restored after the test).
"""

from __future__ import annotations

import os

import pytest

from daedalus.budget import ENV_SUBSCRIPTIONS
from daedalus.provider_router import LATENT_ENV
from daedalus.sensitivity import ENV_TRUSTED_HOSTS

# Imported rather than spelled as literals so that renaming a variable in the
# production module cannot silently un-pin it here -- a pin that stops matching
# the code it pins is worse than no pin, because it still looks deliberate.
#
# THE SECOND HALF OF THE SAME INCIDENT, found by bisection on 2026-07-29: any
# test that runs ``cli.main`` in-process loads the developer's ``.env`` into
# ``os.environ`` for real (cli.py does this deliberately -- the spend guard's
# own config lives there). Clearing only the two fence declarations above left
# every OTHER ``.env`` key leaking into the tests that ran afterwards: a bench
# model name (``OLLAMA_MODEL=qwen3.6:latest``) that exists on the operator's
# remote GPU and nowhere else, and a ``DEEPSEEK_API_KEY`` whose mere presence
# flips provider availability and therefore routing. Twelve tests were red in
# the full suite and green in isolation -- the shortest failing prefix ended,
# reproducibly, at the first CLI-invoking test file. So: every key the
# ``.env`` loader can inject that moves a verdict is pinned here, from
# ``.env.example``'s own key list (kept in sync by the test below in
# ``test_dotenv.py`` -- if a new key appears there, this tuple must grow).
_OPERATOR_DECLARATIONS = (
    ENV_TRUSTED_HOSTS, ENV_SUBSCRIPTIONS,
    "OLLAMA_HOST", "OLLAMA_MODEL", "OLLAMA_EMBED_MODEL",
    "DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL",
    "DAEDALUS_RTX_SSH", "DAEDALUS_RTX_SSH_FALLBACK",
    "DAEDALUS_TRACE_ID",
    # The operator's live-activation ceiling. A leaked real ceiling would make
    # budget tests measure the owner's wallet instead of their fixtures.
    "DAEDALUS_BUDGET_USD", "DAEDALUS_BUDGET_MAX_CALLS",
)

os.environ[LATENT_ENV] = "0"
for _name in _OPERATOR_DECLARATIONS:
    os.environ.pop(_name, None)


@pytest.fixture(autouse=True)
def _pin_latent_route_off(tmp_path_factory):
    """Re-pin before every test, so one test's environment edit cannot leak
    non-determinism into the tests that follow it.

    Since 83e41fcc the chat seam writes its turns into the canonical spine
    (``runs/spine/spine.sqlite3``); a suite run that calls ``ikarus_os.ask``
    would append real intents to the operator's event store. Every test
    therefore gets a throwaway ``DAEDALUS_SPINE_DB`` unless it pins its own.
    """
    os.environ[LATENT_ENV] = "0"
    for name in _OPERATOR_DECLARATIONS:
        os.environ.pop(name, None)
    had_spine = "DAEDALUS_SPINE_DB" in os.environ
    if not had_spine:
        os.environ["DAEDALUS_SPINE_DB"] = str(
            tmp_path_factory.mktemp("spine") / "spine.sqlite3"
        )
    # Since fd314dd5 ikarus_os.ask installs the budget process guard and reads
    # the ledger named by DAEDALUS_BUDGET_LEDGER; without a pin a suite run
    # would meter against the operator's runs/budget/ledger.json.
    had_ledger = "DAEDALUS_BUDGET_LEDGER" in os.environ
    if not had_ledger:
        os.environ["DAEDALUS_BUDGET_LEDGER"] = str(
            tmp_path_factory.mktemp("budget") / "ledger.json"
        )
    # Since 2026-08-23 the default worktree root is <OS profile>/.daedalus/
    # worktrees (it was %LOCALAPPDATA%, where suite runs had left 1,149
    # digest directories of .daedalus-alloc litter, MEASURED). A test that
    # wants the default derivation deletes this pin itself.
    had_worktrees = "DAEDALUS_WORKTREE_ROOT" in os.environ
    if not had_worktrees:
        os.environ["DAEDALUS_WORKTREE_ROOT"] = str(
            tmp_path_factory.mktemp("worktrees")
        )
    yield
    try:
        from daedalus import budget as _budget
        _budget.uninstall_process_guard()
    except Exception:  # noqa: BLE001 - teardown must never fail a test
        pass
    if not had_spine:
        os.environ.pop("DAEDALUS_SPINE_DB", None)
    if not had_ledger:
        os.environ.pop("DAEDALUS_BUDGET_LEDGER", None)
    if not had_worktrees:
        os.environ.pop("DAEDALUS_WORKTREE_ROOT", None)
