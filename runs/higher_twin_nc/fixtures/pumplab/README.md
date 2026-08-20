# pumplab (fixture 2 of higher-twin-nc-v1)

Five-field four-plane project used as intervention substrate:

- Code plane: `calib.py` (calibration pipeline), `checks.py` (behavior checks)
- Type plane: `schema.json` (field names, types, units)
- Data plane: `data/events.csv`
- Knowledge plane: `docs/fields.md` (generated-canonical field reference)

Documented contract (knowledge plane): `calibrated` is a linear function of
`flow_rate` alone — `calibrated = flow_rate * GAIN + OFFSET`.

Ground truth (experiment record, watchdog slice 1): `calib.py` additionally
reads the `pressure` column (multiplicative correction around `P_REF`).
This coupling is deliberately absent from the documented contract. It is
the non-circular target for H-ANOM: an operator whose footprint declaration
honestly follows the documented contract (e.g. `retune_offset`) will be
declared-disjoint from pressure edits, yet order-sensitive in behavior.
`temperature` and `rpm` are read by nothing — specificity controls.

The fixture is never mutated in place; the assay runner copies it per run.
`docs/fields.md` is byte-identical to the `regen_docs` operator template so
that doc regeneration is idempotent on the pristine tree (a designed null).
