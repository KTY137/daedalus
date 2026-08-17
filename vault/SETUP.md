---
tags: [meta, setup]
created: 2026-08-17
---

# SETUP — was der Owner einmalig tun muss

Gesamtaufwand: ca. 10–15 Minuten. Der Vault funktioniert schon jetzt ohne
jeden dieser Schritte als reiner Markdown-Ordner (Claude liest/schreibt ihn
direkt); die Schritte machen ihn zur Obsidian-Oberfläche.

## 1. Obsidian installieren (5 min)

1. https://obsidian.md/download → Windows-Installer, installieren.
2. Obsidian starten → "Open folder as vault" → `C:\Users\nukei\Desktop\agent_env\vault` wählen.
3. "Trust author and enable plugins" kann übersprungen werden — der Vault
   braucht **keine** Community-Plugins, um zu funktionieren (alle Dashboards
   sind mit Bordmitteln gebaut).

## 2. Community-Plugins (optional, je 1–2 min)

Nur der Owner kann Plugins in der Obsidian-App installieren
(Settings → Community plugins → Browse). Empfehlungen, bewusst kurz:

| Plugin | Wozu | Empfehlung |
| --- | --- | --- |
| **Local REST API** (coddingtonbear) | Voraussetzung für den REST-basierten Obsidian-MCP (Upgrade-Pfad, s. u.) | Nur wenn Upgrade-Pfad gewünscht |
| **Dataview** | Automatische Übersichten/Abfragen | Optional — Dashboards hier sind absichtlich Dataview-frei |
| **Templater** | Mächtigere Templates als das Core-Plugin | Optional |
| **Periodic Notes** | Wochen-/Monatsnotizen zusätzlich zu Daily Notes | Optional |

**Bewusst NICHT empfohlen:** *Obsidian Git* — der Vault liegt bereits im
Daedalus-Repo; ein zweiter Git-Automat würde mit dem Repo-Guard und den
Commit-Trailern kollidieren. Committen läuft über den normalen Repo-Workflow.

## 3. Obsidian-MCP: was konfiguriert ist und der Upgrade-Pfad

**Konfiguriert (keine Aktion nötig):** In `.mcp.json` ist der Server
`obsidian-vault` ergänzt — der offizielle MCP-Filesystem-Server, gescoped auf
`vault/`. Er braucht kein Plugin, keinen API-Key und keine laufende
Obsidian-App; das ist unter Windows die robusteste Variante (Quelle:
contextbolt.com Obsidian-MCP-Vergleich, 2026).

**Upgrade-Pfad REST (2 min), nur falls Obsidian-interne Features per MCP
gewünscht sind** (Suche über den Obsidian-Index, Patch einzelner Headings):

1. Plugin **Local REST API** installieren und aktivieren.
2. Settings → Local REST API → API-Key kopieren.
3. In `.mcp.json` zusätzlich eintragen (Python/uv muss vorhanden sein; ist es):

   ```json
   "obsidian-rest": {
     "command": "uvx",
     "args": ["mcp-obsidian"],
     "env": {
       "OBSIDIAN_API_KEY": "<hier den Key einfügen>",
       "OBSIDIAN_HOST": "127.0.0.1",
       "OBSIDIAN_PORT": "27124"
     }
   }
   ```

   Server: `MarkusPfundstein/mcp-obsidian` (meistgenutzter Obsidian-MCP auf
   GitHub). Achtung: funktioniert nur, solange die Obsidian-App läuft.

## 4. Statusline & Hook-Vorschläge übernehmen (optional, 3 min)

`.claude/settings.json` ist ein geschütztes Iron-Plan-Artefakt — deshalb liegen
Statusline und neue Hooks nur als Vorschläge unter `.claude/proposals/`
(README dort erklärt das Mergen). Kurzfassung: Snippet aus
`settings.statusline.snippet.json` bzw. `settings.hooks.snippet.json` in die
settings.json übernehmen; die Skripte selbst sind lauffähig getestet.
