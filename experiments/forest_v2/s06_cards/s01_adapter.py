"""EXPERIMENT s06: adapter from an upstream node stream (slice s01) to card records.

s01's concrete key names were NOT available when this slice was built — its
worktree still sat on the shared base ``d849c2a9`` with no output.  Guessing
silently would be the dishonest option, so the adapter does the opposite:

* it declares the aliases it accepts per field (``FIELD_ALIASES``);
* it maps a stream line by line into ``forest-v2-node-record/1``;
* it **fails loudly** with the offending line number and the missing field
  when a line does not satisfy the contract, instead of emitting a card with
  invented values.

That means the day s01 lands, the integration is a one-line alias addition or
a green run — never a silent mismatch that a size histogram would hide.

Read-only, pure stdlib, no repository imports, no writes, no network, no
subprocess.
"""
from __future__ import annotations

import json
from typing import Iterable, Iterator

from node_cards import RECORD_SCHEMA, validate_record

#: target field -> accepted upstream key names, in priority order.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "plane": ("plane", "layer"),
    "kind": ("kind", "node_kind", "type", "symbol_kind"),
    "path": ("path", "file", "rel_path", "source_path"),
    "qualname": ("qualname", "qualified_name", "fqn", "name"),
    "start_line": ("start_line", "lineno", "line", "start"),
    "end_line": ("end_line", "end_lineno", "end"),
    "ordinal": ("ordinal", "index"),
    "signature": ("signature", "sig"),
    "doc": ("doc", "docstring", "summary"),
    "text": ("text", "source", "body", "segment"),
    "source_sha256": ("source_sha256", "file_sha256", "digest"),
    "neighbors": ("neighbors", "edges", "neighbourhood"),
}

REQUIRED = ("plane", "kind", "path", "qualname", "start_line", "end_line")


class AdapterError(ValueError):
    """Raised when an upstream line cannot be mapped without inventing data."""


def _pick(raw: dict, field: str):
    for alias in FIELD_ALIASES[field]:
        if alias in raw and raw[alias] not in (None, ""):
            return raw[alias]
    return None


def adapt_record(raw: dict, *, line_no: int = 0) -> dict:
    """Map one upstream dict onto ``forest-v2-node-record/1``."""
    record: dict = {}
    for field in FIELD_ALIASES:
        value = _pick(raw, field)
        if value is not None:
            record[field] = value
    missing = [field for field in REQUIRED if field not in record]
    if missing:
        raise AdapterError(
            f"line {line_no}: cannot map upstream node to {RECORD_SCHEMA}; "
            f"missing {missing}; keys seen: {sorted(raw)}"
        )
    for field in ("start_line", "end_line", "ordinal"):
        if field in record:
            try:
                record[field] = int(record[field])
            except (TypeError, ValueError) as exc:
                raise AdapterError(f"line {line_no}: {field} not an int") from exc
    problems = validate_record(record)
    if problems:
        raise AdapterError(f"line {line_no}: " + "; ".join(problems))
    return record


def adapt_stream(lines: Iterable[str]) -> Iterator[dict]:
    """Map a JSONL node stream.  Blank lines are skipped; bad JSON raises."""
    for line_no, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            raw = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise AdapterError(f"line {line_no}: not JSON ({exc.msg})") from exc
        if not isinstance(raw, dict):
            raise AdapterError(f"line {line_no}: expected a JSON object")
        yield adapt_record(raw, line_no=line_no)
