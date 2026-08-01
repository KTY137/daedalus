# Event voltage

The [`Event`](../src/ignition_app/models.py) type stores the measured
`voltage`. Rows are loaded by the [repository](../src/ignition_app/repository.py)
from the [event CSV](../data/events.csv) and constrained by the
[event schema](../schemas/event.schema.json).
