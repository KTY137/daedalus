"""Frozen launcher for the canonical desktop-sidecar owner.

All bootstrap effects live in ``daedalus.interfaces.desktop.sidecar`` so the
production registry can inspect and admit them. This file only provides the
PyInstaller executable tail and backwards-compatible helper imports.
"""
from daedalus.interfaces.desktop.sidecar import (
    DESKTOP_PROJECT_COMMENT,
    DESKTOP_PROJECT_SCHEMA,
    bundled_root,
    main,
    prepare_runtime,
)


if __name__ == "__main__":
    # Frozen Windows multiprocessing children re-enter this executable with
    # ``--multiprocessing-fork``. Dispatch them before our web-API argparse sees
    # those private arguments.
    import multiprocessing

    multiprocessing.freeze_support()
    main()
