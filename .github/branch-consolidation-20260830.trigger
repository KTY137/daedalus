Owner-authorized one-shot remote branch consolidation on 2026-08-30.
Target: exactly 11 canonical remote branches.
Recovery manifest is mandatory before any PR archival or ref deletion.
Every retired branch tip must additionally exist as an exact Git archive tag before deletion.
Retrigger: safe-archive-v1.
