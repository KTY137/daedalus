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
from typing import TYPE_CHECKING, Mapping, Sequence

if TYPE_CHECKING:  # pragma: no cover - typing only
    from daedalus.kernel.seals import (
        ConsumedBaselineSeal,
        SealAuthority,
        VerifiedBaselineSeal,
    )

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
        # Freeze the sequence FIRST, before anything validates it. The
        # annotation says tuple; a caller passing a list kept a live reference,
        # so an object could later hold a state its own validator refuses (a
        # census that no longer sums to the task count) and its .digest could
        # move underneath a seal. The same reviewer finding as the
        # label_plane_census copy below, in the field the fix missed.
        object.__setattr__(self, "task_ids", tuple(self.task_ids))
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
        # Freeze before validating, for the same reason as FrozenTaskSet.
        object.__setattr__(self, "seeds", tuple(self.seeds))
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
    #: The persisted receipt of one consumed seal, and the authority that can
    #: re-authenticate it.  BOTH are required, or neither.
    #:
    #: An earlier revision took a ``VerifiedBaselineSeal`` value and trusted
    #: its type.  That was wrong and an adversarial reviewer demonstrated it:
    #: the class is a frozen dataclass anyone can construct, deserialize,
    #: subclass, pickle or deepcopy, and every digest it carries is publicly
    #: computable from this manifest via ``seal_expectation_digests()``.  A
    #: seal with ``owner_id="attacker"`` and an all-zero signature sealed a
    #: run -- the G3-BASE-01 string forgery, one layer down.  Holding a value
    #: proves nothing; only re-reading the ledger and re-running the HMAC does.
    #:
    #: Both stay OUTSIDE ``digest`` for the recorded reason: sealing an
    #: existing run must not change the identity of what was measured.
    consumed_seal: "ConsumedBaselineSeal | None" = None
    seal_authority: "SealAuthority | None" = None
    #: Set ONLY by ``__post_init__``, from the authority's re-authentication.
    #: ``init=False`` so no caller can pass it, and so ``dataclasses.replace``
    #: drops it and forces a fresh ledger round trip on the new instance.
    _authenticated_seal: "VerifiedBaselineSeal | None" = field(
        default=None, init=False, compare=False, repr=False
    )

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
        object.__setattr__(self, "_authenticated_seal", None)
        if (self.consumed_seal is None) != (self.seal_authority is None):
            raise FreezeError(
                "RunManifest requires consumed_seal and seal_authority together: "
                "a receipt without an authority cannot be authenticated, and an "
                "authority without a receipt has nothing to authenticate"
            )
        if self.consumed_seal is not None:
            # Deferred so this package keeps a stdlib-only module-level import
            # graph until a caller actually presents a seal.
            from daedalus.kernel.seals import (
                ConsumedBaselineSeal,
                SealAuthority,
            )

            if not isinstance(self.consumed_seal, ConsumedBaselineSeal):
                raise FreezeError(
                    "RunManifest.consumed_seal must be a ConsumedBaselineSeal, not "
                    f"{type(self.consumed_seal).__name__}"
                )
            if not isinstance(self.seal_authority, SealAuthority):
                raise FreezeError(
                    "RunManifest.seal_authority must be a SealAuthority, not "
                    f"{type(self.seal_authority).__name__}"
                )
            # THE load-bearing line. Re-reads the ledger row and re-runs the
            # HMAC against the owner keyring; raises on anything short of that.
            # It happens once, at construction, so `sealed` stays a cheap
            # property that reports an answer an authority already gave -- and
            # so a forged receipt fails LOUDLY at construction instead of
            # quietly reporting False somewhere in a report.
            object.__setattr__(
                self,
                "_authenticated_seal",
                self.seal_authority.reauthenticate(self.consumed_seal),
            )

    @property
    def sealed(self) -> bool:
        """True only for a kernel-authenticated seal bound to THIS manifest.

        History, kept because it is the reason for every line below. This
        property once returned ``bool(owner_seal_ref)`` -- any caller could
        seal a run by passing any non-blank string, and an independent reviewer
        sealed a manifest with the literal text "i am definitely the owner
        trust me". That is exactly the forgery plan §4 invariant 5 and §11
        Gate 3 exist to prevent. It was then hard-wired ``False``, which was
        honest but terminal: an eternally-false flag means no Gate-3 evidence
        can ever exist (recorded as `G3-BASE-01` §F4).

        `G3-SEAL-02` supplies the mechanism, in TWO independent halves, and
        both are needed:

        1. ``_authenticated_seal`` is set only by ``__post_init__`` calling
           ``SealAuthority.reauthenticate``, which re-reads the ledger row for
           this receipt and re-runs the owner HMAC over the persisted signed
           seal. A first revision of this packet skipped that and trusted a
           ``VerifiedBaselineSeal`` VALUE; a reviewer sealed a run with
           ``owner_id="attacker"`` and an all-zero signature, because the class
           is freely constructible and every digest it carries is published by
           ``seal_expectation_digests()``.
        2. The comparison below re-checks every freeze obligation against the
           LIVE manifest, so a genuinely authenticated seal issued for a
           different harness -- or for this one before an obligation was
           swapped -- still reports ``False``.

        Half 1 answers "did an owner sign this?"; half 2 answers "sign what?".
        Neither is sufficient alone. Fail-closed stays the default.

        The seal still authorizes nothing: it cannot promote, merge, widen a
        write root or mint a lease.
        """
        seal = self._authenticated_seal
        if seal is None:
            return False
        return (
            seal.manifest_sha256 == self.digest
            and seal.task_set_sha256 == self.task_set.digest
            and seal.evaluator_sha256 == self.evaluator.digest
            and seal.budget_sha256 == self._budget_digest
            and seal.environment_sha256 == self.environment.digest
            and seal.seed_policy_sha256 == self.seed_policy.digest
            and seal.base_revision == self.base_revision
            and seal.plan_digest == self.plan_digest
        )

    @property
    def _budget_digest(self) -> str:
        """One digest over the whole equal-budget mapping.

        The seal binds budgets as a single digest because ``require_equal_budgets``
        already forces them equal; binding them per-arm would let an arm be
        added after sealing without changing any bound value.
        """
        return canonical_digest(
            {arm: budget.digest for arm, budget in sorted(self.budgets.items())}
        )

    def seal_expectation_digests(self) -> dict[str, str]:
        """The eight digests an owner must sign to seal THIS manifest.

        Exposed so the sealing caller derives them from the live manifest
        rather than copying them out of a seal it is about to trust.
        """
        return {
            "manifest_sha256": self.digest,
            "task_set_sha256": self.task_set.digest,
            "evaluator_sha256": self.evaluator.digest,
            "budget_sha256": self._budget_digest,
            "environment_sha256": self.environment.digest,
            "seed_policy_sha256": self.seed_policy.digest,
            "base_revision": self.base_revision,
            "plan_digest": self.plan_digest,
        }

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
        """One line for any report rendering this run.

        It says SEALED only when an authority re-authenticated a persisted
        consumption AND every obligation still matches; every other state --
        including a genuine seal bound to a different harness, and an
        unverified string claim -- renders as UNSEALED and says why. The
        sealed line still names the unverified ``owner_seal_ref`` if one is
        present, so the claim is never silently dropped from a rendered run.
        """
        if self.sealed:
            seal = self._authenticated_seal
            assert seal is not None  # implied by self.sealed
            claim = self.seal_claim
            trailer = f"; unverified seal_claim {claim!r} also present" if claim else ""
            return (f"SEALED run {self.digest[:12]} @ {self.base_revision[:12]} "
                    f"-- owner {seal.owner_id} key {seal.key_id} seal "
                    f"{seal.seal_sha256[:12]}; all six freeze obligations bound"
                    f"{trailer}")
        if self._authenticated_seal is not None:
            return (f"UNSEALED run {self.digest[:12]} @ {self.base_revision[:12]} "
                    "-- carries an authenticated seal "
                    f"({self._authenticated_seal.seal_sha256[:12]}) bound to a "
                    "DIFFERENT harness; NOT Gate-3 baseline evidence")
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
