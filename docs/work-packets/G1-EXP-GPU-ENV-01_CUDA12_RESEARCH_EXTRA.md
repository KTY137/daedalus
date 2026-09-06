# G1-EXP-GPU-ENV-01 - CUDA 12 research environment extra

Packet ID: `G1-EXP-GPU-ENV-01`
Artifact role: `primary`
Status: `implemented locally; integration hardened; no-promotion resource budget exceeded`
Active gate: `1`
Classification: `EXPERIMENT`
Owner: `repository owner`
Base revision: `61cd1f3e8eca1d02cd9ddeb734f4c112c69c29a0`
Dependencies: `G1-EXP-TENSOR-GPU-01`, `G1-EXP-TENSOR-GPU-02`, and the
officially published CUDA 12 wheels named below
Master-plan authority: `Revision 11`, digest
`711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2`
Promotion: not requested; automatic merge, promotion, and Gate transition are
forbidden
Expiry: `2026-12-04`, or immediately if the pinned CUDA 12 wheels stop
supporting the declared Python/platform matrix or fail the CUDA oracle

## Primary acceptance claim

Daedalus can offer one explicit, removable `gpu` research extra that installs
PyTorch, Newton/NVIDIA Warp, and CuPy on supported NVIDIA hosts without adding
anything to the zero-dependency production core, silently selecting a GPU
backend, or claiming that a visible GPU or successful import is useful compute.

The local owner-requested measurement targets Windows 11 x86-64, CPython 3.13,
an NVIDIA GeForce MX330 (compute capability 6.1), driver 581.83, and 2 GiB VRAM.
Because current CUDA 13 PyTorch and RAPIDS binaries exclude Pascal, the frozen
stack uses CUDA 12.6 PyTorch and excludes cuGraph/cuVS. Newton and Warp remain
physics/custom-kernel research tools, never general code semantics or a new
runtime authority.

## Scope

Allowed changes are exactly:

- `pyproject.toml` (optional dependency/source metadata only; core dependencies
  stay empty);
- `uv.lock` (mechanically regenerated dependency lock);
- `bootstrap.ps1` and `bootstrap.sh` (an explicit opt-in flag only);
- `README.md` (installation and hardware-limit documentation);
- `tests/test_gpu_extra_contract.py` (offline packaging/refusal contracts);
- `docs/work-packets/G1-EXP-GPU-ENV-01_CUDA12_RESEARCH_EXTRA.md`; and
- `docs/work-packets/index.json` (canonical registry render only if the
  independent tracked registry baseline is green).

Every production module, chat/settings surface, kernel contract, policy,
evaluator, store, effect entrypoint, generated distribution, Master Plan,
amendment record, and existing Work Packet is forbidden. This packet adds no
runtime selector, service, scheduler, semantic plane, state store, automatic
download at application runtime, merge, or promotion path.

## Contracts and behavior

The optional `gpu` extra freezes these packages for the experiment:

- `torch==2.14.0+cu126`, resolved by uv from PyTorch's explicit CUDA 12.6
  wheel index; the local version in published metadata makes an index-free pip
  install fail instead of selecting the incompatible CUDA 13 build;
- `newton==1.5.1` plus its directly relied-on `warp-lang==1.17.0` runtime; and
- `cupy-cuda12x[ctk]==14.2.0` plus the exact
  `cuda-toolkit[cublas,cudart,cufft,curand,cusolver,cusparse,nvrtc]==12.6.3`
  component set on native Windows/Linux, so a system CUDA Toolkit is not a
  prerequisite.

The PyTorch CUDA 12.6 index is explicit: it may supply `torch`, not become a
general fallback package source. The GPU bootstrap requires uv and performs
`uv sync --locked --all-extras`, preserving every declared development extra
while enforcing the checked-in wheel sources and hashes. It then refuses if
the installed Torch build or `torch.version.cuda` changed, no CUDA device is
enumerated, or a bounded 256-element CUDA arithmetic/readback oracle differs.
This path is used only when the owner supplies `-GpuResearch` /
`--gpu-research`; default bootstrap continues to install only the existing
YAML extra through pip. Installation happens during bootstrap or an explicit
development sync, never while Daedalus is running.

