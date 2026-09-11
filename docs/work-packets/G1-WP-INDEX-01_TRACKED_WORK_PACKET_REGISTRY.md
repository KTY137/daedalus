# G1-WP-INDEX-01 - Tracked Work Packet registry contract

Packet ID: `G1-WP-INDEX-01`
Artifact role: `primary`
Active gate: `1`
Classification: `ALIGNED`
Owner: `repository owner`
Base revision: `151b8d180e321cfba48b4c7d62f9be56579d52a5`
Dependencies: `the frozen Gate-1 archive parent and Master Plan Revision 11`
Promotion: not requested

## Primary acceptance claim

Every Git-tracked artifact under `docs/work-packets/` is represented
exactly once by a deterministic registry. Packet identity groups Markdown and
JSON companions without treating a second artifact as a second packet. The 204
artifacts present at the frozen parent remain byte-for-byte untouched; missing
legacy metadata is represented by the literal string `unknown`.

## Scope

Allowed changes are exactly:

- `configs/schemas/work-packet-index-v1.schema.json`;
- `docs/work-packets/index.json`;
- this Work Packet;
- `tools/index_work_packets.py`; and
- `tests/contracts/test_work_packet_index.py`.

Every other path is forbidden. In particular this packet does not edit or move
historical Work Packets, `runs/`, retained evidence, the Master Plan, its
amendment chain, policy, the Effect Registry, runtime code, generated assets,
or persistent stores.

## Contracts and behavior

`docs/work-packets/index.json` is the sole v1 registry document. Its schema
freezes authority, counts, the exact 204-path legacy baseline, grouped packet
IDs, artifact paths, source metadata, unassigned legacy artifacts,
and the registry artifact itself. The legacy path list is independently bound
to its count, frozen parent revision, and SHA-256 digest.

The checker reads the repository's stage-zero SHA-1 Git index directly. It
accepts only DIRC v2/v3, validates the trailing checksum and every entry and
extension boundary, and refuses split, sparse, conflicted, locked, changing,
or malformed indices. It does not enumerate the working directory and does not
spawn Git, so untracked files are excluded without adding an effectful
entrypoint or changing the Effect Registry digest.

Post-index artifacts must declare a filename-consistent packet ID and an
artifact role. A new packet ID has exactly one `primary` artifact; any number
of `companion` artifacts may share that ID. A primary also declares all frozen
metadata and required Work Packet sections. A new primary may not redefine a
legacy ID. Legacy omissions are not guessed or repaired.

## Acceptance matrix

1. `python tools/index_work_packets.py --check` exits zero only when the
   committed canonical JSON equals a fresh tracked-only measurement.
2. JSON Schema Draft 2020-12 accepts the committed registry and rejects shape,
   authority, path, digest, and enum drift.
3. All 204 parent artifacts remain present and hashed, plus this primary
   artifact; `index.json` is counted separately to avoid a self-hash.
4. Known multi-artifact IDs (`G0-FLT-07A`, `G0-RTC-06Y`, `G0-RTC-07C`, and
   `G0-RTC-07D`) form one group each with all artifact paths retained.
5. Missing or mismatched IDs, incomplete primary metadata or sections,
   duplicate primary definitions, removed legacy paths, malformed Git indices,
   and inconsistent counts fail closed.
6. A deliberately untracked Work Packet-shaped file is ignored; a staged path
   absent from the registry makes `--check` fail.
7. Verification is local and read-only: no provider, network, EDA, promotion,
   repository-write, or runtime invocation is authorized. The test budget is
   five minutes on one supported local Python interpreter.

## Migration and rollback

There is no persistent-data or historical-document migration. CI and later
packet tooling may adopt `--check` after this packet is reviewed; existing
callers and paths remain valid. Rollback removes the schema, registry, checker,
test, and this document together. It does not alter any legacy artifact.

## Evidence expected failures and review

The retained baseline has 204 tracked artifacts: 140 Markdown and 64 JSON,
forming 140 filename-derived packet IDs with two deliberately unassigned
legacy documents. Historical metadata is heterogeneous and is therefore not a
green completeness claim. Values absent from an artifact are `unknown`; where
multiple explicit legacy values conflict, the group value stays `unknown` and
the values remain visible in `metadata_conflicts`.

Expected refusal evidence covers corrupt signatures and checksums, unsupported
versions and mandatory extensions, split/sparse/conflict indices, a concurrent
index lock/change, missing legacy paths, filename/declaration disagreement,
and duplicate new primaries. Independent review should verify tracked-only
coverage, the frozen baseline digest, grouped multi-artifact IDs, exact
`unknown` handling, no hidden directory fallback or subprocess, unchanged
Effect Registry digest, and an exact scoped diff.

Iron Plan: **ALIGNED**
Iron Gate: **1**
Master-plan authority: **Revision 11**
Automatic merge or promotion: **forbidden**
