---
title: Kairos
type: module
status: living
updated: 2026-09-05
covers: daedalus/kairos
---
# Kairos

`daedalus/kairos` ist der begrenzte Scheduler fuer die Contractor-Bench plus
alles, was ein Kandidat zum Leben braucht: isolierte Git-Worktrees, ein
Notizbuch vergangener Versuche, persistierte Beratungsentwuerfe und die
versiegelte Promotionsnaht. Im Bild des Masterplans sitzt Kairos unterhalb von
Ikarus (er entscheidet nie ueber Vertrauen und spricht nie mit dem Nutzer) und
oberhalb der Provider: er nimmt bereits freigegebene, risikoarme Arbeit
entgegen, verteilt sie auf eine begrenzte Zahl lokaler Worker und liefert einen
konsolidierten Bericht zurueck. Alles, was zur Senior-Crew gehoert, prallt an
ihm ab.

Der Name ist keine vierte Mythologie im Sinne von `AGENTS.md`, sondern ein
internes Modul: Kairos publiziert kein eigenes Produktkonzept, keinen eigenen
Event Store und keine eigene Promotionsautoritaet.

Gemessen 2026-09-05: 11 Python-Dateien, 3647 Zeilen. `worktree.py` ist mit 1561
Zeilen die groesste, `__init__.py` ist leer.

## Module

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [__init__.py](../../../daedalus/kairos/__init__.py) | Leer (0 Zeilen, gemessen 2026-09-05). Die Untermodule werden einzeln importiert; das Paket re-exportiert bewusst nichts, damit ein Import nicht die Baumlaeufe der schweren Module bezahlt. | -- |
| [scheduler.py](../../../daedalus/kairos/scheduler.py) | Der Scheduler selbst: Aufgaben annehmen oder zurueckweisen, in begrenzte Wellen planen, live ueber die Provider-Naht ausfuehren, nebenlaeufige Schreibarbeit gaten, Rollen zur Laufzeit konfigurieren. Kennt auch den Weg zu den geplanten Computer-Missionen. | `KairosScheduler`, `Assignment`, `spend_refused_result`, `FREE_LANES`, `DEFAULT_AVAILABILITY`, `SPEND_REFUSED_STATUS`, `SPEND_REFUSED_SKIPPED_STATUS` |
| [worktree.py](../../../daedalus/kairos/worktree.py) | Isolierte Git-Worktrees fuer Kandidatencode. Containment ist der Zweck: ein Aufraeumziel wird nur geloescht, wenn der Manager beweisen kann, dass es das ist, was er selbst allokiert hat. | `GitWorktreeManager`, `remove_tree_no_follow`, `WorktreeContainmentError`, `WorktreeRemovalRace` |
| [gated_writes.py](../../../daedalus/kairos/gated_writes.py) | Kompatibilitaets-Strangler fuer die versiegelte Promotionsnaht. Die historische Implementierung bleibt als nicht importierbare Paketressource byte-identisch erhalten, wird gegen ihre exakte Git-Blob-Identitaet geprueft und in diesen Namensraum ausgefuehrt; nur der oeffentliche Promotionsaufruf ist ersetzt. | `promote_candidates` |
| [archive.py](../../../daedalus/kairos/archive.py) | Was frueherer Versuche gelernt haben, dem naechsten angeboten: ein JSONL-Notizbuch plus eine zweistufige Inspirationsziehung (einige Elite-, einige Diversitaetseintraege). Die Form ist aus OpenEvolve adaptiert und im Modul-Docstring mit Upstream, Commit und Lizenz belegt. | `Attempt`, `record_attempt`, `load_attempts`, `sample_inspirations`, `digest_patch` |
| [decompose.py](../../../daedalus/kairos/decompose.py) | Zerlegt ein Ziel in eine begrenzte Liste bereichsgebundener Teilaufgaben. Primaer dynamisch ueber das lokale Ollama-Modell, deterministischer Fallback ist eine Aufteilung pro Pfad. Wirft nie und liefert immer mindestens eine Teilaufgabe. | `decompose` |
| [drafts.py](../../../daedalus/kairos/drafts.py) | Persistiert Beratungsentwuerfe -- die fehlende Haelfte der Kaskade. Ein Advisory-Lauf schreibt legitim nichts; sein Vorschlag lag frueher nur im Ergebnisobjekt und verfiel. Das Anwenden ist bewusst nicht automatisiert. | `save_draft`, `list_drafts`, `get_draft`, `delete_draft`, `set_status`, `handoff_payload`, `apply_payload`, `same_repo` |
| [control.py](../../../daedalus/kairos/control.py) | Duenne Lese- und CLI-Huelle ueber `daedalus.core`: Dashboard, Modellressourcen, Queue-Zeitachse, Watcher-Status, Squads, Quality-Gates, Review-Diff. Enthaelt keine eigene Logik. | `dashboard`, `ollama_models`, `queue_timeline`, `watcher_status`, `squads`, `quality_gates`, `review_diff`, `main_dashboard`, `main_models`, `main_squads`, `main_watcher`, `main_review_diff` |
| [orchestrate.py](../../../daedalus/kairos/orchestrate.py) | Bereitet eine Nachricht zu einer Aufgabe auf: Pfade aus dem Text erschliessen, Projekt aufloesen, Rolle routen, Token-Budget beschneiden, in die Bruecke einreihen. | `prepare_task` |
| [evolution.py](../../../daedalus/kairos/evolution.py) | Experimenteller Kandidatenlauf: N isolierte Branches erzeugen, ein konfiguriertes Testkommando ausfuehren, den besten behalten. Ausdruecklich *keine* autonome Code-Evolution und *keine* Promotionsgrenze. | `EvolutionaryOrchestrator`, `DEFAULT_EVAL_TIMEOUT_S` |
| [shadow_shell.py](../../../daedalus/kairos/shadow_shell.py) | Startet einen Adapter und laesst den Agenten in einem gegebenen Worktree laufen; ein Kandidat, der nichts geaendert hat oder mit Fehlercode endet, wird verworfen und sein Worktree aufgeraeumt. | `ShadowShellManager`, `CandidateBranch` |

