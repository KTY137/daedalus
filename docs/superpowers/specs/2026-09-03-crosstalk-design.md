# Crosstalk: parallele Claude-Sessions reden über GitHub Discussions

Datum: 2026-09-03
Owner: repository owner (KTY)
Status: implemented 2026-09-03; **live path UNVERIFIED** — no `gh` login on this
machine, so "it really posts to GitHub" has not been observed even once. The
25 tests in `tests/test_crosstalk.py` prove the contract against a fake
transport, which is not the same claim.
Iron Plan: ALIGNED — Gate 1, keine Invariante geändert
Betroffener Entrypoint: `daedalus.hooks` (bestehend), `daedalus.hooks.crosstalk` (neu, CLI)

## Problem

In diesem Checkout laufen mehrere Claude-Code-Sessions gleichzeitig. Sie wissen
nichts voneinander. Der belegte Schaden steht im Session-Gedächtnis dieses
Repos: Sessions committen und wechseln Branches im Primär-Checkout mitten in der
Arbeit einer anderen; `git add -A` einer Session hat Arbeit einer anderen
mitgenommen; eine Session hat eine Datei aufgeräumt, die sie nicht angelegt
hatte.

Der Owner will die Sessions sichtbar miteinander reden lassen — und selbst
mitlesen und antworten können, aus dem Browser. Deshalb GitHub Discussions und
nicht ein lokaler Bus: die GitHub-Oberfläche ist der Punkt, nicht der Speicher.

## Was das nicht ist

Kein zweiter Hook-Dispatcher. Kein Ersatz für den Ledger. Keine
Orchestrierungs-Ebene: Discussions sind eine *Anzeige*, kein Workflow-Zustand
(Plan §13 verbietet Chat als Orchestrierungszustand — dieser Kanal trifft keine
Entscheidungen und hält keinen Zustand, von dem Ausführung abhängt).

## Entscheidungen (vom Owner bestätigt, 2026-09-03)

| Frage | Entscheidung |
|---|---|
| Zweck | GitHub-UI ist der Punkt — Owner liest und antwortet dort |
| Trigger | Anmelden bei Sessionstart, Abmelden bei Sessionende. Dazwischen Stille. |
| Enforcement | injizieren, **nie** blockieren |
| Thread-Schnitt | eine Discussion pro Branch/Packet **plus** ein globaler `crew-channel` |

## Architektur

### Drei Oberflächen, ein Dispatcher

Alles läuft durch den bestehenden Entrypoint
`python -m daedalus.hooks <event>` ([daedalus/hooks/__main__.py](../../../daedalus/hooks/__main__.py)).
Es entsteht **kein** zweites Hook-Skript — das wäre die parallele Control-Plane,
die [AGENTS.md](../../../AGENTS.md) als release-blocking führt.

| Oberfläche | Event | Aufgabe |
|---|---|---|
| `events.session_start` (erweitert) | `SessionStart` | ANMELDUNG posten; beide Threads zurücklesen und injizieren |
| `events.session_end` (neu) | `SessionEnd` | ERGEBNIS posten |
| `events.user_prompt` (erweitert) | `UserPromptSubmit` | gecachtes Nachlesen neuer Kommentare |
| `daedalus.hooks.crosstalk say "…"` | CLI | eine vom Modell geschriebene Zeile posten |

Neue Logik liegt in **einem** Modul `daedalus/hooks/crosstalk.py`, nicht in
einem neuen Paket. Die Handler in `events.py` rufen es auf; sie enthalten keine
Transport- oder Redaktionslogik.

### Warum der CLI-Teil nicht wegzukürzen ist

Ein Hook ist ein Python-Skript ohne Modell. Bei `SessionStart` hat die Session
den Prompt des Owners noch nicht gesehen — sie *kann* ihre Absicht nicht kennen.
Die Hooks posten deshalb ausschließlich mechanische Fakten. Absicht, Antworten
an andere Sessions und Antworten an den Owner sind vom Modell verfasst und
werden explizit über `crosstalk say` abgesetzt.

Ohne diesen dritten Teil entsteht ein Anwesenheitsprotokoll, keine Diskussion.
Das ist die ehrliche Form der Anforderung „zwei Hooks": zwei Hook-Events tragen
die Mechanik, der CLI trägt die Sprache.

### Warum `UserPromptSubmit` mitliest

Antworten, die der Owner im Browser schreibt, erreichen eine *laufende* Session
sonst erst bei ihrem nächsten Start. Der bestehende Turn-Handler liest deshalb
mit — aber gecacht: Re-Fetch höchstens alle `POLL_TTL_S` (Default 300), sonst
aus dem Cache. Ein GitHub-Call statt einem pro Turn. Kein neuer Hook, kein
zusätzlicher Eintrag in `settings.json`.

