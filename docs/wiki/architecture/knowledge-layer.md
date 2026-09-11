---
title: Knowledge layer
type: spec
status: partial
updated: 2026-09-05
---

# Knowledge layer

Dieses Wiki. Obsidian-Format mit Absicht: Obsidian selbst ist geschlossen und
nicht einbettbar, aber einfaches Markdown plus Wikilinks plus
YAML-Frontmatter ist der De-facto-Standard, also öffnet derselbe Ordner in
Obsidian und funktioniert weiter. Es ist die Knowledge-Ebene des vierteiligen
Project Twin (Plan §5) -- und ausdrücklich **keine Autorität über Quelle oder
Evidenz**: was hier steht, ist Dokumentation, kein Beweis.

Vaults verschachteln: ein globaler Vault, den der Betreiber besitzt, und einer
je Projekt.

## Lesen

- [daedalus/wiki/vault.py](../../../daedalus/wiki/vault.py) -- Vaults finden,
  Seiten lesen, Frontmatter parsen, Baum bilden. Symbole: `Vault`, `Page`,
  `vault_rel`, `VaultPathError`, `parse_frontmatter`, `read_page`,
  `discover_pages`, `discover_vaults`, `page_tree`, `MAX_PAGES`,
  `MAX_PAGE_BYTES`, `RESERVED_TOP_LEVEL`.
- [daedalus/wiki/links.py](../../../daedalus/wiki/links.py) -- das Nervensystem:
  Wikilinks, Backlinks, unverlinkte Erwähnungen und der **lokale** Graph.
  Symbole: `WikiLink`, `extract_wikilinks`, `LinkIndex`, `build_index`,
  `backlinks`, `unlinked_mentions`, `local_graph`.

Lokaler Graph auf Tiefe 1, nie der globale Knäuel: die Recherche dahinter kam
überall zum selben Urteil -- eine globale Graphansicht ist "hübsch, aber
nutzlos", sobald ein Vault wächst, während die n-Hop-Nachbarschaft der Seite,
auf der man steht, eine Frage beantwortet, die jemand tatsächlich hat. Der
globale Graph wird deshalb gar nicht erst gebaut.

Die Linkformen sind mehr als Text: `[[Note]]`, `[[Note#Heading]]`,
`[[Note|Anzeigetext]]`, `![[Note]]` als Einbettung statt Link, und
`[[code:pfad/datei.py]]` beziehungsweise `[[code:pfad#symbol]]` als echte
Dokument-zu-Code-Kante.

## Der Pfadvalidator

`vault_rel` ist der Grund, warum die Schreibseite noch blockiert ist. Ein
Momus-Review stufte sie als CRITICAL ein: jeder bestehende Pfadparameter der
HTTP-API ist eine ID gegen `^[A-Za-z0-9._-]{1,160}$`, in der `/` verboten ist,
Traversal also konstruktionsbedingt unmöglich. Ein Wiki-Seitenpfad **muss** `/`
enthalten -- ein `PUT` darauf wäre die erste beliebige Schreib-Traversal-Fläche
dieser API. Der Validator wurde deshalb vor jedem Endpunkt geschrieben und ist
fail-closed: jede Ablehnung gibt `None` plus Grund zurück, es gibt keinen
Best-Effort-Pfad, der eine verdächtige Schreibweise in etwas Plausibles
auflöst. Abgelehnt werden absolute Pfade und Laufwerksbuchstaben, jedes
`..`-Segment **vor** der Auflösung, ein aufgelöster Pfad außerhalb des Vaults,
Symlinks irgendwo auf der Kette, `:` in einem Segment (NTFS Alternate Data
Streams), reservierte Windows-Gerätenamen, abschließende Punkte und Leerzeichen
sowie jede Endung außer `.md`.

**Stand 2026-09-05: die Schreibseite existiert weiter nicht.** Der Docstring
von `vault.py` sagt es selbst -- das Modul entdeckt, parst und validiert, es
schreibt nie; der Schreibpfad bräuchte eine eigene Gate-Liste plus
Cerberus-Review. `kairos.gated_writes` ist eine Provider-Attempt-Pipeline, kein
Schreibzaun; ein menschlicher Editor-Save würde still durchfallen.

## Dazugekommen: das Wiki misst und prüft sich selbst

Seit der ersten Fassung dieser Seite ist das Paket über Lesen hinausgewachsen.
Details stehen auf [Wiki](wiki.md); für diese Ebene zählen drei Dinge:

- [verify.py](../../../daedalus/wiki/verify.py) ist die Evidenzgrenze des
  Wikis. Ein Modell darf Dokumentation schreiben; ob sie über das Repository
  wahr ist, entscheidet dieses Modul, indem es in den Baum schaut -- dieselbe
  Grenze wie überall sonst in Daedalus. Es kennt fünf Befunde, darunter
  `unknown_symbol` (ein Bezeichner in Backticks, der nirgends im Baum
  vorkommt), `broken_link`, `unsourced_claim`, `thin_concept` und
  `uncovered_module`. Wichtig für die Ehrlichkeit des Instruments: die geprüfte
  Menge darf nicht für sich selbst bürgen -- das Wiki unter Prüfung und
  `runs/` sind aus dem Vokabular ausgeschlossen, sonst würde ein erfundener
  Name allein dadurch gültig, dass er aufgeschrieben wurde.
- [metrics.py](../../../daedalus/wiki/metrics.py) misst die *strukturelle*
  Qualität: den Anteil der Dokument-zu-Quelle-Kanten, die einen k-Core des
  vierteiligen Graphen überleben. Eine Seite kann gut geschrieben, aktuell und
  wahr sein und dem Projekt trotzdem nichts bringen, wenn sie mit nichts
  verbunden ist.
- [qml_index.py](../../../daedalus/wiki/qml_index.py) erweitert das Vokabular
  um die Namen, die eine Qt/QML-Oberfläche außerhalb von Python definiert --
  ohne das hält der Verifier eine ganze reale Namensfläche für erfunden.

Nur zwei Stellen im Paket schreiben überhaupt: `plan.py` legt einen Plan als
JSON ab und `verify.py` einen Bericht, beides nur auf ausdrücklichen
Ausgabepfad. Der Vault selbst bleibt read-only.

## Verwandt

- [Wiki](wiki.md) -- das Paket `daedalus/wiki` im Detail.
- [Structcore](structcore.md) -- `markdown.py` liefert Dokumentknoten,
  Dokumentlinks und die aufgelöste Wikilink-Schicht in den Index.
- [Type graph](type-graph.md), [Data layer](data-layer.md),
  [Observation layer](observation-layer.md) -- die übrigen Ebenen.
- [Twin](twin.md), [Twin-Extraktoren](twin-extractors.md).
- [Interfaces — HTTP](interfaces-http.md) -- die API, deren ID-Muster den
  Validator nötig gemacht hat.
- [Forest v2 — s11 Fusion](../experiments/forest-v2-s11-fusion.md) und
  [Forest v2 — Tensor-Embeddings](../experiments/forest-v2-tensor-embeddings.md)
  -- Experimente, in denen `knowledge` eine eigene indizierte Ebene ist.
- [Feature-Backlog](../feature-backlog.md), [Wiki-Index](../index.md).
