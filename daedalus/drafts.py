# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Compatibility wrapper for :mod:`daedalus.kairos.drafts`."""

from .kairos.drafts import (
    DRAFT_DIR,
    ROOT,
    apply_payload,
    delete_draft,
    get_draft,
    list_drafts,
    save_draft,
    set_status,
)

__all__ = [
    "DRAFT_DIR",
    "ROOT",
    "apply_payload",
    "delete_draft",
    "get_draft",
    "list_drafts",
    "save_draft",
    "set_status",
]
