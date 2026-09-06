"""contracts.py -- the six Gate-3 freeze obligations as typed, digest-bound artifacts.

Plan §11, Gate 3, sentence 1:

    First freeze public tasks, evaluator versions, budgets, model/hardware
    reporting, seed policy, and statistical reporting.

Each of those six becomes exactly one frozen dataclass here, and ``RunManifest``
binds all six plus the base revision. **The manifest is the seal.** A run whose
manifest is incomplete reports ``sealed=False``; nothing in this package can set
``sealed=True`` on a run that is missing any obligation, because the flag is
derived (``RunManifest.sealed``), never assigned.

EXPERIMENT (packet G3-BASE-01). The active delivery gate is 1. This package is
Gate-3 prework prototyped under plan §11's later-gate allowance; it does not
open, enter, or satisfy Gate 3, and a value produced here is not Gate-3 baseline
evidence until an owner seals the harness.

Design rules inherited from measured failures in this repository -- see
``docs/GATE2_FOREST_V2_TRIAGE.md`` and packet §3:

* An absent measurement is ABSENT, never a zero. ``TrialResult`` carries no
  score field at all when a trial errored, so an aggregator that forgets to
  filter raises ``KeyError``/``AttributeError`` instead of averaging a
  placeholder. This mirrors ``daedalus.eval.harness``'s ``_task_error_row``.
* A counter that cannot be non-zero is not a measurement. Every count here is
  derived from a collection whose emptiness is itself reportable.
* The denominator is frozen before the run (``FrozenTaskSet.counting_rule``)
  and hashed into the manifest, so it cannot be chosen after seeing a result.
"""
from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Sequence

# The four planes of the Project Twin (plan §5). Used by the label-plane census
# so a task set cannot silently be single-plane while claiming to test a
# cross-plane hypothesis (packet rule R3).
PLANES = ("code", "type", "data", "knowledge")


class FreezeError(ValueError):
    """A freeze obligation was violated. Always raised, never returned as a
    flag -- a caller that ignores a return value must not be able to proceed
    with an unfrozen artifact."""


def canonical_digest(payload: object) -> str:
    """sha256 over canonically serialized ``payload``.

    Canonical means: sorted keys, no insignificant whitespace, UTF-8, and
    ``ensure_ascii=False`` so the digest is stable across platforms and does not
    change merely because a value contains a non-ASCII character. Matches the
    canonical-serialization posture of ``daedalus.kernel.contracts``.
    """
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# --------------------------------------------------------------------------- #
# 1. public tasks                                                             #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class FrozenTaskSet:
    """The frozen public task set: which tasks, counted how, labelled where.

    ``counting_rule`` is free text but MANDATORY and hashed: it is the
    denominator, declared before the run (packet rule R4). The Forest-v2
    pre-study's own honest caveat is the precedent -- "the later experiment must
    report its gain against this same counting rule, not against a friendlier
    denominator" (``experiments/forest_v2/README.md``).

    ``label_plane_census`` maps plane -> number of tasks whose gold labels live
    in that plane. It must sum to ``len(task_ids)``; a census that does not
    balance is a lost category, and this repository has already shipped one
    metric ruined by exactly that (triage doc, s04).
    """

    name: str
    task_ids: tuple[str, ...]
    counting_rule: str
    label_plane_census: Mapping[str, int]

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise FreezeError("frozen task set needs a name")
        if not self.task_ids:
            raise FreezeError(f"task set {self.name!r} is empty")
        if len(set(self.task_ids)) != len(self.task_ids):
            dupes = sorted({t for t in self.task_ids
                            if list(self.task_ids).count(t) > 1})
            raise FreezeError(f"task set {self.name!r} repeats task ids: {dupes}")
        if not self.counting_rule.strip():
            raise FreezeError(
                f"task set {self.name!r} has no counting_rule -- the denominator "
                "must be declared before the run, not chosen after it")
        unknown = sorted(set(self.label_plane_census) - set(PLANES))
        if unknown:
            raise FreezeError(
                f"task set {self.name!r} census names non-planes {unknown}; "
                f"the four planes are {list(PLANES)}")
        total = sum(self.label_plane_census.values())
        if total != len(self.task_ids):
            raise FreezeError(
                f"task set {self.name!r} census sums to {total} but has "
                f"{len(self.task_ids)} tasks -- a lost category corrupts every "
                "rate computed from it")
        # Defensive copy behind a read-only proxy. Without it the caller keeps
        # a live reference to the dict they passed in, and mutating it later
        # silently changes .digest on an object whose whole purpose is being
        # frozen. An independent reviewer demonstrated exactly that.
        object.__setattr__(self, "label_plane_census",
                           MappingProxyType(dict(self.label_plane_census)))

    @property
    def digest(self) -> str:
        return canonical_digest({
            "name": self.name,
            "task_ids": list(self.task_ids),
            "counting_rule": self.counting_rule,
            "label_plane_census": dict(self.label_plane_census),
        })

    @property
    def planes_present(self) -> tuple[str, ...]:
        """Planes with at least one gold label."""
        return tuple(p for p in PLANES if self.label_plane_census.get(p, 0) > 0)

    def require_cross_plane(self) -> None:
        """Packet rule R3. Refuse this task set for a cross-plane comparison
        when every gold label sits in one plane.

        This is the s08 defect made mechanical. That slice compared cross-plane
        fusion against four separate indices on 600 queries whose gold labels
        were 100% code documents -- a setup in which no cross-plane retriever
        can win, because the answer is only ever in one plane. The measured
        conclusion ("four independent indices are strictly inferior") was an
        artifact of the arrangement, and it fired a plan §14 kill criterion on a
        question the setup could not actually ask.

        Refusing loudly is the whole point: a structurally impossible comparison
        must not be run and then reported as a finding.
        """
        present = self.planes_present
        if len(present) < 2:
            raise FreezeError(
                f"task set {self.name!r} has gold labels in only {present or ('none',)} "
                "-- a cross-plane hypothesis cannot be tested against a "
                "single-plane label set. Any cross-plane arm would lose "
                "structurally, not empirically (see G3-BASE-01 rule R3 and the "
                "s08 finding in docs/GATE2_FOREST_V2_TRIAGE.md).")