Der Cache liegt im vorhandenen Session-State (`runs/hooks/state-<sid>.json`),
**nicht** in einer eigenen Datei — siehe Nachtrag am Ende.

## Threads

- Globaler Thread: Titel `crew-channel`.
- Pro Branch: Titel = Branchname, z. B. `packet/g1-map-01`, on-demand angelegt.
- Kategorie: eine Discussion-Kategorie des Repos, konfiguriert über
  `DAEDALUS_CROSSTALK_CATEGORY` (Default `General`).
- Zuordnung Branch → Discussion-ID: eine einzige Repo-Abfrage pro Prozess
  liefert Repository-ID, Sichtbarkeit, Kategorien und die letzten 50
  Discussions auf einmal; ein Hook ist ein Prozess. Ein Cache auf Platte wäre
  Zustand ohne Nutzen — siehe Nachtrag am Ende.

Ein detached HEAD bekommt keinen eigenen Thread; er postet nur in
`crew-channel`, mit dem short sha statt eines Branchnamens.

### Nachrichtenformat

```
ANMELDUNG · session a3f2 · packet/g1-map-01 @b9321abd
dirty: daedalus/mapping/reach.py, tests/test_mapping_reach_facades.py
2026-09-03T09:05:11+02:00
```

```
ERGEBNIS · session a3f2 · packet/g1-map-01 @b9321abd -> @e7c40021
commits: 2 (refactor(mapping): anchor pkg.__init__ resolution | test(mapping): …)
geändert: 3 Dateien · Dauer: 41 min
2026-09-03T09:46:02+02:00
```

`crosstalk say` postet eine freie Zeile mit demselben Kopf
(`session a3f2 · packet/g1-map-01`).

## Egress-Kontrakt

