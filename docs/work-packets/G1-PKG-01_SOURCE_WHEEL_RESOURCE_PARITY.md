# G1-PKG-01 — Source/Wheel resource parity

## Frozen packet metadata

- Packet ID: `G1-PKG-01`
- Active gate: **Gate 1 — Renovation ignition slice**
- Classification: `ALIGNED`
- Owner: repository owner; no automatic merge, promotion, or Gate transition
- Base revision: `151b8d180e321cfba48b4c7d62f9be56579d52a5`
- Master-plan authority: Revision 10
- Primary claim: an installed wheel can read the same built-in roles,
  scaffold templates, GUI catalogue and JSON Schemas as a source checkout,
  without packaging project-local state or creating a second resource truth.

## Baseline

`daedalus.config`, `daedalus.router`, `daedalus.categories` and
`daedalus.gui_catalogue` resolve defaults through repository-root paths.  The
wheel includes only `daedalus*`, so source tests pass while an installed wheel
silently loses those resources.

## Scope and invariants

- Package immutable defaults under `daedalus.resources` and load them through
  `importlib.resources`.
- Keep explicit `<repo>/.agentenv` role/category overrides first.
- Treat root `agents/`, `templates/`, `catalogue/` and `configs/schemas/` as a
  temporary byte-identical mirror.  Divergence refuses instead of choosing one
  of two authorities.
- Built-in package data is read-only.  Role/category mutation requires an
  explicit repository root and never writes into site-packages.
- No credentials, project registry rows, databases, runtime state, prompts or
  generated evidence enter the wheel.

Forbidden: no provider/network/model call, no second configuration store, no
change to policy/effect/promotion semantics, no relocation of historical
evidence, and no Master Plan or amendment edit.

## Acceptance matrix

| Claim/refusal | Evidence | Expected |
| --- | --- | --- |
| Checkout mirrors | byte comparison | every shipped file agrees |
| Root directories absent | focused tests | roles/templates/catalogue still load |
| Isolated wheel | build/install smoke outside checkout | same resource counts and scaffold output |
| Legacy drift | mutated mirror test | `ResourceDriftError` before use |
| Local override | router/category tests | explicit project data wins |
| Global mutation | refusal tests | requires explicit repo root |
| Distribution contents | wheel archive inventory | all declared resources, no local state |

Rollback restores root-relative reads and removes package-data declarations;
it restores the known source/wheel mismatch but changes no persistent format.

## Measured packet evidence

- `py -3.13 -m pytest tests/test_packaged_resources.py tests/test_agents_registry.py tests/test_categories.py tests/test_gui_catalogue.py -q`
  -> `79 passed`.
- `uv build --wheel --offline --out-dir <temporary-directory>` succeeded.
- The isolated install smoke imported from the temporary `site/` directory,
  found 7 built-in roles, 5 scaffold roles, 29 catalogue entries from 2 files,
  and 60 files below `daedalus/resources/` (including the resolver module).
- Built wheel: `daedalus-0.1.3-py3-none-any.whl`, SHA-256
  `5d66d814e2f3e90c7e0c2db535841d6b60dd5bbd42ff7020eb5939e5369e923f`.
- The wheel inventory contained no top-level project/runs tree, database, or
  credential-named file.

The broader frozen parent is not green: imports through `daedalus.kernel`
currently reference an absent `daedalus.kernel.campaigns`, and the existing
VS Code extension fixture fails its dashboard-control assertion. Those are
retained parent evidence, not attributed to this resource packet.

Iron Plan: ALIGNED
Iron Gate: 1
