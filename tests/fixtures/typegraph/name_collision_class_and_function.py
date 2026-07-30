"""HAZARD I2a — a class and a function with the SAME name, in one file.

``graph.build_resolver`` fills ``defs_by_file`` with ``bucket.setdefault(u.name,
u)`` -- FIRST definition wins -- and ``ast.walk`` yields the module's children in
source order, so the ``ClassDef`` comes first. Put classes into ``defs_by_file``
and the class ``Foo`` DISPLACES the function ``Foo`` for every ``resolve`` call
made from this file and from every file that imports it. The call edge does not
merely change target: it points at something that is not callable code.

The rebinding below is legal Python (the ``def`` wins at runtime, the class
becomes unreachable) and is exactly the static ambiguity the resolver cannot
see. ``Foo`` must stay a FUNCTION in ``defs_by_file``.
"""


class Foo:
    """The class named Foo. Declared FIRST -- which is what makes it dangerous."""

    payload: str


def Foo(value: str) -> str:  # noqa: F811 -- the collision IS the fixture
    """The function named Foo. This is the one ``defs_by_file`` must hold."""
    return value.upper()


def call_foo(value: str) -> str:
    return Foo(value)
