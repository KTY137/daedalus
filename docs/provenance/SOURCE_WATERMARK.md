# Daedalus source watermark

Daedalus first-party source carries this SPDX preamble:

```text
SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
SPDX-License-Identifier: Apache-2.0
```

The authoritative rollout scope is
`provenance/source-watermark-policy.json`. It intentionally excludes imported
or separately licensed material, generated bundles, frozen experiments,
byte-exact fixtures, retained evidence, archives, and runtime state. An
exclusion is not an ownership claim and does not remove any existing notice.
Mixed-provenance `daedalus/kairos/archive.py` retains its existing upstream
OpenEvolve attribution without a new whole-file ownership line.

`NOTICE` supplies the repository-level attribution. The signed snapshot under
`provenance/source-watermark-manifest.json` records the SHA-256 of every source
file covered during the rollout. It is evidence for that snapshot, not an
access-control mechanism and not a claim that a removable text marker prevents
copying.

## Commands

```console
python tools/source_provenance.py check
python tools/source_provenance.py render-manifest --target-ref main --base-revision <sha>
python tools/source_provenance.py verify-manifest --target-ref main --base-revision <sha>
```

`check`, `render-manifest`, and `verify-manifest` are read-only. The renderer
reads the prospective staged Git blobs and emits deterministic JSON to stdout;
it never writes a repository path. An owner-approved repository-write path must
capture that output and create the detached signature. There is deliberately
no shipped `apply` or arbitrary `--output` command outside the canonical effect
boundary.

The detached SSH signature is verified with the dedicated normal source-
provenance signer listed in `provenance/source-watermark-allowed-signers` and
namespace `daedalus-source-provenance`. The privileged Daedalus promotion key
is deliberately not accepted for this purpose:

```console
ssh-keygen -Y verify -f provenance/source-watermark-allowed-signers \
  -I kaya-yesilyurt@daedalus \
  -n daedalus-source-provenance -s provenance/source-watermark-manifest.json.sig \
  < provenance/source-watermark-manifest.json
```

New in-scope source is rejected by the source-provenance workflow until it
carries the exact preamble. Historical commits, tags, archives, forks, and
clones are not rewritten.
