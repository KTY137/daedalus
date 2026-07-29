# ADR-019: Guards Are Six Predicates Over One Noun

## Status

**Proposed**, 2026-07-29. Raised by Kaya, who asked the right question after the
third policy leak in one week: *"Eventuell haben wir auch ein policy/ruling
chaos das diese ganzen leaks erzeugt."*

The answer is yes, and this ADR states its exact shape. It records a **finding
and a direction**, and deliberately does not authorise the refactor — the fix
touches the safety core, and a rushed rewrite there is worse than the defect.

## Provenance

**MEASURED** = read from the code and/or produced by a command on this box on
2026-07-29. **ASSUMED** is labelled where it appears.

## The finding

Six predicates decide over the same nouns (a path, a lane, some content). Each
reads a **different subset** of the same `Policy` object.

| predicate | axis | normaliser | policy fields it reads |
|---|---|---|---|
| `secret_floor_rule` | unconditional floor | own | *none* (hard-coded) |
| `classify_data` / `_path_is_sensitive` | egress | `_norm` | `deny`, **`allow`**, **`allow_exceptions`**, **`default_deny`**, `deny_content` |
| `path_write_blocked` | write | `_norm` + `_fence_norm` | `deny`, `high_risk_paths`, (now) `write_allow` |
| `change_risk` | routing | `_fence_norm` | `high_risk_paths`, `high_risk_terms`, `mid_risk_terms` |
| `slice_egress_rule` | slice egress | delegates | floor + `classify_data` |
| `lane_for_host` | network | own | *none* |

**Three policy fields are read by exactly one of the six** — `allow`,
`allow_exceptions`, `default_deny` (MEASURED). They are the egress axis and
nothing else.

### What that cost, concretely

`docs/PROPOSED_SELF_POLICY.md` proposed a policy for this repo and claimed:

> "The ONLY paths a candidate patch may touch. Everything else is denied by
> `default_deny`, so this list is the whole permission."

Measured against `path_write_blocked` — the function the local write lane
actually calls — **8 of 12 paths the document claimed to deny were writable**:

```
WRITABLE  daedalus/core.py        WRITABLE  daedalus/cli.py
WRITABLE  daedalus/offload.py     WRITABLE  daedalus/health.py
WRITABLE  daedalus/router.py      WRITABLE  daedalus/config.py   <-- loads the policy
WRITABLE  daedalus/providers/ollama.py      WRITABLE  pyproject.toml
```

The field existed, the JSON carried it, `load_policy` parsed it, and the write
guard never looked at it. No test could catch this, because no test ever
claimed `allow` governed writes. **A document described a fence the code did
not have** — the ninth instance of this repo's recurring defect.

### The second half: four normalisers

`_norm` exists in `sensitivity.py` **and** `router.py`; `_fence_norm` exists in
`sensitivity.py` **and** `structcore/graph.py` (MEASURED, four definitions).
Two parsers for one question is the classic bypass class, and this repo has
already paid for it once: a slash-anchored `/controller` structurally could not
match the repo-relative `controller/core.py`, so a literally-fenced top-level
file scored `low` and reached the local write lane.

## What is genuinely right, and must survive any refactor

1. **The unconditional floor.** `secret_floor_rule` runs in every lane with no
   bypass and no policy input to weaken it. This is the correct pattern.
2. **Union, never replace.** `load_policy` always unions `GENERIC_DENY_SUBSTRINGS`
   and `GENERIC_HIGH_RISK_PATHS` in, so a repo-local policy can extend the floor
   and can never remove it. A real safety property, correctly implemented.
3. **Capability over predicate.** The gate's containment does not ask whether a
   path is allowed; the child holds one bounded handle via
   `PROC_THREAD_ATTRIBUTE_HANDLE_LIST` and structurally cannot reach outside.
   Measured in the drill: the child **exits 0** and the canary outside its
   worktree survives. **This layer has never leaked.** Every leak found so far
   came from the string-predicate layer.

## Decision

**Accept the finding. Do not refactor yet.** Three things are decided now:

1. **An allow-list for writes is a separate, opt-in field** (`write_allow`),
   not a reuse of the egress `allow`/`default_deny`. Reusing them would have
   silently confined every other repo's write lane the moment it shipped —
   the same conflation that caused the bug. Empty means unconfined, which is
   byte-identical to previous behaviour.
2. **Allow-lists match by root-anchored prefix, deny-lists by substring.** A
   loose match in a deny list errs toward blocking (safe); the same loose match
   in an allow list errs toward permitting (unsafe). `"docs/"` as a substring
   admits `evildocs/payload.py`; as an anchored prefix it does not. Both cases
   are pinned in `tests/test_self_policy_confinement.py`.
3. **Confinement narrows and never widens.** With `write_allow` set, the
   `*_simulated.py` exemption is disabled — a repo opting into confinement is
   asking for fewer exemptions, not more.

## Direction (NOT yet authorised)

The target shape, for when someone has a clear week and an adversarial reviewer:

- **One decision point, many enforcement points** (the PDP/PEP split from
  XACML/Cedar/OPA). One `verdict(path, action, lane, policy) -> Verdict` that
  evaluates every field exactly once; the six call sites become thin. A new
  policy field then takes effect everywhere instead of silently doing nothing in
  five of six paths.
- **Canonicalise once, at the boundary.** `OllamaProvider._resolve` already does
  the right thing — it returns a resolved repo-relative path and raises on
  escape. One normaliser should apply from there inward. Four is three too many.
- **Demote the string layer to defence-in-depth.** The boundary should be the
  capability: a writer that holds no rights outside its worktree. Then a hole in
  a substring list is a bug, not an incident.

**ASSUMED**, and the reason this is not authorised here: the refactor is
mechanical in appearance and load-bearing in fact. Every one of the six
predicates has callers that depend on its exact current answer, and the way to
find that out is not to discover it in production.

## Consequences

- `write_allow` is live in `.agentenv/agentenv.json` for this repo, authorised
  by Kaya on 2026-07-29.
- The red-when-disabled receipt is recorded in
  `tests/test_self_policy_confinement.py::test_general_source_is_blocked`:
  disabling the confinement fails 9 tests, and **6 of the 8** named paths leak.
  The two that stay blocked — `offload.py`, `config.py` — are caught by
  `high_risk_paths`, which is the measurement showing belt-and-braces does real
  work rather than restating `write_allow`.
- `docs/PROPOSED_SELF_POLICY.md` has been corrected; its central claim was
  false and is now labelled as such rather than deleted, because the mistake is
  the more useful artefact.
