"""Bounded, pure-stdlib S-expression reader for KiCad artifacts.

This module is intentionally dependency-free and effect-free. It never imports
``pcbnew``, never starts a process, and never writes. Every input is treated as
untrusted: size, nesting depth and node count are bounded before the reader
allocates a tree, and every rejection is a *typed* :class:`PcbRefusal` with a
frozen reason code rather than a stack trace or a silent partial parse.

The grammar accepted here is the KiCad dialect, not general Lisp: a file is one
list; atoms are bare tokens or double-quoted strings; comments are not part of
the dialect and are therefore not accepted. Unknown string escapes are refused
instead of being guessed, because a guessed escape changes bytes that later
become an identity.
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

__all__ = [
    "ABSOLUTE_MAX_BYTES",
    "Atom",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_NODES",
    "PcbRefusal",
    "REFUSAL_REASONS",
    "ReadArtifact",
    "args",
    "first",
    "head",
    "parse",
    "parse_bytes",
    "read_artifact",
    "sublists",
    "to_float",
]


# Frozen refusal vocabulary. A caller may switch on these; they are contract.
REFUSAL_REASONS: tuple[str, ...] = (
    "not_a_file",
    "unreadable",
    "input_too_large",
    "max_bytes_out_of_range",
    "invalid_encoding",
    "malformed_sexpr",
    "depth_exceeded",
    "node_budget_exceeded",
    "unsupported_suffix",
    "unexpected_root",
    "unsupported_format_version",
)

DEFAULT_MAX_BYTES = 32 * 1024 * 1024
ABSOLUTE_MAX_BYTES = 256 * 1024 * 1024
DEFAULT_MAX_DEPTH = 200
DEFAULT_MAX_NODES = 1_000_000


class PcbRefusal(Exception):
    """A typed, reportable refusal.

    The reason is a member of :data:`REFUSAL_REASONS`; ``detail`` explains the
    concrete measurement. Refusals are values, not accidents: they serialize
    into the JSON report so a caller sees *why* an artifact was not inspected.
    """

    def __init__(self, reason: str, detail: str = "", **context: object) -> None:
        if reason not in REFUSAL_REASONS:
            raise ValueError(f"unknown refusal reason: {reason!r}")
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail
        self.context: dict[str, object] = dict(context)

    def to_dict(self) -> dict[str, object]:
        return {
            "refused": True,
            "reason": self.reason,
            "detail": self.detail,
            "context": dict(sorted(self.context.items())),
        }


@dataclass(frozen=True, slots=True)
class Atom:
    """One S-expression atom.

    ``quoted`` is retained because the KiCad dialect distinguishes the keyword
    ``signal`` from the string ``"signal"``; collapsing them would lose the
    only evidence of which one the generator wrote.
    """

    text: str
    quoted: bool


# A parsed list is a tuple of atoms and nested tuples.
SExpr = tuple[object, ...]

_WHITESPACE = " \t\r\n\f\v"
_ATOM_STOP = set(_WHITESPACE) | {"(", ")", '"'}
_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t", "r": "\r"}


def _read_quoted(text: str, start: int) -> tuple[str, int]:
    size = len(text)
    index = start + 1
    out: list[str] = []
    while index < size:
        char = text[index]
        if char == '"':
            return "".join(out), index + 1
        if char == "\\":
            if index + 1 >= size:
                raise PcbRefusal(
                    "malformed_sexpr", "unterminated string escape", offset=index
                )
            mapped = _ESCAPES.get(text[index + 1])
            if mapped is None:
                raise PcbRefusal(
                    "malformed_sexpr",
                    f"unknown string escape \\{text[index + 1]!r}",
                    offset=index,
                )
            out.append(mapped)
            index += 2
            continue
        out.append(char)
        index += 1
    raise PcbRefusal("malformed_sexpr", "unterminated string", offset=start)


def parse(
    text: str,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_nodes: int = DEFAULT_MAX_NODES,
) -> SExpr:
    """Parse exactly one S-expression and refuse anything else.

    The scanner is iterative on an explicit stack, so a hostile nesting depth
    is answered by ``depth_exceeded`` rather than by a Python recursion crash.
    """

    if max_depth < 1:
        raise ValueError("max_depth must be >= 1")
    if max_nodes < 1:
        raise ValueError("max_nodes must be >= 1")

    size = len(text)
    index = 0
    stack: list[list[object]] = []
    root: SExpr | None = None
    nodes = 0

    while index < size:
        char = text[index]
        if char in _WHITESPACE:
            index += 1
            continue
        if root is not None:
            raise PcbRefusal(
                "malformed_sexpr", "content after the root expression", offset=index
            )
        if char == "(":
            stack.append([])
            if len(stack) > max_depth:
                raise PcbRefusal(
                    "depth_exceeded",
                    f"nesting deeper than {max_depth}",
                    offset=index,
                    max_depth=max_depth,
                )
            index += 1
            continue
        if char == ")":
            if not stack:
                raise PcbRefusal(
                    "malformed_sexpr", "unbalanced closing parenthesis", offset=index
                )
            finished = tuple(stack.pop())
            nodes += 1
            if nodes > max_nodes:
                raise PcbRefusal(
                    "node_budget_exceeded",
                    f"more than {max_nodes} nodes",
                    max_nodes=max_nodes,
                )
            if stack:
                stack[-1].append(finished)
            else:
                root = finished
            index += 1
            continue
        if not stack:
            raise PcbRefusal(
                "malformed_sexpr", "atom outside any expression", offset=index
            )
        if char == '"':
            value, index = _read_quoted(text, index)
            stack[-1].append(Atom(value, True))
        else:
            end = index
            while end < size and text[end] not in _ATOM_STOP:
                end += 1
            stack[-1].append(Atom(text[index:end], False))
            index = end
        nodes += 1
        if nodes > max_nodes:
            raise PcbRefusal(
                "node_budget_exceeded", f"more than {max_nodes} nodes", max_nodes=max_nodes
            )

    if stack:
        raise PcbRefusal(
            "malformed_sexpr", f"{len(stack)} unterminated expression(s)", depth=len(stack)
        )
    if root is None:
        raise PcbRefusal("malformed_sexpr", "no expression found")
    return root


def parse_bytes(
    data: bytes,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_nodes: int = DEFAULT_MAX_NODES,
) -> SExpr:
    """Decode UTF-8 (tolerating a BOM) and parse. Encoding errors are typed."""

    payload = data[3:] if data.startswith(b"\xef\xbb\xbf") else data
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PcbRefusal(
            "invalid_encoding",
            f"not UTF-8 at byte {exc.start}: {exc.reason}",
            offset=exc.start,
        ) from exc
    return parse(text, max_depth=max_depth, max_nodes=max_nodes)


@dataclass(frozen=True, slots=True)
class ReadArtifact:
    """Bytes of one artifact plus its deterministic identity."""

    name: str
    size_bytes: int
    sha256: str
    data: bytes

    def identity(self) -> dict[str, object]:
        return {"name": self.name, "size_bytes": self.size_bytes, "sha256": self.sha256}


def read_artifact(
    path: str | os.PathLike[str], *, max_bytes: int = DEFAULT_MAX_BYTES
) -> ReadArtifact:
    """Read one file under an explicit byte bound. Reads only; never writes.

    The size is measured with ``stat`` before the read, so an oversized file is
    refused without being pulled into memory first.
    """

    if max_bytes < 1 or max_bytes > ABSOLUTE_MAX_BYTES:
        raise PcbRefusal(
            "max_bytes_out_of_range",
            f"max_bytes must be in 1..{ABSOLUTE_MAX_BYTES}",
            max_bytes=max_bytes,
            absolute_max_bytes=ABSOLUTE_MAX_BYTES,
        )
    candidate = Path(path)
    try:
        stat = candidate.stat()
    except OSError as exc:
        raise PcbRefusal("not_a_file", f"cannot stat {candidate.name}: {exc.strerror or exc}") from exc
    if not candidate.is_file():
        raise PcbRefusal("not_a_file", f"{candidate.name} is not a regular file")
    if stat.st_size > max_bytes:
        raise PcbRefusal(
            "input_too_large",
            f"{stat.st_size} bytes exceeds the {max_bytes} byte bound",
            size_bytes=stat.st_size,
            max_bytes=max_bytes,
        )
    try:
        data = candidate.read_bytes()
    except OSError as exc:
        raise PcbRefusal("unreadable", f"cannot read {candidate.name}: {exc.strerror or exc}") from exc
    if len(data) > max_bytes:
        # The file grew between stat and read; refuse rather than truncate.
        raise PcbRefusal(
            "input_too_large",
            f"{len(data)} bytes exceeds the {max_bytes} byte bound after read",
            size_bytes=len(data),
            max_bytes=max_bytes,
        )
    return ReadArtifact(
        name=candidate.name,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        data=data,
    )


# ---------------------------------------------------------------------------
# Accessors. Deliberately tiny: the reports do the interpreting, not the tree.
# ---------------------------------------------------------------------------


def head(node: object) -> str:
    """Head symbol of a list, or ``""`` for an atom or an empty list."""

    if isinstance(node, tuple) and node and isinstance(node[0], Atom):
        return node[0].text
    return ""


def sublists(node: SExpr, name: str | None = None) -> Iterator[SExpr]:
    """Yield nested lists of ``node``, optionally filtered by head symbol."""

    for item in node:
        if isinstance(item, tuple) and (name is None or head(item) == name):
            yield item


def first(node: SExpr, name: str) -> SExpr | None:
    return next(sublists(node, name), None)


def args(node: SExpr) -> tuple[str, ...]:
    """Atom texts after the head symbol, in source order."""

    return tuple(
        item.text
        for index, item in enumerate(node)
        if index > 0 and isinstance(item, Atom)
    )


def to_float(text: str) -> float | None:
    """Parse a finite number, or ``None``.

    ``nan`` and ``inf`` parse in Python but are not coordinates; accepting them
    would let a hostile file poison an extents computation, so they are treated
    as unparseable.
    """

    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value
