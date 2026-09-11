# daedalus/accelerators.py

## 1. Size and shape

573 lines (`wc -l`). 1 class: `ComputeLane` (frozen dataclass, `daedalus/accelerators.py:44-55`).
10 top-level functions: `_has_module` (58), `_parse_nvidia_csv` (65),
`nvidia_hardware_status` (83), `deep_framework_status` (171),
`_redacted_endpoint` (200), `_remote_rtx_status` (209), `capability_lanes`
(284), `_remote_compute_status` (312), `_framework_rows` (379),
`accelerator_status` (409).

Module-level state: plain string env-var-name constants only —
`RTX_OLLAMA_ENV`/`RTX_TOKEN_ENV`/`RTX_TOKEN_FALLBACK_ENV`/`RTX_SSH_ENV`/
`RTX_SSH_FALLBACK_ENV`/`NVOF_SDK_ENV` (`accelerators.py:31-41`), and the
`_CC_FLOORS` dict of compute-capability floors (`accelerators.py:273-281`).
Two functions carry `@lru_cache(maxsize=1)` (`accelerators.py:82`,
`accelerators.py:170`) — process-lifetime memoized singletons for
`nvidia_hardware_status()` and `deep_framework_status()`, but the cache is
populated lazily on first call, not at import.

Module-level side effects at import time: **none**. No file reads, no env
reads, no subprocess/network calls, no registry mutation, no path creation
happen at module scope — every I/O op (`subprocess.run`, `os.environ.get`,
`urllib.request.urlopen`, `Path(...).exists()`) is inside a function body,
executed only when that function is called.

## 2. What it does

It answers three separable questions about optional NVIDIA/RTX compute
lanes — hardware visibility (`nvidia-smi`, local and via SSH to a
configured bench), software-backend readiness (torch/cupy/warp/cuvs/cugraph/
newton, probed in an isolated subprocess), and whether a ready backend is
actually applicable to a given Daedalus operation — and refuses to collapse
any of those into the others. It derives a `capability_lanes()` verdict from
raw compute-capability numbers so a pre-Volta/pre-Turing device is reported
as "unsupported: no such silicon" rather than "missing: go install
something." `accelerator_status()` assembles all of this plus a redacted
remote-Ollama probe into one JSON-serializable status payload with six named
`ComputeLane` rows (tensor inference, sparse graph/ANN, Warp kernels, Newton
physics, NVIDIA Optical Flow SDK, DLSS) and three top-level `claims` booleans
asserting hardware-visible/backend-ready/semantic-validity are distinct.

## 3. Who imports it (MEASURED)

Search covered `from daedalus.accelerators import`, `from daedalus import
accelerators`, `import daedalus.accelerators`, `from .accelerators import`,
`from . import accelerators`, `importlib.import_module("daedalus.accelerators")`,
and the bare string `"daedalus.accelerators"`, across daedalus/, tests/,
tools/, apps/, docs/, .claude/. Two hits were bare-string data, not imports
(`tests/test_budget.py:932`, `tests/test_host_predicate.py:430` — both list
`"daedalus/accelerators.py"` as a path string in an audit table) and one is
a docstring mention (`daedalus/sensitivity.py:656`), not an import.

**TOTAL real importer edges: 5** — 3 under `daedalus/`, 2 under `tests/`.

| Importer | Layer | Form |
| --- | --- | --- |
| `daedalus/cli.py:238` (`from .accelerators import accelerator_status`) | interfaces/cli (flat today) | DEFERRED — inside `_accelerators()` |
| `daedalus/interfaces/http/read.py:9-10` (`from ... import (accelerators, ...)`) | interfaces/http | MODULE-LEVEL |
| `daedalus/web_api.py:22-23` (`from . import (accelerators, ...)`) | flat, functions as interfaces/http host | MODULE-LEVEL |
| `tests/test_accelerators.py:6` (`from daedalus import accelerators`) | tests | MODULE-LEVEL |
| `tests/test_unbounded_security_floor.py:20` (`from daedalus import accelerators`) | tests | MODULE-LEVEL |

## 4. What it imports (MEASURED)

Zero `daedalus.*` imports anywhere in the file. Third-party/stdlib only:
`dataclasses`, `functools.lru_cache`, `importlib.util`, `json`, `os`,
`pathlib.Path`, `shutil`, `subprocess`, `sys`, `typing.Any`, `urllib.error`,
`urllib.parse`, `urllib.request` — all stdlib, all module-level
(`accelerators.py:16-28`). No third-party package dependency.

## 5. Proposed destination

**foundation** — confidence medium.

The module is a self-contained leaf: zero internal `daedalus.*` coupling,
every fact it reports is derived from subprocess/env/filesystem probes it
owns outright, and it is consumed only by outer report/status surfaces
(CLI subcommand, two HTTP read paths) that display its payload verbatim. It
never touches kernel/spine/twin/orchestration state and holds no mutable
process singleton beyond a memoized read-only probe result. That profile —
zero-dependency, broadly-readable evidence utility — matches the existing
FOUNDATION set (`atomic`, `budget`, `config`, `limit_policy`, `primary_tree`,
`sensitivity`, `storage`) better than any effectful layer.

The alternative is **runtimes**: the module's *subject matter* (CUDA/RTX
compute-lane readiness for optional GPU acceleration) is domain-adjacent to
`daedalus/runtimes/`, which owns provider execution and fault/receipt
machinery. But measured coupling argues against it — `daedalus/runtimes/`
is built around provider-invocation contracts and receipt ledgers that
`accelerators.py` shares zero imports with, and moving it there would be a
name-based, not an edge-based, decision.

What would change my mind: if a future work packet gives `daedalus.runtimes`
its own capability-probe contract that `accelerator_status()` is expected to
implement or feed, the domain argument would dominate the dependency
argument and runtimes would become the better fit.

## 6. Boundary-rule check after the move

(a) If moved to `foundation`: no rule in `docs/architecture/import-boundaries.json`
names `foundation` as a `source_prefixes` entry, so there is nothing to be
refused by a rule as written today. Independently, the module's own import
list is empty of `daedalus.*` targets (section 4), so no allowlist anywhere
— including the strictest ones — could refuse anything it actually does.

(b) No rule names `daedalus.accelerators` (or a prefix that would match it)
in any `forbidden_target_prefixes` or `allowed_target_prefixes` list across
all four rules. Moving it under a package changes nothing here because it
was never named by prefix in the first place.

(c) Hypothetically landing it in kernel/spine/twin: since it imports zero
`daedalus.*` modules, the ALLOWLIST nature of those three rules is moot for
this module — there is no flat import to enumerate against an allowlist.
(This is true only because of measured section-4 emptiness; it would not
hold if the module later grew an internal dependency.)

## 7. Dead-code signals

Not applicable — importer count is 5, not 0, and none of the importers are
test-only (2 of 5 are production code paths: `cli.py`, `interfaces/http/read.py`,
plus `web_api.py`). Also reachable as a `daedalus` console-script subcommand:
`pyproject.toml:78` registers `daedalus = "daedalus.cli:main"`, and
`daedalus/cli.py:1181-1182` dispatches `daedalus accelerators` to this
module. **Label: LIVE.**