# --------------------------------------------------------------------------- #
# 2. evaluator versions                                                       #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EvaluatorVersion:
    """Identity of the thing that decides whether a trial succeeded.

    ``code_digest`` is the digest of the evaluator's own scoring source. It
    exists so that editing the scorer changes the recorded version whether or
    not a human remembered to bump ``version`` -- plan invariant 4 makes the
    evaluator the truth boundary, and a truth boundary that can change silently
    is not one.
    """

    name: str
    version: str
    code_digest: str

    def __post_init__(self) -> None:
        for f_name in ("name", "version", "code_digest"):
            if not str(getattr(self, f_name)).strip():
                raise FreezeError(f"EvaluatorVersion.{f_name} must be non-empty")
        if len(self.code_digest) != 64:
            raise FreezeError(
                "EvaluatorVersion.code_digest must be a sha256 hex digest "
                f"(64 chars), got {len(self.code_digest)}")

    @property
    def digest(self) -> str:
        return canonical_digest({"name": self.name, "version": self.version,
                                 "code_digest": self.code_digest})


# --------------------------------------------------------------------------- #
# 3. budgets                                                                  #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ArmBudget:
    """What one arm may spend. Equality is structural, which is what makes
    "budget-equal" checkable rather than asserted (packet rule R1).

    ``None`` means *this axis is not capped for this comparison* -- never
    ``0`` and never a sentinel like ``MAX_INT``, matching plan §4.1's
    representation rule for disabled caps.

    The precedent for equality-by-construction already exists in
    ``daedalus.eval.harness``: arm C's retrieval budget is literally
    ``token_budget_C = max(tokens_A, 1)``, so the BM25 baseline is handed the
    same token count the product arm actually used.
    """

    max_tokens: int | None = None
    max_wall_seconds: float | None = None
    max_usd: float | None = None
    max_calls: int | None = None

    def __post_init__(self) -> None:
        for f_name in ("max_tokens", "max_wall_seconds", "max_usd", "max_calls"):
            v = getattr(self, f_name)
            if v is None:
                continue
            if v <= 0:
                raise FreezeError(
                    f"ArmBudget.{f_name} must be positive or None (uncapped); "
                    f"got {v!r}. Zero is not 'unlimited' and not 'disabled'.")

    def split(self, n: int) -> "ArmBudget":
        """REFUSED. Dividing one budget across an arm's internal components is
        the exact defect that produced this repository's worst measurement.

        Slice s08 split a shared hit budget round-robin across four indices;
        because every gold label was a code document, only the code index could
        hold the answer, and it effectively received ranks 1, 5, 9 -- top-3.
        Measured that way, "no fusion" scored 432 against 491. Given each index
        its own full budget, it scored 491: exactly the pure code index, and a
        null result rather than a strict loss.

        A composite arm gives each component the FULL budget and declares the
        arrangement in its result row (packet rule R1 / test B2).
        """
        raise FreezeError(
            f"ArmBudget.split({n}) is refused: an arm's components each receive "
            "the full budget. Splitting one budget across components starves "
            "them and produces an artifact of the split, not a measurement "
            "(G3-BASE-01 rule R1; s08 in docs/GATE2_FOREST_V2_TRIAGE.md).")

    @property
    def digest(self) -> str:
        return canonical_digest({
            "max_tokens": self.max_tokens,
            "max_wall_seconds": self.max_wall_seconds,
            "max_usd": self.max_usd,
            "max_calls": self.max_calls,
        })


