"""Read-only, bounded memory snapshot supplied by the Daedalus caller."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Iterable, Mapping


class HermesMemoryError(ValueError):
    pass


@dataclass(frozen=True)
class MemoryRecord:
    record_id: str
    text: str
    source_digest: str

    def __post_init__(self) -> None:
        if not self.record_id or not isinstance(self.record_id, str):
            raise HermesMemoryError("memory record_id is required")
        if not isinstance(self.text, str):
            raise HermesMemoryError("memory text must be a string")
        if not isinstance(self.source_digest, str) or len(self.source_digest) != 64:
            raise HermesMemoryError("memory source_digest must be SHA-256")
        try:
            int(self.source_digest, 16)
        except ValueError as exc:
            raise HermesMemoryError("memory source_digest must be hexadecimal") from exc

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class ReadOnlyMemoryProvider:
    def __init__(self, records: Iterable[MemoryRecord] = (), *, max_characters: int = 120_000) -> None:
        if not 0 <= max_characters <= 2_000_000:
            raise HermesMemoryError("memory character budget is outside the accepted range")
        materialized = tuple(records)
        ids = [record.record_id for record in materialized]
        if len(ids) != len(set(ids)):
            raise HermesMemoryError("memory record ids must be unique")
        if sum(len(record.text) for record in materialized) > max_characters:
            raise HermesMemoryError("memory snapshot exceeds its character budget")
        self._records = materialized
        self._max_characters = max_characters

    @property
    def records(self) -> tuple[MemoryRecord, ...]:
        return self._records

    def render(self) -> str:
        return "\n\n".join(
            f"<daedalus-memory id={json.dumps(record.record_id)} source_sha256={json.dumps(record.source_digest)}>\n{record.text}\n</daedalus-memory>"
            for record in self._records
        )

    def remember(self, *_args: object, **_kwargs: object) -> None:
        raise PermissionError("Hermes memory mutation is disabled; Daedalus owns canonical memory")

    def to_metadata(self) -> dict[str, object]:
        return {
            "schema": "daedalus-hermes-memory/1",
            "max_characters": self._max_characters,
            "records": [record.to_dict() for record in self._records],
            "digest": self.digest,
            "mutable": False,
        }

    @classmethod
    def from_metadata(cls, value: Mapping[str, object]) -> "ReadOnlyMemoryProvider":
        if set(value) != {"schema", "max_characters", "records", "digest", "mutable"}:
            raise HermesMemoryError("memory metadata fields are not exact")
        if value["schema"] != "daedalus-hermes-memory/1" or value["mutable"] is not False:
            raise HermesMemoryError("memory metadata is not a read-only Daedalus snapshot")
        raw = value["records"]
        if not isinstance(raw, list):
            raise HermesMemoryError("memory records must be a list")
        records: list[MemoryRecord] = []
        for item in raw:
            if not isinstance(item, Mapping) or set(item) != {"record_id", "text", "source_digest"}:
                raise HermesMemoryError("memory record fields are not exact")
            records.append(MemoryRecord(record_id=str(item["record_id"]), text=str(item["text"]), source_digest=str(item["source_digest"])))
        provider = cls(records, max_characters=int(value["max_characters"]))
        if value["digest"] != provider.digest:
            raise HermesMemoryError("memory digest mismatch")
        return provider

    @property
    def digest(self) -> str:
        payload = {
            "max_characters": self._max_characters,
            "records": [record.to_dict() for record in self._records],
            "mutable": False,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return sha256(encoded).hexdigest()
