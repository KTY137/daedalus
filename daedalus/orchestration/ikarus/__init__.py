"""Ikarus: the assistant surface -- intent in, typed proposal out.

WHY THIS PACKAGE EXISTS. Nine modules under ``daedalus/orchestration/`` shared
the ``ikarus_`` prefix, which is a package spelled with underscores, and
``orchestration`` was left as the largest flat directory in the tree once the
provider and repository families became packages. ``Ikarus`` is one of the three
names the master plan admits (§3), so this groups existing modules under a name
the plan already owns rather than minting a new one.

THE PREFIX IS DROPPED because the package now carries it, with ONE exception
that is a hazard and not a preference: stripping ``ikarus_os`` yields ``os.py``,
which shadows the standard library for any process whose working directory or
``sys.path[0]`` lands beside it. ``daedalus/interfaces/http/`` already has that
defect and it is recorded in G1-FLAT-06; deliberately creating a second one
would be careless. The module is ``shell.py``, which is the word its own
docstring uses for the three capability-split modes it dispatches between.

WHAT IS HERE:

* ``shell`` -- the deterministic intent router and the vendor-neutral voice;
* ``act`` -- the capability predicate the Hand shell must clear first;
* ``chat``, ``oneshot`` -- the conversational and stateless request shapes;
* ``tool_scope``, ``runtime_role`` -- what a runtime may use, and as whom;
* ``runtime_events``, ``effect_bridge`` -- observation and the canonical seam;
* ``supervisor`` -- the state ledger over a run.

WHAT IS NOT HERE, and must not move in. Ikarus proposes; it does not authorize.
Policy, budget, the Effect Lease, evidence and promotion stay with the kernel
and spine contracts these modules call into. The plan's own words: "Models never
obtain authority by being selected as the speaking voice."
"""