def require_equal_budgets(budgets: Mapping[str, ArmBudget]) -> None:
    """Packet rule R1 / test B1: every arm in one comparison gets the same
    budget. Raises naming the offenders, so a violation is diagnosable rather
    than merely detected."""
    if not budgets:
        raise FreezeError("a comparison needs at least one arm budget")
    digests: dict[str, list[str]] = {}
    for arm, b in budgets.items():
        digests.setdefault(b.digest, []).append(arm)
    if len(digests) > 1:
        groups = " vs ".join(
            f"{sorted(arms)}" for _, arms in sorted(digests.items()))
        raise FreezeError(
            f"arms do not share one budget: {groups}. A comparison between "
            "unequally-budgeted arms measures the budget, not the method "
            "(plan §4 invariant 9).")


# --------------------------------------------------------------------------- #
# 4. model / hardware reporting                                               #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RunEnvironment:
    """What produced the numbers. Plan §4 invariant 9 requires declared
    hardware and models for any comparative claim.

    ``model_id`` is ``None`` for a deterministic, model-free arm -- that is a
    real and common case here (Tier 1 and arms A/B/C are all model-free), and
    recording ``None`` is honest where inventing a model id would not be.
    """

    tokenizer: str
    os_name: str
    cpu: str
    ram_gb: float | None
    model_id: str | None = None
    provider: str | None = None
    host: str | None = None

    def __post_init__(self) -> None:
        for f_name in ("tokenizer", "os_name", "cpu"):
            if not str(getattr(self, f_name)).strip():
                raise FreezeError(f"RunEnvironment.{f_name} must be non-empty")
        # ram_gb is None when it genuinely could not be determined. An earlier
        # version required a positive float, which left no honest way to say
        # "unknown" -- a caller was driven to smuggle float("nan") through,
        # because `nan <= 0` is False in IEEE-754 and the guard let it pass.
        # A validator that only accepts honest input by accident is not one.
        if self.ram_gb is not None:
            if math.isnan(self.ram_gb) or math.isinf(self.ram_gb):
                raise FreezeError(
                    "RunEnvironment.ram_gb must be a real number or None "
                    f"(unknown); got {self.ram_gb!r}. Use None to declare an "
                    "undetermined value -- never NaN, never a fabricated size.")
            if self.ram_gb <= 0:
                raise FreezeError(
                    "RunEnvironment.ram_gb must be positive or None (unknown); "
                    f"got {self.ram_gb!r}")

    @property
    def digest(self) -> str:
        return canonical_digest({
            "tokenizer": self.tokenizer, "os_name": self.os_name,
            "cpu": self.cpu, "ram_gb": self.ram_gb,
            "model_id": self.model_id, "provider": self.provider,
            "host": self.host,
        })


