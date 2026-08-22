# Verification: v-markdown-parser

Source file markdown-parser.py not provided; unable to verify any claims. All claims are UNDECIDABLE.

## Verdicts

- UNDECIDABLE: Source file missing. Claim: Reference definitions and autolinks may be matched on raw lines, not filtered by _content_lines.
- UNDECIDABLE: Source file missing. Claim: Inline code stripping regex fails on nested backticks (e.g., `` `[[Note]]` ``).
- UNDECIDABLE: Source file missing. Claim: _INLINE_CODE regex does not handle backtick escapes or multiple backtick sequences correctly.
- UNDECIDABLE: Source file missing. Claim: No test coverage for adversarial inputs like nested brackets, pipes in aliases, or embeds inside code fences.
- UNDECIDABLE: Source file missing. Claim: HTML comments are not stripped; links inside comments are parsed.
- UNDECIDABLE: Source file missing. Claim: Add unit tests for adversarial inputs.
- UNDECIDABLE: Source file missing. Claim: Move reference definition and autolink matching inside _content_lines.
- UNDECIDABLE: Source file missing. Claim: Fix inline code stripping for nested backticks and multiple sequences.
- UNDECIDABLE: Source file missing. Claim: Consider using a proper Markdown AST parser.
- UNDECIDABLE: Source file missing. Claim: Add HTML comment stripping before link parsing.
