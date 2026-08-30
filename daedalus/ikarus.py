# SPDX-FileCopyrightText: 2026 Kaya Yesilyurt
# SPDX-License-Identifier: Apache-2.0

"""Backward-compatible import surface for the renamed Kairos scheduler.

Existing integrations historically imported ``daedalus.ikarus.Ikarus``.  The
conversation persona still uses the Ikarus name, while scheduling now lives in
``daedalus.kairos``.  Keep the old API working during that migration.
"""

from .kairos.scheduler import (
    Assignment,
    DEFAULT_AVAILABILITY,
    FREE_LANES,
    KairosScheduler,
    _paths_overlap,
    main,
)

Ikarus = KairosScheduler
MetronScheduler = KairosScheduler  # pre-rename name, still importable

__all__ = [
    "Assignment",
    "DEFAULT_AVAILABILITY",
    "FREE_LANES",
    "Ikarus",
    "KairosScheduler",
    "MetronScheduler",
    "_paths_overlap",
    "main",
]


if __name__ == "__main__":
    main()