# --------------------------------------------------------------------------- #
# 5. seed policy                                                              #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SeedPolicy:
    """How stochastic variance is handled.

    Plan §14: "run at least 5-10 seeds when stochastic variance matters".
    ``MIN_STOCHASTIC_SEEDS`` encodes the lower bound; a stochastic arm run with
    fewer is refused rather than reported with an uncertainty nobody measured.

    A deterministic arm declares ``deterministic=True`` and carries exactly one
    seed -- not because determinism needs a seed, but because the run record
    should show which single execution produced the number.
    """

    MIN_STOCHASTIC_SEEDS = 5

    seeds: tuple[int, ...]
    deterministic: bool = False

    def __post_init__(self) -> None:
        if not self.seeds:
            raise FreezeError("SeedPolicy needs at least one seed")
        if len(set(self.seeds)) != len(self.seeds):
            raise FreezeError(
                f"SeedPolicy repeats seeds {list(self.seeds)}; a repeated seed "
                "re-runs one sample and reports it as two, understating variance")
        if self.deterministic and len(self.seeds) != 1:
            raise FreezeError(
                f"a deterministic arm carries exactly one seed, got {len(self.seeds)}")
        if not self.deterministic and len(self.seeds) < self.MIN_STOCHASTIC_SEEDS:
            raise FreezeError(
                f"a stochastic arm needs >= {self.MIN_STOCHASTIC_SEEDS} seeds "
                f"(plan §14), got {len(self.seeds)}. Reporting a single "
                "stochastic run hides the variance the seeds exist to measure.")

    @property
    def n_repetitions(self) -> int:
        return len(self.seeds)

    @property
    def digest(self) -> str:
        return canonical_digest({"seeds": list(self.seeds),
                                 "deterministic": self.deterministic})


# --------------------------------------------------------------------------- #
# 6. the seal                                                                 #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class RunManifest:
    """Binds all six freeze obligations plus the base revision.

    ``sealed`` is DERIVED, never assigned. There is deliberately no way to
    construct a manifest that claims to be sealed while missing an obligation:
    the dataclass requires every field, and ``sealed`` additionally requires a
    non-empty ``owner_seal_ref``. An owner seals the harness (plan §11 Gate 3:
    "Only after that baseline harness is sealed"); a builder cannot.

    ``base_revision`` is the git revision the run measured. ``plan_digest`` is
    the sha256 of the master plan it was run under, so a result can always be
    read back against the rules that were in force -- plan §15 requires
    verifying the plan digest before editing, and evidence deserves the same.
    """

    task_set: FrozenTaskSet
    evaluator: EvaluatorVersion
    budgets: Mapping[str, ArmBudget]
    environment: RunEnvironment
    seed_policy: SeedPolicy
    base_revision: str
    plan_digest: str
    owner_seal_ref: str | None = None

    def __post_init__(self) -> None:
        if not self.base_revision.strip():
            raise FreezeError("RunManifest.base_revision must be non-empty")
        if not self.plan_digest.strip():
            raise FreezeError("RunManifest.plan_digest must be non-empty")
        require_equal_budgets(self.budgets)
        # Defensive copy: `budgets` was a live reference to the caller's dict,
        # so require_equal_budgets could pass at construction and the caller
        # could then swap in an unequal budget. The runner had to re-check at
        # run time to defend itself; now the mapping simply cannot change.
        object.__setattr__(self, "budgets",
                           MappingProxyType(dict(self.budgets)))

    @property
    def sealed(self) -> bool:
        """ALWAYS FALSE here. Sealing is not something this package can do.

        This property used to return ``bool(owner_seal_ref)`` -- i.e. any
        caller could seal a run by passing any non-blank string. An independent
        reviewer sealed a manifest with the literal text "i am definitely the
        owner trust me", which is exactly the forgery plan §4 invariant 5 and
        §11 Gate 3 exist to prevent: "Only after that baseline harness is
        sealed" has to mean an owner sealed it, not a builder typing a string.

        A real seal requires a one-use, authenticated ``OwnerApproval`` bound to
        this manifest digest, verified by the kernel (see plan §7.1 and
        `daedalus/kernel`). That path is NOT wired into this Gate-3 prework
        packet, so the only honest answer available here is "not sealed".

        Fail-closed on purpose: an unsealed harness is the correct description
        of reality today. When the kernel binding is built, this becomes a real
        verification against a real approval -- not a looser string check.
        """
        return False

    @property
    def seal_claim(self) -> str | None:
        """The unverified seal reference, if a caller recorded one.

        Named ``claim`` and not ``seal`` deliberately: it is an assertion by
        whoever built the manifest, carrying no authority whatsoever until the
        kernel verifies it.
        """
        ref = (self.owner_seal_ref or "").strip()
        return ref or None

    @property
    def arms(self) -> tuple[str, ...]:
        return tuple(sorted(self.budgets))

    @property
    def digest(self) -> str:
        return canonical_digest({
            "task_set": self.task_set.digest,
            "evaluator": self.evaluator.digest,
            "budgets": {a: b.digest for a, b in sorted(self.budgets.items())},
            "environment": self.environment.digest,
            "seed_policy": self.seed_policy.digest,
            "base_revision": self.base_revision,
            "plan_digest": self.plan_digest,
            # owner_seal_ref is deliberately OUTSIDE the digest: sealing an
            # existing run must not change the identity of what was measured.
        })

    def evidence_status(self) -> str:
        """One line for any report rendering this run. It can never say a run
        is Gate-3 evidence, because no code path in this package can seal one
        (see ``sealed``). A recorded seal reference is reported as an
        UNVERIFIED CLAIM, which is what it is."""
        claim = self.seal_claim
        if claim is not None:
            return (f"UNSEALED run {self.digest[:12]} @ {self.base_revision[:12]} "
                    f"-- carries an UNVERIFIED seal claim ({claim!r}) that no "
                    "owner approval backs; NOT Gate-3 baseline evidence")
        return (f"UNSEALED run {self.digest[:12]} @ {self.base_revision[:12]} "
                "-- prework only, NOT Gate-3 baseline evidence")


