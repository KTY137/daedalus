"""Transport sinks for normalized runtime-shell records."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Iterable, Protocol

from .events import TransportRecord


class TransportSink(Protocol):
    async def publish(self, record: TransportRecord) -> None:
        """Persist or forward one lossless transport record."""


class InMemoryTransportSink:
    """Small deterministic sink for tests and embedded consumers."""

    def __init__(self) -> None:
        self.records: list[TransportRecord] = []

    async def publish(self, record: TransportRecord) -> None:
        self.records.append(record)


class JsonlTransportSink:
    """Append-only JSONL journal preserving every normalized input/output."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = asyncio.Lock()

    async def publish(self, record: TransportRecord) -> None:
        line = json.dumps(record.to_dict(), ensure_ascii=False, default=str)
        async with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")


class CompositeTransportSink:
    """Fan one record out to multiple sinks; failures remain visible."""

    def __init__(self, sinks: Iterable[TransportSink]) -> None:
        self.sinks = tuple(sinks)

    async def publish(self, record: TransportRecord) -> None:
        for sink in self.sinks:
            await sink.publish(record)
