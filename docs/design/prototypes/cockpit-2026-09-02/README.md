# Cockpit — 2026-09-02 (G1-UI-05)

**These are not mockups.** Every image is a screenshot of the running
application at `apps/web`, served from the built bundle by `daedalus web` on
loopback against this checkout registered as project `daedalus_wt`, at
1440×900. `manifest.json` is `tools/shoot.mjs`'s record of what was on screen
for the two `gespraech-*.png` shots (theme, composition attributes, the
state line verbatim). The other three were taken with a short Playwright
script after opening a stored thread from the rail.

| file | what it shows |
| --- | --- |
| `gespraech-referenz.png` | the conversation page at rest: invitation and composer as one centred group, the pre-flight rail (Antwortet · Aufwand · Bühne · Was würde gelesen?), the Verlauf rail listing this project's threads from the spine |
| `gespraech-leitstand.png` | the same page in the light theme |
| `thread-open-referenz.png` | a resumed thread: the reader's question, Ikarus's answer in the voice face, and its Protokoll opened — Route `Lokaler Index · Shell: deterministisch`, Antwort `GEMESSEN · lokaler Index` |
| `thread-leitstand.png` | the same thread with the Protokoll folded and the nudge under a measured answer |
| `commands-referenz.png` | the `/` menu above the composer, every command with what it does |

What is real: the thread list is `GET /api/conversations?project=`, the
threads it shows were made by the Playwright suite's `status` turns, and the
Protokoll rows are derived from the envelope the spine stored with each turn.
Nothing in these shots is a fixture.

The map page is unchanged by this packet and is not shown.
