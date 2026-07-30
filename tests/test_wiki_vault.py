"""
Adversarial tests for the vault path validator (vault_rel). The function decides 
which files a wiki write may touch and must resist Windows-specific path attacks. 

The tests verify that vault_rel refuses:
- 8.3 short names (e.g., PROGRA~1)
- UNC paths (\\\\server\\share\\...)
- Drive-relative paths (C:path)
- Unicode normalisation collisions (e.g., using ONE DOT LEADER to produce "..")
- Case-insensitive duplicates that would escape the vault

Every test also asserts the function never raises; any exception will cause the test to fail.
If an attack is NOT refused, the test fails – that is the reportable finding.

We cannot test NTFS junction points, symbolic links, or mount points because
vault_rel operates on path strings, not filesystem objects. Those are outside scope.
"""

import pytest
from daedalus.wiki_vault import vault_rel


# -------------------------------------------------------------------
# Helpers – adjust if the real vault_rel takes additional arguments
# -------------------------------------------------------------------

def call_vault_rel(path: str):
    """Invoke vault_rel with the given path and return its result.
    This wrapper ensures the function doesn't raise; otherwise the test fails.
    """
    try:
        return vault_rel(path)
    except Exception as e:
        pytest.fail(f"vault_rel raised {e!r} for path {path!r}")


# -------------------------------------------------------------------
# Paths that MUST be allowed
# -------------------------------------------------------------------

def test_safe_relative_path():
    """A plain relative path inside the vault must be accepted."""
    result = call_vault_rel("page/file.txt")
    assert result is not None, "Expected an accepted (non-None) result"
    assert isinstance(result, str)
    # The returned path must not contain upward traversal
    assert ".." not in result, "Returned path contains '..'"


def test_safe_absolute_path_within_vault():
    """An absolute path exactly within the vault root must be accepted."""
    result = call_vault_rel("C:\\wiki_vault\\page\\file.txt")
    assert result is not None


# -------------------------------------------------------------------
# Refusal tests – each attack must be rejected (return None)
# -------------------------------------------------------------------

def test_refuse_short_name_path():
    """8.3 short names like PROGRA~1 are ambiguous on Windows;
    reject them because they could bypass vault-bound checks.
    """
    result = call_vault_rel("C:\\PROGRA~1\\file.txt")
    assert result is None, "8.3 short name path was NOT refused"


def test_refuse_unc_path():
    """UNC paths (\\\\server\\share) point to remote or special locations,
    which must never be written."""
    result = call_vault_rel("\\\\server\\share\\file.txt")
    assert result is None, "UNC path was NOT refused"


def test_refuse_drive_relative_path():
    """Drive-relative paths (C:folder) are resolved relative to the
    current directory on that drive, which could escape the vault."""
    result = call_vault_rel("C:page\\file.txt")
    assert result is None, "Drive-relative path was NOT refused"


def test_refuse_unicode_normalization_collision():
    """Using characters that normalise to '.' (e.g., U+2024 ONE DOT LEADER)
    could create a '..' after normalisation, escaping the vault.
    The function MUST normalise (or reject) such tricks."""
    # U+2024 normalises to '.' under NFKC, turning into '..'
    tricky = "C:\\wiki_vault\\․․\\etc\\passwd"
    result = call_vault_rel(tricky)
    assert result is None, "Unicode normalisation traversal was NOT refused"


def test_refuse_case_insensitive_duplicate():
    """Windows treats paths case-insensitively.  A path that uses
    different casing for the vault name may bypass string comparisons
    and escape.  The validator must refuse such misdirections."""
    tricky = "C:\\Vault\\..\\windows\\system32\\cmd.exe"
    result = call_vault_rel(tricky)
    assert result is None, "Case-insensitive traversal was NOT refused"


# -------------------------------------------------------------------
# Robustness: the function must never raise, no matter how weird the input
# -------------------------------------------------------------------

def test_no_exception_on_bizarre_inputs():
    """Smoke-test with a variety of weird but valid-looking path strings.
    If any path causes an unhandled exception the test will fail."""
    inputs = [
        "",                           # empty
        "..",                         # plain parent
        "C:",                         # drive letter only
        "C:\\wiki_vault\\..\\..",    # multiple traversal
        "C:\\wiki_vault\\nul\\file",  # reserved name
        "\\\\?\\C:\\wiki_vault\\f",   # extended-length path
        "C:\\wiki_vault\\" + "a"*1000, # very long component
        "C:\\wiki_vault\\file\\.\\",   # trailing dot-space
        "\0",                         # null byte may be handled
    ]
    for p in inputs:
        # call_vault_rel already asserts no raise; we can also assert result is either str or None
        r = call_vault_rel(p)
        assert r is None or isinstance(r, str), f"Unexpected return type for {p!r}"
