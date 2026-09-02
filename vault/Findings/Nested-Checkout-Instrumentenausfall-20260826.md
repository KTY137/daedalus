---
tags:
- findings
created: 2026-08-26
source: Athena, Live-Baum HEAD 4f71c020
permalink: main/findings/nested-checkout-instrumentenausfall-20260826
---

# Nested-Checkout-Instrumentenausfall

**Artefakt (autoritativ):** `../../docs/GATE0_NESTED_CHECKOUT_INSTRUMENT_FAILURE_20260826.md`

Ein per `git worktree` INNERHALB des Repos ausgecheckter Baum
(`.claude/worktrees/wiki-generation-gate`, über `.git/info/exclude` für
`git status` unsichtbar) legte eine zweite Kopie jedes Moduls in zwei
namensbasierte Scanner. Beide degradierten nicht — beide trafen ihre eigene
Sicherheitsregel und schalteten sich ab: `python.offload` fiel von 573 auf 94
dominierte Positionen, `docrefs` von 380 auf 3622 mehrdeutige Suffixe. Der
Fix pruned strukturell (ein Verzeichnis mit `.git`-Eintrag ist ein anderes
Repository) und hat sich in der ersten Fassung selbst besiegt, weil der Index
rohen Text liest und der Docstring den wiederhergestellten Bezeichner nannte.

Provenienz: MEASURED

Offene Prüfschritte:

- [ ] `daedalus/health.py`, `daedalus/wiki/plan.py`, `daedalus/wiki/verify.py`
      laufen ebenfalls von einer Wurzel mit Namens-Skiplisten — nicht gemessen.
- [ ] Ob frühere Messungen nach 2026-08-25 22:49 betroffen sind, ist pro
      Messung zu prüfen; die Rank-2-Erhebung vom 2026-08-25 ist es NICHT
      (sie lief davor).