Neben den Python-Dateien liegt `_gated_writes_legacy.py.src` im Paket: die
zurueckbehaltene, nicht importierbare Quelle der historischen Gating-Logik.
Sie ist an einen festen Git-Blob-Hash gebunden; weicht die Datei ab, weigert
sich der Import.

## Trust-Grenzen / Effekte

- **Worktree-Containment.** `cleanup_worktree` laeuft unbeaufsichtigt in einem
  `finally`-Block gegen ein Verzeichnis, in das Kandidatencode geschrieben hat.
  Das Argument ist damit angreiferbeeinflusste Daten, und die Loeschung ist
  eine fail-closed Entscheidung: was nicht als selbst allokiertes Worktree
  bewiesen werden kann, loest `WorktreeContainmentError` aus und es wird nichts
  entfernt. Der konkret abgewehrte Angriff ist der Ersatz des Verzeichnisses
  durch einen Symlink oder -- unter Windows -- durch eine Verzeichnis-Junction,
  die eine gewoehnliche Symlink-Pruefung nicht sieht. `remove_tree_no_follow`
  ist der Loeschpfad, der Reparse-Punkten nicht folgt.
- **Effekt-Grenze.** [worktree.py](../../../daedalus/kairos/worktree.py) oeffnet
  `begin_effect` an vier Stellen (gemessen 2026-09-05), jeweils mit einer
  `GuardDecision`, die benennt, was geprueft wurde. Der Import der Effekt-Grenze
  ist absichtlich lazy und die Bindung von `begin_effect` an einen lokalen
  Namen ist Pflicht, weil der Registry-Anker ein mechanischer Syntaxcheck auf
  genau diesen Aufruf ist.
