# Proposals — Statusline & Hooks (seit 2026-08-23 VERDRAHTET)

Stand 2026-08-23 (hooks v2, `docs/superpowers/specs/2026-08-23-hooks-v2-design.md`):
PreCompact ist in `.claude/settings.json` über den registrierten
`daedalus/hooks`-Dispatcher verdrahtet;
`statusline.py` und `hook_notification_toast.py` laufen als Kopien unter
`~/.claude/hooks/` (user-global, damit sie nicht von einem archivierbaren
Repo-Pfad abhängen). Quelle der Wahrheit bleibt dieses Verzeichnis — nach einer
Änderung hier die Kopie nachziehen. Die Merge-Anleitung unten ist Geschichte.

## Inhalt

| Datei | Zweck |
| --- | --- |
| `statusline.py` | Statusline: Modell, Verzeichnis, Branch, Kontext-%, Session-Kosten. Pure stdlib, kein jq (jq ist auf dieser Box nicht installiert). |
| `settings.statusline.snippet.json` | Das `statusLine`-Objekt zum Mergen. |
| `daedalus/hooks/events.py` | PreCompact: schreibt über den kanonischen Dispatcher vor jeder Kompaktierung einen Marker in die heutige Vault-Daily-Note (`vault/Sessions/YYYY-MM-DD.md`). Blockiert nie. |
| `hook_notification_toast.py` | Notification: Windows-Popup (WScript.Shell, kein Zusatzmodul) bei `permission_prompt` / `agent_needs_input` / `agent_completed` — für unbeaufsichtigte lange Läufe. |
| `orient.py` + `roots.example.json` | User-level SessionStart/CwdChanged-Hook: sagt, ob die Session im LIVE- oder im ARCHIVIERTEN Baum steht (Liste der Roots in `~/.claude/hooks/roots.json`). Kopie läuft unter `~/.claude/hooks/orient.py`. |
| `settings.hooks.snippet.json` | Projekt-PreCompact über `daedalus/hooks` plus optionaler Notification-Eintrag. |

## Mergen (Owner, ~3 min)

1. Snippet-Inhalt in `.claude/settings.json` oder `.claude/settings.local.json` kopieren.
2. Bestehende `hooks`-Einträge NICHT ersetzen: `PreCompact`/`Notification` sind
   neue Schlüssel, sie kollidieren mit nichts Bestehendem.
3. Testen: `echo {"model":{"display_name":"Test"}} | python .claude/proposals/statusline.py`

## Warum genau diese zwei Hooks (Recherche-Kurzfassung)

- PreCompact ist der einzige Punkt, an dem Kontextverlust VOR dem Verlust
  sichtbar wird (offizielle Hook-Doku: PreCompact kann sogar blocken; wir
  loggen nur). Quelle: code.claude.com/docs/en/hooks
- Notification-Hooks sind der Standard-Trick der 2026-Community-Setups für
  lange autonome Läufe (Quelle: smartscope.blog Claude-Code-Best-Practices 2026).
