# Proposals — Statusline & Hooks (NICHT aktiv)

`.claude/settings.json` ist ein geschütztes Iron-Plan-Artefakt. Diese Dateien
sind deshalb **Vorschläge**: die Skripte sind lauffähig und getestet, aber erst
wirksam, wenn der Owner die Snippets selbst in die settings.json merged
(oder — sofortiger, ungeschützter Weg — in `.claude/settings.local.json`).

## Inhalt

| Datei | Zweck |
| --- | --- |
| `statusline.py` | Statusline: Modell, Verzeichnis, Branch, Kontext-%, Session-Kosten. Pure stdlib, kein jq (jq ist auf dieser Box nicht installiert). |
| `settings.statusline.snippet.json` | Das `statusLine`-Objekt zum Mergen. |
| `hook_precompact_vault.py` | PreCompact: schreibt vor jeder Kompaktierung einen Marker in die heutige Vault-Daily-Note (`vault/Sessions/YYYY-MM-DD.md`), damit Session-Kontext nie spurlos kompaktiert wird. Blockiert nie (exit 0). |
| `hook_notification_toast.py` | Notification: Windows-Popup (WScript.Shell, kein Zusatzmodul) bei `permission_prompt` / `agent_needs_input` / `agent_completed` — für unbeaufsichtigte lange Läufe. |
| `settings.hooks.snippet.json` | Die beiden Hook-Einträge zum Mergen (additiv zu den bestehenden Iron-Plan-Hooks — nichts ersetzen!). |

## Mergen (Owner, ~3 min)

1. Snippet-Inhalt in `.claude/settings.json` (geschützt, ggf. Amendment-frei da
   additive Hook-Ergänzung — Owner entscheidet) ODER `.claude/settings.local.json` kopieren.
2. Bestehende `hooks`-Einträge NICHT ersetzen: `PreCompact`/`Notification` sind
   neue Schlüssel, sie kollidieren mit nichts Bestehendem.
3. Testen: `echo {"model":{"display_name":"Test"}} | python .claude/proposals/statusline.py`

## Warum genau diese zwei Hooks (Recherche-Kurzfassung)

- PreCompact ist der einzige Punkt, an dem Kontextverlust VOR dem Verlust
  sichtbar wird (offizielle Hook-Doku: PreCompact kann sogar blocken; wir
  loggen nur). Quelle: code.claude.com/docs/en/hooks
- Notification-Hooks sind der Standard-Trick der 2026-Community-Setups für
  lange autonome Läufe (Quelle: smartscope.blog Claude-Code-Best-Practices 2026).
