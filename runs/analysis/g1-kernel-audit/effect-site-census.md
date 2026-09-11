# Kernel effect-site census vs the Effect Registry

Base 54f09753. Mechanically derived, `.venv/Scripts/python.exe`, AST walk over
all 50 files of `daedalus/kernel/`. Static only.

## Method

An `ast.walk` over every `daedalus/kernel/**/*.py`, counting only
**module-qualified or unambiguous** call shapes:

- `subprocess.*` (any attribute call on the `subprocess` module)
- `os.{replace,rename,remove,unlink,makedirs,mkdir,fsync}`
- `shutil.{rmtree,copytree,copy2,copyfile,move,copy}`
- `tempfile.{mkdtemp,mkstemp,NamedTemporaryFile,TemporaryDirectory}`
- `sqlite3.connect`
- `socket.*` / `requests.*` / `httpx.*` / `urlopen(...)`
- `.{mkdir,write_text,write_bytes,touch,chmod}` on a non-stdlib-module receiver
  (i.e. `Path`-like)
- `open(..., <mode containing w/a/x/+>)`
- regex for `os.environ.get(` / `os.getenv(` / `in os.environ` (reads) and
  `os.environ[...] =` / `os.environ.pop(` (writes)

**A first pass over-counted `fs_write` at 69 by matching bare `.replace(`, which
also matches `str.replace`.** The numbers below are from the corrected,
module-qualified pass. Recording the error because the inflated number is the
one an unchecked script would have reported.

### Known limits of this census

- It counts **syntactic** sites, not reachable effects. Some are benign
  (`chmod`), and one file's count can be a single effect expressed twice.
- It does **not** follow indirection. A module that calls into
  `daedalus.spine.ledger` performs a filesystem effect that this census
  attributes to the callee, not the caller. So the true effectful-module count
  is a lower bound, not an upper one.
- It says nothing about whether an effect is *guarded* — only whether the
  Registry names it.

## Result

**77 effect sites across 18 of the 50 kernel files.**

| file | subproc | fs write | sqlite | env read | env write | open(w) |
| --- | --- | --- | --- | --- | --- | --- |
| `policy/ledger.py` | 0 | 4 | 0 | 8 | 3 | 1 |
| `source_trees.py` | 0 | 13 | 0 | 0 | 0 | 0 |
| `promotion_trust_root.py` | 1 | 7 | 0 | 1 | 0 | 2 |
| `events/envelope.py` | 0 | 0 | 0 | 3 | 4 | 0 |
| `approvals.py` | 0 | 1 | 1 | 2 | 0 | 0 |
| `attempt_execution.py` | 1 | 2 | 0 | 0 | 0 | 1 |
| `events/ledger.py` | 0 | 1 | 2 | 1 | 0 | 0 |
| `runtime_conformance.py` | 0 | 4 | 0 | 0 | 0 | 0 |
| `artifacts.py` | 0 | 2 | 0 | 0 | 0 | 0 |
| `effects.py` | 0 | 1 | 1 | 0 | 0 | 0 |
| `offload_lease.py` | 0 | 1 | 1 | 0 | 0 | 0 |
| `policy/pricing.py` | 0 | 0 | 0 | 2 | 0 | 0 |
| `attempt_spine_reader.py` | 0 | 0 | 1 | 0 | 0 | 0 |
| `effect_recovery.py` | 0 | 0 | 1 | 0 | 0 | 0 |
| `effect_replay.py` | 0 | 0 | 1 | 0 | 0 | 0 |
| `promotion.py` | 1 | 0 | 0 | 0 | 0 | 0 |
| `promotion_execution_reader.py` | 0 | 0 | 1 | 0 | 0 | 0 |
| `sandbox.py` | 1 | 0 | 0 | 0 | 0 | 0 |
| **total** | **4** | **36** | **9** | **17** | **7** | **4** |

Network: **0** sites in the entire kernel. That is a real and positive result —
egress does not originate in the trust kernel.

## The registry side

`daedalus/spine/effect_boundary.py` declares **108** `EntrypointSpec` rows.
Exactly **4** carry `target="daedalus.kernel...."`:

| line | id | target | declared effects |
| --- | --- | --- | --- |
| 350 | `kernel.attempt.begin` | `attempt_ledger:AttemptLedger.begin` | FILESYSTEM_WRITE |
| 372 | `kernel.attempt.complete` | `attempt_ledger:AttemptLedger.complete` | FILESYSTEM_WRITE |
| 394 | `kernel.attempt.prepare` | `attempt_workspace:IsolatedAttemptCoordinator.prepare` | FILESYSTEM_WRITE |
| 2304 | `cli.approvals` | `approvals:main` | (CLI row) |

So: **18 kernel modules contain effect sites; 3 of them are named by a registry
row.** All four rows declare only `FILESYSTEM_WRITE`, so no kernel row declares
`PROCESS_SPAWN` despite 4 subprocess sites (`sandbox.py`, `promotion.py`,
`promotion_trust_root.py`, `attempt_execution.py`), and none declares `SPEND`
despite `policy/ledger.py` owning the money path.

`Effect` (`effect_boundary.py:43-51`) has eight members —
`FILESYSTEM_WRITE, PROCESS_SPAWN, PROCESS_CONTROL, NETWORK_EGRESS,
LISTEN_SOCKET, REPOSITORY_MUTATION, SPEND, SECRETS` — and **no member for
environment mutation**, so the 7 env-write sites (`events/envelope.py` ×4,
`policy/ledger.py` ×3) are not expressible in the model at all. That matters
because the environment is how state crosses the `subprocess` boundary the
registry *does* model: `events/envelope.py:347` exports `DAEDALUS_TRACE_ID` and
`policy/ledger.py:527` exports `DAEDALUS_BUDGET_ENVELOPE` specifically so
children inherit them.

## Reading this fairly

This is an **inventory-coverage** result, not a list of vulnerabilities. Two
honest qualifications:

1. Several rows model the kernel as the **guard** rather than the guarded thing —
   `kernel.attempt.begin`/`complete` declare
   `guard_contracts=("spine.intent_ledger",)` and anchor on
   `record_intent`/`mark_completed`. Under that model, `events/ledger.py` is
   deliberately a guard implementation and not an entrypoint.
2. Some kernel effects are covered by a **non-kernel** row further out.
   `fourfold_evidence.py`'s `_store_snapshot` is reached in production only via
   `daedalus/ignition/__main__.py`, whose row (`effect_boundary.py:2560-2579`)
   explicitly credits "content-addressed evidence stores".

What survives both qualifications:

- **Constructors and factories are systematically uninventoried.**
  `SpineLedger.__init__` (`events/ledger.py:338-343`) creates a directory,
  creates the database, performs a persistent `journal_mode=WAL` transition and
  runs schema DDL. `AttemptLedger.__init__` (`attempt_ledger.py:63,99-104`)
  opens that store and executes `CREATE UNIQUE INDEX`. Both are durable
  cross-process filesystem effects; the registry's anchors are all method-body
  anchors, so a mechanical anchor check passes while the constructor writes go
  uncounted.
- **`PROCESS_SPAWN` has no kernel row**, while `sandbox.py` — the module whose
  whole purpose is containment — spawns the Docker CLI.