# --------------------------------------------------------------------------- #
# results                                                                     #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class TrialResult:
    """One arm x one task x one seed.

    A FAILED trial carries ``error`` and NO ``score``/``success`` -- absent, not
    zero, not False. ``daedalus.eval.harness`` established this contract
    ("ABSENT, not None -- so any aggregation path that forgets to filter on
    error fails loudly instead of silently averaging a placeholder") and every
    aggregator in this package relies on it.

    ``budget_exceeded`` is reported, never used to clip a result silently: an
    arm that ran over is a finding about the arm, and hiding it would make the
    budget-equality guarantee cosmetic (packet test B4).
    """

    arm: str
    task_id: str
    seed: int
    wall_seconds: float
    tokens_used: int
    calls: int
    success: bool | None = None
    score: float | None = None
    # The candidate the arm actually produced. Carried here because the
    # diversity measure compares candidates across an arm's trials, and an
    # earlier version of run_trial dropped it -- leaving that measure to guess
    # from a notes convention most arms never populate.
    candidate: str | None = None
    budget_exceeded: bool = False
    human_interventions: int = 0
    error: str | None = None
    notes: Mapping[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.error is None and self.success is None:
            raise FreezeError(
                f"trial {self.arm}/{self.task_id}/seed={self.seed} has neither a "
                "success verdict nor an error -- an unmeasured trial must say so")
        if self.error is not None and self.success is not None:
            raise FreezeError(
                f"trial {self.arm}/{self.task_id}/seed={self.seed} reports both "
                "an error and a success verdict; a failed trial has no verdict")
        for f_name in ("wall_seconds", "tokens_used", "calls", "human_interventions"):
            if getattr(self, f_name) < 0:
                raise FreezeError(f"TrialResult.{f_name} cannot be negative")

    @property
    def measured(self) -> bool:
        """False for an errored trial. THE filter every aggregator must apply."""
        return self.error is None


def partition_trials(trials: Sequence[TrialResult]) -> tuple[list[TrialResult],
                                                             list[TrialResult]]:
    """(measured, errored). Aggregators take the first; reports must show both,
    because a silently dropped failure is how a success rate gets inflated."""
    measured = [t for t in trials if t.measured]
    errored = [t for t in trials if not t.measured]
    return measured, errored
