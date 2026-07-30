# Plan: Der zweite Graph (Datenstruktur-Layer) & die Knowledge-Space

Stand: 2026-07-29 · Autor: Athena · Status: Teil A **GO-WITH-CHANGES** (Momus: 3 CRITICAL,
eingearbeitet); Teil B **GO-WITH-CHANGES, K2+K6 NO-GO wie ursprünglich geschrieben**
(Momus: 3 CRITICAL, alle selbst nachverifiziert, eingearbeitet); Teil C Skills installiert
+ erster Design-Lauf kritisch bewertet.
Research-Provenienz: drei Web-Sweeps (SOTA-Code-Graphen; Knowledge-UI-Patterns;
Wiki-Lizenzen/Absorption), Quellen inline. Zahlen mit [MEASURED]/[VERIFIED] gestempelt.

**Update 2026-07-30 (Chronicle-Pass):** Teil A **Fundament IMPLEMENTIERT** (parse →
resolve → index → forest, im Working Tree, NICHT committed); Teil B **K1-Backend-Hälfte
implementiert, aber UNVERDRAHTET** (`markdown.py` parst `[[wikilinks]]`, `index.py` ruft
sie nicht auf). Details, Testzahlen und offene Fragen:
[`TYPE_GRAPH_IMPLEMENTATION_REPORT.md`](TYPE_GRAPH_IMPLEMENTATION_REPORT.md).
Provenienz-Regel ab hier: jede Zahl trägt **[MEASURED …]** (in diesem Repo ausgeführt und
abgelesen), **[INHERITED …]** (von einem früheren Lauf gemessen, hier NICHT nachgemessen)
oder **[ASSUMED]** (Schätzung, nie gemessen). Eine Zahl ohne Stempel ist ein Defekt.

## Produktrahmen

Das Produkt hat sich verändert (Agent OS: Build → Orchestrate → Distill). Die UI-IA wird
daraus NEU abgeleitet, nicht geflickt. Zielbild der Spaces:

| Space | Inhalt | Heute |
|---|---|---|
| **Chat** (Home) | Ikarus, chat-first | existiert |
| **Mission Control** | Orchestrierung + Loop-Telemetrie (Queue/Attempts/Architecture ziehen HIERHIN um) | existiert, Telemetrie liegt falsch unter "Knowledge" |
| **Graph** | EIN Forest, drei Linsen: Code · **Typen (neu)** · Knowledge | Code-Linse existiert |
| **Knowledge** | Confluence×Obsidian-Wiki mit eigenem (lokalem) Graphen | heute mislabeltes Loop-Dashboard |

