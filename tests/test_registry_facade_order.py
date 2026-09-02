"""The facade reader is aimed at planted answers, in both directions.

WHY THIS FILE EXISTS
--------------------
``tests/test_registry_new_doors.py`` and ``tests/test_registry_retired_rows.py``
derive a door's effects by walking the repository. When the hierarchy refactor
put facades, alias shims, inherited doors and injected ports on that walk, the
walk went blind and 14 of 42 declared effects lost their justification -- while
the UNDER-declaration direction of both instruments kept passing, because a
walk that reaches nothing reports no undeclared effect either.

Making the walk follow those constructs makes the red go away. That is not the
same as making the walk correct, and the difference is the whole subject of
this file. Two failure modes have to be excluded:

1. THE READER IS TOO NARROW -- it follows the construct in the one shape the
   repository happens to use today and silently stops at the next one. Every
   probe below plants a REAL sink behind a construct and requires it to be
   derived.

2. THE READER IS TOO EAGER -- it credits a facade that Python would not
   actually honour, so an effect gets attributed to a module that never
   receives the lookup. Six statement-order shapes below are the ones that
   flipped the gate of the reader in the parallel packet G1-HIER-13, which
   failed security review twice with a working exploit through the real write
   gate. Each appears as a DEAD/LIVE PAIR differing by exactly one statement:
   DEAD must not derive the owner's effect, LIVE must. A reader that ignores
   order fails DEAD; a reader that simply gave up on the shape fails LIVE.

3. THE READER ABSORBS WHAT IT CANNOT READ -- a module that could not be parsed
   drops out of the model set, and a hole in the model set is indistinguishable
   from a function with no effects. Every way a name can arrive from such a
   module is probed, plus the model set's own refusal to be built with a hole
   in it.

THE CONTROL IS THE POINT
------------------------
Every construct probe is also run against ``_Blind`` -- a resolver with the
facade following removed, i.e. what the walk did before this packet. A fixture
that the blind resolver ALSO passes never discriminated, and
:func:`test_every_construct_probe_is_red_without_the_reader` fails if any of
them does. That check exists because shipping fixtures which passed before the
fix is exactly the mistake made in G1-HIER-13.

The LIVE half of each order pair plays the same role for the order shapes:
MEASURED 2026-09-02, disabling the whole-module alias and the module-class
fallback turns all six LIVE probes red, so the pairs are measuring the reader
and not the fixture.

Nothing here reads the repository except the blind-spot census at the end:
every other module is written into ``tmp_path``, so the probes keep meaning the
same thing when the tree moves again.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from daedalus.spine.effect_boundary import Effect, _models  # noqa: E402

import registry_facades  # noqa: E402
import test_registry_new_doors as walk  # noqa: E402
from registry_facades import FacadeResolutionError, Resolver  # noqa: E402

# --------------------------------------------------------------------------- #
# plantable sinks                                                              #
# --------------------------------------------------------------------------- #
#: Each sink is a line of real Python whose effect ``_direct_effects`` -- the
#: scanner's OWN table, not a copy of it -- classifies. Distinct effects per
#: fixture so an assertion can say WHICH body was reached, not merely that
#: something was.
EGRESS = "import urllib.request\ndef sink():\n    urllib.request.urlopen('http://x')\n"
SPAWN = "import subprocess\ndef sink():\n    subprocess.Popen(['x'])\n"
LISTEN = (
    "import http.server\ndef sink():\n"
    "    http.server.ThreadingHTTPServer(('', 0), None)\n"
)


def _tree(tmp_path: Path, **modules: str) -> dict:
    """Write ``daedalus/<name>.py`` for each entry and model the result."""
    package = tmp_path / "daedalus"
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    for name, source in modules.items():
        path = package / (name.replace(".", "/") + ".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        for parent in path.parents:
            if parent == package.parent:
                break
            init = parent / "__init__.py"
            if not init.exists():
                init.write_text("", encoding="utf-8")
        path.write_text(source, encoding="utf-8")
    return {model.module: model for model in _models(tmp_path, ("daedalus",))[0]}


def _effects(models: dict, target: str) -> set[Effect]:
    """The direct sinks reachable from ``target``, through the real walk."""
    with walk.walk_over(models):
        return {
            effect
            for module, qualname in walk.closure(target)
            for effect in walk._local(module)[qualname][0]
        }


class _Blind(Resolver):
    """The resolver as it behaved BEFORE this packet: split, never follow.

    Not a stub. Each override restores one pre-fix behaviour exactly:

    * ``resolve`` is the old ``_owner`` -- longest existing module prefix, with
      the remainder left where it fell and no facade hop;
    * ``bases`` is empty, because the old walk had no notion of a base class,
      which also removes the ``super()`` and inherited-``self`` hops that read
      through it;
    * ``method`` finds a method only where the class is written;
    * ``receivers`` is empty, because an annotation resolved to nothing.

    A probe that passes against this is a probe that would have passed before
    the walk learned anything, and therefore tests nothing.
    """

    def module(self, dotted: str, _seen=frozenset()) -> str | None:
        return self._known(dotted)

    def resolve(self, absolute: str) -> tuple[str, str] | None:
        return self.split(absolute)

    def bases(self, module: str, klass: str) -> tuple[str, ...]:
        return ()

    def receivers(self, module: str, klass: str) -> tuple[tuple[str, str], ...]:
        return ()

    def method(self, module: str, klass: str, method: str):
        qualname = f"{klass}.{method}"
        if module in self._models and qualname in self._models[module].functions:
            return module, qualname
        return None


def _blind_effects(models: dict, target: str) -> set[Effect]:
    with walk.walk_over(models):
        walk.RESOLVER = _Blind(models)
        return {
            effect
            for module, qualname in walk.closure(target)
            for effect in walk._local(module)[qualname][0]
        }


# --------------------------------------------------------------------------- #
# one planted effect per construct the walk claims to follow                   #
# --------------------------------------------------------------------------- #
def _alias_shim(tmp_path: Path) -> dict:
    """construct 1 -- ``sys.modules[__name__] = _owner``."""
    return _tree(
        tmp_path,
        owner=EGRESS,
        shim="import sys as _sys\nfrom daedalus import owner as _owner\n"
        "_sys.modules[__name__] = _owner\n",
        door="from daedalus import shim\ndef main():\n    shim.sink()\n",
    )


def _reexport(tmp_path: Path) -> dict:
    """construct 2 -- ``from owner import sink`` through a locator module."""
    return _tree(
        tmp_path,
        owner=EGRESS,
        facade="from daedalus.owner import sink\n__all__ = ['sink']\n",
        door="from daedalus.facade import sink\ndef main():\n    sink()\n",
    )


def _module_class(tmp_path: Path) -> dict:
    """construct 3 -- ``_module.__class__ = _Facade`` forwarding to ``_owner``."""
    return _tree(
        tmp_path,
        owner=EGRESS,
        facade="import sys\nfrom types import ModuleType\n"
        "from daedalus import owner as _owner\n"
        "class _Facade(ModuleType):\n"
        "    def __getattr__(self, name):\n        return getattr(_owner, name)\n"
        "_module = sys.modules[__name__]\n_module.__class__ = _Facade\n",
        door="from daedalus import facade\ndef main():\n    facade.sink()\n",
    )


def _pep562_string_table(tmp_path: Path) -> dict:
    """construct 4a -- a PEP 562 table of name -> owner module."""
    return _tree(
        tmp_path,
        owner=EGRESS,
        facade="from importlib import import_module\n"
        "_EXPORTS = {'sink': 'daedalus.owner'}\n"
        "def __getattr__(name):\n"
        "    target = _EXPORTS.get(name)\n"
        "    if target is None:\n        raise AttributeError(name)\n"
        "    return getattr(import_module(target), name)\n",
        door="from daedalus import facade\ndef main():\n    facade.sink()\n",
    )


def _pep562_pair_table(tmp_path: Path) -> dict:
    """construct 4b -- a PEP 562 table of name -> (owner module, attribute)."""
    return _tree(
        tmp_path,
        owner=EGRESS,
        facade="from importlib import import_module\n"
        "_EXPORTS = {'sink': ('daedalus.owner', 'sink')}\n"
        "def __getattr__(name):\n"
        "    module_name, attribute = _EXPORTS[name]\n"
        "    return getattr(import_module(module_name), attribute)\n",
        door="from daedalus import facade\ndef main():\n    facade.sink()\n",
    )


def _pep562_single_owner(tmp_path: Path) -> dict:
    """construct 4c -- a guard plus one ``f"{__name__}.sub"`` owner."""
    return _tree(
        tmp_path,
        **{
            "pkg.missions": EGRESS,
            "pkg": "from importlib import import_module\n"
            "__all__ = ['sink']\n"
            "def __getattr__(name):\n"
            "    if name != 'sink':\n        raise AttributeError(name)\n"
            "    return import_module(f'{__name__}.missions').sink\n",
            "door": "from daedalus import pkg\ndef main():\n    pkg.sink()\n",
        },
    )


def _inherited_super(tmp_path: Path) -> dict:
    """construct 5a -- a thin door subclass whose ``__init__`` is ``super()``."""
    return _tree(
        tmp_path,
        owner="import urllib.request\nclass Base:\n"
        "    def __init__(self):\n        urllib.request.urlopen('http://x')\n",
        door="from daedalus.owner import Base\n"
        "class Door(Base):\n"
        "    def __init__(self):\n        super().__init__()\n"
        "def main():\n    Door()\n",
    )


def _inherited_self(tmp_path: Path) -> dict:
    """construct 5b -- ``self.method()`` resolved on a base one module away."""
    return _tree(
        tmp_path,
        owner="import urllib.request\nclass Base:\n"
        "    def restore(self):\n        urllib.request.urlopen('http://x')\n",
        door="from daedalus.owner import Base\n"
        "class Door(Base):\n"
        "    def run(self):\n        return self.restore()\n"
        "def main():\n    Door().run()\n",
    )


def _injected_protocol(tmp_path: Path) -> dict:
    """construct 6a -- a parameter annotated with a repository-local Protocol."""
    return _tree(
        tmp_path,
        port="from typing import Protocol\n"
        "class GatePort(Protocol):\n    def gate(self) -> None: ...\n",
        adapter="import urllib.request\n"
        "class GateAdapter:\n"
        "    def gate(self):\n        urllib.request.urlopen('http://x')\n",
        door="from daedalus.port import GatePort\n"
        "def main(gate_port: GatePort | None = None):\n    gate_port.gate()\n",
    )


def _injected_concrete(tmp_path: Path) -> dict:
    """construct 6b -- a parameter annotated with a concrete owner class."""
    return _tree(
        tmp_path,
        owner="import urllib.request\n"
        "class Executor:\n"
        "    def run(self):\n        urllib.request.urlopen('http://x')\n",
        door="from daedalus.owner import Executor\n"
        "def main(executor: Executor):\n    executor.run()\n",
    )


#: Every construct the walk claims to follow, each with a real sink behind it.
CONSTRUCTS = {
    "module alias shim": _alias_shim,
    "re-export locator": _reexport,
    "module-class facade": _module_class,
    "PEP 562 string table": _pep562_string_table,
    "PEP 562 pair table": _pep562_pair_table,
    "PEP 562 single owner": _pep562_single_owner,
    "inherited super().__init__": _inherited_super,
    "inherited self.method": _inherited_self,
    "injected Protocol port": _injected_protocol,
    "injected concrete port": _injected_concrete,
}


@pytest.mark.parametrize("name", sorted(CONSTRUCTS))
def test_a_planted_effect_behind_each_construct_is_caught(name, tmp_path):
    """The narrow-reader direction: the sink is really derived, per construct."""
    models = CONSTRUCTS[name](tmp_path)
    derived = _effects(models, "daedalus.door:main")
    assert Effect.NETWORK_EGRESS in derived, (
        f"the walk no longer follows the {name!r} construct: a urlopen planted "
        f"behind it derived {sorted(e.value for e in derived)}. Restore the "
        f"hop; do not delete this probe."
    )


@pytest.mark.parametrize("name", sorted(CONSTRUCTS))
def test_every_construct_probe_is_red_without_the_reader(name, tmp_path):
    """The control: each probe FAILS against the pre-packet walk.

    A fixture that passes with the facade following removed proved nothing
    about the facade following. Exactly that mistake shipped in G1-HIER-13,
    so it is asserted here rather than reasoned about.
    """
    models = CONSTRUCTS[name](tmp_path)
    blind = _blind_effects(models, "daedalus.door:main")
    assert Effect.NETWORK_EGRESS not in blind, (
        f"the {name!r} probe is satisfied by the blinded walk too, so it never "
        f"discriminated: it does not test the construct it names."
    )


# --------------------------------------------------------------------------- #
# the six statement-order shapes, each in a DEAD and a LIVE variant            #
# --------------------------------------------------------------------------- #
#: Each shape appears twice: once with the statement that kills the facade and
#: once without it. Nothing else differs. The pair is what makes this an
#: order test rather than a "does the reader cope with this file" test --
#: DEAD must not derive the owner's egress, LIVE must, and since the only
#: difference between them is one statement's position, a reader that gave up
#: on the shape fails LIVE and a reader that ignores order fails DEAD.
#:
#: The four ``__class__`` shapes need a second attribute to be honest about it.
#: Their facade module has to define a local ``sink`` (that is what makes the
#: DEAD case reachable at all), and a local definition SHADOWS the fallback, so
#: ``facade.sink()`` can never exercise the retype. The door therefore also
#: calls ``facade.other()``, which exists ONLY on the owner: it resolves through
#: the module-class fallback or not at all. Without that split the spawn half
#: was satisfied by an ordinary same-module call and proved nothing about the
#: order -- caught in adversarial review of this very file.
_OWNER_TWO = (
    "import urllib.request\n"
    "def sink():\n    urllib.request.urlopen('http://x')\n"
    "def other():\n    urllib.request.urlopen('http://y')\n"
)
_DECOY_PAIR = {"owner": _OWNER_TWO, "decoy": SPAWN}

#: The door for the ``__class__`` shapes: one local call, one fallback-only call.
_TWO_CALL_DOOR = (
    "from daedalus import facade\n"
    "def main():\n    facade.sink()\n    facade.other()\n"
)
_ONE_CALL_DOOR = "from daedalus import facade\ndef main():\n    facade.sink()\n"


def _dead_alias_then_rebound(tmp_path: Path, live: bool) -> dict:
    """A dead ``from owner import`` line, then a rebinding to the decoy."""
    kill = "" if live else "_target = _other\n"
    return _tree(
        tmp_path,
        **_DECOY_PAIR,
        facade="import sys as _s\n"
        "from daedalus import owner as _target\n"
        "from daedalus import decoy as _other\n"
        f"{kill}"
        "_s.modules[__name__] = _target\n",
        door=_ONE_CALL_DOOR,
    )


def _tuple_assign_then_rebind(tmp_path: Path, live: bool) -> dict:
    """A tuple assignment, then a rebinding of one element."""
    kill = "" if live else "_target = _b\n"
    return _tree(
        tmp_path,
        **_DECOY_PAIR,
        facade="import sys as _s\n"
        "from daedalus import owner as _a\n"
        "from daedalus import decoy as _b\n"
        "_target, _spare = _a, _b\n"
        f"{kill}"
        "_s.modules[__name__] = _target\n",
        door=_ONE_CALL_DOOR,
    )


def _facade_class(body_extra: str = "") -> str:
    return (
        "import sys\nfrom types import ModuleType\n"
        "from daedalus import owner as _owner\n"
        "from daedalus import decoy as _decoy\n"
        "class _Facade(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        return getattr(_owner, name)\n" + body_extra
    )


def _retype_before_binding(tmp_path: Path, live: bool) -> dict:
    """``__class__`` set on a name that is not this module yet."""
    bind = "_module = sys.modules[__name__]\n"
    retype = "_module.__class__ = _Facade\n"
    order = bind + retype if live else "_module = None\n" + retype + bind
    return _tree(
        tmp_path,
        **_DECOY_PAIR,
        facade=_facade_class(order + "def sink():\n    _decoy.sink()\n"),
        door=_TWO_CALL_DOOR,
    )


def _retype_undone(tmp_path: Path, live: bool) -> dict:
    """``__class__`` set to the facade, then put back to a plain module."""
    undo = "" if live else "_module.__class__ = ModuleType\n"
    return _tree(
        tmp_path,
        **_DECOY_PAIR,
        facade=_facade_class(
            "_module = sys.modules[__name__]\n"
            "_module.__class__ = _Facade\n"
            f"{undo}"
            "def sink():\n    _decoy.sink()\n"
        ),
        door=_TWO_CALL_DOOR,
    )


def _hookless_class_shadow(tmp_path: Path, live: bool) -> dict:
    """A second class of the same name, without the hook, is the bound one."""
    shadow = "" if live else "class _Facade(ModuleType):\n    pass\n"
    return _tree(
        tmp_path,
        **_DECOY_PAIR,
        facade=_facade_class(
            f"{shadow}"
            "_module = sys.modules[__name__]\n"
            "_module.__class__ = _Facade\n"
            "def sink():\n    _decoy.sink()\n"
        ),
        door=_TWO_CALL_DOOR,
    )


def _hook_deleted_in_class_body(tmp_path: Path, live: bool) -> dict:
    """``def __getattr__`` then ``del __getattr__`` inside the same class."""
    body = (
        "import sys\nfrom types import ModuleType\n"
        "from daedalus import owner as _owner\n"
        "from daedalus import decoy as _decoy\n"
        "class _Facade(ModuleType):\n"
        "    def __getattr__(self, name):\n"
        "        return getattr(_owner, name)\n"
        + ("" if live else "    del __getattr__\n")
        + "_module = sys.modules[__name__]\n"
        "_module.__class__ = _Facade\n"
        "def sink():\n    _decoy.sink()\n"
    )
    return _tree(tmp_path, **_DECOY_PAIR, facade=body, door=_TWO_CALL_DOOR)


ORDER_SHAPES = {
    "dead alias line then rebound": _dead_alias_then_rebound,
    "retype before binding": _retype_before_binding,
    "tuple-assign then rebind": _tuple_assign_then_rebind,
    "retype undone": _retype_undone,
    "same-named hookless class shadowing": _hookless_class_shadow,
    "__getattr__ defined then deleted": _hook_deleted_in_class_body,
}


@pytest.mark.parametrize("name", sorted(ORDER_SHAPES))
def test_the_killing_statement_closes_the_facade(name, tmp_path):
    """DEAD: the reader must not credit a facade a later statement replaced."""
    derived = _effects(ORDER_SHAPES[name](tmp_path, live=False), "daedalus.door:main")
    assert Effect.NETWORK_EGRESS not in derived, (
        f"{name}: the reader credited a facade line that a later statement "
        f"replaced. Python binds the LAST one, so an effect was attributed to "
        f"a module the lookup never reaches."
    )
    assert Effect.PROCESS_SPAWN in derived, (
        f"{name}: the reader lost the module's own content too, so it did not "
        f"read the order -- it gave up on the file. Derived "
        f"{sorted(e.value for e in derived)}."
    )


@pytest.mark.parametrize("name", sorted(ORDER_SHAPES))
def test_without_the_killing_statement_the_same_facade_is_open(name, tmp_path):
    """LIVE: the identical module, minus one statement, DOES reach the owner.

    This is the half that makes the pair an order test. Without it, every DEAD
    assertion above is satisfied by a reader that cannot read the shape at all,
    which is precisely the mistake this file exists to refuse to repeat.
    """
    derived = _effects(ORDER_SHAPES[name](tmp_path, live=True), "daedalus.door:main")
    assert Effect.NETWORK_EGRESS in derived, (
        f"{name}: with the killing statement removed the facade is live and "
        f"the owner's egress must be derived, but the reader found "
        f"{sorted(e.value for e in derived)}. The DEAD half of this pair is "
        f"therefore not measuring order -- it is measuring the reader giving up."
    )


#: The same dead-alias shape, but with the rebinding NESTED. The six pairs
#: above are all flat top-level statements, so none of them could see this.
_NESTED_REBINDS = {
    "if": "if True:\n    _target = _other\n",
    "for": "for _ in (1,):\n    _target = _other\n",
    "try/except": "try:\n    _target = _other\nexcept Exception:\n    pass\n",
    "with": "import contextlib\nwith contextlib.suppress(Exception):\n"
    "    _target = _other\n",
}


@pytest.mark.parametrize("name", sorted(_NESTED_REBINDS))
def test_a_conditional_rebinding_makes_the_reader_decline_not_guess(name, tmp_path):
    """A nested rebinding must not leave the dead import credited.

    The ordered interpreter reads module TOP-LEVEL statements only, because
    which branch of a module-scope ``if`` ran is exactly what a static reader
    cannot know. That is fine on its own; it was wrong where the two layers
    met. MEASURED 2026-09-02, before ``_conditionally_bound``: each of these
    made the reader derive the DEAD owner's NETWORK_EGRESS, where CPython binds
    the decoy -- an effect attributed to a module the lookup never reaches, and
    the exact property the six pairs above are named after.

    The reader now DECLINES the name: it derives neither owner. That is
    under-derivation, which surfaces loudly in the painted-label direction,
    rather than over-derivation, which invents justification for a row. So the
    assertion is one-sided on purpose -- asserting the decoy's spawn here would
    be asserting a guess this reader is right not to make.
    """
    models = _tree(
        tmp_path,
        owner=EGRESS,
        decoy=SPAWN,
        facade="import sys as _s\n"
        "from daedalus import owner as _target\n"
        "from daedalus import decoy as _other\n"
        f"{_NESTED_REBINDS[name]}"
        "_s.modules[__name__] = _target\n",
        door=_ONE_CALL_DOOR,
    )
    derived = _effects(models, "daedalus.door:main")
    assert Effect.NETWORK_EGRESS not in derived, (
        f"a rebinding nested in `{name}` left the dead alias credited: the "
        f"reader derived {sorted(e.value for e in derived)} from a module the "
        f"lookup never reaches. A name this reader cannot follow in order must "
        f"be declined, not resolved to whichever line it happened to see."
    )


#: Every way a name can arrive from a module that cannot be parsed. Each one
#: was measured FAIL-OPEN before 2026-09-02: ``split`` never returns ``None``
#: for ``daedalus.owner.sink`` while ``daedalus`` is a modelled package -- the
#: parent absorbs the missing module as the remainder ``owner.sink`` -- so the
#: refusal that was keyed off ``split`` returning ``None`` could not fire. The
#: import statement's own module name is checked instead.
_UNREADABLE_ARRIVALS = {
    "whole-module alias": (
        {
            "shim": "import sys as _s\nfrom daedalus import owner as _o\n"
            "_s.modules[__name__] = _o\n",
        },
        "daedalus.shim.sink",
    ),
    "re-export locator": (
        {"facade": "from daedalus.owner import sink\n"},
        "daedalus.facade.sink",
    ),
    "re-export from a subpackage": (
        {"facade": "from daedalus.sub.owner import sink\n"},
        "daedalus.facade.sink",
    ),
    "module-class facade": (
        {
            "facade": "import sys\nfrom types import ModuleType\n"
            "from daedalus import owner as _owner\n"
            "class _F(ModuleType):\n"
            "    def __getattr__(self, name):\n        return getattr(_owner, name)\n"
            "_m = sys.modules[__name__]\n_m.__class__ = _F\n",
        },
        "daedalus.facade.sink",
    ),
    "PEP 562 table": (
        {
            "facade": "from importlib import import_module\n"
            "_E = {'sink': 'daedalus.owner'}\n"
            "def __getattr__(name):\n"
            "    t = _E.get(name)\n"
            "    if t is None:\n        raise AttributeError(name)\n"
            "    return getattr(import_module(t), name)\n",
        },
        "daedalus.facade.sink",
    ),
    "an ordinary import, no facade at all": (
        {"door": "from daedalus.owner import sink\n"},
        "daedalus.door.sink",
    ),
}


@pytest.mark.parametrize("name", sorted(_UNREADABLE_ARRIVALS))
def test_every_arrival_from_an_unparseable_owner_refuses(name, tmp_path):
    """No shape may absorb a module the model set could not read."""
    extra, query = _UNREADABLE_ARRIVALS[name]
    owner = "sub.owner" if "subpackage" in name else "owner"
    modules = {owner: EGRESS, **extra}
    if "subpackage" not in name:
        modules.setdefault("owner", EGRESS)
    _tree(tmp_path, **modules)
    target = tmp_path / "daedalus" / (owner.replace(".", "/") + ".py")
    target.write_bytes(b"\xef\xbb\xbf" + target.read_bytes())
    broken = {
        model.module: model for model in _models(tmp_path, ("daedalus",))[0]
    }
    assert f"daedalus.{owner}" not in broken, "the fixture's owner is still readable"

    with pytest.raises(FacadeResolutionError):
        Resolver(broken).resolve(query)


def test_an_incomplete_model_set_refuses_before_any_derivation(tmp_path):
    """The repo-level guarantee, above every individual hop.

    A per-hop check only fires where the missing module is NAMED by the hop.
    MEASURED before this refusal existed: BOM'ing ``daedalus/spine/cancel.py``
    silently removed PROCESS_CONTROL from cli.picker, cli.bootstrap and
    cli.ignition, and BOM'ing ``daedalus/offload.py`` silently removed
    NETWORK_EGRESS, SECRETS and SPEND from two more -- no refusal, just smaller
    answers. A hole the walk cannot see is indistinguishable from a function
    with no effects, so the model set refuses to be built with one in it.
    """
    _tree(tmp_path, owner=EGRESS, door="from daedalus.owner import sink\n")
    broken = tmp_path / "daedalus" / "owner.py"
    broken.write_bytes(b"\xef\xbb\xbf" + broken.read_bytes())

    with pytest.raises(FacadeResolutionError) as raised:
        registry_facades.models(tmp_path)
    assert "owner.py" in str(raised.value)


# --------------------------------------------------------------------------- #
# hooks this reader cannot read must be VISIBLE, not absent                    #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "shape",
    [
        "__getattr__ = _make_hook()\n",
        "try:\n    def __getattr__(name):\n        return getattr(_o, name)\nexcept Exception:\n    pass\n",
        "if True:\n    def __getattr__(name):\n        return getattr(_o, name)\n",
    ],
)
def test_a_hook_with_no_readable_def_is_counted_not_invisible(shape, tmp_path):
    """The census must see the hooks that are hardest to read.

    A ``__getattr__`` bound by assignment, or defined inside ``try:``/``if:``,
    leaves no ``def`` at module top level. Keying the "unreadable" flag off the
    presence of such a ``def`` made those modules invisible to the walk AND
    invisible to the census that exists to count invisible modules -- the hole
    sat exactly where it does the most damage.
    """
    models = _tree(
        tmp_path,
        owner=EGRESS,
        facade="from daedalus import owner as _o\n"
        "def _make_hook():\n    return lambda name: getattr(_o, name)\n" + shape,
    )
    facade = Resolver(models).facade("daedalus.facade")
    assert facade.unreadable_hook, (
        "a module-level __getattr__ this reader cannot interpret was neither "
        "read nor counted"
    )


def test_a_decorated_facade_class_is_not_credited(tmp_path):
    """A decorator can return anything, including a class without the hook.

    Crediting the ``__getattr__`` that is visible in the source would attribute
    the owner's effects to a facade Python may never have installed. The
    over-credit direction is the one that invents justification for a row.
    """
    models = _tree(
        tmp_path,
        owner=EGRESS,
        decoy=SPAWN,
        facade="import sys\nfrom types import ModuleType\n"
        "from daedalus import owner as _owner\n"
        "from daedalus import decoy as _decoy\n"
        "def strip(cls):\n    return ModuleType\n"
        "@strip\n"
        "class _F(ModuleType):\n"
        "    def __getattr__(self, name):\n        return getattr(_owner, name)\n"
        "_m = sys.modules[__name__]\n_m.__class__ = _F\n"
        "def sink():\n    _decoy.sink()\n",
        door="from daedalus import facade\ndef main():\n    facade.sink()\n",
    )
    assert Resolver(models).facade("daedalus.facade").fallback is None
    derived = _effects(models, "daedalus.door:main")
    assert Effect.NETWORK_EGRESS not in derived
    assert Effect.PROCESS_SPAWN in derived


def test_a_cycle_of_facades_terminates(tmp_path):
    """Two modules that alias each other must stop, not spin.

    This reader runs inside the g1 gate profile. A pathological tree that made
    it loop would not fail the gate -- it would HANG it, which is the one
    outcome an operator cannot read. Pinned rather than argued from the
    ``_seen`` guards, because a future hop is exactly the kind of change that
    adds a path around them.
    """
    models = _tree(
        tmp_path,
        a="import sys as _s\nfrom daedalus import b as _o\n_s.modules[__name__] = _o\n",
        b="import sys as _s\nfrom daedalus import a as _o\n_s.modules[__name__] = _o\n",
    )
    resolver = Resolver(models)
    assert resolver.resolve("daedalus.a.sink") == ("daedalus.b", "sink")
    assert resolver.method("daedalus.a", "Missing", "sink") is None


def test_an_unreadable_owner_outside_the_scanned_packages_is_not_an_error(tmp_path):
    """The refusal is aimed, not indiscriminate.

    Third-party and stdlib modules have no model and never did; raising on them
    would make the walk unusable and would teach the next reader to catch the
    exception, which is how a fail-closed hop becomes fail-open.
    """
    models = _tree(
        tmp_path,
        shim="import sys as _sys\nimport json as _owner\n"
        "_sys.modules[__name__] = _owner\n",
    )
    # No refusal, and no invented hop either: the name stays at the locator,
    # which has no function of that name, so the walk simply derives nothing
    # from it.
    assert Resolver(models).resolve("daedalus.shim.dumps") == (
        "daedalus.shim",
        "dumps",
    )


# --------------------------------------------------------------------------- #
# the blind spots stay counted                                                 #
# --------------------------------------------------------------------------- #
#: Modules whose module-level ``__getattr__`` the reader cannot interpret. It
#: contributes NOTHING for these rather than guessing, which is the honest
#: disposition -- but an uncounted blind spot is how a derivation stops
#: deriving, so the set is pinned. Adding a facade shape the reader cannot read
#: must be a decision someone writes down here, not a silent loss of coverage.
#:
#: MEASURED 2026-09-02 on this branch: exactly one, ``daedalus.kernel``. Its
#: two siblings ``daedalus.kernel.contracts`` and ``daedalus.kernel.policy``
#: share the ``_EXPORT_GROUPS`` table and ARE read; ``daedalus.kernel`` builds
#: the same table with a module-scope ``for`` loop that appends to an initially
#: empty dict rather than with a comprehension, which this reader does not
#: interpret. Its entries name submodules of ``daedalus.kernel`` that every
#: caller reaches as ordinary modules -- ``from daedalus.kernel import
#: attempt_execution`` is an import, not an attribute lookup through the hook --
#: so no door currently loses a witness to it. That is an argument, not a
#: permission: if a door starts reaching a sink through
#: ``daedalus.kernel.<name>`` as an attribute, this is where the loss happens.
UNREADABLE_HOOKS = {"daedalus.kernel.__init__"}


def test_the_unreadable_facade_hooks_are_counted_not_discovered():
    """A hook the reader cannot follow is named here or it is a regression."""
    unreadable = {
        module
        for module in registry_facades.models(ROOT)
        if registry_facades.resolver(ROOT).facade(module).unreadable_hook
    }
    assert unreadable == UNREADABLE_HOOKS, (
        "the set of module-level __getattr__ facades this reader cannot "
        f"interpret moved to {sorted(unreadable)}. Each one is a place the "
        "derivation stops without saying so. Teach the reader the shape, or "
        "add it here WITH the argument for why no door loses a witness to it."
    )