Der Entrypoint `daedalus.hooks` deklariert in
[effect_boundary.py:1738](../../../daedalus/spine/effect_boundary.py#L1738)
bereits `NETWORK_EGRESS` — begründet allerdings mit *„probes Serena's loopback
dashboard port"*. Mechanisch ist der Effekt damit gedeckt; seine **Bedeutung**
weitet sich von Loopback auf `github.com`. Die `notes` des Specs werden
entsprechend korrigiert. Eine Registry, deren Begründung nicht mehr stimmt, ist
schlimmer als gar keine.

Es ist **kein** Amendment: keine Invariante ändert sich, kein neuer Effekt-Typ,
kein neuer effektvoller Entrypoint außerhalb der kanonischen Kontrakte.

### Was die Maschine verlässt — abschließende Liste

Erlaubt:

- kurze Session-ID (erste 4 Zeichen der Harness-UUID)
- Branchname
- HEAD, short sha
- repo-**relative** Pfade geänderter Dateien
- Commit-Betreffs (subject line), erzeugt in dieser Session
- Zeilen, die das Modell explizit über `crosstalk say` verfasst hat

Nie:

- Prompt-Text des Owners, weder wörtlich noch vom Hook zusammengefasst
- Dateiinhalte, Diffs, Testausgaben
- absolute Pfade, Benutzernamen, Hostnamen
- irgendetwas aus `.env`, `.agentenv/`, oder Pfaden, die auf das
  Secrets-Muster passen

Pfade, die auf das Secrets-Muster passen, werden **gezählt und als solche
ausgewiesen**, nicht benannt und nicht still weggelassen — nach der stehenden
Hausregel „nie still weglassen" in [AGENT_PROTOCOL.md](../../../.claude/AGENT_PROTOCOL.md).

Die Redaktion ist eine reine Funktion über dem Nachrichtenobjekt und wird
separat getestet; sie sitzt nicht verstreut in den Handlern.

## Sicherungen

**Default aus.** Nur `DAEDALUS_CROSSTALK=on` schaltet scharf. Begründung: fünf
parallele Sessions, die ab dem nächsten Sessionstart unangekündigt ins Internet
publizieren, sind genau die Überraschung, die ein Egress-Schalter verhindern
soll.

**Public-Repo-Sperre.** Ist das Repo öffentlich, verweigert der Poster, außer
`DAEDALUS_CROSSTALK_PUBLIC=1`. Die Sichtbarkeit von `KTY137/daedalus` ist zum
Zeitpunkt dieser Spec **nicht gemessen** (kein `gh`-Login) — die Sperre steht
statt einer Annahme. Die Sichtbarkeit kommt aus derselben Repo-Abfrage und gilt
für die Lebensdauer des Prozesses.

**Fail-open, ausnahmslos.** Timeout, Rate-Limit, fehlendes Login, fehlendes
`gh`, deaktivierte Discussions → eine sichtbare Notiz im injizierten Text
(`crosstalk: Thread nicht erreichbar (<Grund>)`), eine Ledger-Zeile, Exit 0.
Kein Tool-Call wird je verweigert. Das ist bewusst *nicht* fail-closed: dies ist
eine Anzeigefunktion, keine Vertrauensgrenze. Fail-closed hieße hier, dass ein
GitHub-Ausfall den Checkout unbenutzbar macht.

**Kein Token in unserem Code.** Transport ist `gh api graphql` als Subprozess.
`gh` hält die Credentials; dieser Code liest, speichert und loggt kein Secret.
Deshalb braucht der Entrypoint kein `Effect.SECRETS`.

**Zeitbudget.** Jeder GitHub-Aufruf läuft über den vorhandenen
`with_deadline(...)`: 6 s bei `SessionStart` (Hook-Budget 15 s), 3 s im
Turn-Handler (Hook-Budget 10 s). Überschreitung ist ein Fail-open-Fall.

## Die Compact-Falle

Der `SessionStart`-Matcher in `.claude/settings.json` ist
`startup|resume|clear|compact|fork`. **`compact` feuert `SessionStart`.** Ohne
Dedupe meldet sich eine lange Session bei jeder Kompaktierung neu an und müllt
den Thread zu.

Dedupe: `session_start` postet die ANMELDUNG nur, wenn im Session-State unter
`sid` noch kein `crosstalk.announced` steht. `payload["source"]` wird zusätzlich
in der Ledger-Zeile festgehalten, damit sichtbar bleibt, welcher Start-Grund
unterdrückt wurde. Das Zurücklesen und Injizieren passiert bei **jedem** Start,
auch nach `compact` — nach einer Kompaktierung ist der Kontext ja gerade weg.

## Fehlersemantik

| Fall | Verhalten |
|---|---|
| `DAEDALUS_CROSSTALK` nicht `on` | kein Netz-Call, keine Notiz, keine Ledger-Zeile |
| `gh` fehlt oder nicht eingeloggt | Notiz, Ledger-Zeile, weiter |
| Repo öffentlich ohne Opt-in | Notiz mit genanntem Grund, kein Post, weiter |
| Discussions deaktiviert | Notiz, Ledger-Zeile, kein Retry in dieser Session |
| Rate-Limit / Timeout | Notiz, Ledger-Zeile, Cache-Inhalt wird trotzdem injiziert |
| Thread existiert nicht | wird angelegt; scheitert das, ist es ein Notiz-Fall |

Kein Fall führt zu einem Except nach oben, keiner zu einem Exit ≠ 0, keiner zu
einer Tool-Verweigerung.

## Testplan und Thermometer

`tests/test_crosstalk.py`, gegen einen Fake-Transport (kein Netz im Test):

1. **Redaktion.** Ein Nachrichtenobjekt, das Prompt-Text, einen absoluten Pfad
   und `.agentenv/tool-allowances.json` enthält, erzeugt einen Body, in dem
   keines davon vorkommt — und in dem die unterdrückte Datei *gezählt*
   auftaucht. Der Test behauptet zusätzlich, dass die Eingabe die verbotenen
   Strings wirklich enthielt (eine Fixture, die inert ist, ist schlimmer als
   kein Test — stehende Hausregel).
2. **Fail-open.** Transport wirft `TimeoutError` / `FileNotFoundError` /
   `CalledProcessError` → Handler liefert `HookResult` mit Notiz, kein Except.
3. **Dedupe.** Zweiter `session_start` mit `source="compact"` und gleicher `sid`
   postet nicht, injiziert aber.
4. **Default aus.** Ohne `DAEDALUS_CROSSTALK=on` findet kein Transportaufruf
   statt (der Fake zählt Aufrufe: erwartet 0).
5. **Public-Sperre.** Sichtbarkeit `PUBLIC` ohne Opt-in → kein Post, Notiz nennt
   den Grund.
6. **Turn-Cache.** Zwei `user_prompt`-Aufrufe innerhalb der TTL erzeugen genau
   einen Transportaufruf.

**BEFORE:** 0 Tests zu crosstalk.
**EXPECTED AFTER:** die sechs oben grün, plus `tests/test_hooks_v2.py`,
`tests/test_hooks_precompact.py`, `tests/test_hooks_review_20260825.py`
unverändert grün.

**UNVERIFIED bis auf Weiteres:** dass live wirklich gepostet wird. Das verlangt
`gh auth login` und aktivierte Discussions auf `KTY137/daedalus`, beides eine
Owner-Handlung. Bis dahin ist der Live-Pfad ungeprüft und wird genau so
berichtet — nicht als „funktioniert".

## Betroffene Dateien

| Datei | Änderung |
|---|---|
| `daedalus/hooks/crosstalk.py` | neu — Transport, Redaktion, Formatierung, Thread-Auflösung |
| `daedalus/hooks/events.py` | `session_start` erweitern, `session_end` ergänzen, `user_prompt` erweitern |
| `daedalus/hooks/__main__.py` | `session_end` in `HANDLERS` registrieren |
| `.claude/settings.json` | ein `SessionEnd`-Eintrag |
| `daedalus/spine/effect_boundary.py` | `notes` von `daedalus.hooks` korrigieren; CLI-Entrypoint registrieren |
| `tests/test_crosstalk.py` | neu |

Branch- und Baumfakten kommen aus dem vorhandenen `_tree.py` und `_common.git`,
nicht neu abgeleitet.

## Arbeitsweise im geteilten Checkout

Andere Sessions schreiben parallel in diesen Checkout. Es wird ausschließlich
mit explizit genannten Pfaden gestaged, nie `git add -A`; `daedalus/mapping/reach.py`
und `tests/test_mapping_reach_facades.py` gehören einer anderen Session und
werden nicht angefasst.

## Rollback

`DAEDALUS_CROSSTALK` nicht setzen — der Pfad ist dann tot. Vollständig:
`SessionEnd`-Eintrag aus `.claude/settings.json` entfernen, `crosstalk.py` und
den Test löschen, die drei Handler-Erweiterungen zurücknehmen, `notes` in
`effect_boundary.py` zurücksetzen. Keine Migration; der einzige persistente
Zustand sind vier Schlüssel im vorhandenen Session-State, die mit ihrer Datei
verschwinden.

## Bewusst nicht in diesem Design

- Kein Blockieren bei Kollisionen (Owner-Entscheidung: injizieren, nie
  blockieren). Die Kollisionserkennung selbst kann später auf demselben
  Thread-Inhalt aufsetzen, ohne diesen Entwurf zu ändern.
- Kein Posten pro Turn (Rate-Limit, Kosten, Unlesbarkeit).
- Kein lokaler Spiegel des Threads als Wahrheit — GitHub ist hier die Anzeige,
  der Poll-Cache ist reiner Cache und darf jederzeit gelöscht werden.

## Nachtrag 2026-09-03 — was die Umsetzung anders gemacht hat

Diese Spec ist vor der Implementierung geschrieben worden. Vier Dinge sind
anders geworden; sie stehen hier, statt dass die Spec sich stillschweigend
selbst korrigiert.

**1. Kein `runs/crosstalk/`.** Die Spec sah `threads.json` und `cache.json`
vor. Beide sind überflüssig: eine einzige GraphQL-Abfrage liefert
Repository-ID, Sichtbarkeit, Kategorien und die letzten 50 Discussions
gemeinsam, und ein Hook ist ein einzelner Prozess — es gibt nichts zwischen
zwei Abfragen zu cachen. Der Poll-Cache lebt in `runs/hooks/state-<sid>.json`,
das bereits gesperrt und atomar geschrieben wird. Ein zweiter Zustandsspeicher
neben einem vorhandenen wäre genau das, was `AGENTS.md` „prefer wiring over a
new subsystem" verbietet.

**2. Die Redaktion greift nur auf pfadförmige Token.** Die Spec sagte
„Pfade, die auf das Secrets-Muster passen, werden gezählt". Umgesetzt wurde
zunächst *jedes* Token — und ein Commit-Betreff „fix(auth): rotate the token"
ließ damit die ganze ERGEBNIS-Zeile verschwinden, mit der Begründung
„secret-verdächtiger Pfad", der nie ein Pfad war. `PATH_SHAPED` ist das Gatter,
das Prosa in Ruhe lässt; eine echte Pfad**liste** geht weiter ungefiltert durch
`redact_paths`.

**3. `gh_graphql` nimmt einen `argv_prefix`.** Ohne ihn ist die einzige real
laufende Naht — Argv-Aufbau, `-f`/`-F`-Wahl, Exit-Code-Abbildung, JSON-Parsing
— nicht testbar, weil jeder Test die Funktion als Ganzes fälscht. Default
bleibt `("gh",)`; die Tests fahren gegen ein Stub-Executable.

**4. Ein `status`-Verb.** Der Kanal ist per Default aus und hat sechs
verschiedene Arten zu schweigen. Ohne `crosstalk status` ist „ausgeschaltet"
von „kein gh-Login" von „Discussions nicht aktiviert" nur durch Starten einer
Session zu unterscheiden — ein schlechtes Instrument für etwas, das man gerade
einrichtet.
