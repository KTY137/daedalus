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

Die drei Fix-Rezepte sind präzise und **alle drei sind umgesetzt** (in ihren
Lanes, nicht geportet):

- **s03** (`c93a68c1`…`6a2fda3f`): Verifikation kennt jetzt drei Ausgänge —
  rejected / indeterminate / verified — und „kein Widerspruch gefunden" gilt
  nicht mehr als verifiziert. Nenner ehrlich: **285 von 285 geparst** statt
  285 gescannt bei 10 geparsten; die „0 unparseable" waren über einen Nenner
  von zehn berechnet. Ergebnis der Ehrlichkeit: aus 2 verifizierten Paaren
  wird **1** (das zweite Schema hatte nie einen Typ, gegen den man prüfen
  konnte). Zusätzlich ein echter Doppelzähl-Bug gefunden (f-String-Literale
  erscheinen im Syntaxbaum zweimal). 54 Tests, 5/5 Mutationen getötet.
- **s04** (`84d54f05`…`06d2ca01`): Wasserfall statt Einzelzahl, mit erzwungenen
  Bilanz-Identitäten (eine verlorene Kategorie lässt den Build krachen). Die
  alte Zahl war dreifach publiziert (96,6 / 95,9 / 95,2) und real **69,5 %
  strikt verifiziert**. Die Lane fand außerdem, dass ihre eigene Fixture die
  Metrik kontaminierte, und hat es selbst korrigiert. 35 Tests, 4 Mutationen.
- **s05** (`be34f92f`…`2be67ef6`): Die Widerlegung zuerst als **roter** Gate-Test
  reproduziert, dann behoben. Bindung jetzt zweischichtig: ein Per-Plane-Witness
  (Digest als Nebenprodukt genau der Lesung, die die Extraktion fütterte) plus
  eine Scope-Klammer vor der ersten und nach der letzten Extraktion. Contract
  `/1` → `/2`. Sensitivität ehrlich **18/18** statt überstellter 10/10, Timer
  getrennt, Kosten der Bindung gemessen: **+1,23 s (×1,18)**. 63 Tests,
  7/7 Guards mutationsgeprüft.

Zwei Grenzen hat s05 ausdrücklich stehen lassen statt sie zu verstecken: eine
transiente Mutation, die keine Ebene liest, wird bewusst NICHT refüsiert (als
bestehender Test festgehalten, nicht als Prosa), und die Zeugen schlagen einen
konkurrierenden Schreiber, nicht einen lügenden Extraktor — dafür bräuchte es
einen Leser außerhalb des Produzenten (§4).

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

## Die sieben internen Falsifikationen (13:45) — einer von sieben überlebte

| Slice | Behauptung | Überlebt? | Kern |
| --- | --- | --- | --- |
| s01 Code-Plane | Import-Bindung hebt Attribution 21,24 % → 29,16 % | **JA** | Nenner nicht geschönt, geratene/externe Auflösungen aus der Kennzahl gehalten, Parität maschinell gepinnt |
| s08 Graph-Baselines | „Vier getrennte Indizes sind strikt unterlegen (432 vs. 491)" | nein | **Die Baseline wurde ausgehungert** (s.u.) |
| s10 Kill-Evaluator | „9 von 15 Kriterien entscheidbar = 60 % Abdeckung" | nein | §14 hat **16** Bullets; real 9/16 = 56,3 %; ein Kriterium fehlt ganz, eines liegt unter falschem Index |
| s02 Type-Plane | „92,77 % Signaturauflösung vs. 37,16 % Kontrolle = +55,6 pp" | nein | Strohmann-Kontrolle; gegen die natürliche Baseline sind es **0,12 pp** |
| s07 BM25 | „Lehrbuch-BM25, ehrlicher Nenner" | nein | Formel überlebte eine unabhängige Reimplementierung exakt; der Korpus-Filter hebt die Zahl um +0,056 MRR |
| s06 Node Cards | „8466 §6-konforme Karten, 0 abgelehnt, 0 Verstöße" | nein | 30,8 % der Envelope-Bytes sind ein konstantes Provenance-Literal; die beiden Null-Zähler sind strukturell garantiert, nicht gemessen |

### Der schwerste Befund: die Messung war zugunsten der eigenen Hypothese verzerrt

s08 vergleicht den Vier-Ebenen-Ansatz gegen „vier unabhängige Indizes ohne
Fusion" — und teilte dabei ein gemeinsames Trefferbudget im Round-Robin auf
die vier Indizes auf. Da **jedes Gold-Label ein Code-Dokument ist**, konnte nur
der Code-Index die Antwort halten — und der bekam effektiv nur die Plätze
1, 5, 9, also top-3. Gemessen: no-fusion@10 = 432, Code-Index@3 = 430. Gibt man
jeder Ebene ihr eigenes Budget **ohne jede ebenenübergreifende Wertung**,
erreicht sie 491 — exakt so viel wie der reine Code-Index. Die „strikte
Unterlegenheit" war ein Artefakt der Platzaufteilung. Das README sieht es
halb (Zeile 192-193) und verbucht es dennoch als Evidenz FÜR die Hypothese.

Konsequenzen, beide ernst:
1. **Ein Kill-Kriterium feuert.** Plan §13: „vier unabhängige Indizes
   performen äquivalent zu Cross-Plane-Fusion" — genau das zeigt die
   korrigierte Messung. Der Plan verlangt dann: Track stoppen oder umbauen,
   Evidenz archivieren, Amendment vorschlagen. **Aber:** Diese Messung läuft
   auf 600 Anfragen mit 100 % Code-Gold-Labels; ein ebenenübergreifender
   Retriever kann dort strukturell nur verlieren. Das Kriterium ist mit
   diesem Aufbau nicht sauber prüfbar — und genau das ist der Befund.
2. **Der Vergleichspartner wurde ausgetauscht.** Die eingefrorene Spezifikation
   nennt „ein Index über dieselben Dokumente"; bestätigt wurde gegen einen
   anderen. Gegen den benannten ist das Ergebnis ein Null-Resultat.

### Die Ironie, die man nicht erfinden könnte

Das Instrument, das geschönte Nenner aufdecken soll (s10, der
Kill-Kriterien-Evaluator), hat selbst einen: Es zählt 15 Kriterien, wo der
lebende Plan 16 führt, veröffentlicht 60 % statt 56,3 %, und der Test, der
genau das schützen sollte, kodiert die falsche Konstante samt falscher
Begründung fest. Ein Kriterium („Lizenz-/Provenienz- oder Extraktionskosten
verhindern reproduzierbare Nachnutzung") existiert im Code überhaupt nicht,
und das Orchestrierungs-Kriterium liegt unter dem freigewordenen Index —
wer 14.15 aus einem Bericht nachschlägt, landet im Plan bei etwas anderem.

## Regel für die Fortsetzung

Kein Slice wird geportet, bevor er ein unabhängiges Verdikt hat — besonders
nicht s09. Eine Zahl ohne überlebte Falsifikation ist keine Evidenz,
sondern eine Behauptung mit Dezimalstellen.
