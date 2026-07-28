"""Compatibility CLI for :mod:`daedalus.kairos.orchestrate`."""

from .kairos.orchestrate import _infer_paths, main, prepare_task

__all__ = ["prepare_task"]


if __name__ == "__main__":
    main()
