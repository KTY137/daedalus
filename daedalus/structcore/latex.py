"""
Tier-0 LaTeX extractor using regular expressions.

Guarantee: extracts direct \input, \include, \subfile, \includegraphics,
\bibliography, \label, and \ref uses from a LaTeX string.
Does NOT handle:
- Paths defined via macros (e.g., \def\myfig{...} then \includegraphics{\myfig})
- Conditional includes (\IfFileExists, \includeonly)
- \graphicspath modifications
- \verb, verbatim, and other environments that suppress special‑character meaning.
Comments (introduced by %) are stripped before extraction; the escaped \% is
treated as a literal percent sign and does NOT start a comment.
"""

import re

_PERCENT_PLACEHOLDER = "DAEDALUS_PERCENT_PLACEHOLDER"


def _strip_comments(text: str) -> str:
    """Remove LaTeX comments while respecting escaped percent signs."""
    # Protect \% before removing comments so that \% does not start a comment.
    protected = text.replace(r"\%", _PERCENT_PLACEHOLDER)
    # Replace every comment (from the first unescaped % to end of line) with a space.
    # This preserves line boundaries so that multi‑line arguments can be joined later.
    no_comments = re.sub(r"%.*$", " ", protected, flags=re.MULTILINE)
    # Restore the literal percent signs from \% that were not inside comments.
    restored = no_comments.replace(_PERCENT_PLACEHOLDER, "%")
    # Collapse newlines into spaces because LaTeX treats them as ordinary whitespace
    # and we want to match commands that may span lines.
    single_line = re.sub(r"\n", " ", restored)
    return single_line


def extract(text: str) -> dict[str, list[str]]:
    """
    Extract LaTeX dependency hints from `text`.

    Returns a dictionary with keys:
      "inputs"        – list of file names given to \\input,
      "includes"      – list of file names given to \\include,
      "subfiles"      – list of file names given to \\subfile,
      "graphics"      – list of paths given to \\includegraphics,
      "bibliographies" – list of individual .bib file names given to \\bibliography
                         (commas are split, whitespace trimmed),
      "labels"        – list of label names,
      "refs"          – list of reference keys (\ref, \eqref, etc.).
    All lists preserve the order of appearance in the cleaned text.
    """
    cleaned = _strip_comments(text)

    # We strip whitespace from captured arguments because spaces inside braces
    # that come from line breaks would otherwise be included in the filename.
    inputs = [s.strip() for s in re.findall(r"\\input\s*{([^}]+)}", cleaned)]
    includes = [s.strip() for s in re.findall(r"\\include\s*{([^}]+)}", cleaned)]
    subfiles = [s.strip() for s in re.findall(r"\\subfile\s*{([^}]+)}", cleaned)]
    # \includegraphics may have an optional [key=val] argument; we skip it.
    graphics = [
        s.strip()
        for s in re.findall(
            r"\\includegraphics\s*(?:\[[^\]]*\])?\s*{([^}]+)}", cleaned
        )
    ]
    # \bibliography{file1,file2} – split on commas to give individual files.
    raw_biblios = re.findall(r"\\bibliography\s*{([^}]+)}", cleaned)
    biblios = []
    for entry in raw_biblios:
        biblios.extend(
            part.strip() for part in entry.split(",") if part.strip()
        )
    labels = [s.strip() for s in re.findall(r"\\label\s*{([^}]+)}", cleaned)]
    # Common cross‑reference commands.
    ref_cmds = r"\\ref|\\eqref|\\pageref|\\cref|\\Cref|\\vref|\\Vref|\\autoref"
    refs = [
        s.strip()
        for s in re.findall(
            r"(?:" + ref_cmds + r")\s*{([^}]+)}",
            cleaned,
        )
    ]

    return {
        "inputs": inputs,
        "includes": includes,
        "subfiles": subfiles,
        "graphics": graphics,
        "bibliographies": biblios,
        "labels": labels,
        "refs": refs,
    }


# ---------------------------------------------------------------------------
# Defect demonstrations: tests that expose known failures in the regex extraction.
# Run this file directly to see failures.
# ---------------------------------------------------------------------------


def _assert_equal(expected, actual, message):
    if expected != actual:
        print(f"FAIL: {message}")
        print(f"       expected: {expected!r}")
        print(f"       actual:   {actual!r}")
        import sys
        sys.exit(1)
    else:
        print(f"ok: {message}")


def test_commented_include_inside_braces_phantom():
    # A comment inside braces should suppress the remainder of the line,
    # but if there is a closing brace on the next line it can create a phantom input.
    text = "\\input{some%comment\n}"
    result = extract(text)
    _assert_equal([], result["inputs"],
                  "comment in braces: should not extract phantom input")
    # Explanation: The % comments out everything on the first line, leaving
    #   "\input{some " then newline then "}". After newline collapse we get
    #   "\input{some  }", which matches and extracts "some  " with spaces.
    # This is a phantom edge because the user intended a comment, not an actual file name.


def test_verbatim_yields_phantom_input():
    text = r"\begin{verbatim}\input{file}\end{verbatim}"
    result = extract(text)
    _assert_equal([], result["inputs"],
                  "verbatim: should ignore \\input inside verbatim")
    # The extractor does not know about verbatim; it sees the literal command and extracts "file".
    # This is a phantom edge (false positive).


def test_macro_defined_path_yields_phantom_graphics():
    text = r"\def\myfig{figure1}\includegraphics{\myfig}"
    result = extract(text)
    _assert_equal([], result["graphics"],
                  "macro-defined path: should not extract macro name as graphics")
    # The regex captures everything between braces, giving "\myfig". That is not a real file.


def test_nested_brackets_in_optional_arg_misses_graphics():
    text = r"\includegraphics[draw=red, frametitle={Title with [brackets]}]{file}"
    result = extract(text)
    _assert_equal(["file"], result["graphics"],
                  "nested brackets in optional arg: should still extract the file")
    # The regex for optional arguments uses [^\]]*, which stops at the first ']' it sees.
    # Inside the optional arg, the inner ']' (from the bracket in the title) will terminate
    # the optional argument prematurely, leaving ']{file}' unmatched.
    # This yields a false negative (missed real dependency).


def test_graphicx_graphicpath_not_extracted():
    # \graphicspath should not produce any graphics entry (expected behaviour).
    text = r"\graphicspath{{subdir/}}"
    result = extract(text)
    _assert_equal([], result["graphics"],
                  "\\graphicspath should not be seen as an includegraphics")


if __name__ == "__main__":
    print("Running defect tests...")
    test_commented_include_inside_braces_phantom()
    test_verbatim_yields_phantom_input()
    test_macro_defined_path_yields_phantom_graphics()
    test_nested_brackets_in_optional_arg_misses_graphics()
    test_graphicx_graphicpath_not_extracted()
    print("All defect tests ran – some should fail (see messages).")
