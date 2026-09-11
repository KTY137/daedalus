---
title: Desktop-Interface
type: module
status: living
updated: 2026-09-05
covers: daedalus/interfaces/desktop
---
# Desktop-Interface

`daedalus/interfaces/desktop` ist die Desktop-Hälfte der Ikarus-Oberfläche: der
gepackte Sidecar, der die Tauri-Anwendung startet, die Desktop-Routen auf der
bestehenden authentifizierten HTTP-Fassade, die Einstellungspersistenz und die
read-only Projektionen, die die Oberfläche rendert. Es ist ein *Interface*, kein
zweiter Kernel: Policy, Leases, Ledger und Kill-Switch kommen aus
[Spine](spine.md) und [Kernel-Policy](kernel-policy.md); dieses Paket besitzt
genau drei registrierte Effekt-Türen und sonst nichts.

Die Struktur ist ein laufender Strangler: `daedalus.desktop_runtime` bleibt die
stabile Kompatibilitätsfassade, die Implementierungsmodule hier importieren
diese Fassade bewusst nie zurück, und `__init__.py` reicht die Alt-Namen nur
faul durch, ohne monkeypatch-empfindliche Attribute zu cachen.

Gemessen 2026-09-05: 8 Python-Module, 3942 Zeilen; `effects.py` (1477) und
`sidecar.py` (1169) tragen zusammen zwei Drittel davon.

## Module

| Datei | Aufgabe | Wichtige Symbole |
| --- | --- | --- |
| [__init__.py](../../../daedalus/interfaces/desktop/__init__.py) | Kompatibilitätsoberfläche über der kanonischen Runtime-Fassade. Ein `__getattr__` löst eine feste Menge von Alt-Exporten pro Zugriff neu auf, statt sie zu cachen. | `__getattr__`, `__dir__` |
| [configuration.py](../../../daedalus/interfaces/desktop/configuration.py) | Reine Konfigurationsvorgaben und Whitelist-Normalisierung. Besitzt keine Persistenz, keine Umgebungsmutation, keine Prozessverwaltung und keinen Effekt-Einstiegspunkt. Passwörter, Tokens, Schlüsselbytes und Kommandos sind ungültige Eingaben, nicht redigierte. | `defaults`, `normalize_config`, `port`, `loopback_endpoint`, `ide_endpoint`, `numeric_host` |
| [effects.py](../../../daedalus/interfaces/desktop/effects.py) | Die festgeschriebene Effekt-Eigentümerschaft: exakte Publikation der Einstellungen und explizite Beobachtung/Adoption eines lokalen Ollama auf Loopback. Trägt die typisierte Fehlerfamilie, die die HTTP-Schicht in Statuscodes übersetzt. | `DesktopEffectOwner`, `DesktopEffectRefused`, `DesktopValidationError`, `DesktopPolicyDenied`, `DesktopFeatureUnavailable`, `DesktopEffectStopped`, `DesktopEffectUnavailable`, `DesktopOllamaUnreachable`, `DesktopSettingsDurabilityIndeterminate`, `DesktopSettingsCommittedUnrecorded`, `DesktopSettingsCommittedFollowupError` |
| [http.py](../../../daedalus/interfaces/desktop/http.py) | Komposition der Desktop-Routen auf der vorhandenen Fassade. Erzeugt eine Handler-Unterklasse statt eines zweiten HTTP- oder Control-Servers. | `install_web_integration` |
| [lifecycle.py](../../../daedalus/interfaces/desktop/lifecycle.py) | Start und Ende ohne Prozessbesitz: `bootstrap` startet nur, was die Manager-Konfiguration bereits zugelassen hat, `close` beendet die Session. | `bootstrap`, `close` |
| [projection.py](../../../daedalus/interfaces/desktop/projection.py) | Read-only Statusprojektionen über den bestehenden Managerzustand. Genau eine abgekoppelte Konfigurationsgeneration speist jeden verschachtelten Projektor; kein Helfer liest `manager.config` während eines Snapshots erneut. | `snapshot`, `budget_status`, `ide_status`, `bridge_status_is_managed` |
| [settings.py](../../../daedalus/interfaces/desktop/settings.py) | Persistenz, Zustimmung und Umgebungsprojektion der Einstellungen. Jede autoritätstragende Abhängigkeit wird pro Aufruf über Ports hereingereicht, die die Fassade liefert. | `load`, `prepare_settings`, `environment_projection`, `read_budget_environment` |
| [sidecar.py](../../../daedalus/interfaces/desktop/sidecar.py) | Kanonischer Eigentümer des Bootstraps im gepackten Sidecar: Laufzeitverzeichnisse anlegen, den Selbst-Projekt-Datensatz säen und genau einmal eine unberührte Kill-Switch-Control-Root scharfschalten. | `main`, `bundled_root`, `prepare_runtime`, `initialize_desktop_switch_once`, `DesktopSwitchInitializationRefused`, `DesktopSwitchRevocationUnproven` |

