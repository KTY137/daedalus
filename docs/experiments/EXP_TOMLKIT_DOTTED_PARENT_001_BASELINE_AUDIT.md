# EXP-TOMLKIT-DOTTED-PARENT-001 baseline audit

Status: **invalidated before activation; zero candidate evaluations**

Classification: **EXPERIMENT**

Active delivery gate: **Gate 0 — Canonical Kernel**

Audited: **2026-08-03**

This is retained negative harness evidence for
`EXP-TOMLKIT-DOTTED-PARENT-001`. It does not change the frozen task, start the
experiment, close a delivery gate, or authorize promotion. No model call and no
candidate mutation occurred during this audit.

## Source identity

The audit used only the frozen source inputs recorded by the experiment:

- TOMLKit commit `d8ed1e3cdb024dfc2c6f12b45a0dfd4d4d91f727`, tree
  `1af692f3944e67c7de962dc8094faf184ec3427f`;
- `toml-test` gitlink commit
  `08ed8697864548b3cdb4b8decbf496bef47e1c82`, tree
  `4b9ff71fa2de930104473805a662117f5b38ea87`;
- byte-reproducible source archives SHA-256
  `9184035b8a186089bad9ad8e3f09568182dbe43827b613f01ff269e84bbe996f`
  and
  `0f3361e8b21f03bbf224647c2c541dc5732da42fca4a11c18fe174204be17434`;
- canonical materialized file-tree SHA-256
  `eb005fd9cc49320d347dac24fb03498f596cbe60be72b43a798f78916ed3f646`;
- `poetry.lock` SHA-256
  `7c0e9b4cc541b2b1176225c1e05c3db88967aac3a5069563810f85e9a5468c8d`.

The main and submodule archives were published through the existing canonical
Artifact Store. Their locator digests are retained in the parent experiment
document. The materialized tree contains no `.git` directory.

## Baseline environment

The dependency environment used CPython 3.10.11 and the exact package versions
from the pinned Poetry lock, installed with Poetry 2.1.3 through `uv` 0.11.26.
`uv pip check` reported all 48 installed packages compatible.

The first setup command ended with exit code 1 after successful installation
because it incorrectly invoked `python -m pip check` in a `uv` environment that
does not contain the `pip` module. The environment was not recreated or
silently relabelled. The correct environment-native `uv pip check --python
<venv-python>` then passed. This setup-command defect is retained as harness
evidence and is not a product failure.

## Results

### Upstream behavioral baseline — pass

Command shape:

```text
<py310-venv> -m pytest -q -p no:cacheprovider
```

Environment pins included `PYTHONDONTWRITEBYTECODE=1` and
`PYTHONHASHSEED=0`. Result:

```text
1051 passed in 9.58s
exit 0
```

This proves that the materialized pinned baseline passes its complete checked-in
pytest suite, including the pinned `toml-test` tree.

### Public semantic defect — reproduced

The first oracle attempt correctly failed before evaluation: CPython 3.10 has
no standard-library `tomllib`. The audit did not substitute an undeclared
backport. It instead bound the independent oracle to the already installed
CPython 3.12.13 standard library:

| Oracle component | SHA-256 |
| --- | --- |
| CPython 3.12.13 executable | `88b9e780cfdc38597c7f53e20f7165262befa28d9a5e9470360d349e172ecf37` |
| `tomllib` library tree | `3f7940b9b3995b704ff3e85d520c1622b79f4d40a2e0b2482811a2c4002c41fb` |
| canonical oracle toolchain | `21f5defc4beb91a7a4673c6cb8b51cddb033f6fc05c31e3cd9d84d6f50a2fa26` |

The loaded `tomlkit.__file__` was inside the exact materialized source tree.
The public parse → mutate → serialize → independent parse chain produced:

```toml
[t]
a.b = 1

[a.c]
```

Output SHA-256:
`b20703b96b2b25d87d95d06156f9a8713904e73436de7840bb16b366e683a096`.
The independent semantic value was
`{"a":{"c":{}},"t":{"a":{"b":1}}}`, not the required value under
`t.a`; the top-level `a` was present and `[t.a.c]` was absent. The real defect
is therefore reproduced without a mock, canned response, or external solution.

### Frozen absolute type gate — baseline fail

Command shape:

```text
<py310-venv> -m mypy tomlkit tests
```

Result: exit 1, 30 errors in 5 files. Six diagnostics are in TOMLKit source;
the remainder include the pinned `toml-test` generator. Examples include
missing generic parameters, an untyped local, Python-3.10-incompatible
`typing.Self`, and strict-mode diagnostics in `tests/toml-test/gen.py`.

### Frozen warning-as-error documentation gate — baseline fail

Command shape:

```text
<py310-venv> -m sphinx -W --keep-going -b html docs <external-output-dir>
```

Result: exit 1. Sphinx 4.5.0 completed the HTML build but retained four
warnings/errors for the `register_encoder` docstring (two unexpected
indentation errors and two block/definition-list warnings).

## Decision

Experiment 001 required the strict type check and warning-as-error documentation
build to be absolutely green for every passing candidate. Its unchanged frozen
baseline fails both gates. Counting every candidate as a failure would measure
pre-existing evaluator incompatibility, not repair quality; weakening either
gate after observing these results would violate the frozen protocol.

Therefore Experiment 001 is invalidated before activation and must not consume
any of its 26 candidate-evaluation budget. A successor needs a new experiment
ID and a new pre-registration. It may retain these diagnostics as a
baseline-parity/no-new-regression comparison, while keeping the green upstream
suite, packaging checks, source identity, independent semantic oracle, hidden
task corpus, equal budgets, isolation, and no-promotion rules unchanged.

Iron Plan: EXPERIMENT

Iron Gate: 0

Evidence: exact source/submodule/CAS identities; 1051-pass upstream baseline;
real local-source semantic defect reproduction; retained Python-3.10 oracle
failure; 30-error mypy baseline; four-warning/error Sphinx baseline; zero
candidate evaluations.
