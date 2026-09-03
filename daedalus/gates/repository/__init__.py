"""Repository gates: what a write to this checkout must satisfy before it happens.

WHY A SUBPACKAGE. Sixteen modules under ``daedalus/gates/`` shared the
``repository_`` prefix, and seven of them are one strongly connected import
component. As with ``daedalus.runtimes.provider``, the grouping is measured
rather than preferred: the modules already formed a unit and only the directory
disagreed. The prefix is dropped because the package now carries it.

TWO FAMILIES:

* ``head_revision`` and ``tree`` -- reading the repository as it is: the
  authenticated HEAD receipt and the tree the gates classify;
* ``write_*`` -- the admission chain for one write: classification, effect
  lease, guard structure, artifact CAS and verification, evidence origin and
  materialization, runtime conformance, and the inventories that count what
  the chain found.

WHAT THIS PACKAGE DOES NOT DO. It authorizes nothing on its own. Every module
here produces a classification, an inventory or a receipt that the canonical
kernel and spine contracts consume; the Effect Lease, the owner approval and
the promotion path stay where they are. A gate that could also grant would be
the defect its own tests are written to catch.
"""
