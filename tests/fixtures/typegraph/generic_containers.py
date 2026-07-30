"""HAZARD: generics must not create a node per instantiation (TYGAR lesson).

``list[Item]``, ``dict[str, Item]`` and ``Mapping[str, list[Item]]`` are THREE
annotations over ONE nominal element type. A node per instantiation makes the
type vocabulary unbounded in the number of call sites instead of bounded by the
number of declarations; the edge must point at ``Item`` with the container shell
carried as an attribute.

``Mapping`` is also one of the MEASURED hub types in daedalus/ (three-digit
fan-in), which is why invariant I6 forbids wiring this layer into DSS diffusion
before the hub cap is measured: two unrelated functions that both accept a
``Mapping`` must not become two hops apart.
"""
from collections.abc import Mapping


class Item:
    sku: str


def first_item(items: list[Item]) -> Item:
    return items[0]


def by_sku(index: dict[str, Item]) -> int:
    return len(index)


def grouped(groups: Mapping[str, list[Item]]) -> int:
    return sum(len(v) for v in groups.values())


def nested_tuple(pairs: list[tuple[str, Item]]) -> int:
    return len(pairs)
