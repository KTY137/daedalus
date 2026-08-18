"""EXPERIMENT (forest_v2 / slice s01): tests for the code-plane resolver.

Runnable directly::

    python -m pytest experiments/forest_v2/s01_resolution/test_s01_resolver.py -q

Every fixture is a throwaway source tree under pytest's ``tmp_path``; nothing
here reads or writes the repository, imports production code, or executes the
fixtures.  The resolver only ever parses text.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
for _extra in (_HERE, _HERE.parent):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

from s01_index import build_index  # noqa: E402
from s01_measure import audit_definition, rotation_map  # noqa: E402
from s01_resolver import Options, Resolution, resolve_module  # noqa: E402


class Tree:
    """A fixture source tree plus the resolutions the resolver produced for it."""

    def __init__(self, root: Path, options: Options | None = None) -> None:
        self.root = root
        self.index = build_index(root, ("pkg",))
        self.by_site: dict[tuple[str, int], list[Resolution]] = {}
        for module in self.index.modules.values():
            for _node, res in resolve_module(
                self.index, module, options or Options()
            ):
                self.by_site.setdefault((res.site_rel, res.site_line), []).append(res)

    def at(self, rel: str, line: int) -> Resolution:
        found = self.by_site.get((rel, line))
        assert found, f"no call site recorded at {rel}:{line}"
        return found[0]

    def all_of(self, rel: str, line: int) -> list[Resolution]:
        return self.by_site.get((rel, line), [])

    def kinds(self) -> list[str]:
        return [r.kind for group in self.by_site.values() for r in group]

    def verified(self) -> int:
        return sum(
            1 for group in self.by_site.values() for r in group if r.status == "verified"
        )


def build(tmp_path: Path, files: dict[str, str], options: Options | None = None) -> Tree:
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return Tree(tmp_path, options)


# ---------------------------------------------------------------- imports ----
def test_cross_module_import_resolves_to_the_definition(tmp_path: Path) -> None:
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/lib.py": "def helper():\n    return 1\n",
            "pkg/app.py": "from pkg.lib import helper\n\n\ndef run():\n    return helper()\n",
        },
    )
    res = tree.at("pkg/app.py", 5)
    assert res.status == "verified"
    assert res.kind == "import_repo"
    assert res.target == "pkg.lib.helper"
    assert (res.target_rel, res.target_line) == ("pkg/lib.py", 1)


def test_reexport_chain_is_followed_to_the_defining_module(tmp_path: Path) -> None:
    """``pkg.facade`` only re-exports; the definition lives in ``pkg.deep``."""
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/deep.py": "def worker():\n    return 2\n",
            "pkg/facade.py": "from pkg.deep import worker\n",
            "pkg/app.py": "from pkg.facade import worker\n\n\ndef run():\n    return worker()\n",
        },
    )
    res = tree.at("pkg/app.py", 5)
    assert res.status == "verified"
    assert res.target == "pkg.deep.worker"
    assert res.target_rel == "pkg/deep.py"


def test_relative_import_resolves(tmp_path: Path) -> None:
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/lib.py": "def helper():\n    return 1\n",
            "pkg/app.py": "from .lib import helper\n\n\ndef run():\n    return helper()\n",
        },
    )
    assert tree.at("pkg/app.py", 5).target == "pkg.lib.helper"


def test_function_level_import_is_seen(tmp_path: Path) -> None:
    """The sink pattern the pre-study flagged: the import is inside the body."""
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/lib.py": "def sink():\n    return 1\n",
            "pkg/app.py": "def run():\n    from pkg.lib import sink\n\n    return sink()\n",
        },
    )
    assert tree.at("pkg/app.py", 4).target == "pkg.lib.sink"


def test_module_attribute_call_resolves(tmp_path: Path) -> None:
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/lib.py": "def helper():\n    return 1\n",
            "pkg/app.py": "import pkg.lib\n\n\ndef run():\n    return pkg.lib.helper()\n",
        },
    )
    res = tree.at("pkg/app.py", 5)
    assert res.kind == "module_attr_repo"
    assert res.target == "pkg.lib.helper"


def test_conditional_module_level_definition_is_indexed(tmp_path: Path) -> None:
    """``try: import x / except ImportError: def x()`` binds at module level."""
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/lib.py": (
                "try:\n"
                "    from nowhere import fallback\n"
                "except ImportError:\n"
                "    def fallback():\n"
                "        return 0\n"
            ),
            "pkg/app.py": "from pkg.lib import fallback\n\n\ndef run():\n    return fallback()\n",
        },
    )
    res = tree.at("pkg/app.py", 5)
    assert res.status == "verified"
    assert res.target_rel == "pkg/lib.py"


def test_external_import_is_claimed_not_verified(tmp_path: Path) -> None:
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/app.py": "import json\n\n\ndef run():\n    return json.dumps({})\n",
        },
    )
    res = tree.at("pkg/app.py", 5)
    assert res.status == "external"
    assert res.target == "json.dumps"
    assert res.target_rel == ""


# --------------------------------------------------------------- methods -----
def test_self_method_resolves_within_the_class(tmp_path: Path) -> None:
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/app.py": (
                "class Worker:\n"
                "    def step(self):\n"
                "        return 1\n"
                "\n"
                "    def run(self):\n"
                "        return self.step()\n"
            ),
        },
    )
    res = tree.at("pkg/app.py", 6)
    assert res.status == "verified"
    assert res.kind == "self_method"
    assert res.target == "pkg.app.Worker.step"
    assert res.target_line == 2


def test_inherited_method_resolves_across_modules(tmp_path: Path) -> None:
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/base.py": "class Base:\n    def shared(self):\n        return 1\n",
            "pkg/app.py": (
                "from pkg.base import Base\n"
                "\n"
                "\n"
                "class Child(Base):\n"
                "    def run(self):\n"
                "        return self.shared()\n"
            ),
        },
    )
    res = tree.at("pkg/app.py", 6)
    assert res.status == "verified"
    assert res.target == "pkg.base.Base.shared"
    assert res.target_rel == "pkg/base.py"


def test_super_call_resolves_to_the_base(tmp_path: Path) -> None:
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/app.py": (
                "class Base:\n"
                "    def run(self):\n"
                "        return 1\n"
                "\n"
                "\n"
                "class Child(Base):\n"
                "    def run(self):\n"
                "        return super().run()\n"
            ),
        },
    )
    res = tree.at("pkg/app.py", 8)
    assert res.kind == "super_method"
    assert res.target == "pkg.app.Base.run"


def test_unseen_base_class_is_external_not_verified(tmp_path: Path) -> None:
    """The subclass-evasion shape: a base we cannot read stays a claim."""
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/app.py": (
                "from http.server import ThreadingHTTPServer\n"
                "\n"
                "\n"
                "class Server(ThreadingHTTPServer):\n"
                "    def go(self):\n"
                "        return self.serve_forever()\n"
            ),
        },
    )
    res = tree.at("pkg/app.py", 6)
    assert res.status == "external"
    assert res.kind == "self_method_external_base"
    assert "serve_forever" in res.target


def test_classmethod_cls_constructs_and_dispatches(tmp_path: Path) -> None:
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/app.py": (
                "class Thing:\n"
                "    @classmethod\n"
                "    def make(cls):\n"
                "        return cls()\n"
                "\n"
                "    @classmethod\n"
                "    def other(cls):\n"
                "        return cls.make()\n"
            ),
        },
    )
    assert tree.at("pkg/app.py", 4).kind == "local_class"
    assert tree.at("pkg/app.py", 8).kind == "cls_method"


def test_staticmethod_first_argument_is_not_self(tmp_path: Path) -> None:
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/app.py": (
                "class Thing:\n"
                "    def step(self):\n"
                "        return 1\n"
                "\n"
                "    @staticmethod\n"
                "    def helper(self):\n"
                "        return self.step()\n"
            ),
        },
    )
    assert tree.at("pkg/app.py", 7).status == "unresolved"


# ------------------------------------------------------- receiver typing -----
def test_local_variable_type_from_constructor(tmp_path: Path) -> None:
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/lib.py": "class Engine:\n    def start(self):\n        return 1\n",
            "pkg/app.py": (
                "from pkg.lib import Engine\n"
                "\n"
                "\n"
                "def run():\n"
                "    engine = Engine()\n"
                "    return engine.start()\n"
            ),
        },
    )
    res = tree.at("pkg/app.py", 6)
    assert res.kind == "local_var_method"
    assert res.origin == "assign"
    assert res.target == "pkg.lib.Engine.start"


def test_annotated_parameter_type(tmp_path: Path) -> None:
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/lib.py": "class Engine:\n    def start(self):\n        return 1\n",
            "pkg/app.py": (
                "from pkg.lib import Engine\n"
                "\n"
                "\n"
                "def run(engine: Engine):\n"
                "    return engine.start()\n"
            ),
        },
    )
    res = tree.at("pkg/app.py", 5)
    assert res.origin == "param_annotation"
    assert res.target == "pkg.lib.Engine.start"


def test_instance_attribute_type_from_constructor(tmp_path: Path) -> None:
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/lib.py": "class Engine:\n    def start(self):\n        return 1\n",
            "pkg/app.py": (
                "from pkg.lib import Engine\n"
                "\n"
                "\n"
                "class App:\n"
                "    def __init__(self):\n"
                "        self.engine = Engine()\n"
                "\n"
                "    def run(self):\n"
                "        return self.engine.start()\n"
            ),
        },
    )
    res = tree.at("pkg/app.py", 9)
    assert res.kind == "self_attr_method"
    assert res.target == "pkg.lib.Engine.start"


def test_reassignment_to_an_unknown_value_drops_the_type(tmp_path: Path) -> None:
    """A receiver whose type we cannot know must not inherit a stale one."""
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/lib.py": "class Engine:\n    def start(self):\n        return 1\n",
            "pkg/app.py": (
                "from pkg.lib import Engine\n"
                "\n"
                "\n"
                "def run(source):\n"
                "    engine = source.build()\n"
                "    return engine.start()\n"
            ),
        },
    )
    assert tree.at("pkg/app.py", 6).status == "unresolved"


# ----------------------------------------------------------- scoping ---------
def test_local_binding_shadows_an_import(tmp_path: Path) -> None:
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/lib.py": "def helper():\n    return 1\n",
            "pkg/app.py": (
                "from pkg.lib import helper\n"
                "\n"
                "\n"
                "def run(source):\n"
                "    helper = source.pick()\n"
                "    return helper()\n"
            ),
        },
    )
    res = tree.at("pkg/app.py", 6)
    assert res.status == "unresolved", "a shadowed name must not keep the import target"


def test_nested_function_definition_resolves(tmp_path: Path) -> None:
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/app.py": (
                "def run():\n"
                "    def emit():\n"
                "        return 1\n"
                "\n"
                "    return emit()\n"
            ),
        },
    )
    res = tree.at("pkg/app.py", 5)
    assert res.status == "verified"
    assert res.target_line == 2


def test_same_name_method_on_a_foreign_receiver_is_not_claimed(tmp_path: Path) -> None:
    """The pre-study's over-claim, made explicit.

    The baseline probe matches the last dotted segment against every method name
    in the file, so a local ``read_text`` method makes ``path.read_text()`` look
    same-module resolvable.  The resolver must refuse that.
    """
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/app.py": (
                "from pathlib import Path\n"
                "\n"
                "\n"
                "class Loader:\n"
                "    def read_text(self):\n"
                "        return ''\n"
                "\n"
                "\n"
                "def run(path: Path):\n"
                "    return path.read_text()\n"
            ),
        },
    )
    res = tree.at("pkg/app.py", 10)
    assert res.status != "verified"
    assert res.target != "pkg.app.Loader.read_text"


# ------------------------------------------------- named failure reasons -----
@pytest.mark.parametrize(
    "body, expected",
    [
        # a subscript in call position is not a Name/Attribute at all, so it
        # lands in the same shape bucket the pre-study probe uses
        ("    return TABLE[key]()", "unresolvable_shape"),
        # a subscript as the *receiver* is the dispatch-table shape
        ("    return TABLE[key].run()", "subscript_receiver"),
        ("    return make().run()", "call_result_receiver"),
        ("    return value.run()", "untyped_local_receiver"),
        ("    return ''.join([])", "literal_receiver"),
    ],
)
def test_failure_reasons_are_named(tmp_path: Path, body: str, expected: str) -> None:
    source = (
        "TABLE = {}\n"
        "\n"
        "\n"
        "def make():\n"
        "    return None\n"
        "\n"
        "\n"
        "def run(key, value):\n"
        f"{body}\n"
    )
    tree = build(tmp_path, {"pkg/__init__.py": "", "pkg/app.py": source})
    res = tree.at("pkg/app.py", 9)
    assert res.status == "unresolved"
    assert res.kind == expected


# --------------------------------------------------- structural guarantees ---
def test_every_call_node_is_visited_exactly_once(tmp_path: Path) -> None:
    """Call-site parity: the denominator must match a plain ``ast.walk`` count."""
    source = (
        "import json\n"
        "\n"
        "\n"
        "@staticmethod\n"
        "def decorated(a=len([]), *, b=str()):\n"
        "    fn = lambda x=int(): x\n"
        "    return [json.dumps(i) for i in range(3)] + [fn()]\n"
        "\n"
        "\n"
        "class Thing(dict):\n"
        "    field: str = str()\n"
        "\n"
        "    def go(self) -> str:\n"
        "        with open('x') as handle:\n"
        "            return handle.read()\n"
    )
    tree = build(tmp_path, {"pkg/__init__.py": "", "pkg/app.py": source})
    module = tree.index.modules["pkg.app"]
    expected = sum(1 for node in ast.walk(module.tree) if isinstance(node, ast.Call))
    resolved = sum(len(group) for group in tree.by_site.values())
    assert resolved == expected


def test_verified_targets_survive_the_definition_audit(tmp_path: Path) -> None:
    tree = build(
        tmp_path,
        {
            "pkg/__init__.py": "",
            "pkg/base.py": "class Base:\n    def shared(self):\n        return 1\n",
            "pkg/app.py": (
                "from pkg.base import Base\n"
                "\n"
                "\n"
                "class Child(Base):\n"
                "    def run(self):\n"
                "        return self.shared()\n"
                "\n"
                "\n"
                "def go():\n"
                "    child = Child()\n"
                "    return child.run()\n"
            ),
        },
    )
    cache: dict = {}
    checked = 0
    for group in tree.by_site.values():
        for res in group:
            if res.status != "verified":
                continue
            checked += 1
            verdict = audit_definition(
                tree.root, res.target, res.target_rel, res.target_line, cache
            )
            assert verdict == "def", f"{res.target} at {res.target_rel}:{res.target_line}"
    assert checked >= 3


def test_control_destroys_import_derived_verification(tmp_path: Path) -> None:
    """The randomised control must actually break something.

    Local resolution is untouched by the control; import-derived resolution must
    collapse.  If both survive, the resolver was matching names.
    """
    files = {
        "pkg/__init__.py": "",
        "pkg/lib.py": "def helper():\n    return 1\n",
        "pkg/other.py": "def unrelated():\n    return 2\n",
        "pkg/app.py": (
            "from pkg.lib import helper\n"
            "\n"
            "\n"
            "def local():\n"
            "    return 3\n"
            "\n"
            "\n"
            "def run():\n"
            "    return helper() + local()\n"
        ),
    }
    honest = build(tmp_path, files)
    mapping = rotation_map(honest.index, rotate=1)
    controlled = build(tmp_path, files, Options(module_map=mapping))

    honest_kinds = {r.kind for r in honest.all_of("pkg/app.py", 9)}
    control_kinds = {r.kind for r in controlled.all_of("pkg/app.py", 9)}
    assert "import_repo" in honest_kinds
    assert "local_function" in honest_kinds
    assert "import_repo" not in control_kinds, "the control failed to break the binding"
    assert "local_function" in control_kinds, "the control must not touch local resolution"
    assert controlled.verified() < honest.verified()


def test_ablations_never_increase_verification(tmp_path: Path) -> None:
    files = {
        "pkg/__init__.py": "",
        "pkg/base.py": "class Base:\n    def shared(self):\n        return 1\n",
        "pkg/app.py": (
            "from pkg.base import Base\n"
            "\n"
            "\n"
            "class Child(Base):\n"
            "    def run(self):\n"
            "        return self.shared()\n"
            "\n"
            "\n"
            "def go(child: Child):\n"
            "    return child.run()\n"
        ),
    }
    full = build(tmp_path, files).verified()
    for options in (
        Options(use_imports=False),
        Options(use_hierarchy=False),
        Options(use_receiver_types=False),
    ):
        assert build(tmp_path, files, options).verified() <= full
