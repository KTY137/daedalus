"""A nested package, so at least one fixture import is dotted rather than flat.

Present so ``pkg_nested.inner_types`` exercises the multi-segment dotted-name
path in ``_PyNaming``/``resolve_python_imports`` instead of only the top-level
single-segment case.
"""
