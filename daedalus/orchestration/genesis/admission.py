"""Pure admission and contract planning for owner-directed Genesis runs.

This module performs no I/O.  It turns one bounded request into the canonical
policy, proposal, product, design, target, Mission and runtime contracts used
by the effectful service.  Unsupported *required* capabilities are retained as
blockers before a lease, workspace, provider or process can be reached.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Mapping

from daedalus.kernel.artifacts import ArtifactRef
from daedalus.kernel.contracts import (
    AttemptContract,
    BuildIntentProposal,
    ContractProvenance,
    DesignContract,
    EffectScope,
    GenesisAutonomyPolicy,
    GraphProposal,
    MaterializationPlan,
    MissionContract,
    PolicyDecision,
    ProductSpec,
    ResourceBudget,
    RuntimeCapabilities,
    RuntimeManifest,
    TargetFourfoldSpec,
    ToolchainManifest,
    derive_work_item_id,
)
from daedalus.spine.envelope import canonical_sha


MASTER_PLAN_SHA256 = (
    "711de9f0bdf0ab15011314528821b75ed5666906f4805ec9ff9c65386ed5a3b2"
)
KANBAN_MASTER_PLAN_SHA256 = (
    "126594137ebf1854458e625b64831c431c64b4a9f3dd8ca2b03c7867e0e8d8fb"
)
GENESIS_POLICY_VERSION = "11.2"
GENESIS_RUN_ID_NAMESPACE_VERSION = "11.2"
KANBAN_POLICY_VERSION = "12.1"
GENESIS_POLICY_ID = "genesis-owner-directed"
ITEM_COLLECTION_BLUEPRINT = "item-collection-v1"
KANBAN_BOARD_BLUEPRINT = "kanban-board-v1"
GENESIS_MAX_FILES = 64
GENESIS_MAX_BYTES = 4 * 1024 * 1024
GENESIS_TIMEOUT_S = 120
SUPPORTED_TARGETS = ("cli", "desktop", "mobile", "web")

_TARGET_ALIASES = {
    "browser": "web",
    "command-line": "cli",
    "commandline": "cli",
    "kommandozeile": "cli",
    "pwa": "web",
    "terminal": "cli",
}
_STACKS = {
    "web": frozenset({"python-stdlib", "vanilla", "vanilla-js", "html-css-js"}),
    "cli": frozenset({"python", "python-stdlib", "stdlib"}),
    "desktop": frozenset({"pwa", "pwa-python-stdlib", "python-stdlib"}),
    "mobile": frozenset({"pwa", "pwa-python-stdlib", "python-stdlib"}),
}
_DEFAULT_STACK = {
    "web": "python-stdlib",
    "cli": "python-stdlib",
    "desktop": "pwa-python-stdlib",
    "mobile": "pwa-python-stdlib",
}
_SECRET_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\b(?:sk|rk)_live_[A-Za-z0-9]{12,}\b"),
    re.compile(
        r"\b(?:api[_ -]?key|password|secret|token)\s*(?:is|=|:)\s*['\"]?"
        r"[A-Za-z0-9_./+\-=]{8,}",
        re.IGNORECASE,
    ),
)
_REQUIRED_EXTERNAL = re.compile(
    r"\b(?:must|requires?|required|braucht|ben[oö]tigt|zwingend|mit)\b"
    r".{0,36}\b(?:oauth|login|stripe|payment|cloud|firebase|supabase|"
    r"remote database|externe datenbank|api[- ]?key|production deploy)\b",
    re.IGNORECASE,
)
_NEGATED_EXTERNAL = re.compile(
    r"\b(?:without|no|kein(?:e[rsnm]?)?|ohne)\b.{0,24}"
    r"\b(?:oauth|login|authentication|anmeldung|telemetry|telemetrie|stripe|"
    r"payment|cloud|api[- ]?key)\b",
    re.IGNORECASE,
)
_NATIVE_REQUIRED = re.compile(
    r"\b(?:native|apk|ipa|packages?|packaging|signing|publication|"
    r"android package|ios package|app[ -]?store|play[ -]?store|"
    r"windows store|mac app store)\b",
    re.IGNORECASE,
)
_NEGATED_NATIVE = re.compile(
    r"\b(?:without|not|no|kein(?:e[rsnm]?)?|ohne)\b.{0,24}"
    r"\b(?:native(?:[ -]+packag(?:e|ing))?|apk|ipa|packages?|packaging|"
    r"signing|publication|android package|ios package|app[ -]?store|"
    r"play[ -]?store|windows store|mac app store)\b",
    re.IGNORECASE,
)
_LOCAL_ARCHETYPES = (
    (
        "task collection",
        re.compile(
            r"\b(?:tasks?|to[ -]?dos?|boards?|trackers?|[\w-]*aufgab\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "notes collection",
        re.compile(r"\b(?:notes?|memos?|notiz\w*)\b", re.IGNORECASE),
    ),
    (
        "inventory collection",
        re.compile(
            r"\b(?:inventor(?:y|ies)|[\w-]*(?:inventar|bestand)\w*)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "general collection",
        re.compile(
            r"\b(?:collections?|lists?|catalog(?:ue)?s?|[\w-]*(?:samml|katalog)\w*|listen?)\b",
            re.IGNORECASE,
        ),
    ),
)
_KANBAN_TRIGGER = re.compile(
    r"(?<![\w-])kanban(?: |-)board(?![\w-])",
    re.IGNORECASE,
)

# Genesis v1 is a finite product grammar, not a general software prompt.  Every
# lexical word must be consumed here (or by one of the narrow morphology
# patterns below) before the request may reach an effect.  Keeping this list
# intentionally mundane is what prevents a supported word such as ``tasks``
# from laundering an unrelated requirement in the same sentence.
_ALLOWED_PROMPT_WORDS = frozenset(
    """
    a add an and android another app application as basic board boards browser
    build catalog catalogs catalogue catalogues cli collect collection
    collections command complete completed completion create crud delete desktop
    detail details different do done edit entries entry filter filtering filters
    find first for general generate give html css inventory inventories iphone
    ios item items javascript js keep line linux list lists local locally mac
    macos make maintain maintenance manage memo memos mobile must my native no
    note notes not of offline one only package packaging personal please private
    pwa python read reading record records remove reopen required save search
    searchable simple single small smartphone status stdlib store task tasks the
    title titles to todo todos tool track tracker trackers update use user using
    vanilla view web windows with without work
    abschliessen abschließen aktualisieren als anlegen anzeigen app aufgabe
    aufgaben bau baue bearbeiten beschreibung bestand bitte das der die ein eine
    einen einfach erledigen erledigt erstelle erstellen fuer für hinzufuegen
    hinzufügen inventar katalog kein keine keinen kommandozeile liste lokal
    loeschen löschen mach mache memo mobil mit notiz offline ohne oeffnen öffnen
    persoenlich persönlich privat sammlung speichern suche suchen titel und
    verwalten wieder wiederoeffnen wiederöffnen zu zum zur wartung
    apk ipa play signing publication
    """.split()
)
_ALLOWED_PROMPT_WORD_PATTERNS = (
    re.compile(r"^[\w]*aufgab\w*$", re.IGNORECASE),
    re.compile(r"^(?:notiz|inventar|bestand|samml|katalog|wartung)\w*$", re.IGNORECASE),
    re.compile(r"^(?:lokal|privat|pers[oö]nlich|einfach|klein)\w*$", re.IGNORECASE),
)
_PROMPT_WORD = re.compile(r"[^\W_]+", re.UNICODE)
_PROMPT_GRAMMAR_MAX_TERMS = 12


def _clean_text(value: object, label: str, *, limit: int) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{label} must be a string")
    text = unicodedata.normalize(
        "NFC", value.replace("\r\n", "\n").replace("\r", "\n")
    ).strip()
    if not text:
        raise ValueError(f"{label} must not be empty")
    if len(text) > limit:
        raise ValueError(f"{label} must be at most {limit} characters")
    if "\x00" in text or any(
        ord(character) < 32 and character not in {"\n", "\t"}
        for character in text
    ):
        raise ValueError(f"{label} contains unsupported control characters")
    return text


def _slug(value: str, *, fallback: str = "product") -> str:
    ascii_value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    )
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value.lower()).strip("-")
    return (slug or fallback)[:64].rstrip("-")


def _infer_target(prompt: str) -> str:
    lowered = prompt.casefold()
    if re.search(r"\b(cli|terminal|command[ -]?line|kommandozeile)\b", lowered):
        return "cli"
    if re.search(r"\b(desktop|windows app|mac(?:os)? app|linux app)\b", lowered):
        return "desktop"
    if re.search(
        r"\b(mobile|android|ios|iphone|smartphone|apk|ipa|"
        r"app[ -]?store|play[ -]?store)\b",
        lowered,
    ):
        return "mobile"
    return "web"


def _product_name(prompt: str) -> str:
    one_line = " ".join(prompt.split())
    one_line = re.sub(
        r"^(?:please\s+)?(?:build|create|make|generate|baue|bau|erstelle|mach)\s+",
        "",
        one_line,
        flags=re.IGNORECASE,
    )
    words = re.findall(r"[\wÄÖÜäöüß'-]+", one_line, flags=re.UNICODE)[:6]
    if not words:
        return "Genesis Product"
    value = " ".join(words)
    return value[:160].strip().title()


def _features(prompt: str) -> tuple[str, ...]:
    lowered = prompt.casefold()
    features = {
        "complete and reopen items",
        "create local items",
        "edit local items",
        "delete local items",
        "persist data locally",
    }
    if any(word in lowered for word in ("search", "suche", "filter")):
        features.add("search and filter items")
    return tuple(sorted(features))


def _kanban_features(prompt: str) -> tuple[str, ...]:
    lowered = prompt.casefold()
    features = {
        "create local cards",
        "delete local cards",
        "edit local cards",
        "move cards between fixed columns",
        "persist data locally",
    }
    if any(word in lowered for word in ("search", "suche", "filter")):
        features.add("search and filter cards")
    return tuple(sorted(features))


def _blueprint(prompt: str) -> str:
    return (
        KANBAN_BOARD_BLUEPRINT
        if _KANBAN_TRIGGER.search(prompt)
        else ITEM_COLLECTION_BLUEPRINT
    )


def _local_archetype(prompt: str) -> str | None:
    """Classify only the finite product family this materializer can build.

    A matching word is admission, not a claim that arbitrary software was
    understood. Requests outside these local collection shapes remain inert
    and receive an explicit blocker before any state root or process exists.
    """

    for name, pattern in _LOCAL_ARCHETYPES:
        if pattern.search(prompt):
            return name
    return None


def _unsupported_prompt_requirement(
    prompt: str,
    *,
    additional_allowed_words: frozenset[str] = frozenset(),
) -> str | None:
    """Return one bounded blocker unless the positive v1 grammar consumes all.

    Punctuation is presentation-only. Unicode symbols (including emoji) are
    not silently discarded because they can carry a requirement such as a
    reminder bell. Hyphenated terms are deliberately split into their words,
    so supported spellings such as ``local-first`` and ``python-stdlib`` stay
    finite without creating a second fuzzy parser.
    """

    lexical = unicodedata.normalize("NFKC", prompt).casefold().replace("_", " ")
    lexical = lexical.replace("-", " ").replace("\u2010", " ").replace("\u2011", " ")
    unsupported: list[str] = []
    seen: set[str] = set()
    for word in _PROMPT_WORD.findall(lexical):
        if word in _ALLOWED_PROMPT_WORDS or word in additional_allowed_words or any(
            pattern.fullmatch(word) for pattern in _ALLOWED_PROMPT_WORD_PATTERNS
        ):
            continue
        if word not in seen:
            seen.add(word)
            unsupported.append(word[:48])

    for character in lexical:
        category = unicodedata.category(character)
        if (
            character.isspace()
            or character.isalnum()
            or category.startswith("P")
            or category.startswith("M")
            or character in {"+", "&"}
        ):
            continue
        label = f"U+{ord(character):04X}"
        if label not in seen:
            seen.add(label)
            unsupported.append(label)

    if not unsupported:
        return None
    shown = unsupported[:_PROMPT_GRAMMAR_MAX_TERMS]
    remainder = len(unsupported) - len(shown)
    rendered = ", ".join(repr(term) for term in shown)
    if remainder:
        rendered += f" (+{remainder} more)"
    return (
        "Unsupported Genesis v1 requirement token(s): "
        + rendered
        + ". Supported prompt scope is only a local/offline single-user item "
        "collection (tasks/todos, notes, inventory, or a general list) with "
        "title/details CRUD, completion, and optional search/filter."
    )


def _external_requirement(prompt: str) -> str | None:
    without_negations = _NEGATED_EXTERNAL.sub("", prompt)
    match = _REQUIRED_EXTERNAL.search(without_negations)
    if match is None:
        return None
    return (
        "The request requires an external authentication, payment, cloud, API-key "
        "or deployment dependency that the offline Genesis policy cannot satisfy."
    )


def _native_requirement(prompt: str) -> str | None:
    without_negations = _NEGATED_NATIVE.sub("", prompt)
    if _NATIVE_REQUIRED.search(without_negations) is None:
        return None
    return (
        "The request explicitly requires native or store packaging, signing, or "
        "publication, but Genesis v1 creates only local source candidates; its "
        "desktop/mobile targets are installable offline PWAs, not native packages."
    )


@dataclass(frozen=True)
class GenesisRequest:
    """Normalized, deterministic request identity; still entirely inert."""

    prompt: str
    target: str
    stack: str
    request_key: str
    source_revision: str
    run_id: str
    lineage_id: str
    mission_id: str
    attempt_id: str
    product_name: str
    features: tuple[str, ...]
    target_required: bool
    stack_required: bool
    requested_target: str | None
    requested_stack: str | None
    defaults: Mapping[str, object]
    blockers: tuple[str, ...]
    notices: tuple[str, ...]

    @property
    def admitted(self) -> bool:
        return not self.blockers

    @property
    def blueprint(self) -> str:
        value = self.defaults.get("blueprint")
        if value is None:
            return ITEM_COLLECTION_BLUEPRINT
        return str(value)

    @property
    def policy_version(self) -> str:
        return (
            KANBAN_POLICY_VERSION
            if self.blueprint == KANBAN_BOARD_BLUEPRINT
            else GENESIS_POLICY_VERSION
        )


@dataclass(frozen=True)
class GenesisPlan:
    """Canonical pre-effect plan for one admitted request."""

    request: GenesisRequest
    policy: GenesisAutonomyPolicy
    runtime_manifest: RuntimeManifest
    intent: BuildIntentProposal
    product: ProductSpec
    policy_decision: PolicyDecision
    design: DesignContract
    target_spec: TargetFourfoldSpec
    graph: GraphProposal
    mission: MissionContract
    work_item_ids: tuple[str, ...]


@dataclass(frozen=True)
class BoundGenesisPlan:
    """The plan after an empty CAS base and a real lease decision are bound."""

    plan: GenesisPlan
    materialization: MaterializationPlan
    toolchain: ToolchainManifest
    attempt: AttemptContract


def normalize_genesis_request(
    prompt: object,
    *,
    target: object | None = None,
    stack: object | None = None,
    request_key: object | None = None,
) -> GenesisRequest:
    clean_prompt = _clean_text(prompt, "prompt", limit=8_000)
    blueprint = _blueprint(clean_prompt)
    explicit_target = target is not None and str(target).strip() != ""
    raw_target = str(target).strip().casefold() if explicit_target else ""
    selected_target = _TARGET_ALIASES.get(raw_target, raw_target)
    blockers: list[str] = []
    if explicit_target and selected_target not in SUPPORTED_TARGETS:
        blockers.append(
            f"Unsupported required target {raw_target!r}; supported targets are "
            + ", ".join(SUPPORTED_TARGETS)
            + "."
        )
        selected_target = "web"
    elif not explicit_target:
        selected_target = _infer_target(clean_prompt)

    if blueprint == KANBAN_BOARD_BLUEPRINT and selected_target == "cli":
        blockers.append(
            "The kanban-board-v1 blueprint supports browser, desktop, and mobile "
            "PWA targets only; CLI is not implemented."
        )

    explicit_stack = stack is not None and str(stack).strip() != ""
    raw_stack = (
        _clean_text(stack, "stack", limit=240).casefold()
        if explicit_stack
        else _DEFAULT_STACK[selected_target]
    )
    raw_stack = re.sub(r"\s+", "-", raw_stack)
    if raw_stack not in _STACKS[selected_target]:
        blockers.append(
            f"Unsupported required stack {raw_stack!r} for target "
            f"{selected_target!r}; this Genesis slice supports "
            + ", ".join(sorted(_STACKS[selected_target]))
            + "."
        )

    archetype = _local_archetype(clean_prompt)
    if archetype is None:
        blockers.append(
            "Unsupported product shape; Genesis v1 currently builds only local "
            "item collections (tasks/todos, notes, inventories, or general lists) "
            "with title/details, completion, and optional search/filter."
        )
    grammar = _unsupported_prompt_requirement(
        clean_prompt,
        additional_allowed_words=(
            frozenset({"kanban"})
            if blueprint == KANBAN_BOARD_BLUEPRINT
            else frozenset()
        ),
    )
    if grammar is not None:
        blockers.append(grammar)

    if any(pattern.search(clean_prompt) for pattern in _SECRET_PATTERNS):
        blockers.append(
            "The prompt appears to contain credential material; Genesis refuses "
            "to copy secrets into a candidate."
        )
    external = _external_requirement(clean_prompt)
    if external is not None:
        blockers.append(external)
    native = _native_requirement(clean_prompt)
    if native is not None:
        blockers.append(native)

    notices: list[str] = []
    if selected_target in {"desktop", "mobile"}:
        notices.append(
            f"{selected_target.title()} is delivered as an installable offline PWA, "
            "not as a native store package."
        )
    elif raw_target == "pwa" or (
        not explicit_target and re.search(r"\bpwa\b", clean_prompt, re.IGNORECASE)
    ):
        notices.append(
            "PWA is delivered as an installable offline browser application, "
            "not as a native store package."
        )

    if request_key is None or str(request_key).strip() == "":
        clean_key = "prompt:" + canonical_sha(
            {"prompt": clean_prompt, "target": selected_target, "stack": raw_stack}
        )[:32]
    else:
        clean_key = _clean_text(request_key, "request_key", limit=200)

    identity = {
        "schema": "daedalus-genesis-request-identity/1",
        "policy_version": GENESIS_POLICY_VERSION,
        "prompt": clean_prompt,
        "request_key": clean_key,
        "requested_stack": raw_stack if explicit_stack else None,
        "requested_target": raw_target if explicit_target else None,
        "stack": raw_stack,
        "stack_required": explicit_stack,
        "target": selected_target,
        "target_required": explicit_target,
    }
    if blueprint == KANBAN_BOARD_BLUEPRINT:
        identity = {
            **identity,
            "blueprint": blueprint,
            "policy_version": KANBAN_POLICY_VERSION,
            "schema": "daedalus-genesis-request-identity/2",
        }
    digest = canonical_sha(identity)
    source_revision = digest[:40]
    # The caller's key owns retry identity.  Request material owns the source
    # revision. Reusing one key with changed material therefore reaches the
    # same Attempt and is refused as a binding mismatch instead of silently
    # becoming a second run.
    suffix = canonical_sha(
        {
            "schema": "daedalus-genesis-idempotency-key/1",
            "policy_version": GENESIS_RUN_ID_NAMESPACE_VERSION,
            "request_key": clean_key,
        }
    )[:24]
    defaults = {
        "accessibility": "WCAG 2.2 AA",
        "authentication": False,
        "audience": "one local user",
        "base_repository": None,
        "capability_scope": (
            "item CRUD with title/details, completion, and optional search/filter"
        ),
        "language": "English UI generated from the supplied objective",
        "product_class": f"local-first {archetype or 'unsupported product'}",
        "requested_stack": raw_stack if explicit_stack else None,
        "requested_target": raw_target if explicit_target else None,
        "stack": raw_stack,
        "stack_required": explicit_stack,
        "storage": "local-only",
        "target": selected_target,
        "target_required": explicit_target,
        "telemetry": False,
    }
    if blueprint == KANBAN_BOARD_BLUEPRINT:
        defaults = {
            **defaults,
            "blueprint": blueprint,
            "capability_scope": (
                "card CRUD with fixed backlog/in-progress/done columns, keyboard "
                "move controls, and optional search/filter"
            ),
            "product_class": "local-first kanban board",
        }
    return GenesisRequest(
        prompt=clean_prompt,
        target=selected_target,
        stack=raw_stack,
        request_key=clean_key,
        source_revision=source_revision,
        run_id=f"genesis-{suffix}",
        lineage_id=f"lineage-{suffix}",
        mission_id=f"mission-{suffix}",
        attempt_id=f"attempt-{suffix}",
        product_name=_product_name(clean_prompt),
        features=(
            _kanban_features(clean_prompt)
            if blueprint == KANBAN_BOARD_BLUEPRINT
            else _features(clean_prompt)
        ),
        target_required=explicit_target,
        stack_required=explicit_stack,
        requested_target=raw_target if explicit_target else None,
        requested_stack=raw_stack if explicit_stack else None,
        defaults=defaults,
        blockers=tuple(sorted(set(blockers))),
        notices=tuple(sorted(set(notices))),
    )


def _provenance(
    request: GenesisRequest,
    *,
    origin: str,
    created_at: str,
    inputs: tuple[str, ...] = (),
) -> ContractProvenance:
    return ContractProvenance(
        origin=origin,
        source_revision=request.source_revision,
        created_at=created_at,
        input_digests=tuple(sorted(set(inputs))),
        trace_id=request.run_id,
    )


def build_genesis_plan(request: GenesisRequest, *, created_at: str) -> GenesisPlan:
    if not isinstance(request, GenesisRequest):
        raise TypeError("request must be a GenesisRequest")
    if not request.admitted:
        raise ValueError("blocked Genesis request cannot become a Mission")

    budget = ResourceBudget(max_cost_microusd=0, max_wall_time_s=GENESIS_TIMEOUT_S, max_attempts=2)
    policy = GenesisAutonomyPolicy(
        policy_id=GENESIS_POLICY_ID,
        policy_version=request.policy_version,
        source_revision=request.source_revision,
        defaults=request.defaults,
        allowed_targets=(
            ("desktop", "mobile", "web")
            if request.blueprint == KANBAN_BOARD_BLUEPRINT
            else SUPPORTED_TARGETS
        ),
        default_target="web",
        budget=budget,
        max_files=GENESIS_MAX_FILES,
        max_bytes=GENESIS_MAX_BYTES,
        max_repairs=1,
        allow_isolated_preview=True,
        public_release_requires_owner_approval=True,
        provenance=_provenance(
            request,
            origin="genesis.owner-policy",
            created_at=created_at,
            inputs=(
                KANBAN_MASTER_PLAN_SHA256
                if request.blueprint == KANBAN_BOARD_BLUEPRINT
                else MASTER_PLAN_SHA256,
            ),
        ),
    )
    runtime = RuntimeManifest(
        runtime_id="genesis-python-stdlib",
        runtime_version="1",
        adapter_id="genesis-deterministic-materializer",
        adapter_version="1",
        source_revision=request.source_revision,
        assurance="declared",
        capabilities=RuntimeCapabilities(
            timeout=True,
            cancellation=True,
            workspace_isolation=True,
            workspace_write=True,
        ),
        declared_tools=(),
        egress_transports=(),
        workspace_modes=("isolated-worktree", "read-only"),
        cost_model="zero-local",
        provenance=_provenance(
            request,
            origin="genesis.runtime-manifest",
            created_at=created_at,
            inputs=(policy.digest,),
        ),
    )
    intent = BuildIntentProposal(
        proposal_id=f"intent-{request.run_id.removeprefix('genesis-')}",
        lineage_id=request.lineage_id,
        source_revision=request.source_revision,
        prompt=request.prompt,
        target=request.target,
        stack=request.stack,
        advisory=True,
        runtime_manifest_sha256=runtime.digest,
        assumptions=tuple(
            f"{key}={value}" for key, value in sorted(request.defaults.items())
        ),
        requested_features=request.features,
        target_required=request.target_required,
        stack_required=request.stack_required,
        provenance=_provenance(
            request,
            origin="genesis.build-intent",
            created_at=created_at,
            inputs=(runtime.digest,),
        ),
    )
    product_constraints = (
        (
            "no authentication",
            "no drag-and-drop interaction",
            "no external network dependency",
            "no telemetry",
            "offline-capable",
            "product shape is limited to the kanban-board-v1 blueprint",
            "source starts from an explicit empty base",
        )
        if request.blueprint == KANBAN_BOARD_BLUEPRINT
        else (
            "no authentication",
            "no external network dependency",
            "no telemetry",
            "offline-capable",
            "product shape is limited to the admitted local item-collection scope",
            "source starts from an explicit empty base",
        )
    )
    product = ProductSpec(
        product_id=_slug(request.product_name),
        lineage_id=request.lineage_id,
        source_revision=request.source_revision,
        name=request.product_name,
        summary=request.prompt,
        target=request.target,
        audience="one local user",
        features=request.features,
        constraints=product_constraints,
        base_repository=None,
        defaults=request.defaults,
        policy_sha256=policy.digest,
        build_intent_proposal_sha256=intent.digest,
        provenance=_provenance(
            request,
            origin="genesis.product-spec",
            created_at=created_at,
            inputs=(policy.digest, intent.digest),
        ),
    )
    policy_decision = PolicyDecision(
        decision_id=f"{request.run_id}-allow",
        subject_id=product.product_id,
        subject_sha256=product.digest,
        policy_version=policy.policy_version,
        policy_sha256=policy.digest,
        verdict="allow",
        reasons=(
            "request fits the deterministic local-only Genesis capability",
            "all candidate writes are confined to one isolated Attempt workspace",
            "public release remains owner-controlled and is not part of this decision",
        ),
        effect_scope=EffectScope(
            read_only=False,
            writable_paths=(".",),
            tools=("python",),
            max_cost_microusd=0,
            max_concurrency=1,
            timeout_s=GENESIS_TIMEOUT_S,
            kill_switch_ref=f"genesis-{request.run_id.removeprefix('genesis-')}",
        ),
        provenance=_provenance(
            request,
            origin="genesis.admission-policy",
            created_at=created_at,
            inputs=(product.digest, policy.digest),
        ),
    )
    interaction_requirements = (
        (
            "all primary actions are keyboard operable",
            "create edit move and delete actions report status",
            "move back and move forward buttons preserve fixed column order",
            "layout remains usable from 320px viewport width",
        )
        if request.blueprint == KANBAN_BOARD_BLUEPRINT
        else (
            "all primary actions are keyboard operable",
            "create edit complete and delete actions report status",
            "layout remains usable from 320px viewport width",
        )
    )
    visual_contract = (
        {
            "accent": "#4f46e5",
            "fixed_columns": ("backlog", "in-progress", "done"),
            "minimum_target_px": 44,
            "responsive": True,
        }
        if request.blueprint == KANBAN_BOARD_BLUEPRINT
        else {
            "accent": "#1d4ed8",
            "minimum_target_px": 44,
            "responsive": True,
        }
    )
    design = DesignContract(
        design_id=f"design-{request.run_id.removeprefix('genesis-')}",
        lineage_id=request.lineage_id,
        source_revision=request.source_revision,
        product_spec_sha256=product.digest,
        interaction_requirements=interaction_requirements,
        accessibility_requirements=(
            "semantic landmarks and labels",
            "visible keyboard focus",
            "WCAG 2.2 AA contrast target",
        ),
        visual_contract=visual_contract,
        provenance=_provenance(
            request,
            origin="genesis.design-contract",
            created_at=created_at,
            inputs=(product.digest,),
        ),
    )
    if request.blueprint == KANBAN_BOARD_BLUEPRINT:
        code_requirements = (
            "bounded local kanban card CRUD behavior",
            "fixed backlog/in-progress/done workflow",
            "stdlib-only runtime",
        )
        type_requirements = (
            "Card has stable typed identity and one fixed column",
        )
        data_requirements = (
            "Card schema and local persistence agree on the fixed column enum",
        )
        knowledge_requirements = (
            "README documents keyboard movement and limitations",
        )
        behavior_acceptance = (
            "app.js matches the pinned kanban-board-v1 template after exact CONFIG normalization",
            "Card model and schema match their independently pinned identities",
            "browser behavior is not claimed by certified-template conformance",
        )
    else:
        code_requirements = ("bounded local CRUD behavior", "stdlib-only runtime")
        type_requirements = ("Item has stable typed identity and completion state",)
        data_requirements = ("Item schema and local persistence agree",)
        knowledge_requirements = ("README documents operation and limitations",)
        behavior_acceptance = (
            (
                "requested CLI behavior passes a kernel-owned contained "
                "black-box CRUD/search scenario",
            )
            if request.target == "cli"
            else (
                "app.js matches the pinned approved template after exact "
                "CONFIG normalization",
                "browser behavior is not claimed by certified-template conformance",
            )
        )
    target_spec = TargetFourfoldSpec(
        target_spec_id=f"fourfold-target-{request.run_id.removeprefix('genesis-')}",
        lineage_id=request.lineage_id,
        source_revision=request.source_revision,
        product_spec_sha256=product.digest,
        design_contract_sha256=design.digest,
        code_requirements=code_requirements,
        type_requirements=type_requirements,
        data_requirements=data_requirements,
        knowledge_requirements=knowledge_requirements,
        acceptance_criteria=(
            "deterministic syntax check passes",
            "generated unit tests pass",
            "runtime smoke check passes",
            "package smoke check passes",
            *behavior_acceptance,
            "candidate-executing checks report effective OS write containment",
            "rebuilt Fourfold snapshot is complete",
        ),
        provenance=_provenance(
            request,
            origin="genesis.target-fourfold",
            created_at=created_at,
            inputs=(product.digest, design.digest),
        ),
    )
    context_payload = {
        "schema": "daedalus-genesis-context-capsule/1",
        "base_repository": None,
        "prompt_sha256": canonical_sha(request.prompt),
        "target": request.target,
    }
    if request.blueprint == KANBAN_BOARD_BLUEPRINT:
        context_payload = {
            **context_payload,
            "blueprint": request.blueprint,
            "schema": "daedalus-genesis-context-capsule/2",
        }
    context_sha = canonical_sha(context_payload)
    graph_operations = (
        (
            {"operation": "materialize", "plane": "code", "subject": "local-kanban"},
            {"operation": "bind", "from": "Card", "to": "card-schema"},
            {"operation": "document", "subject": "runtime-and-limitations"},
        )
        if request.blueprint == KANBAN_BOARD_BLUEPRINT
        else (
            {"operation": "materialize", "plane": "code", "subject": "local-crud"},
            {"operation": "bind", "from": "Item", "to": "item-schema"},
            {"operation": "document", "subject": "runtime-and-limitations"},
        )
    )
    graph = GraphProposal(
        proposal_id=f"graph-{request.run_id.removeprefix('genesis-')}",
        lineage_id=request.lineage_id,
        source_revision=request.source_revision,
        target_fourfold_spec_sha256=target_spec.digest,
        runtime_manifest_sha256=runtime.digest,
        context_capsule_sha256=context_sha,
        budget=budget,
        operations=graph_operations,
        writable_paths=(".",),
        advisory=True,
        provenance=_provenance(
            request,
            origin="genesis.graph-proposal",
            created_at=created_at,
            inputs=(target_spec.digest, runtime.digest, context_sha),
        ),
    )
    phases = (
        "specification",
        "design-and-target",
        "materialization",
        "build",
        "test",
        "runtime-smoke",
        "package-smoke",
        "fourfold-roundtrip",
        "isolated-preview",
    )
    work_identity_suffix = (
        (request.source_revision, request.target, request.blueprint)
        if request.blueprint == KANBAN_BOARD_BLUEPRINT
        else (request.source_revision, request.target)
    )
    work_ids = tuple(
        derive_work_item_id(
            request.mission_id,
            ordinal=index,
            identity=(phase, *work_identity_suffix),
        )
        for index, phase in enumerate(phases, start=1)
    )
    mission = MissionContract(
        mission_id=request.mission_id,
        objective=f"Materialize and verify an isolated {request.target} product: {request.prompt}",
        source_revision=request.source_revision,
        work_item_ids=work_ids,
        success_criteria=target_spec.acceptance_criteria,
        policy_sha256=policy.digest,
        budget=budget,
        provenance=_provenance(
            request,
            origin="genesis.mission",
            created_at=created_at,
            inputs=(policy.digest, product.digest, target_spec.digest, graph.digest),
        ),
    )
    return GenesisPlan(
        request=request,
        policy=policy,
        runtime_manifest=runtime,
        intent=intent,
        product=product,
        policy_decision=policy_decision,
        design=design,
        target_spec=target_spec,
        graph=graph,
        mission=mission,
        work_item_ids=work_ids,
    )


def bind_genesis_attempt(
    plan: GenesisPlan,
    *,
    input_tree: ArtifactRef,
    expected_outputs: tuple[str, ...],
    python_version: str,
    created_at: str,
) -> BoundGenesisPlan:
    if not isinstance(plan, GenesisPlan):
        raise TypeError("plan must be a GenesisPlan")
    if not isinstance(input_tree, ArtifactRef):
        raise TypeError("input_tree must be an ArtifactRef")
    policy_decision = plan.policy_decision
    if policy_decision.verdict != "allow":  # defensive: GenesisPlan is frozen
        raise ValueError("Genesis attempt requires an allowed canonical policy decision")
    request = plan.request
    materialization = MaterializationPlan(
        plan_id=f"materialize-{request.run_id.removeprefix('genesis-')}",
        lineage_id=request.lineage_id,
        source_revision=request.source_revision,
        product_spec_sha256=plan.product.digest,
        design_contract_sha256=plan.design.digest,
        target_fourfold_spec_sha256=plan.target_spec.digest,
        graph_proposal_sha256=plan.graph.digest,
        input_tree=input_tree,
        work_item_ids=plan.work_item_ids,
        writable_paths=(".",),
        expected_outputs=tuple(sorted(expected_outputs)),
        max_files=plan.policy.max_files,
        max_bytes=plan.policy.max_bytes,
        provenance=_provenance(
            request,
            origin="genesis.materialization-plan",
            created_at=created_at,
            inputs=(
                plan.product.digest,
                plan.design.digest,
                plan.target_spec.digest,
                plan.graph.digest,
                input_tree.sha256,
            ),
        ),
    )
    code_files = ("app.py",) if request.target == "cli" else ("model.py", "server.py")
    syntax_probe = (
        "import ast,pathlib; "
        + "[ast.parse(pathlib.Path(p).read_text(encoding='utf-8'), filename=p) "
        + f"for p in {code_files!r}]; print('GENESIS_BUILD_OK')"
    )
    runtime_command = (
        ("python", "-B", "app.py", "about")
        if request.target == "cli"
        else (
            "python",
            "-B",
            "-c",
            "import pathlib,server; c=server.ServerConfig(); "
            "assert c.host == '127.0.0.1'; "
            "assert '<main' in pathlib.Path('index.html').read_text(encoding='utf-8'); "
            "print('GENESIS_RUNTIME_OK')",
        )
    )
    toolchain = ToolchainManifest(
        manifest_id=f"toolchain-{request.run_id.removeprefix('genesis-')}",
        lineage_id=request.lineage_id,
        source_revision=request.source_revision,
        target=request.target,
        stack=request.stack,
        versions={"python": python_version},
        required_tools=("python",),
        lockfiles=(),
        build_command=("python", "-B", "-c", syntax_probe),
        test_command=("python", "-B", "-m", "unittest", "discover", "-s", "tests", "-q"),
        run_command=runtime_command,
        package_command=(
            "python",
            "-B",
            "-c",
            "import pathlib; assert pathlib.Path('README.md').is_file(); "
            "print('GENESIS_PACKAGE_OK')",
        ),
        licenses=("generated source: CC0-1.0",),
        egress_endpoints=(),
        materialization_plan_sha256=materialization.digest,
        sandbox_policy_sha256=plan.policy.digest,
        provenance=_provenance(
            request,
            origin="genesis.toolchain-manifest",
            created_at=created_at,
            inputs=(materialization.digest, plan.policy.digest),
        ),
    )
    attempt = AttemptContract(
        attempt_id=request.attempt_id,
        mission_id=request.mission_id,
        task_id=plan.work_item_ids[2],
        instruction="Materialize the admitted Genesis plan and run independent local checks.",
        base_revision=request.source_revision,
        task_sha256=materialization.digest,
        runtime_manifest_sha256=plan.runtime_manifest.digest,
        policy_decision_sha256=policy_decision.digest,
        budget=plan.policy.budget,
        writable_paths=(".",),
        gate_names=tuple(
            sorted(
                {
                    "build",
                    "fourfold",
                    "package",
                    "roundtrip",
                    "runtime",
                    "test",
                    *(
                        {"kanban_template_conformance"}
                        if request.blueprint == KANBAN_BOARD_BLUEPRINT
                        else {"cli_black_box", "feature_conformance"}
                        if request.target == "cli"
                        else {"certified_template_conformance"}
                    ),
                }
            )
        ),
        read_only=False,
        provenance=_provenance(
            request,
            origin="genesis.attempt",
            created_at=created_at,
            inputs=(materialization.digest, plan.runtime_manifest.digest, policy_decision.digest),
        ),
    )
    return BoundGenesisPlan(
        plan=plan,
        materialization=materialization,
        toolchain=toolchain,
        attempt=attempt,
    )


def denied_policy_decision(
    request: GenesisRequest, *, created_at: str
) -> PolicyDecision:
    if request.admitted:
        raise ValueError("admitted request does not need a denial")
    subject_sha = canonical_sha(
        {
            "prompt": request.prompt,
            "request_key": request.request_key,
            "stack": request.stack,
            "target": request.target,
        }
    )
    policy_sha = canonical_sha(
        {
            "policy_id": GENESIS_POLICY_ID,
            "policy_version": request.policy_version,
            "master_plan_sha256": (
                KANBAN_MASTER_PLAN_SHA256
                if request.blueprint == KANBAN_BOARD_BLUEPRINT
                else MASTER_PLAN_SHA256
            ),
        }
    )
    return PolicyDecision(
        decision_id=f"{request.run_id}-deny",
        subject_id=request.run_id,
        subject_sha256=subject_sha,
        policy_version=request.policy_version,
        policy_sha256=policy_sha,
        verdict="deny",
        reasons=request.blockers,
        effect_scope=EffectScope(),
        provenance=_provenance(
            request,
            origin="genesis.admission-denial",
            created_at=created_at,
            inputs=(subject_sha, policy_sha),
        ),
    )


__all__ = [
    "BoundGenesisPlan",
    "GENESIS_MAX_BYTES",
    "GENESIS_MAX_FILES",
    "GENESIS_POLICY_ID",
    "GENESIS_POLICY_VERSION",
    "GENESIS_RUN_ID_NAMESPACE_VERSION",
    "GENESIS_TIMEOUT_S",
    "ITEM_COLLECTION_BLUEPRINT",
    "KANBAN_BOARD_BLUEPRINT",
    "KANBAN_MASTER_PLAN_SHA256",
    "KANBAN_POLICY_VERSION",
    "GenesisPlan",
    "GenesisRequest",
    "MASTER_PLAN_SHA256",
    "SUPPORTED_TARGETS",
    "bind_genesis_attempt",
    "build_genesis_plan",
    "denied_policy_decision",
    "normalize_genesis_request",
]