## Trust-Grenzen / Effekte

Drei registrierte Einstiegspunkte, sonst nichts:

| Registry-Zeile | Aufrufstelle | Was sie darf |
| --- | --- | --- |
| `cli.desktop_sidecar` | [sidecar.py](../../../daedalus/interfaces/desktop/sidecar.py):1112 in `main` | den beschreibbaren Laufzeitzustand des gepackten Sidecars anlegen, bevor der engere Listen-Socket-Boundary des HTTP-Servers überhaupt existiert |
| `python.desktop_switch` | [effects.py](../../../daedalus/interfaces/desktop/effects.py):672 in `_ensure_switch` | die Control-Root-Sonde des Kill-Switch. Der erste `read_state` in einem Interpreter schreibt eine Nonce-Datei und ruft den Plattformleser auf, ist also selbst ein exakter Effekt und muss vor dem Lesen beginnen |
| `python.desktop_settings_persist` und `python.desktop_ollama_adopt` | über den Lease-Pfad in `DesktopEffectOwner` | die Einstellungsdatei schreiben bzw. ein bereits laufendes Loopback-Ollama adoptieren |

Weitere Eigenschaften, die im Code festgeschrieben sind:

- **Kein Prozessbesitz in v0.1.6.** `start_bridge`, `start_ide`, `stop_ollama`
  und `stop_ide` werfen `DesktopFeatureUnavailable` mit einer Begründung. Der
  Docstring nennt den Grund: für OpenVSCode gibt es keinen langlebigen
  Projekt-Schreib- und Netzwerkvertrag im Kernel, und für Remote-SSH keinen
  physischen Peer plus Schlüsselverwahrungsvertrag. `bridge_status_is_managed`
  gibt konstant Falsch zurück; die File-Bridge behält ihre eigene registrierte
  Boundary.
- **Der Kill-Switch ist Voraussetzung, nicht Zubehör.** `_ensure_switch` hebt
  `LoopHalted`, wenn der Schalter nicht scharf ist. Dieser Eigentümer schaltet
  nie selbst scharf und fabriziert keinen Permit.
- **Evidenz vor STARTED.** `_begin_authorized` verlangt ein retentiertes
  Lease-Subjekt und einen exakten Ausführungsdatensatz, bevor der Ledger in
  STARTED geht; genau eine als nicht anwendbar gemeldete Containment-Notiz gilt
  als Metadatum, jeder andere Retentionsfehler ist fatal. Ein bereits
  vorhandenes terminales Ausführungsquittungsdatum führt zur Ablehnung.
- **Schreibziele sind repository-relativ und keine Symlinks.**
  `_resolved_paths` verweigert absolute Pfade, `..`-Segmente, Pfade, die aus der
  Anwendungswurzel herausführen, und symbolische Links -- und gibt bewusst
  relative POSIX-Pfade zurück, weil der Lease-Vertrag auf Windows sonst
  ungültig wäre.
- **Whitelist statt Redaktion.** `normalize_config` prüft die erlaubten
  Schlüssel je Abschnitt; alles andere ist ein Validierungsfehler. Ein
  Alt-Wert `bridge.auto_start = true` wird zum wahrheitsgemäßen deaktivierten
  Zustand migriert statt akzeptiert.
- **Fail-closed reparierbar.** Eine ungültige kanonische Limit-Policy wird
  nicht still durch eine ausgabefreundliche Voreinstellung ersetzt:
  `environment_projection` setzt dann einen absichtlich unparsbaren Wert in die
  Umgebung, sodass jeder Ledger-Read fehlschlägt, während die Einstellungs-UI
  zur Reparatur erreichbar bleibt.
- **Mutationsrouten sind gesondert bewacht.** `install_web_integration` fängt
  `PUT`/`POST` unter `/api/desktop/` ab, begrenzt den Body und verlangt für
  `/api/desktop/shutdown` eine Eltern-Nonce im Header, die per
  konstantzeitigem Vergleich geprüft wird. Same-Origin-Prüfung kommt aus der
  gemeinsamen HTTP-Schicht ([interfaces-http.md](interfaces-http.md)).
