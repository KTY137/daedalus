"""Deterministic source-language and data-format discovery registry.

Discovery is intentionally weaker than semantic extraction. A detected suffix
identifies which adapter may inspect an artifact; it does not establish AST,
type, data-lineage, or knowledge claims.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from .contracts import LanguageSpec


@dataclass(frozen=True)
class LanguageDetection:
    language_id: str
    artifact_kind: str
    confidence: str
    framework_hints: tuple[str, ...] = ()


LANGUAGE_SPECS: tuple[LanguageSpec, ...] = (
    LanguageSpec("python", (".py", ".pyi"), "text", ("code", "type")),
    LanguageSpec("rust", (".rs",), "text", ("code", "type")),
    LanguageSpec("java", (".java",), "text", ("code", "type")),
    LanguageSpec("kotlin", (".kt", ".kts"), "text", ("code", "type")),
    LanguageSpec("scala", (".scala", ".sc"), "text", ("code", "type")),
    LanguageSpec("cpp", (".cc", ".cpp", ".cxx", ".hh", ".hpp", ".hxx"), "text", ("code", "type")),
    LanguageSpec("c", (".c",), "text", ("code", "type")),
    LanguageSpec("c-cpp-header", (".h",), "text", ("code", "type")),
    LanguageSpec("root-macro", (".C",), "text", ("code", "type"), ("root",)),
    LanguageSpec("root-binary", (".root",), "binary", ("data",), ("root",)),
    LanguageSpec("go", (".go",), "text", ("code", "type")),
    LanguageSpec("csharp", (".cs",), "text", ("code", "type")),
    LanguageSpec("typescript", (".ts", ".tsx"), "text", ("code", "type")),
    LanguageSpec("javascript", (".js", ".jsx", ".mjs", ".cjs"), "text", ("code",)),
    LanguageSpec("markdown", (".md", ".mdx"), "text", ("knowledge",)),
    LanguageSpec("json", (".json",), "text", ("data", "knowledge")),
    LanguageSpec("json-schema", (".schema.json",), "text", ("data",)),
    LanguageSpec("csv", (".csv",), "text", ("data",)),
    LanguageSpec("sql", (".sql",), "text", ("code", "data")),
    LanguageSpec("hdf5", (".h5", ".hdf5"), "binary", ("data",)),
    LanguageSpec("parquet", (".parquet",), "binary", ("data",)),
)

_SUFFIX_INDEX = tuple(
    sorted(
        ((extension, spec) for spec in LANGUAGE_SPECS for extension in spec.extensions),
        key=lambda item: (-len(item[0]), item[0], item[1].language_id),
    )
)

_BUILD_FILES: dict[str, LanguageDetection] = {
    "Cargo.toml": LanguageDetection("rust-build", "configuration", "exact"),
    "Cargo.lock": LanguageDetection("rust-build", "configuration", "exact"),
    "pom.xml": LanguageDetection("java-build", "configuration", "exact"),
    "build.gradle": LanguageDetection("java-build", "configuration", "exact"),
    "build.gradle.kts": LanguageDetection("kotlin-build", "configuration", "exact"),
    "settings.gradle": LanguageDetection("java-build", "configuration", "exact"),
    "settings.gradle.kts": LanguageDetection("kotlin-build", "configuration", "exact"),
    "CMakeLists.txt": LanguageDetection("cmake", "configuration", "exact"),
    "Makefile": LanguageDetection("make", "configuration", "exact"),
}


def detect_language(path: str) -> LanguageDetection | None:
    """Return a conservative path-based detection or ``None``.

    ``.root`` is a binary data format. ROOT C++ source remains C++ unless a
    framework-aware extractor independently observes ROOT APIs. Uppercase
    ``.C`` is retained as the conventional ROOT/Cling macro form.
    """

    if not isinstance(path, str) or not path or "\\" in path or "\x00" in path:
        raise ValueError("path must be a non-empty repository-relative POSIX path")
    pure = PurePosixPath(path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("path must be normalized and repository-relative")

    build = _BUILD_FILES.get(pure.name)
    if build is not None:
        return build

    for suffix, spec in _SUFFIX_INDEX:
        if path.endswith(suffix):
            return LanguageDetection(
                spec.language_id,
                spec.artifact_kind,
                "suffix",
                spec.framework_hints,
            )
    return None


def registered_language_ids() -> tuple[str, ...]:
    ids = {spec.language_id for spec in LANGUAGE_SPECS}
    ids.update(item.language_id for item in _BUILD_FILES.values())
    return tuple(sorted(ids))
