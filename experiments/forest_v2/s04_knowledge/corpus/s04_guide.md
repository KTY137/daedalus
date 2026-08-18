# Guide

## Resolution rules

Each line below is one code reference, and each lands in a different stage of
the waterfall.

Exact path, line in range: `pkg/spine/s04_attempt.py:12`
Exact path, line past end of file: `pkg/spine/s04_attempt.py:900`
Path that does not exist: `pkg/spine/s04_ghost.py:3`
Bare basename, unique: `s04_solo.py:5`
Bare basename, two candidates: `s04_report.py:5`
Package-relative, unique suffix: `spine/s04_attempt.py:12`
Package-relative, two candidates: `s04mod/s04_thing.py:5`