- **Promotion.** `promote_candidates` ist die einzige oeffentliche
  Promotionsnaht dieses Pakets und faellt gegenueber der historischen
  Implementierung fail-closed aus: exakt ein Kandidat pro Aufruf, persistierte
  und authentifizierte Owner-Autoritaet vor jedem Effekt (Praeautorisierung),
  danach die zweite Authentifizierung *innerhalb* des Promotionslocks gegen
  eine frisch gelesene Ziel-Revision. Stimmt die Basis-Revision des Kandidaten
  nicht mit der autorisierten Live-Revision ueberein, wird verweigert; eine
  veraltete Regeneration braucht neue Evidenz und eine neue `OwnerApproval`.
  Jede Ausnahme auf diesem Pfad wird zu einer Verweigerung, nicht zu einem
  Teilerfolg.
- **Geld.** Eine Ziehung ueber die geleaste Obergrenze wird nicht als Ausnahme
  nach oben durchgereicht -- das hatte gemessen die bereits fertigen Ergebnisse
  derselben Welle mitgerissen -- sondern als positionsgebundenes Ergebnis mit
  `SPEND_REFUSED_STATUS` gemeldet. Die spaeteren Positionen derselben Welle
  bekommen den davon verschiedenen Status
  `SPEND_REFUSED_SKIPPED_STATUS`, damit eine Ablehnung nicht als drei gezaehlt
  wird. Nichts hier wiederholt den abgelehnten Aufruf.
- **Nebenlaeufiges Schreiben.** `gate_concurrent_writes` ist ausdruecklich nur
  Phase 1: jeder Schreib-Task laeuft nebenlaeufig in einem eigenen Worktree
  ueber die Attempt-Maschinerie des [Spine](spine.md); das Landen im Ziel ist
  nicht Teil dieses Aufrufs.
- **Nur lesend.** `control.py` liest ausschliesslich ueber
  [core](daedalus-package-root.md); `decompose` macht beim Import keinerlei
  Netz-I/O und faellt bei unerreichbarem lokalem Server deterministisch zurueck;
  `archive` und `drafts` schreiben nur in ihre eigenen Ablagen unter `runs/`.
- **Kein Auto-Merge.** `EvolutionaryOrchestrator` behaelt einen bestandenen
  Kandidaten, aber ein vertrauenswuerdiger Verifier muss ihn weiterhin
  ansehen, bevor er in den primaeren Workspace kann.

## Tests

Gemessen 2026-09-05 ueber eine Importsuche in `tests/`; Auswahl:

- Worktree und Containment: [test_worktree.py](../../../tests/test_worktree.py),
  [test_worktree_properties.py](../../../tests/test_worktree_properties.py),
  [test_worktree_central_start.py](../../../tests/test_worktree_central_start.py),
  [test_spine_attempt_containment.py](../../../tests/test_spine_attempt_containment.py)
- Versiegelte Promotion:
  [tests/kernel/test_sealed_promotion.py](../../../tests/kernel/test_sealed_promotion.py),
  [tests/kernel/test_live_promotion_seam.py](../../../tests/kernel/test_live_promotion_seam.py),
  [tests/kernel/test_live_promotion_legacy_retirement.py](../../../tests/kernel/test_live_promotion_legacy_retirement.py),
  [tests/kernel/test_persisted_promotion_authorization.py](../../../tests/kernel/test_persisted_promotion_authorization.py),
  [tests/kernel/test_promotion_execution_review.py](../../../tests/kernel/test_promotion_execution_review.py),
  [tests/kernel/test_promotion_material_review.py](../../../tests/kernel/test_promotion_material_review.py),
  [tests/kernel/test_approval_consumption_review.py](../../../tests/kernel/test_approval_consumption_review.py),
  [test_promotion_trust_root_single_caller.py](../../../tests/test_promotion_trust_root_single_caller.py)
