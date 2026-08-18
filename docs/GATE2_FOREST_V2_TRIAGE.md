# Gate-2-Vorbau: Forest-v2-Buildout, Triage nach Falsifikation (2026-08-18)

Status: EXPERIMENT-Triage. Nichts davon ist geportet; alle zehn Slices leben
in ihren Lanes (`grind/f2-s01` … `grind/f2-s10`). Dieses Dokument hält fest,
was gebaut wurde, was der Falsifikation NICHT standhielt, und was fehlt.

## Aufbau

Zehn Opus-Builder haben je einen Slice der Vier-Ebenen-Maschinerie gebaut
(Code-Resolution, Type-, Data-, Knowledge-Plane, Snapshot-Atomizität, Node
Cards, BM25-Baseline, Graph-Baselines, Eval-Harness, Kill-Kriterien), jeder
danach von einem codex-Seat angegriffen. Alle zehn Branches sind real:
2–5 Commits, 813–6375 Insertions über `d849c2a9`.

## Der zentrale Befund

**Kein einziger Headline-Wert hat die Falsifikation überlebt.** Drei Slices
wurden bis zum Verdikt angegriffen, und alle drei Zahlen fielen:

| Slice | behauptet | gemessen |
| --- | --- | --- |
| s03 Data-Plane | „285 scanned / 0 unparseable", cross-plane verified per §6 | Prefilter-Artefakt im Nenner; die „Verifikation" ist eine Intra-Data-Heuristik ohne §6-Verifier-Felder, ohne Required-Field-Check, nur über 50 Zeilen |
| s04 Knowledge-Plane | 96,6 % Referenz-Auflösung | 72,4 % (399/551) über alle Kandidaten; 136 externe/mehrdeutige Kanten aus dem Nenner genommen, Suffix-Inferenz als „resolved" gezählt, Repro ergibt 95,9 % statt 96,6 |
| s05 Snapshot | Revisions-Atomizität, 10/10 Sensitivität | **Atomizität WIDERLEGT**: Bindung ist String-Gleichheit, kein Source-Evidenz-Beweis — ein zwischen zwei Plane-Extraktionen mutierter Worktree digestet als eine „atomare" Revision (Invariante 6). Sensitivität überstellt: Mutatoren nicht wirklich ein-Feld, mehrere Felder ungetestet, Timer vermischt |

Die drei Fix-Rezepte sind präzise und laufen als eigene Lanes: fail-closed
Verifikation mit ehrlichem Nenner (s03), Denominator-Waterfall statt
Einzelzahl plus korpus-gepinnter Test (s04), und der Gate-Test
`test_mutation_between_plane_extractions_is_refused` plus Bindung an
Source-Evidenz (s05).

## Was für Gate 2 noch vollständig fehlt

Die Gate-2-Messlatte lautet: der volle Graph schlägt einfachere
Repräsentationen, budget-gleich. Diese Messung existiert in keinem Slice.
Es fehlen die Ablations-Harness, die budget-gleichen Baselines im
Vergleichslauf und eine vertrauenswürdige Messschicht. Sieben der zehn
Slices haben zudem noch kein unabhängiges Verdikt — darunter der größte
(s09, 18 Dateien, 6375 Insertions), der bisher völlig ungeprüft ist.

## Betriebsbefund: der Egress-Classifier blockte einen Angriff hart

Ein codex-Angriff (s02) wurde vom Safety-Classifier als Data Exfiltration
hart abgelehnt — Repo-Diff an einen externen Vendor. Der Council-Pfad mit
Egress-Gate und Secret-Floor ist der sanktionierte Weg und trug die übrigen
Angriffe; hier griff eine Ebene darüber. Der Block wurde respektiert, nicht
umgangen; der Slice bleibt ungeprüft und damit auf `hold`.

## Nachtrag (13:20): die sieben offenen Slices haben KEIN Verdikt

Eine Ernte über alle 29 Bus-Transkripte (`bus.verify_chain`, 29/29 ok, null
Chain-Fehler) zeigt: Für s01, s02, s06, s07, s08, s09, s10 existiert **kein
einziger Angriff**. Vier Seats zwischen 11:01 und 11:08 schrieben einen
Roster-Open und danach nichts — kein Turn, kein Timeout-Receipt, kein
Close; ihre Slice-Identität ist nicht einmal rekonstruierbar, weil sie am
nie geschriebenen Turn-Record hing. Kein Seat läuft noch.

**Infrastruktur-Defekt, hier benannt statt später wiederentdeckt:** Ein
hängender Vendor-Call fällt stumm aus dem Protokoll. Die 09:57-Charge starb
sauber (`status=unavailable, reason=not_on_path` plus Close, diagnostizierbar);
diese vier hinterließen keine Quittung. Ein Council, dessen Hänger unsichtbar
sind, kann „degraded quorum" nicht ehrlich melden — die Doktrin verlangt
genau das als erste Meldung. Fix: ein Watchdog, der nach Fristablauf einen
`status=timeout`-Turn plus Roster-Close anhängt. Dazu: PATH-Vorabprüfung der
codex-CLI, denn der `not_on_path`-Modus hat schon einmal zehn Seats auf
einen Schlag entwertet.

Ersatzmaßnahme: Da der Egress-Classifier Slice-Diffs an externe Vendors hart
ablehnt, laufen die sieben Prüfungen intern-adversarisch (voller Codezugriff,
Auftrag identisch: Zahlen nachrechnen, Vakuum-Tests suchen, Contract-Drift
gegen §5/§6/§13). Cross-Vendor-Unabhängigkeit fehlt diesen sieben damit —
das ist ein schwächeres Signal und wird hier als solches vermerkt.

## Regel für die Fortsetzung

Kein Slice wird geportet, bevor er ein unabhängiges Verdikt hat — besonders
nicht s09. Eine Zahl ohne überlebte Falsifikation ist keine Evidenz,
sondern eine Behauptung mit Dezimalstellen.