Before creating a virtual environment or starting the multi-gigabyte sync, the
GPU flag admits only native x86-64 Windows or Linux. It refuses ARM/emulated
processes, WSL, a missing or non-functional `nvidia-smi`, an empty NVIDIA GPU
inventory, and drivers below the conservative CUDA 12.6 Update 3 floors:
Windows `561.17`, Linux `560.35.05`. The floors come from NVIDIA's frozen
[CUDA 12.6.3 release notes](https://docs.nvidia.com/cuda/archive/12.6.3/cuda-toolkit-release-notes/index.html).
The preflight prints GPU and driver identity. It also attempts NVIDIA's
documented
[`compute_cap` query](https://docs.nvidia.com/cuda/cuda-programming-guide/05-appendices/compute-capabilities.html),
but treats an unavailable field as unknown rather than proof of compatibility
or incompatibility: the exact installed Torch probe, real device operation,
and final Daedalus deep probe remain authoritative. A maintainer can still run
uv directly, but that explicitly bypasses this bootstrap host preflight.

The canonical `daedalus accelerators --deep --json` probe remains the runtime
inventory truth surface. Import success is insufficient: it distinguishes
module presence from CUDA device enumeration and explicitly leaves Newton
unverified because that status probe does not execute a solver step. Separate
acceptance evidence requires small bounded device operations and exact
CPU-visible results. Those oracles have a budget of at most 256 MiB device
memory and 60 seconds per framework, with no model/provider call and no paid
service. Dependency resolution/download has an 8 GiB disk-growth ceiling and a
30 minute wall-time ceiling on this host.

cuGraph and cuVS stay absent: their current wheels are Linux/WSL-oriented and
RAPIDS 24.02+ requires compute capability 7.0, while this host is Pascal 6.1.
Their absence is retained negative evidence, not repaired with an unsupported
source build or a second environment. Tensor-Core use is not claimed because
the MX330 has no Tensor Cores. No speedup claim is in scope.

## Acceptance matrix

1. `project.dependencies` remains exactly empty and a normal editable install
   does not resolve Torch, Newton, Warp, CuPy, CUDA components, cuVS, or
   cuGraph.
2. The GPU bootstrap refuses unsupported architecture, WSL, missing
   `nvidia-smi`, zero GPUs, and below-floor drivers before virtual-environment
   creation or `uv sync`; the default path runs none of those checks.
3. `uv lock --check`, `uv sync --locked --all-extras`, and `uv pip check` pass
   on the declared Windows/Python host without a system CUDA Toolkit.
4. Default bootstrap remains byte-for-byte equivalent in dependency intent;
   only the explicit GPU flag installs the multi-gigabyte research stack.
5. PyTorch reports the exact installed build/index, `cuda.is_available()`, the
   device name and capability, compiled architecture list, and passes a bounded
   CUDA tensor arithmetic/matmul oracle with synchronized readback.
6. Warp reports its version, CUDA toolkit/driver view and `cuda:0`, then a
   bounded launched kernel produces the expected host-visible values.
7. Newton imports with its version and finalizes one minimal model on the same
   CUDA device; no simulation-performance or semantic-validity claim follows.
8. CuPy reports its version/runtime/device and a bounded array operation equals
   the CPU oracle. If toolkit component coexistence fails, CuPy is removed from
   the extra and the failure is retained rather than weakening the oracle.
9. `daedalus accelerators --deep --json` truthfully separates hardware,
   import/device-enumeration, unverified Newton execution, and semantic
   readiness. Separate retained oracles establish active-kernel evidence;
   cuVS/cuGraph remain absent and the MX330 is never described as Tensor-Core
   hardware.
10. Offline packaging/refusal tests pass and reject a non-empty core, a
   non-explicit Torch index, CUDA 13/default Torch resolution, default GPU
   bootstrap installation, ARM, missing NVIDIA tooling, empty GPU inventory,
   or RAPIDS dependencies.
11. `python tools/index_work_packets.py --check` passes only after the existing
    independent post-index artifact defect is separately resolved; this packet
    must not edit that artifact or conceal the prior red baseline.

## Migration and rollback

There is no production-data migration. Rollback removes the `gpu` optional
extra, explicit uv index/source mapping, bootstrap flags, README section,
offline contract test, this Work Packet and its registry entry, then regenerates
`uv.lock`. Locally installed packages may be removed by recreating `.venv` or
syncing without the extra; no user project, ledger, evidence, or model data is
deleted automatically.

## Evidence expected failures and review

Baseline on 2026-09-04: `.venv` uses CPython 3.13.14; none of `torch`, `warp`,
`newton`, `cupy`, `cuvs`, or `cugraph` is importable; NVIDIA reports GeForce
MX330, compute capability 6.1, driver 581.83, 2048 MiB total and 1597 MiB free
VRAM; the environment occupies 254312 bytes before the extra. The C: volume has
62.82 GiB free.

At the frozen base the tracked Work Packet registry was red because
`G1-EXP-FOURFOLD-HYBRID-01.json` lacked the post-index `artifact_role`. That
historical blocker is retained here; a separate aligned repair later restored
the tracked registry without altering this experiment's primary claim.

Expected experimental failures include a missing Pascal architecture in the
selected Torch wheel, driver/runtime incompatibility, Warp JIT refusal, Newton
API/version drift, CuPy CUDA-component collision, or 2 GiB VRAM exhaustion.
Each failure blocks only this extra and is retained with exact output. It does
not authorize a source build, CUDA 13 fallback, WSL/RAPIDS install, backend
selection, production promotion, or performance claim.

Independent review should verify the zero-dependency core, explicit-index
isolation, package license/source identity, absence of runtime downloads and
production imports, bootstrap default behavior, bounded real-device oracles,
RAPIDS refusal, exact lock diff, registry-baseline honesty, and that removing
this packet leaves no production behavior behind.

Builder verification on 2026-09-04:

- `uv lock` resolved 104 packages. `uv sync --all-extras` installed every
  declared extra (`yaml`, `math`, `polyglot`, `root`, `orchestration`, `gpu`,
  and `test`); `uv pip check` checked 83 installed distributions and reported
  all compatible.
- Installed versions include Torch `2.14.0+cu126`, Newton `1.5.1`, Warp
  `1.17.0`, CuPy `14.2.0`, CUDA Toolkit component meta-package `12.6.3`, NumPy
  `2.5.2`, SciPy `1.18.1`, NetworkX `3.6.1`, PyYAML `6.0.3`, Tree-sitter
  `0.26.0` plus the pinned Rust/Java/C++ grammars, uproot `5.7.5`, LangGraph
  `1.2.11`, and pytest `9.1.1`.
- The built wheel has no unconditional `Requires-Dist`. It exposes the `gpu`
  extra with exactly the five marker-bound requirements above. The wheel was
  written outside the repository to a dedicated local temporary directory.
- Torch reports CUDA `12.6`, MX330 capability `(6, 1)`, and compiled arches
  `sm_50, sm_60, sm_61, sm_70, sm_75, sm_80, sm_86, sm_90`. Exact elementwise
  and 16x16 identity-matmul oracles passed on `cuda:0`; the latter allocated
  8,522,752 bytes.
- Warp reports its bundled CUDA Toolkit `12.9`, driver view `13.0`, MX330
  `sm_61`, and launched the installed ten-element SAXPY example on `cuda:0`;
  exact host readback passed after synchronization.
- Newton finalized a one-particle model on `cuda:0`; one
  `SolverSemiImplicit` step with zero gravity, unit x velocity and `dt=0.125`
  produced position `[0.125, 0.0, 0.0]` within absolute tolerance `1e-7`.
- CuPy reports runtime `12090`, driver `13000`, capability `61`, and passed an
  exact 1024-element device arithmetic/readback oracle. It emits a retained
  warning that a system `CUDA_PATH` was not detected; the component wheels
  nevertheless executed successfully without a system toolkit.
- PowerShell parsed `bootstrap.ps1`; Git Bash `bash -n` accepted
  `bootstrap.sh`; the first attempted WSL `bash -n` was invalid evidence because
  no WSL distribution is installed and is retained as such. Focused offline
  tests are now `26 passed` across `tests/test_gpu_extra_contract.py` and
  `tests/test_accelerators.py`.
- `.venv` grew from 254,312 bytes to 6,748,830,610 logical bytes (6.285 GiB).
  C: free space fell from 62.82 GiB to 53.36 GiB while this and the concurrent
  repository session ran. That conservative machine-global delta is 9.46 GiB
  and exceeds the packet's 8 GiB download/install ceiling; no post-hoc budget
  widening is claimed. The uv cache totals 10,334,006,206 bytes but its
  pre-experiment size was not measured, so its attributable growth is unknown.
- Historical red observation, retained from before `G1-ACCEL-01`:
  `deep_framework_status()` could not parse `_DEEP_PROBE` output after Warp
  wrote initialization text to stdout, returned only an `invalid probe output`
  row, and projected all six frameworks as uninstalled. The separate aligned
  accelerator-truth packet repaired that parser without changing this
  experiment's primary claims or budget outcome.
- The earlier tracked Work Packet registry defect was repaired separately and
  `tools/index_work_packets.py --check` now passes for the tracked set. This
  local packet is still untracked and therefore intentionally absent from that
  Git-authoritative index until an owner stages it; no green registry claim is
  made for this packet itself.

Integration hardening after independent review on 2026-09-04:

- Published metadata now requires `torch==2.14.0+cu126`. Without the exclusive
  official index a conventional pip resolver fails closed; it cannot silently
  substitute CUDA 13 on Pascal.
- Warp and the CUDA Toolkit component meta-package are direct exact pins. The
  lock retains wheel hashes and the exclusive Torch source. Both bootstrap
  scripts now require that lock for the GPU path, while default bootstrap stays
  dependency-light.
- `uv sync --locked --all-extras --dry-run` resolved 104 packages, checked 83
  installed distributions, and proposed no environment changes. This replaces
  the earlier misleading `uv sync --extra gpu` instruction that would have
  removed unrelated development extras under uv's exact-sync semantics.
- Offline contracts now compare the exact GPU requirement set, inspect the
  root lock metadata plus hashes for the five directly relied-on packages, and
  pin the README/bootstrap fail-closed behavior. The accelerator projection
  says `Newton device execution was not probed` rather than claiming the
  installed Newton/Warp packages are missing.
- The README now discloses that CuPy's CUDA component wheels include NVIDIA
  proprietary-licensed software. This does not grant redistribution through
  the desktop package.
- Adversarial preflight hardening now runs before `.venv` creation and uv sync.
  On the measured host it printed MX330, driver `581.83`, and compute capability
  `6.1`; the post-install exact Torch assertion then passed a bounded real CUDA
  operation. Git Bash running the Linux bootstrap on Windows refused with exit
  `2` before installation. Offline fixtures execute the actual Linux preflight
  functions and prove ARM, missing-`nvidia-smi`, and empty-inventory refusal;
  static contracts cover the equivalent Windows gates and ensure both calls
  precede environment creation and sync.
- The original 9.46 GiB machine-global delta still exceeds the predeclared
  8 GiB ceiling. Hardening does not retroactively widen it; promotion remains
  forbidden.

Iron Plan: **EXPERIMENT**
Iron Gate: **1**
Automatic merge or promotion: **forbidden**
