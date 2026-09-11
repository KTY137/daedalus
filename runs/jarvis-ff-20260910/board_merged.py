"""Board + vault: both packets merged by owner approval."""
from __future__ import annotations

from pathlib import Path

PRIMARY = Path(r"C:\Users\Administrator\Desktop\projects\daedalus")
B = PRIMARY / "docs" / "AGENT_COORDINATION.md"
b = B.read_bytes().decode("utf-8").replace("\r\n", "\n")

HEARTBEAT = """- Herzschlag: 2026-09-10 19:55 — **beide Packets sind gemerged.** Der Owner
  hat um 19:49 „ich approve alles" geschrieben; darauf #364 (G1-IKARUS-46) und
  #365 (G1-IKARUS-47) per Merge-Commit nach `main` (`3003907f`). Lokaler `main`
  im Primär-Checkout ist vorgezogen — **eure dirty Dateien sind unangetastet**:
  `vault/Gates/Gate-Status.md` blockierte den Fast-Forward, ich habe sie vorher
  gesichert (`runs/jarvis-ff-20260910/`) und byte-identisch wieder
  obendrauf gelegt; dasselbe für diese Board-Datei, die jetzt in `main` getrackt
  ist und deren neueren Stand ich als Arbeitsbaum-Änderung behalten habe.
  **`apps/web/dist/**` habe ich NICHT neu gebaut** — das sind eure
  unversionierten Build-Artefakte aus dem Desktop-Packet. Wer das Cockpit neu
  baut, überschreibt sie; das ist eure Entscheidung, nicht meine. Was ohne
  Rebuild schon geht: der Python-Pfad (Chat → Act → Computer-Loop → Werkzeuge)
  ist im gemergten Baum grün (399 Tests im Primär-Checkout) und die
  Registrierung des Kampagnen-Runners steht beim Import.
"""

anchor = "\n### Lane `codex-desktop` — Desktop-Packaging (Codex, direkt im Primär-Checkout)"
assert b.count(anchor) == 1
b = b.replace(anchor, "\n" + HEARTBEAT + anchor)
B.write_bytes(b.encode("utf-8"))

V = PRIMARY / "vault" / "Sessions" / "2026-09-10.md"
v = V.read_bytes().decode("utf-8").replace("\r\n", "\n")
ENTRY = """- 19:40-19:55 **Cerberus Runde 3 auf #365: `approve`, der Block aus Runde 2 ist aufgehoben** (die CRITICAL-Stelle wurde durch Ausführen BEIDER Revisionen gegen denselben injizierten Registry-Fehler als geschlossen verifiziert). Vier Lows: die Quittungsprüfung hieß „matches", misst aber „widerspricht nicht" (umbenannt, mit Test für die schweigende Quittung); die ID-Komposition kürzt ein Label bei 40 Zeichen (jetzt im Packet); die Hardlink-Verweigerung trifft auch Lesevorgänge in einem `.venv`/`node_modules` des Subjekts (3810 von 4951 Dateien dort sind Hardlinks — richtig für eine Reparatur-Kampagne, jetzt an der Prüfung dokumentiert); und ein vorbestehender Befund, der NICHT zu 47 gehört (eine Fehlermeldung kann einen deny-gelisteten Pfad nennen, den die Erfolgsprojektion zurückhält) — auf dem Board bei G1-ARIADNE-11. **Odysseus Runde 4: alle Reparaturen halten** — der TOCTOU-Exploit gewinnt 0 von 3000 Iterationen (vorher 12/12), eine Lesepfad-Zählung zeigt, dass der einzige Byte-Lesevorgang der Kampagne im Subjekt durch den reparierten Leser geht, alle zehn Wächter rot inklusive der zwei zuvor mutationsblinden. Zwei Low-Reste an den EIGENEN Türen der Kampagne (NTFS-Alternate-Data-Stream; Label-Kollaps) → Board. 799 grün, Tabelle 43/43.
- 19:49 **Owner: „ich approve alles"** → #364 und #365 gemergt (`25104777`, `3003907f`), lokaler `main` vorgezogen. Die dirty Dateien der Desktop-Lane und die fremde `vault/Gates/Gate-Status.md` sind byte-identisch erhalten (Sicherung in `runs/jarvis-ff-20260910/`). **Nicht** neu gebaut: `apps/web/dist/**` gehört der Desktop-Lane und ist dort unversioniert geändert — ein Cockpit-Rebuild würde ihre Arbeit überschreiben. Verifiziert im Primär-Checkout auf `main`: 399 Tests grün, `DAEDALUS_TOOLS` + `ARIADNE_TOOLS` registriert, Kampagnen-Runner beim Import gebunden.
"""
anchor2 = "- [ ] **Owner: PR #364 mergen**"
assert v.count(anchor2) == 1
head, sep, tail = v.partition(anchor2)
rest = tail.split("\n", 1)[1] if "\n" in tail else ""
NEW_TODO = """- [ ] Owner: App neu starten, damit der Python-Pfad von `main` läuft; danach `/computer enable daedalus` und `/computer enable ariadne confirm-campaigns` (beides Bestätigungs-pflichtig).
- [ ] Cockpit-Rebuild (`apps/web`) erst, wenn die Desktop-Lane ihre unversionierten `dist/`-Änderungen gesichert oder committet hat — sonst überschreibt der Build ihre Arbeit.
- [ ] Nächste Packets: G1-IKARUS-48 (Evaluator, der Tests ausführt — erst damit ist „Selbstverbesserung" mehr als ein eingefrorener Exakt-Vergleich), dann G1-IKARUS-37 (`terminal.run` Argv-Allowlist), dann Skill `daedalus-jarvis`.
"""
v = head + NEW_TODO + rest
v = ENTRY + v if False else v.replace("## Kompaktierungen", ENTRY + "\n## Kompaktierungen", 1)
V.write_bytes(v.encode("utf-8"))
print("board and vault updated")
