# Daedalus

Daedalus is a multi-agent harness that routes work to the cheapest lane that can
be **verified** to have done it correctly, and refuses to promote work it cannot
justify.

Start with [`docs/STATUS.md`](docs/STATUS.md) for current truth pointers. The
long-horizon architecture and delivery programme live in
[`docs/IKARUS_ARIADNE_MASTER_PLAN.md`](docs/IKARUS_ARIADNE_MASTER_PLAN.md).
In that vocabulary **Ikarus** is the user-facing assistant and **Ariadne** is the
evolution engine; `forest-evolve` is a descriptive CLI surface, not a second
product identity.

## Invariants

- A central router picks one agent. There is no free agent-to-agent chat.
- Every subagent invocation is stateless.
- Downstream agents receive pruned state, never the full transcript.
- Reports are short and structured, or they are rejected.
- A number without provenance is not a result. Use `MEASURED`, `INHERITED`, or
  `ASSUMED` and retain the command/receipt that produced the claim.
- Presence is not proof. Health and gate surfaces distinguish working,
  present-but-unexercised, degraded, unknown, and failed states.
- Model self-report never substitutes for repository state, tests, or evidence.

## Where current truth lives

This README deliberately does **not** copy live module counts, test totals,
island counts, CI status, or a HEAD SHA. Those values rot faster than the
contracts around them. Measure them at the revision you are evaluating:

```powershell
python -m daedalus.interfaces.cli.entry health --deep
python -m daedalus.interfaces.cli.entry map --check
python tools/docs_reference_check.py
python -m pytest tests/ -n auto --dist loadfile
```

`-n auto --dist loadfile` needs the `[test]` extra (it installs `pytest-xdist`)
and is the intended way to run the whole suite: most of the wall clock is spent
waiting on the child processes the tests spawn, so one worker per hardware
thread turns a run measured in tens of minutes into one measured in minutes.
Plain `python -m pytest tests/` still works and still means the same thing --
without xdist the flags are simply rejected, never silently ignored. Keep
`--dist loadfile` rather than the per-test default: it keeps each file's tests
on one worker, which is what makes the parallel verdict equal the serial one.

Two things a parallel run legitimately changes, both measured on 2026-09-02:
each worker adds a `popen-gwN` component to `tmp_path`, which is enough to push
`tests/test_chip_cli_canonical.py` over a 1000-character limit it already sits
within ten characters of; and tests that race a wall-clock deadline against a
child interpreter's start-up see that start-up take longer under load.

Read [`docs/STATUS.md`](docs/STATUS.md) before trusting an old architecture
snapshot or gate receipt. Historical measurements stay historical; they are not
silently rewritten to resemble the current tree.

## Repository layout

| Path | Purpose |
|---|---|
| `daedalus/` | Harness implementation: routing, providers, safety, orchestration, gates, mapping and domain capabilities. |
| `daedalus/chip_design/` | RTL/source classification, EDA tool discovery and dry-run-first Tcl/lint execution. |
| `agents/`, `templates/` | Built-in roles and project-neutral scaffolding. |
| `projects/` | Registered target repositories and per-project policy. |
| `tests/` | Harness and contract tests. |
| `docs/` | Current documentation, authority documents, backlog and historical evidence; see [`docs/README.md`](docs/README.md). |
| `tools/` | Repository/operator scripts that are not shipped as the Python package. |
| `scripts/`, `experiments/` | Operational one-shots and research spikes. |
| `apps/` | Web/application surfaces. |
| `structcore-rs/` | Rust structural core. |
| `vscode-agent-env/` | VS Code integration. |
| `outbox/`, `inbox/`, `runs/`, `memory/` | File-bus state, retained evidence and local/volatile run state. |
| `.room/` | Cross-vendor shared transcript surface. |

Packaging uses setuptools discovery for `daedalus*` packages. Do not maintain a
hand-written package-count list in documentation; verify a built wheel when
packaging behavior matters.

## Quickstart

For policy-scoped Ikarus computer tasks and source/wheel installation of the
optional observation-backed OpenCV/OCR/browser dependencies, see
[Ikarus computer assistance](docs/IKARUS_COMPUTER.md). Native desktop bundles
do not include that optional dependency set.

```powershell
# bench / provider readiness
python -m daedalus.interfaces.cli.entry doctor

# scaffold a target repository; existing files are not overwritten
python -m daedalus.interfaces.cli.entry init <your-repo>

# real local round-trip proof on a throwaway repo
python -m daedalus.interfaces.cli.entry selftest

# plan a scoped offload; add --live only when you intend a real write
python -m daedalus.interfaces.cli.entry offload "Add a docstring to <some function>" `
  --repo-root <your-repo> --paths path\to\file.py

