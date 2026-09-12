"""Orders: what the Waiter understood from a sentence.

Deterministic, bilingual (German/English) recognition. This is an
*affordance* classifier for the kitchen: it decides which pipeline the Chef
would run, never whether the Chef may run it -- admission stays with the Chef
and the kernel policy it calls.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

KIND_BUILD = "build_app"
KIND_IMPROVE = "improve_app"
KIND_SELF = "self_improve"
KIND_FEED = "feed_ariadne"
KIND_STATUS = "kitchen_status"
KINDS = (KIND_BUILD, KIND_IMPROVE, KIND_SELF, KIND_FEED, KIND_STATUS)

_GERMAN_MARKERS = re.compile(
    r"\b(bau|baue|bitte|mir|eine|einen|ein|diese|dieses|dieser|das|den|der|die|mit|und|"
    r"verbessere|verbesser|erstelle|schreib|mach|füttere|fuettere|lerne|dich|selbst)\b",
    re.IGNORECASE,
)

# A Genesis ORDER is addressed to the kitchen: "bau MIR eine App", "build ME a
# tool", "ich brauche eine neue App". A bare imperative such as "entwickle ein
# CLI-Tool" remains the confirm-gated computer task of G1-IKARUS-46.
_BUILD_VERBS = (
    r"bau(?:e)?", r"erstell(?:e)?", r"schreib(?:e)?", r"generier(?:e)?", r"entwickl(?:e)?", r"mach(?:e)?",
    r"programmier(?:e)?", r"build", r"create", r"make", r"write", r"generate", r"develop", r"code",
)
_BUILD_NOUNS = (
    r"app", r"apps", r"anwendung", r"applikation", r"application", r"programm", r"program",
    r"tool", r"werkzeug", r"website", r"webseite", r"web\s*app", r"webapp",
    r"spiel", r"game", r"cli", r"api", r"skript", r"script", r"dashboard", r"bot",
    r"service", r"dienst", r"bibliothek", r"library", r"paket", r"package", r"prototyp",
    r"prototype", r"rechner", r"calculator", r"editor", r"viewer", r"server", r"client",
    r"plugin", r"extension", r"erweiterung",
)
_LEAD = r"^\W*(?:bitte\s+|please\s+|hey\s+ikarus[,\s]+|ikarus[,\s]+|ok\s+|okay\s+)*"
_BUILD_RE = re.compile(
    _LEAD + r"(?:%s)\s+(?:mir|uns|me|us)\b[^.!?\n]*?\b(?:%s)\b" % ("|".join(_BUILD_VERBS), "|".join(_BUILD_NOUNS)),
    re.IGNORECASE,
)
_BUILD_WISH_RE = re.compile(
    _LEAD + r"(?:ich\s+(?:will|möchte|moechte|brauche|hätte\s+gern|haette\s+gern|wünsche\s+mir)|i\s+(?:want|need|would\s+like)|"
    r"(?:%s)\s+(?:mir\s+|me\s+)?(?:eine?n?|a|an)?\s*(?:neue[sn]?|new|kleine?|small|simple|einfache?)\s+)"
    r"[^.!?\n]*?\b(?:%s)\b" % ("|".join(_BUILD_VERBS), "|".join(_BUILD_NOUNS)),
    re.IGNORECASE,
)

_IMPROVE_RE = re.compile(
    r"^\W*(?:bitte\s+|please\s+|hey\s+ikarus[,\s]+|ikarus[,\s]+)?"
    r"(?:verbesser(?:e)?|optimier(?:e)?|refactor(?:e|iere)?|refaktor(?:iere)?|erweiter(?:e)?|"
    r"repari(?:er|ere)|fix(?:e)?|bug\s*fix(?:e)?|härte|haerte|beschleunig(?:e)?|"
    r"improve|enhance|upgrade|optimi[sz]e|harden|speed\s+up|polish|clean\s+up|räum(?:e)?\s+auf)\b",
    re.IGNORECASE,
)
# Reflexive only: "verbessere Daedalus" stays a confirm-gated computer task
# (G1-IKARUS-46); the kitchen's self-Renovation needs "dich selbst"/"yourself".
_SELF_TARGET_RE = re.compile(
    r"\b(dich(?:\s+selbst|\s+selber)?|yourself|deinen?\s+(?:eigenen\s+)?(?:code|kernel|quellcode)|"
    r"your(?:\s+own)?\s+(?:code|source|kernel))\b",
    re.IGNORECASE,
)
# An improvement order names a WHOLE application or project (or a repository
# path/URL). "improve the parser" is a component task for the computer loop.
_IMPROVE_TARGET_RE = re.compile(
    r"\b(?:diese[smnr]?|dieser|die|das|this|the|my|mein[esrn]?|unsere?|our)\s+"
    r"(?:app|apps|anwendung|applikation|application|projekt|project|repo|repository|programm|program|tool|website|webseite|web\s*app)\b",
    re.IGNORECASE,
)
_FEED_RE = re.compile(
    r"(?:f(?:ü|ue)tter(?:e)?|feed|lern(?:e)?|learn|ingest(?:iere)?|indexier(?:e)?|index|"
    r"trainier(?:e)?|train|lies|lese|read|studier(?:e)?|study|absorb(?:iere)?)\b.{0,80}?"
    r"\b(?:ariadne|corpus|korpus|grey\s*matter|graue\s+masse|repo(?:s|sitor(?:y|ies|ien))?)\b"
    r"|\b(?:ariadne|grey\s*matter)\b.{0,40}?\b(?:f(?:ü|ue)ttern|feed|lernen|learn)\b",
    re.IGNORECASE,
)
_STATUS_RE = re.compile(
    r"^\W*(?:/kitchen|/küche|/kueche)\b|"
    r"\b(?:küche|kueche|kitchen|bestellung(?:en)?|orders?|chefkoch|chef|kellner|waiter)\b.{0,60}?"
    r"\b(?:status|stand|wie\s+weit|fortschritt|progress|läuft|laeuft|fertig|done|ready)\b|"
    r"\b(?:status|stand|wie\s+weit|fortschritt|progress)\b.{0,60}?\b(?:küche|kueche|kitchen|bestellung|order|chefkoch|bau|build)\b",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"(?:https?://|git@)[^\s'\"<>]+")
_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/][^\s'\"<>]+|(?:\.{1,2}|~)?/[^\s'\"<>]+)")
_TARGET_RE = re.compile(r"(?:die|das|den|the|this|diese[sn]?|dieser|my|mein[e]?)\s+(?:app|anwendung|application|projekt|project|repo|code|programm|program|tool|website)\s*(?:\"([^\"]+)\"|'([^']+)'|`([^`]+)`|([A-Za-z0-9_./\\:-]{2,}))?", re.IGNORECASE)


@dataclass(frozen=True)
class Order:
    kind: str
    text: str
    language: str = "de"
    target: str | None = None
    sources: tuple[str, ...] = field(default_factory=tuple)
    stack: str | None = None

    @property
    def order_id(self) -> str:
        return "order-" + hashlib.sha256(
            f"{self.kind}\n{self.text}\n{self.target}\n{','.join(self.sources)}".encode("utf-8")
        ).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["sources"] = list(self.sources)
        payload["order_id"] = self.order_id
        return payload


def detect_language(text: str) -> str:
    return "de" if _GERMAN_MARKERS.search(text or "") else "en"


def _stack_hint(text: str) -> str | None:
    lowered = text.lower()
    for token, stack in (("react", "react"), ("vue", "vue"), ("svelte", "svelte"), ("next", "nextjs"),
                         ("fastapi", "fastapi"), ("flask", "flask"), ("django", "django"), ("tauri", "tauri"),
                         ("electron", "electron"), ("rust", "rust"), ("go ", "go"), ("golang", "go"),
                         ("typescript", "typescript"), ("python", "python"), ("node", "node"),
                         ("html", "static-web"), ("kotlin", "kotlin"), ("swift", "swift"), ("c#", "dotnet"),
                         (".net", "dotnet"), ("java", "java")):
        if token in lowered:
            return stack
    return None


def _sources(text: str) -> tuple[str, ...]:
    found: list[str] = []
    for match in _URL_RE.findall(text):
        found.append(match.rstrip(".,;)"))
    for match in _PATH_RE.findall(text):
        candidate = match.rstrip(".,;)")
        if candidate in found:
            continue
        try:
            if Path(candidate).expanduser().exists():
                found.append(candidate)
        except OSError:
            continue
    return tuple(found)


def _target(text: str) -> str | None:
    match = _TARGET_RE.search(text)
    if not match:
        return None
    for group in match.groups():
        if group:
            return group
    return None


def parse_order(message: str) -> Order | None:
    """Return the order a sentence places, or ``None`` for ordinary chat."""
    text = (message or "").strip()
    if not text or text.startswith("/computer"):
        return None
    language = detect_language(text)
    if _STATUS_RE.search(text):
        return Order(KIND_STATUS, text, language)
    if _FEED_RE.search(text):
        return Order(KIND_FEED, text, language, sources=_sources(text))
    if _IMPROVE_RE.search(text):
        if _SELF_TARGET_RE.search(text):
            return Order(KIND_SELF, text, language, target="daedalus")
        sources = _sources(text)
        if _IMPROVE_TARGET_RE.search(text) or sources:
            return Order(KIND_IMPROVE, text, language, target=_target(text), sources=sources)
        return None
    if _BUILD_RE.search(text) or _BUILD_WISH_RE.search(text):
        return Order(KIND_BUILD, text, language, stack=_stack_hint(text))
    return None


__all__ = ["Order", "parse_order", "detect_language", "KINDS", "KIND_BUILD", "KIND_IMPROVE",
           "KIND_SELF", "KIND_FEED", "KIND_STATUS"]