- **Der Initial-Arm ist einmalig und unumkehrbar.**
  `initialize_desktop_switch_once` veröffentlicht zuerst einen dauerhaften
  CREATE_NEW-Claim, der nie entfernt wird. Ein bestehender Claim, ein
  klebender Stopp-Marker, ein manuell gelöschter Permit oder ein Absturz nach
  Claim-Erzeugung können daher nie in ein automatisches Wieder-Scharfschalten
  umschlagen. Auf Windows wird das Elternverzeichnis währenddessen gepinnt, um
  Umbenennungs- und Reparse-Substitution auszuschließen.

## Tests

- [tests/interfaces/test_desktop_effect_owner.py](../../../tests/interfaces/test_desktop_effect_owner.py) --
  Lease-, Evidenz- und Ablehnungspfade von `DesktopEffectOwner`.
- [tests/interfaces/test_desktop_settings_owner.py](../../../tests/interfaces/test_desktop_settings_owner.py) --
  Validierung, Zustimmung und Persistenz der Einstellungen.
- [tests/interfaces/test_desktop_configuration_owner.py](../../../tests/interfaces/test_desktop_configuration_owner.py) --
  Whitelist und Normalisierung.
- [tests/interfaces/test_desktop_sidecar_initial_arm.py](../../../tests/interfaces/test_desktop_sidecar_initial_arm.py) --
  der einmalige Initial-Arm inklusive der Verweigerungsfälle.
- [tests/interfaces/test_desktop_http_csrf.py](../../../tests/interfaces/test_desktop_http_csrf.py) --
  die Mutations-Refusal-Regel der Desktop-Routen.
- [tests/interfaces/test_desktop_strangler_architecture.py](../../../tests/interfaces/test_desktop_strangler_architecture.py) --
  dass die Implementierungsmodule die Fassade nicht zurückimportieren.
- [tests/test_desktop_runtime.py](../../../tests/test_desktop_runtime.py) --
  die Fassade `daedalus.desktop_runtime` selbst.
- [tests/test_desktop_packaging.py](../../../tests/test_desktop_packaging.py) --
  der gepackte Baum und `bundled_root`.
- [tests/test_effect_boundary.py](../../../tests/test_effect_boundary.py) und
  [tests/contracts/test_spine_outer_ports.py](../../../tests/contracts/test_spine_outer_ports.py) --
  die Registrierung der drei Türen.
- [tests/contracts/test_import_scc_hierarchy.py](../../../tests/contracts/test_import_scc_hierarchy.py) --
  die Importhierarchie, die den Strangler trägt.

## Verwandt

- [Spine](spine.md) -- Effekt-Registry, Leases, Kill-Switch.
- [Kernel-Policy](kernel-policy.md) -- Ledger, Ausführungslimits, Egress.
- [Interfaces HTTP](interfaces-http.md) -- die Fassade, auf die dieses Paket
  Routen komponiert.
- [Interfaces Bridge](interfaces-bridge.md) und
  [Interfaces CLI](interfaces-cli.md) -- die beiden anderen Einstiegsflächen.
- [GUI](gui.md) -- die Oberfläche, die diese Projektionen rendert.
- [Runtimes](runtimes.md) und [Runtime-Provider](runtimes-providers.md) --
  woher die Provider-Gesundheitszeilen kommen, die der Snapshot zeigt.
- [Tools](tools.md) -- die Vetting-Verdikte, die dieselbe Oberfläche anzeigt.
- [Wiki-Index](../index.md),
  [Agents hold no state](../decisions/agents-hold-no-state.md).

## Ungeklärt

- Wie viele Registry-Zeilen dieses Paket insgesamt besitzt, habe ich nicht
  vollständig ausgemessen: die drei oben genannten IDs stehen im Code, die
  Zeilen selbst liegen in der Spine-Registry, die ein anderer Bereich abdeckt.
- `projection.ide_status` meldet konstant "not probed by the read-only desktop
  projection". Ob es daneben noch einen aktiven Probe-Pfad in der Fassade gibt,
  geht aus diesem Paket allein nicht hervor.
- Der Docstring von `effects.py` sagt, v0.1.6 besitze keine Service-Handles;
  `lifecycle.bootstrap` ruft dennoch `manager.ensure_bridge`,
  `manager.ensure_ollama` und den IDE-Start, wenn die Konfiguration das
  vorsieht. Da `start_bridge`/`start_ide` typisiert ablehnen, ist das
  vermutlich ein toter Zweig für die Bridge und die IDE -- nachgewiesen habe
  ich es nicht.