- Scheduler und Wellen: [test_parallel_dispatch.py](../../../tests/test_parallel_dispatch.py),
  [test_wave_spend_reservation.py](../../../tests/test_wave_spend_reservation.py),
  [test_wave_spend_reservation_concurrency.py](../../../tests/test_wave_spend_reservation_concurrency.py),
  [test_loop_spend_refused.py](../../../tests/test_loop_spend_refused.py),
  [test_dynamic.py](../../../tests/test_dynamic.py)
- Archiv, Entwuerfe, Evolution: [test_kairos_archive.py](../../../tests/test_kairos_archive.py),
  [test_kairos_evolution.py](../../../tests/test_kairos_evolution.py),
  [test_evolution_baseline.py](../../../tests/test_evolution_baseline.py),
  [test_drafts.py](../../../tests/test_drafts.py)
- Rollen und Bruecke: [test_agents_registry.py](../../../tests/test_agents_registry.py),
  [test_agent_env.py](../../../tests/test_agent_env.py),
  [test_comms.py](../../../tests/test_comms.py),
  [test_bridge_restart.py](../../../tests/test_bridge_restart.py)
- Computer-Missionen: [test_ikarus_computer_history.py](../../../tests/test_ikarus_computer_history.py)

## Verwandt

- [Daedalus-Paketwurzel](daedalus-package-root.md) -- `build_exec` ist der
  Aufrufer des Schedulers, `offload` der Runner hinter jeder Position.
- [Spine](spine.md) -- Attempt, Ledger, Effekt-Grenze, Kill-Switch.
- [Kernel](kernel.md) -- `authorize_persisted_promotion`, `OwnerApproval`,
  `EvidencePacket`; die Promotionsautoritaet liegt dort, nicht hier.
- [Ariadne](ariadne.md) -- die kontrollierte Evolutionsschicht; das
  Kandidaten-Archiv hier ist Werkzeug, nicht Kampagnenautoritaet.
- [Adapters](adapters.md) -- die Agent-Adapter, die `ShadowShellManager` startet.
- [Orchestration Ikarus](orchestration-ikarus.md) -- die Computer-Missionen
  hinter `schedule_computer` und `dispatch_due_computer`.
- [Orchestration Genesis](orchestration-genesis.md) -- der zweite Konsument
  der isolierten Workspaces und derselben Lease-Mechanik.
- [Providers](providers.md) und [Runtimes Providers](runtimes-providers.md) --
  die Naht, ueber die eine Position tatsaechlich laeuft.
- [Gates Repository](gates-repository.md) -- die Schreibklassifikation, die
  die Wellen bewertet.
- [Graph-Delta als Fitness](../graph-delta-as-fitness.md) und
  [Agenten halten keinen Zustand](../decisions/agents-hold-no-state.md).
- [Wiki-Index](../index.md).

## Ungeklaert

- **Ungeklaert:** wie viel von `evolution.py` und `shadow_shell.py` heute noch
  live aufgerufen wird. Beide tragen kein `begin_effect`, importieren aber
  `GitWorktreeManager` und die Adapter, also laufen ihre Effekte ueber die
  Grenzen der aufgerufenen Module. Ein Produktionsaufrufer war 2026-09-05 nicht
  erkennbar; die Tests sind die einzigen sicher belegten Nutzer.
- **Ungeklaert:** `apply_payload` in `drafts.py` ist im Docstring als
  veralteter Alias fuer `handoff_payload` markiert. Ob noch Aufrufer
  existieren, wurde nicht gemessen.
- **Ungeklaert:** ob die Registry-Zeile fuer den historischen Aufrufanker
  `authorize_promotion` inzwischen verschoben wurde -- der Code beschreibt die
  lokale Namensbindung ausdruecklich als temporaeren Adapter bis zu einem
  eigenen Work Packet.
- **Ungeklaert:** `control.py` und `orchestrate.py` tragen keinen
  Modul-Docstring; ihre Rolle ist aus den Importen abgeleitet.
