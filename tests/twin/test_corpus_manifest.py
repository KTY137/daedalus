from __future__ import annotations

import json
from pathlib import Path

import pytest

from daedalus.twin.corpus import (
    CorpusManifest,
    CorpusManifestError,
    CorpusRepository,
    assert_expected_revisions,
    review_blockers,
)

MANIFEST = Path(__file__).resolve().parents[2] / "configs" / "corpus" / "gate2-pilot-v1.json"


def load_manifest() -> CorpusManifest:
    return CorpusManifest.from_json_bytes(MANIFEST.read_bytes())


def test_gate2_pilot_is_canonical_revision_pinned_and_honest_about_review() -> None:
    manifest = load_manifest()
    assert manifest.to_json_bytes() == MANIFEST.read_bytes()
    assert len(manifest.digest) == 64
    assert tuple(item.repository_id for item in manifest.repositories) == (
        "apache-arrow",
        "cern-root",
        "spring-framework",
        "tokio",
    )
    assert all(len(item.source_revision) == 40 for item in manifest.repositories)
    assert not manifest.closed_for_gate2
    assert review_blockers(manifest) == (
        "apache-arrow:license-review-declared",
        "cern-root:license-review-declared",
        "spring-framework:license-review-declared",
        "tokio:license-review-declared",
    )


def test_exact_observed_revisions_are_required() -> None:
    manifest = load_manifest()
    observed = {item.repository_id: item.source_revision for item in manifest.repositories}
    assert_expected_revisions(manifest, observed)

    stale = dict(observed)
    stale["tokio"] = "0" * 40
    with pytest.raises(CorpusManifestError, match="stale or substituted"):
        assert_expected_revisions(manifest, stale)

    missing = dict(observed)
    missing.pop("tokio")
    with pytest.raises(CorpusManifestError, match="IDs do not match"):
        assert_expected_revisions(manifest, missing)


def test_manifest_refuses_noncanonical_and_malformed_input() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))

    pretty = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    with pytest.raises(CorpusManifestError, match="canonical JSON"):
        CorpusManifest.from_json_bytes(pretty)

    payload["repositories"][0]["source_revision"] = "main"
    with pytest.raises(CorpusManifestError, match="40-hex"):
        CorpusManifest.from_dict(payload)

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["repositories"][0]["include_prefixes"] = ["../outside"]
    with pytest.raises(CorpusManifestError, match="stay inside"):
        CorpusManifest.from_dict(payload)

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["repositories"][0]["repository_url"] = "http://github.com/apache/arrow.git"
    with pytest.raises(CorpusManifestError, match="HTTPS"):
        CorpusManifest.from_dict(payload)

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["repositories"][0]["unknown"] = True
    with pytest.raises(CorpusManifestError, match="unknown repository fields"):
        CorpusManifest.from_dict(payload)


def test_reviewed_status_requires_content_addressed_evidence() -> None:
    manifest = load_manifest()
    item = manifest.repositories[0]

    with pytest.raises(CorpusManifestError, match="require sha256"):
        CorpusRepository(
            repository_id=item.repository_id,
            repository_url=item.repository_url,
            source_revision=item.source_revision,
            include_prefixes=item.include_prefixes,
            language_ids=item.language_ids,
            license_spdx=item.license_spdx,
            license_path=item.license_path,
            review_state="reviewed",
            review_evidence=None,
        )

    reviewed = CorpusRepository(
        repository_id=item.repository_id,
        repository_url=item.repository_url,
        source_revision=item.source_revision,
        include_prefixes=item.include_prefixes,
        language_ids=item.language_ids,
        license_spdx=item.license_spdx,
        license_path=item.license_path,
        review_state="reviewed",
        review_evidence="sha256:" + "a" * 64,
    )
    assert reviewed.review_state == "reviewed"


def test_repository_order_and_identity_substitution_refuse() -> None:
    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["repositories"].reverse()
    with pytest.raises(CorpusManifestError, match="sorted"):
        CorpusManifest.from_dict(payload)

    payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
    payload["repositories"][1]["repository_url"] = payload["repositories"][0]["repository_url"]
    with pytest.raises(CorpusManifestError, match="unique"):
        CorpusManifest.from_dict(payload)
