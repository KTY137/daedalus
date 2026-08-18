# Konsolidierungswelle 1 (nach dem Gate-0-Stempel) — Aristaeus-Survey

Read-only Survey @ 0e6a5e56, 2026-08-18. Alle Zahlen MEASURED (Importeur-
Zählungen, AST-Hash-Vergleiche, Callsite-Verifikation). Zwei eigene
Zwischenbefunde wurden im Survey selbst als falsch verworfen (report_v3 und
repository_write_inventory_v2 sind LIVE, keine Waisen).

## Welle 1 (empfohlener Schnitt, kohärent im selben Subsystem)

1. **G1 — gates/fault_matrix.py stilllegen** (L, Owner = Punkt 8 der
   Owner-Liste, Messung eindeutig): 996 Zeilen, NULL Produktions-Importeure;
   der echte Pfad ist report → fault_matrix_binding → runtimes. Mit seinen 4
   Testdateien + 4 Mutationsskripten netto −2076 Zeilen. Vorbedingung: prüfen,
   dass der runtimes-Katalog die declare-then-verify-Garantie des Manifests
   abdeckt. Thermometer: Verdikt-Autoritäten 2 → 1 bei grüner
   binding/bridge/whole_matrix-Suite.
2. **G4 — faults.py-Shim + falscher Provenance-Default** (S): 29-Zeilen-Shim
   ohne Produktions-Importeure, aber `provenance_origin` in
   runtimes/fault_matrix.py:421 backt den Shim-Namen in Evidenz-Artefakte
   (Invariante-7-Verstoß). Owner nur für die Alt-Artefakt-Frage.
3. **G3+G9 — Issuer-Kern extrahieren** (M, ALIGNED): fixture/live importieren
   9 Symbole (6 private!) aus dem host-Issuer und kopieren 7 Helfer
   byte-identisch; Issuer-Klassen unterscheiden sich um 5/120 Zeilen. Kern in
   fault_attestation_common.py mit öffentlichen Namen; Spalten-Scoping bleibt
   in den Konstanten. Dabei G9 gratis: production_key_material-Ausgabe in
   allen drei CLIs statt nur live. Drei getrennte Suiten sichern ab.
4. **G2 — Host-Prädikat-Konsolidierung** (S–M, **Cerberus-PFLICHT**): Der
   alte „drei Antworten für [::1]"-Befund ist LIVE — cli.py:527/809 erreichen
   council session/canary mit byte-identischen `_is_local_http`-Kopien
   (session.py:913, canary.py:823, + Inline accelerators.py:223), drei
   Callsites setzen daraus lane="trusted".
   `tests/test_host_predicate.py::test_the_known_divergences_are_still_divergences`
   pinnt die Divergenz heute als SOLLZUSTAND (:483-491). Umbau dreht die
   permissive Richtung um (sicherheitspositiv, betriebsverhaltensändernd).

## Sicherheitsrelevant, eigene Spur (nicht Welle 1, aber benannt)

- **G7 — runs/council/: 3929 Zeilen ausführbar außerhalb des Pakets**, und
  das Budget-Ceiling wird nur im CLI-Prozess monkeygepatcht
  (budget.py:1069-1091, cli.py:906-911) → Raum-Aufrufe an bezahlte Vendors
  laufen OHNE Schranke (Invariante 8; tragender Zufall, in .room/room.md
  selbst dokumentiert). Thermometer: Egress-Einstiege ohne Ceiling 5 → 0;
  Test existiert noch nicht.

## Welle 2 / später

- G5: repository_write_inventory v1 (832 Z., 1 Importeur) → auf v2 porten,
  löschen. G6: 6 kopierte Exact-Authority-Stacks in tests/ (~156 Z.) → ein
  parametrierbarer Builder (Talos). G12: provider_target_receipt_retention_*
  (4757 Z., 7 Module) — UNGEMESSEN, erst AST-Hash-Survey.

## Erledigt / keine Arbeit

- G8 Mutationsskripte: Fix bereits gelandet (84a8275). G10 compaction: Modul
  seit 2026-07-29 gelöscht (health.py:1654-Grabstein) — nicht erneut
  untersuchen. G11 Room-Doppel: Repo-seitig kein Duplikat mehr; der Befund
  ist Evidenz für G7.

Vollständiger Survey-Report mit allen Ankern: Session-Transkript 2026-08-18
(Aristaeus), Kernaussagen hier vollständig übernommen.
