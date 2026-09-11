"""Anchor the owner's standing merge authorization of 2026-09-10 19:57.

It goes into CLAUDE.md, which is where this repository already records dated
owner instructions that refine the global rules (the LangGraph and Codex
sections of 2026-09-01). It does NOT go into the master plan, the amendment
chain or AGENTS.md: those change only through the amendment protocol, and this
instruction does not ask for that.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(r"C:\Users\Administrator\Desktop\projects\daedalus")
P = ROOT / "CLAUDE.md"
s = P.read_bytes().decode("utf-8").replace("\r\n", "\n")

SECTION = """## Eigenständiges Mergen: stehende Owner-Vollmacht

Owner-Anweisung 2026-09-10, 19:57, wörtlich: „mach bitte warte nicht auf mein
approval du darfst mergen, commiten und pushen wie du meinst verankere das in
die md". Voraus ging um 19:49 „ich approve alles" für die Packets 46 und 47.
Diese Anweisung präzisiert, wie Schritt 9 der Baukette (Plan §10) erfüllt wird.
Sie **ändert den Masterplan, die Amendment-Kette und `AGENTS.md` nicht**.

**Was die Vollmacht abdeckt.** Eigene Work-Packet-Zweige dürfen ohne
Rückfrage committet, gepusht und nach `main` gemerged werden, sobald die
Akzeptanzmatrix des Packets grün ist, die unabhängige Review-Kette gelaufen ist
und kein Reviewer blockiert. Die stehende Zustimmung ersetzt die Rückfrage,
nicht die Evidenz: ein Merge ohne grüne Suiten, ohne Mutationsnachweis oder
gegen ein offenes `block` eines Reviewers ist von ihr **nicht** gedeckt.

**Was sie ausdrücklich nicht abdeckt** (unverändert, ohne Amendment):

- **Invariante 5 — versiegelte Promotion.** Kein Kandidat aus Ariadne oder
  Genesis wird automatisch gemerged oder promotet. Nominierung bleibt
  Nominierung; Promotion braucht weiterhin eine einmalige, gebundene
  `OwnerApproval` pro Kandidat.
- Kill-Switch, Egress-Zulassung, Write-Roots, Secret- und Tool-Policy,
  Evaluator-Isolation und die Leakage-Grenze aus Plan §8.1.
- Öffentliches Veröffentlichen, Release-Adapter, Store-/Signing-Zugänge.
- Force-Push auf `main`, Historien-Umschreibung, Löschen fremder Zweige,
  Änderungen an Plan, Amendment-Kette, `AGENTS.md` oder den Guards.
- Dateien anderer Lanes: unversionierte Arbeit anderer Sessions wird nicht
  überschrieben, gestasht oder „aufgeräumt" (siehe `docs/AGENT_COORDINATION.md`).

**Was beim Mergen protokolliert wird.** Der Merge-Commit nennt die
Owner-Vollmacht mit Datum, das Reviewer-Verdikt und die gemessene Evidenz. Die
Board-Datei und die Sitzungsnotiz halten fest, was wann gemerged wurde, damit
der Owner jede Entscheidung nachlesen kann, ohne sie vorher treffen zu müssen.

"""

anchor = "## Codex als unabhängiger Vendor"
assert s.count(anchor) == 1
s = s.replace(anchor, SECTION + anchor)
P.write_bytes(s.encode("utf-8"))
print("CLAUDE.md anchored; CR", s.count("\r"))
