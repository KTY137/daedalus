"""Explicit, caller-supplied context for Hermes; no ambient file discovery."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from typing import Iterable, Mapping


class HermesContextError(ValueError):
    pass


@dataclass(frozen=True)
class ContextFragment:
    name: str
    content: str
    media_type: str = "text/plain"

    def __post_init__(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise HermesContextError("context fragment name is required")
        if not isinstance(self.content, str):
            raise HermesContextError("context fragment content must be text")
        if not self.media_type or not isinstance(self.media_type, str):
            raise HermesContextError("context fragment media_type is required")

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class ExplicitContextProvider:
    def __init__(self, fragments: Iterable[ContextFragment] = (), *, max_characters: int = 200_000) -> None:
        if not 0 <= max_characters <= 4_000_000:
            raise HermesContextError("context character budget is outside the accepted range")
        materialized = tuple(fragments)
        names = [fragment.name for fragment in materialized]
        if len(names) != len(set(names)):
            raise HermesContextError("context fragment names must be unique")
        if sum(len(fragment.content) for fragment in materialized) > max_characters:
            raise HermesContextError("explicit context exceeds its character budget")
        self._fragments = materialized
        self._max_characters = max_characters

    @property
    def fragments(self) -> tuple[ContextFragment, ...]:
        return self._fragments

    def render(self) -> str:
        blocks: list[str] = []
        for fragment in self._fragments:
            blocks.append(f"<daedalus-context name={json.dumps(fragment.name)} media_type={json.dumps(fragment.media_type)}>\n{fragment.content}\n</daedalus-context>")
        return "\n\n".join(blocks)

    def to_metadata(self) -> dict[str, object]:
        return {
            "schema": "daedalus-hermes-context/1",
            "max_characters": self._max_characters,
            "fragments": [fragment.to_dict() for fragment in self._fragments],
            "digest": self.digest,
        }

    @classmethod
    def from_metadata(cls, value: Mapping[str, object]) -> "ExplicitContextProvider":
        if set(value) != {"schema", "max_characters", "fragments", "digest"}:
            raise HermesContextError("context metadata fields are not exact")
        if value["schema"] != "daedalus-hermes-context/1":
            raise HermesContextError("context schema mismatch")
        raw = value["fragments"]
        if not isinstance(raw, list):
            raise HermesContextError("context fragments must be a list")
        fragments: list[ContextFragment] = []
        for item in raw:
            if not isinstance(item, Mapping) or set(item) != {"name", "content", "media_type"}:
                raise HermesContextError("context fragment fields are not exact")
            fragments.append(ContextFragment(name=str(item["name"]), content=str(item["content"]), media_type=str(item["media_type"])))
        provider = cls(fragments, max_characters=int(value["max_characters"]))
        if value["digest"] != provider.digest:
            raise HermesContextError("context digest mismatch")
        return provider

    @property
    def digest(self) -> str:
        payload = {
            "max_characters": self._max_characters,
            "fragments": [fragment.to_dict() for fragment in self._fragments],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        return sha256(encoded).hexdigest()