# local API + Agent OS webapp
python -m daedalus.interfaces.cli.entry web
```

The authoritative command inventory is always generated by the program:

```powershell
daedalus --help
daedalus <command> --help
```

Representative surfaces include health/governance checks, offload/spawn/build
execution, Ikarus interaction, council/review workflows, mapping/bookkeeping,
project/agent configuration, dashboard/watcher/web operation, and Gate evidence
commands. Do not copy the complete parser into prose; it creates a second command
registry that drifts from `daedalus.interfaces.cli.entry`.

### Genesis v1 and Ariadne v0

The next release exposes one deliberately finite Genesis product path and one
bounded Ariadne improvement path. Genesis currently accepts a local/offline
single-user item collection (Web/PWA or CLI) with create, edit, delete,
complete/reopen, persistence, and optional search/filter. It refuses every
unconsumed requirement before starting an effect; it does not silently turn an
authentication, payments, cloud, collaboration, native-package, or unrelated
product request into generic CRUD.

```powershell
# Build, verify, retain, and preview a zero-base Web candidate.
daedalus genesis "Build a searchable local task board" --target web
daedalus web
```

The Web command serves the Agent OS on loopback; open its **Genesis** workspace,
run the request there, and use the embedded certified preview. The CLI performs
the same retained build and tells you to open that workspace; it does not print
a standalone preview URL. A successful run retains the exact source-tree CAS
identity and independent evidence. It never edits the primary checkout and
never publishes, merges, approves, or promotes the candidate.

Ariadne v0 is usable as a controlled repair campaign over one UTF-8 file. It
freezes the exact working-tree bytes, evaluator, three ordered arms, and equal
per-arm budgets, retains failed arms, and may emit a nomination only. Arm the
operator switch explicitly, then supply the repository's current HEAD and one
unambiguous replacement:

```powershell
python -m daedalus.spine.killswitch arm
$revision = git rev-parse HEAD
daedalus ariadne --source-revision $revision --campaign-id repair-001 `
  --target path\to\file.py --before "old exact text" --after "new exact text"
```

Repeating the exact completed campaign is a read-only replay; reusing its id for
different input is refused. This is the first repeatable link in the improvement
chain, not an unbounded autonomous loop or a general model-driven repair engine.
Candidates cannot alter policy or their evaluator, and nomination still carries
no merge or promotion authority.

On native Linux, candidate-executing checks are opt-in through rootless Podman
and require `DAEDALUS_LINUX_OCI_IMAGE` to name an already-local image by its full
`@sha256:` digest. The backend refuses missing rootless user namespaces, cgroup
v2 limits, the packaged seccomp policy, or automatic container secret mounts;
there is no host-process fallback. Debian and RHEL unit-policy coverage does not
substitute for a live receipt on each advertised host family.

### Optional CUDA research environment

The production package stays Python-stdlib-only. On an NVIDIA Windows/Linux
research host, the explicit `gpu` extra installs the CUDA 12 stack used by the
bounded tensor experiments: PyTorch, Newton/NVIDIA Warp, and CuPy. It is not a
runtime backend selection and is intentionally excluded from normal bootstrap.

```powershell
# Fresh or existing Windows environment; the hardware preflight runs before
# the multi-gigabyte locked sync.
powershell -ExecutionPolicy Bypass -File .\bootstrap.ps1 -GpuResearch
```

```bash
./bootstrap.sh --gpu-research
```

The GPU bootstrap requires `uv` because the checked-in lock contains hashes and
an exclusive source mapping for Torch. Do not replace it with
`pip install ".[gpu]"`: wheel metadata now requires the exact local version
`torch==2.14.0+cu126`, so a resolver without the official CUDA 12.6 index fails
closed, but Python package metadata still cannot publish the alternate index
itself. Do not use `--extra-index-url`, which would make PyPI and the Torch
repository peer sources.

Before touching the environment, the opt-in path refuses non-native x86-64
Windows/Linux hosts, missing or non-functional `nvidia-smi`, zero enumerated
NVIDIA GPUs, and drivers below the conservative CUDA 12.6.3 floors (Windows
561.17; Linux 560.35.05). The Linux experiment excludes WSL. The preflight
prints GPU names and driver versions and attempts the documented
`nvidia-smi` compute-capability query. That last query is advisory because it
is not supported uniformly by every driver/tool build: inability to report it
does not become invented proof either way. After installation, the exact Torch
build assertion, a bounded real CUDA tensor operation, and
`daedalus accelerators --deep --json` are the readiness evidence. Running
`uv sync --locked --all-extras` directly remains possible for maintainers, but
bypasses this host preflight.

CUDA 12.6 is intentional: the local GeForce MX330 is Pascal (compute
capability 6.1), while current CUDA 13 PyTorch wheels require Turing or newer.
The extra does not include cuVS or cuGraph: current RAPIDS releases require
compute capability 7.0+ and Windows execution through WSL2. Importability is
not a readiness claim; keep the deep accelerator probe and an actual bounded
device operation in the evidence for the machine being used.

Licensing is mixed: PyTorch, Newton, Warp and CuPy use permissive open-source
licenses, while CuPy's optional CUDA Toolkit component wheels carry NVIDIA's
proprietary software terms. The extra is an opt-in research environment, not a
redistribution grant or part of the desktop bundle.

## Execution and verification

