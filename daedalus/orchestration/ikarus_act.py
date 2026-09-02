"""ikarus_act — MAY this message reach a tool-bearing executor?

THE SECOND PREDICATE, AND DELIBERATELY NOT THE FIRST ONE.

:func:`daedalus.orchestration.ikarus_os.classify` answers exactly one question — *which
intent is this*, so the UI can pick an affordance — using a broad bilingual
keyword table. What it must never become is a CAPABILITY GATE, because the two
questions have opposite error costs:

  * classify wrong  -> the user sees the wrong panel. Cheap, visible, undone by
    typing again.
  * may_act wrong   -> a sentence reaches something that can write files.

A predicate tuned for the first cost cannot be reused for the second, and the
substring table proves it: ``"does that make sense"`` contains ``"make "``, so
``classify`` returns ``enqueue`` for a question about an opinion. As an
affordance that is a shrug. As a capability gate it is a rhetorical question
arriving at an executor.

So: two functions, two test suites, and NO shared return value. ``may_act``
never calls ``classify`` and its verdict never depends on classify's label —
``intent`` is carried on :class:`ActDecision` for REPORTING only, so that a
divergence between the two answers is visible instead of silently resolved.


THE FALSE-POSITIVE BUDGET, STATED
---------------------------------
Narrow allow, wide suspect. Clearing a message costs more than missing one: a
missed act request has a cheap recovery (the caller offers the confirm path,
one extra turn), a wrongly-cleared one does not.

ALLOWED requires ALL of:

  * the FIRST significant word (leading politeness/filler stripped) is an
    exact English or German imperative act verb from :data:`ACT_VERBS` or
    :data:`_GERMAN_ACT`, and
  * the message is not interrogative — no trailing ``?``, no leading question
    word (English or German).

That is the entire allow rule. It admits "build a settings dialog" and refuses
every construction where an act verb merely APPEARS somewhere. Measured against
the cases this budget was written for (see tests/test_ikarus_act.py):

    "build a settings dialog"     ALLOWED             leading act verb
    "fix the clone detector"      ALLOWED             leading act verb
    "does that make sense"        REFUSED, quiet      "make" is not first, "does" leads a question
    "build a settings dialog?"    REFUSED, suspected  leading act verb, but interrogative
    "can you build a thing?"      REFUSED, suspected  directed request, interrogative
    "mach den Parser robuster"    ALLOWED             leading German act verb
    "kannst du das mal bauen"     REFUSED, suspected  German question, not an imperative
    "hello, who are you?"         REFUSED, quiet      nothing act-shaped
    "yes"  (no pending offer)     REFUSED, quiet      a bare affirmative clears nothing on its own

"REFUSED, suspected" is not a softer allow — it is a refusal that additionally
reports *why it looked like one*, so the caller can say so in words and offer a
confirm path. Nothing about ``suspected`` reaches an executor.

THE DOCUMENTED DIVERGENCE — "fix the clone detector". ``classify`` returns
``distill`` for it (the distill keywords are tested before the enqueue ones and
"clone" matches), so ikarus_os routes it to the local, no-spend distill report
and no tool-bearing executor is reached at all. ``may_act`` says the SENTENCE
would be clearable. Both answers are correct about their own question and
neither overrides the other: the ROUTE is chosen by intent, the CAPABILITY by
may_act, and a message needs both before a Hand ever sees it.


CONFIRMATION
------------
A bare "yes" is an act request only in context. :func:`may_act` therefore takes
the conversation, and clears an affirmative ONLY when the previous turn's
envelope carries an ``act_offer``. What it then clears is the ORIGINAL
message's objective, never the word "yes" — the confirmation re-enters the
same enqueue path the offer described, never a path around it.

This module does no IO. The caller hands in whatever conversation state it has
(a list of turns, one turn, a dict, or ``None``), so the predicate stays
unit-testable without a database, and a store that is unavailable makes the
predicate MORE restrictive (a confirmation stops clearing), never less.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# the vocabularies                                                             #
# --------------------------------------------------------------------------- #
#: Imperative act verbs. Kept aligned with ``ikarus_os.classify``'s enqueue
#: keywords plus their obvious siblings, so the allow surface stays explainable
#: rather than growing by anecdote. Adding a verb here WIDENS what can reach a
#: tool-bearing executor; it is a safety edit, not a convenience one.
ACT_VERBS = frozenset({
    "build", "add", "fix", "implement", "create", "write", "refactor",
    "generate", "make", "queue", "delete", "remove", "rename", "rewrite",
    "run", "install",
})

#: Stripped from the FRONT only, so "please build X" reads as an imperative
#: while a filler word mid-sentence changes nothing.
_LEAD_FILLER = frozenset({
    "please", "pls", "plz", "hey", "hi", "ok", "okay", "now", "just",
    "bitte", "mal", "so", "then",
})

#: A leading question word makes the message interrogative even without a "?".
#: German forms are here because the German act-request is an explicit case
#: this predicate must get right, not an afterthought.
_QUESTION_LEADS = frozenset({
    "does", "do", "did", "is", "are", "am", "was", "were", "has", "have", "had",
    "can", "could", "would", "will", "shall", "should", "may", "might",
    "what", "why", "how", "when", "where", "who", "whom", "which", "whose",
    "kannst", "kann", "koennen", "können", "koenntest", "könntest",
    "wuerdest", "würdest", "willst", "soll", "sollen",
    "wie", "warum", "wieso", "wer", "wo", "wann", "welche", "welcher",
})

#: Unambiguous German imperative act cues, matched as WHOLE TOKENS. Infinitives,
#: participles and indicative forms do not belong in the allow set: ``Bauen ist
#: kompliziert`` and ``Machst du das morgen`` are statements/questions, not
#: clearance for an autonomous executor. Deliberately exact forms rather than
#: stems: a stem like ``mach*`` would also match the English "machine".
_GERMAN_ACT = frozenset({
    "bau", "baue", "mach", "mache", "erstell", "erstelle", "schreib",
    "schreibe", "implementier", "implementiere", "reparier", "repariere",
    "beheb", "behebe", "füg", "füge", "fueg", "fuege", "ändere",
    "aendere", "lösche", "loesche", "benenne", "generiere", "refaktoriere",
    "prüf", "prüfe", "pruef", "pruefe", "teste", "analysier",
    "analysiere", "untersuch", "untersuche", "schau", "such", "suche",
    "lies", "lese", "führ", "führe", "fuehr", "fuehre", "starte",
    "installier", "installiere", "aktualisier", "aktualisiere",
    "dokumentier", "dokumentiere", "optimier", "optimiere",
})

# Broader conjugations are useful only for recognizing a directed or modal
# request such as ``kannst du das bauen``. They may make a refusal explainable,
# but never clear a leading token on their own.
_GERMAN_REQUEST_FORMS = _GERMAN_ACT | frozenset({
    "bauen", "baust", "gebaut", "machen", "machst", "erstellen", "schreiben",
    "implementieren", "reparieren", "beheben", "hinzufügen", "hinzufuegen",
    "ändern", "aendern", "löschen", "loeschen", "umbenennen", "generieren",
    "prüfen", "pruefen", "testen", "analysieren", "untersuchen", "ansehen",
    "suchen", "lesen", "führen", "fuehren", "starten", "installieren",
    "aktualisieren", "dokumentieren", "optimieren",
})

#: A confirmation is the WHOLE message, compared after normalisation — never a
#: substring. "yes" confirms; "yes, but does that make sense?" does not.
_AFFIRMATIVE = frozenset({
    "y", "yes", "yeah", "yep", "yup", "yes please", "yes do it", "do it",
    "do that", "ok", "okay", "k", "sure", "go", "go ahead", "please do",
    "confirm", "confirmed", "affirmative",
    "ja", "jo", "jep", "klar", "genau", "los", "mach", "mach das", "mach es",
    "ja mach das", "ja bitte", "bestätigt", "bestaetigt",
})

#: An explicit decline clears the pending offer rather than falling back to
#: "not affirmative -> suspect it again", which would nag.
_NEGATIVE = frozenset({
    "n", "no", "nope", "nah", "no thanks", "cancel", "stop", "never mind",
    "nevermind", "don't", "dont", "do not",
    "nein", "ne", "nö", "noe", "abbrechen", "lass", "lass es",
})

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_ALT = "|".join(sorted(ACT_VERBS))
#: "can you build …" / "could you fix …" — a directed request. The bounded
#: ``{0,60}`` gap keeps the verb in the same clause as the address, and the
#: ``[^.?!]`` class stops it reaching across a sentence boundary.
_DIRECTED_RE = re.compile(
    r"\b(?:can|could|would|will|cannot|can't|won't)\s+(?:you|u)\b"
    r"[^.?!]{0,60}?\b(?:" + _ALT + r")\b", re.IGNORECASE)
#: "i want you to build …" / "we need to fix …"
_WANT_RE = re.compile(
    r"\b(?:i|we)\s+(?:want|need|would\s+like)\b"
    r"[^.?!]{0,60}?\b(?:" + _ALT + r")\b", re.IGNORECASE)
_GERMAN_ALT = "|".join(sorted(re.escape(word) for word in _GERMAN_REQUEST_FORMS))
_GERMAN_DIRECTED_RE = re.compile(
    r"\b(?:kannst|koenntest|könntest|wuerdest|würdest|willst)\s+du\b"
    r"[^.?!]{0,80}?\b(?:" + _GERMAN_ALT + r")\b", re.IGNORECASE)
_GERMAN_WANT_RE = re.compile(
    r"\b(?:ich|wir)\s+(?:will|wollen|möchte|moechte|möchten|moechten)\b"
    r"[^.?!]{0,80}?\bdu\b[^.?!]{0,80}?\b(?:" + _GERMAN_ALT + r")\b",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- #
# the decision                                                                 #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ActDecision:
    """The answer to the CAPABILITY question, and only that question.

    ``allowed`` is the whole verdict. ``suspected`` never softens it: a
    suspected message is refused exactly as hard as a quiet one, and the flag
    exists so the caller can EXPLAIN the refusal and offer the confirm path
    instead of answering as if nothing act-shaped had been said.

    ``intent`` carries whatever ``classify`` said about the same message. It is
    reporting only — no branch in :func:`may_act` reads it — so that the two
    predicates' answers can be compared without being coupled.
    """

    allowed: bool
    reason: str
    signal: str = ""
    suspected: bool = False
    objective: str = ""
    intent: str = ""
    #: When this decision cleared a CONFIRMATION, the objective being confirmed
    #: (the original message, never the word "yes"). Empty otherwise.
    confirmation_of: str = ""

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "signal": self.signal,
            "suspected": self.suspected,
            "intent": self.intent,
            "confirmation_of": self.confirmation_of,
        }


# --------------------------------------------------------------------------- #
# helpers (pure)                                                               #
# --------------------------------------------------------------------------- #
def _normalize(message: str) -> str:
    """Lowercase, collapse whitespace, drop surrounding quotes and trailing
    punctuation — the form a whole-message confirmation is compared in."""
    text = " ".join((message or "").strip().lower().split())
    return text.strip("\"'`").strip(" .!?,;:").strip()


def _significant_words(message: str) -> list[str]:
    """Words of the message, lowercased, with LEADING filler removed."""
    words = [w.lower() for w in _WORD_RE.findall(message or "")]
    i = 0
    while i < len(words) and words[i] in _LEAD_FILLER:
        i += 1
    return words[i:]


def _is_interrogative(message: str, first_word: str) -> bool:
    return (message or "").rstrip().endswith("?") or first_word in _QUESTION_LEADS


def _get(obj, key: str):
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _last_turn(conversation):
    """The most recent turn out of whatever the caller handed in."""
    if conversation is None:
        return None
    if isinstance(conversation, (list, tuple)):
        return conversation[-1] if conversation else None
    return conversation


def pending_offer(conversation) -> dict | None:
    """The act offer the LAST turn made, if any.

    Reads ``envelope["act_offer"]`` — the block ikarus_os stamps when it
    refuses a suspected act request and offers the confirm path. A malformed or
    objective-less offer is treated as no offer: the fail direction here must
    be "nothing to confirm", never "confirm something unnamed".
    """
    turn = _last_turn(conversation)
    if turn is None:
        return None
    env = _get(turn, "envelope")
    if not isinstance(env, dict):
        return None
    offer = env.get("act_offer")
    if not isinstance(offer, dict):
        return None
    objective = offer.get("objective")
    if not isinstance(objective, str) or not objective.strip():
        return None
    return offer


def _suspect_signal(message: str, words: list[str]) -> str:
    """Why this message READS like an act request, or "" if it does not.

    Only ever reached after the allow rule has already failed, so nothing here
    can widen what is allowed — it can only make a refusal more explicable.
    """
    first = words[0] if words else ""
    if first in ACT_VERBS or first in _GERMAN_ACT:
        return f"leading act verb '{first}' in a question"
    if _DIRECTED_RE.search(message):
        return "directed request: 'can/could you <act verb>'"
    if _WANT_RE.search(message):
        return "stated want: 'i/we want|need … <act verb>'"
    if _GERMAN_DIRECTED_RE.search(message):
        return "German directed request: '<modal> du … <act verb>'"
    if _GERMAN_WANT_RE.search(message):
        return "German stated want: 'ich/wir … du … <act verb>'"
    return ""


# --------------------------------------------------------------------------- #
# the predicate                                                                #
# --------------------------------------------------------------------------- #
def may_act(message: str, intent: str = "", conversation=None) -> ActDecision:
    """MAY this message reach a tool-bearing executor?

    Answers the capability question and nothing else. See the module docstring
    for the stated false-positive budget and the worked cases.
    """
    text = (message or "").strip()
    if not text:
        return ActDecision(False, "empty message", intent=intent)

    offer = pending_offer(conversation)
    if offer is not None:
        norm = _normalize(text)
        if norm in _NEGATIVE:
            return ActDecision(False, "the offered action was declined",
                               signal="declined", intent=intent)
        if norm in _AFFIRMATIVE:
            objective = str(offer.get("objective") or "").strip()
            return ActDecision(
                True, "confirmation of the action offered on the previous turn",
                signal=f"confirmed with '{norm}'", objective=objective,
                intent=intent, confirmation_of=objective)

    words = _significant_words(text)
    first = words[0] if words else ""
    if ((first in ACT_VERBS or first in _GERMAN_ACT)
            and not _is_interrogative(text, first)):
        language = "German " if first in _GERMAN_ACT else ""
        return ActDecision(True, "imperative act request",
                           signal=f"leading {language}act verb '{first}'",
                           objective=text, intent=intent)

    signal = _suspect_signal(text, words)
    if signal:
        return ActDecision(
            False, "reads like an act request but does not meet the allow rule",
            signal=signal, suspected=True, objective=text, intent=intent)
    return ActDecision(False, "no act request detected", intent=intent)
