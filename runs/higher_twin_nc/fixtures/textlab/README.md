# textlab (fixture 4 of higher-twin-nc-v1)

Three-field four-plane project used as intervention substrate; the
INTERESTING plane here is knowledge (`docs/fields.md`), not code:

- Code plane: `calib.py` (calibration pipeline), `checks.py` (behavior checks)
- Type plane: `schema.json` (field names, types, units)
- Data plane: `data/events.csv`
- Knowledge plane: `docs/fields.md` (generated-canonical field reference,
  extended at runtime by note and appendix operators)

Documented contract (knowledge plane), complete by construction:
`calibrated = score * W_COEF + OFFSET`; `weight` is inert.

Purpose (experiment record, watchdog slice 3): the footprint-rule
COMPLETENESS stressor. Knowledge-plane operators (`annotate_field`,
`add_appendix`) exercise regions the footprint vocabulary does not name:
appendix sections live outside every `field:` slice, and the `field:*`
wildcard of `regen_docs` does not reach `concept:*` resources. The
pre-registered prediction is a measured certificate UNSOUNDNESS for
tail-append pairs (declared disjoint, tree-noncommuting, behavior-equal)
adjudicated as vocabulary misdeclaration via the measured file footprint.

The fixture is never mutated in place; the assay runner copies it per run.
`docs/fields.md` is byte-identical to the `regen_docs` operator template so
that doc regeneration is idempotent on the pristine tree (a designed null).
