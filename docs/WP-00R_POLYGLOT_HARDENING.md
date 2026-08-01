# WP-00R — Fourfold hardening and polyglot extractor boundary

Status: active review/hardening packet  
Parent: WP-00  
Gate: 0 — Canonical Kernel

## Purpose

Close the gap between the bounded Python wiki specimen and a future repository
compiler without pretending suffix discovery is semantic extraction. The first
polyglot slice defines immutable adapter contracts and deterministic discovery
for Python, Rust, Java, Kotlin, Scala, C, C++, ROOT macros and ROOT files, Go,
C#, JavaScript/TypeScript, Markdown, JSON Schema, CSV, SQL, HDF5, and Parquet.

ROOT is explicitly split into three concerns:

1. C++ source is extracted by the C++ adapter;
2. uppercase `.C` files are ROOT/Cling macro candidates;
3. `.root` files belong to the Data Plane and require an uproot/PyROOT adapter.

A C++ file is not labelled ROOT merely because it has a C++ suffix. ROOT
framework use must be independently observed from includes, dictionaries,
LinkDef files, CMake configuration, runtime metadata, or binary structure.

## Authority boundary

- discovery selects a possible adapter;
- an extractor emits staged observations and diagnostics;
- deterministic verification decides which observations enter the Forest;
- Fourfold remains a projection over the verified Forest;
- no extractor result, LLM rationale, suffix match, or parser success is a
  verified cross-plane binding by itself.

## Initial adapter order

1. Python AST adapter hardening;
2. Rust adapter using tree-sitter-rust and optional rust-analyzer/SCIP evidence;
3. Java adapter using tree-sitter-java plus optional JDT/JavaParser evidence;
4. C/C++ adapter using tree-sitter-c/cpp plus optional clangd/Clang AST evidence;
5. ROOT layer using C++ evidence, LinkDef/dictionary metadata, and uproot/PyROOT
   binary inspection behind an optional dependency boundary;
6. generic data and knowledge adapters.

## Large-repository benchmark corpus

Pinned bounded slices are used for pull-request and weekly probes:

- `tokio-rs/tokio` for advanced Rust;
- `spring-projects/spring-framework` for large modular Java;
- `root-project/root` for C++, ROOT dictionaries, PyROOT, and ROOT data concepts;
- `apache/arrow` for a large polyglot data system.

The current probe records tracked paths, supported files and bytes, language
counts, and a deterministic repository-shape digest. Its assurance is
`discovery-only`. Semantic extraction, cross-plane verification, and full
Fourfold publication are later acceptance stages.

## Required next packets

### WP-00R-A — source identity and security

- bind source bytes to Git tree/content-bundle identity;
- reject duplicate JSON keys;
- add descriptor-safe or immutable-bundle reads;
- enforce resource limits;
- centralize path and Markdown-target containment;
- add typed diagnostics and compile receipts.

### WP-00R-B — semantic contracts

- define plane completeness relative to declared coverage and extractor set;
- define evidence records and assurance vocabulary;
- define node ID grammar and repository scoping;
- define relation registry;
- verify Forest/Fourfold equivalence.

### WP-00R-C — parser adapters

- Python import-aware dataclass and annotation extraction;
- Rust modules, structs, enums, traits, impls, generics, Cargo workspace graph;
- Java packages, classes, records, interfaces, annotations, generics, Gradle/Maven graph;
- C/C++ namespaces, classes, structs, templates, macros, includes, CMake graph;
- ROOT TObject inheritance, dictionaries, LinkDef, TTree/RNTuple schemas, ROOT files;
- Markdown AST, JSON Schema dialects, CSV dialects, SQL and HDF5 adapters.

### WP-00R-D — validation

- property and mutation tests;
- malformed/hostile fixture corpus;
- crash, cancellation, stale-cache, and mixed-revision injection;
- installed-wheel and full-suite CI;
- pinned large-repository semantic benchmark once each adapter exists.

## Promotion rule

The parent PR remains draft. This packet does not authorize WP-01. Independent
architecture/security review and an explicit owner decision remain mandatory.