Kernthese, die beide Teile verbindet: `structcore` ist bereits ein Multiplex-Graph mit
Erweiterungsvertrag ("Symbols, build targets, schemas, … can be added as new node kinds
and relation layers without changing this contract", forest.py). Typen UND Wiki-Seiten
sind nur zwei weitere Node-Kinds im selben Snapshot — kein zweites System.

---

## Teil A — Type-Graph-Layer (Stufe 1: Signatur-Ebene)

### Gemessene Grundlage [MEASURED 2026-07-29, daedalus/]

2205 Funktionen, 97 % return-annotiert, 1569 voll parameter-annotiert; 297 Klassen,
davon 176 Dataclasses. Ein Signatur-Graph ist hier dicht, nicht löchrig.

*Nachgemessen 2026-07-30 durch den gebauten Layer selbst* [MEASURED, 156 Dateien]:
2410 Funktionen, **96,7 % return-annotiert** (2330/2410), 91,9 % der Parameter annotiert,
333 Typ-Deklarationen. Der Baum ist seit dem 29. gewachsen (parallele Lanes), die
Baseline-Behauptung "dicht, nicht löchrig" hält.
Bekannte Lücke: der structcore-Index selbst läuft als untypisiertes `dict` durchs System —
der Layer macht solche Blobs sichtbar (Coverage-Thermometer, erster Nutzen).

### Research-Verdikt (Kurzfassung)

- **Schema-Vokabular klauen, Tools nicht**: Joern-CPG (`TYPE_DECL`/`MEMBER`/`EVAL_TYPE`) und
  CodexGraph (`HAS_FIELD`/`INHERITS`/`USES`) sind die Namens-Standards; Joern/JVM selbst ist
  nicht stdlib-tauglich. stack-graphs ist archiviert (Sept 2025) → nur Design-Referenz.
- **Agent-Literatur**: kleine Edge-Sets gewinnen (contains/import/call/inherit; RepoGraph,
  LocAgent). Ein Typ/Feld-Layer für Agents ist Forschungs-FRONTIER (CodexGraph ist am
  nächsten dran) — wir wären dort vorn, nicht hinterher.
- **Funktionen als Transformationen**: SyPet/TYGAR modellieren APIs als Petri-Netz
  (Typen = Plätze, Methoden = Transitionen) — exakt unser `consumes`/`produces`.
- **Inference-Sidecar**: scip-python (= Pyright) als OPTIONALE Anreicherung für
  unannotierten Code; Kern bleibt stdlib-`ast`, niemals `typing.get_type_hints`
  (führt Imports aus — Egress/Safety!).

### NON-GOALS / INVARIANTEN (Momus-Runde 2026-07-29 — GO-WITH-CHANGES, 3 CRITICAL)

Diese sechs Zeilen sind der Plan. Sie stehen VOR dem Schema, weil die naive Umsetzung von
Schritt 1 ("ClassDef im selben ast.parse") drei Subsysteme gleichzeitig sprengt.

1. **`type`/`field` sind AUSSCHLIESSLICH Forest-Knoten** — niemals `CodeUnit`s, niemals in
   `all_units`, niemals von einem Clone-Pass gesehen. [C1] Grund: `all_units` speist
   `renamed_clusters` (exakter Abgleich auf abstrahiertem Fingerprint, KEIN Threshold, KEIN
   max_cluster, gemeldet im **präzisen** Tier). Unsere 176 Dataclasses hätten unter Type-2-
   Abstraktion identische Fingerprints je Feldzahl → ~176 Mitglieder als "renamed clones"
   mit voller Konfidenz publiziert. Das ist die C/C++-Lektion eine Vertrauensstufe höher.
   Klassen fehlen heute nur durch einen `isinstance`-Zufall in `_units_from_tree` — die
   Ausnahme wird jetzt ABSICHTLICH, wie `clones.py:526` es verlangt.
2. **`SymbolResolver.defs_by_file` bleibt unberührt**; Annotationsauflösung nutzt eine NEUE,
   separate `types_by_file`-Tabelle. [C2] Grund: der Resolver kennt nur Funktionen und
   Doc-Sections. Klassen/Felder hineinzulegen wäre eine Fabrikations-Maschine — `resolve`
   nimmt bei Namensgleichheit den ERSTEN Treffer (Klasse `Foo` verdrängt Funktion `Foo`),
   und `callees` löst JEDEN Identifier-Token auf: Feldnamen wie `path`, `root`, `name`,
   `line`, `source` stehen in keiner Stopword-Liste und würden als CALL-Kanten in
   `slice_text` landen. Das Argument, das den Document-Layer sicher machte
   ("nichts importiert ein Dokument", index.py:700), gilt für Typen gerade NICHT.
   Zweitrundeneffekt: `context_plan._symbol_names` liest `defs_by_file` komplett in den
   BM25-Korpus — Feldnamen würden per Längennormalisierung ausgerechnet die
   Dataclass-reichen Dateien systematisch abwerten.
3. **`type` tritt NIE `FILE_NODE_KINDS` bei**; Typ-Kanten sind Evidenz, die FILE-Knoten
   neu bewertet — ein Typ-Knoten ist niemals ein packbares Kontext-Item. [M5] Sonst
   erfindet `_estimated_tokens` Kosten für einen Knoten ohne Bytes auf der Platte, und die
   Token-Buchhaltung wird Fiktion.
4. **Typ-Knoten betreten nie `modules`, `import_edges` oder `_graph_nodes`**; der Nenner von
   `fenced_dominance` bleibt code-only — unabhängig davon, wie typed reachability später
   gebaut wird. [M6] Sonst landen 297 Typ-Knoten im Nenner, `fraction` sinkt, die
   Stand-down-Schwelle greift nicht und JEDE Task bleibt auf der Premium-Lane. Das kostet
   echtes Geld aus falschem Grund.
5. **Unaufgelöste oder ambige Annotation → KEINE Kante, gezählt** in
   `types.coverage.unresolved`. [M4] Deterministisch und willkürlich sind nicht dasselbe:
   `resolve` nimmt den ersten sortierten Import, was bei zwei `Result`-Definitionen eine
   stabil reproduzierte Falschkante erzeugt. Dieselbe Refuse-to-guess-Regel, die
   `markdown.py` für Links schon hat.
6. **Hub-Cap gemessen und publiziert, BEVOR der Layer ein DSS-Diffusionskanal wird**;
   das Fundament liefert eine LINSE, keinen Kanal. [C3] Das Any-Verbot zielte auf den
   falschen Knoten — `Any` wäre nie entstanden. Die echten Hubs sind `Path`, `Mapping`,
   `CodeUnit`, `dict`, `DSSResult` mit dreistelligem Fan-in. Zwei beliebige Funktionen, die
   beide ein `Path` nehmen, wären dann zwei Hops entfernt, und `dss.diffuse_relation_scores`
   filtert nicht nach Node-Kind → der Graph ist durch ein Dutzend Hub-Typen praktisch
   vollständig verbunden. Cap wird aus der GEMESSENEN Fan-in-Verteilung von `daedalus/`
   gewählt, nicht geraten.

   **→ GEMESSEN UND ENTSCHIEDEN: `DEFAULT_HUB_CAP = 64`** (`typegraph.py:167`).
   [INHERITED 2026-07-29, Hub-Vormessung über `daedalus/` mit 143 Dateien / 2207
   Funktionen / 227 nominalen Typen; im Chronicle-Pass NICHT nachgemessen — die
   Fan-in-Tabelle wurde einmal erhoben und ist nicht in der Testsuite eingefroren.]

   - **Der Blow-up ist real, nicht befürchtet.** 2182 Funktionen tragen ≥1 Typkante →
     2.379.471 mögliche Funktionspaare. Ungecapped sind **1.276.024 Paare (53,63 %)**
     zwei Hops entfernt; `str` allein liefert 939.135, `None` 326.028, `Any` 117.370.
     Ein Diffusionskanal darüber ist ein nahezu vollständiger Graph — Momus' Vorhersage
     ist quantitativ bestätigt.
   - **Der Cap ist von einem PLATEAU abgelesen, nicht geurteilt.** Sortiertes Fan-in am
     Kopf: 1722 (`str`), 883 (`None`), 565 (`Any`), 394 (`dict`), 336 (`int`),
     325 (`Path`), 317 (`bool`), 175 (`float`) ‖ 33 (`Report`), 27 (`AST`), 26, 25, 23,
     23, 20 … Zwischen Rang 8 und Rang 9 liegt ein **5,3×-Sprung mit NICHTS dazwischen**;
     jeder Cap in **[34, 174]** schließt exakt dieselben acht Typen aus. Die Entscheidung
     ist damit gegen ±100 % Fehler unempfindlich. 64 = `max(8, min(64, round(0.03 · 2182)))`,
     d. h. die absolute Zahl und die relative Regel ("ein Typ, den >3 % aller Funktionen
     berühren, kann nicht mehr zwischen ihnen unterscheiden" — der klassische
     df-Stopword-Schnitt) fallen hier zusammen. Gewählt wird die HOHE Seite des Bandes:
     Hubs wachsen nur, Domänentypen wachsen in den Cap hinein und würden dort STILL alle
     Kanten verlieren.
   - **Verteilung** (n = 227 Typen, Fan-in gesamt): p50 = 2, p75 = 6, p90 = 12, p95 = 25,
     p99 = 565, max = 1722. 116 von 227 Typen (51 %) haben Fan-in ≤ 2; die Top-8 tragen
     83,6 % aller Kanten.
   - **Preis des Caps, ehrlich**: bei 64 fallen 8 von 227 Typen (3,52 %) und **83,6 %
     aller Kanten** (Occurrence-Basis 86,5 %) weg; die 2-Hop-Paare sinken von 1.276.024
     auf **3.734 (0,157 % des vollständigen Graphen, Faktor 342)**, der mittlere
     2-Hop-Grad von ~1170 auf 3,42. Das ist kein Verlust, das IST der Befund: 85 % der
     Typkanten dieses Repos sind die Wörter `str` und `None`.
   - **Auf `daedalus/` ist der Cap heute INERT** [MEASURED 2026-07-30, Chronicle-Pass,
     `build_index(daedalus/, types=True)`, 156 Dateien]: `hub_suppressed_edges = 0`,
     `hub_suppressed_types = []`, max Fan-in 33. Grund: in einem *resolve-only*-Graphen
     kommen die acht Hubs gar nicht an — keiner von ihnen wird HIER deklariert (builtin
     bzw. extern). Der Cap ist eine Wache für das Repo, das einen Hub selbst deklariert,
     kein Filter für dieses. Genau darum publiziert der Index `hub_cap`,
     `hub_suppressed_edges` und `edges_before_hub_cap` **auch dann**, wenn nichts
     unterdrückt wurde: ein Leser muss "nichts fiel weg" von "85 % fielen weg"
     unterscheiden können.
   - Zusätzlich, orthogonal zum Cap: `None` und `Any` sind gar keine Knoten
     (`normalize_annotation` legt sie nie in `members`), damit die Verweigerung der
     Default ist und nicht eine Option.
   - **Die Vorbedingung des Caps für einen DSS-Kanal ist damit erfüllt, die Freigabe
     NICHT.** Der Layer ist heute eine Linse: keine der sechs Relationen steht in
     `dss.DEFAULT_RELATION_WEIGHTS`, und `_relation_adjacencies` filtert Diffusion
     strukturell auf File-Knoten.

**Regressions-Thermometer (neu, nicht verhandelbar)** — je ein Test, dass auf `daedalus/`
byte-identisch bleibt: (a) der `duplication`-Block, (b) `resolver.defs_by_file`,
(c) die `lexical_seed`-Scores. Diese drei sind der Beweis, dass der Layer additiv ist.

**Cache-Kopplung** [M9]: Extraktion MUSS in `parse.py` landen, weil `file_key` einen
sha256 von `parse.py` mischt — ein Geschwistermodul würde stale Cache-Zeilen an neuen Code
liefern und die Typ-Blöcke kämen leer zurück, ohne Fehler. `ANALYSIS_VERSION` im selben
Commit bumpen; falls env-gated, `_scope_key` um `+types` erweitern.

**Sprachumfang** [M8]: **Stufe 1 = Python only.** Der tree-sitter-Pfad hat keine Klassen-/
Feld-Vokabular in `LanguageSpec` — das wäre eine Schema-Änderung. `types.coverage` meldet
darum pro Sprache `not_supported`, NIE eine numerische Null (eine Null würde "wir haben
geschaut und nichts gefunden" behaupten, wo "wir haben nicht geschaut" gilt).

**Aus Teil A ENTFERNT (gated follow-on lanes)**: `type_blindspot`-Picker-Band und typed
reachability. Vorbedingung für beide: Hub-Messung (Invariante 6) und Falschkanten-Suite
(Invariante 2) sind grün. Grund fürs Band: `DEFAULT_LIMIT = 10` heißt, ein neuntes Band
VERDRÄNGT Arbeit — dieser Anspruch ist unhaltbar, solange die Falschkantenrate ungemessen ist.

**Kostenkorrektur**: 3–4 Sessions fürs Fundament (nicht 1–2), A/B-Eval ist eine eigene Lane.

### IMPLEMENTIERUNGSSTAND (Chronicle-Pass 2026-07-30)

Alles in diesem Abschnitt liegt **im Working Tree, nicht committed**. Der vollständige
Bericht inkl. RAW-Testzahlen, Thermometer-Verdikten und der einen gefundenen
Invarianten-Verletzung steht in
[`TYPE_GRAPH_IMPLEMENTATION_REPORT.md`](TYPE_GRAPH_IMPLEMENTATION_REPORT.md).

| Baustein | Stand | Ort |
|---|---|---|
| Extraktion (`ClassDef`/`AnnAssign`/Signaturen im selben `ast.parse`) | **IMPLEMENTIERT** | `parse.py` (+958 Zeilen, 0 gelöscht) |
| Normalisierung (Optional/Union/Generics/Callable/Forward-Refs) | **IMPLEMENTIERT** | `parse.normalize_annotation` |
| Auflösung (2 Pässe, eigene `types_by_file`, refuse-to-guess) | **IMPLEMENTIERT** | `typegraph.py` (neu, 1139 Zeilen) |
| Index-Blöcke `types` / `type_nodes` / `type_edges`, gegated | **IMPLEMENTIERT** | `index.py`, Default **AUS** |
| Cache-Kopplung (`ANALYSIS_VERSION` 3→5, `_SCHEMA` 1→2, `+types` im `_scope_key`) | **IMPLEMENTIERT** | `perfile.py`, `cache.py`, `index.py` |
| Forest-Node-Kinds `type`/`field` + 5 Relationsschichten | **IMPLEMENTIERT** | `forest.py` |
| DSS-Härtung (`build_context_plan` prüft KIND, Diffusion file-only) | **IMPLEMENTIERT** | `dss.py` |
| CLI `--types` + Coverage-Summary | **IMPLEMENTIERT** | `__main__.py` |
| Drei Regressions-Thermometer | **IMPLEMENTIERT, alle drei GRÜN** | `tests/test_typegraph_regression.py` |
| `instantiates`-Relation | **NICHT gebaut** (braucht Call-Graph) | — |
| Stufe 2 (tree-sitter-Sprachen) | **NICHT gebaut**, per Plan | — |
| Typ-Layer als DSS-Kanal / `type_blindspot`-Band | **NICHT gebaut**, weiterhin gegated | — |
| A/B-Frontier-Eval + Komparator | **NICHT gebaut** | — |
| OFM-`[[wikilink]]`-Parsing + Auflösung (K1-Backend) | **IMPLEMENTIERT, aber UNVERDRAHTET** — `index.py` ruft nur `internal_links` | `markdown.py` (+398 Zeilen) |

### Was der Layer über sich selbst berichtet [MEASURED 2026-07-30, Chronicle-Pass]

`build_index("daedalus/", types=True)`, serieller Scan, 156 Python-Dateien. Der Baum wurde
während des Laufs von einem zweiten Agenten (Codex) editiert — die Dateizahl ist deshalb
gegenüber der Hub-Vormessung (143) gewachsen, und diese Zahlen sind eine Momentaufnahme,
kein eingefrorener Baseline-Wert. Eingefroren sind nur die Fixture-Zahlen in der Testsuite.

**Struktur**: 333 Typ-Deklarationen · 1734 Felder · 2067 Knoten · **2599 Kanten**
(`has_field` 1734, `field_type` 102, `inherits` 34, `consumes` 339, `produces` 390,
`alias_of` 0) · `graph_version` 1 · `parse_version` 1.

**Auflösungs-Buckets** (die Summe ist als Test gepinnt: `attempts` == Summe der sechs):
`attempts` **7112** = `resolved` **864** + `builtin` **5605** + `external` **619** +
`unresolved` **24** + `ambiguous` **0** + `vocabulary` **0**.
Die 24 Unaufgelösten sind ehrlich gezählt und benannt (`unresolved_sample`); der Bulk sind
Modul-Aliase in nackter Zuweisungsform (`AgentEvent = Union[...]`,
`PromptMode = Literal[...]`), die `parse.py` bewusst NICHT als Deklaration mintet, weil
`X = ...` auf Modulebene meist eine Konstante ist.

**Annotations-Coverage** (der Nenner, den der Plan als Thermometer verlangt hat):
Returns **2330 / 2410 = 96,7 %** (Planbaseline war 97 % [INHERITED 2026-07-29] — hält),
Parameter **3822 / 4161 = 91,9 %**, Felder **1500 / 1734 = 86,5 %**.
Sites gesamt 8398, davon annotiert 7745, fehlend 653, `Any` 188, `Any` im Inneren 674,
`None` 266, ohne Member 465, Union 169, unparsebar **0**.
`dropped_keys` **646** — so oft wurde bei `dict[K, V]` der Key-Typ verworfen (Warnung W2:
jede `str`-Zahl ist damit eine UNTERGRENZE, und die Zahl steht im Index statt im Kopf).

**Refusals und Wachen**: `hub_cap` 64, `hub_suppressed_edges` 0, `hub_suppressed_types` []
(siehe Invariante 6 — der Cap ist hier inert), `duplicate_declarations` 0,
`files_truncated` [], `truncated` false, `structural_matches` 1 (Protocol-Heuristik,
`min_members` 2 / `max_matches` 25), `structural_overmatched` [],
`future_annotations_files` 138.

**Sprachumfang** wie [M8] verlangt: `languages = {"python": "supported",
"javascript": "not_supported"}` — ein String, nie eine numerische Null.

**Additivität** [MEASURED 2026-07-30]: mit Layer AN kommen exakt drei Schlüssel hinzu
(`types`, `type_nodes`, `type_edges`); von den 17 gemeinsamen Schlüsseln bewegt sich genau
einer — `scope_key` (`…/daedalus` → `…/daedalus+types`), und das ist der Zweck des Gates.
Im Forest: 157 → 2224 Knoten (`source_file` 157 unverändert, + 333 `type`, + 1734 `field`),
122 → 2721 Kanten (`imports` bleibt bei 122). Der `content_sha256` des Forest wandert
(347b9ffe… → c36aeb2e…) — genau deshalb ist der Default AUS, und ein Umlegen ist eine
bewusste Re-Baselining-Entscheidung.

### Schema (neue Node-Kinds + Relationsschichten im Forest)

Node-Kinds: `type` (Klasse/Dataclass/TypedDict/NamedTuple/Enum/Protocol — ein Node pro
Deklaration), `field` (Kind-Node eines `type`). Funktions-Units existieren schon.

| Relation | Von → Nach | SOTA-Pate | Stand 2026-07-30 [MEASURED, `daedalus/`] |
|---|---|---|---|
| `has_field` | type → field (Attr: annotation; Kante weiter zum Feld-Typ) | CPG MEMBER, CodexGraph HAS_FIELD | **gebaut**, 1734 Kanten |
| `field_type` | field → type (die "Kante weiter zum Feld-Typ" aus der Zeile darüber) | CPG EVAL_TYPE | **gebaut**, 102 Kanten — **NICHT in der ursprünglichen Liste**; eigene Relation, weil die Richtung umgekehrt zu `has_field` läuft und eine Schicht mit zwei Richtungen unlesbar ist. Konstante `REL_FIELD_TYPE`, Umbenennen = eine Zeile |
| `inherits` | type → type (Protocol-Matches: `structural=True`) | CodexGraph INHERITS, SCIP is_implementation | **gebaut**, 34 Kanten (davon 1 strukturell) |
| `consumes` | function → type (eine Kante pro Param; Attr: param, position, union_id) | CPG PARAMETER_IN→EVAL_TYPE; SyPet | **gebaut**, 339 Kanten. Quelle ist die **Datei** (`rel`), nicht ein Funktionsknoten — Funktionen sind heute keine Forest-Knoten; die Funktionsidentität reist in `attributes.function` / `function_ref` |
| `produces` | function → type | CPG METHOD_RETURN; SyPet | **gebaut**, 390 Kanten (gleiche Quellen-Konvention) |
| `instantiates` | function → type (Konstruktor-Calls aus bestehendem Call-Graph) | CodexGraph USES/CALLS | **NICHT gebaut** — braucht den Call-Graph; ein Test pinnt die Abwesenheit |
| `alias_of` | type → type (TypeAlias) | SCIP is_type_definition | **gebaut**, aber **0 Kanten** auf `daedalus/`: nur unzweideutige Formen (`X: TypeAlias = …`, PEP 695 `type X = …`, `NewType(…)`) werden erkannt; nacktes `X = int` wird VERWEIGERT |

### Pitfall-Policy (verbindlich, aus dem Research gerankt)

1. **Optional/Union**: beim Parsen normalisieren — `Optional` strippen, pro Union-Member
   eine `consumes`-Kante mit gemeinsamer `union_id`. PEP-604 `X | None` ≡ `typing.Optional[X]`.
2. **Generics**: KEIN Node pro Instanziierung (`list[User]` explodiert). Kante zielt auf den
   Element-Nominal-Typ, `container`-Attribut trägt die Hülle. (TYGAR-Lektion.)
3. **Dict-Blobs**: TypedDict first-class; später optional `x["key"]`-Mining als Pseudo-Felder
   mit `provenance=mined`. Bis dahin: Coverage ehrlich reporten statt raten.
4. **PEP 563 / Forward-Refs**: String-Annotationen sind der NORMALFALL. Zwei Pässe:
   erst alle Typ-Nodes, dann Auflösung über den bestehenden import-aware `SymbolResolver`.
5. **Protocol**: Member-Namens-Schnittmenge → `inherits(structural=True)`, als Heuristik geflaggt.
6. **`Any`/fehlende Annotation**: NIEMALS eine Kante auf einen Any-Node (Hub vergiftet jedes
   Ranking). Stattdessen Coverage-Zahl im Index — der Layer reportet sein eigenes Vertrauen.

### Fusion in die Daedalus-Maschinerie

1. **parse.py**: `ClassDef` + `AnnAssign` + Signatur-Annotationen im SELBEN `ast.parse`,
   der heute schon Units+Imports liefert (kein zweiter Parse; Muster
   `python_units_and_imports` fortgesetzt).
   → **ERLEDIGT**: neuer Einstiegspunkt `python_units_imports_and_types()` (ein `ast.parse`,
   drei Walks); `python_units_and_imports`/`extract_units` **unverändert** (0 gelöschte
   Zeilen im Diff). Extraktion läuft UNBEDINGT (auf dem inhaltsgeschlüsselten Disk-Cache),
   nur Auflösung + Publikation sind gegated — die Gegenoption wurde reproduziert und
   liefert stumm einen leeren Typblock aus einem layer-OFF-gewärmten Cache.
2. **index.py**: neue Index-Blöcke `types`, `type_edges` — derived, cached, deterministisch.
   → **ERLEDIGT**, plus `type_nodes` als dritter Block; Gate `types=True` /
   `DAEDALUS_INDEX_TYPES=1` / `--types`, Default AUS, `+types` im `_scope_key` an allen
   drei Aufrufstellen. Kosten [INHERITED, Stage-3-Messung]: +0,48 s Extraktion über 152
   Dateien (3,1 ms/Datei, nur bei Cache-MISS) und +0,28 s Auflösung.
3. **forest.py**: Node-Kinds `type`/`field`, Relationen wie oben. Per Vertrag OHNE
   Schema-Bump (Muster: `document`-Kind).
   → **ERLEDIGT**: `type`/`field` leben in einem eigenen `type_ids`-Set; `module_ids` (das
   Mitgliedschafts-Gate von vier anderen Schichten) wächst NICHT. Zusätzlich gehärtet:
   `dss.build_context_plan` prüft jetzt den Node-KIND (nicht nur Mitgliedschaft) und
   `_relation_adjacencies` filtert Diffusion auf File-Knoten — I3 und I6 ruhen damit auf
   Struktur statt auf dem Config-Default `unknown_relation_weight = 0.0`.
4. **Konsumenten** (der eigentliche Payoff, je eine eigene Lane NACH dem Fundament):
   - **DSS/context_plan**: Typ-Nachbarschaft als Evidenzquelle — "Task berührt `DSSResult`
     → auch Producer/Consumer von `DSSResult` in den Slice" (Aider-Lektion: Ranking über
     den Graphen ist der Liefermechanismus an LLMs, nicht der Graph selbst).
   - **Picker**: neue Kandidaten-Band `type_blindspot` (dict-Blob-Hotspots: hohe Fan-in-
     Funktion ohne Typ-Kanten) — Evidence-first wie alle Bänder.
   - **Fence (später, separat durch Minos/Cerberus)**: typed reachability ("welche Edits
     erreichen eine Struktur, die eine gefencte Komponente konsumiert").
   - **Ikarus/Wiki**: Typ-Seiten als Link-Ziele (`[[type:...]]`, s. Teil B).
5. **Sidecar-Lane (optional, aus)**: scip-python-Enrichment für unannotierte Fremd-Repos.

### Thermometer (jede Behauptung mit Test)

- Determinismus: gleicher Tree → byte-identischer `type_edges`-Block über 5 PYTHONHASHSEEDs
  (Muster der bestehenden Resolver-Tests).
  → **ERFÜLLT UND ÜBERTROFFEN** [MEASURED 2026-07-30]: sieben frische Interpreter über
  sechs `PYTHONHASHSEED`-Werte inkl. `random`, plus ein Lauf auf dem parallelen Scan-Pfad,
  ein identischer sha256 (`tests/test_typegraph_determinism.py`, 43 Tests).
- Kein Any-Hub: Test, dass `Any`/unaufgelöste Namen keine Kanten erzeugen.
  → **ERFÜLLT**: `Any` steht nie in `Annotation.members` (`is_any`/`has_any` stattdessen),
  unaufgelöste Namen minten weder Knoten noch Kante und werden gezählt; jeweils mit
  Positivkontrolle, damit "verweigere alles" nicht durchkommt.
- Coverage-Report: `types.coverage` ∈ Index, gegen die MEASURED-Baseline (97 % Return-Ann.).
  → **ERFÜLLT**: 96,7 % gemessen gegen 97 % Baseline [MEASURED 2026-07-30 vs
  INHERITED 2026-07-29] — die Baseline hält.
- **Regressions-Thermometer T1/T2/T3** (der eigentliche Additivitätsbeweis):
  → **ALLE DREI GRÜN, KEINES GEFALLEN** (`tests/test_typegraph_regression.py`, 30 Tests /
  119 Subtests). Vier absichtlich injizierte Lecks (Typ-Deklarationen in `all_units`,
  Typ-/Feldnamen in `defs_by_file`, je gegated und ungegated) haben alle gefeuert.
  **Bekannte strukturelle Grenze, nicht wegzudiskutieren**: die Extraktion ist bewusst
  UNGEGATED, also ist ein Leck auf der Extraktionsseite in beiden Builds identisch und für
  jeden off/on-Byte-Vergleich UNSICHTBAR. Gefangen wird er nur von den ABSOLUTEN
  Assertions daneben (Block ist leer, kein Cluster nennt einen Typ, jeder Name stammt aus
  `extract_units`). Wer diese Hälfte als "redundant" löscht, löscht die einzige Hälfte,
  die den ungegateten Fall sieht.
- Konsumenten-Nutzen: context_plan-Eval vorher/nachher auf minted tasks — der Layer muss
  einen MESSBAREN Slice-Gewinn zeigen oder bleibt eine Linse ohne Routing-Einfluss.
  → **OFFEN, nicht gemessen.** Der Layer ist heute genau das: eine Linse ohne
  Routing-Einfluss. Das ist der Zustand, den der Plan verlangt, nicht ein Versäumnis —
  aber der Nutzen-Nachweis steht aus.

### Frontier-Claim (Owner-Entscheid 2026-07-29: "Above and beyond")

Die Literatur hat KEINE Ablations-Evidenz, dass ein Typ/Feld-Layer LLM-Agents hilft
(CodexGraphs HAS_FIELD ist der nächste Nachbar, unabgelatet). Wir liefern sie — aber nur
mit einem Eval, das den Effekt überhaupt sehen KANN. Momus [M7] hat zwei strukturelle
Defekte im ersten Entwurf gefunden, die vorab ausgeschlossen werden:

- **Die Metrik war monoton in der Behandlung.** `must_include`-Recall kann nur steigen,
  wenn man einem Slice Nachbarn hinzufügt — es sei denn, das Token-Budget bindet. Ein
  unbudgetiertes A/B hätte "Typ-Kanten helfen" für JEDES Kantenset gemeldet, auch ein
  zufälliges.
- **Der Task-Mix war, was zufällig committet wurde.** Minted tasks sind diff-abgeleitet;
  docref-Tasks üben den Typ-Layer NULL mal aus. Ein A/B über ein Korpus, in dem die
  Behandlung nichts verändert hat, ist ein Nicht-Resultat — und das als "Null-Resultat" zu
  publizieren wäre die eigentliche Reputationskatastrophe: "wir haben gemessen und keinen
  Effekt gefunden", wo die Wahrheit "wir haben die Behandlung nie angewandt" ist.

**Prä-Registrierung (verbindlich, vor dem ersten Lauf):** (a) FIXES Token-Budget → gemessen
wird Recall-bei-gleichen-Tokens PLUS ein Präzisionsmaß; (b) ein **Zufallskanten-Kontrollarm**
(gleiche Kantenzahl, zufällige Ziele) — schlägt die Behandlung den Zufall nicht, gibt es
keinen Effekt; (c) berichteter Nenner ist *n_tasks, in denen der Typ-Layer den Slice
überhaupt verändert hat*; liegt der unter einer vorab festgelegten Untergrenze, lautet das
Ergebnis "underpowered, Behandlung nicht ausgeübt" — NIE "kein Effekt".
`eval/mint.py` liefert dafür Tasks, aber KEINEN A/B-Komparator, keine Wiederholungen,
keine Seeds, keine Konfidenzintervalle. Der Komparator ist eigene Arbeit und eigene Lane.

### Aufwand

Fundament (1–3): ~1–2 Sessions, null neue Deps. Konsumenten (4): je eigene kleine Lane.
Sidecar: separat, nur bei Bedarf.

---

## Teil B — Knowledge-Space: Confluence × Obsidian

### Befund

`KnowledgeSpace.tsx` zeigt Loop-Telemetrie (Queue/Attempts/Architecture) → zieht um nach
Mission Control. Backend-Hälfte des Wikis EXISTIERT schon in structcore: Dokumente als
Node-Kind, Heading-Baum (`DocSection` ≙ CodeUnit), Intra-Repo-Links als `documents`-Kanten,
Backlinks = Reverse-Kanten. Es fehlen: `[[wikilink]]`-Syntax, Schreibpfad, API, UI.

### Owner-Entscheide (2026-07-29)

1. Echtes Wiki, **von Agenten maintainbar** (Schreibpfad ist first-class, nicht Beiwerk).
2. **Nested Wikis**: ein globales Wiki + projektabhängige Wikis, mit Cross-Wiki-Links.
3. Falls Obsidian nicht geht: andere Open-Source-Alternative — Verdikt unten.

### Obsidian/Open-Source-Verdikt [VERIFIED 2026-07-29, Quellen im Sweep]

**Keine App absorbieren — Vault-Format-kompatibel sein und eigene UI bauen.**

- **Obsidian**: proprietär/closed-source (seit Feb 2025 zwar auch kommerziell frei
  NUTZBAR, aber kein SDK, kein Embedding, keine Redistribution). Das FORMAT ist offen:
  Ordner voller `.md` + `[[wikilinks]]` (inkl. `#heading`, `|alias`, `![[embeds]]`,
  Callouts) + YAML-Frontmatter; Canvas ist als **JSON Canvas** (MIT, jsoncanvas.org)
  spezifiziert. Vault-Kompatibilität = User kann unser Wiki jederzeit in Obsidian öffnen.
- **Lizenz-K.O.s fürs Produkt**: Logseq/AppFlowy/Wiki.js = AGPL-3.0, Outline = BUSL-1.1,
  Anytype = source-available (nicht OSI). Nichts davon in ein kommerzielles Tauri-Produkt.
- **AFFiNE**: Lizenz gemischt (MIT-Kern), aber CRDT-Block-Store statt Markdown-Dateien —
  architektonisch falsch für agent-writable Vaults.
- **MIT-Code klauen, keine Apps**: Quartz' Obsidian-Flavored-Markdown-Transformer
  (MIT, TypeScript) fürs Rendering; Foams Link-Graph-Core (MIT) als Referenz;
  SilverBullet (MIT, CodeMirror-6-Wikilink-Maschinerie) als Architektur-Steinbruch.
- **Nested Wikis**: Obsidian KANN keine Cross-Vault-Links (offenes Feature-Request seit
  2021) — wir können hier besser sein als das Vorbild. Muster: Dendron-/MediaWiki-Style
  Prefix-Links, aber als EIN reserviertes Literal `[[vault:NAME/pfad]]` (siehe B-M2:
  `[[global/note]]` wäre von einem echten Relativpfad nicht unterscheidbar gewesen).
  **Ehrliche Grenze des Escape-Hatch**: Intra-Vault-Links sind voll Obsidian-kompatibel;
  Cross-Vault-Links sind UNSERE Erweiterung, die Obsidian als unaufgelöst anzeigt.
  Frühestens K6, mit eigener Review-Runde.
- **Agent-maintained (Prior Art 2024–26: DeepWiki, Karpathys LLM-Wiki, CLAUDE.md-Ökosystem,
  Letta)** — die funktionierenden Konventionen sind exakt unsere Doktrin: deterministisches
  Datei-Layout, ein Index/MOC-File, das der Agent aktuell hält, Frontmatter-Schema
  (owner, updated, provenance, status), relative Links + Link-Checker, Staleness-Checks
  per Schedule statt Agentengedächtnis. Agentenschreibpfad läuft durch dieselben
  Gated Writes wie Code — ein Wiki-Edit ist ein Intent mit Gate, kein Sonderweg.

### UI-Research-Verdikt (Kurzfassung)

- **Lokaler Graph zuerst** (Tiefe 1, expandierbar auf 2, gefärbt nach Typ/Space, Filter):
  globale Graphen sind das, was alle "hübsch aber nutzlos" nennen. Global = sekundärer
  "Map"-Tab, immer vorgefiltert.
- **Backlinks-Panel + Unlinked Mentions ≈ 90 % des Werts.** Block-References: bewusst NEIN
  (Outliner-Feature, braucht Block-Datenbank).
- **Confluence-Anteil**: Spaces + flacher Page-Tree + Status-Chips (Draft/Verified/Stale) +
  typed Page-Properties. Gehasst wird ungoverntes Wuchern → Space-Anlage bewusst machen.
- **Typed Pages nach Capacities-Modell**: JEDE Seite hat genau EINEN Typ
  (`note`, `spec`, `adr`, `run-report`, `agent`, `concept`) mit typdefinierten Feldern
  im Frontmatter — passt 1:1 auf unseren typed Forest.
- **Code-Links als First-Class-Kanten (Swimm-Modell)**: `[[code:daedalus/loop.py#run]]` =
  doc→code-Kante MIT Staleness-Check (Ziel verschoben/gelöscht → Chip "Stale"). Mit Teil A
  auch `[[type:DSSResult]]`. Das ist der Merge, den weder Confluence noch Obsidian haben —
  und published prior art hat das kombinierte Code+Docs-Graph-View NICHT: offenes Terrain.
- **Libs**: Graph = `sigma.js + graphology + @react-sigma/core` (WebGL, 1–5k Nodes, Worker-
  Layout; graphology liefert n-hop-Extraktion gratis). Editor = **BlockNote** (React,
  Notion-Gefühl, dokumentiertes Custom-Inline-Content-Rezept für `[[`-Autocomplete,
  Markdown-Roundtrip). Fallback pur-Markdown: CodeMirror 6.

### NON-GOALS / INVARIANTEN (Momus-Runde 2026-07-29 — GO-WITH-CHANGES; K2 + globaler Vault NO-GO wie geschrieben)

Drei CRITICALs, alle im Schreib-/Sicherheitspfad, alle drei selbst nachverifiziert:

**B-C1 · "Schreibpfad durch die bestehende Gated-Writes-Maschinerie" war ein
Kategorienfehler — und er fällt OFFEN aus.** [VERIFIED] `gated_writes` ist kein
Write-Fence, sondern eine Provider-Attempt-Pipeline. Ihr Gate lautet wörtlich
`ok = res.get("action") == "offloaded" and bool(res.get("wrote"))` — ein menschlicher
Editor-PUT hat kein Offload, also **scheitert JEDER Save**, und zwar ohne Exception
(`{"status": "write_gate_failed"}`). Naiv verdrahtet: ein Speichern-Button, der still
nie speichert, und kein Test schlägt an. Zweitens verspricht die Maschinerie strukturell,
dass der primäre Checkout UNBERÜHRT bleibt — ein *erfolgreicher* gegateter Wiki-Write
landet also auf einem Integrations-Branch, während die Datei auf der Platte alt bleibt.
Der Obsidian-Escape-Hatch bricht genau dann, wenn der Schreibpfad funktioniert.
→ **Zwei getrennte Pfade, explizit:**
  (a) **Mensch-PUT** = neues, eigenes `knowledge.write_page` mit HIER aufgezählter
      Gate-Liste: (i) Vault-Root-Confinement, (ii) `path_write_blocked`,
      (iii) Frontmatter-Schema-Validierung, (iv) atomarer Write + fsync + Vault-Commit,
      (v) loopback + `_authorized()`. Eine ANDERE Gate-Liste als Code-Writes — aufgeschrieben,
      nicht per Analogie delegiert.
  (b) **Agent-Wiki-Edit** = normale Offload-Task mit `target_paths` unter dem
      **In-Repo-**`docs/wiki/`. Nur DIESER Pfad reitet auf gated_writes. Niemals der
      globale Vault.

**B-C2 · Der globale Vault (`~/.daedalus/wiki/`) bricht vier Repo-Invarianten — er wird
zu K6 mit eigener Momus-/Cerberus-Runde.** [VERIFIED]
  (a) Der Index ist single-root (`os.walk(root)`, `_scope_key` = resolved root). Zwei Vaults
      = zwei Indizes = zwei Forests, aber `build_knowledge_forest` konsumiert EINEN.
      **Cross-Vault-Links — der ganze Punkt der Nested Wikis — sind mit dem heutigen Forest
      gar nicht auflösbar.** "Kein zweites System" ist für den globalen Vault FALSCH: das ist
      ein Multi-Root-Join, kein neuer Node-Kind.
  (b) `write_allow` ist Prefix-Arithmetik ab Repo-Root; ein Home-Pfad ist entweder
      unschreibbar oder AUSSERHALB des Confinements — die Fail-open-Form, die diese
      Funktion gerade verhindern soll.
  (c) **Egress: `.md` steht auf der Allow-Liste**, und `_path_is_sensitive` prüft
      `allow_substrings` VOR `default_deny` [selbst verifiziert: `'.md' in
      GENERIC_ALLOW_SUBSTRINGS`, Reihenfolge bestätigt]. Heute heißt `.md` "Doku über
      dieses Repo". Zeigt ein Vault auf die PERSÖNLICHE Wissensbasis eines Users, ist jede
      private Notiz egress-frei zu einem untrusted Provider — davor steht nur der
      wertförmige Secret-Floor, der PEM-Blöcke und AWS-Keys fängt, aber keinen Klientennamen.
      Das hat noch niemand bepreist. **Cerberus-Sache, vor jeder Zeile Code.**
  (d) `PUT /api/knowledge/page/<rel>` ist die ERSTE Traversal-Fläche der API: alle
      bestehenden Pfad-Parameter sind IDs gegen `^[A-Za-z0-9._-]{1,160}$` — `/` verboten,
      Traversal per Konstruktion unmöglich. Ein Wiki-Rel MUSS `/` enthalten.
      → Benannter Validator `vault_rel(vault_root, rel) -> Path | None` mit Reject-Liste im
      Thermometer: absolute Pfade; JEDES `..`-Segment VOR der Auflösung; Nicht-`.md`;
      Symlink irgendwo in der aufgelösten Kette; `:`/NTFS-ADS/reservierte Gerätenamen;
      dann `resolve().relative_to(vault_root.resolve())`. Bedrohung wird im Plan benannt:
      **"arbitrary-write traversal auf PUT"**, damit Cerberus etwas zu vetoen hat.

**B-C3 · Dokumente sind DEFAULT AUS — K1 würde einen Schalter umlegen, den das Repo
absichtlich aus hält.** [VERIFIED] `documents_enabled` ist ohne Env-Var False, und
`web_api.py` übergibt `documents=` **null Mal**. Das "schon existierende Wiki-Backend" ist
ein Pfad, den die Web-Schicht noch NIE ausgeführt hat. Der Preis des Umlegens steht im
Repo selbst: der Degenerate-Index-Detektor des Routers hört auf zu feuern, und die
BM25-Normalisierer verschieben sich → **jeder Code-Datei-Seed-Score wandert**, "eine
Ranking-Änderung ohne Code-Änderung". Das würde außerdem Teil A's A/B konfundieren.
→ **`documents=True` wird PER CALL nur von den Knowledge-Endpoints angefordert** (eigener
`+docs`-Scope-Key); der Env-Default bleibt aus, bis das Eval neu baselined ist. Teil A's
A/B deklariert, auf welcher Seite des Schalters es lief.

**B-M1 · Es gibt keinen Invalidierungspfad, und "Rebuild bei jedem Save" ist unbezahlbar.**
`_INDEX_CACHE` ist auf root+scope+docs geschlüsselt — ohne mtime, Content-Hash oder
Git-Rev. Ein PUT ändert die Datei, der Key wandert nicht, Backlinks servieren den
Vor-Edit-Stand bis zum Prozess-Restart. `refresh=True` wäre ein Vollrebuild, und das Repo
hat gemessen, was das auf dem ThreadingHTTPServer kostet: ein paralleler zweiter Scan eines
6.8k-Datei-Baums "erschöpfte den Speicher und nahm die Seite runter".
→ Dokumenten-Sub-Index mit eigenem Key inkl. Vault-Fingerprint (Hash über sortierte
`(rel, mtime_ns, size)`), unabhängig vom Code-Index rebuildbar. Thermometer:
**GEMESSENE P95-Latenz Save→Backlink-sichtbar bei N Seiten**, plus das N, ab dem der Plan
Degradation zugibt.

**B-M2 · Prefix-Links brechen die Obsidian-Kompatibilität — die Behauptung war unehrlich.**
`[[project:foo/note]]` löst Obsidian als Seite mit Namen `project:foo/note` auf; `:` ist auf
NTFS illegal, also dauerhaft toter Link. Schlimmer: `[[global/note]]` ist von einem legitimen
Relativpfad `global/note.md` NICHT unterscheidbar — der Fehlermodus wechselt von
*unaufgelöst* zu *auf den falschen von zwei Kandidaten aufgelöst*. Das ist Fabrikation.
→ Namensraum per KONSTRUKTION eindeutig, nicht per Präzedenz: ein einziges festes Literal
`[[vault:NAME/pfad]]`, wobei `vault` ein RESERVIERTER Top-Level-Verzeichnisname ist, den der
Validator nicht anzulegen erlaubt. Kompat-Satz wird ersetzt durch: "Cross-Vault-Links sind
UNSERE Erweiterung; Obsidian zeigt sie unaufgelöst. Intra-Vault-Links sind voll kompatibel.
Das ist die Grenze des Escape-Hatch." Thermometer: Ein Doc mit `[[global/note]]` UND einer
echten lokalen `global/note.md` löst auf die lokale Datei auf und ZÄHLT die Ambiguität.

**B-M3 · K5 ist eine Schreibschleife ohne Fixpunkt und ohne Schlichtung.**
Nichts im Plan sagt, was einen Edit UNNÖTIG macht. Vorhersage: die MOC-Datei wird jede
Iteration kosmetisch umsortiert, jeder Rewrite ist ein Commit, jeder invalidiert Backlinks,
das Ledger füllt sich mit `did_work: true` für null Information. Und die Konfliktasymmetrie
ist verkehrt: die AGENT-Seite hat Base-Revision-Konfliktbehandlung, die MENSCH-Seite hat
keine — last-write-wins, still, über eine im Editor offene Seite.
→ (1) K5 braucht einen benannten, maschinenprüfbaren Prädikat-Fixpunkt (doc→code-Ziel fehlt /
Frontmatter-Feld fehlt / unresolved-link-count > 0), und **dasselbe Prädikat muss nach dem
Edit FALSCH sein — das ist das Gate**. Kein Prädikat, keine Lane. (2) Pro-Seite-Edit-Budget
und "kein Agent-Edit innerhalb von N nach einem Menschen-Edit derselben Seite".
(3) Mensch-PUT trägt das gelesene `updated`-Frontmatter als **If-Match-Vorbedingung;
Mismatch = 409**, niemals stilles Überschreiben.

**B-Mi2 · BlockNote-Roundtrip ist für OFM nicht verlustfrei** (kein Modell für YAML-
Frontmatter — worauf K3 baut —, keine Callouts, keine `![[embeds]]`, kein `#heading|alias`).
→ Invariante statt Bibliothek: **"Ein Save darf niemals ein Byte ändern, das der User nicht
editiert hat"**, erzwungen durch einen Byte-Identitäts-Test parse→serialize über ein
OFM-Fixture-Korpus; Frontmatter ist ein Sidecar, das der Editor nur liest und verbatim
zurückschreibt. Fällt BlockNote durch diesen Test, ist CodeMirror 6 die Wahl, kein Fallback.

**B-Mi3 · Unlinked Mentions** sind neue Determinismus- UND Kostenfläche: in den
Determinismus-Test aufnehmen (5 Seeds), und `max_mentions_per_page` im Plan deklarieren —
ein Wort wie "agent" matcht jede Seite, unbeschränkt ist das UI-Kollaps und quadratischer Scan.

**B-Mi4 · Der "Stale"-Chip kann in BEIDE Richtungen falsch sein**, weil er gegen einen
Index ohne Invalidierungs-Key prüft. → Staleness löst gegen den `scope_key` des Code-Index
auf, und der Chip zeigt an, WELCHER Build geantwortet hat. Die Ehrlichkeits-Doktrin gilt
auch für die Provenienz des Chips, nicht nur für sein Ziel.

**Was müde ist (Momus, wörtlich):** "Route the write through the existing gated-writes
machinery" ist der Reflex, der einen Plan sicherheitsbewusst AUSSEHEN lässt, ohne dass
jemand gelesen hat, was die Maschinerie verlangt. Und: Page-Tree + Editor + Backlinks +
Force-Graph ist die meistgebaute Form der Kategorie. Der eine wirklich neue Anspruch ist der
untertriebene und aufgeschobene — `[[code:]]`/`[[type:]]`-Kanten mit Staleness, Docs und Code
in EINEM Graphen. Der steht als K4 an vierter Stelle, hinter drei Phasen Tischgedeck.
→ **Konsequenz: K4 wird hochgezogen, sobald Teil A liefert. Das ist der Differenzierer,
nicht der Page-Tree.**

### Architektur

1. **Storage**: Obsidian-kompatible Vaults aus reinen Markdown-Dateien. **K1–K5 nur
   Projekt-Vault** (`docs/wiki/`, im Repo — dort halten Confinement, Egress-Regeln,
   Index-Root und Traversal-Schutz alle schon). Globaler Vault + Registry = **K6**,
   eigene Review-Runde. Frontmatter: `type`, `status`, `space`, typspezifische Felder.
   Git = Versionierung.
2. **markdown.py erweitern**: OFM-`[[wikilink]]` (inkl. `#heading`/`|alias`) und
   `[[code:…]]`/`[[type:…]]`, gleiche Refuse-to-guess-Regel wie heute (unaufgelöster Link
   wird GEZÄHLT, nie geraten). Cross-Vault-Literal `[[vault:NAME/pfad]]` erst in K6.
   Quartz' MIT-OFM-Transformer als Referenz/Rendering-Baustein.
   → **IMPLEMENTIERT (Parsing + Auflösung), aber NICHT VERDRAHTET** [MEASURED 2026-07-30:
   `tests/test_markdown_wikilinks.py` 35 Tests grün, im Gesamtlauf enthalten]. `DocLink`
   hat `embed`/`alias`/`namespace` und vier neue Kinds (`wiki`, `code`, `type`,
   `deferred`); `[[Note]]`, `[[Note#Heading]]`, `[[Note|alias]]`, `![[embed]]`,
   `[[code:pfad#symbol]]`, `[[type:Name]]` werden geparst, in Fences/Backticks NICHT.
   Auflösung in `wiki_lookup` / `resolve_wiki_target` / `resolve_wiki_links` /
   `knowledge_links`; unaufgelöst wird gezählt und verworfen, MEHRDEUTIG (Bare-Name-
   Kollision oder Pfad, der vault-root- UND dokument-relativ lesbar ist) erzeugt **keine**
   Kante und zählt als `ambiguous` — B-M2's Thermometer ist damit erfüllt. `[[type:]]` /
   `[[vault:]]` zählen als `deferred`, nie als unresolved.
   **`internal_links` (was `index.py` heute konsumiert) ist absichtlich UNVERÄNDERT**, also
   bewegt sich heute keine einzige bestehende Dokumentkante — und es entsteht auch keine
   neue: Wiki-Kanten erreichen keinen Aufrufer. Beim Verdrahten offen: `n_links_unresolved`
   sollte drei Schlüssel werden (`unresolved`/`ambiguous`/`deferred`), sonst werden drei
   verschiedene Aussagen wieder zu einer Summe verrührt.
3. **API (web_api.py)**: `GET /api/knowledge/tree`, `GET/PUT /api/knowledge/page/<rel>`,
   `GET /api/knowledge/backlinks/<rel>` (+ unlinked mentions), `GET /api/knowledge/graph/local?
   node=&depth=`. Schreibpfad = eigenes `knowledge.write_page` mit der Gate-Liste aus B-C1(a);
   `vault_rel`-Validator vor JEDEM Pfad-Zugriff; loopback-only; `documents=True` per Call.
4. **UI**: dreispaltig — Page-Tree (Spaces) · Editor/Reader · rechtes Panel
   (Backlinks, Unlinked Mentions, lokaler Graph). Status-Chips im Tree und auf der Seite.
5. **Staleness**: doc→code-Kante prüft gegen den Code-Index und zeigt mit, welcher Build
   geantwortet hat; tote Kante = sichtbarer "Stale"-Chip, nie stiller Bruch.

### Phasen (nach Momus neu geschnitten)

- **K0** (frei): Telemetrie-Tabs nach Mission Control. Klein — `KnowledgeSpace` hat zwei
  Props und drei eigenständige Tabs. MIT umziehen: das `loopDegraded`-Badge und BEIDE
  `goSpace('knowledge')`-Deeplinks, sonst leuchtet "Knowledge" für Loop-Fehler, die es
  nicht mehr zeigt.
- **K1 (Lesen)** (frei): Tree + Reader + Backlinks + lokaler Graph, **Projekt-Vault only**,
  `documents=True` per Call, Dokumenten-Sub-Index mit Vault-Fingerprint, gemessene
  Save→sichtbar-Latenz.
- **K2 (Schreiben)** — **BLOCKIERT** bis §3 die Mensch-PUT-Gate-Liste und den
  `vault_rel`-Validator mit Reject-Liste aufzählt und If-Match steht. Dann **Cerberus
  reviewt den PUT, vor Code.**
- **K3 (Typed)**: Frontmatter-Typen, Status-Chips, Property-Tabellen + Byte-Identitäts-Test.
- **K4 (Code-Merge, DER DIFFERENZIERER)**: `[[code:]]`/`[[type:]]`-Kanten + Staleness.
  Wird vorgezogen, sobald Teil A liefert. → **Teil A liefert jetzt**, und die Syntax
  `[[code:…]]`/`[[type:…]]` wird bereits geparst und in getrennten Buckets aufgelöst.
  Es fehlen: Verdrahtung in `index.py`, die Auflösung von `[[type:Name]]` gegen
  `type_nodes` (heute bewusst `deferred`, weil der Typ-Layer default-AUS ist) und der
  Staleness-Chip. Das ist der Differenzierer und er ist jetzt technisch entblockt.
- **K5 (Agent-Maintenance)** — **BLOCKIERT** bis der Fixpunkt-Prädikat benannt ist.
- **K6 (globaler Vault + Registry)** — neue Phase, eigene Momus-/Cerberus-Runde, gegated auf
  schriftliche Antworten zu Multi-Root-Join, Write-Confinement und `.md`-Egress-Allow-Liste.

---

## Teil C — UI-Gesamtstrategie & Skills

Owner-Verdikt: "Die ganze UI ist blöd" + "Das Produkt hat sich komplett verändert" →
Redesign wird aus der neuen IA abgeleitet (Tabelle oben), Glass-DNA ("cold glass, warm
voice") bleibt.

Vom Owner vorgegebene Quellen, eingearbeitet:

1. **Skills installieren** (nach Sichtung der SKILL.md + Scripts — Snyk warnt: 13 % der
   Community-Skills mit kritischen Flaws, 36 % mit Prompt-Injection; vor Install lesen):
   - `anthropics/skills` → `frontend-design` (Creative-Director-Pass; bannt Generik-Fonts,
     pusht Komposition/Motion) — Konsens-Winner beider Artikel.
   - `nextlevelbuilder/ui-ux-pro-max-skill` (durchsuchbare Design-DB: 84 Styles, 192 Paletten,
     74 Font-Pairings, Design-Dials variance/motion/density; Prioritätenliste A11y > Touch >
    Performance). Python-Search-Tool passt zur Harness (kein jq-Problem).
   - `vercel-labs/agent-skills` → `web-design-guidelines` (100+-Regel-Audit) als
     REVIEW-Gate nach jedem UI-Beat, nicht als Generator.
2. **Einsatz**: frontend-design + ui-ux-pro-max VOR dem ersten Redesign-Beat (Design-System
   für die vier Spaces einmal erzeugen, persistieren), web-design-guidelines als Audit vor
   jedem Merge. Skills ersetzen kein Urteil — Forge-Prozess (Instrument-Verdikt) bleibt.

### Skill-Audit + erster Lauf [DONE 2026-07-29]

Alle drei Skills auditiert (Snyk-Warnung: 13 % kritische Flaws, 36 % Prompt-Injection in
Community-Skills) und in `.claude/skills/` installiert:
`ui-ux-pro-max` (Scripts: kein Netzwerk, kein exec, Schreibzugriff nur aufs eigene
Output-Dir; 1.7 MB CSV-Daten auf Injection gescannt — clean), `frontend-design`
(Anthropic, reiner Text, keine Scripts), `web-design-guidelines` (Vercel, reiner Text).

**Erster Design-System-Lauf und sein Verdikt — die DB ist ein Werkzeug, kein Urteil.**
Query: Kontrollraum/Glass/Minimalismus/spatial, dials variance 8 · motion 4 · density 7.
Brauchbar: Dark-first-Palette (#0F172A Grund, #1E293B Flächen, Akzent-Grün fürs "läuft"),
Motion-Budget 150–300 ms, Pre-Delivery-Checkliste (SVG statt Emoji, Focus-States,
prefers-reduced-motion). **VERWORFEN**: (a) Font-Empfehlung **Inter** — genau das, was
`frontend-design` als Template-Signal Nr. 1 verbietet und was jedes AI-Dashboard trägt;
(b) Muster "AI Personalization Landing" — wir bauen einen Kontrollraum, keine Landingpage;
(c) Style "Zero Interface" (voice-first) — falsche Produktklasse.
→ Typografie wird eigenständig entschieden (Kandidaten mit Charakter statt Default-Grotesk),
Layout aus der Instrument-Metapher (ADR: "cold glass, warm voice"), nicht aus dem
Karten-Raster. Die Anti-Slop-Regel steht damit als Filter VOR der Datenbank, nicht danach.

## Nächste Schritte (nach beiden Momus-Runden)

**Sofort frei:**

1. ~~**Teil A Fundament**~~ → **ERLEDIGT 2026-07-30, im Working Tree, nicht committed.**
   Die sechs Invarianten sind implementiert und getestet, die drei Regressions-Thermometer
   sind grün. Nächster Schritt ist ein Commit-Entscheid, kein Bau — siehe
   [`TYPE_GRAPH_IMPLEMENTATION_REPORT.md`](TYPE_GRAPH_IMPLEMENTATION_REPORT.md),
   Abschnitt "Offene Fragen".
2. **K0** — Telemetrie nach Mission Control (inkl. Badge + beide Deeplinks). Klein.
   (Teilweise angefasst von einer parallelen Lane — `MissionControl.tsx` existiert im
   Working Tree; nicht von diesem Lauf, nicht hier verifiziert.)
3. **K1** — Knowledge lesen, Projekt-Vault only, `documents=True` per Call,
   Dokumenten-Sub-Index mit Vault-Fingerprint, gemessene Freshness-Latenz.
   **Backend-Parsing-Hälfte ist gebaut** (s. Architektur §2); es fehlen Verdrahtung in
   `index.py`, Sub-Index mit Vault-Fingerprint, API und UI.
4. **Teil C** — Redesign der vier Spaces mit den installierten Skills; Anti-Slop-Filter VOR
   der Datenbank (keine Default-Grotesk, kein Karten-Raster, Instrument-Metapher).

**Gegated (nicht anfangen, bis die Vorbedingung schriftlich steht):**

- **K2 (Wiki-Schreiben)** → Mensch-PUT-Gate-Liste + `vault_rel`-Reject-Liste + If-Match,
  dann **Cerberus-Review vor Code**.
- **K5 (Agent-Maintenance)** → Fixpunkt-Prädikat benannt.
- **K6 (globaler Vault)** → schriftliche Antworten zu Multi-Root-Join, Write-Confinement,
  `.md`-Egress-Allow-Liste; eigene Momus- UND Cerberus-Runde.
- **Typ-Layer als DSS-Kanal / `type_blindspot`-Band** → Hub-Messung + Falschkanten-Suite grün.
  **Beide Vorbedingungen sind jetzt erfüllt** (Cap = 64 gemessen und publiziert;
  Falschkanten-Suite grün, inkl. der einen gefundenen und behobenen Verletzung bei
  `import *`). Das Band bleibt trotzdem gegated: `DEFAULT_LIMIT = 10` heißt, ein neuntes
  Band VERDRÄNGT Arbeit, und der Konsumenten-Nutzen ist ungemessen. Freigabe ist eine
  eigene Lane mit eigener Messung, kein Automatismus aus diesem Fundament.
- **A/B-Frontier-Eval** → Prä-Registrierung (fixes Budget, Zufallsarm, n-Untergrenze) steht.

**Offene Cerberus-Frage, unabhängig vom Wiki (aus B-C2c gefallen):** `.md` steht auf der
generischen Egress-Allow-Liste und wird VOR `default_deny` geprüft. Für Repo-Doku gewollt,
für persönliche Notizen ein Leck. Auch ohne K6 wert, angeschaut zu werden.
