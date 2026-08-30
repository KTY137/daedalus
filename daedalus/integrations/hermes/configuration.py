"""Pinned source and containment configuration for the Hermes userspace worker."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import os
from pathlib import Path
import subprocess
from typing import Mapping

HERMES_RUNTIME_ID = "hermes_agent"
HERMES_ADAPTER_ID = "daedalus.integrations.hermes"
HERMES_ADAPTER_VERSION = "1"
HERMES_OPERATION_ID = "provider.hermes_agent.oneshot.v1"
HERMES_PROTOCOL_SCHEMA = "daedalus-hermes-worker-jsonl/1"


class HermesConfigurationError(ValueError):
    """Raised when exact source or containment configuration is not admissible."""


def _hex_digest(value: object, *, length: int, label: str) -> str:
    if not isinstance(value, str) or len(value) != length:
        raise HermesConfigurationError(f"{label} must be {length} lowercase hex characters")
    lowered = value.lower()
    try:
        int(lowered, 16)
    except ValueError as exc:
        raise HermesConfigurationError(f"{label} must be hexadecimal") from exc
    if value != lowered:
        raise HermesConfigurationError(f"{label} must be lowercase")
    return value


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class HermesPinnedSource:
    repository: str
    release: str
    tag: str
    commit: str
    tree: str
    run_agent_sha256: str
    license_sha256: str
    archive_sha256: str
    license: str = "MIT"

    def __post_init__(self) -> None:
        if self.repository != "NousResearch/hermes-agent":
            raise HermesConfigurationError("Hermes repository identity is not the accepted upstream")
        if not self.release or not self.tag:
            raise HermesConfigurationError("Hermes release and tag must be explicit")
        _hex_digest(self.commit, length=40, label="commit")
        _hex_digest(self.tree, length=40, label="tree")
        _hex_digest(self.run_agent_sha256, length=64, label="run_agent_sha256")
        _hex_digest(self.license_sha256, length=64, label="license_sha256")
        _hex_digest(self.archive_sha256, length=64, label="archive_sha256")
        if self.license != "MIT":
            raise HermesConfigurationError("only the provenance-reviewed MIT upstream is accepted")

    def to_dict(self) -> dict[str, str]:
        return {str(key): str(value) for key, value in asdict(self).items()}

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "HermesPinnedSource":
        required = {
            "repository",
            "release",
            "tag",
            "commit",
            "tree",
            "run_agent_sha256",
            "license_sha256",
            "archive_sha256",
            "license",
        }
        if set(value) != required:
            raise HermesConfigurationError("Hermes source record fields are not exact")
        return cls(**{key: str(value[key]) for key in required})


DEFAULT_HERMES_SOURCE = HermesPinnedSource(
    repository="NousResearch/hermes-agent",
    release="v0.20.5",
    tag="v2026.8.19",
    commit="fcbd1076a93841fa88855acce810e342a5b78101",
    tree="cc9f987a403a1d02b8b17cc527a57b54402e864b",
    run_agent_sha256="b8e0244cfdbdce9328040d92adb9b89d78351000ee88bafae35d71b3e33fb8a1",
    license_sha256="821556e6336796450ab852d375117b48a4887e71d255794fd6318d99982a5ab6",
    archive_sha256="b7a86a237c11b4b5b439c6b803cc9837f1eab4861c3470a0b7f00651e18a5654",
)


@dataclass(frozen=True)
class HermesCheckoutEvidence:
    checkout_root: str
    commit: str
    tree: str
    run_agent_sha256: str
    license_sha256: str
    clean: bool
    digest: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class HermesSandboxProfile:
    """Outer containment command and immutable runtime bounds."""

    command_prefix: tuple[str, ...]
    network_mode: str = "loopback-only"
    max_iterations: int = 24
    max_wall_seconds: float = 600.0
    max_tool_calls: int = 48
    max_output_bytes: int = 4 * 1024 * 1024
    test_only_uncontained: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.command_prefix, tuple) or any(
            not isinstance(part, str) or not part for part in self.command_prefix
        ):
            raise HermesConfigurationError("sandbox command prefix must be an immutable string tuple")
        if not self.command_prefix and not self.test_only_uncontained:
            raise HermesConfigurationError("production Hermes execution requires an outer sandbox command")
        if self.network_mode not in {"none", "loopback-only", "declared-egress"}:
            raise HermesConfigurationError("unsupported Hermes network mode")
        if not 1 <= self.max_iterations <= 512:
            raise HermesConfigurationError("max_iterations is outside the accepted range")
        if not 0.1 <= self.max_wall_seconds <= 86_400:
            raise HermesConfigurationError("max_wall_seconds is outside the accepted range")
        if not 0 <= self.max_tool_calls <= 4_096:
            raise HermesConfigurationError("max_tool_calls is outside the accepted range")
        if not 1_024 <= self.max_output_bytes <= 64 * 1024 * 1024:
            raise HermesConfigurationError("max_output_bytes is outside the accepted range")

    def to_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["command_prefix"] = list(self.command_prefix)
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "HermesSandboxProfile":
        exact = {
            "command_prefix",
            "network_mode",
            "max_iterations",
            "max_wall_seconds",
            "max_tool_calls",
            "max_output_bytes",
            "test_only_uncontained",
        }
        if set(value) != exact:
            raise HermesConfigurationError("Hermes sandbox profile fields are not exact")
        prefix = value["command_prefix"]
        if not isinstance(prefix, list) or any(not isinstance(item, str) for item in prefix):
            raise HermesConfigurationError("sandbox command_prefix must be a list of strings")
        return cls(
            command_prefix=tuple(prefix),
            network_mode=str(value["network_mode"]),
            max_iterations=int(value["max_iterations"]),
            max_wall_seconds=float(value["max_wall_seconds"]),
            max_tool_calls=int(value["max_tool_calls"]),
            max_output_bytes=int(value["max_output_bytes"]),
            test_only_uncontained=bool(value["test_only_uncontained"]),
        )


@dataclass(frozen=True)
class HermesRuntimeConfig:
    checkout_root: str
    python_executable: str
    source: HermesPinnedSource = DEFAULT_HERMES_SOURCE
    sandbox: HermesSandboxProfile = field(
        default_factory=lambda: HermesSandboxProfile(command_prefix=(), test_only_uncontained=True)
    )
    model: str = ""
    provider: str = ""
    base_url: str = ""
    api_key_env: str = ""
    ordinary_env_allowlist: tuple[str, ...] = (
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "LD_LIBRARY_PATH",
        "DYLD_LIBRARY_PATH",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "NO_PROXY",
    )
    secret_env_allowlist: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.checkout_root or not self.python_executable:
            raise HermesConfigurationError("checkout_root and python_executable are required")
        for name in (*self.ordinary_env_allowlist, *self.secret_env_allowlist):
            if not isinstance(name, str) or not name or "=" in name or "\x00" in name:
                raise HermesConfigurationError("environment allowlist contains an invalid name")
        if len(set(self.ordinary_env_allowlist)) != len(self.ordinary_env_allowlist):
            raise HermesConfigurationError("ordinary environment allowlist contains duplicates")
        if len(set(self.secret_env_allowlist)) != len(self.secret_env_allowlist):
            raise HermesConfigurationError("secret environment allowlist contains duplicates")
        if set(self.ordinary_env_allowlist) & set(self.secret_env_allowlist):
            raise HermesConfigurationError("ordinary and secret environment allowlists must be disjoint")
        if self.api_key_env and self.api_key_env not in self.secret_env_allowlist:
            raise HermesConfigurationError("api_key_env must be present in the secret allowlist")

    def to_metadata(self) -> dict[str, object]:
        return {
            "adapter_id": HERMES_ADAPTER_ID,
            "adapter_version": HERMES_ADAPTER_VERSION,
            "checkout_root": self.checkout_root,
            "python_executable": self.python_executable,
            "source": self.source.to_dict(),
            "sandbox": self.sandbox.to_dict(),
            "model": self.model,
            "provider": self.provider,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "ordinary_env_allowlist": list(self.ordinary_env_allowlist),
            "secret_env_allowlist": list(self.secret_env_allowlist),
        }

    @classmethod
    def from_metadata(cls, value: Mapping[str, object]) -> "HermesRuntimeConfig":
        exact = {
            "adapter_id",
            "adapter_version",
            "checkout_root",
            "python_executable",
            "source",
            "sandbox",
            "model",
            "provider",
            "base_url",
            "api_key_env",
            "ordinary_env_allowlist",
            "secret_env_allowlist",
        }
        if set(value) != exact:
            raise HermesConfigurationError("Hermes runtime metadata fields are not exact")
        if value["adapter_id"] != HERMES_ADAPTER_ID or value["adapter_version"] != HERMES_ADAPTER_VERSION:
            raise HermesConfigurationError("Hermes adapter identity/version mismatch")
        source = value["source"]
        sandbox = value["sandbox"]
        ordinary = value["ordinary_env_allowlist"]
        secrets = value["secret_env_allowlist"]
        if not isinstance(source, Mapping) or not isinstance(sandbox, Mapping):
            raise HermesConfigurationError("Hermes source and sandbox metadata must be objects")
        if not isinstance(ordinary, list) or any(not isinstance(item, str) for item in ordinary):
            raise HermesConfigurationError("ordinary_env_allowlist must be a string list")
        if not isinstance(secrets, list) or any(not isinstance(item, str) for item in secrets):
            raise HermesConfigurationError("secret_env_allowlist must be a string list")
        return cls(
            checkout_root=str(value["checkout_root"]),
            python_executable=str(value["python_executable"]),
            source=HermesPinnedSource.from_dict(source),
            sandbox=HermesSandboxProfile.from_dict(sandbox),
            model=str(value["model"]),
            provider=str(value["provider"]),
            base_url=str(value["base_url"]),
            api_key_env=str(value["api_key_env"]),
            ordinary_env_allowlist=tuple(ordinary),
            secret_env_allowlist=tuple(secrets),
        )


def _run_git(checkout: Path, git_executable: str, *args: str) -> str:
    completed = subprocess.run(
        [git_executable, "-C", str(checkout), *args],
        check=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=30,
    )
    if completed.returncode != 0:
        raise HermesConfigurationError(f"Hermes checkout git verification failed: {' '.join(args)}")
    return completed.stdout.strip()


def verify_hermes_checkout(
    checkout_root: str | Path,
    *,
    source: HermesPinnedSource = DEFAULT_HERMES_SOURCE,
    git_executable: str = "git",
) -> HermesCheckoutEvidence:
    root = Path(checkout_root).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise HermesConfigurationError("Hermes checkout root is not a directory")
    run_agent = root / "run_agent.py"
    license_file = root / "LICENSE"
    if not run_agent.is_file() or not license_file.is_file():
        raise HermesConfigurationError("Hermes checkout is missing run_agent.py or LICENSE")
    commit = _run_git(root, git_executable, "rev-parse", "HEAD")
    tree = _run_git(root, git_executable, "rev-parse", "HEAD^{tree}")
    status = _run_git(root, git_executable, "status", "--porcelain=v1", "--untracked-files=all")
    run_digest = file_sha256(run_agent)
    license_digest = file_sha256(license_file)
    if commit != source.commit:
        raise HermesConfigurationError("Hermes checkout commit does not match the pinned source")
    if tree != source.tree:
        raise HermesConfigurationError("Hermes checkout tree does not match the pinned source")
    if run_digest != source.run_agent_sha256:
        raise HermesConfigurationError("Hermes run_agent.py digest does not match the pinned source")
    if license_digest != source.license_sha256:
        raise HermesConfigurationError("Hermes LICENSE digest does not match the pinned source")
    if status:
        raise HermesConfigurationError("Hermes checkout must be clean")
    payload = "\n".join((str(root), commit, tree, run_digest, license_digest, "clean"))
    return HermesCheckoutEvidence(
        checkout_root=str(root),
        commit=commit,
        tree=tree,
        run_agent_sha256=run_digest,
        license_sha256=license_digest,
        clean=True,
        digest=sha256(payload.encode("utf-8")).hexdigest(),
    )


def ensure_disjoint_roots(*roots: str | Path) -> tuple[Path, ...]:
    resolved = tuple(Path(root).expanduser().resolve(strict=False) for root in roots)
    for index, left in enumerate(resolved):
        for right in resolved[index + 1 :]:
            if left == right or left in right.parents or right in left.parents:
                raise HermesConfigurationError("Hermes checkout, runtime HOME and task workspace must be disjoint")
    return resolved


def build_sanitized_environment(
    config: HermesRuntimeConfig,
    *,
    runtime_root: Path,
    source_environment: Mapping[str, str] | None = None,
) -> dict[str, str]:
    source_environment = os.environ if source_environment is None else source_environment
    result: dict[str, str] = {}
    for name in (*config.ordinary_env_allowlist, *config.secret_env_allowlist):
        value = source_environment.get(name)
        if value is not None:
            result[name] = value
    runtime_root = runtime_root.resolve(strict=True)
    home = runtime_root / "home"
    temporary = runtime_root / "tmp"
    hermes_home = runtime_root / "hermes-home"
    for directory in (home, temporary, hermes_home):
        directory.mkdir(parents=True, exist_ok=True)
    result.update(
        {
            "HOME": str(home),
            "USERPROFILE": str(home),
            "HERMES_HOME": str(hermes_home),
            "TMP": str(temporary),
            "TEMP": str(temporary),
            "TMPDIR": str(temporary),
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
            "HERMES_DISABLE_MEMORY": "1",
            "HERMES_DISABLE_LEARNING": "1",
            "HERMES_DISABLE_GATEWAY": "1",
            "HERMES_DISABLE_CRON": "1",
            "HERMES_DISABLE_CHECKPOINTS": "1",
            "HERMES_EPHEMERAL": "1",
        }
    )
    return result


def canonical_environment_names(config: HermesRuntimeConfig) -> tuple[str, ...]:
    return tuple(sorted(set(config.ordinary_env_allowlist) | set(config.secret_env_allowlist)))
