# sensorlab (fixture 1 of higher-twin-nc-v1)

Minimal four-plane project used as intervention substrate:

- Code plane: `calib.py` (calibration pipeline), `checks.py` (behavior checks)
- Type plane: `schema.json` (field names, types, units)
- Data plane: `data/events.csv`
- Knowledge plane: `docs/fields.md` (generated-canonical field reference)

The fixture is never mutated in place; the assay runner copies it per run.
`docs/fields.md` is byte-identical to the `regen_docs` operator template so
that doc regeneration is idempotent on the pristine tree (a designed null).