At a high level:

```text
request
  -> route role and provider lane
  -> build a bounded task brief
  -> execute in the selected capability boundary
  -> derive the actual repository change
  -> run required verification/evidence gates
  -> accept, retain for review, roll back, or escalate
```

For local write paths, disk state is authoritative. A model saying that it
changed a file is not evidence that a file changed. The verifier compares real
state and applies syntax/format/project gates before acceptance.

### Three distinct policy gates

Do not collapse these into one generic “safety” switch; they read different
policy fields and have different defaults.

| Gate | Question | Predicate / default |
|---|---|---|
| **Data egress** | May these bytes leave for an untrusted API? | `classify_data`; fail-closed — content not allow-listed for egress is sensitive. |
| **Write confinement** | May a local writer put bytes on this path? | `path_write_blocked`; an empty `write_allow` is not an allow-list denial — configured denylists/high-risk rules still apply. |
| **Change risk** | Is this high-blast-radius work? | Risk classification decides whether a lower-trust/free lane may write or only review. |

Per-project policy is loaded from project configuration and `.agentenv` rather
than being inferred from documentation. High-risk and protected paths remain
explicit policy.

## Provider model

Daedalus can use local and frontier providers with different trust, cost and
write capabilities. The exact provider registry is code/config, not this page;
conceptually:

- **Local/Ollama** — no network egress, suited to cheap bounded work and review;
  writes remain policy- and verifier-gated.
- **Trusted frontier CLI lanes** — used for broader or higher-risk building when
  the configured trust boundary allows it.
- **Untrusted external advisory lanes** — egress-gated and not treated as
  authoritative writers.

Use the health/provider commands for the current installed capabilities rather
than inferring availability from documentation.

## File bridge and durable handoff

The compatibility backbone is the request/report file bus documented in
[`docs/COMMS_PROTOCOL.md`](docs/COMMS_PROTOCOL.md). Its `outbox/*.json` request
and `inbox/*.report.json` report contracts are preserved across refactors.

```powershell
python -m daedalus.file_bridge watch --repo-root <your-repo>
python -m daedalus.file_bridge enqueue "<task>" --project <name> --paths <file>
python -m daedalus.file_bridge status --project <name>
python -m daedalus.file_bridge mark-read --all
```

The watcher consumes `outbox/*.json`, writes `inbox/*.report.json`, and moves
processed work into run-state/evidence surfaces. Long task briefs should live in
the target repository and be referenced from the queue rather than duplicated
into a short transport objective.

Local mutable memory and retained evidence are intentionally different. A file
being under `runs/` or `memory/` does not by itself tell you whether it should be
committed; follow the repository's ignore/persistence policy and the owning
component's contract.

## VS Code and web surfaces

The shipped VS Code entry points currently render `agentOsHtml()`, an iframe
onto the React application in `apps/web/`. The older five-tab
`dashboardHtml`/Mission-Control design has no live caller and is retained only as
historical/reference material. See [`vscode-agent-env/DESIGN.md`](vscode-agent-env/DESIGN.md)
and the tombstone [`docs/MISSION_CONTROL.md`](docs/MISSION_CONTROL.md).

This distinction is intentional: do not implement features against the dead
five-tab template merely because the design document is detailed.

## Continuous bounded operation

Windows Task Scheduler support is documented in
[`docs/CONTINUOUS_DAEDALUS.md`](docs/CONTINUOUS_DAEDALUS.md). It schedules the
existing bounded loop with finite iteration, wall-clock, spend and retry limits;
it does not grant merge, promotion, Gate-closure, or owner-approval authority.

```powershell
powershell -ExecutionPolicy Bypass -File tools/continuous_daedalus.ps1 Install
powershell -ExecutionPolicy Bypass -File tools/continuous_daedalus.ps1 Status
```

## Chip-design workflows

The optional hardware-design surface is documented under
[`docs/chip-design/`](docs/chip-design/README.md). The package remains stdlib-only;
EDA tools are external capabilities.

```powershell
daedalus-chip status
daedalus-chip scan .
daedalus-chip lint --tool verilator --top top rtl/top.sv
daedalus-chip tcl vivado flow/build.tcl
```

`lint` and `tcl` are planning-only surfaces in G1-EDA-01; their raw `--live`
form is refused. The only admitted live Vivado surface is the project-aware
`daedalus-chip run` flow documented in
[`docs/chip-design/README.md`](docs/chip-design/README.md). A generated
bitstream, report, or GDS artifact is not by itself a pass signal: hardware
confidence is built through staged lint/elaboration, verification, synthesis,
timing, implementation/physical checks and retained receipts.

## Documentation discipline

[`docs/README.md`](docs/README.md) separates current docs, authority, backlog and
evidence. The short version:

- repair current docs when code moves;
- do not rewrite dated evidence to make it look current;
- archive superseded explanations and leave short compatibility pointers;
- keep one canonical explanation per contract and link to it elsewhere;
- do not hand-edit generated snapshots to force agreement with prose.

## License

See [LICENSE](LICENSE).
