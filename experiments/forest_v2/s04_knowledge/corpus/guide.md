# Guide

## Resolution rules

Each line below is one code reference, and each lands in a different stage of
the waterfall.

Exact path, line in range: `pkg/spine/attempt.py:12`
Exact path, line past end of file: `pkg/spine/attempt.py:900`
Path that does not exist: `pkg/spine/ghost.py:3`
Bare basename, unique: `solo.py:5`
Bare basename, two candidates: `report.py:5`
Package-relative, unique suffix: `spine/attempt.py:12`
Package-relative, two candidates: `mod/thing.py:5`
