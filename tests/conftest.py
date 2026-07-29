"""Suite-wide determinism for stage-1 routing.

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
"""

from __future__ import annotations

import os

import pytest

from daedalus.provider_router import LATENT_ENV

os.environ[LATENT_ENV] = "0"


@pytest.fixture(autouse=True)
def _pin_latent_route_off():
    """Re-pin before every test, so one test's environment edit cannot leak
    non-determinism into the tests that follow it."""
    os.environ[LATENT_ENV] = "0"
    yield
