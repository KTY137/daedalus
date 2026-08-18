# Corpus fixture: THIS FILE IS DELIBERATELY NOT VALID PYTHON.
#
# It exists so the pinned table can assert "unparseable = 1" against a real
# parser failure instead of against a claim.  The earlier probe could not have
# counted a file like this at all: it skipped anything without the literal
# text CREATE TABLE before ever reaching the parser.
#
# It is never imported and never collected: the name does not start with
# `test_`, so a test runner walks past it.
def (
